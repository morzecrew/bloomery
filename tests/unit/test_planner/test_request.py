"""Request-type structural validation (RFC 0011 D2/D9): every malformed
shape fails construction with ``InvalidRequest`` — nothing malformed ever
reaches coverage, let alone MetricFlow."""

from __future__ import annotations

from decimal import Decimal

import pytest

from bloomery import MetricRequest, OrderSpec, RowPolicy, TimeGrain
from bloomery.errors import InvalidRequest
from bloomery.planner import FilterExpr

pytestmark = pytest.mark.unit


def test_time_grain_vocabulary() -> None:
    assert [g.value for g in TimeGrain] == ["hour", "day", "week", "month", "quarter", "year"]


# ....................... #
# FilterExpr


def test_valid_filters_construct() -> None:
    FilterExpr("store", "eq", ("A",))
    FilterExpr("day", "between", ("2024-01-01", "2024-01-31"))
    FilterExpr("store", "in", ("A", "B", "C"))
    FilterExpr("store", "is_null")
    FilterExpr("amount", "gt", (Decimal("10.5"),))


@pytest.mark.parametrize(
    ("op", "values"),
    [
        ("eq", ()),
        ("eq", ("A", "B")),
        ("between", ("2024-01-01",)),
        ("between", ("a", "b", "c")),
        ("is_null", ("A",)),
        ("in", ()),
        ("not_in", ()),
        ("contains", ()),
        ("lt", ("1", "2")),
    ],
)
def test_op_value_arity_is_enforced(op: str, values: tuple[str, ...]) -> None:
    with pytest.raises(InvalidRequest):
        FilterExpr("store", op, values)  # type: ignore[arg-type]


def test_unknown_operator_is_refused() -> None:
    with pytest.raises(InvalidRequest, match="unknown filter operator"):
        FilterExpr("store", "like", ("A",))  # type: ignore[arg-type]


def test_empty_dimension_is_refused() -> None:
    with pytest.raises(InvalidRequest, match="dimension name"):
        FilterExpr("", "eq", ("A",))


def test_float_values_are_refused() -> None:
    with pytest.raises(InvalidRequest, match="float"):
        FilterExpr("amount", "eq", (1.5,))  # type: ignore[arg-type]


def test_non_scalar_values_are_refused() -> None:
    with pytest.raises(InvalidRequest, match="non-scalar"):
        FilterExpr("amount", "eq", (None,))  # type: ignore[arg-type]


# ....................... #
# OrderSpec / MetricRequest


def test_bad_order_direction_is_refused() -> None:
    with pytest.raises(InvalidRequest, match="asc"):
        OrderSpec("revenue", "descending")  # type: ignore[arg-type]


def test_empty_metrics_are_refused() -> None:
    with pytest.raises(InvalidRequest, match="at least one metric"):
        MetricRequest(metrics=())


@pytest.mark.parametrize(
    ("metrics", "dimensions"),
    [(("revenue", "revenue"), ()), (("revenue",), ("store", "store"))],
)
def test_duplicates_are_refused(metrics: tuple[str, ...], dimensions: tuple[str, ...]) -> None:
    with pytest.raises(InvalidRequest, match="duplicate"):
        MetricRequest(metrics=metrics, dimensions=dimensions)


@pytest.mark.parametrize("limit", [0, -5])
def test_limit_below_one_is_refused(limit: int) -> None:
    with pytest.raises(InvalidRequest, match="limit"):
        MetricRequest(metrics=("revenue",), limit=limit)


def test_order_by_outside_request_members_is_refused() -> None:
    with pytest.raises(InvalidRequest, match="order_by"):
        MetricRequest(metrics=("revenue",), order_by=(OrderSpec("sneaky_expr"),))


def test_order_by_requested_members_is_accepted() -> None:
    request = MetricRequest(
        metrics=("revenue",),
        dimensions=("store",),
        order_by=(OrderSpec("revenue", "desc"), OrderSpec("store")),
    )
    assert request.limit is None


# ....................... #
# RowPolicy — a typed filter, validated at construction


def test_policy_single_value_becomes_a_filter() -> None:
    policy = RowPolicy("store", "eq", "A")
    assert policy.as_filter() == FilterExpr("store", "eq", ("A",))


def test_policy_tuple_value_supports_multi_value_ops() -> None:
    policy = RowPolicy("store", "in", ("A", "B"))
    assert policy.as_filter().values == ("A", "B")


def test_malformed_policy_fails_at_construction() -> None:
    with pytest.raises(InvalidRequest):
        RowPolicy("store", "between", "A")  # between needs exactly two values
