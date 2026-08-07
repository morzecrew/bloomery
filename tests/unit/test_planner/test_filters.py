"""Filter-rendering unit tests (RFC 0013 D8, per-clause form per RFC 0015):
every operator template, the typed literal renderer per LogicalType,
escaping (quotes, Jinja braces, NUL), pattern pass-through with the fixed
``ESCAPE`` clause, ``AnyOf`` parenthesization, ``FilterTypeMismatch`` on
every contradiction, and policy prepending."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from bloomery import AnyOf, Op, Predicate, RowPolicy
from bloomery.errors import FilterTypeMismatch, InvalidLiteral, InvalidRequest
from bloomery.planner import TimeGrain
from bloomery.planner.filters import to_where
from bloomery.planner.names import ResolvedDimension
from bloomery.planner.request import Clause
from support.planning import fixture_ir

pytestmark = pytest.mark.unit

AOV_MART = fixture_ir("non_additive_aov").marts[0]  # store/amount/order_id/ordered_*
ENTITY = "order"

STORE = ResolvedDimension(name="store")
AMOUNT = ResolvedDimension(name="amount")
ORDER_ID = ResolvedDimension(name="order_id")
ORDERED_DAY = ResolvedDimension(name="ordered_day", role="ordered", grain=TimeGrain.DAY)
ORDERED_MONTH = ResolvedDimension(name="ordered_month", role="ordered", grain=TimeGrain.MONTH)


def render(clause: Clause, *resolved: ResolvedDimension) -> str:
    (constraint,) = to_where((clause,), (resolved,), mart=AOV_MART, entity=ENTITY)
    return constraint


# ....................... #
# Operators


def test_comparison_operators() -> None:
    ref = "{{ Dimension('order__store') }}"
    assert render(Predicate("store", Op.EQ, ("A",)), STORE) == f"{ref} = 'A'"
    assert render(Predicate("store", Op.NE, ("A",)), STORE) == f"{ref} <> 'A'"
    amount_ref = "{{ Dimension('order__amount') }}"
    assert render(Predicate("amount", Op.GT, (10,)), AMOUNT) == f"{amount_ref} > 10"
    assert render(Predicate("amount", Op.GTE, (10,)), AMOUNT) == f"{amount_ref} >= 10"
    assert render(Predicate("amount", Op.LT, (10,)), AMOUNT) == f"{amount_ref} < 10"
    assert render(Predicate("amount", Op.LTE, (10,)), AMOUNT) == f"{amount_ref} <= 10"


def test_in_not_in_is_null() -> None:
    assert render(Predicate("store", Op.IN, ("A", "B")), STORE) == (
        "{{ Dimension('order__store') }} IN ('A', 'B')"
    )
    assert render(Predicate("store", Op.NOT_IN, ("A",)), STORE) == (
        "{{ Dimension('order__store') }} NOT IN ('A')"
    )
    assert render(Predicate("store", Op.IS_NULL, (True,)), STORE) == (
        "{{ Dimension('order__store') }} IS NULL"
    )
    assert render(Predicate("store", Op.IS_NULL, (False,)), STORE) == (
        "{{ Dimension('order__store') }} IS NOT NULL"
    )


def test_like_passes_the_pattern_through_with_the_escape_clause() -> None:
    # RFC 0015 decision 13: caller-owned wildcards, no auto-wrapping, no
    # renderer-side escaping beyond injection safety.
    assert render(Predicate("store", Op.LIKE, ("%50\\%_off%",)), STORE) == (
        "{{ Dimension('order__store') }} LIKE '%50\\%_off%' ESCAPE '\\'"
    )


def test_ilike_lowers_portably_through_lower() -> None:
    # Trino has no ILIKE — the neutral LOWER/LOWER lowering keeps one
    # rendering across duckdb/postgres/trino (see filters.py docstring).
    assert render(Predicate("store", Op.ILIKE, ("ACME%",)), STORE) == (
        "LOWER({{ Dimension('order__store') }}) LIKE LOWER('ACME%') ESCAPE '\\'"
    )


def test_multi_pattern_like_is_a_parenthesized_or() -> None:
    assert render(Predicate("store", Op.LIKE, ("A%", "B%")), STORE) == (
        "({{ Dimension('order__store') }} LIKE 'A%' ESCAPE '\\' OR "
        "{{ Dimension('order__store') }} LIKE 'B%' ESCAPE '\\')"
    )


def test_range_composes_from_gte_and_lte_clauses() -> None:
    # RFC 0015 D-Q1: `between` left the DSL — a range is two clauses.
    constraints = to_where(
        (
            Predicate("ordered_day", Op.GTE, ("2024-01-01",)),
            Predicate("ordered_day", Op.LTE, ("2024-01-31",)),
        ),
        ((ORDERED_DAY,), (ORDERED_DAY,)),
        mart=AOV_MART,
        entity=ENTITY,
    )
    assert constraints == (
        "{{ Dimension('order__ordered_day__day') }} >= '2024-01-01'",
        "{{ Dimension('order__ordered_day__day') }} <= '2024-01-31'",
    )


def test_time_dimension_filters_use_the_grain_suffixed_dunder() -> None:
    assert render(Predicate("ordered_month", Op.EQ, ("2024-01-01",)), ORDERED_MONTH) == (
        "{{ Dimension('order__ordered_day__month') }} = '2024-01-01'"
    )


# ....................... #
# AnyOf — always parenthesized (RFC 0015 D11)


def test_any_of_renders_as_one_parenthesized_or_constraint() -> None:
    clause = AnyOf((Predicate("store", Op.EQ, ("A",)), Predicate("store", Op.EQ, ("B",))))
    assert render(clause, STORE, STORE) == (
        "({{ Dimension('order__store') }} = 'A' OR {{ Dimension('order__store') }} = 'B')"
    )


def test_single_member_any_of_is_still_parenthesized() -> None:
    clause = AnyOf((Predicate("store", Op.EQ, ("A",)),))
    assert render(clause, STORE) == "({{ Dimension('order__store') }} = 'A')"


def test_mixed_dimension_any_of_renders_each_member_typed() -> None:
    clause = AnyOf((Predicate("store", Op.EQ, ("A",)), Predicate("amount", Op.GT, (100,))))
    assert render(clause, STORE, AMOUNT) == (
        "({{ Dimension('order__store') }} = 'A' OR {{ Dimension('order__amount') }} > 100)"
    )


# ....................... #
# Literal rendering and escaping


def test_single_quotes_are_doubled() -> None:
    assert render(Predicate("store", Op.EQ, ("O'Neil",)), STORE).endswith("= 'O''Neil'")


def test_jinja_braces_are_neutralized_character_by_character() -> None:
    constraint = render(Predicate("store", Op.EQ, ("{{ evil }}",)), STORE)
    # No raw double-brace from the value survives outside the neutralizer.
    assert '{{ "{" }}{{ "{" }} evil {{ "}" }}{{ "}" }}' in constraint


def test_nul_byte_is_refused() -> None:
    with pytest.raises(InvalidRequest, match="NUL"):
        render(Predicate("store", Op.EQ, ("a\x00b",)), STORE)


def test_decimal_and_int_literals() -> None:
    assert render(Predicate("amount", Op.EQ, (Decimal("10.50"),)), AMOUNT).endswith("= 10.50")
    assert render(Predicate("amount", Op.EQ, (7,)), AMOUNT).endswith("= 7")


def test_string_carrier_parses_against_decimal_dimensions() -> None:
    # RFC 0015 D5: the str carrier for exact bounds — parsed here, never a
    # SQL cast.
    assert render(Predicate("amount", Op.GTE, ("10.50",)), AMOUNT).endswith(">= 10.50")


@pytest.mark.parametrize("carrier", ["NaN", "Infinity", "-Infinity", "inf", "nan"])
@pytest.mark.parametrize(
    "op", [Op.EQ, Op.NE, Op.GT, Op.GTE, Op.LT, Op.LTE, Op.IN, Op.NOT_IN]
)
def test_non_finite_string_carriers_are_invalid_literals(carrier: str, op: Op) -> None:
    """RFC 0015 D5 + decision 15: the carrier's non-finite refusal covers
    ``in``/``not_in`` membership members too, not only the ordering ops."""
    with pytest.raises(InvalidLiteral) as excinfo:
        render(Predicate("amount", op, (carrier,)), AMOUNT)
    assert excinfo.value.reason == "invalid_literal"


def test_date_literals_are_iso_validated_and_normalized() -> None:
    assert render(Predicate("ordered_day", Op.EQ, ("2024-01-03",)), ORDERED_DAY).endswith(
        "= '2024-01-03'"
    )


def test_date_object_renders_iso() -> None:
    assert render(Predicate("ordered_day", Op.EQ, (date(2024, 1, 3),)), ORDERED_DAY).endswith(
        "= '2024-01-03'"
    )


def test_date_dimension_refuses_a_datetime_object() -> None:
    # datetime is a date subclass — the renderer must not silently truncate.
    with pytest.raises(FilterTypeMismatch, match="an ISO date"):
        render(Predicate("ordered_day", Op.EQ, (datetime(2024, 1, 3, 12, 0),)), ORDERED_DAY)


def test_uuid_renders_as_a_string_literal() -> None:
    # RFC 0015 D5: no UUID LogicalType exists — a UUID value renders as a
    # quoted string literal against string-typed dimensions.
    value = UUID("12345678-1234-5678-1234-567812345678")
    assert render(Predicate("store", Op.EQ, (value,)), STORE).endswith(
        "= '12345678-1234-5678-1234-567812345678'"
    )


def test_literal_refuses_a_non_finite_decimal_directly() -> None:
    """Defense in depth, exercised directly: Predicate construction already
    refuses non-finite Decimals, so this renderer guard is unreachable
    through the public path — it stays as the last line before SQL."""
    from bloomery.planner.filters import _literal
    from bloomery.typing import DecimalType

    with pytest.raises(InvalidLiteral, match="non-finite"):
        _literal(Decimal("NaN"), DecimalType(precision=12, scale=4), dimension="amount")


# ....................... #
# FilterTypeMismatch — never a cast


@pytest.mark.parametrize(
    ("clause", "resolved"),
    [
        (Predicate("store", Op.EQ, (5,)), STORE),  # int into string
        (Predicate("amount", Op.EQ, ("abc",)), AMOUNT),  # unparsable carrier
        (Predicate("amount", Op.EQ, (True,)), AMOUNT),  # bool into decimal
        (Predicate("ordered_day", Op.EQ, ("not-a-date",)), ORDERED_DAY),
        (Predicate("ordered_day", Op.EQ, (20240103,)), ORDERED_DAY),
        (Predicate("amount", Op.LIKE, ("1%",)), AMOUNT),  # patterns need strings
    ],
)
def test_type_mismatches_are_refused(clause: Predicate, resolved: ResolvedDimension) -> None:
    with pytest.raises(FilterTypeMismatch):
        render(clause, resolved)


def test_int_dimension_refuses_bool() -> None:
    inventory = fixture_ir("semi_additive_inventory").marts[0]
    stock = ResolvedDimension(name="stock_level")
    with pytest.raises(FilterTypeMismatch, match="an int"):
        to_where(
            (Predicate("stock_level", Op.EQ, (True,)),),
            ((stock,),),
            mart=inventory,
            entity="inventory_level",
        )
    (ok,) = to_where(
        (Predicate("stock_level", Op.EQ, (90,)),),
        ((stock,),),
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


def _render_typed(clause: Predicate) -> str:
    (constraint,) = to_where(
        (clause,),
        ((ResolvedDimension(name=clause.dimension),),),
        mart=_typed_mart(),  # type: ignore[arg-type]
        entity="thing",
    )
    return constraint


def test_bool_literals_render_as_keywords() -> None:
    assert _render_typed(Predicate("active", Op.EQ, (True,))).endswith("= TRUE")
    assert _render_typed(Predicate("active", Op.NE, (False,))).endswith("<> FALSE")


def test_bool_dimension_refuses_non_bool() -> None:
    with pytest.raises(FilterTypeMismatch, match="a bool"):
        _render_typed(Predicate("active", Op.EQ, ("yes",)))


def test_timestamp_literals_are_iso_validated() -> None:
    assert _render_typed(Predicate("seen_at", Op.GTE, ("2024-01-02T03:04:05",))).endswith(
        "'2024-01-02 03:04:05'"
    )
    # A datetime object renders with the space separator directly.
    assert _render_typed(Predicate("seen_at", Op.EQ, (datetime(2024, 1, 2, 3, 4, 5),))).endswith(
        "= '2024-01-02 03:04:05'"
    )
    with pytest.raises(FilterTypeMismatch, match="ISO timestamp"):
        _render_typed(Predicate("seen_at", Op.EQ, ("not a time",)))
    with pytest.raises(FilterTypeMismatch, match="ISO timestamp"):
        _render_typed(Predicate("seen_at", Op.EQ, (5,)))


def test_variant_dimension_cannot_be_filtered() -> None:
    with pytest.raises(FilterTypeMismatch, match="cannot be filtered"):
        _render_typed(Predicate("payload", Op.EQ, ("x",)))


def test_date_dimension_refuses_non_string() -> None:
    with pytest.raises(FilterTypeMismatch, match="ISO date"):
        render(Predicate("ordered_day", Op.EQ, (Decimal("1"),)), ORDERED_DAY)


# ....................... #
# Policy prepending (RFC 0013 D9) — via as_clause (RFC 0015 D11)


def test_policy_is_always_first() -> None:
    constraints = to_where(
        (Predicate("store", Op.EQ, ("B",)),),
        ((STORE,),),
        mart=AOV_MART,
        entity=ENTITY,
        policy=RowPolicy("store", Op.EQ, "A"),
        policy_dimension=STORE,
    )
    assert constraints == (
        "{{ Dimension('order__store') }} = 'A'",
        "{{ Dimension('order__store') }} = 'B'",
    )


def test_policy_with_any_of_keeps_the_group_parenthesized() -> None:
    clause = AnyOf((Predicate("store", Op.EQ, ("B",)), Predicate("store", Op.EQ, ("C",))))
    constraints = to_where(
        (clause,),
        ((STORE, STORE),),
        mart=AOV_MART,
        entity=ENTITY,
        policy=RowPolicy("store", Op.EQ, "A"),
        policy_dimension=STORE,
    )
    assert constraints == (
        "{{ Dimension('order__store') }} = 'A'",
        "({{ Dimension('order__store') }} = 'B' OR {{ Dimension('order__store') }} = 'C')",
    )
