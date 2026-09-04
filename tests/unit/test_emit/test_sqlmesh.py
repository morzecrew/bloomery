"""The SQLMesh emitter (RFC 0008 §5.3): artifact shape, path ordering,
fingerprint headers, kind mapping, naming-policy routing, and audit lowering
(builtin-style in the MODEL block; custom bodies under ``audits/``)."""

from __future__ import annotations

from dataclasses import replace

import pytest
import yaml

from bloomery import Target, build_project_ir, compile_project, project_fingerprint
from bloomery.dialects import get_dialect
from bloomery.emit import ArtifactKind, EmitContext
from bloomery.emit.sqlmesh import SQLMeshEmitter
from bloomery.ir import (
    AuditIR,
    ColumnIR,
    EntityIR,
    Materialization,
    ProjectIR,
    SCDKind,
    SourceColumnIR,
    SourceIR,
    SqlExpr,
)
from bloomery.naming import DefaultNaming, PrefixNaming
from bloomery.typing import DateType, DecimalType, IntType, LogicalType, StringType
from support.compiling import compile_fixture, extract_select, load_fixture

pytestmark = pytest.mark.unit


def test_minimal_artifact_shape() -> None:
    artifact = next(a for a in compile_fixture("minimal") if a.path.endswith("event.sql"))
    assert artifact.path == "models/silver/event.sql"
    assert artifact.kind is ArtifactKind.MODEL
    assert artifact.content.endswith("\n")
    assert not artifact.content.endswith("\n\n")
    assert "\r" not in artifact.content
    assert "MODEL (" in artifact.content
    assert "name silver.event," in artifact.content
    assert "kind FULL," in artifact.content
    assert "grain (event_id)" in artifact.content
    assert "FROM bronze.raw__events" in artifact.content


def test_artifacts_are_sorted_by_path() -> None:
    artifacts = compile_fixture("ecom_basic")
    paths = [a.path for a in artifacts]
    assert paths == sorted(paths)
    assert paths == [
        "config.yaml",
        "models/gold/dim_date.sql",
        "models/gold/mart_order_items.sql",
        "models/silver/order.sql",
        "models/silver/order_item.sql",
    ]


def test_fingerprint_header_matches_the_built_ir() -> None:
    """Every artifact carries it, in its own comment syntax: `--` for SQL,
    `#` for the YAML project file (RFC 0054)."""
    project, catalog = load_fixture("ecom_basic")
    fingerprint = project_fingerprint(build_project_ir(project, catalog))
    for artifact in compile_fixture("ecom_basic"):
        comment = "#" if artifact.path.endswith(".yaml") else "--"
        assert f"{comment} fingerprint: {fingerprint}" in artifact.content


def test_incremental_by_partition_lowers_to_time_range_kind() -> None:
    artifacts = compile_fixture("ecom_basic")
    order_item = next(a for a in artifacts if a.path.endswith("order_item.sql"))
    assert "kind INCREMENTAL_BY_TIME_RANGE (time_column order_date)," in order_item.content
    assert "partitioned_by (days(order_date))" in order_item.content
    assert "grain (order_id, line_no)," in order_item.content


def test_select_projects_every_column_sorted() -> None:
    artifacts = compile_fixture("ecom_basic")
    order_item = next(a for a in artifacts if a.path.endswith("order_item.sql"))
    select = extract_select(order_item.content)
    assert select.startswith("SELECT")
    for alias in ("line_no", "order_date", "order_id", "quantity", "unit_price"):
        assert f"AS {alias}" in select


def test_naming_policy_routes_paths_and_relations() -> None:
    project, catalog = load_fixture("minimal")
    artifacts = compile_project(
        project,
        target=Target.SQLMESH,
        dialect="duckdb",
        naming=PrefixNaming(prefix="acme"),
        catalog=catalog,
    )
    artifact = next(a for a in artifacts if a.path.endswith("event.sql"))
    assert artifact.path == "models/acme_silver/event.sql"
    assert "name acme_silver.event," in artifact.content
    assert "FROM acme_bronze.raw__events" in artifact.content


def test_checksum_matches_content() -> None:
    import hashlib

    for artifact in compile_fixture("ecom_basic"):
        assert artifact.checksum == hashlib.sha256(artifact.content.encode()).hexdigest()


def test_incremental_by_key_lowers_to_unique_key_kind() -> None:
    from bloomery import load_project

    model = """\
spec_version: 1
entities:
  event:
    grain: one row per event
    key: [event_id, kind]
    materialization: incremental_by_key
    fields:
      event_id: {type: string, required: true}
      kind: {type: string, required: true}
"""
    mapping = """\
mapping_version: 1
source: raw__events
target: event
key:
  event_id: {from: "$.id", transform: [to_string]}
  kind: {from: "$.kind", transform: [to_string]}
"""
    artifact = next(
        a
        for a in compile_project(
            load_project({"entity_model": model, "mapping": mapping}),
            target=Target.SQLMESH,
            dialect="duckdb",
        )
        if a.path.endswith(".sql")
    )
    assert "kind INCREMENTAL_BY_UNIQUE_KEY (unique_key (event_id, kind))," in artifact.content


_PARTITIONED_MODEL = """\
spec_version: 1
entities:
  event:
    grain: one row per event
    key: [event_id]
    partition_by: [{first}, {second}]
    fields:
      event_id: {{type: string, required: true}}
      status: {{type: string}}
      event_date: {{type: date}}
"""

_PARTITIONED_MAPPING = """\
mapping_version: 1
source: raw__events
target: event
key:
  event_id: {from: "$.id", transform: [to_string]}
fields:
  status: {from: "$.status", transform: [to_string]}
  event_date: {from: "$.happened_at", transform: [{parse_date: ISO8601}]}
"""


def _compile_partitioned(first: str, second: str) -> str:
    from bloomery import load_project

    (artifact,) = compile_project(
        load_project(
            {
                "entity_model": _PARTITIONED_MODEL.format(first=first, second=second),
                "mapping": _PARTITIONED_MAPPING,
            }
        ),
        target=Target.SQLMESH,
        dialect="duckdb",
    )
    return artifact.content


def test_a_non_temporal_leading_partition_column_is_refused() -> None:
    """``INCREMENTAL_BY_TIME_RANGE`` takes exactly one time column, documented
    as the first ``partition_by`` entry — before this refusal a non-temporal
    leading column emitted a model whose ``time_column`` is not time, which
    SQLMesh then fails on (or filters wrongly by) at run time."""
    from bloomery.errors import UnsupportedByTarget

    with pytest.raises(UnsupportedByTarget) as excinfo:
        _compile_partitioned("status", "event_date")
    message = str(excinfo.value)
    assert "'status'" in message
    assert "time_column" in message
    assert "Fix:" in message


def test_a_temporal_leading_partition_column_keeps_every_partition() -> None:
    """The control: the time column drives the kind, and the full partition
    list — later columns included — still lands in ``partitioned_by``."""
    content = _compile_partitioned("event_date", "status")
    assert "kind INCREMENTAL_BY_TIME_RANGE (time_column event_date)," in content
    assert "partitioned_by (event_date, status)" in content


def test_an_unknown_leading_partition_column_is_refused() -> None:
    """A ``partition_by`` entry naming no model column would become a
    ``time_column`` SQLMesh cannot resolve — same compile-and-fail shape as a
    non-temporal one, so the same refusal."""
    from bloomery.errors import UnsupportedByTarget

    with pytest.raises(UnsupportedByTarget) as excinfo:
        _compile_partitioned("vanished", "event_date")
    message = str(excinfo.value)
    assert "'vanished'" in message
    assert "time_column" in message


_PARTITIONED_MARTS = """\
marts_version: 1
marts:
  events:
    grain: event
    base: event
    partition_by: [{first}, {second}]
    materialization: incremental_by_partition
    flatten:
      - {{date: event_date, role: happened}}
"""


def _compile_partitioned_mart(first: str, second: str) -> tuple[str, ...]:
    from bloomery import load_project

    artifacts = compile_project(
        load_project(
            {
                "entity_model": _PARTITIONED_MODEL.format(first="event_date", second="status"),
                "mapping": _PARTITIONED_MAPPING,
                "marts": _PARTITIONED_MARTS.format(first=first, second=second),
            }
        ),
        target=Target.SQLMESH,
        dialect="duckdb",
    )
    return tuple(a.content for a in artifacts if a.path == "models/gold/mart_events.sql")


def test_a_non_temporal_leading_partition_column_is_refused_for_marts_too() -> None:
    """The mart kind clause takes the same first-partition-column mapping as
    the entity one, so the same non-temporal leading column emitted the same
    broken ``INCREMENTAL_BY_TIME_RANGE`` model through the gold path."""
    from bloomery.errors import UnsupportedByTarget

    with pytest.raises(UnsupportedByTarget) as excinfo:
        _compile_partitioned_mart("status", "event_date")
    message = str(excinfo.value)
    assert "mart 'events'" in message
    assert "'status'" in message


def test_a_temporal_leading_mart_partition_column_passes() -> None:
    (content,) = _compile_partitioned_mart("event_date", "status")
    assert "kind INCREMENTAL_BY_TIME_RANGE (time_column event_date)," in content


# ....................... #
# Audit lowering (RFC 0006 §5.6/D7 → RFC 0008 §5.3)


def _column(name: str, column_type: LogicalType) -> ColumnIR:
    return ColumnIR(
        name=name,
        type=column_type,
        canonical=None,
        unit=None,
        tax_basis=None,
        renamed_from=None,
        required=False,
    )


def _projection(name: str) -> SourceColumnIR:
    """This source\'s lowering of the column (RFC 0024 D26)."""
    return SourceColumnIR(name=name, expr=SqlExpr(name))


#: Every column these builders declare, lowered as itself. The emitted
#: SELECT projects `SourceIR.columns`, so a name missing here is a column
#: the model cannot produce (RFC 0024 D26).
_SOURCE = SourceIR(
    relation="src",
    columns=tuple(
        _projection(name)
        for name in (
            "amount",
            "item_id",
            "net_price",
            "net_price__direct",
            "qty",
            "shipped_on",
            "status",
        )
    ),
)


def _ctx() -> EmitContext:
    return EmitContext(
        dialect=get_dialect("duckdb"), naming=DefaultNaming(), fingerprint="blm1:test"
    )


def _merged_entity() -> EntityIR:
    """The same entity built from two sources, each with its own lowering."""
    return replace(
        _audited_entity(),
        sources=(
            replace(_SOURCE, relation="src_a"),
            replace(_SOURCE, relation="src_b"),
        ),
    )


def test_the_union_orders_branches_and_stamps_provenance() -> None:
    """RFC 0024 D3/D7: lexicographic branch order, and a ``_source`` literal
    per branch."""
    artifacts = SQLMeshEmitter().emit(ProjectIR(entities=(_merged_entity(),)), _ctx())
    model = next(a for a in artifacts if a.path == "models/silver/item.sql")
    body = model.content
    assert "UNION ALL" in body
    assert body.index("'src_a' AS _source") < body.index("'src_b' AS _source")
    assert body.index("bronze.src_a") < body.index("bronze.src_b")


def test_a_single_source_entity_emits_no_union_and_no_source_column() -> None:
    """D7: ``_source`` exists only on merged entities. The union of one is
    itself, not a one-branch UNION, so the whole existing corpus keeps its
    emitted SQL."""
    artifacts = SQLMeshEmitter().emit(ProjectIR(entities=(_audited_entity(),)), _ctx())
    body = next(a for a in artifacts if a.path == "models/silver/item.sql").content
    assert "UNION ALL" not in body
    assert "_source" not in body


def test_the_collision_audit_is_emitted_only_for_a_merged_entity() -> None:
    single = SQLMeshEmitter().emit(ProjectIR(entities=(_audited_entity(),)), _ctx())
    merged = SQLMeshEmitter().emit(ProjectIR(entities=(_merged_entity(),)), _ctx())
    assert not [a for a in single if "collision" in a.path]
    (audit,) = [a for a in merged if "collision" in a.path]
    assert audit.path == "audits/item_source_collision.sql"
    assert audit.kind is ArtifactKind.AUDIT
    # Grouped by every declared key column (D13), and counting *distinct*
    # sources — a plain COUNT would refuse a key duplicated within one source,
    # which is ordinary duplication `dedupe:` owns.
    assert "COUNT(DISTINCT _source)" in audit.content
    assert "GROUP BY" in audit.content
    # Blocking: SQLMesh audits block unless declared otherwise, so the envelope
    # says nothing about it — and there is no knob to say otherwise (D5).
    assert "blocking" not in audit.content
    model = next(a for a in merged if a.path == "models/silver/item.sql").content
    assert "item_source_collision" in model


def _audited_entity(*audits: AuditIR) -> EntityIR:
    return EntityIR(
        name="item",
        grain="one row per item",
        key=("item_id",),
        scd=SCDKind.TYPE1,
        materialization=Materialization.FULL,
        partition_by=(),
        columns=(
            _column("amount", DecimalType(12, 4)),
            _column("item_id", StringType()),
            _column("net_price", DecimalType(12, 4)),
            _column("net_price__direct", DecimalType(12, 4)),
            _column("qty", IntType()),
            _column("shipped_on", DateType()),
            _column("status", StringType()),
        ),
        sources=(_SOURCE,),
        audits=tuple(sorted(audits, key=lambda a: (a.kind, a.column))),
    )


def _emit(*audits: AuditIR) -> tuple[str, dict[str, str]]:
    """The MODEL artifact content plus {path: content} of the audit artifacts."""
    ctx = EmitContext(
        dialect=get_dialect("duckdb"), naming=DefaultNaming(), fingerprint="blm1:test"
    )
    artifacts = SQLMeshEmitter().emit(ProjectIR(entities=(_audited_entity(*audits),)), ctx)
    model = next(a for a in artifacts if a.kind is ArtifactKind.MODEL)
    audits_by_path = {a.path: a.content for a in artifacts if a.kind is ArtifactKind.AUDIT}
    return model.content, audits_by_path


def test_not_null_lowers_builtin_style_into_the_model_block() -> None:
    model, custom = _emit(AuditIR(kind="not_null", column="item_id"))
    assert "audits (not_null(columns := (item_id)))" in model
    assert custom == {}


def test_enum_lowers_as_accepted_values_with_typed_literals() -> None:
    model, custom = _emit(
        AuditIR(kind="enum", column="status", params=(("value_0000", "a"), ("value_0001", "b"))),
        AuditIR(kind="enum", column="qty", params=(("value_0000", "1"), ("value_0001", "2"))),
    )
    # int columns take number literals, string columns string literals.
    assert "accepted_values(column := qty, is_in := (1, 2))" in model
    assert "accepted_values(column := status, is_in := ('a', 'b'))" in model
    assert custom == {}


def test_min_max_lower_as_custom_audit_artifacts() -> None:
    model, custom = _emit(
        AuditIR(kind="min", column="amount", params=(("value", "0"),)),
        AuditIR(kind="max", column="qty", params=(("value", "10"),)),
    )
    assert "audits (item_qty_max, item_amount_min)" in model
    assert "SELECT * FROM @this_model WHERE amount < 0" in custom["audits/item_amount_min.sql"]
    assert "SELECT * FROM @this_model WHERE qty > 10" in custom["audits/item_qty_max.sql"]
    assert "AUDIT (\n  name item_amount_min\n);" in custom["audits/item_amount_min.sql"]
    assert "-- fingerprint: blm1:test" in custom["audits/item_amount_min.sql"]


def test_temporal_bounds_cast_the_literal() -> None:
    _model, custom = _emit(
        AuditIR(kind="min", column="shipped_on", params=(("value", "2020-01-01"),))
    )
    content = custom["audits/item_shipped_on_min.sql"]
    assert "WHERE shipped_on < CAST('2020-01-01' AS DATE)" in content


def test_regex_lowers_as_a_custom_audit() -> None:
    _model, custom = _emit(
        AuditIR(kind="regex", column="status", params=(("pattern", "^[a-z]+$"),))
    )
    content = custom["audits/item_status_regex.sql"]
    assert "WHERE NOT REGEXP_MATCHES(status, '^[a-z]+$')" in content


def test_reconcile_lowers_as_an_is_distinct_from_audit() -> None:
    model, custom = _emit(
        AuditIR(kind="reconcile", column="net_price", params=(("shadow", "net_price__direct"),))
    )
    assert "audits (item_net_price_reconcile)" in model
    content = custom["audits/item_net_price_reconcile.sql"]
    assert "WHERE net_price IS DISTINCT FROM net_price__direct" in content


def test_audit_artifacts_sort_before_models_and_end_in_one_newline() -> None:
    ctx = EmitContext(
        dialect=get_dialect("duckdb"), naming=DefaultNaming(), fingerprint="blm1:test"
    )
    entity = _audited_entity(
        AuditIR(kind="min", column="amount", params=(("value", "0"),)),
        AuditIR(kind="not_null", column="item_id"),
    )
    artifacts = SQLMeshEmitter().emit(ProjectIR(entities=(entity,)), ctx)
    assert [a.path for a in artifacts] == [
        "audits/item_amount_min.sql",
        "config.yaml",
        "models/silver/item.sql",
    ]
    for artifact in artifacts:
        assert artifact.content.endswith("\n")
        assert not artifact.content.endswith("\n\n")


def test_entities_without_audits_render_no_audits_property() -> None:
    model, custom = _emit()
    assert "audits" not in model
    assert custom == {}


# ....................... #
# Mart lowering (RFC 0010 / RFC 0008 D11) — the only join-emitting path


def _mart_artifact_for(fixture: str, relation: str) -> str:
    artifact = next(a for a in compile_fixture(fixture) if a.path.endswith(f"{relation}.sql"))
    assert artifact.kind is ArtifactKind.MODEL
    return artifact.content


def test_mart_model_joins_once_per_via_step_at_the_gold_relation() -> None:
    content = _mart_artifact_for("ecom_basic", "mart_order_items")
    assert "name gold.mart_order_items," in content
    assert "kind INCREMENTAL_BY_TIME_RANGE (time_column ordered_day)," in content
    assert "grain (order_id, line_no)," in content  # a mart is at base grain
    assert "partitioned_by (days(ordered_day))" in content
    assert "FROM silver.order_item AS order_item" in content
    assert 'LEFT JOIN silver."order" AS order_' in content
    assert "ON order_item.order_id = order_.order_id" in content
    assert content.count("JOIN") == 1  # one join per via step, nowhere else
    assert "order_.customer_id AS order_customer_id" in content


def test_mart_date_roles_bucket_via_date_trunc_cast_to_date() -> None:
    content = _mart_artifact_for("role_playing_dates", "mart_orders")
    for role, source in (("ordered", "order_date"), ("shipped", "ship_date")):
        for bucket in ("DAY", "WEEK", "MONTH", "QUARTER", "YEAR"):
            expected = (
                f"CAST(DATE_TRUNC('{bucket}', \"order\".{source}) AS DATE) "
                f"AS {role}_{bucket.lower()}"
            )
            assert expected in content
    assert "JOIN" not in content  # roles alone emit no joins


def test_silver_models_never_contain_joins() -> None:
    for artifact in compile_fixture("ecom_basic"):
        if "/silver/" in artifact.path:
            assert "JOIN" not in artifact.content


def test_mart_incremental_by_key_uses_the_base_entity_key() -> None:
    from bloomery import load_project

    sources = {
        "entity_model": """\
spec_version: 1
entities:
  event:
    grain: one row per event
    key: [event_id]
    fields:
      event_id: {type: string, required: true}
      occurred_at: {type: timestamp}
""",
        "mapping": """\
mapping_version: 1
source: raw__events
target: event
key:
  event_id: {from: "$.id", transform: [to_string]}
fields:
  occurred_at: {from: "$.ts"}
""",
        "marts": """\
marts_version: 1
marts:
  events:
    grain: event
    base: event
    flatten:
      - {date: occurred_at, role: occurred}
    materialization: incremental_by_key
""",
    }
    artifacts = compile_project(load_project(sources), target=Target.SQLMESH, dialect="duckdb")
    mart = next(a for a in artifacts if a.path == "models/gold/mart_events.sql")
    assert "kind INCREMENTAL_BY_UNIQUE_KEY (unique_key (event_id))," in mart.content


def test_naming_policy_routes_the_gold_layer() -> None:
    project, catalog = load_fixture("role_playing_dates")
    artifacts = compile_project(
        project,
        target=Target.SQLMESH,
        dialect="duckdb",
        naming=PrefixNaming(prefix="acme"),
        catalog=catalog,
    )
    mart = next(a for a in artifacts if "mart_orders" in a.path)
    assert mart.path == "models/acme_gold/mart_orders.sql"
    assert "name acme_gold.mart_orders," in mart.content
    assert 'FROM acme_silver."order" AS "order"' in mart.content


# ....................... #
# Date dimension (RFC 0008 D13)


def test_dim_date_emits_a_deterministic_calendar_from_the_catalog() -> None:
    content = _mart_artifact_for("ecom_basic", "dim_date")
    assert "name gold.dim_date," in content
    assert "kind FULL," in content
    assert "grain (date_day)" in content
    # Bounds come from the catalog definition, never from a clock.
    assert "CAST('2020-01-01' AS DATE)" in content
    assert "CAST('2030-12-31' AS DATE)" in content
    assert "GENERATE_SERIES" in content
    for bucket in ("month", "quarter", "week", "year"):
        assert f"AS date_{bucket}" in content


def test_projects_without_a_date_dimension_emit_no_dim_date() -> None:
    # `minimal` has no catalog at all — the only fixture left without a date
    # dimension now that every mart fixture declares one (RFC 0013 R1 rule 4).
    assert not any("dim_date" in a.path for a in compile_fixture("minimal"))


# ....................... #
# The project file (RFC 0054)


def _config(fixture: str) -> str | None:
    return next(
        (a.content for a in compile_fixture(fixture, dialect="duckdb") if a.path == "config.yaml"),
        None,
    )


def test_the_emitted_tree_carries_a_project_file() -> None:
    """Without it SQLMesh does not read the models at all — "SQLMesh project
    config could not be found" (RFC 0054 §3 M1). The dbt target has emitted
    `dbt_project.yml` all along; this is the same artifact for the primary
    target."""
    (config,) = [a for a in compile_fixture("ecom_basic", dialect="duckdb") if a.path == "config.yaml"]
    assert config.kind is ArtifactKind.CONFIG
    assert config.content.endswith("\n")
    assert not config.content.endswith("\n\n")


def test_the_project_file_carries_only_model_defaults() -> None:
    """The line already drawn for dbt, where `dbt_project.yml` is emitted and
    `profiles.yml` deliberately is not: a connection carries hosts and
    credentials, and the compiler reads no environment (D1).

    Asserted by parsing rather than by substring — the header comment names
    `gateways:` in the sentence telling the caller to add one, so a substring
    check would either fail on the comment or pass on a real gateway block
    depending on how it was written.
    """
    content = _config("ecom_basic")
    assert content is not None
    document = yaml.safe_load(content)
    assert set(document) == {"model_defaults"}
    assert set(document["model_defaults"]) == {"dialect", "start"}


def test_the_dialect_is_the_one_the_compile_was_asked_for() -> None:
    for dialect in ("duckdb", "postgres"):
        content = next(
            a.content
            for a in compile_fixture("ecom_basic", dialect=dialect)
            if a.path == "config.yaml"
        )
        assert f"dialect: {dialect}" in content


def test_the_start_comes_from_the_catalog_date_dimension() -> None:
    """The finding this artifact exists for (D2). Without a start SQLMesh
    backfills every INCREMENTAL_BY_TIME_RANGE model over a single day and
    reports success, so the value is not optional — and it is derived rather
    than declared, because the date dimension already states the project's
    temporal extent (D3).

    The expectation is read off the fixture's catalog rather than retyped: a
    hard-coded 2020 would keep passing if the derivation stopped reading the
    catalog at all.
    """
    _project, catalog = load_fixture("ecom_basic")
    assert catalog is not None
    content = _config("ecom_basic")
    assert content is not None
    assert f"start: '{catalog.date_dimension.start_year}-01-01'" in content


def test_a_project_with_nothing_to_backfill_by_time_needs_no_start() -> None:
    """`minimal` declares no catalog and partitions nothing, so every model is
    a full refresh and the start is read by none of them. The key is absent
    rather than guessed."""
    content = _config("minimal")
    assert content is not None
    assert "dialect: duckdb" in content
    assert "start" not in content


def test_a_year_below_1000_is_written_as_four_digits() -> None:
    """`start_year` is `ge=1` (spec/catalog.py), so a single-digit year is a
    legal catalog. Unpadded it renders `start: '1-01-01'`, which SQLMesh does
    not reject — it reads it as **2001-01-01**, two millennia of backfill
    silently disappearing into a value the compiler wrote itself. The date
    spine is padded for the same reason: `CAST('1-01-01' AS DATE)` means
    whatever the engine's date style guesses, and the two artifacts of one
    compile must not disagree about the same year.
    """
    project, catalog = load_fixture("ecom_basic")
    ir = build_project_ir(project, catalog)
    assert ir.date_dimension is not None
    ctx = EmitContext(dialect=get_dialect("duckdb"), naming=DefaultNaming(), fingerprint="x")
    early = replace(ir, date_dimension=replace(ir.date_dimension, start_year=1, end_year=2))
    artifacts = SQLMeshEmitter().emit(early, ctx)

    config = next(a.content for a in artifacts if a.path == "config.yaml")
    assert "start: '0001-01-01'" in config
    spine = next(a.content for a in artifacts if a.path.endswith("dim_date.sql"))
    assert "CAST('0001-01-01' AS DATE)" in spine
    assert "CAST('0002-12-31' AS DATE)" in spine


def test_no_project_file_where_the_start_cannot_be_stated() -> None:
    """D5, answered: a project that backfills by time and declares no date
    dimension gets **no** config rather than one missing its start.

    That is today's behaviour exactly, and it is the conservative reading of
    the measurement rather than a lesser one — a config.yaml whose missing
    start makes `sqlmesh plan` succeed over one day is worse than a directory
    with no config, because the first runs and the second does not.
    """
    project, catalog = load_fixture("ecom_basic")
    ir = build_project_ir(project, catalog)
    ctx = EmitContext(dialect=get_dialect("duckdb"), naming=DefaultNaming(), fingerprint="x")
    stripped = replace(ir, date_dimension=None, marts=())
    assert any(
        entity.materialization is Materialization.INCREMENTAL_BY_PARTITION
        for entity in stripped.entities
    ), "the fixture must still backfill by time for this to prove anything"
    assert not any(a.path == "config.yaml" for a in SQLMeshEmitter().emit(stripped, ctx))
