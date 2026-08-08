"""The closed starter set, exactly RFC 0004 D3: ``trim upper lower to_string
to_int to_decimal to_bool parse_ts parse_date to_utc enum_map coalesce nullif
split_part regex_extract strip_prefix strip_suffix multiply divide round abs
concat json_path`` plus ``convert``, the explicit currency-conversion marker
the currency guardrail requires (RFC 0006; typechecks decimal → decimal here,
its semantic obligations are guardrail/emit concerns).

Every builder constructs SQLGlot AST only — string SQL inside a builder is a
review-time ban (RFC 0004 D7), and the property tests assert every builder
output round-trips through ``sqlglot.parse_one``.
"""

from __future__ import annotations

from decimal import Decimal

from sqlglot import exp
from sqlglot.expressions.core import Expression

from bloomery.errors import TypeCheckError
from bloomery.transforms.registry import OutputType, transform
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

__all__: list[str] = []

_ALL_TYPES: tuple[type[LogicalType], ...] = (
    StringType,
    IntType,
    DecimalType,
    BoolType,
    DateType,
    TimestampType,
    VariantType,
)

#: ``parse_ts``/``parse_date`` treat this format name as a plain cast — the
#: engine's native ISO-8601 parsing — instead of an explicit format string.
_ISO8601 = "ISO8601"

_PRECISION_CAP = 38


def _literal(value: str | int) -> Expression:
    """A spec-level literal arg as a SQLGlot literal node."""
    if isinstance(value, int):
        return exp.Literal.number(value)
    return exp.Literal.string(value)


def _number(value: str | int) -> Expression:
    """A NUMBER-kind arg as a SQLGlot numeric literal node."""
    return exp.Literal.number(value)


def _literal_shape(value: str | int) -> tuple[int, int]:
    """The (precision, scale) a numeric literal contributes to arithmetic
    tracking (RFC 0004 §5.4). The arg-kind check guarantees a finite value."""
    parsed = Decimal(str(value))
    exponent = parsed.as_tuple().exponent
    scale = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    return max(len(parsed.as_tuple().digits), scale, 1), scale


def _require_decimal(t: LogicalType, name: str) -> DecimalType:
    if not isinstance(t, DecimalType):  # pragma: no cover — input domain enforces
        msg = f"{name!r} requires a decimal input, got {t!r}"
        raise TypeCheckError(msg)
    return t


def _arith_output(name: str) -> OutputType:
    """Capped-widening output for ``multiply``/``divide`` (RFC 0004 §5.4):
    ``decimal(p1+p2, s1+s2)``, precision capped at 38 with a loud error."""

    def output(t: LogicalType, args: tuple[str | int, ...]) -> LogicalType:
        current = _require_decimal(t, name)
        p2, s2 = _literal_shape(args[0])
        precision, scale = current.precision + p2, current.scale + s2
        if precision > _PRECISION_CAP:
            msg = (
                f"{name!r} widens decimal({current.precision}, {current.scale}) to "
                f"decimal({precision}, {scale}), exceeding the {_PRECISION_CAP}-digit "
                "precision cap; narrow the operands with an explicit to_decimal(p, s) step"
            )
            raise TypeCheckError(msg)
        return DecimalType(precision=precision, scale=scale)

    return output


# ....................... #
# String transforms


@transform("trim", arity=0, input=(StringType,), output=StringType())
def trim(col: Expression) -> Expression:
    return exp.Trim(this=col)


@transform("upper", arity=0, input=(StringType,), output=StringType())
def upper(col: Expression) -> Expression:
    return exp.Upper(this=col)


@transform("lower", arity=0, input=(StringType,), output=StringType())
def lower(col: Expression) -> Expression:
    return exp.Lower(this=col)


@transform(
    "split_part",
    arity=2,
    arg_kinds=(ArgKind.STR, ArgKind.INT),
    input=(StringType,),
    output=StringType(),
    # Out-of-range index: '' on DuckDB, NULL on Trino. Declared nullifying on
    # the portable reading — a divergence must not be resolved by whichever
    # engine happens to run (RFC 0016 §5.2).
    nullifies=True,
)
def split_part(col: Expression, delimiter: str, index: int) -> Expression:
    return exp.SplitPart(
        this=col,
        delimiter=exp.Literal.string(delimiter),
        part_index=exp.Literal.number(index),
    )


@transform(
    "regex_extract",
    arity=2,
    arg_kinds=(ArgKind.STR, ArgKind.INT),
    input=(StringType,),
    output=StringType(),
    # No match: '' on DuckDB, NULL on Trino and Postgres. Same reading as
    # split_part — the portable one.
    nullifies=True,
)
def regex_extract(col: Expression, pattern: str, group: int) -> Expression:
    return exp.RegexpExtract(
        this=col,
        expression=exp.Literal.string(pattern),
        group=exp.Literal.number(group),
    )


@transform(
    "strip_prefix", arity=1, arg_kinds=(ArgKind.STR,), input=(StringType,), output=StringType()
)
def strip_prefix(col: Expression, prefix: str) -> Expression:
    return exp.Case(
        ifs=[
            exp.If(
                this=exp.func("STARTS_WITH", col.copy(), exp.Literal.string(prefix)),
                true=exp.Substring(this=col.copy(), start=exp.Literal.number(len(prefix) + 1)),
            )
        ],
        default=col,
    )


@transform(
    "strip_suffix", arity=1, arg_kinds=(ArgKind.STR,), input=(StringType,), output=StringType()
)
def strip_suffix(col: Expression, suffix: str) -> Expression:
    remaining = exp.Sub(
        this=exp.Length(this=col.copy()),
        expression=exp.Literal.number(len(suffix)),
    )
    return exp.Case(
        ifs=[
            exp.If(
                this=exp.func("ENDS_WITH", col.copy(), exp.Literal.string(suffix)),
                true=exp.Substring(this=col.copy(), start=exp.Literal.number(1), length=remaining),
            )
        ],
        default=col,
    )


@transform("concat", arity=1, arg_kinds=(ArgKind.STR,), input=(StringType,), output=StringType())
def concat(col: Expression, text: str) -> Expression:
    return exp.DPipe(this=col, expression=exp.Literal.string(text))


@transform(
    "enum_map",
    arity=2,
    arg_kinds=(ArgKind.STR, ArgKind.STR),
    input=(StringType,),
    output=StringType(),
    variadic=True,
)
def enum_map(col: Expression, *pairs: str) -> Expression:
    """``{enum_map: [raw, mapped, ...]}`` — flat from/to pairs. Values outside
    the map pass through: disposing of them is the ``in_enum`` quality rule's
    job (RFC 0016 §5.2, D3 — superseding RFC 0008 D7), not a chain concern."""
    ifs = [
        exp.If(this=exp.Literal.string(source), true=exp.Literal.string(mapped))
        for source, mapped in zip(pairs[0::2], pairs[1::2], strict=True)
    ]
    return exp.Case(this=col.copy(), ifs=ifs, default=col)


# ....................... #
# Casts and parses


@transform("to_string", arity=0, input=_ALL_TYPES, output=StringType())
def to_string(col: Expression) -> Expression:
    return exp.cast(col, exp.DataType.build("TEXT"))


@transform("to_int", arity=0, input=(StringType, IntType, DecimalType, BoolType), output=IntType())
def to_int(col: Expression) -> Expression:
    return exp.cast(col, exp.DataType.build("BIGINT"))


def _to_decimal_output(_t: LogicalType, args: tuple[str | int, ...]) -> LogicalType:
    precision, scale = int(args[0]), int(args[1])
    if not 1 <= precision <= _PRECISION_CAP:
        msg = f"to_decimal precision must be between 1 and {_PRECISION_CAP}, got {precision}"
        raise TypeCheckError(msg)
    if not 0 <= scale <= precision:
        msg = f"to_decimal scale ({scale}) must be between 0 and precision ({precision})"
        raise TypeCheckError(msg)
    return DecimalType(precision=precision, scale=scale)


@transform(
    "to_decimal",
    arity=2,
    arg_kinds=(ArgKind.INT, ArgKind.INT),
    input=(StringType, IntType, DecimalType),
    output=_to_decimal_output,
)
def to_decimal(col: Expression, precision: int, scale: int) -> Expression:
    return exp.cast(col, exp.DataType.build(f"DECIMAL({precision}, {scale})"))


@transform("to_bool", arity=0, input=(StringType, IntType, BoolType), output=BoolType())
def to_bool(col: Expression) -> Expression:
    return exp.cast(col, exp.DataType.build("BOOLEAN"))


@transform(
    "parse_ts", arity=1, arg_kinds=(ArgKind.STR,), input=(StringType,), output=TimestampType()
)
def parse_ts(col: Expression, fmt: str) -> Expression:
    if fmt == _ISO8601:
        return exp.cast(col, exp.DataType.build("TIMESTAMP"))
    return exp.StrToTime(this=col, format=exp.Literal.string(fmt))


@transform("parse_date", arity=1, arg_kinds=(ArgKind.STR,), input=(StringType,), output=DateType())
def parse_date(col: Expression, fmt: str) -> Expression:
    if fmt == _ISO8601:
        return exp.cast(col, exp.DataType.build("DATE"))
    return exp.StrToDate(this=col, format=exp.Literal.string(fmt))


@transform(
    "to_utc", arity=1, arg_kinds=(ArgKind.STR,), input=(TimestampType,), output=TimestampType()
)
def to_utc(col: Expression, zone: str) -> Expression:
    """Interpret a zoneless local timestamp in ``zone`` — the only door into
    the always-UTC ``timestamp`` type (RFC 0004 §5.1)."""
    return exp.AtTimeZone(this=col, zone=exp.Literal.string(zone))


# ....................... #
# Null handling and JSON


@transform(
    "coalesce", arity=1, arg_kinds=(ArgKind.LITERAL,), input=_ALL_TYPES, output=lambda t, _args: t
)
def coalesce(col: Expression, fallback: str | int) -> Expression:
    return exp.Coalesce(this=col, expressions=[_literal(fallback)])


@transform(
    "nullif",
    arity=1,
    arg_kinds=(ArgKind.LITERAL,),
    input=_ALL_TYPES,
    output=lambda t, _args: t,
    nullifies=True,
)
def nullif(col: Expression, sentinel: str | int) -> Expression:
    return exp.Nullif(this=col, expression=_literal(sentinel))


@transform(
    "json_path",
    arity=1,
    arg_kinds=(ArgKind.STR,),
    input=(VariantType, StringType),
    output=VariantType(),
    nullifies=True,
)
def json_path(col: Expression, path: str) -> Expression:
    return exp.JSONExtract(this=col, expression=exp.Literal.string(path))


# ....................... #
# Arithmetic (decimal precision/scale tracked — RFC 0004 §5.4)


@transform(
    "multiply",
    arity=1,
    arg_kinds=(ArgKind.NUMBER,),
    input=(DecimalType,),
    output=_arith_output("multiply"),
)
def multiply(col: Expression, factor: str | int) -> Expression:
    return exp.Mul(this=col, expression=_number(factor))


@transform(
    "divide",
    arity=1,
    arg_kinds=(ArgKind.NUMBER,),
    input=(DecimalType,),
    output=_arith_output("divide"),
)
def divide(col: Expression, divisor: str | int) -> Expression:
    return exp.Div(this=col, expression=_number(divisor))


def _round_output(t: LogicalType, args: tuple[str | int, ...]) -> LogicalType:
    if isinstance(t, IntType):
        return t
    current = _require_decimal(t, "round")
    digits = int(args[0])
    if digits < 0:
        msg = f"round digits must be >= 0, got {digits}"
        raise TypeCheckError(msg)
    precision = max(current.precision - current.scale + digits, digits, 1)
    if precision > _PRECISION_CAP:
        msg = (
            f"round(...) widens decimal({current.precision}, {current.scale}) past the "
            f"{_PRECISION_CAP}-digit precision cap"
        )
        raise TypeCheckError(msg)
    return DecimalType(precision=precision, scale=digits)


@transform(
    "round",
    arity=1,
    arg_kinds=(ArgKind.INT,),
    input=(IntType, DecimalType),
    output=_round_output,
)
def round_(col: Expression, digits: int) -> Expression:
    return exp.Round(this=col, decimals=exp.Literal.number(digits))


@transform("abs", arity=0, input=(IntType, DecimalType), output=lambda t, _args: t)
def abs_(col: Expression) -> Expression:
    return exp.Abs(this=col)


# ....................... #
# Currency-conversion marker (RFC 0004 D3; semantics land with RFC 0006)


@transform(
    "convert", arity=1, arg_kinds=(ArgKind.STR,), input=(DecimalType,), output=lambda t, _args: t
)
def convert(col: Expression, currency: str) -> Expression:
    """The explicit conversion marker the currency guardrail requires for
    mixed-currency arithmetic (RFC 0006). Typechecks decimal → decimal; the
    rate source and target-currency semantics are guardrail/emit concerns."""
    return exp.Anonymous(this="CONVERT_CURRENCY", expressions=[col, exp.Literal.string(currency)])
