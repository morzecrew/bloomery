"""The guardrail stage (RFC 0006 §5.1, D2, D9): batched project-wide
aggregation sorted by (source_path, type name), purity/idempotence of the
amendments, and the M4 acceptance — `fanout_trap` and
`semi_additive_inventory` fail closed with useful messages."""

from __future__ import annotations

import pytest

from bloomery import build_project_ir, load_project
from bloomery.errors import (
    AdditivityViolation,
    GrainMismatch,
    GrainViolation,
    GuardrailError,
    HistoricalFanout,
    NonAdditiveWithoutComponents,
    SpecParseError,
)
from bloomery.guardrails import check_guardrails
from bloomery.quality import QUALITY_METRICS
from support.compiling import fixture_sources, load_fixture

pytestmark = pytest.mark.unit


# ....................... #
# Acceptance: fanout_trap fails closed (RFC 0006 §12; mart level RFC 0006 D10)


def test_fanout_trap_fails_closed_with_both_grains_named() -> None:
    project, catalog = load_fixture("fanout_trap")
    with pytest.raises(GuardrailError) as excinfo:
        build_project_ir(project, catalog)
    error = excinfo.value
    # Mart-level and entity-level violations batch into ONE aggregate: the
    # derivation and metric GrainMismatch leaves plus the mart's
    # GrainViolation for the order-grain measure on the item-grain mart.
    assert [type(leaf) for leaf in error.collected] == [
        GrainMismatch,
        GrainViolation,
        GrainMismatch,
    ]
    message = str(error)
    assert "one row per line on an order" in message
    assert "one row per order" in message
    assert "relationship 'item_of_order' (many_to_one)" in message
    assert "Fix: add an explicit aggregation/allocation over 'order_item'" in message
    # The mart-level refusal (RFC 0006 §5.7 worked-example quality).
    assert "measure 'shipping_cost' has grain 'order' (one row per order)" in message
    assert "duplicated once per 'order_item' row" in message
    assert "Fix: remove it from this mart's measures" in message


def test_fanout_trap_violations_sort_by_source_path() -> None:
    project, catalog = load_fixture("fanout_trap")
    with pytest.raises(GuardrailError) as excinfo:
        build_project_ir(project, catalog)
    paths = [leaf.source_path for leaf in excinfo.value.collected]
    assert paths == [
        "mapping[wms__order_lines->order_item]: fields.landed_cost",
        "marts: marts.order_items.measures.shipping_cost",
        "metrics: metrics.landed_revenue",
    ]
    assert paths == sorted(p or "" for p in paths)


# ....................... #
# Acceptance: scd2_mart_refusal fails closed on both sides (RFC 0023 D1/D2)


def test_scd2_mart_refusal_fails_closed_on_both_sides() -> None:
    project, catalog = load_fixture("scd2_mart_refusal")
    with pytest.raises(GuardrailError) as excinfo:
        build_project_ir(project, catalog)
    leaves = excinfo.value.collected
    assert [type(leaf) for leaf in leaves] == [HistoricalFanout, HistoricalFanout]
    assert [leaf.source_path for leaf in leaves] == [
        "marts: marts.customers.base",
        "marts: marts.orders.flatten[0].via",
    ]
    message = str(excinfo.value)
    # Each side names its own mechanism: the base counts revisions, the
    # flatten multiplies. One error class, two readings, neither generic.
    assert "counts revisions" in message
    assert "matches every version of each 'customer' key" in message
    # And each routes to the fix its own side has. Only the flatten can be
    # qualified by an anchor (RFC 0023 §5.3); a base has nothing to qualify,
    # so sending its author to `as_of:` would be a dead end.
    assert message.count("Fix: declare an anchor") == 1
    assert message.count("Fix: declare the entity scd: type1, or build a type1") == 1


def test_the_same_project_without_the_scd2_line_compiles_clean() -> None:
    """The one-line discrimination (RFC 0023 §6).

    ``scd: type2`` is the whole difference between the fixture and a project
    that lowers two marts — so the refusal is pinned to the *combination*
    rather than to anything else about the documents.
    """
    sources = dict(fixture_sources("scd2_mart_refusal"))
    sources["entity_model"] = sources["entity_model"].replace("    scd: type2\n", "")
    project = load_project(sources)
    # Asserted on the parsed model, not on the text: the fixture's own comment
    # quotes the line it is about, so a substring check over the document
    # would be satisfied by prose.
    assert project.entity_model.entities["customer"].scd == "type1"
    _project, catalog = load_fixture("scd2_mart_refusal")
    ir = build_project_ir(project, catalog)
    assert [mart.name for mart in ir.marts] == ["customers", "orders"]


def test_a_type2_entity_with_no_mart_still_lowers() -> None:
    """RFC 0023 §8: ``scd: type2`` as a silver target is untouched. The
    fixture that owns that coverage must keep compiling."""
    project, catalog = load_fixture("scd2_customers")
    ir = build_project_ir(project, catalog)
    (customer,) = ir.entities
    assert customer.scd == "type2"


# ....................... #
# Acceptance: semi_additive_inventory refusal variants (RFC 0006 §12)


def _inventory_sources(metrics: str) -> dict[str, str]:
    sources = dict(fixture_sources("semi_additive_inventory"))
    sources["metrics"] = metrics
    return sources


def test_semi_additive_inventory_base_fixture_compiles_clean() -> None:
    project, catalog = load_fixture("semi_additive_inventory")
    ir = build_project_ir(project, catalog)
    # Plus the quality mart's own metrics (RFC 0016 §5.8), which every
    # quality-carrying project gains.
    (metric,) = [m for m in ir.metrics if m.name not in QUALITY_METRICS]
    assert metric.name == "stock_on_hand"
    assert metric.semi_additive is not None
    assert metric.semi_additive.over.dimension == "stock_date"
    assert metric.semi_additive.rule == "last"


def test_missing_over_rule_policy_fails_closed() -> None:
    _project, catalog = load_fixture("semi_additive_inventory")
    broken = load_project(
        _inventory_sources(
            """\
metrics_version: 1
metrics:
  stock_on_hand:
    requires: [stock_level]
    grain: inventory_level
    additivity: semi_additive
    agg: sum
    expr: "stock_level"
"""
        )
    )
    with pytest.raises(GuardrailError) as excinfo:
        build_project_ir(broken, catalog)
    (leaf,) = excinfo.value.collected
    assert isinstance(leaf, AdditivityViolation)
    assert leaf.source_path == "metrics: metrics.stock_on_hand"
    assert "semi_additive: {over, rule}" in str(leaf)


def test_missing_rule_is_a_parse_error() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        load_project(
            _inventory_sources(
                """\
metrics_version: 1
metrics:
  stock_on_hand:
    requires: [stock_level]
    grain: inventory_level
    additivity: semi_additive
    agg: sum
    expr: "stock_level"
    semi_additive: {over: stock_date}
"""
            )
        )
    assert "metrics: metrics.stock_on_hand.semi_additive.rule" in str(excinfo.value.source_path)


def test_non_additive_average_without_ratio_fails_closed() -> None:
    _project, catalog = load_fixture("semi_additive_inventory")
    broken = load_project(
        _inventory_sources(
            """\
metrics_version: 1
metrics:
  stock_on_hand:
    requires: [stock_level]
    grain: inventory_level
    additivity: semi_additive
    agg: sum
    expr: "stock_level"
    semi_additive: {over: stock_date, rule: last}
  average_stock:
    requires: [stock_level]
    grain: inventory_level
    additivity: non_additive
"""
        )
    )
    with pytest.raises(GuardrailError) as excinfo:
        build_project_ir(broken, catalog)
    (leaf,) = excinfo.value.collected
    assert isinstance(leaf, NonAdditiveWithoutComponents)
    assert "'average_stock'" in str(leaf)
    assert "add ratio: {numerator, denominator}" in str(leaf)


# ....................... #
# Batching and ordering (RFC 0006 D2)


def test_violations_with_one_source_path_sort_by_type_name() -> None:
    # One metric, two rules at one source path: net/gross across grains gives
    # GrainMismatch < TaxBasisMismatch, sorted by type name (RFC 0006 D2).
    catalog_text = """\
catalog_version: 1
vertical: v
canonical_fields:
  price: {entity: order_item, type: "decimal(12,4)", unit: currency, tax_basis: net}
  ship: {entity: order, type: "decimal(12,4)", unit: currency, tax_basis: gross}
"""
    model = """\
spec_version: 1
entities:
  order_item:
    grain: one row per line on an order
    key: [order_id]
    fields:
      order_id: {type: string, required: true}
      price: {type: "decimal(12,4)", canonical: price}
  order:
    grain: one row per order
    key: [order_id]
    fields:
      order_id: {type: string, required: true}
      ship: {type: "decimal(12,4)", canonical: ship}
"""
    mapping_items = """\
mapping_version: 1
source: src_items
target: order_item
key:
  order_id: {from: "$.oid", transform: [to_string]}
fields:
  price: {from: "$.price", transform: [{to_decimal: [12, 4]}]}
"""
    mapping_orders = """\
mapping_version: 1
source: src_orders
target: order
key:
  order_id: {from: "$.id", transform: [to_string]}
fields:
  ship: {from: "$.ship", transform: [{to_decimal: [12, 4]}]}
"""
    metrics = """\
metrics_version: 1
metrics:
  broken:
    requires: [price, ship]
    grain: order_item
    additivity: additive
    agg: sum
    expr: "price + ship"
"""
    from bloomery import load_catalog

    project = load_project(
        {
            "entity_model": model,
            "mapping_items": mapping_items,
            "mapping_orders": mapping_orders,
            "metrics": metrics,
        }
    )
    with pytest.raises(GuardrailError) as excinfo:
        build_project_ir(project, load_catalog(catalog_text))
    leaves = excinfo.value.collected
    assert [type(leaf).__name__ for leaf in leaves] == ["GrainMismatch", "TaxBasisMismatch"]
    assert {leaf.source_path for leaf in leaves} == {"metrics: metrics.broken"}


# ....................... #
# Purity and idempotence (RFC 0006 D9)


def test_stage_is_identity_on_a_clean_project() -> None:
    project, catalog = load_fixture("minimal")
    draft = build_project_ir(project, catalog)
    assert check_guardrails(draft, project=project, catalog=catalog) is draft


def test_stage_is_idempotent_on_amended_projects() -> None:
    # ecom_basic, role_playing_dates, and semi_additive_inventory carry marts:
    # the stage's mart re-check finds nothing on the already-lowered IR.
    for name in ("ecom_basic", "path_conflict", "role_playing_dates", "semi_additive_inventory"):
        project, catalog = load_fixture(name)
        amended = build_project_ir(project, catalog)
        assert check_guardrails(amended, project=project, catalog=catalog) is amended
