"""Request-type structural validation (RFC 0011 D2/D9, vocabulary per
RFC 0015): every malformed shape fails construction with ``InvalidRequest``
(or the RFC 0015 refusal for vocabulary-level problems) — nothing malformed
ever reaches coverage, let alone MetricFlow."""

from __future__ import annotations

from decimal import Decimal

import pytest

from bloomery import AnyOf, MetricRequest, Op, OrderSpec, Predicate, RowPolicy, TimeGrain
from bloomery.errors import InvalidLiteral, InvalidRequest

pytestmark = pytest.mark.unit


def test_time_grain_vocabulary() -> None:
    assert [g.value for g in TimeGrain] == ["hour", "day", "week", "month", "quarter", "year"]


def test_op_vocabulary_is_the_closed_rfc_0015_set() -> None:
    assert sorted(op.value for op in Op) == [
        "eq",
        "gt",
        "gte",
        "ilike",
        "in",
        "is_null",
        "like",
        "lt",
        "lte",
        "ne",
        "not_in",
    ]


# ....................... #
# Predicate — the per-operator arity matrix (RFC 0015 §5.1)


def test_valid_predicates_construct() -> None:
    Predicate("store", Op.EQ, ("A",))
    Predicate("store", Op.IN, ("A", "B", "C"))
    Predicate("store", Op.IS_NULL, (True,))
    Predicate("store", Op.IS_NULL, (False,))
    Predicate("amount", Op.GT, (Decimal("10.5"),))
    Predicate("store", Op.LIKE, ("%off%",))
    Predicate("store", Op.ILIKE, ("a%", "b%"))


@pytest.mark.parametrize(
    ("op", "values"),
    [
        # comparisons: exactly one
        *[(op, ()) for op in ("eq", "ne", "gt", "gte", "lt", "lte")],
        *[(op, ("A", "B")) for op in ("eq", "ne", "gt", "gte", "lt", "lte")],
        # membership: one or more
        ("in", ()),
        ("not_in", ()),
        # is_null: exactly one bool — zero-arity is gone (RFC 0015 §5.1)
        ("is_null", ()),
        ("is_null", ("A",)),
        ("is_null", (1,)),
        ("is_null", (True, False)),
        # patterns: one or more strings
        ("like", ()),
        ("ilike", ()),
        ("like", (5,)),
    ],
)
def test_op_value_arity_is_enforced(op: str, values: tuple[object, ...]) -> None:
    with pytest.raises(InvalidRequest):
        Predicate("store", op, values)  # type: ignore[arg-type]


@pytest.mark.parametrize("op", ["between", "contains", "regex", "boom"])
def test_removed_and_unknown_operators_are_refused(op: str) -> None:
    with pytest.raises(InvalidRequest, match="unknown filter operator"):
        Predicate("store", op, ("A", "B"))  # type: ignore[arg-type]


def test_string_op_spellings_coerce_to_the_enum() -> None:
    predicate = Predicate("store", "eq", ("A",))  # type: ignore[arg-type]
    assert predicate.op is Op.EQ


@pytest.mark.parametrize("dimension", ["", 123, None, ("store",)])
def test_dimension_must_be_a_non_empty_string(dimension: object) -> None:
    # The same runtime discipline OrderSpec applies to `field`: a truthy
    # non-string (123) would otherwise sail past an emptiness check and
    # reach name resolution as an ill-typed value.
    with pytest.raises(InvalidRequest, match="non-empty string dimension name"):
        Predicate(dimension, Op.EQ, ("A",))  # type: ignore[arg-type]


def test_non_scalar_values_are_refused() -> None:
    with pytest.raises(InvalidRequest, match="non-scalar"):
        Predicate("amount", Op.EQ, (None,))  # type: ignore[arg-type]


# ....................... #
# Float boundary (RFC 0015 D5, amending RFC 0003 D5)


def test_floats_normalize_to_decimal_via_str() -> None:
    predicate = Predicate("amount", Op.EQ, (0.5,))
    assert predicate.values == (Decimal("0.5"),)
    assert isinstance(predicate.values[0], Decimal)
    # str(float) round-trips the shortest repr — 0.1 stays "0.1", never
    # the binary expansion.
    assert Predicate("amount", Op.GT, (0.1,)).values == (Decimal("0.1"),)


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
    ],
)
@pytest.mark.parametrize(
    "op", [Op.EQ, Op.NE, Op.GT, Op.GTE, Op.LT, Op.LTE, Op.IN, Op.NOT_IN]
)
def test_non_finite_numerics_are_invalid_literals_on_every_scalar_op(
    value: object, op: Op
) -> None:
    """RFC 0015 D5 + decision 15's exhaustive matrix (with the
    string-carrier half in ``test_filters``): a non-finite operand fails
    open — ``lt NaN`` matches every row on Postgres, and an ``in`` list
    holding ``NaN`` is the same hazard — so every operator taking scalars
    refuses it, membership lists included."""
    with pytest.raises(InvalidLiteral) as excinfo:
        Predicate("amount", op, (value,))  # type: ignore[arg-type]
    assert excinfo.value.reason == "invalid_literal"


# ....................... #
# Pattern validation (RFC 0015 decision 13)


def test_trailing_unpaired_backslash_is_refused() -> None:
    with pytest.raises(InvalidLiteral, match="unpaired escape"):
        Predicate("store", Op.LIKE, ("50%\\",))


def test_escaped_backslash_pattern_is_accepted() -> None:
    assert Predicate("store", Op.LIKE, ("C:\\\\temp%",)).values == ("C:\\\\temp%",)
    assert Predicate("store", Op.LIKE, ("\\%literal",)).values == ("\\%literal",)


def test_nul_in_pattern_is_refused() -> None:
    with pytest.raises(InvalidLiteral, match="NUL"):
        Predicate("store", Op.LIKE, ("a\x00b",))


# ....................... #
# AnyOf — one disjunction level (RFC 0015 D-Q3)


def test_any_of_may_span_different_dimensions() -> None:
    clause = AnyOf(
        (Predicate("region", Op.EQ, ("EU",)), Predicate("carrier", Op.EQ, ("DHL",)))
    )
    assert len(clause.predicates) == 2


def test_empty_any_of_is_refused() -> None:
    with pytest.raises(InvalidRequest, match="at least one predicate"):
        AnyOf(())


def test_any_of_needs_a_tuple_container() -> None:
    # A list passes the emptiness check but stays mutable after
    # construction — a frozen value object may not hold one.
    members = [Predicate("region", Op.EQ, ("EU",))]
    with pytest.raises(InvalidRequest, match="tuple predicate members"):
        AnyOf(members)  # type: ignore[arg-type]
    assert AnyOf(tuple(members)).predicates == tuple(members)


def test_nested_any_of_is_unrepresentable() -> None:
    inner = AnyOf((Predicate("a", Op.EQ, ("x",)),))
    with pytest.raises(InvalidRequest, match="Predicate members only"):
        AnyOf((inner,))  # type: ignore[arg-type]


def test_filters_accept_clauses_only() -> None:
    with pytest.raises(InvalidRequest, match="Predicate or AnyOf"):
        MetricRequest(metrics=("revenue",), filters=("raw sql",))  # type: ignore[arg-type]


# ....................... #
# OrderSpec / MetricRequest


def test_bad_order_direction_is_refused() -> None:
    with pytest.raises(InvalidRequest, match="asc"):
        OrderSpec("revenue", "descending")  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["", 1, None, ("revenue",)])
def test_order_field_must_be_a_non_empty_string(field: object) -> None:
    # The same runtime discipline Predicate applies to `dimension` —
    # untyped callers must not build an ill-typed OrderSpec.
    with pytest.raises(InvalidRequest, match="non-empty string field"):
        OrderSpec(field)  # type: ignore[arg-type]


def test_order_spec_carries_no_nulls_field() -> None:
    # RFC 0015 D-Q6: accepting-and-dropping a nulls placement is worse than
    # refusing it — the field must not exist.
    assert not hasattr(OrderSpec("revenue"), "nulls")
    with pytest.raises(TypeError):
        OrderSpec("revenue", "asc", "first")  # type: ignore[call-arg]


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
# RowPolicy — a typed filter, validated at construction (RFC 0015 D11)


def test_policy_single_value_becomes_a_clause() -> None:
    policy = RowPolicy("store", Op.EQ, "A")
    assert policy.as_clause() == Predicate("store", Op.EQ, ("A",))


def test_policy_tuple_value_supports_multi_value_ops() -> None:
    policy = RowPolicy("store", Op.IN, ("A", "B"))
    assert policy.as_clause().values == ("A", "B")


def test_policy_accepts_string_op_spellings() -> None:
    assert RowPolicy("store", "eq", "A").as_clause().op is Op.EQ  # type: ignore[arg-type]


def test_malformed_policy_fails_at_construction() -> None:
    with pytest.raises(InvalidRequest):
        RowPolicy("store", Op.IN, ())  # in needs at least one value


def test_between_shaped_policy_has_no_post_migration_form() -> None:
    # RFC 0015 D11: `between` left the vocabulary — a range policy composes
    # into the request filters or becomes a gte-only/lte-only policy.
    with pytest.raises(InvalidRequest, match="unknown filter operator"):
        RowPolicy("day", "between", ("2024-01-01", "2024-01-31"))  # type: ignore[arg-type]
