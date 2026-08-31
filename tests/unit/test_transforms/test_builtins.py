"""Every starter transform (RFC 0004 §6): input domain, output type
(including arg-dependent cases), and builder AST that round-trips through
``sqlglot.parse_one``."""

from __future__ import annotations

import pytest
from sqlglot import exp, parse_one

from bloomery.errors import TypeCheckError
from bloomery.resolve.build import _try_cast_shape
from bloomery.transforms import DEFAULT_REGISTRY, ISO_TEXT_MARKER
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
    args, input_type, _domain, _output = CASES[name]
    spec = DEFAULT_REGISTRY[name]
    # A spec declaring `types` is handed the type entering the step (RFC 0029
    # D1); the case table already carries it for the output-type assertion.
    extra = {"input_type": input_type} if spec.types else {}
    node = spec.builder(exp.column("x"), *args, **extra)
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
    # A decimal column takes a numeric literal — a non-numeric one is refused
    # (see test_a_literal_that_cannot_survive_its_cast_is_refused).
    coalesce = DEFAULT_REGISTRY["coalesce"]
    for t in (StringType(), IntType(), TimestampType()):
        assert coalesce.output_type(t, ("x",)) == t
    assert coalesce.output_type(DecimalType(9, 2), ("1.5",)) == DecimalType(9, 2)


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


@pytest.mark.parametrize("name", ["coalesce", "nullif"])
def test_a_literal_that_cannot_survive_its_cast_is_refused(name: str) -> None:
    """T-0002 D-018: the emitter casts the literal into the column's decimal
    type, and a value whose integral part cannot fit raises ConversionException
    on the engine — compile-and-fail, the degradation RFC 0008 D3 refuses."""
    spec = DEFAULT_REGISTRY[name]
    with pytest.raises(TypeCheckError, match=r"does not fit decimal\(12, 4\)"):
        spec.output_type(DecimalType(12, 4), (99999999999999,))
    with pytest.raises(TypeCheckError, match=r"does not fit decimal\(12, 4\)"):
        spec.output_type(DecimalType(12, 4), ("100000000",))
    with pytest.raises(TypeCheckError, match="is not a number"):
        spec.output_type(DecimalType(12, 4), ("unknown",))


@pytest.mark.parametrize("name", ["coalesce", "nullif"])
def test_a_fitting_literal_still_produces_the_input_type(name: str) -> None:
    spec = DEFAULT_REGISTRY[name]
    # 99999999.9999 is the largest decimal(12, 4); the boundary fits.
    assert spec.output_type(DecimalType(12, 4), ("99999999.9999",)) == DecimalType(12, 4)
    assert spec.output_type(DecimalType(12, 4), (0,)) == DecimalType(12, 4)
    # Non-decimal columns are untouched: a string fallback stays a string.
    assert spec.output_type(StringType(), ("unknown",)) == StringType()


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


def test_parse_builders_iso8601_is_a_marked_cast_and_formats_are_explicit() -> None:
    """The ISO8601 format name lowers to the engine's native cast over a
    *marked* operand; any other format is an explicit STR_TO_TIME/STR_TO_DATE.

    The marker exists because the engines disagree about what their own casts
    accept and the IR carries canonical text, so nothing else would tell a
    dialect that this particular cast is parsing ISO 8601 (RFC 0027 §3). It
    wraps the operand rather than replacing the cast, so that the quality
    system's ``Cast`` → ``TryCast`` rewrite still reaches it.
    """
    parse_ts = DEFAULT_REGISTRY["parse_ts"].builder
    parse_date = DEFAULT_REGISTRY["parse_date"].builder
    assert parse_ts(exp.column("x"), "ISO8601").sql() == "CAST(BLM_ISO_TEXT(x) AS TIMESTAMP)"
    assert parse_ts(exp.column("x"), "%d/%m/%Y").sql() == "STR_TO_TIME(x, '%d/%m/%Y')"
    # `parse_date` is deliberately unmarked — see its builder, and RFC 0027 D6.
    assert parse_date(exp.column("x"), "ISO8601").sql() == "CAST(x AS DATE)"
    assert parse_date(exp.column("x"), "%d/%m/%Y").sql() == "STR_TO_DATE(x, '%d/%m/%Y')"


def test_the_iso_marker_survives_the_canonical_text_round_trip() -> None:
    """The load-bearing property. The IR stores an expression as canonical text
    and re-parses it at emit (RFC 0003 D2), so a marker that did not survive
    that trip would be gone by the time any dialect could act on it — which is
    exactly why an AST annotation could not do this job.
    """
    built = DEFAULT_REGISTRY["parse_ts"].builder(exp.column("created_at"), "ISO8601")
    reparsed = parse_one(built.sql())
    assert isinstance(reparsed, exp.Cast)
    assert isinstance(reparsed.this, exp.Anonymous)
    assert reparsed.this.name.upper() == ISO_TEXT_MARKER


def test_the_quality_rewrite_still_reaches_a_marked_cast() -> None:
    """A marker standing *where the cast stood* would not be rewritten to
    ``TRY_CAST``, turning the construct that most needs to mark a coercion
    failure back into produce-or-raise. Marking the operand keeps the cast a
    cast, so the existing rewrite finds it.
    """
    built = DEFAULT_REGISTRY["parse_ts"].builder(exp.column("created_at"), "ISO8601")
    assert _try_cast_shape(built).sql() == "TRY_CAST(BLM_ISO_TEXT(created_at) AS TIMESTAMP)"


@pytest.mark.parametrize(
    ("input_type", "fallback", "expected"),
    [
        # The one case the cast buys nothing: all three engines read a string
        # literal as text already, and the emitted SQL is a reviewed artifact.
        (StringType(), "unknown", "COALESCE(x, 'unknown')"),
        # ...but the condition is on the literal too — `COALESCE(text, 0)` does
        # not plan on Trino.
        (StringType(), 0, "COALESCE(x, CAST(0 AS TEXT))"),
        (DateType(), "1970-01-01", "COALESCE(x, CAST('1970-01-01' AS DATE))"),
        # An integer fallback over a decimal widened the result past the
        # declared (p, s) on every engine before this cast (RFC 0029 §2.1).
        (DecimalType(12, 4), 0, "COALESCE(x, CAST(0 AS DECIMAL(12, 4)))"),
    ],
)
def test_coalesce_casts_its_fallback_to_the_column_type(
    input_type: LogicalType, fallback: str | int, expected: str
) -> None:
    node = DEFAULT_REGISTRY["coalesce"].builder(exp.column("x"), fallback, input_type=input_type)
    assert node.sql() == expected


@pytest.mark.parametrize(
    ("input_type", "expected"),
    [
        # PostgreSQL refuses `bigint` -> `boolean`; `x <> 0` is what DuckDB and
        # Trino's cast means anyway, measured over 0, 1, 5 and -1 (RFC 0029 D5).
        (IntType(), "x <> 0"),
        (StringType(), "CAST(x AS BOOLEAN)"),
    ],
)
def test_to_bool_spells_the_integer_boundary_portably(
    input_type: LogicalType, expected: str
) -> None:
    node = DEFAULT_REGISTRY["to_bool"].builder(exp.column("x"), input_type=input_type)
    assert node.sql() == expected


def test_to_int_routes_a_boolean_through_int() -> None:
    """PostgreSQL converts `int4` to boolean and back and refuses `bigint` in
    either direction, so the single cast did not run there at all. The two-step
    form is neutral — DuckDB and Trino evaluate it identically."""
    node = DEFAULT_REGISTRY["to_int"].builder(exp.column("x"), input_type=BoolType())
    assert node.sql() == "CAST(CAST(x AS INT) AS BIGINT)"
    plain = DEFAULT_REGISTRY["to_int"].builder(exp.column("x"), input_type=StringType())
    assert plain.sql() == "CAST(x AS BIGINT)"


@pytest.mark.parametrize(
    ("transform", "args", "input_type", "expected"),
    [
        # decimal(12,4) * 2 is decimal(18,4) on DuckDB, decimal(22,4) on Trino
        # and unconstrained numeric on PostgreSQL — against a declared
        # decimal(13,4). The cast is lossless: p1+p2 is exactly the width the
        # exact product needs, which is what `_arith_output` declares.
        ("multiply", (2,), DecimalType(12, 4), "CAST(x * 2 AS DECIMAL(13, 4))"),
        ("divide", (2,), DecimalType(12, 4), "CAST(BLM_EXACT_DIV(x, 2) AS DECIMAL(13, 4))"),
        ("round", (2,), DecimalType(12, 4), "CAST(ROUND(x, 2) AS DECIMAL(10, 2))"),
        # PostgreSQL has no `round(bigint, int)`, so the argument was promoted
        # to numeric and the result came back numeric where `round` declares the
        # input type unchanged.
        ("round", (0,), IntType(), "CAST(ROUND(x, 0) AS BIGINT)"),
        ("abs", (), DecimalType(12, 4), "CAST(ABS(x) AS DECIMAL(12, 4))"),
    ],
)
def test_arithmetic_narrows_to_the_type_it_declares(
    transform: str, args: tuple[object, ...], input_type: LogicalType, expected: str
) -> None:
    """RFC 0029 D2. Every engine widens decimal arithmetic past the (p, s)
    RFC 0004 §5.4 tracks, and each widens differently — so the declaration
    stopped being true, and with it the 38-digit cap, which is computed over
    the numbers the compiler tracks rather than the ones the engine uses.

    Asserted here rather than only in the engine-tier battery because no
    fixture uses any of these four transforms: a sabotage sweep found that
    removing the narrowing left every non-Docker tier green.
    """
    node = DEFAULT_REGISTRY[transform].builder(exp.column("x"), *args, input_type=input_type)
    assert node.sql() == expected


def test_the_narrowing_cast_is_the_declared_output_not_a_second_opinion() -> None:
    """The builder calls the *same* output function the declaration does, so
    the two cannot drift into agreeing by inspection only."""
    spec = DEFAULT_REGISTRY["multiply"]
    for factor in (2, "0.01", 1000):
        declared = spec.output_type(DecimalType(12, 4), (factor,))
        node = spec.builder(exp.column("x"), factor, input_type=DecimalType(12, 4))
        assert isinstance(declared, DecimalType)
        assert node.to.sql() == f"DECIMAL({declared.precision}, {declared.scale})"


def test_the_narrowing_cast_becomes_a_try_cast_inside_the_quality_system() -> None:
    """An arithmetic overflow is then a coercion failure and a quarantined row
    rather than an aborted run — the disposition RFC 0016 gives every other bad
    value. Asserted because the claim is made in `_narrowed`'s docstring and is
    the reason narrowing is safe to add to an entity carrying quality rules."""
    node = DEFAULT_REGISTRY["multiply"].builder(exp.column("x"), 2, input_type=DecimalType(12, 4))
    assert _try_cast_shape(node).sql() == "TRY_CAST(x * 2 AS DECIMAL(13, 4))"
