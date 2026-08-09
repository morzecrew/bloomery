"""Emission of the data-quality artifacts (RFC 0016 §5.4–§5.6): the silver
pipeline's shape, the reject model, the replay merge, the generated blocking
audits, and the two honest refusals.

The execution assertions — running the SQL, checking quarantine contents,
the conservation law — are the execution tier's (RFC 0016 §6); what is
asserted here is that the artifacts say what the RFC says they say.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlglot import exp, parse_one

from bloomery import Target, build_project_ir, compile_project
from bloomery.dialects import get_dialect
from bloomery.emit import ArtifactKind, EmitContext
from bloomery.emit.sqlmesh import SQLMeshEmitter
from bloomery.emit.lowering import REJECT_KEY, _schema_column, entity_select, mart_select
from bloomery.errors import EmitError, UnsupportedByTarget
from bloomery.ir import MartJoinIR
from bloomery.marts import HAS_QUALITY_FLAGS
from bloomery.naming import DefaultNaming
from bloomery.quality import FLAGS_COLUMN, INGESTION_METADATA, OK_COLUMN, REJECT_COLUMNS
from bloomery.typing import BoolType
from support.compiling import compile_fixture, extract_select, load_fixture
from support.plan_ir import column as plan_column
from support.plan_ir import entity as plan_entity
from support.plan_ir import mart as plan_mart
from support.plan_ir import mart_column as plan_mart_column
from support.plan_ir import quality_rule as plan_rule

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
        if not artifact.path.startswith("models/silver/") or artifact.path.endswith(
            ("__reject.sql", "__reconcile.sql")
        ):
            continue  # neither is an entity model: one holds rejected rows, one a comparison
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


def test_the_flag_pass_is_single_and_records_what_a_kept_row_can_fire() -> None:
    """One array construct, one pass (§5.4) — over the rules a *kept* row can
    actually trip: ``flag`` and ``fail``. A quarantine rule firing diverts the
    row, so its name could never appear here; a ``fail`` rule firing does not
    move the row at all, and leaving its name out made such a row read as clean
    everywhere the package looks (D18)."""
    body = extract_select(_artifact("models/silver/inventory_level.sql"))
    assert body.count("AS _quality_flags") == 1
    flags_clause = body.split("AS _quality_flags")[0]
    assert "stock_level_not_negative" in flags_clause  # flag
    assert "stock_level_not_null" in flags_clause  # fail
    # Quarantine-disposition names never enter _quality_flags; they route.
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
    assert "INCREMENTAL_BY_UNIQUE_KEY (unique_key (reject_id)" in content
    # …and land on it *selectively*: `first_seen` records when the problem
    # started, so the merge keeps the existing value while every other column
    # takes the arriving one (§5.6). Without the clause the default merge
    # overwrites the whole row and the column tracks the newest delivery.
    assert "when_matched (WHEN MATCHED THEN UPDATE SET " in content
    assert "target.first_seen = COALESCE(target.first_seen, source.first_seen)" in content
    assert "target.last_seen = source.last_seen" in content
    assert "target.reject_id" not in content  # the merge key is never assigned
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


def test_failed_rules_records_every_failure_the_row_had() -> None:
    """D18: the reject row is the full account of why a row is not in the
    entity — "all failed rule names … its flag-level failures included", and by
    the same argument its blocking ones. A diverted row that also tripped a
    ``fail`` rule is the case where the omission mattered most: it is the row
    the run was supposed to stop for."""
    body = extract_select(_artifact("models/silver/inventory_level__reject.sql"))
    failed = body.split("AS failed_rules")[0]
    assert "stock_level_range_min" in failed  # the rule that diverted the row
    assert "stock_level_not_negative" in failed  # a flag-level failure
    assert "stock_level_not_null" in failed  # the blocking one


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
    # D25/D31: a present-but-uncastable _ingested_at stops the run too — the
    # one dedupe sort key no `coercible` rule can reach, because ingestion
    # metadata is never a mapped field.
    assert "TRY_CAST(_ingested_at AS TIMESTAMP) IS NULL" in audit


def test_a_fail_disposition_rule_becomes_a_blocking_audit_over_two_populations() -> None:
    """D18/D32/D67: the audit reads the **pre-route** population *and* the
    entity.

    Routing is stage 6 of the pipeline and the audit runs after the model is
    built, so an audit over the entity alone sees only the rows the split kept —
    a row that failed a blocking rule *and* a quarantine rule would sit in the
    reject table with the run carrying on, inverting the severity order the RFC
    pins (D32). And an audit over the extract alone misses every row that
    reached the entity by **replay**, whose bronze source has aged out of the
    incremental window by construction (D67). Both legs, or the audit is silent
    about a population that exists.
    """
    model = _artifact("models/silver/inventory_level.sql")
    assert "inventory_level_stock_level_not_null" in model
    audit = _artifact("audits/inventory_level_stock_level_not_null.sql")
    assert "FROM bronze.wms__stock_levels" in audit
    assert ") AS _extract\nWHERE\n  _extract.stock_level IS NULL" in audit
    # The entity leg reads the *recorded* verdict, not a re-derived predicate:
    # over model columns the coercion marker's source conjuncts are gone.
    assert "FROM @this_model AS _entity" in audit
    assert "ARRAY_CONTAINS(_entity._quality_flags, 'stock_level_not_null')" in audit
    # UNION, not UNION ALL: the ordinary violator is in both populations.
    assert "\nUNION\n" in audit
    assert "UNION ALL" not in audit


def test_the_conservation_audit_is_generated_and_blocking() -> None:
    """RFC 0016 §6 does not merely ask for a conservation *test*: the law is
    "also emitted as a runtime audit on every production run". So it is an
    artifact, referenced from the model, and blocking like the D21 audit beside
    it — a row that reached neither side of the split has been silently
    dropped, and that is the failure this package exists to make impossible."""
    model = _artifact("models/silver/inventory_level.sql")
    assert "inventory_level_conservation" in model
    audit = _artifact("audits/inventory_level_conservation.sql")
    assert "AUDIT (\n  name inventory_level_conservation\n)" in audit
    assert "blocking false" not in audit  # blocking is the default, and wanted

    # The one leg an audit body can reach that can actually fail (D61). The
    # second leg it used to carry — ``surviving_rows > bronze_rows`` — compared
    # a CTE against the very relation it filters, so it could not fire for any
    # spec, any data or any bug; ``bronze_rows`` stays a projected column,
    # because the deduped count is what makes a reported violation legible.
    assert "entity_rows + diverted_rows <> surviving_rows" in audit
    assert "surviving_rows > bronze_rows" not in audit
    assert "AS bronze_rows" in audit
    # The entity side is scoped to *this* run's survivors by source-row
    # identity, which keeps the sum stable across a replay and exact under an
    # incremental entity.
    assert "_entity._source_row_id IN (" in audit


def test_the_conservation_audit_addresses_only_the_model_and_its_source() -> None:
    """The scope limit, pinned. An AUDIT body may reference the audited model
    (through the target's macro) and the model's external upstream — nothing
    else: SQLMesh rewrites model references inside a MODEL query to the
    physical snapshot table and does **not** do so inside an audit, so a
    literal sibling reference resolves to a virtual-layer view that does not
    exist yet on a first plan. The reject table is therefore recomputed from
    the routing predicate rather than read."""
    audit = _artifact("audits/inventory_level_conservation.sql")
    assert "FROM @this_model AS _entity" in audit
    assert "FROM bronze.wms__stock_levels" in audit
    assert "__reject" not in audit
    assert "silver." not in audit


def test_the_conservation_audit_reuses_the_pipelines_own_extract_and_routing() -> None:
    """The survivors CTE is the *same* stages 1–3 the model runs, dedupe
    ``QUALIFY`` included, and ``diverted_rows`` counts by the *same* routing
    predicate the reject model routes by. An audit with its own idea of
    "survivors" would agree with itself and with nothing else."""
    audit = _artifact("audits/inventory_level_conservation.sql")
    model = _artifact("models/silver/inventory_level.sql")
    reject = _artifact("models/silver/inventory_level__reject.sql")
    assert "WITH _survivors AS (" in audit
    for line in ("ROW_NUMBER() OVER (", "PARTITION BY warehouse_id, stock_date"):
        assert line in audit
        assert line in model
    assert "_survivors.stock_level < 0" in audit  # the routing predicate, verbatim
    assert "_extract.stock_level < 0" in reject


def test_an_entity_without_a_reject_table_gets_no_conservation_audit() -> None:
    """The law relates the entity to its reject table, so it is emitted exactly
    where that table is — the same condition the reject and replay artifacts
    ride on."""
    paths = {a.path for a in compile_fixture("ecom_basic")}
    assert not any(path.endswith("_conservation.sql") for path in paths)


def test_a_referential_quarantine_entity_gets_no_conservation_audit() -> None:
    """The one shape the audit is skipped for, asserted rather than assumed:
    its routing predicate reads a *sibling* silver entity, and an audit body
    cannot address one on this target. Recorded as scope, not worked around —
    the conservation property still covers the shape (RFC 0016 §6)."""
    project, catalog = load_fixture(FIXTURE)
    ir = build_project_ir(project, catalog)
    entity = ir.entities[0]
    referential = plan_rule(
        name="item_of_order_referential",
        kind="referential",
        column_name=None,
        on_fail=None,
        params=(
            ("on_missing", "quarantine"),
            ("relationship", "item_of_order"),
            ("to_entity", "order"),
            ("via_0000", "warehouse_id=warehouse_id"),
        ),
    )
    mutated = replace(
        ir,
        entities=(replace(entity, quality=(*entity.quality, referential)),),
        marts=(),
        reconcile=(),
    )
    ctx = EmitContext(
        fingerprint="blm1:test", naming=DefaultNaming(), dialect=get_dialect("duckdb")
    )
    paths = {a.path for a in SQLMeshEmitter().emit(mutated, ctx)}
    assert "models/silver/inventory_level__reject.sql" in paths  # still routed
    assert "audits/inventory_level_conservation.sql" not in paths


def test_audit_artifacts_are_kind_audit_and_models_are_kind_model() -> None:
    kinds = {a.path: a.kind for a in compile_fixture(FIXTURE)}
    assert kinds["audits/inventory_level_ingestion_metadata.sql"] is ArtifactKind.AUDIT
    assert kinds["audits/inventory_level_conservation.sql"] is ArtifactKind.AUDIT
    assert kinds["models/silver/inventory_level__reject.sql"] is ArtifactKind.MODEL
    assert kinds["replay/inventory_level.sql"] is ArtifactKind.REPLAY


# ....................... #
# The replay artifact (§5.6, D22)


def test_replay_merges_by_the_pipeline_dedupe_order() -> None:
    content = _artifact("replay/inventory_level.sql")
    assert "MERGE INTO silver.inventory_level AS _target" in content
    assert "FROM silver.inventory_level__reject" in content
    assert "resolved_at IS NULL" in content
    # The winner is decided by the dedupe total order — spelled per column and
    # NULL-aware, *not* as a row constructor. `(a, b) > (c, d)` reads like the
    # same question but orders NULL as the largest value, the inverse of the
    # DESC NULLS LAST the pipeline ranks by; the two then disagreed on any
    # nullable sort column. Asserting the absence matters as much as the
    # presence: the old text is what this test used to pin.
    assert (
        "(_replay._ingested_at, _replay._load_id, _replay._source_row_id) > "
        "(_target._ingested_at, _target._load_id, _target._source_row_id)"
    ) not in content
    assert "NOT _replay._ingested_at IS NULL AND _target._ingested_at IS NULL" in content
    assert "_replay._ingested_at > _target._ingested_at" in content
    # Replay re-runs the *current mapping* against raw — the same expressions.
    assert "TRY_CAST(raw ->> '$.on_hand' AS BIGINT) AS stock_level" in content


def test_replay_assigns_to_unqualified_target_columns() -> None:
    """Standard SQL: the left side of a MERGE ``SET`` is a **bare** column of
    the merge target. DuckDB, Postgres and Trino all reject a qualified one
    ("Qualified column names in UPDATE .. SET not supported"), so emitting
    ``_target.col = …`` made the replay artifact unrunnable on every shipped
    dialect while every golden stayed green. Found by the execution tier
    (RFC 0016 §6), pinned here."""
    content = _artifact("replay/inventory_level.sql")
    assert "THEN UPDATE SET\n  stock_level = _replay.stock_level" in content
    assert "_target.stock_level = " not in content
    # The right side stays qualified — it names the source row.
    assert "= _replay._quality_flags" in content


def test_replay_without_a_dedupe_block_still_compares_by_the_row_identity() -> None:
    """An entity may declare ``quarantine:`` without ``dedupe:`` — the two opt
    in separately. The total order does not vanish with the block: D20 makes
    ``_source_row_id`` the final sort key and D21 guarantees it exists on any
    entity with a reject table, so the comparison degenerates to that key
    alone. It used to degenerate to ``()``, i.e. to invalid SQL."""
    content = next(
        artifact.content
        for artifact in compile_fixture("dirty_corpus")
        if artifact.path == "replay/dirty_status.sql"
    )
    assert "_replay._source_row_id > _target._source_row_id" in content
    assert "() > ()" not in content
    # D21 guarantees the key is non-null, but the comparison is generated from
    # the order, not from that guarantee, so it carries the same NULL arms.
    assert "NOT _replay._source_row_id IS NULL" in content


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
    # The fixture also declares a reconcile check, which dbt refuses *first*
    # (it is a project-level check, made before any entity is walked), so this
    # test drops it to reach the entity-level refusal it is about.
    without_reconcile = replace(
        project,
        entity_model=project.entity_model.model_copy(update={"reconcile": ()}),
    )
    with pytest.raises(UnsupportedByTarget) as excinfo:
        compile_project(without_reconcile, target=Target.DBT, dialect="duckdb", catalog=catalog)
    message = str(excinfo.value)
    assert "inventory_level__reject" in message
    assert "compatibility target, minimal but honest" in message
    assert excinfo.value.source_path == "entity_model: entities.inventory_level.quarantine"


def test_dbt_refuses_reconcile_naming_the_checks() -> None:
    """The second honest refusal (RFC 0016 §5.4): a reconcile check lowers to
    a model *and* a non-blocking audit, and dbt has no non-blocking test —
    approximating it would turn "report the disagreement" into "fail the
    build"."""
    project, catalog = load_fixture(FIXTURE)
    with pytest.raises(UnsupportedByTarget) as excinfo:
        compile_project(project, target=Target.DBT, dialect="duckdb", catalog=catalog)
    assert "stock_level_matches_snapshot" in str(excinfo.value)
    assert excinfo.value.source_path == "entity_model: reconcile"


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
    # Specifically the coercible refusal, not the metadata audit's — an author
    # who wrote rules must read about the rules they wrote.
    assert "carries coercible quality rules" in str(excinfo.value)
    assert "dialect 'postgres' has none" in str(excinfo.value)


def test_postgres_refuses_the_metadata_audit_on_a_dedupe_only_entity() -> None:
    """The edge of D30, which the coercible-rule refusal above does not reach.

    ``dedupe:`` alone does not join the entity to the quality system (D24), so
    a dedupe-only entity carries no ``coercible`` rule and sails past
    ``_require_try_cast`` — yet it still gets the D21 metadata audit, whose
    D25 castability assertion is a ``TRY_CAST``. Rendered on Postgres that
    becomes a plain ``CAST`` that raises inside the audit query. The IR is
    mutated rather than fixtured because no shipped fixture has this shape.
    """
    project, catalog = load_fixture(FIXTURE)
    ir = build_project_ir(project, catalog)
    entity = ir.entities[0]
    assert entity.dedupe is not None
    mutated = replace(
        ir,
        entities=(replace(entity, quality=(), quarantine=None),),
        marts=(),
        reconcile=(),
    )
    ctx = EmitContext(
        fingerprint="blm1:test", naming=DefaultNaming(), dialect=get_dialect("postgres")
    )
    with pytest.raises(UnsupportedByTarget) as excinfo:
        SQLMeshEmitter().emit(mutated, ctx)
    assert "_ingested_at casts to timestamp" in str(excinfo.value)
    # …and the same shape compiles on a dialect that has the cast.
    duckdb_ctx = replace(ctx, dialect=get_dialect("duckdb"))
    assert SQLMeshEmitter().emit(mutated, duckdb_ctx)


def test_trino_and_duckdb_both_express_the_marker() -> None:
    """Both carry ``TRY_CAST``, so the coercion-failure marker means the same
    thing on each — that is what this test is about, and it still holds."""
    project, catalog = load_fixture(FIXTURE)
    ir = build_project_ir(project, catalog)
    for dialect in ("duckdb", "trino"):
        ctx = EmitContext(
            fingerprint="blm1:test", naming=DefaultNaming(), dialect=get_dialect(dialect)
        )
        assert "TRY_CAST" in entity_select(ir.entities[0], ctx).sql(dialect=dialect)


def test_trino_now_emits_the_reject_table_it_used_to_be_refused() -> None:
    """Trino was refused here because both constructions the reject table is
    built from were DuckDB's spellings: ``SHA256`` over text, and the
    positional ``JSON_OBJECT('k', v)``. Each dialect now spells both through
    its own port (RFC 0016 D76), verified against ``trinodb/trino:483``.
    """
    project, catalog = load_fixture(FIXTURE)
    artifacts = compile_project(
        project, target=Target.SQLMESH, dialect="trino", catalog=catalog
    )
    (reject,) = [a for a in artifacts if a.path.endswith("__reject.sql")]
    assert "TO_HEX(" in reject.content and "TO_UTF8(" in reject.content
    assert "JSON_OBJECT(" in reject.content


def test_postgres_is_still_refused_but_for_the_other_gap() -> None:
    """D76 closes the reject *constructions* on every shipped dialect. It does
    not close D30: Postgres has no NULL-on-failure cast, so an entity carrying
    ``coercible`` rules is still refused there — a different gap, and the
    message has to be the one that names it, not a reject-table one."""
    project, catalog = load_fixture(FIXTURE)
    with pytest.raises(UnsupportedByTarget) as excinfo:
        compile_project(project, target=Target.SQLMESH, dialect="postgres", catalog=catalog)
    message = str(excinfo.value)
    assert "NULL-on-failure cast" in message
    assert "reject_id" not in message


def test_the_three_dialects_spell_the_reject_constructions_differently() -> None:
    """Asserted on the port rather than through a compile, because Postgres
    cannot reach emission while D30 stands — and a spelling that is only
    exercised once D30 lifts is exactly the kind that rots unnoticed.

    The property is that the three *differ*: one rendering passing everywhere
    would mean the split never happened. Each was executed against its engine
    (RFC 0016 D76) — DuckDB's returns hex directly, Postgres' ``sha256``
    returns ``bytea``, and Trino's does not take text at all.
    """
    digests, objects = set(), set()
    for name in ("duckdb", "postgres", "trino"):
        dialect = get_dialect(name)
        digests.add(dialect.render(dialect.text_sha256(exp.Literal.string("abc"))))
        objects.add(dialect.render(dialect.json_object([("a", exp.Literal.number(1))])))
    assert len(digests) == 3
    assert len(objects) == 3


def test_the_ir_still_compiles_for_every_dialect() -> None:
    """The refusal is an *emit* concern: the IR itself is dialect-neutral."""
    project, catalog = load_fixture(FIXTURE)
    assert build_project_ir(project, catalog).entities[0].quarantine is not None


# ....................... #
# has_quality_flags on a mart that also joins (RFC 0016 §5.5)


def test_the_quality_dimension_projects_from_the_base_alongside_joins() -> None:
    """The derived column is owned by the **base** join alias, so it renders
    correctly on a mart that flattens other entities too — the case no fixture
    combines, and the one where a wrong owner would silently qualify
    ``_quality_ok`` with a joined alias."""
    base = plan_entity(
        name="order_item",
        key=("order_id",),
        columns=(plan_column("order_id"), plan_column("amount")),
        quality=(plan_rule(),),
    )
    joined = plan_entity(name="order", key=("id",), columns=(plan_column("id"),))
    mart = plan_mart(
        name="items",
        base="order_item",
        grain="order_item",
        columns=(
            plan_mart_column("order_id"),
            plan_mart_column("amount"),
            plan_mart_column(HAS_QUALITY_FLAGS, type_=BoolType(), source_column=OK_COLUMN),
            plan_mart_column("o_id", source_entity="order", source_column="id"),
        ),
        joins=(
            MartJoinIR(
                relationship="item_of_order", entity="order", prefix="o_", on=(("order_id", "id"),)
            ),
        ),
    )
    context = EmitContext(
        dialect=get_dialect("duckdb"), naming=DefaultNaming(), fingerprint="blm1:test"
    )
    rendered = context.dialect.render(
        mart_select(mart, context)  # the shared lowering both SQL targets use
    )
    assert "NOT order_item._quality_ok AS has_quality_flags" in rendered
    assert 'LEFT JOIN silver."order" AS o_' in rendered
    assert "order_item.order_id = o_.id" in rendered


# ....................... #
# The reconcile audit's disposition (§5.3)


@pytest.mark.parametrize(
    ("on_fail", "blocking"),
    [("flag", False), ("fail", True), ("quarantine", False)],
)
def test_a_reconcile_checks_audit_blocks_exactly_when_it_says_fail(
    on_fail: str, blocking: bool
) -> None:
    """§5.3 nominates ``reconcile`` as the pipeline-stopping gate — "a
    pipeline-stopping orphan gate, where genuinely wanted, is expressed as a
    ``reconcile`` check instead" — and that sentence is only true if
    ``on_fail: fail`` actually blocks. Emitting the same non-blocking audit for
    every value made the field decoration: the quality mart reported
    ``disposition = 'fail'`` while the run carried on regardless.

    ``quarantine`` lowers non-blocking: a reconcile compares two aggregates and
    routes no row, so there is nothing for it to divert (refusing the value is
    the spec surface's job, where ``on_fail`` is typed).
    """
    project, catalog = load_fixture(FIXTURE)
    checks = tuple(
        check.model_copy(update={"on_fail": on_fail}) for check in project.entity_model.reconcile
    )
    project = replace(
        project, entity_model=project.entity_model.model_copy(update={"reconcile": checks})
    )
    artifacts = compile_project(project, target=Target.SQLMESH, dialect="duckdb", catalog=catalog)
    audit = next(
        a.content
        for a in artifacts
        if a.kind is ArtifactKind.AUDIT and a.path.endswith("_matches_snapshot_reconcile.sql")
    )
    assert ("blocking false" in audit) is not blocking


def test_a_schema_constant_that_lost_its_column_says_so() -> None:
    """``REJECT_KEY`` singles out one column of a schema tuple declared
    elsewhere, so it is only correct while that column is still in the tuple.
    Written as ``next(n for n in REJECT_COLUMNS if n == "reject_id")`` the
    dependency is an identity filter that spells the name twice and, the day
    the column leaves, raises a bare ``StopIteration`` at import naming neither
    the column nor the schema."""
    assert REJECT_KEY in REJECT_COLUMNS
    with pytest.raises(EmitError) as excinfo:
        _schema_column("reject_id", ("a", "b"), "the reject table's unique key")
    message = str(excinfo.value)
    assert "reject_id" in message
    assert "the reject table's unique key" in message
