"""Filter-rendering unit tests (RFC 0013 D8): every operator template, the
typed literal renderer per LogicalType, escaping (quotes, Jinja braces, LIKE
wildcards, NUL), ``FilterTypeMismatch`` on every contradiction, and policy
prepending."""

from __future__ import annotations

from decimal import Decimal

import pytest

from bloomery import RowPolicy
from bloomery.errors import FilterTypeMismatch, InvalidRequest
from bloomery.planner import TimeGrain
from bloomery.planner.filters import to_where
from bloomery.planner.names import ResolvedDimension
from bloomery.planner.request import FilterExpr
from support.planning import fixture_ir

pytestmark = pytest.mark.unit

AOV_MART = fixture_ir("non_additive_aov").marts[0]  # store/amount/order_id/ordered_*
ENTITY = "order"

STORE = ResolvedDimension(name="store")
AMOUNT = ResolvedDimension(name="amount")
ORDER_ID = ResolvedDimension(name="order_id")
ORDERED_DAY = ResolvedDimension(name="ordered_day", role="ordered", grain=TimeGrain.DAY)
ORDERED_MONTH = ResolvedDimension(name="ordered_month", role="ordered", grain=TimeGrain.MONTH)


def render(filter_expr: FilterExpr, resolved: ResolvedDimension) -> str:
    (constraint,) = to_where((filter_expr,), (resolved,), mart=AOV_MART, entity=ENTITY)
    return constraint


# ....................... #
# Operators


def test_comparison_operators() -> None:
    ref = "{{ Dimension('order__store') }}"
    assert render(FilterExpr("store", "eq", ("A",)), STORE) == f"{ref} = 'A'"
    assert render(FilterExpr("store", "ne", ("A",)), STORE) == f"{ref} <> 'A'"
    amount_ref = "{{ Dimension('order__amount') }}"
    assert render(FilterExpr("amount", "gt", (10,)), AMOUNT) == f"{amount_ref} > 10"
    assert render(FilterExpr("amount", "gte", (10,)), AMOUNT) == f"{amount_ref} >= 10"
    assert render(FilterExpr("amount", "lt", (10,)), AMOUNT) == f"{amount_ref} < 10"
    assert render(FilterExpr("amount", "lte", (10,)), AMOUNT) == f"{amount_ref} <= 10"


def test_between_in_not_in_is_null() -> None:
    assert render(
        FilterExpr("ordered_day", "between", ("2024-01-01", "2024-01-31")), ORDERED_DAY
    ) == ("{{ Dimension('order__ordered_day__day') }} BETWEEN '2024-01-01' AND '2024-01-31'")
    assert render(FilterExpr("store", "in", ("A", "B")), STORE) == (
        "{{ Dimension('order__store') }} IN ('A', 'B')"
    )
    assert render(FilterExpr("store", "not_in", ("A",)), STORE) == (
        "{{ Dimension('order__store') }} NOT IN ('A')"
    )
    assert render(FilterExpr("store", "is_null"), STORE) == (
        "{{ Dimension('order__store') }} IS NULL"
    )


def test_contains_escapes_wildcards_and_carries_escape_clause() -> None:
    assert render(FilterExpr("store", "contains", ("50%_off\\now",)), STORE) == (
        "{{ Dimension('order__store') }} LIKE '%50\\%\\_off\\\\now%' ESCAPE '\\'"
    )


def test_time_dimension_filters_use_the_grain_suffixed_dunder() -> None:
    assert render(FilterExpr("ordered_month", "eq", ("2024-01-01",)), ORDERED_MONTH) == (
        "{{ Dimension('order__ordered_day__month') }} = '2024-01-01'"
    )


# ....................... #
# Literal rendering and escaping


def test_single_quotes_are_doubled() -> None:
    assert render(FilterExpr("store", "eq", ("O'Neil",)), STORE).endswith("= 'O''Neil'")


def test_jinja_braces_are_neutralized_character_by_character() -> None:
    constraint = render(FilterExpr("store", "eq", ("{{ evil }}",)), STORE)
    # No raw double-brace from the value survives outside the neutralizer.
    assert '{{ "{" }}{{ "{" }} evil {{ "}" }}{{ "}" }}' in constraint


def test_nul_byte_is_refused() -> None:
    with pytest.raises(InvalidRequest, match="NUL"):
        render(FilterExpr("store", "eq", ("a\x00b",)), STORE)


def test_decimal_and_int_literals() -> None:
    assert render(FilterExpr("amount", "eq", (Decimal("10.50"),)), AMOUNT).endswith("= 10.50")
    assert render(FilterExpr("amount", "eq", (7,)), AMOUNT).endswith("= 7")


def test_date_literals_are_iso_validated_and_normalized() -> None:
    assert render(FilterExpr("ordered_day", "eq", ("2024-01-03",)), ORDERED_DAY).endswith(
        "= '2024-01-03'"
    )


# ....................... #
# FilterTypeMismatch — never a cast


@pytest.mark.parametrize(
    ("filter_expr", "resolved"),
    [
        (FilterExpr("store", "eq", (5,)), STORE),  # int into string
        (FilterExpr("amount", "eq", ("abc",)), AMOUNT),  # string into decimal
        (FilterExpr("amount", "eq", (True,)), AMOUNT),  # bool into decimal
        (FilterExpr("ordered_day", "eq", ("not-a-date",)), ORDERED_DAY),
        (FilterExpr("ordered_day", "eq", (20240103,)), ORDERED_DAY),
        (FilterExpr("amount", "contains", ("1",)), AMOUNT),  # contains needs strings
        (FilterExpr("amount", "eq", (Decimal("NaN"),)), AMOUNT),
    ],
)
def test_type_mismatches_are_refused(
    filter_expr: FilterExpr, resolved: ResolvedDimension
) -> None:
    with pytest.raises(FilterTypeMismatch):
        render(filter_expr, resolved)


def test_int_dimension_refuses_bool() -> None:
    inventory = fixture_ir("semi_additive_inventory").marts[0]
    stock = ResolvedDimension(name="stock_level")
    with pytest.raises(FilterTypeMismatch, match="an int"):
        to_where(
            (FilterExpr("stock_level", "eq", (True,)),),
            (stock,),
            mart=inventory,
            entity="inventory_level",
        )
    (ok,) = to_where(
        (FilterExpr("stock_level", "eq", (90,)),),
        (stock,),
        mart=inventory,
        entity="inventory_level",
    )
    assert ok == "{{ Dimension('inventory_level__stock_level') }} = 90"


def _typed_mart() -> object:
    """A synthetic mart carrying the column types no fixture flattens —
    bool, timestamp, and variant — to close the literal-renderer branches."""
    from bloomery.ir import MartColumnIR, MartDimensionIR, Materialization
    from bloomery.ir.nodes import DimensionRef, MartIR
    from bloomery.typing import BoolType, TimestampType, VariantType

    columns = tuple(
        MartColumnIR(name=name, type=type_, source_entity="thing", source_column=name)
        for name, type_ in (
            ("active", BoolType()),
            ("payload", VariantType()),
            ("seen_at", TimestampType()),
        )
    )
    return MartIR(
        name="things",
        grain="thing",
        base="thing",
        columns=columns,
        measures=(),
        dimensions=tuple(
            MartDimensionIR(ref=DimensionRef(dimension=c.name), column=c.name) for c in columns
        ),
        joins=(),
        partition_by=(),
        materialization=Materialization.FULL,
    )


def _render_typed(filter_expr: FilterExpr) -> str:
    (constraint,) = to_where(
        (filter_expr,),
        (ResolvedDimension(name=filter_expr.dimension),),
        mart=_typed_mart(),  # type: ignore[arg-type]
        entity="thing",
    )
    return constraint


def test_bool_literals_render_as_keywords() -> None:
    assert _render_typed(FilterExpr("active", "eq", (True,))).endswith("= TRUE")
    assert _render_typed(FilterExpr("active", "ne", (False,))).endswith("<> FALSE")


def test_bool_dimension_refuses_non_bool() -> None:
    with pytest.raises(FilterTypeMismatch, match="a bool"):
        _render_typed(FilterExpr("active", "eq", ("yes",)))


def test_timestamp_literals_are_iso_validated() -> None:
    assert _render_typed(FilterExpr("seen_at", "gte", ("2024-01-02T03:04:05",))).endswith(
        "'2024-01-02 03:04:05'"
    )
    with pytest.raises(FilterTypeMismatch, match="ISO timestamp"):
        _render_typed(FilterExpr("seen_at", "eq", ("not a time",)))
    with pytest.raises(FilterTypeMismatch, match="ISO timestamp"):
        _render_typed(FilterExpr("seen_at", "eq", (5,)))


def test_variant_dimension_cannot_be_filtered() -> None:
    with pytest.raises(FilterTypeMismatch, match="cannot be filtered"):
        _render_typed(FilterExpr("payload", "eq", ("x",)))


def test_date_dimension_refuses_non_string() -> None:
    with pytest.raises(FilterTypeMismatch, match="ISO date"):
        render(FilterExpr("ordered_day", "eq", (Decimal("1"),)), ORDERED_DAY)


def test_decimal_dimension_accepts_int_and_decimal_only() -> None:
    with pytest.raises(FilterTypeMismatch, match="int or Decimal"):
        render(FilterExpr("amount", "in", (1, "2")), AMOUNT)


# ....................... #
# Policy prepending (RFC 0013 D9)


def test_policy_is_always_first() -> None:
    constraints = to_where(
        (FilterExpr("store", "eq", ("B",)),),
        (STORE,),
        mart=AOV_MART,
        entity=ENTITY,
        policy=RowPolicy("store", "eq", "A"),
        policy_dimension=STORE,
    )
    assert constraints == (
        "{{ Dimension('order__store') }} = 'A'",
        "{{ Dimension('order__store') }} = 'B'",
    )
