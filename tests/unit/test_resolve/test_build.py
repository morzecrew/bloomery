"""The IR builder (RFC 0003 §12, RFC 0004/0005 integration): lowering rules,
materialization defaults, reachable-only metrics, batched typecheck failures."""

from __future__ import annotations

import pytest

from bloomery import build_project_ir, load_catalog, load_project, project_fingerprint
from bloomery.errors import ResolutionError, TypeCheckError
from bloomery.ir import Materialization, PartitionSpec, UnreachableMetric
from bloomery.typing import DecimalType, StringType, TimestampType
from support.compiling import load_fixture

pytestmark = pytest.mark.unit


def test_minimal_ir_lowering() -> None:
    project, _ = load_fixture("minimal")
    ir = build_project_ir(project)
    (entity,) = ir.entities
    assert entity.name == "event"
    assert entity.materialization is Materialization.FULL
    assert [c.name for c in entity.columns] == ["event_id", "kind", "occurred_at"]
    by_name = {c.name: c for c in entity.columns}
    # A chain lowers through the registry builders; a chain-less mapping is a
    # declared-type cast at extraction.
    assert by_name["event_id"].expr.sql == "CAST(id AS TEXT)"
    assert by_name["occurred_at"].expr.sql == "CAST(ts AS TIMESTAMP)"
    assert by_name["occurred_at"].type == TimestampType()
    assert entity.source.relation == "raw__events"
    assert ir.metrics == ()
    assert ir.marts == ()


def test_ecom_recipe_lowering_records_the_recipe_id() -> None:
    project, catalog = load_fixture("ecom_basic")
    ir = build_project_ir(project, catalog)
    order_item = next(e for e in ir.entities if e.name == "order_item")
    unit_price = next(c for c in order_item.columns if c.name == "unit_price")
    assert unit_price.expr.sql == "CAST(total / qty AS DECIMAL(12, 4))"
    assert unit_price.recipe_id == "from_total"
    assert unit_price.type == DecimalType(12, 4)
    assert unit_price.canonical == "unit_price"
    assert unit_price.unit is not None and unit_price.unit.value == "currency"
    assert unit_price.tax_basis is not None and unit_price.tax_basis.value == "net"


def test_ecom_nested_jsonpath_lowering() -> None:
    project, catalog = load_fixture("ecom_basic")
    ir = build_project_ir(project, catalog)
    order = next(e for e in ir.entities if e.name == "order")
    customer_id = next(c for c in order.columns if c.name == "customer_id")
    assert customer_id.expr.sql == "CAST(JSON_EXTRACT_SCALAR(customer, '$.id') AS TEXT)"
    assert customer_id.type == StringType()


def test_materialization_default_derives_from_partitioning() -> None:
    project, catalog = load_fixture("ecom_basic")
    ir = build_project_ir(project, catalog)
    by_name = {e.name: e for e in ir.entities}
    # partition_by present → incremental_by_partition (RFC 0002 D7).
    assert by_name["order_item"].materialization is Materialization.INCREMENTAL_BY_PARTITION
    assert by_name["order_item"].partition_by == (
        PartitionSpec(transform="days", column="order_date"),
    )
    # No partitioning → full.
    assert by_name["order"].materialization is Materialization.FULL


def test_explicit_materialization_wins_over_the_derived_default() -> None:
    project, _ = load_fixture("minimal")
    model = """\
spec_version: 1
entities:
  event:
    grain: one row per event
    key: [event_id]
    partition_by: [days(occurred_at)]
    materialization: full
    fields:
      event_id: {type: string, required: true}
      kind: {type: string}
      occurred_at: {type: timestamp}
"""
    mapping = """\
mapping_version: 1
source: raw__events
target: event
key:
  event_id: {from: "$.id", transform: [to_string]}
fields:
  occurred_at: {from: "$.ts"}
"""
    ir = build_project_ir(load_project({"entity_model": model, "mapping": mapping}))
    assert ir.entities[0].materialization is Materialization.FULL


def test_only_reachable_metrics_are_lowered() -> None:
    project, catalog = load_fixture("ecom_basic")
    ir = build_project_ir(project, catalog)
    assert [m.name for m in ir.metrics] == [
        "average_order_value",
        "gross_revenue",
        "order_count",
    ]
    assert ir.unreachable == (UnreachableMetric(name="margin", missing=("cogs",)),)
    aov = ir.metrics[0]
    assert aov.depends_on == ("gross_revenue", "order_count")
    assert aov.ratio is not None
    gross = ir.metrics[1]
    assert gross.expr is not None and gross.expr.sql == "unit_price * quantity"
    assert gross.agg == "sum"
    assert gross.depends_on == ("quantity", "unit_price")


def test_relationships_are_lowered_sorted() -> None:
    project, catalog = load_fixture("ecom_basic")
    ir = build_project_ir(project, catalog)
    (rel,) = ir.relationships
    assert rel.name == "item_of_order"
    assert rel.from_entity == "order_item"
    assert rel.to_entity == "order"
    assert rel.via == (("order_id", "order_id"),)


def test_marts_are_not_lowered_before_m5() -> None:
    """ecom_basic's mart document parses but does not lower — mart flattening
    is the M5 milestone (RFC 0010); the IR carries no marts."""
    project, catalog = load_fixture("ecom_basic")
    assert project.marts is not None
    assert build_project_ir(project, catalog).marts == ()


def test_fingerprint_is_stable_across_builds() -> None:
    project, catalog = load_fixture("ecom_basic")
    first = project_fingerprint(build_project_ir(project, catalog))
    second = project_fingerprint(build_project_ir(project, catalog))
    assert first == second
    assert first.startswith("blm1:")


def test_typecheck_failures_are_batched_across_mappings() -> None:
    model = """\
spec_version: 1
entities:
  event:
    grain: one row per event
    key: [event_id]
    fields:
      event_id: {type: string, required: true}
      amount: {type: "decimal(10,2)"}
      kind: {type: string}
"""
    mapping = """\
mapping_version: 1
source: raw__events
target: event
key:
  event_id: {from: "$.id", transform: [to_string]}
fields:
  amount: {from: "$.amount", transform: [{to_decimal: [12, 4]}]}
  kind: {from: "$.kind", transform: [pars_ts]}
"""
    project = load_project({"entity_model": model, "mapping": mapping})
    with pytest.raises(TypeCheckError) as excinfo:
        build_project_ir(project)
    error = excinfo.value
    assert len(error.collected) == 2
    assert "mapping[raw__events->event]: fields.amount" in str(error)
    assert "mapping[raw__events->event]: fields.kind.transform[0]" in str(error)
    assert "closest match: 'parse_ts'" in str(error)


def test_multiple_mappings_per_entity_refuse_until_multi_source() -> None:
    project, _ = load_fixture("minimal")
    sources = {
        "entity_model": """\
spec_version: 1
entities:
  event:
    grain: one row per event
    key: [event_id]
    fields:
      event_id: {type: string, required: true}
""",
        "mapping_a": """\
mapping_version: 1
source: src_a
target: event
key:
  event_id: {from: "$.id", transform: [to_string]}
""",
        "mapping_b": """\
mapping_version: 1
source: src_b
target: event
key:
  event_id: {from: "$.id", transform: [to_string]}
""",
    }
    with pytest.raises(ResolutionError, match="multi_source milestone"):
        build_project_ir(load_project(sources))
