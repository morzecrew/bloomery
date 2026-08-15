"""Mart flattening (RFC 0010 §5.4–§5.5): the wide-schema shape, transitive
chains, prefixes, date-role expansion, and every validation rule's trigger
plus its nearest non-trigger — violations as guardrail leaves, never raises."""

from __future__ import annotations

import pytest

from bloomery import build_project_ir, load_project
from bloomery.errors import (
    FanoutRisk,
    GrainViolation,
    GuardrailError,
    HistoricalFanout,
    MartMissingTimeDimension,
    MeasureRef,
)
from bloomery.ir import (
    DimensionRef,
    MartJoinIR,
    Materialization,
    PartitionSpec,
    ProjectIR,
)
from bloomery.ir import OK_COLUMN
from bloomery.marts import DATE_BUCKETS, HAS_QUALITY_FLAGS, MartLowering, lower_marts
from bloomery.spec import MartSet
from bloomery.typing import BoolType, DateType
from support.compiling import load_fixture
from support.steps import registry_for
from support.plan_ir import column as plan_column
from support.plan_ir import entity as plan_entity
from support.plan_ir import project as plan_project
from support.plan_ir import quality_rule as plan_rule

pytestmark = pytest.mark.unit

# A three-entity chain (order_item → order → customer) with one deliberate
# one_to_many relationship, one declared-but-unmapped entity (warehouse), and
# an int base column named like a date-role bucket (ordered_day) — every
# validation rule finds its trigger here.
_SOURCES = {
    "entity_model": """\
spec_version: 1
entities:
  order_item:
    grain: one row per line on an order
    key: [order_id, line_no]
    fields:
      order_id: {type: string, required: true}
      line_no: {type: int, required: true}
      amount: {type: "decimal(12,4)"}
      order_date: {type: date}
      ship_date: {type: date}
      ordered_day: {type: int}
  order:
    grain: one row per order
    key: [order_id]
    fields:
      order_id: {type: string, required: true}
      customer_id: {type: string}
      warehouse_id: {type: string}
  customer:
    grain: one row per customer
    key: [customer_id]
    fields:
      customer_id: {type: string, required: true}
      region: {type: string}
  warehouse:
    grain: one row per warehouse
    key: [warehouse_id]
    fields:
      warehouse_id: {type: string, required: true}
relationships:
  - name: item_of_order
    from: order_item
    to: order
    via: {order_id: order_id}
    cardinality: many_to_one
  - name: order_of_customer
    from: order
    to: customer
    via: {customer_id: customer_id}
    cardinality: many_to_one
  - name: items_of_order
    from: order
    to: order_item
    via: {order_id: order_id}
    cardinality: one_to_many
  - name: order_of_warehouse
    from: order
    to: warehouse
    via: {warehouse_id: warehouse_id}
    cardinality: many_to_one
""",
    "mapping_items": """\
mapping_version: 1
source: src__items
target: order_item
key:
  order_id: {from: "$.oid", transform: [to_string]}
  line_no: {from: "$.line", transform: [to_int]}
fields:
  amount: {from: "$.amount"}
  order_date: {from: "$.od", transform: [{parse_date: ISO8601}]}
  ship_date: {from: "$.sd", transform: [{parse_date: ISO8601}]}
  ordered_day: {from: "$.odd", transform: [to_int]}
""",
    "mapping_orders": """\
mapping_version: 1
source: src__orders
target: order
key:
  order_id: {from: "$.id", transform: [to_string]}
fields:
  customer_id: {from: "$.cid", transform: [to_string]}
""",
    "mapping_customers": """\
mapping_version: 1
source: src__customers
target: customer
key:
  customer_id: {from: "$.id", transform: [to_string]}
fields:
  region: {from: "$.region"}
""",
    "metrics": """\
metrics_version: 1
metrics:
  revenue:
    grain: order_item
    additivity: additive
    agg: sum
    expr: "amount"
  order_count:
    grain: order
    additivity: additive
    agg: count
    expr: "order_id"
""",
}


def _draft() -> ProjectIR:
    return build_project_ir(load_project(_SOURCES))


def _mart_set(marts_yaml: str) -> MartSet:
    project = load_project({**_SOURCES, "marts": marts_yaml})
    assert project.marts is not None
    return project.marts


def _violations(marts_yaml: str) -> tuple[GuardrailError, ...]:
    lowering = lower_marts(_mart_set(marts_yaml), _draft())
    assert lowering.marts == ()  # a mart with any violation contributes no IR
    return lowering.violations


def _as_type2(entity: str) -> dict[str, str]:
    """``_SOURCES`` with one entity declared ``scd: type2``.

    One added line is the whole difference RFC 0023 D1/D2 refuse on, so the
    tests below are written as that line rather than as a second corpus: what
    they discriminate is the *combination*, and a separate document would let
    an unrelated difference stand in for it.
    """
    anchor = f"  {entity}:\n"
    assert anchor in _SOURCES["entity_model"]
    return {
        **_SOURCES,
        "entity_model": _SOURCES["entity_model"].replace(anchor, f"{anchor}    scd: type2\n", 1),
    }


def _historical(entity: str, marts_yaml: str) -> MartLowering:
    """The whole lowering for ``marts_yaml`` with ``entity`` made historical.

    The lowering rather than its violations, because "a mart with any violation
    contributes no IR" is half the refusal contract: an implementation that
    reported ``HistoricalFanout`` *and* still emitted the multiplying mart would
    satisfy a violations-only assertion. ``_violations`` above pins that half
    with its own assert; this helper cannot, because one of its callers is the
    case where the mart legitimately lowers.
    """
    sources = _as_type2(entity)
    project = load_project({**sources, "marts": marts_yaml})
    assert project.marts is not None
    return lower_marts(project.marts, build_project_ir(load_project(sources)))


# ....................... #
# Flattening shape (RFC 0010 §5.1–§5.4)


def test_transitive_chain_flattens_prefixed_in_authored_order() -> None:
    lowering = lower_marts(
        _mart_set(
            """\
marts_version: 1
marts:
  items:
    grain: order_item
    base: order_item
    flatten:
      - {via: item_of_order, prefix: order_}
      - {via: order_of_customer, prefix: customer_}
      - {date: order_date, role: ordered_at}
    measures: [revenue]
    partition_by: [days(ordered_at_day)]
    cost_hint: 3
"""
        ),
        _draft(),
    )
    assert lowering.violations == ()
    (mart,) = lowering.marts
    assert [column.name for column in mart.columns] == [
        "amount",
        "customer_customer_id",
        "customer_region",
        "line_no",
        "order_customer_id",
        "order_date",
        "order_id",
        "order_order_id",
        "ordered_at_day",
        "ordered_at_month",
        "ordered_at_quarter",
        "ordered_at_week",
        "ordered_at_year",
        "ordered_day",
        "ship_date",
    ]
    # order_of_customer is reachable only because item_of_order flattened
    # first — the chain join keys off the earlier join's flattened column.
    assert mart.joins == (
        MartJoinIR(
            relationship="item_of_order",
            entity="order",
            prefix="order_",
            on=(("order_id", "order_id"),),
        ),
        MartJoinIR(
            relationship="order_of_customer",
            entity="customer",
            prefix="customer_",
            on=(("order_customer_id", "customer_id"),),
        ),
    )
    region = next(column for column in mart.columns if column.name == "customer_region")
    assert (region.source_entity, region.source_column) == ("customer", "region")
    assert region.ref is None
    assert mart.measures == ("revenue",)
    assert mart.partition_by == (PartitionSpec(transform="days", column="ordered_at_day"),)
    assert mart.materialization is Materialization.INCREMENTAL_BY_PARTITION
    assert mart.cost_hint == 3


def test_date_role_expands_to_exactly_the_five_buckets() -> None:
    assert DATE_BUCKETS == ("day", "week", "month", "quarter", "year")
    lowering = lower_marts(
        _mart_set(
            """\
marts_version: 1
marts:
  items:
    grain: order_item
    base: order_item
    flatten:
      - {date: ship_date, role: shipped}
"""
        ),
        _draft(),
    )
    (mart,) = lowering.marts
    buckets = [column for column in mart.columns if column.ref is not None]
    assert [column.name for column in buckets] == [
        f"shipped_{bucket}" for bucket in sorted(DATE_BUCKETS)
    ]
    for column in buckets:
        assert column.type == DateType()
        assert (column.source_entity, column.source_column) == ("order_item", "ship_date")
        assert column.ref is not None
        assert column.ref.role == "shipped"
        assert column.ref.qualified == column.name


def test_every_flattened_column_is_a_requestable_dimension() -> None:
    lowering = lower_marts(
        _mart_set(
            """\
marts_version: 1
marts:
  items:
    grain: order_item
    base: order_item
    flatten:
      - {via: item_of_order, prefix: order_}
      - {date: order_date, role: placed}
"""
        ),
        _draft(),
    )
    (mart,) = lowering.marts
    # RFC 0010 §10: every flattened column is a dimension, sorted by
    # qualified name — which equals the column name for buckets and plain
    # columns alike.
    assert [dimension.column for dimension in mart.dimensions] == [
        column.name for column in mart.columns
    ]
    assert [dimension.ref.qualified for dimension in mart.dimensions] == [
        column.name for column in mart.columns
    ]
    plain = next(d for d in mart.dimensions if d.column == "order_customer_id")
    assert plain.ref == DimensionRef(dimension="order_customer_id")


def test_two_roles_may_share_a_source_column() -> None:
    # Rare but legal (RFC 0010 §5.2): the same date under two roles.
    lowering = lower_marts(
        _mart_set(
            """\
marts_version: 1
marts:
  items:
    grain: order_item
    base: order_item
    flatten:
      - {date: order_date, role: placed}
      - {date: order_date, role: booked}
"""
        ),
        _draft(),
    )
    assert lowering.violations == ()
    (mart,) = lowering.marts
    roles = sorted({column.ref.role for column in mart.columns if column.ref is not None})
    assert roles == ["booked", "placed"]


def test_explicit_materialization_wins_over_the_partition_default() -> None:
    lowering = lower_marts(
        _mart_set(
            """\
marts_version: 1
marts:
  items:
    grain: order_item
    base: order_item
    flatten:
      - {date: order_date, role: placed}
    partition_by: [days(placed_day)]
    materialization: full
"""
        ),
        _draft(),
    )
    (mart,) = lowering.marts
    assert mart.materialization is Materialization.FULL


def test_unpartitioned_mart_defaults_to_full() -> None:
    lowering = lower_marts(
        _mart_set("marts_version: 1\nmarts:\n  items: {grain: order_item, base: order_item}\n"),
        _draft(),
    )
    (mart,) = lowering.marts
    assert mart.materialization is Materialization.FULL
    assert mart.joins == ()
    assert mart.measures == ()


def test_no_marts_document_lowers_to_the_empty_tuple() -> None:
    lowering = lower_marts(None, _draft())
    assert lowering.marts == ()
    assert lowering.violations == ()


def test_a_broken_mart_never_blocks_a_clean_sibling() -> None:
    lowering = lower_marts(
        _mart_set(
            """\
marts_version: 1
marts:
  broken:
    grain: order
    base: order_item
  clean:
    grain: order_item
    base: order_item
"""
        ),
        _draft(),
    )
    assert [mart.name for mart in lowering.marts] == ["clean"]
    (violation,) = lowering.violations
    assert isinstance(violation, GrainViolation)


# ....................... #
# Validation rules (RFC 0010 §5.5) — trigger and nearest non-trigger


def test_unknown_base_entity_is_refused() -> None:
    (violation,) = _violations(
        "marts_version: 1\nmarts:\n  items: {grain: shipment, base: shipment}\n"
    )
    assert type(violation) is GuardrailError
    assert violation.source_path == "marts: marts.items.base"
    assert "no mapping lowers" in str(violation)


def test_mart_grain_must_equal_the_base_grain() -> None:
    (violation,) = _violations(
        "marts_version: 1\nmarts:\n  items: {grain: order, base: order_item}\n"
    )
    assert isinstance(violation, GrainViolation)
    assert violation.source_path == "marts: marts.items.grain"
    assert "exactly its base grain" in str(violation)
    assert "one row per line on an order" in str(violation)
    # The mart header is wrong, not any measure — so the suggestion is empty,
    # and empty is a fact rather than a search that was skipped (RFC 0020 D7).
    assert violation.offending_measures == ()


def test_via_step_must_name_a_declared_relationship() -> None:
    (violation,) = _violations(
        """\
marts_version: 1
marts:
  items:
    grain: order_item
    base: order_item
    flatten:
      - {via: item_of_ordr, prefix: order_}
"""
    )
    assert isinstance(violation, FanoutRisk)
    assert violation.source_path == "marts: marts.items.flatten[0].via"
    assert "no declared relationship 'item_of_ordr'" in str(violation)
    assert "'item_of_order'" in str(violation)  # known names listed


def test_one_to_many_flatten_is_fanout_risk() -> None:
    (violation,) = _violations(
        """\
marts_version: 1
marts:
  orders:
    grain: order
    base: order
    flatten:
      - {via: items_of_order, prefix: item_}
"""
    )
    assert isinstance(violation, FanoutRisk)
    assert "one_to_many" in str(violation)
    assert "multiplies the mart's own rows" in str(violation)


def test_unreachable_relationship_is_fanout_risk() -> None:
    # order_of_customer joins from 'order', which is not flattened yet —
    # the non-trigger (item_of_order first) is the happy chain test above.
    (violation,) = _violations(
        """\
marts_version: 1
marts:
  items:
    grain: order_item
    base: order_item
    flatten:
      - {via: order_of_customer, prefix: customer_}
"""
    )
    assert isinstance(violation, FanoutRisk)
    assert "neither the base nor a previously flattened entity" in str(violation)
    assert "authored order" in str(violation)


# ....................... #
# Historical dimensions (RFC 0023 D1/D2) — the join that has no validity
# predicate, and the base whose grain counts revisions.

_CHAIN_TO_CUSTOMER = """\
marts_version: 1
marts:
  items:
    grain: order_item
    base: order_item
    flatten:
      - {via: item_of_order, prefix: order_}
      - {via: order_of_customer, prefix: customer_}
"""

_ORDERS_BASE = """\
marts_version: 1
marts:
  orders:
    grain: order
    base: order
"""


def test_flattening_a_type2_entity_is_historical_fanout() -> None:
    lowering = _historical("customer", _CHAIN_TO_CUSTOMER)
    # The other half of the refusal: the multiplying mart must not reach the IR.
    # Reporting the violation and emitting the mart anyway would satisfy an
    # assertion over the violations alone.
    assert lowering.marts == ()
    (violation,) = lowering.violations
    assert isinstance(violation, HistoricalFanout)
    assert violation.source_path == "marts: marts.items.flatten[1].via"
    assert "no validity predicate" in str(violation)
    assert "version count" in str(violation)
    # The declared cardinality is correct and must not be what the reader is
    # sent to check — that is the whole reason this is not a FanoutRisk.
    assert not isinstance(violation, FanoutRisk)
    assert "claim about the domain" in str(violation)


def test_the_same_flatten_over_a_type1_entity_is_clean() -> None:
    # The nearest non-trigger: one line apart from the case above.
    lowering = lower_marts(_mart_set(_CHAIN_TO_CUSTOMER), _draft())
    assert lowering.violations == ()
    assert [m.name for m in lowering.marts] == ["items"]


def test_a_type2_base_is_historical_fanout() -> None:
    lowering = _historical("order", _ORDERS_BASE)
    assert lowering.marts == ()
    (violation,) = lowering.violations
    assert isinstance(violation, HistoricalFanout)
    assert violation.source_path == "marts: marts.orders.base"
    assert "counts revisions" in str(violation)


def test_a_one_to_many_flatten_onto_a_type2_entity_reports_both_reasons() -> None:
    """Two independent faults, one round-trip.

    ``one_to_many`` is a property of the relationship and ``scd: type2`` a
    property of the entity, so a step can be wrong in both ways at once and
    fixing either alone leaves the other. Behind an early return the second
    reason was never reported; ordering the two differently would only have
    suppressed the other one instead.
    """
    lowering = _historical(
        "order_item",
        """\
marts_version: 1
marts:
  orders:
    grain: order
    base: order
    flatten:
      - {via: items_of_order, prefix: item_}
""",
    )
    assert lowering.marts == ()
    historical, fanout = lowering.violations
    assert isinstance(historical, HistoricalFanout)
    assert "scd: type2" in str(historical)
    assert isinstance(fanout, FanoutRisk)
    assert "one_to_many" in str(fanout)
    assert {v.source_path for v in lowering.violations} == {
        "marts: marts.orders.flatten[0].via"
    }


def test_an_unreachable_chain_onto_a_type2_entity_reports_both_reasons() -> None:
    lowering = _historical(
        "customer",
        """\
marts_version: 1
marts:
  items:
    grain: order_item
    base: order_item
    flatten:
      - {via: order_of_customer, prefix: customer_}
""",
    )
    assert lowering.marts == ()
    historical, unreachable = lowering.violations
    assert isinstance(historical, HistoricalFanout)
    assert isinstance(unreachable, FanoutRisk)
    assert "neither the base nor a previously flattened entity" in str(unreachable)


def test_an_unmapped_type2_target_reports_only_the_unmapped_leaf() -> None:
    """An entity no mapping lowers has no ``scd`` to read, and its own leaf is
    the one worth reporting — ``warehouse`` is declared and never mapped."""
    lowering = _historical(
        "warehouse",
        """\
marts_version: 1
marts:
  orders:
    grain: order
    base: order
    flatten:
      - {via: order_of_warehouse, prefix: wh_}
""",
    )
    (violation,) = lowering.violations
    assert type(violation) is GuardrailError
    assert "no mapping lowers" in str(violation)


def test_the_same_base_as_type1_is_clean() -> None:
    lowering = lower_marts(_mart_set(_ORDERS_BASE), _draft())
    assert lowering.violations == ()
    assert [m.name for m in lowering.marts] == ["orders"]


def test_a_type2_entity_the_mart_never_reaches_is_not_refused() -> None:
    """The refusal is the *combination*, never the feature (RFC 0023 §4).

    ``customer`` is historical and the mart neither flattens it nor is based on
    it — so the mart lowers, and the silver model keeping that history is
    untouched.
    """
    marts = """\
marts_version: 1
marts:
  items:
    grain: order_item
    base: order_item
    flatten:
      - {via: item_of_order, prefix: order_}
"""
    lowering = _historical("customer", marts)
    assert lowering.violations == ()
    assert [m.name for m in lowering.marts] == ["items"]


def test_flattening_an_unmapped_entity_is_refused() -> None:
    (violation,) = _violations(
        """\
marts_version: 1
marts:
  orders:
    grain: order
    base: order
    flatten:
      - {via: order_of_warehouse, prefix: wh_}
"""
    )
    assert type(violation) is GuardrailError
    assert "no mapping lowers" in str(violation)
    assert "unbuilt entity" in str(violation)


def test_post_prefix_collisions_are_errors_never_renamed() -> None:
    # The same relationship twice under one prefix: every column collides.
    violations = _violations(
        """\
marts_version: 1
marts:
  orders:
    grain: order
    base: order
    flatten:
      - {via: order_of_customer, prefix: cust_}
      - {via: order_of_customer, prefix: cust_}
"""
    )
    assert [violation.source_path for violation in violations] == [
        "marts: marts.orders.flatten[1].prefix",
        "marts: marts.orders.flatten[1].prefix",
    ]
    assert "collides" in str(violations[0])
    assert "never auto-renamed" in str(violations[0])


def test_date_role_bucket_colliding_with_a_flattened_column_is_an_error() -> None:
    # The base carries an int column literally named ordered_day.
    violations = _violations(
        """\
marts_version: 1
marts:
  items:
    grain: order_item
    base: order_item
    flatten:
      - {date: order_date, role: ordered}
"""
    )
    (violation,) = violations
    assert violation.source_path == "marts: marts.items.flatten[0].role"
    assert "'ordered_day' collides" in str(violation)


def test_duplicate_date_role_is_refused() -> None:
    (violation,) = _violations(
        """\
marts_version: 1
marts:
  items:
    grain: order_item
    base: order_item
    flatten:
      - {date: order_date, role: placed}
      - {date: ship_date, role: placed}
"""
    )
    assert violation.source_path == "marts: marts.items.flatten[1].role"
    assert "more than once" in str(violation)


def test_date_role_source_must_be_a_base_column() -> None:
    (violation,) = _violations(
        """\
marts_version: 1
marts:
  items:
    grain: order_item
    base: order_item
    flatten:
      - {date: shipped_on, role: shipped}
"""
    )
    assert violation.source_path == "marts: marts.items.flatten[0].date"
    assert "not a column of base entity 'order_item'" in str(violation)


def test_date_role_source_must_be_date_or_timestamp_typed() -> None:
    (violation,) = _violations(
        """\
marts_version: 1
marts:
  items:
    grain: order_item
    base: order_item
    flatten:
      - {date: amount, role: amounted}
"""
    )
    assert violation.source_path == "marts: marts.items.flatten[0].date"
    assert "has type 'decimal(12, 4)'" in str(violation)
    assert "date or timestamp" in str(violation)


def test_date_role_source_type_message_names_scalar_types_too() -> None:
    (violation,) = _violations(
        """\
marts_version: 1
marts:
  items:
    grain: order_item
    base: order_item
    flatten:
      - {date: line_no, role: lined}
"""
    )
    assert "has type 'int'" in str(violation)


def test_measure_must_name_a_declared_metric() -> None:
    violations = _violations(
        """\
marts_version: 1
marts:
  items:
    grain: order_item
    base: order_item
    flatten:
      - {date: order_date, role: placed}
    measures: [revenu]
"""
    )
    (violation,) = violations
    assert violation.source_path == "marts: marts.items.measures.revenu"
    assert "no declared metric 'revenu'" in str(violation)
    assert "'revenue'" in str(violation)  # known names listed


def test_unreachable_metric_cannot_be_a_measure() -> None:
    # ecom_basic's margin is the corpus unreachable case (missing cogs).
    project, catalog = load_fixture("ecom_basic")
    draft = build_project_ir(project, catalog)
    marts_yaml = """\
marts_version: 1
marts:
  items:
    grain: order_item
    base: order_item
    flatten:
      - {date: order_date, role: ordered}
    measures: [margin]
"""
    mart_project = load_project(
        {
            "marts": marts_yaml,
            "entity_model": "spec_version: 1\nentities:\n  e:\n    grain: g\n    key: [k]\n"
            "    fields:\n      k: {type: string, required: true}\n",
        }
    )
    assert mart_project.marts is not None
    lowering = lower_marts(mart_project.marts, draft)
    (violation,) = lowering.violations
    assert violation.source_path == "marts: marts.items.measures.margin"
    assert "unreachable" in str(violation)
    assert "cogs" in str(violation)


def test_measure_grain_must_strictly_equal_mart_grain() -> None:
    (violation,) = _violations(
        """\
marts_version: 1
marts:
  items:
    grain: order_item
    base: order_item
    flatten:
      - {date: order_date, role: placed}
    measures: [order_count]
"""
    )
    assert isinstance(violation, GrainViolation)
    assert violation.source_path == "marts: marts.items.measures.order_count"
    assert "grain 'order' (one row per order)" in str(violation)
    assert "must strictly equal mart grain" in str(violation)
    # The same pair the sentence states, as data (RFC 0020 §5.4): which
    # measure is at odds with the mart grain, and the grain it is at.
    assert violation.offending_measures == (MeasureRef(measure="order_count", grain="order"),)
    assert "duplicated once per 'order_item' row" in str(violation)


def test_measure_carrying_mart_requires_a_date_role() -> None:
    (violation,) = _violations(
        """\
marts_version: 1
marts:
  items:
    grain: order_item
    base: order_item
    measures: [revenue]
"""
    )
    assert isinstance(violation, MartMissingTimeDimension)
    assert violation.source_path == "marts: marts.items"
    assert "agg_time_dimension" in str(violation)


def test_measureless_mart_needs_no_date_role() -> None:
    lowering = lower_marts(
        _mart_set("marts_version: 1\nmarts:\n  items: {grain: order_item, base: order_item}\n"),
        _draft(),
    )
    assert lowering.violations == ()


# ....................... #
# The RFC 0016 §5.5 amendment: has_quality_flags, and the reject-table refusal


def test_a_reject_table_can_never_be_a_mart_base() -> None:
    """RFC 0016 D15. Refused on the *name*, ahead of the generic
    "no mapping lowers this entity" message, so the author reads why rather
    than a missing-entity puzzle."""
    (violation,) = _violations(
        "marts_version: 1\nmarts:\n"
        "  rejects: {grain: order_item__reject, base: order_item__reject}\n"
    )
    assert type(violation) is GuardrailError
    assert violation.source_path == "marts: marts.rejects.base"
    message = str(violation)
    assert "must be a silver entity, never a quarantine surface" in message
    assert "not queryable through the semantic layer" in message
    assert "base the mart on 'order_item'" in message
    # And it points at the surface that *is* the analytic answer.
    assert "gold.mart_data_quality" in message


def test_a_mart_over_a_quality_carrying_base_flattens_has_quality_flags() -> None:
    ir = build_project_ir(*load_fixture("semi_additive_inventory"))
    inventory = next(mart for mart in ir.marts if mart.name == "inventory")
    column = next(c for c in inventory.columns if c.name == HAS_QUALITY_FLAGS)
    assert isinstance(column.type, BoolType)
    # Derived from the generated ``_quality_ok`` (D23), never re-evaluated.
    assert (column.source_entity, column.source_column) == ("inventory_level", OK_COLUMN)
    # An ordinary dimension: that is what makes "revenue excluding flagged
    # rows" a plain MetricRequest rather than a new planner concept.
    assert any(
        dimension.column == HAS_QUALITY_FLAGS and dimension.ref.role is None
        for dimension in inventory.dimensions
    )


def test_a_quality_free_base_gets_no_quality_dimension() -> None:
    """A constant-FALSE dimension on a mart whose base evaluates nothing would
    read as "no flagged rows" instead of "nothing to flag"."""
    lowering = lower_marts(
        _mart_set(
            "marts_version: 1\nmarts:\n  items: {grain: order_item, base: order_item}\n"
        ),
        _draft(),
    )
    (mart,) = lowering.marts
    assert HAS_QUALITY_FLAGS not in {column.name for column in mart.columns}


def test_a_step_produced_base_gets_no_quality_dimension() -> None:
    """The same rule as the test above, on the base that made it a bug.

    A step's rows are written by its generated wrapper, which projects exactly
    the manifest's declared columns — so there is no `_quality_flags` to reduce
    and no `_quality_ok` to negate. The entity still *carries* a rule: an
    `expression` with `on_fail: fail` lowers to a blocking audit over the
    relation, which stops the run rather than marking a row, so nothing
    survives to be flagged.

    Before this, the flattener saw `base.quality` and projected
    `NOT customer._quality_ok` anyway. The mart compiled, matched its golden,
    and failed on its first execution with a binder error naming a generated
    column the author never wrote — which is what
    `tests/execution/test_identity_resolution.py` now runs.
    """
    ir = build_project_ir(
        *load_fixture("identity_resolution"), steps=registry_for("identity_resolution")
    )
    customer = next(entity for entity in ir.entities if entity.name == "customer")
    assert customer.produced_by is not None
    assert customer.quality, "the fixture must carry a rule for this to prove anything"

    customers = next(mart for mart in ir.marts if mart.name == "customers")
    assert HAS_QUALITY_FLAGS not in {column.name for column in customers.columns}


def test_a_base_column_colliding_with_the_quality_dimension_is_refused() -> None:
    """Collisions are errors, never auto-renamed (RFC 0010 D3) — including
    against the dimension RFC 0016 §5.5 reserves. Built from a hand-made draft
    because the spec layer has no reason to reserve the name *and* the mart
    layer has every reason to refuse it."""
    draft = plan_project(
        entities=(
            plan_entity(
                name="order_item",
                grain="one row per line on an order",
                key=("order_id",),
                columns=(plan_column("order_id"), plan_column(HAS_QUALITY_FLAGS)),
                quality=(plan_rule(),),
            ),
        )
    )
    marts = load_project(
        {
            **_SOURCES,
            "marts": "marts_version: 1\nmarts:\n  items: {grain: order_item, base: order_item}\n",
        }
    ).marts
    assert marts is not None
    lowering = lower_marts(marts, draft)
    assert lowering.marts == ()
    (violation,) = lowering.violations
    assert type(violation) is GuardrailError
    assert violation.source_path == "marts: marts.items.base"
    assert "already" in str(violation)
    assert "never auto-renamed" in str(violation)
