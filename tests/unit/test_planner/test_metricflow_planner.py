"""Adapter unit tests (RFC 0013 R2): plan assembly, limit clamping and
warnings, the fingerprint, error translation (MetricFlow types never
escape), dialect refusal, and the Explanation ``render()`` shapes locked as
goldens-in-code."""

from __future__ import annotations

import hashlib

import pytest
import sqlglot
from metricflow_semantics.errors.error_classes import (
    InvalidQueryException,
    InvalidQuerySyntax,
    MetricFlowException,
    UnknownMetricError,
)

from bloomery import AnyOf, MetricRequest, Op, OrderSpec, Predicate, RowPolicy
from bloomery.errors import (
    AmbiguousDimension,
    InvalidRequest,
    PlannerError,
    UnknownMember,
    UnreachableAtGrain,
)
from bloomery.planner import TimeGrain
from bloomery.planner.metricflow_planner import translate_mf_error
from support.planning import fixture_ir, make_planner

pytestmark = pytest.mark.unit

PLANNER = make_planner()


def test_plan_shape_and_fingerprint() -> None:
    plan = PLANNER.plan(
        fixture_ir("semi_additive_inventory"),
        MetricRequest(metrics=("stock_on_hand",), dimensions=("warehouse_id",)),
        dialect="duckdb",
    )
    assert plan.mart == "inventory"
    assert plan.warnings == ()
    assert plan.fingerprint == hashlib.sha256(plan.sql.encode("utf-8")).hexdigest()
    assert [c.name for c in plan.columns] == ["warehouse_id", "stock_on_hand"]
    assert "gold.mart_inventory" in plan.sql


def test_limit_is_clamped_with_a_warning() -> None:
    planner = make_planner(max_limit=10)
    plan = planner.plan(
        fixture_ir("non_additive_aov"),
        MetricRequest(metrics=("revenue",), dimensions=("store",), limit=99),
        dialect="duckdb",
    )
    assert plan.warnings == ("limit 99 exceeds the planner's max_limit 10; clamped to 10",)
    assert "LIMIT 10" in plan.sql
    assert "99" not in plan.sql


def test_default_limit_applies_when_request_has_none() -> None:
    planner = make_planner(default_limit=5)
    plan = planner.plan(
        fixture_ir("non_additive_aov"),
        MetricRequest(metrics=("revenue",)),
        dialect="duckdb",
    )
    assert "LIMIT 5" in plan.sql
    assert plan.warnings == ()


def test_default_limit_is_clamped_too() -> None:
    planner = make_planner(max_limit=3, default_limit=50)
    plan = planner.plan(
        fixture_ir("non_additive_aov"), MetricRequest(metrics=("revenue",)), dialect="duckdb"
    )
    assert "LIMIT 3" in plan.sql
    assert plan.warnings == ("limit 50 exceeds the planner's max_limit 3; clamped to 3",)


def test_time_grain_without_date_dimension_warns_and_is_ignored() -> None:
    plan = PLANNER.plan(
        fixture_ir("non_additive_aov"),
        MetricRequest(metrics=("revenue",), dimensions=("store",), time_grain=TimeGrain.MONTH),
        dialect="duckdb",
    )
    assert plan.warnings == (
        "time_grain 'month' has no date-role dimension in the request to apply to; ignored",
    )


def test_unknown_dialect_is_a_planner_error() -> None:
    with pytest.raises(PlannerError, match="unknown planner dialect"):
        PLANNER.plan(
            fixture_ir("non_additive_aov"),
            MetricRequest(metrics=("revenue",)),
            dialect="oracle",
        )


def test_order_by_desc_and_limit_reach_the_sql() -> None:
    plan = PLANNER.plan(
        fixture_ir("non_additive_aov"),
        MetricRequest(
            metrics=("revenue",),
            dimensions=("store",),
            order_by=(OrderSpec("revenue", "desc"), OrderSpec("store")),
            limit=7,
        ),
        dialect="duckdb",
    )
    assert "ORDER BY revenue DESC" in plan.sql
    assert "LIMIT 7" in plan.sql


# ....................... #
# Error translation (RFC 0013 D2) — MetricFlow types never escape


def test_invalid_query_syntax_translates_to_invalid_request() -> None:
    error = translate_mf_error(InvalidQuerySyntax("bad filter template"))
    assert isinstance(error, InvalidRequest)
    assert "bad filter template" in str(error)


def test_unknown_metric_error_translates_to_unknown_member() -> None:
    assert isinstance(translate_mf_error(UnknownMetricError("no such metric")), UnknownMember)


def test_ambiguous_resolution_translates_to_ambiguous_dimension() -> None:
    error = translate_mf_error(InvalidQueryException("the given input is ambiguous"))
    assert isinstance(error, AmbiguousDimension)


def test_unmatched_group_by_translates_to_unknown_member() -> None:
    error = translate_mf_error(
        InvalidQueryException("The given input does not match any of the available group-bys")
    )
    assert isinstance(error, UnknownMember)


def test_join_failure_translates_to_unreachable_at_grain() -> None:
    error = translate_mf_error(
        InvalidQueryException("unable to join metrics without a common semantic model")
    )
    assert isinstance(error, UnreachableAtGrain)


def test_other_invalid_query_translates_to_invalid_request() -> None:
    error = translate_mf_error(InvalidQueryException("something request-shaped went wrong"))
    assert isinstance(error, InvalidRequest)


def test_unclassified_metricflow_error_stays_a_planner_error_with_message() -> None:
    error = translate_mf_error(MetricFlowException("internal surprise"))
    assert type(error) is PlannerError
    assert "internal surprise" in str(error)


def test_metricflow_failure_is_translated_never_reraised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The delegation seam: a MetricFlow exception surfacing from explain()
    reaches the caller as bloomery taxonomy, with the original chained."""
    from bloomery.planner import metricflow_planner as adapter

    class _ExplodingEngine:
        def __init__(self, **_kwargs: object) -> None: ...

        def explain(self, _request: object) -> object:
            raise InvalidQueryException("the given input is ambiguous")

    monkeypatch.setattr(adapter, "MetricFlowEngine", _ExplodingEngine)
    with pytest.raises(AmbiguousDimension) as excinfo:
        make_planner().plan(
            fixture_ir("non_additive_aov"), MetricRequest(metrics=("revenue",)), dialect="duckdb"
        )
    assert isinstance(excinfo.value.__cause__, InvalidQueryException)


def test_refusals_happen_before_delegation() -> None:
    """Coverage refuses the split request; MetricFlow never sees it — the
    hydrator is never even consulted for an unanswerable request."""
    planner = make_planner()
    with pytest.raises(UnreachableAtGrain):
        planner.plan(
            fixture_ir("multi_mart_refusal"),
            MetricRequest(metrics=("shipping_cost", "line_discount")),
            dialect="duckdb",
        )


# ....................... #
# Explanation renders — locked shapes (RFC 0011 D8: change deliberately)


def test_day_column_falls_back_to_the_source_column_name() -> None:
    from bloomery.planner.explain import _day_column

    mart = fixture_ir("non_additive_aov").marts[0]
    assert _day_column(mart, "order_date") == "ordered_day"
    assert _day_column(mart, "not_a_date_source") == "not_a_date_source"


def test_human_predicate_prose_covers_every_operator() -> None:
    from bloomery.planner.explain import _human_predicate

    assert _human_predicate(Predicate("store", Op.IS_NULL, (True,)), "store") == (
        "store is null"
    )
    assert _human_predicate(Predicate("store", Op.IS_NULL, (False,)), "store") == (
        "store is not null"
    )
    assert _human_predicate(Predicate("store", Op.IN, ("A", "B")), "store") == (
        "store in ('A', 'B')"
    )
    assert _human_predicate(Predicate("store", Op.NOT_IN, ("A",)), "store") == (
        "store not in ('A')"
    )
    assert _human_predicate(Predicate("store", Op.LIKE, ("%dh%",)), "store") == (
        "store like '%dh%'"
    )
    # Multi-pattern like/ilike is an OR of repeated predicates — the prose
    # says what the renderer executes (RFC 0015 §5.1), never a value list
    # that hides the disjunction.
    assert _human_predicate(Predicate("store", Op.ILIKE, ("a%", "b%")), "store") == (
        "store ilike 'a%' OR store ilike 'b%'"
    )
    assert _human_predicate(Predicate("store", Op.LIKE, ("a%", "b%", "c%")), "store") == (
        "store like 'a%' OR store like 'b%' OR store like 'c%'"
    )
    assert _human_predicate(Predicate("flag", Op.EQ, (True,)), "flag") == "flag = true"
    assert _human_predicate(Predicate("flag", Op.NE, (False,)), "flag") == "flag != false"
    assert _human_predicate(Predicate("amount", Op.GT, (5,)), "amount") == "amount > 5"
    # The remaining comparison symbols — all eleven Op members are asserted
    # here, so the _SYMBOLS lookup is locked for every one of them.
    assert _human_predicate(Predicate("amount", Op.LT, (5,)), "amount") == "amount < 5"
    assert _human_predicate(Predicate("amount", Op.LTE, (5,)), "amount") == "amount <= 5"
    assert _human_predicate(Predicate("amount", Op.GTE, (5,)), "amount") == "amount >= 5"


def test_ratio_explanation_render() -> None:
    plan = PLANNER.plan(
        fixture_ir("non_additive_aov"),
        MetricRequest(
            metrics=("average_order_value",),
            dimensions=("store",),
            filters=(
                Predicate("ordered_month", Op.GTE, ("2024-01-01",)),
                Predicate("ordered_month", Op.LTE, ("2024-03-01",)),
            ),
        ),
        dialect="duckdb",
        policy=RowPolicy("store", Op.EQ, "A"),
    )
    assert plan.explanation.render() == (
        "average_order_value\n"
        "  mart:     gold.mart_orders (grain: order)\n"
        "  measure:  average_order_value = revenue / order_count\n"
        "            [non-additive ratio — recomputed at the requested grain, not summed]\n"
        "  filters:  ordered_month >= '2024-01-01'; ordered_month <= '2024-03-01'\n"
        "  policy:   applied"
    )


def test_any_of_explanation_shows_one_entry_with_or() -> None:
    plan = PLANNER.plan(
        fixture_ir("non_additive_aov"),
        MetricRequest(
            metrics=("revenue",),
            filters=(
                AnyOf((Predicate("store", Op.EQ, ("A",)), Predicate("store", Op.EQ, ("B",)))),
            ),
        ),
        dialect="duckdb",
    )
    assert plan.explanation.filters == ("store = 'A' OR store = 'B'",)


def test_semi_additive_explanation_render() -> None:
    plan = PLANNER.plan(
        fixture_ir("semi_additive_inventory"),
        MetricRequest(metrics=("stock_on_hand",)),
        dialect="duckdb",
    )
    assert plan.explanation.render() == (
        "stock_on_hand\n"
        "  mart:     gold.mart_inventory (grain: inventory_level)\n"
        "  measure:  stock_on_hand = SUM(stock_level)\n"
        "            [semi-additive last over snapshot_day — MAX-join then SUM]\n"
        "  filters:  (none)\n"
        "  policy:   not applied"
    )


def test_additive_explanation_render() -> None:
    plan = PLANNER.plan(
        fixture_ir("non_additive_aov"),
        MetricRequest(metrics=("order_count", "revenue")),
        dialect="duckdb",
    )
    assert plan.explanation.render() == (
        "order_count, revenue\n"
        "  mart:     gold.mart_orders (grain: order)\n"
        "  measure:  order_count = COUNT(order_id)\n"
        "            [additive — COUNT]\n"
        "  measure:  revenue = SUM(amount)\n"
        "            [additive — SUM]\n"
        "  filters:  (none)\n"
        "  policy:   not applied"
    )


# ....................... #
# Planner dialect smoke (M10): MetricFlow's shipped trino/postgres renderers
# wired through sql_client_for_dialect — render-only, nothing executed.


@pytest.mark.parametrize("dialect", ["postgres", "trino"])
def test_plan_renders_legal_sql_for_the_second_dialects(dialect: str) -> None:
    plan = PLANNER.plan(
        fixture_ir("non_additive_aov"),
        MetricRequest(metrics=("revenue",), dimensions=("store",)),
        dialect=dialect,
    )
    assert "gold.mart_orders" in plan.sql
    parsed = sqlglot.parse_one(plan.sql, dialect=dialect)
    assert parsed is not None
