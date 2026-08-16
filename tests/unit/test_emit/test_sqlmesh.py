"""The SQLMesh emitter (RFC 0008 §5.3): artifact shape, path ordering,
fingerprint headers, kind mapping, naming-policy routing, and audit lowering
(builtin-style in the MODEL block; custom bodies under ``audits/``)."""

from __future__ import annotations

import pytest

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
    (artifact,) = compile_fixture("minimal")
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
        "models/gold/dim_date.sql",
        "models/gold/mart_order_items.sql",
        "models/silver/order.sql",
        "models/silver/order_item.sql",
    ]


def test_fingerprint_header_matches_the_built_ir() -> None:
    project, catalog = load_fixture("ecom_basic")
    fingerprint = project_fingerprint(build_project_ir(project, catalog))
    for artifact in compile_fixture("ecom_basic"):
        assert f"-- fingerprint: {fingerprint}" in artifact.content


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
    (artifact,) = artifacts
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
    (artifact,) = compile_project(
        load_project({"entity_model": model, "mapping": mapping}),
        target=Target.SQLMESH,
        dialect="duckdb",
    )
    assert "kind INCREMENTAL_BY_UNIQUE_KEY (unique_key (event_id, kind))," in artifact.content


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
    assert [a.path for a in artifacts] == ["audits/item_amount_min.sql", "models/silver/item.sql"]
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
