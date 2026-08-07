"""Emission of the data-quality artifacts (RFC 0016 §5.4–§5.6): the silver
pipeline's shape, the reject model, the replay merge, the generated blocking
audits, and the two honest refusals.

The execution assertions — running the SQL, checking quarantine contents,
the conservation law — are the execution tier's (RFC 0016 §6); what is
asserted here is that the artifacts say what the RFC says they say.
"""

from __future__ import annotations

import pytest
from sqlglot import exp, parse_one

from bloomery import Target, build_project_ir, compile_project
from bloomery.emit import ArtifactKind
from bloomery.errors import UnsupportedByTarget
from bloomery.quality import FLAGS_COLUMN, INGESTION_METADATA, OK_COLUMN
from support.compiling import compile_fixture, extract_select, load_fixture

pytestmark = pytest.mark.unit

FIXTURE = "semi_additive_inventory"


def _artifact(path: str, *, dialect: str = "duckdb") -> str:
    artifacts = compile_fixture(FIXTURE, dialect=dialect)
    return next(a.content for a in artifacts if a.path == path)


# ....................... #
# Every silver entity carries the generated columns (§5.5)


@pytest.mark.parametrize("fixture", ["minimal", "ecom_basic", FIXTURE])
def test_every_silver_model_carries_the_two_generated_columns(fixture: str) -> None:
    for artifact in compile_fixture(fixture):
        if not artifact.path.startswith("models/silver/") or artifact.path.endswith("__reject.sql"):
            continue
        select = parse_one(extract_select(artifact.content), dialect="duckdb")
        assert isinstance(select, exp.Select)
        aliases = {projection.alias_or_name for projection in select.expressions}
        assert {FLAGS_COLUMN, OK_COLUMN} <= aliases


def test_a_quality_free_entity_gets_the_constants_and_no_extra_nesting() -> None:
    """The empty collection is what a clean row carries, so the specialization
    is the general form evaluated at compile — and a quality-free golden gains
    two projections, not a subquery."""
    (artifact,) = compile_fixture("minimal")
    body = extract_select(artifact.content)
    assert f"CAST([] AS TEXT[]) AS {FLAGS_COLUMN}" in body
    assert f"TRUE AS {OK_COLUMN}" in body
    assert body.count("SELECT") == 1  # no nesting was introduced


# ....................... #
# The silver pipeline (§5.4)


def test_the_silver_model_renders_the_fixed_pipeline_order() -> None:
    body = extract_select(_artifact("models/silver/inventory_level.sql"))
    # Innermost: extract + transform + the dedupe QUALIFY; then the rules and
    # the routing WHERE; then _quality_ok over the flag column.
    assert body.index("QUALIFY") > body.index("_quality_flags")  # inner is later in the text
    assert "TRY_CAST(day AS DATE) AS stock_date" in body
    assert "ROW_NUMBER() OVER (" in body
    assert "PARTITION BY warehouse_id, stock_date" in body
    assert "ORDER BY _ingested_at DESC, _load_id DESC, _source_row_id DESC" in body
    # Stage 6: the two-way split keeps the rows no quarantine rule fired on.
    assert "WHERE\n    NOT COALESCE(" in body
    assert "ARRAY_LENGTH(_evaluated._quality_flags) = 0 AS _quality_ok" in body


def test_the_flag_pass_is_single_and_carries_only_flag_rules() -> None:
    body = extract_select(_artifact("models/silver/inventory_level.sql"))
    # One array construct, one CASE — the fixture has exactly one flag rule.
    assert body.count("AS _quality_flags") == 1
    assert body.count("stock_level_not_negative") == 1
    # Quarantine-disposition names never enter _quality_flags; they route.
    flags_clause = body.split("AS _quality_flags")[0]
    assert "stock_level_range_min" not in flags_clause


def test_the_ingestion_metadata_rides_through_to_silver() -> None:
    body = extract_select(_artifact("models/silver/inventory_level.sql"))
    for column in INGESTION_METADATA:
        assert f"_evaluated.{column}" in body


# ....................... #
# The reject model (§5.6)


def test_the_reject_model_carries_the_rfc_schema() -> None:
    content = _artifact("models/silver/inventory_level__reject.sql")
    assert "name silver.inventory_level__reject" in content
    # Re-deliveries land on the same row: the identity is the unique key.
    assert "INCREMENTAL_BY_UNIQUE_KEY (unique_key (reject_id))" in content
    select = parse_one(extract_select(content), dialect="duckdb")
    assert isinstance(select, exp.Select)
    assert [projection.alias_or_name for projection in select.expressions] == [
        "reject_id",
        "source_relation",
        "mapping",
        "mapping_version",
        "failed_rules",
        "key_values",
        "raw",
        "_load_id",
        "_ingested_at",
        "_source_row_id",
        "first_seen",
        "last_seen",
        "resolved_at",
    ]


def test_failed_rules_records_flag_level_failures_too() -> None:
    """D18: the reject row is the full account of why a row is not in the
    entity."""
    body = extract_select(_artifact("models/silver/inventory_level__reject.sql"))
    failed = body.split("AS failed_rules")[0]
    assert "stock_level_range_min" in failed  # the rule that diverted the row
    assert "stock_level_not_negative" in failed  # a flag-level failure


def test_redacted_paths_never_reach_raw() -> None:
    body = extract_select(_artifact("models/silver/inventory_level__reject.sql"))
    payload = body.split("AS _raw")[0]
    assert "'on_hand'" in payload  # mapped column, carried
    assert "'_load_id'" in payload  # acknowledged tail, carried
    assert "operator_note" not in payload  # redacted at write time (§5.6)


def test_the_reject_side_is_the_complement_of_the_entity_side() -> None:
    entity = extract_select(_artifact("models/silver/inventory_level.sql"))
    reject = extract_select(_artifact("models/silver/inventory_level__reject.sql"))
    fired = "COALESCE(\n"
    assert fired in entity
    assert fired in reject
    assert "NOT COALESCE(" in entity
    assert "NOT COALESCE(" not in reject.split("WHERE")[-1]


# ....................... #
# The generated blocking audits (D21, §5.4)


def test_the_ingestion_metadata_audit_is_generated_and_referenced() -> None:
    model = _artifact("models/silver/inventory_level.sql")
    assert "audits (inventory_level_ingestion_metadata" in model
    audit = _artifact("audits/inventory_level_ingestion_metadata.sql")
    assert "AUDIT (\n  name inventory_level_ingestion_metadata\n)" in audit
    # A null or duplicated _source_row_id stops the run.
    for column in INGESTION_METADATA:
        assert f"{column} IS NULL" in audit
    # The duplicate half is a window count, which SQL forbids in WHERE — the
    # body projects it once and the predicate reads the projection.
    assert "COUNT(*) OVER (PARTITION BY _source_row_id) AS _row_id_count" in audit
    assert "OR _row_id_count > 1" in audit


def test_a_fail_disposition_rule_becomes_a_blocking_audit() -> None:
    model = _artifact("models/silver/inventory_level.sql")
    assert "inventory_level_stock_level_not_null" in model
    audit = _artifact("audits/inventory_level_stock_level_not_null.sql")
    assert audit.rstrip().endswith("SELECT * FROM @this_model WHERE stock_level IS NULL")


def test_audit_artifacts_are_kind_audit_and_models_are_kind_model() -> None:
    kinds = {a.path: a.kind for a in compile_fixture(FIXTURE)}
    assert kinds["audits/inventory_level_ingestion_metadata.sql"] is ArtifactKind.AUDIT
    assert kinds["models/silver/inventory_level__reject.sql"] is ArtifactKind.MODEL
    assert kinds["replay/inventory_level.sql"] is ArtifactKind.REPLAY


# ....................... #
# The replay artifact (§5.6, D22)


def test_replay_merges_by_the_pipeline_dedupe_order() -> None:
    content = _artifact("replay/inventory_level.sql")
    assert "MERGE INTO silver.inventory_level AS _target" in content
    assert "FROM silver.inventory_level__reject" in content
    assert "resolved_at IS NULL" in content
    # The winner is decided by the dedupe total order, as a row comparison.
    assert (
        "(_replay._ingested_at, _replay._load_id, _replay._source_row_id) > "
        "(_target._ingested_at, _target._load_id, _target._source_row_id)"
    ) in content
    # Replay re-runs the *current mapping* against raw — the same expressions.
    assert "TRY_CAST(raw ->> '$.on_hand' AS BIGINT) AS stock_level" in content


def test_replay_stamps_resolution_with_the_executing_engines_clock() -> None:
    """bloomery never reads a clock (RFC 0003); the emitted statement defers
    to the engine that runs it."""
    content = _artifact("replay/inventory_level.sql")
    assert "SET resolved_at = CURRENT_TIMESTAMP" in content
    assert "never executes it" in content  # the artifact says so in its header


def test_replay_candidates_pass_the_same_rules_the_pipeline_applies() -> None:
    content = _artifact("replay/inventory_level.sql")
    # A candidate that still fires a quarantine rule is filtered out by the
    # very same routing predicate, so "passers merge, the rest stay" holds.
    assert "NOT COALESCE(" in content
    assert f"AS {FLAGS_COLUMN}" in content


# ....................... #
# The two honest refusals


def test_dbt_refuses_the_reject_and_replay_artifacts() -> None:
    project, catalog = load_fixture(FIXTURE)
    with pytest.raises(UnsupportedByTarget) as excinfo:
        compile_project(project, target=Target.DBT, dialect="duckdb", catalog=catalog)
    message = str(excinfo.value)
    assert "inventory_level__reject" in message
    assert "compatibility target, minimal but honest" in message
    assert excinfo.value.source_path == "entity_model: entities.inventory_level.quarantine"


def test_dbt_still_emits_a_flag_only_quality_entity() -> None:
    """The refusal is about reject/replay, not about ``_quality_flags`` — the
    flag column is the *same* shared SELECT both targets render."""
    project, catalog = load_fixture("ecom_basic")
    artifacts = compile_project(project, target=Target.DBT, dialect="postgres", catalog=catalog)
    silver = next(a for a in artifacts if a.path.endswith("models/silver/order_item.sql"))
    assert FLAGS_COLUMN in silver.content


def test_postgres_refuses_the_coercion_failure_marker() -> None:
    """Postgres has no ``TRY_CAST`` and SQLGlot would render one as a plain
    ``CAST`` — a silent downgrade of quarantine into abort (RFC 0008 D3)."""
    project, catalog = load_fixture(FIXTURE)
    with pytest.raises(UnsupportedByTarget) as excinfo:
        compile_project(project, target=Target.SQLMESH, dialect="postgres", catalog=catalog)
    assert "dialect 'postgres' has none" in str(excinfo.value)


def test_trino_and_duckdb_both_express_the_marker() -> None:
    project, catalog = load_fixture(FIXTURE)
    for dialect in ("duckdb", "trino"):
        assert compile_project(project, target=Target.SQLMESH, dialect=dialect, catalog=catalog)


def test_the_ir_still_compiles_for_every_dialect() -> None:
    """The refusal is an *emit* concern: the IR itself is dialect-neutral."""
    project, catalog = load_fixture(FIXTURE)
    assert build_project_ir(project, catalog).entities[0].quarantine is not None
