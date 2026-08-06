"""The closed LogicalType set (RFC 0004 §5.1): parse_type happy/sad paths and
the assignability matrix including decimal widening/narrowing."""

from __future__ import annotations

import pytest

from bloomery.errors import BloomeryError, TypeCheckError
from bloomery.typing import (
    BoolType,
    DateType,
    DecimalType,
    IntType,
    LogicalType,
    StringType,
    TimestampType,
    VariantType,
    assignable,
    parse_type,
)

pytestmark = pytest.mark.unit

SCALARS: list[tuple[str, LogicalType]] = [
    ("string", StringType()),
    ("int", IntType()),
    ("bool", BoolType()),
    ("date", DateType()),
    ("timestamp", TimestampType()),
    ("variant", VariantType()),
]


@pytest.mark.parametrize(("text", "expected"), SCALARS, ids=lambda v: str(v))
def test_parse_type_scalars(text: str, expected: LogicalType) -> None:
    assert parse_type(text, source_path="doc: f.type") == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("decimal(12,4)", DecimalType(precision=12, scale=4)),
        ("decimal(12, 4)", DecimalType(precision=12, scale=4)),
        ("decimal(1,0)", DecimalType(precision=1, scale=0)),
        ("decimal(10,10)", DecimalType(precision=10, scale=10)),
    ],
)
def test_parse_type_decimal(text: str, expected: LogicalType) -> None:
    assert parse_type(text, source_path="doc: f.type") == expected


@pytest.mark.parametrize(
    "text",
    [
        "float",  # banned package-wide (RFC 0003 D5)
        "time",
        "array",
        "STRING",
        "decimal",
        "decimal(12)",
        "decimal(12,4,2)",
        "decimal(12,-1)",
        "decimal(0,0)",  # grammar admits, type set rejects: precision >= 1
        "decimal(4,5)",  # grammar admits, type set rejects: scale <= precision
        "",
    ],
)
def test_parse_type_rejects(text: str) -> None:
    with pytest.raises(TypeCheckError) as excinfo:
        parse_type(text, source_path="doc: entities.e.fields.f.type")
    assert excinfo.value.source_path == "doc: entities.e.fields.f.type"
    assert isinstance(excinfo.value, BloomeryError)


def test_parse_type_returns_frozen_hashable_values() -> None:
    a = parse_type("decimal(12,4)", source_path="p")
    b = parse_type("decimal(12,4)", source_path="p")
    assert a == b
    assert hash(a) == hash(b)
    with pytest.raises(AttributeError):
        a.precision = 13  # type: ignore[misc]


# ....................... #
# Assignability (RFC 0004 §5.1)


@pytest.mark.parametrize(("_text", "logical"), SCALARS, ids=lambda v: str(v))
def test_assignable_identity(_text: str, logical: LogicalType) -> None:
    assert assignable(logical, logical)


@pytest.mark.parametrize(("_text", "logical"), SCALARS, ids=lambda v: str(v))
def test_anything_assignable_to_variant(_text: str, logical: LogicalType) -> None:
    assert assignable(logical, VariantType())


def test_decimal_assignable_to_variant() -> None:
    assert assignable(DecimalType(12, 4), VariantType())


def test_variant_not_assignable_to_scalars() -> None:
    assert not assignable(VariantType(), StringType())
    assert not assignable(VariantType(), DecimalType(12, 4))


def test_cross_scalar_never_assignable() -> None:
    assert not assignable(IntType(), StringType())
    assert not assignable(StringType(), IntType())
    assert not assignable(DateType(), TimestampType())
    assert not assignable(IntType(), DecimalType(20, 0))
    assert not assignable(DecimalType(20, 0), IntType())


@pytest.mark.parametrize(
    ("actual", "declared", "expected"),
    [
        # identity
        (DecimalType(12, 4), DecimalType(12, 4), True),
        # widening: both p-s and s non-decreasing
        (DecimalType(12, 4), DecimalType(14, 4), True),
        (DecimalType(12, 4), DecimalType(14, 6), True),
        (DecimalType(12, 4), DecimalType(12, 5), False),  # p-s shrinks 8 → 7
        (DecimalType(12, 2), DecimalType(14, 4), True),
        # narrowing is never implicit
        (DecimalType(14, 4), DecimalType(12, 4), False),
        (DecimalType(12, 4), DecimalType(12, 2), False),  # scale shrinks
        (DecimalType(12, 4), DecimalType(10, 4), False),
    ],
)
def test_decimal_widening_matrix(
    actual: DecimalType, declared: DecimalType, expected: bool
) -> None:
    assert assignable(actual, declared) is expected
