"""Coverage precheck unit tests (RFC 0013 R3, RFC 0011 D3): every refusal
branch — unknown members with suggestions, zero/split mart candidates with
the R3 message shape, ownership tie-breaks, dimension resolution including
role ambiguity and the time-grain interplay."""

from __future__ import annotations

from dataclasses import replace

import pytest

from bloomery import MetricRequest, RowPolicy
from bloomery.errors import (
    AmbiguousDimension,
    InvalidRequest,
    UnknownMember,
    UnreachableAtGrain,
)
from bloomery.ir import ProjectIR
from bloomery.naming import DefaultNaming
from bloomery.planner import TimeGrain
from bloomery.planner.coverage import check, resolve_request
from bloomery.planner.names import ResolvedDimension
from bloomery.planner.request import FilterExpr
from support.planning import fixture_ir

pytestmark = pytest.mark.unit

NAMING = DefaultNaming()


def _check(ir: ProjectIR, request: MetricRequest) -> str:
    return check(ir, request, naming=NAMING)


# ....................... #
# Metric validation (step 1)


def test_unknown_metric_gets_a_suggestion() -> None:
    with pytest.raises(UnknownMember, match="did you mean 'revenue'"):
        _check(fixture_ir("non_additive_aov"), MetricRequest(metrics=("revenu",)))


def test_unknown_metric_without_close_match_lists_known() -> None:
    with pytest.raises(UnknownMember, match="known"):
        _check(fixture_ir("non_additive_aov"), MetricRequest(metrics=("zzz",)))


def test_unreachable_metric_names_its_missing_leaves() -> None:
    # ecom_basic's `margin` requires the deliberately unmapped `cogs`.
    with pytest.raises(UnknownMember, match="unreachable.*cogs"):
        _check(fixture_ir("ecom_basic"), MetricRequest(metrics=("margin",)))


# ....................... #
# Mart selection (step 2) — 0 / 1 / N and splits


def test_single_mart_is_selected() -> None:
    assert _check(fixture_ir("semi_additive_inventory"), MetricRequest(("stock_on_hand",))) == (
        "inventory"
    )


def test_ratio_resolves_through_its_components() -> None:
    assert _check(fixture_ir("non_additive_aov"), MetricRequest(("average_order_value",))) == (
        "orders"
    )


def test_metric_on_no_mart_is_unreachable() -> None:
    # ecom_basic declares order_count but no mart lists it as a measure.
    with pytest.raises(UnreachableAtGrain, match="served by no mart"):
        _check(fixture_ir("ecom_basic"), MetricRequest(metrics=("order_count",)))


def test_unservable_ratio_names_the_missing_component() -> None:
    # average_order_value = gross_revenue / order_count; order_count is martless.
    with pytest.raises(UnreachableAtGrain, match="component of the requested ratio"):
        _check(fixture_ir("ecom_basic"), MetricRequest(metrics=("average_order_value",)))


def test_split_measures_refuse_with_the_r3_message() -> None:
    with pytest.raises(UnreachableAtGrain) as excinfo:
        _check(
            fixture_ir("multi_mart_refusal"),
            MetricRequest(metrics=("shipping_cost", "line_discount")),
        )
    message = str(excinfo.value)
    assert "live on different grains" in message
    assert "grain: order " in message or "grain: order (" in message
    assert "grain: order_item" in message
    assert "gold.mart_orders" in message
    assert "gold.mart_order_items" in message
    assert "double-count" in message
    assert "Request them separately" in message
    assert "define a mart at the shared grain" in message


def test_ownership_prefers_cheapest_cost_hint_then_name() -> None:
    """The RFC 0010 D8 rule, shared verbatim with the emitter: cheapest
    ``cost_hint`` wins; ties break lexicographic by mart name."""
    ir = fixture_ir("multi_mart_refusal")
    orders = next(m for m in ir.marts if m.name == "orders")
    # A second mart also carrying shipping_cost, cheaper — it must win.
    cheaper = replace(orders, name="orders_lite", cost_hint=0)
    with_cheaper = replace(ir, marts=tuple(sorted((*ir.marts, cheaper), key=lambda m: m.name)))
    assert _check(with_cheaper, MetricRequest(("shipping_cost",))) == "orders_lite"
    # Same cost: lexicographic tie-break — "orders" < "orders_lite".
    tied = replace(cheaper, cost_hint=orders.cost_hint)
    with_tie = replace(ir, marts=tuple(sorted((*ir.marts, tied), key=lambda m: m.name)))
    assert _check(with_tie, MetricRequest(("shipping_cost",))) == "orders"


# ....................... #
# Dimension resolution (step 3)


def test_unknown_dimension_gets_a_suggestion() -> None:
    request = MetricRequest(metrics=("stock_on_hand",), dimensions=("warehouse",))
    with pytest.raises(UnknownMember, match="did you mean 'warehouse_id'"):
        _check(fixture_ir("semi_additive_inventory"), request)


def test_filter_dimension_must_be_on_the_covering_mart() -> None:
    request = MetricRequest(
        metrics=("stock_on_hand",), filters=(FilterExpr("nonexistent", "eq", ("x",)),)
    )
    with pytest.raises(UnknownMember, match="nonexistent"):
        _check(fixture_ir("semi_additive_inventory"), request)


def test_policy_dimension_must_be_on_the_covering_mart() -> None:
    with pytest.raises(UnknownMember, match="tenant_key"):
        resolve_request(
            fixture_ir("semi_additive_inventory"),
            MetricRequest(metrics=("stock_on_hand",)),
            naming=NAMING,
            policy=RowPolicy("tenant_key", "eq", "acme"),
        )


def test_unqualified_bucket_with_one_role_resolves() -> None:
    resolved = resolve_request(
        fixture_ir("semi_additive_inventory"),
        MetricRequest(metrics=("stock_on_hand",), dimensions=("month",)),
        naming=NAMING,
    )
    assert resolved.dimensions == (
        ResolvedDimension(name="snapshot_month", role="snapshot", grain=TimeGrain.MONTH),
    )


def test_unqualified_bucket_with_two_roles_is_ambiguous() -> None:
    request = MetricRequest(metrics=("revenue",), dimensions=("month",))
    with pytest.raises(
        AmbiguousDimension,
        match=r"'month' has roles \['ordered', 'shipped'\]. "
        r"Use 'ordered_month' or 'shipped_month'\.",
    ):
        _check(fixture_ir("role_playing_dates"), request)


def test_time_grain_rebuckets_requested_date_dimensions() -> None:
    resolved = resolve_request(
        fixture_ir("role_playing_dates"),
        MetricRequest(
            metrics=("revenue",), dimensions=("ordered_day",), time_grain=TimeGrain.QUARTER
        ),
        naming=NAMING,
    )
    assert resolved.dimensions == (
        ResolvedDimension(name="ordered_quarter", role="ordered", grain=TimeGrain.QUARTER),
    )


def test_time_grain_leaves_filter_dimensions_alone() -> None:
    resolved = resolve_request(
        fixture_ir("role_playing_dates"),
        MetricRequest(
            metrics=("revenue",),
            dimensions=("ordered_day",),
            filters=(FilterExpr("shipped_day", "eq", ("2024-01-01",)),),
            time_grain=TimeGrain.MONTH,
        ),
        naming=NAMING,
    )
    assert resolved.filter_dimensions == (
        ResolvedDimension(name="shipped_day", role="shipped", grain=TimeGrain.DAY),
    )


def test_hour_grain_has_no_bucket_and_is_refused() -> None:
    request = MetricRequest(
        metrics=("revenue",), dimensions=("ordered_day",), time_grain=TimeGrain.HOUR
    )
    with pytest.raises(InvalidRequest, match="hour"):
        _check(fixture_ir("role_playing_dates"), request)


def test_categorical_dimensions_ignore_time_grain() -> None:
    resolved = resolve_request(
        fixture_ir("non_additive_aov"),
        MetricRequest(metrics=("revenue",), dimensions=("store",), time_grain=TimeGrain.MONTH),
        naming=NAMING,
    )
    assert resolved.dimensions == (ResolvedDimension(name="store"),)
