"""Every starter transform (RFC 0004 §6): input domain, output type
(including arg-dependent cases), and builder AST that round-trips through
``sqlglot.parse_one``."""

from __future__ import annotations

import pytest
from sqlglot import exp, parse_one

from bloomery.errors import TypeCheckError
from bloomery.transforms import DEFAULT_REGISTRY
from bloomery.typing import (
    ArgKind,
    BoolType,
    DateType,
    DecimalType,
    IntType,
    LogicalType,
    StringType,
    TimestampType,
    VariantType,
)

pytestmark = pytest.mark.unit

ALL_TYPES = (
    StringType,
    IntType,
    DecimalType,
    BoolType,
    DateType,
    TimestampType,
    VariantType,
)

#: name → (args, input instance, expected input domain, expected output type)
CASES: dict[str, tuple[tuple[str | int, ...], LogicalType, tuple[type, ...], LogicalType]] = {
    "trim": ((), StringType(), (StringType,), StringType()),
    "upper": ((), StringType(), (StringType,), StringType()),
    "lower": ((), StringType(), (StringType,), StringType()),
    "to_string": ((), IntType(), ALL_TYPES, StringType()),
    "to_int": ((), StringType(), (StringType, IntType, DecimalType, BoolType), IntType()),
    "to_decimal": (
        (12, 4),
        StringType(),
        (StringType, IntType, DecimalType),
        DecimalType(12, 4),
    ),
    "to_bool": ((), StringType(), (StringType, IntType, BoolType), BoolType()),
    "parse_ts": (("ISO8601",), StringType(), (StringType,), TimestampType()),
    "parse_date": (("%Y-%m-%d",), StringType(), (StringType,), DateType()),
    "to_utc": (("Europe/Paris",), TimestampType(), (TimestampType,), TimestampType()),
    "enum_map": (("a", "b", "c", "d"), StringType(), (StringType,), StringType()),
    "coalesce": (("fallback",), DateType(), ALL_TYPES, DateType()),
    "nullif": ((0,), IntType(), ALL_TYPES, IntType()),
    "split_part": (("-", 2), StringType(), (StringType,), StringType()),
    "regex_extract": (("[0-9]+", 1), StringType(), (StringType,), StringType()),
    "strip_prefix": (("pre_",), StringType(), (StringType,), StringType()),
    "strip_suffix": (("_sfx",), StringType(), (StringType,), StringType()),
    "multiply": ((3,), DecimalType(12, 4), (DecimalType,), DecimalType(13, 4)),
    "divide": (("0.25",), DecimalType(12, 4), (DecimalType,), DecimalType(14, 6)),
    "round": ((2,), DecimalType(12, 4), (IntType, DecimalType), DecimalType(10, 2)),
    "abs": ((), DecimalType(12, 4), (IntType, DecimalType), DecimalType(12, 4)),
    "concat": (("!",), StringType(), (StringType,), StringType()),
    "json_path": (("$.a.b",), VariantType(), (VariantType, StringType), VariantType()),
    "convert": (("USD",), DecimalType(12, 4), (DecimalType,), DecimalType(12, 4)),
}


def test_case_table_covers_the_whole_starter_set() -> None:
    assert sorted(CASES) == sorted(DEFAULT_REGISTRY)


@pytest.mark.parametrize("name", sorted(CASES))
def test_input_domain_and_output_type(name: str) -> None:
    args, input_type, domain, expected_output = CASES[name]
    spec = DEFAULT_REGISTRY[name]
    assert spec.input_domain == domain
    assert spec.output_type(input_type, args) == expected_output


@pytest.mark.parametrize("name", sorted(CASES))
def test_builder_ast_round_trips_through_sqlglot(name: str) -> None:
    args, _input_type, _domain, _output = CASES[name]
    spec = DEFAULT_REGISTRY[name]
    node = spec.builder(exp.column("x"), *args)
    assert isinstance(node, exp.Expression)
    rendered = node.sql()
    reparsed = parse_one(rendered)
    assert reparsed.sql() == rendered  # canonical text is a fixed point


@pytest.mark.parametrize("name", sorted(CASES))
def test_arity_matches_arg_kinds(name: str) -> None:
    spec = DEFAULT_REGISTRY[name]
    assert spec.arity == len(spec.arg_kinds)
    args, *_ = CASES[name]
    if spec.variadic:
        assert len(args) % spec.arity == 0
    else:
        assert len(args) == spec.arity


def test_enum_map_is_the_only_variadic_transform() -> None:
    variadic = [name for name, spec in DEFAULT_REGISTRY.items() if spec.variadic]
    assert variadic == ["enum_map"]
    assert DEFAULT_REGISTRY["enum_map"].arg_kinds == (ArgKind.STR, ArgKind.STR)


def test_output_preservation_tracks_the_input_type() -> None:
    coalesce = DEFAULT_REGISTRY["coalesce"]
    for t in (StringType(), IntType(), DecimalType(9, 2), TimestampType()):
        assert coalesce.output_type(t, ("x",)) == t


@pytest.mark.parametrize(
    ("precision", "scale", "match"),
    [
        (0, 0, "precision must be between 1 and 38"),
        (39, 0, "precision must be between 1 and 38"),
        (12, 13, "scale .* must be between 0 and precision"),
        (12, -1, "scale .* must be between 0 and precision"),
    ],
)
def test_to_decimal_rejects_bad_parameters(precision: int, scale: int, match: str) -> None:
    with pytest.raises(TypeCheckError, match=match):
        DEFAULT_REGISTRY["to_decimal"].output_type(StringType(), (precision, scale))


@pytest.mark.parametrize("name", ["multiply", "divide"])
def test_arithmetic_precision_tracking(name: str) -> None:
    spec = DEFAULT_REGISTRY[name]
    # p1+p2 / s1+s2 (RFC 0004 §5.4): literal "2.5" contributes (2, 1).
    assert spec.output_type(DecimalType(20, 4), ("2.5",)) == DecimalType(22, 5)
    # An int literal contributes (digits, 0).
    assert spec.output_type(DecimalType(20, 4), (100,)) == DecimalType(23, 4)


@pytest.mark.parametrize("name", ["multiply", "divide"])
def test_arithmetic_overflow_past_38_is_loud(name: str) -> None:
    spec = DEFAULT_REGISTRY[name]
    with pytest.raises(TypeCheckError, match="38-digit precision cap"):
        spec.output_type(DecimalType(38, 2), (10,))


def test_round_output() -> None:
    spec = DEFAULT_REGISTRY["round"]
    assert spec.output_type(IntType(), (2,)) == IntType()
    assert spec.output_type(DecimalType(12, 4), (0,)) == DecimalType(8, 0)
    assert spec.output_type(DecimalType(12, 4), (6,)) == DecimalType(14, 6)
    with pytest.raises(TypeCheckError, match="digits must be >= 0"):
        spec.output_type(DecimalType(12, 4), (-1,))


def test_round_overflow_past_38_is_loud() -> None:
    with pytest.raises(TypeCheckError, match="38-digit precision cap"):
        DEFAULT_REGISTRY["round"].output_type(DecimalType(38, 0), (10,))


def test_convert_typechecks_decimal_to_decimal() -> None:
    """RFC 0004 D3: `convert` is the currency-conversion marker; its semantic
    obligations land with the currency guardrail (M4)."""
    spec = DEFAULT_REGISTRY["convert"]
    assert spec.input_domain == (DecimalType,)
    assert spec.output_type(DecimalType(12, 4), ("USD",)) == DecimalType(12, 4)
    rendered = spec.builder(exp.column("x"), "USD").sql()
    assert rendered == "CONVERT_CURRENCY(x, 'USD')"


def test_enum_map_builder_maps_pairs_and_passes_unmapped_through() -> None:
    node = DEFAULT_REGISTRY["enum_map"].builder(exp.column("x"), "paid", "PAID")
    assert node.sql() == "CASE x WHEN 'paid' THEN 'PAID' ELSE x END"


def test_parse_builders_iso8601_is_a_cast_and_formats_are_explicit() -> None:
    """The ISO8601 format name lowers to the engine's native cast; any other
    format is an explicit STR_TO_TIME/STR_TO_DATE."""
    parse_ts = DEFAULT_REGISTRY["parse_ts"].builder
    parse_date = DEFAULT_REGISTRY["parse_date"].builder
    assert parse_ts(exp.column("x"), "ISO8601").sql() == "CAST(x AS TIMESTAMP)"
    assert parse_ts(exp.column("x"), "%d/%m/%Y").sql() == "STR_TO_TIME(x, '%d/%m/%Y')"
    assert parse_date(exp.column("x"), "ISO8601").sql() == "CAST(x AS DATE)"
    assert parse_date(exp.column("x"), "%d/%m/%Y").sql() == "STR_TO_DATE(x, '%d/%m/%Y')"
