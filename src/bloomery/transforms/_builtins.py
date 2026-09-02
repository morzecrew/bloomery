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

import re
from decimal import ROUND_HALF_UP, Decimal, localcontext

from sqlglot import exp
from sqlglot.expressions.core import Expression

from bloomery.errors import TypeCheckError
from bloomery.transforms.registry import OutputType, neutral_type, transform
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
    render_type,
)

# ----------------------- #

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


# ....................... #


def _number(value: str | int) -> Expression:
    """A NUMBER-kind arg as a SQLGlot numeric literal node."""

    return exp.Literal.number(value)


# ....................... #


def _typed_literal(value: str | int, input_type: LogicalType) -> Expression:
    """A literal argument, cast to the column's type where that changes anything.

    ``coalesce`` and ``nullif`` declare they produce the *input* type, and an
    uncast literal makes that false: Trino will not coerce a varchar literal to
    a non-varchar column at all, and an integer fallback over a decimal column
    widens the result past the declared ``(p, s)`` on every engine
    (RFC 0029 §2.1, §2.4).

    A string literal against a ``string`` column is the one case where the cast
    buys nothing — all three engines already read it as text — and the emitted
    SQL is a reviewed artifact, so ``COALESCE(segment, 'unknown')`` is left as
    it reads in the spec rather than becoming ``COALESCE(segment, CAST('unknown'
    AS TEXT))``. The condition is on the literal *and* the type: ``{coalesce: 0}``
    over a string column still casts, because ``COALESCE(text, 0)`` does not plan
    on Trino.
    """

    if isinstance(input_type, StringType) and isinstance(value, str):
        return _literal(value)

    return exp.cast(_literal(value), neutral_type(input_type))


# ....................... #


#: The one numeric spelling every engine's text-to-decimal cast agrees on:
#: optional sign, ASCII digits, optional dot-fraction. ``Decimal`` alone is
#: too permissive a gate — it accepts exponents, underscores, padding and
#: Unicode digits (``"1e3"``, ``"1_0"``, ``" 1 "``, ``"١٢٣"``) that the
#: emitted ``CAST('…' AS DECIMAL)`` does not portably accept, which would
#: re-open the compile-and-fail hole this check closes. ``[0-9]`` rather than
#: ``\\d`` for the same reason.
_PLAIN_NUMBER = re.compile(r"[+-]?([0-9]+(\.[0-9]+)?|\.[0-9]+)\Z")


def _checked_passthrough(t: LogicalType, args: tuple[str | int, ...]) -> LogicalType:
    """``coalesce``/``nullif`` produce the input type — after proving the
    literal survives the cast :func:`_typed_literal` emits.

    The cast makes the declared *type* true (RFC 0029 §2.1/§2.4) and says
    nothing about the *value*: a fallback whose integral part cannot fit
    ``decimal(p, s)`` raises ``ConversionException`` on the engine, so the
    spec compiled and failed at run time (T-0002 D-018) — the degradation
    RFC 0008 D3 refuses. The bound is applied to the value *rounded to the
    declared scale*, because that is what the engines cast: ``9.999`` is below
    10 and still overflows ``decimal(3, 2)``, rounding to ``10.00``. Only
    decimal columns are value-checked: theirs is the one cast whose failure is
    decidable from ``(p, s)`` alone at compile time.
    """
    if isinstance(t, DecimalType):
        value = args[0]

        if isinstance(value, str) and _PLAIN_NUMBER.match(value) is None:
            msg = (
                f"literal {value!r} is not a number the emitted CAST portably accepts — "
                f"only plain sign/digits/fraction spellings reach decimal({t.precision}, "
                f"{t.scale}) on every engine; no exponents, underscores or padding"
            )
            raise TypeCheckError(msg)

        parsed = Decimal(str(value))
        # Quantize under a context sized to the literal itself, never the
        # default 28-digit one: a fitting 38-digit fallback must not be
        # misread as overflow, and with room for every digit plus the target
        # scale the quantize cannot raise — the magnitude compare below is
        # the one arbiter of fit.
        with localcontext() as ctx:
            ctx.prec = len(parsed.as_tuple().digits) + t.scale + 2
            rounded = parsed.quantize(Decimal(1).scaleb(-t.scale), rounding=ROUND_HALF_UP)

        # ``copy_abs`` rather than ``abs``: the builtin is a *context*
        # operation and would re-round a wide value back to 28 digits, undoing
        # the widened quantize above.
        if rounded.copy_abs() >= Decimal(10) ** (t.precision - t.scale):
            msg = (
                f"literal {value!r} does not fit decimal({t.precision}, {t.scale}): the "
                f"emitted CAST would overflow at run time on every engine — the value's "
                f"magnitude, rounded to scale {t.scale}, must stay below "
                f"10^{t.precision - t.scale}. Fix: use a fitting literal, or widen the "
                "field's declared type"
            )
            raise TypeCheckError(msg)

    return t


# ....................... #


def _literal_shape(value: str | int) -> tuple[int, int]:
    """The (precision, scale) a numeric literal contributes to arithmetic
    tracking (RFC 0004 §5.4). The arg-kind check guarantees a finite value."""
    parsed = Decimal(str(value))
    exponent = parsed.as_tuple().exponent
    scale = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    return max(len(parsed.as_tuple().digits), scale, 1), scale


# ....................... #


def _require_decimal(t: LogicalType, name: str) -> DecimalType:
    if not isinstance(t, DecimalType):  # pragma: no cover — input domain enforces
        msg = f"{name!r} requires a decimal input, got {t!r}"
        raise TypeCheckError(msg)

    return t


# ....................... #


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


# ....................... #


@transform("trim", arity=0, input=(StringType,), output=StringType())
def trim(col: Expression) -> Expression:
    return exp.Trim(this=col)


# ....................... #


@transform("upper", arity=0, input=(StringType,), output=StringType())
def upper(col: Expression) -> Expression:
    return exp.Upper(this=col)


# ....................... #


@transform("lower", arity=0, input=(StringType,), output=StringType())
def lower(col: Expression) -> Expression:
    return exp.Lower(this=col)


# ....................... #


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


# ....................... #


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


# ....................... #


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


# ....................... #


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


# ....................... #


@transform("concat", arity=1, arg_kinds=(ArgKind.STR,), input=(StringType,), output=StringType())
def concat(col: Expression, text: str) -> Expression:
    return exp.DPipe(this=col, expression=exp.Literal.string(text))


# ....................... #


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


# ....................... #


@transform("to_string", arity=0, input=_ALL_TYPES, output=StringType())
def to_string(col: Expression) -> Expression:
    return exp.cast(col, exp.DataType.build("TEXT"))


# ....................... #


@transform(
    "to_int",
    arity=0,
    input=(StringType, IntType, DecimalType, BoolType),
    output=IntType(),
    types=True,
)
def to_int(col: Expression, *, input_type: LogicalType) -> Expression:
    """``CAST(x AS BIGINT)``, through ``INT`` when the input is a boolean.

    PostgreSQL converts ``int4`` to boolean and back and refuses ``bigint`` in
    either direction (``42846``), so the single cast did not run there at all —
    a whitelisted transform dying on the first run of a shipped dialect
    (RFC 0029 §2.3). The two-step form is *neutral*, not a PostgreSQL spelling:
    DuckDB and Trino render and evaluate it identically, so the fix stays in the
    builder and no port learns about booleans.
    """

    if isinstance(input_type, BoolType):
        through_int = exp.cast(col, exp.DataType.build("INT"))
        return exp.cast(through_int, exp.DataType.build("BIGINT"))

    return exp.cast(col, exp.DataType.build("BIGINT"))


# ....................... #


def _to_decimal_output(_t: LogicalType, args: tuple[str | int, ...]) -> LogicalType:
    precision, scale = int(args[0]), int(args[1])

    if not 1 <= precision <= _PRECISION_CAP:
        msg = f"to_decimal precision must be between 1 and {_PRECISION_CAP}, got {precision}"
        raise TypeCheckError(msg)

    if not 0 <= scale <= precision:
        msg = f"to_decimal scale ({scale}) must be between 0 and precision ({precision})"
        raise TypeCheckError(msg)

    return DecimalType(precision=precision, scale=scale)


# ....................... #


@transform(
    "to_decimal",
    arity=2,
    arg_kinds=(ArgKind.INT, ArgKind.INT),
    input=(StringType, IntType, DecimalType),
    output=_to_decimal_output,
)
def to_decimal(col: Expression, precision: int, scale: int) -> Expression:
    return exp.cast(col, exp.DataType.build(f"DECIMAL({precision}, {scale})"))


# ....................... #


@transform("to_bool", arity=0, input=(StringType, IntType, BoolType), output=BoolType(), types=True)
def to_bool(col: Expression, *, input_type: LogicalType) -> Expression:
    """``CAST(x AS BOOLEAN)``, or ``x <> 0`` when the input is an integer.

    PostgreSQL refuses ``bigint`` → ``boolean`` outright. RFC 0029 D5 left open
    whether to spell it or refuse it, on the ground that a refusal would be
    "honest about ``to_bool`` over an arbitrary integer having no agreed
    meaning" — measured, the meaning *is* agreed: DuckDB and Trino both read
    every non-zero value as true, including negatives, which is exactly
    ``x <> 0``. There was nothing to be honest about, so it is spelled
    (logs/T-0002.md D-001, D5 settled).

    ``x <> 0`` rather than ``CAST(CAST(x AS INT) AS BOOLEAN)`` because the
    second overflows for a ``bigint`` outside ``int4``.
    """

    if isinstance(input_type, IntType):
        return exp.NEQ(this=col, expression=exp.Literal.number(0))

    return exp.cast(col, exp.DataType.build("BOOLEAN"))


# ....................... #


#: The marker wrapping the *text* an ISO 8601 parse is about to cast
#: (RFC 0027 D4). Each dialect's ``render`` replaces it with whatever that
#: engine needs to accept both ISO spellings — nothing at all on DuckDB and
#: PostgreSQL, whose own casts take the ``T`` separator, and a separator
#: rewrite on Trino, whose cast takes only the space form and returns NULL for
#: the other.
#:
#: It marks the text rather than replacing the cast, and that is load-bearing:
#: :func:`bloomery.resolve.build._try_cast_shape` rewrites every ``Cast`` in a
#: chain to ``TryCast`` for entities inside the quality system, and a marker
#: standing where the cast stood would not be rewritten — turning the one
#: construct that most needs to mark a coercion failure back into
#: produce-or-raise.
#:
#: A dialect that does not strip it renders a function no engine defines, which
#: fails at plan time. That is deliberate: the alternative for a port whose
#: cast rejects ISO 8601 is silently NULL data.
ISO_TEXT_MARKER = "BLM_ISO_TEXT"


def _iso_text(col: Expression) -> Expression:
    return exp.Anonymous(this=ISO_TEXT_MARKER, expressions=[col])


# ....................... #


@transform(
    "parse_ts", arity=1, arg_kinds=(ArgKind.STR,), input=(StringType,), output=TimestampType()
)
def parse_ts(col: Expression, fmt: str) -> Expression:
    if fmt == _ISO8601:
        return exp.cast(_iso_text(col), exp.DataType.build("TIMESTAMP"))

    return exp.StrToTime(this=col, format=exp.Literal.string(fmt))


# ....................... #


@transform("parse_date", arity=1, arg_kinds=(ArgKind.STR,), input=(StringType,), output=DateType())
def parse_date(col: Expression, fmt: str) -> Expression:
    if fmt == _ISO8601:
        # Deliberately *not* marked, against RFC 0027 D6's assumption, on
        # engine-tier evidence. An ISO date has no `T` to rewrite, and the case
        # the marker would have covered — a full ISO timestamp fed to a date
        # parser — is not helped by it: Trino cannot cast `2026-01-06 12:00:00`
        # to DATE either, so the rewrite only converts a NULL into
        # `INVALID_CAST_ARGUMENT: Value cannot be cast to date`. Marking here
        # would trade a silent wrong answer for a louder wrong answer while
        # moving every date golden on every dialect for nothing.
        return exp.cast(col, exp.DataType.build("DATE"))

    return exp.StrToDate(this=col, format=exp.Literal.string(fmt))


# ....................... #


@transform(
    "to_utc", arity=1, arg_kinds=(ArgKind.STR,), input=(TimestampType,), output=TimestampType()
)
def to_utc(col: Expression, zone: str) -> Expression:
    """Interpret a zoneless local timestamp in ``zone`` — the only door into
    the always-UTC ``timestamp`` type (RFC 0004 §5.1)."""

    return exp.AtTimeZone(this=col, zone=exp.Literal.string(zone))


# ....................... #
# Null handling and JSON


# ....................... #


@transform(
    "coalesce",
    arity=1,
    arg_kinds=(ArgKind.LITERAL,),
    input=_ALL_TYPES,
    output=_checked_passthrough,
    types=True,
)
def coalesce(col: Expression, fallback: str | int, *, input_type: LogicalType) -> Expression:
    """``COALESCE(x, <fallback cast to x's type>)``.

    The fallback is cast because the transform declares it produces the *input*
    type and an uncast literal makes that false in two different ways
    (RFC 0029 §2.1, §2.4):

    * on Trino the expression does not plan at all — it does not coerce a
      varchar literal to the column's type, so ``{coalesce: "1970-01-01"}`` over
      a ``date`` field ran on DuckDB and PostgreSQL and failed here;
    * on every engine an integer fallback over a decimal column *widened* the
      result past the declared ``(p, s)``, so the declared type was not the
      emitted one.

    Casting the literal settles D6 in favour of the spec surface staying as it
    is: the alternative was rejecting a literal whose type cannot match, which
    would have made a spec that runs today on two of three engines stop
    compiling on all three.
    """

    return exp.Coalesce(this=col, expressions=[_typed_literal(fallback, input_type)])


# ....................... #


@transform(
    "nullif",
    arity=1,
    arg_kinds=(ArgKind.LITERAL,),
    input=_ALL_TYPES,
    output=_checked_passthrough,
    nullifies=True,
    types=True,
)
def nullif(col: Expression, sentinel: str | int, *, input_type: LogicalType) -> Expression:
    """``NULLIF(x, <sentinel cast to x's type>)``.

    Same reason as ``coalesce``: Trino refuses to compare a varchar literal
    against a non-varchar column (``TYPE_MISMATCH``), so a sentinel that worked
    on two engines failed on the third (RFC 0029 §2.4).
    """

    return exp.Nullif(this=col, expression=_typed_literal(sentinel, input_type))


# ....................... #


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


# ....................... #


#: The marker wrapping a ``divide``'s two operands (RFC 0029 D3).
#:
#: It exists to tell the transform's division apart from any other ``/`` in the
#: tree. The treatment — exact, non-float division — is the same on every port,
#: so :meth:`bloomery.dialects.base.SQLGlotDialect.render` applies it centrally
#: rather than each port re-deciding; what could not be central is *which*
#: divisions to apply it to, since a ratio metric's ``COUNT(a) / COUNT(b)`` must
#: keep the engine's own division semantics.
DIVIDE_MARKER = "BLM_EXACT_DIV"


#: Hoisted so the declaration and the construction call the *same* function
#: rather than two that agree by inspection (RFC 0029 D2).
_MULTIPLY_OUTPUT = _arith_output("multiply")
_DIVIDE_OUTPUT = _arith_output("divide")


def _narrowed(node: Expression, declared: LogicalType) -> Expression:
    """An arithmetic result, cast to the type the transform declares.

    Every engine widens decimal arithmetic past the ``(p, s)`` RFC 0004 §5.4
    tracks, and each widens differently: ``decimal(12,4) * 2`` is
    ``decimal(18,4)`` on DuckDB, ``decimal(22,4)`` on Trino and unconstrained
    ``numeric`` on PostgreSQL, against a declared ``decimal(13,4)``. No value is
    lost by that — every one of them is a widening — but the declaration stops
    being true, and with it the 38-digit precision cap, which is computed over
    the numbers the compiler tracks rather than the ones the engine uses.

    The cast is lossless by construction for these transforms: the algebra
    ``decimal(p1,s1) x decimal(p2,s2) -> p1+p2`` is exactly what
    :func:`_arith_output` declares, so the declared width always holds the exact
    result. It is not lossless for `coalesce`, whose declared type is its
    *input* type and whose literal is not bounded by it — which is why that one
    casts the literal instead (logs/T-0002.md D-002).

    Inside the quality system this cast becomes a ``TRY_CAST`` like any other
    (``_try_cast_shape``), so an overflow is a coercion failure and a
    quarantined row rather than an aborted run — the disposition RFC 0016
    already gives every other bad value.
    """

    return exp.cast(node, neutral_type(declared))


# ....................... #


@transform(
    "multiply",
    arity=1,
    arg_kinds=(ArgKind.NUMBER,),
    input=(DecimalType,),
    output=_MULTIPLY_OUTPUT,
    types=True,
)
def multiply(col: Expression, factor: str | int, *, input_type: LogicalType) -> Expression:
    product = exp.Mul(this=col, expression=_number(factor))
    return _narrowed(product, _MULTIPLY_OUTPUT(input_type, (factor,)))


# ....................... #


@transform(
    "divide",
    arity=1,
    arg_kinds=(ArgKind.NUMBER,),
    input=(DecimalType,),
    output=_DIVIDE_OUTPUT,
    types=True,
)
def divide(col: Expression, divisor: str | int, *, input_type: LogicalType) -> Expression:
    """``x / n``, marked so the ports can keep it in exact arithmetic.

    SQLGlot renders a bare division as ``CAST(x AS DOUBLE PRECISION) / n`` on
    PostgreSQL and ``CAST(x AS DOUBLE) / n`` on Trino — an explicit **binary
    float** on an emission path, which RFC 0003 D5 forbids, on the transform
    whose output is most often money.

    No golden moved when this was fixed, and that is worth knowing rather than
    glossing: the ``CAST(CAST(total AS DOUBLE PRECISION) / qty AS DECIMAL(12,
    4))`` in the ``ecom_basic`` goldens comes from a *catalog recipe* —
    ``expr: line_total / quantity`` — whose SQL is parsed rather than built,
    so it carries no marker and is untouched here. That float is real and still
    ships; it is recorded in logs/T-0002.md D-004, not fixed by this.

    ``exp.Div(typed=True)`` suppresses that cast and **does not survive the
    canonical round trip** — the IR keeps text and ``x / 2`` carries no flag
    (RFC 0003 D2). Re-reading every ``Div`` at render was the other option and
    is wrong: a ratio metric dividing two counts would silently become integer
    division. So the division is marked, exactly as ``parse_ts`` marks an ISO
    parse (RFC 0027 D4), and the marker says *this division came from the
    transform* rather than from someone's SQL (RFC 0029 D3).
    """
    marked = exp.Anonymous(this=DIVIDE_MARKER, expressions=[col, _number(divisor)])
    return _narrowed(marked, _DIVIDE_OUTPUT(input_type, (divisor,)))


# ....................... #


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


# ....................... #


@transform(
    "round",
    arity=1,
    arg_kinds=(ArgKind.INT,),
    input=(IntType, DecimalType),
    output=_round_output,
    types=True,
)
def round_(col: Expression, digits: int, *, input_type: LogicalType) -> Expression:
    rounded = exp.Round(this=col, decimals=exp.Literal.number(digits))
    return _narrowed(rounded, _round_output(input_type, (digits,)))


# ....................... #


@transform("abs", arity=0, input=(IntType, DecimalType), output=lambda t, _args: t, types=True)
def abs_(col: Expression, *, input_type: LogicalType) -> Expression:
    return _narrowed(exp.Abs(this=col), input_type)


# ....................... #
# Currency-conversion marker (RFC 0004 D3) — refused at emit (RFC 0023 D4)


# ....................... #


#: The call :func:`convert` builds, and the token the lowering resolves — or,
#: where no rate relation is declared, the token the emit side refuses on
#: (RFC 0023 D4/§5.4). Shared rather than spelled thrice: a marker whose
#: producer, resolver and refusal disagree about its name is a refusal that
#: never fires.
CONVERT_MARKER = "CONVERT_CURRENCY"

#: Positions inside the marker call, after the amount at 0. Named so the
#: builder here, the resolver in ``resolve.build`` and the emit-time rewrite
#: index one vocabulary.
CONVERT_FROM, CONVERT_TO, CONVERT_ANCHOR, CONVERT_TYPE = 1, 2, 3, 4

#: How many expressions a well-formed marker carries — the amount plus the four
#: above. Defined here rather than counted at each reader: the resolver and the
#: emit-time rewrite both gate on it, and when the two spelled it separately,
#: adding an argument updated one of them and left the other matching nothing.
#: The anchor then stayed the field *name* all the way into the emitted SQL,
#: where it compared a string literal against a date and neither guard noticed.
CONVERT_ARITY = 5


@transform(
    "convert",
    arity=3,
    arg_kinds=(ArgKind.STR, ArgKind.STR, ArgKind.STR),
    input=(DecimalType,),
    output=lambda t, _args: t,
    types=True,
)
def convert(
    col: Expression, from_ccy: str, to_ccy: str, anchor: str, *, input_type: LogicalType
) -> Expression:
    """Convert a decimal amount between two declared currencies, as of a date
    (RFC 0023 §5.4).

    ``{convert: [EUR, USD, paid_at]}`` — the currency the column is in, the
    currency it should end up in, and the field whose value dates the rate.
    All three are declared because none can be safely inferred: the source path
    carries no currency, and guessing the anchor from a mart's date role is the
    "plausible number against the wrong version of history" this RFC refuses
    (RFC 0021 closes inference).

    What this builds is a **marker**, not the conversion. The rate lives in a
    relation named by the catalog and the anchor's value comes from a sibling
    field's own lowering, and a transform builder sees neither — it gets an
    expression and literals. So the chain carries the request forward and
    ``resolve.build`` rewrites it into the as-of subquery once the catalog is
    in scope. A marker that survives to emit is a conversion no catalog
    declared rates for, which is exactly what :class:`UnsupportedByTarget`
    then says.

    The three-argument spelling replaced ``{convert: USD}``, which could not be
    finished rather than merely being unimplemented: a rate without a date is
    under-determined, so the old signature named no rate that exists.

    The marker also carries the **running type** — what the chain holds where
    this step sits, which is what conversion produces, since the declared
    output is the input unchanged. Emit multiplies by the rate and narrows back
    to it, exactly as :func:`multiply` and :func:`divide` narrow to their own
    ``_arith_output``. Reaching for the *field's* type instead would let a
    later widening step in the same chain absorb an overflow the compiler
    believes cannot happen here.
    """

    return exp.Anonymous(
        this=CONVERT_MARKER,
        expressions=[
            col,
            exp.Literal.string(from_ccy),
            exp.Literal.string(to_ccy),
            exp.Literal.string(anchor),
            exp.Literal.string(render_type(input_type)),
        ],
    )
