"""Name-bridge unit tests (RFC 0013 D7): dunder construction keyed on the
primary entity, order-term mapping, the reverse mapping, and the typed
column envelope from a real ``query_spec``."""

from __future__ import annotations

import pytest
from sqlglot import parse_one

from bloomery import ColumnDescriptor, MetricRequest, OrderSpec
from bloomery.errors import PlannerError
from bloomery.planner import TimeGrain
from bloomery.planner.names import (
    ResolvedDimension,
    _column_type,
    bloomery_dimension_name,
    columns_from,
    entity_key,
    group_by_name,
    to_mf_group_by,
    to_mf_metrics,
    to_mf_order,
)
from bloomery.typing import DateType, DecimalType, IntType, StringType
from support.planning import fixture_ir, fixture_mart, make_planner

pytestmark = pytest.mark.unit

STORE = ResolvedDimension(name="store")
ORDERED_MONTH = ResolvedDimension(name="ordered_month", role="ordered", grain=TimeGrain.MONTH)


def test_entity_key_is_the_grain_entity_not_the_mart_name() -> None:
    """The RFC 0013 §5.5 gotcha: a model named ``orders`` with grain
    ``order`` keys dunders on ``order`` — for both key shapes."""
    aov = fixture_ir("non_additive_aov").marts[0]
    assert (aov.name, entity_key(aov)) == ("orders", "order")
    inventory = fixture_mart("semi_additive_inventory", "inventory")  # composite key
    assert (inventory.name, entity_key(inventory)) == ("inventory", "inventory_level")


def test_metric_names_cross_unchanged() -> None:
    assert to_mf_metrics(("revenue", "order_count")) == ("revenue", "order_count")


def test_group_by_names() -> None:
    assert group_by_name(STORE, entity="order") == "order__store"
    assert group_by_name(ORDERED_MONTH, entity="order") == "order__ordered_day__month"
    assert to_mf_group_by((STORE, ORDERED_MONTH), entity="order") == (
        "order__store",
        "order__ordered_day__month",
    )


def test_order_terms_map_with_descending_prefix() -> None:
    names = to_mf_order(
        (OrderSpec("revenue", "desc"), OrderSpec("ordered_month"), OrderSpec("store", "desc")),
        entity="order",
        metrics=("revenue",),
        dimensions={"ordered_month": ORDERED_MONTH, "store": STORE},
    )
    assert names == ("-revenue", "order__ordered_day__month", "-order__store")


def test_reverse_mapping() -> None:
    assert bloomery_dimension_name("store", None) == "store"
    assert bloomery_dimension_name("ordered_day", TimeGrain.MONTH) == "ordered_month"
    assert bloomery_dimension_name("ordered_day", TimeGrain.DAY) == "ordered_day"


def test_columns_from_a_real_query_spec_never_leaks_dunders() -> None:
    plan = make_planner().plan(
        fixture_ir("non_additive_aov"),
        MetricRequest(
            metrics=("average_order_value", "order_count", "revenue"),
            dimensions=("store", "ordered_month"),
        ),
        dialect="duckdb",
    )
    names = [(c.name, c.role) for c in plan.columns]
    assert names == [
        ("store", "dimension"),
        ("ordered_month", "dimension"),
        ("average_order_value", "measure"),
        ("order_count", "measure"),
        ("revenue", "measure"),
    ]
    assert all("__" not in c.name for c in plan.columns)
    types = {c.name: c.type for c in plan.columns}
    assert types["store"] == StringType()
    assert types["ordered_month"] == DateType()
    assert types["average_order_value"] == DecimalType(38, 9)  # ratio → wide decimal
    assert types["order_count"] == IntType()  # count → int
    assert types["revenue"] == DecimalType(12, 4)  # bare column keeps its type


def test_expression_measures_fall_back_to_wide_decimal() -> None:
    # ecom_basic's gross_revenue is `unit_price * quantity` — not a bare column.
    plan = make_planner().plan(
        fixture_ir("ecom_basic"), MetricRequest(metrics=("gross_revenue",)), dialect="duckdb"
    )
    assert plan.columns[0].type == DecimalType(38, 9)


def test_unexpected_group_by_spec_is_a_planner_error() -> None:
    from types import SimpleNamespace

    mart = fixture_ir("non_additive_aov").marts[0]
    bogus = SimpleNamespace(
        input_spec_order=SimpleNamespace(
            group_by_item_specs=(SimpleNamespace(element_name="order"),), metric_specs=()
        )
    )
    with pytest.raises(PlannerError, match="never requests"):
        columns_from(bogus, mart=mart, metrics_by_name={})  # type: ignore[arg-type]


def test_sql_alias_is_the_alias_the_rendered_sql_actually_projects() -> None:
    """RFC 0018 D4, closing RFC 0009 D24.

    ``QueryPlan.columns`` named the *requested* dimension while the SQL
    projected MetricFlow's dunder — so a caller binding a result set by name
    found nothing, and the envelope only worked positionally. This asserts the
    two against each other on the case that exhibits the gap: a categorical
    dimension (entity-qualified) and a date role at a non-day grain
    (entity-qualified *and* grain-suffixed).

    Parsed out of the SQL rather than hard-coded, so a MetricFlow upgrade that
    changes the spelling fails here instead of silently downstream.
    """
    plan = make_planner().plan(
        fixture_ir("non_additive_aov"),
        MetricRequest(
            metrics=("average_order_value", "order_count", "revenue"),
            dimensions=("store", "ordered_month"),
        ),
        dialect="duckdb",
    )
    projected = [
        projection.alias_or_name for projection in parse_one(plan.sql, read="duckdb").expressions
    ]
    assert [column.sql_alias for column in plan.columns] == projected
    by_name = {column.name: column.sql_alias for column in plan.columns}
    assert by_name["store"] == "order__store"
    assert by_name["ordered_month"] == "order__ordered_day__month"
    assert by_name["revenue"] == "revenue", "a measure agrees on both names"
    assert all("__" not in column.name for column in plan.columns), (
        "the dunder belongs to sql_alias alone; name stays the caller's word"
    )


def test_a_column_descriptor_cannot_be_built_positionally() -> None:
    """`sql_alias` was inserted second, not appended.

    That reads better and is a breaking constructor change with a silent
    failure mode: a caller writing the pre-M15 four-argument form
    `ColumnDescriptor("revenue", DecimalType(12, 4), "measure", "Revenue")`
    used to get every field after the first misassigned — the type into
    `sql_alias`, the role into `type`, the label into `role` — with no error
    raised and a frozen dataclass validating nothing.

    Keyword-only turns that into an immediate `TypeError`. Appending the field
    with a default was the alternative and is worse: the only plausible default
    is `name`, which is exactly the defect this field exists to remove, and it
    would be restored for anyone who omits the argument.
    """
    with pytest.raises(TypeError):
        ColumnDescriptor("revenue", "revenue", DecimalType(12, 4), "measure")  # type: ignore[misc]

    built = ColumnDescriptor(
        name="revenue", sql_alias="revenue", type=DecimalType(12, 4), role="measure"
    )
    assert built.type == DecimalType(12, 4)
    assert built.role == "measure"


def test_positional_binding_is_unchanged() -> None:
    """The D24 status quo does not regress: `columns[i]` still lines up with
    projection `i`. That is what every consumer does today, and why the fix is
    an added field rather than a redefined one."""
    plan = make_planner().plan(
        fixture_ir("non_additive_aov"),
        MetricRequest(metrics=("revenue",), dimensions=("store",)),
        dialect="duckdb",
    )
    projected = parse_one(plan.sql, read="duckdb").expressions
    assert len(plan.columns) == len(projected)
    for column, projection in zip(plan.columns, projected, strict=True):
        assert column.sql_alias == projection.alias_or_name


def test_unknown_dimension_column_is_a_planner_error() -> None:
    mart = fixture_ir("non_additive_aov").marts[0]
    with pytest.raises(PlannerError, match="does not flatten"):
        _column_type(mart, "nope")


def test_columns_from_is_the_public_reverse_entry() -> None:
    assert callable(columns_from)
