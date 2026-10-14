"""Every built-in transform's value semantics, stated in Python (S-0092/D-1).

This is the **second, independent statement** of what each whitelisted
transform does. The compiler states it once — in the SQLGlot builders under
``src/bloomery/transforms/_builtins.py`` — and a differential test can then say
*which* statement an engine broke, rather than only that its answer differed.
The rules here are written from ``pages/docs/reference/transforms.md`` and the
decision rows that page cites, **never** from the builders: a reference that
read the builders would agree with them by construction and hide the defect
this exists to find.

The vocabulary is deliberately small. A transform's Python function takes the
values its declared input domain admits — ``None``, ``int``, ``Decimal``,
``str``, ``bool``, ``date``, a zoneless UTC ``datetime``, and parsed JSON for a
variant — and returns its declared output. Decimals are quantized with
``ROUND_HALF_UP``; a value outside the declared precision is :data:`OVERFLOW`,
which a plain entity's engine must *raise* and a quality-ruled entity's must
return as NULL (D-1).

A transform whose input is not text is reached through a **typed setup step** —
``{to_decimal: [12, 4]}`` ahead of ``abs``, ``{parse_ts: ISO8601}`` ahead of
``to_utc`` — and :func:`fold` applies the same setup to the source text, so the
reference and the compiled chain walk the same steps in the same order.
``convert`` is the one case that cannot be a pure function of the value: it
reads the fixture's ``fx_rates`` relation and the row's anchor date, so it
builds its reference from those (:func:`converting`).
"""

from __future__ import annotations

import json
import re
import string
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from hypothesis import strategies as st

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from hypothesis.strategies import SearchStrategy

__all__ = [
    "CASES",
    "CONVERT_ANCHOR",
    "FX_RATES",
    "OVERFLOW",
    "Case",
    "Fixture",
    "Overflow",
    "SEMANTICS",
    "Step",
    "converting",
    "fold",
]


# ----------------------- #
# Values


class Overflow:
    """A value outside the declared type's precision.

    A *value*, not an exception, because the reference must name what a
    well-typed engine does with it: a plain entity's ``CAST`` raises, and an
    entity carrying a ``quality:`` block turns the same cast into ``TRY_CAST``
    and returns NULL (D-1). The differential reads this sentinel and holds the
    engine to the raise.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "Overflow"


#: The one :class:`Overflow` instance.
OVERFLOW = Overflow()


#: One chain step: the transform's name and its spec-level args, in the order
#: ``TransformStep`` normalizes them (``{to_decimal: [12, 4]}`` → ``(12, 4)``).
type Step = tuple[str, tuple[str | int, ...]]


# ----------------------- #
# Decimal helpers


def _scale(value: Decimal) -> int:
    """The number of fraction digits a ``Decimal`` carries."""
    exponent = value.as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def _literal_width(value: str | int) -> tuple[int, int]:
    """The (precision, scale) a numeric literal contributes to arithmetic."""
    parsed = Decimal(str(value))
    exponent = parsed.as_tuple().exponent
    scale = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    return max(len(parsed.as_tuple().digits), scale, 1), scale


def _literal_scale(value: str | int) -> int:
    """The scale a numeric literal contributes, matching ``_literal_shape``."""
    return _literal_width(value)[1]


@dataclass(frozen=True)
class Shape:
    """A ``decimal(precision, scale)`` width, tracked through a chain.

    The widths are the page's stated algebra, not the builders': ``multiply``
    and ``divide`` widen to ``decimal(p1+p2, s1+s2)``, and ``round`` narrows to
    ``decimal(max(p-s+d, d, 1), d)``. A value outside the width is
    :data:`OVERFLOW` — the plain engine's cast raises on it (D-1).
    """

    precision: int
    scale: int


def shape_after(step: Step, shape: Shape | None) -> Shape | None:
    name, args = step
    if name == "to_decimal":
        return Shape(int(args[0]), int(args[1]))
    if shape is None:
        return None
    if name in {"multiply", "divide"}:
        if not args:
            return shape
        digits, scale = _literal_width(args[0])
        return Shape(shape.precision + digits, shape.scale + scale)
    if name == "round":
        digits = int(args[0])
        return Shape(max(shape.precision - shape.scale + digits, digits, 1), digits)
    return shape


def _quantize(value: Decimal, scale: int) -> Decimal:
    """``value`` at ``scale`` fraction digits, ties away from zero."""
    with localcontext() as ctx:
        ctx.prec = max(len(value.as_tuple().digits) + scale + 2, 28)
        return value.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)


def _fits(value: Decimal, precision: int, scale: int) -> bool:
    """Whether ``value`` fits ``decimal(precision, scale)`` once quantized."""
    with localcontext() as ctx:
        ctx.prec = 60
        return value.copy_abs() < Decimal(10) ** (precision - scale)


# ----------------------- #
# String transforms


def trim(value: str | None) -> str | None:
    """Strip surrounding **spaces** — SQL ``TRIM``'s default, not ``str.strip``'s
    whole-whitespace set."""
    return None if value is None else value.strip(" ")


def upper(value: str | None) -> str | None:
    return None if value is None else value.upper()


def lower(value: str | None) -> str | None:
    return None if value is None else value.lower()


def split_part(value: str | None, delimiter: str, index: int) -> str | None:
    """The nth (1-indexed) delimited part, or NULL when there is no such part.

    NULL is the **portable** reading the transform declares (``nullifies=True``):
    DuckDB answers ``''`` where Trino answers NULL, and the difference is a
    D-3 row rather than a tolerance (``engine_differences``).
    """
    if value is None:
        return None
    parts = value.split(delimiter)
    return parts[index - 1] if 1 <= index <= len(parts) else None


def regex_extract(value: str | None, pattern: str, group: int) -> str | None:
    """The capture group, or NULL when the pattern does not match — the
    portable reading; DuckDB answers ``''``."""
    if value is None:
        return None
    match = re.search(pattern, value)
    return match.group(group) if match is not None else None


def strip_prefix(value: str | None, prefix: str) -> str | None:
    if value is None:
        return None
    return value[len(prefix) :] if value.startswith(prefix) else value


def strip_suffix(value: str | None, suffix: str) -> str | None:
    if value is None:
        return None
    if not suffix or not value.endswith(suffix):
        return value
    return value[: -len(suffix)]


def concat(value: str | None, text: str) -> str | None:
    return None if value is None else value + text


def enum_map(value: str | None, *pairs: str) -> str | None:
    """Map values through from/to pairs; unmapped values (and NULL) pass through."""
    if value is None:
        return None
    mapping = dict(zip(pairs[0::2], pairs[1::2], strict=True))
    return mapping.get(value, value)


# ----------------------- #
# Casts and parses


def to_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (int, date, datetime)):
        return str(value)
    msg = f"to_string has no stated text for {value!r}"
    raise TypeError(msg)


def to_int(value: Any) -> int | Overflow | None:
    if value is None:
        return None
    if isinstance(value, bool):
        number = 1 if value else 0
    elif isinstance(value, int):
        number = value
    else:
        number = int(Decimal(str(value)).to_integral_value(rounding=ROUND_HALF_UP))
    if not -(2**63) <= number < 2**63:
        return OVERFLOW
    return number


def to_decimal(value: Any, precision: int, scale: int) -> Decimal | Overflow | None:
    """`CAST(x AS DECIMAL(p, s))`, quantized ``ROUND_HALF_UP``."""
    if value is None:
        return None
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    rounded = _quantize(amount, scale)
    return rounded if _fits(rounded, precision, scale) else OVERFLOW


def to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    return value.strip().lower() in {"true", "t", "1"}


#: A time part's ``+``/``-`` (an offset) after the date, or a trailing ``Z``.
_OFFSET = re.compile(r"(?:[+-][0-9]{2}:?[0-9]{2}|Z)$")


def parse_ts(value: str | None, fmt: str) -> datetime | None:
    """``parse_ts: ISO8601`` reads a zoneless wall clock; text stating its own
    offset is NULL (S-0052/D-6)."""
    if value is None:
        return None
    if fmt == "ISO8601" and _OFFSET.search(value):
        return None
    return datetime.fromisoformat(value)


def parse_date(value: str | None, fmt: str) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)


def to_utc(value: datetime | None, zone: str) -> datetime | None:
    """Interpret a zoneless wall clock in ``zone`` and keep the UTC instant,
    zoneless — the always-UTC ``timestamp`` type (S-0081)."""
    if value is None:
        return None
    return value.replace(tzinfo=ZoneInfo(zone)).astimezone(timezone.utc).replace(tzinfo=None)


# ----------------------- #
# Null handling and JSON


def coalesce(value: Any, fallback: Any) -> Any:
    return fallback if value is None else value


def nullif(value: Any, sentinel: Any) -> Any:
    return None if value == sentinel else value


#: One JSONPath step: a ``.key`` or an ``[index]``.
_JSON_STEP = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[([0-9]+)\]")


def _walk_json(document: Any, path: str) -> Any:
    if not path.startswith("$"):
        msg = f"json_path must start at the document root, got {path!r}"
        raise ValueError(msg)
    current = document
    for key, index in _JSON_STEP.findall(path[1:]):
        if key:
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        else:
            if not isinstance(current, list) or int(index) >= len(current):
                return None
            current = current[int(index)]
    return current


def json_path(value: str | None, path: str) -> Any:
    """Extract ``path`` from a JSON document; a missing path is NULL."""
    if value is None:
        return None
    return _walk_json(json.loads(value), path)


# ----------------------- #
# Arithmetic


def multiply(
    value: Decimal | None, factor: str | int, *, shape: Shape | None = None
) -> Decimal | Overflow | None:
    """``decimal(p1,s1) x decimal(p2,s2) -> decimal(p1+p2, s1+s2)`` — exact, so
    quantizing to the widened scale changes nothing (S-0021)."""
    if value is None:
        return None
    with localcontext() as ctx:
        ctx.prec = 60
        product = value * Decimal(str(factor))
    return _narrowed(product, _scale(value) + _literal_scale(factor), shape)


def divide(
    value: Decimal | None, divisor: str | int, *, shape: Shape | None = None
) -> Decimal | Overflow | None:
    """Exact decimal division, quantized to the widened scale ``ROUND_HALF_UP``.

    DuckDB's ``/`` is float and cannot be exact (S-0046/D-3, S-0092/D-8), so a
    disagreement here is a D-3 row rather than a tolerance.
    """
    if value is None:
        return None
    with localcontext() as ctx:
        ctx.prec = 60
        quotient = value / Decimal(str(divisor))
    return _narrowed(quotient, _scale(value) + _literal_scale(divisor), shape)


def round_(
    value: int | Decimal | None, digits: int, *, shape: Shape | None = None
) -> int | Decimal | Overflow | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return _narrowed(value, digits, shape)


def abs_(
    value: int | Decimal | None, *, shape: Shape | None = None
) -> int | Decimal | Overflow | None:
    if value is None:
        return None
    if shape is not None and not _fits(value, shape.precision, shape.scale):
        return OVERFLOW
    return abs(value)


def _narrowed(amount: Decimal, scale: int, shape: Shape | None) -> Decimal | Overflow:
    """``amount`` at ``scale``, or :data:`OVERFLOW` when it leaves ``shape``."""
    rounded = _quantize(amount, scale)
    if shape is None:
        return rounded
    return rounded if _fits(rounded, shape.precision, shape.scale) else OVERFLOW


# ----------------------- #
# Currency


def convert(
    value: Decimal | None,
    from_ccy: str,
    to_ccy: str,
    anchor: str,
    *,
    rates: Sequence[tuple[str, str, Decimal, date, date | None]],
    on: date,
    shape: Shape | None = None,
) -> Decimal | None | Overflow:
    """Convert ``value`` at the rate current on ``on``, narrowed to its scale.

    A pair, or a date, the relation does not cover converts to NULL — the miss
    stays visible (S-0040/D-11). The catalog-declared ``fx_rates`` relation is
    the operator's, so the differential supplies it here (D-1); the chain
    reference is built with :func:`converting`.
    """
    del anchor  # the anchor's *value* is `on`; the name is a spec-level handle
    if value is None:
        return None
    rate = next(
        (
            row_rate
            for row_from, row_to, row_rate, valid_from, valid_to in rates
            if (row_from, row_to) == (from_ccy, to_ccy)
            and valid_from <= on
            and (valid_to is None or on < valid_to)
        ),
        None,
    )
    if rate is None:
        return None
    with localcontext() as ctx:
        ctx.prec = 60
        converted = value * rate
    return _narrowed(converted, _scale(value), shape)


def converting(
    rates: Sequence[tuple[str, str, Decimal, date, date | None]], on: date
) -> Callable[[str | None], Decimal | Overflow | None]:
    """A chain reference for a ``[{to_decimal: [12, 4]}, {convert: ...}]`` chain."""
    shape = Shape(12, 4)

    def reference(text: str | None) -> Decimal | Overflow | None:
        amount = to_decimal(text, 12, 4)
        if amount is None or amount is OVERFLOW:
            return amount
        return convert(amount, "EUR", "USD", "paid_at", rates=rates, on=on, shape=shape)

    return reference


# ----------------------- #
# The table


#: Transform name → its Python value semantics.
SEMANTICS: dict[str, Callable[..., Any]] = {
    "trim": trim,
    "upper": upper,
    "lower": lower,
    "split_part": split_part,
    "regex_extract": regex_extract,
    "strip_prefix": strip_prefix,
    "strip_suffix": strip_suffix,
    "concat": concat,
    "enum_map": enum_map,
    "to_string": to_string,
    "to_int": to_int,
    "to_decimal": to_decimal,
    "to_bool": to_bool,
    "parse_ts": parse_ts,
    "parse_date": parse_date,
    "to_utc": to_utc,
    "coalesce": coalesce,
    "nullif": nullif,
    "json_path": json_path,
    "multiply": multiply,
    "divide": divide,
    "round": round_,
    "abs": abs_,
    "convert": convert,
}


#: Transforms whose single-entity semantics need the declared width they
#: narrow to — the ones an engine's cast can overflow.
_WIDTH_AWARE = frozenset({"multiply", "divide", "round", "abs", "convert"})


def fold(chain: Sequence[Step], text: str | None) -> Any:
    """Apply a chain's semantics to a source text, in order.

    NULL propagates through every step but ``coalesce``, which is the whole
    point of that transform; an :data:`OVERFLOW` ends the chain, since a later
    step cannot rescue a value the previous one could not hold. The declared
    width is threaded alongside the value, so a narrowing step can say that its
    result overflows the field the compiler will cast it to (D-1).
    """
    value: Any = text
    shape: Shape | None = None
    for name, args in chain:
        if value is OVERFLOW:
            return OVERFLOW
        if value is None and name != "coalesce":
            continue
        function = SEMANTICS[name]
        output_shape = shape_after((name, args), shape)
        if name in _WIDTH_AWARE:
            value = function(value, *args, shape=output_shape)
        else:
            value = function(value, *args)
        shape = output_shape
    return value


# ----------------------- #
# Cases and fixtures


@dataclass(frozen=True)
class Fixture:
    """The one-entity project a case compiles, beyond the shared skeleton.

    The skeleton is one entity keyed by ``probe_id`` with one ``value`` field
    carrying the case's chain, read from a bronze ``raw__probe`` relation whose
    ``value`` column is text — the shape every mapping starts from. ``convert``
    is the one case that needs more: an anchor field, a declared
    ``currency_in:``, and a catalog naming the rate relation.
    """

    extra_fields: tuple[tuple[str, str], ...] = ()
    extra_mapping: tuple[str, ...] = ()
    value_prefix: str = ""
    catalog: str | None = None
    extra_columns: tuple[tuple[str, str, str], ...] = ()
    seed_sql: tuple[str, ...] = ()


_PLAIN = Fixture()


@dataclass(frozen=True)
class Case:
    """One built-in, the chain that exercises it, and the values drawn for it.

    ``chain`` is the spec-level setup *plus* the transform itself, so the
    terminal type is the field's declared type and :func:`fold` walks exactly
    what the compiler lowers. ``reference`` maps the drawn source text to the
    expected answer — the fold for every case but ``convert``.
    """

    transform: str
    chain: tuple[Step, ...]
    source: SearchStrategy[Any]
    reference: Callable[[Any], Any]
    fixture: Fixture = field(default=_PLAIN)


# ----------------------- #
# Source strategies


_ALPHABET = string.ascii_letters + string.digits + " -_.@/:,"

#: Free text: NULL, the empty string, ordinary text, and text that makes the
#: string transforms exercise their edges (leading/trailing spaces, a sentinel).
_TEXT = st.one_of(
    st.none(),
    st.just(""),
    st.just("  padded  "),
    st.just("N/A"),
    st.text(alphabet=_ALPHABET, max_size=16),
)

#: Decimal text at (12, 4): NULL, the boundaries, ordinary values, and two the
#: declared precision cannot hold (which must overflow).
_DECIMAL = st.one_of(
    st.none(),
    st.sampled_from(
        [
            "0",
            "0.0000",
            "99999999.9999",
            "-99999999.9999",
            "99999999.99999",
            "123456789012.3456",
            "0.00005",
            "-0.00005",
        ]
    ),
    st.builds(
        lambda whole, frac: f"{whole}.{frac:04d}",
        st.integers(-99999999, 99999999),
        st.integers(0, 9999),
    ),
    st.integers(-(2**40), 2**40).map(str),
)

#: Integer text: NULL, the 64-bit boundaries, overflow, and ordinary values.
_INTEGER = st.one_of(
    st.none(),
    st.sampled_from(
        ["0", "9223372036854775807", "-9223372036854775808", "9223372036854775808"]
    ),
    st.integers(-(2**40), 2**40).map(str),
)

#: Wall-clock ISO timestamps; no offset and no ``Z``, so no parse is refused.
_TIMESTAMP = st.one_of(
    st.none(),
    st.just("2024-01-02T03:04:05"),
    st.just("2026-12-31T23:59:59"),
    st.datetimes(
        min_value=datetime(2000, 1, 1), max_value=datetime(2030, 1, 1)
    ).map(lambda moment: moment.isoformat(sep="T")),
)

_ISO_DATE = st.one_of(
    st.none(),
    st.just("2024-02-29"),
    st.just("1970-01-01"),
    st.dates(min_value=date(1970, 1, 1), max_value=date(2099, 12, 31)).map(date.isoformat),
)

_BOOLEAN = st.one_of(st.none(), st.sampled_from(["true", "false", "1", "0", "t", "f"]))

#: JSON documents a variant extraction can be asked for: an object, a nested
#: object, an array, a scalar, and documents that lack the requested path.
_JSON = st.one_of(
    st.none(),
    st.just('{"a": 1}'),
    st.just('{"a": {"b": 2}}'),
    st.just('{"a": [10, 20, 30]}'),
    st.just('{"a": "x"}'),
    st.just('{"b": 3}'),
    st.just("[]"),
)

#: A time-of-day with no ambiguity in the zone below: the fall-back hour is
#: skipped, because DuckDB and ``zoneinfo`` resolve the repeated local hour to
#: different offsets and neither is "the" answer this reference may name.
_SAFE_HOUR = st.sampled_from([0, 6, 12, 18, 23])


def _unambiguous(zone: str = "Europe/Paris") -> SearchStrategy[datetime]:
    """Datetimes whose local reading in ``zone`` is not a repeated hour."""

    def ambiguous(moment: datetime) -> bool:
        early = moment.replace(tzinfo=ZoneInfo(zone), fold=0).utcoffset()
        late = moment.replace(tzinfo=ZoneInfo(zone), fold=1).utcoffset()
        return early != late

    return st.datetimes(
        min_value=datetime(2000, 1, 1), max_value=datetime(2030, 1, 1)
    ).filter(lambda moment: not ambiguous(moment))


_TZ_TEXT = st.one_of(
    st.none(),
    st.just("2026-01-06T12:00:00"),
    st.just("2026-07-06T12:00:00"),
    _unambiguous().map(lambda moment: moment.isoformat(sep="T")),
)


# ----------------------- #
# The rate relation the convert case reads


#: ``(from, to, rate, valid_from, valid_to)`` — one interval for EUR→USD, and a
#: pair nothing converts through.
FX_RATES: tuple[tuple[str, str, Decimal, date, date | None], ...] = (
    ("EUR", "USD", Decimal("1.10"), date(2024, 1, 1), date(2024, 6, 1)),
    ("EUR", "USD", Decimal("1.20"), date(2024, 6, 1), date(2025, 1, 1)),
    ("GBP", "USD", Decimal("9.99"), date(2024, 1, 1), None),
)

#: The anchor the convert case reads: inside the second EUR→USD interval.
CONVERT_ANCHOR = date(2024, 7, 4)


def _rate_row(row: tuple[str, str, Decimal, date, date | None]) -> str:
    parts = (
        "NULL" if part is None else f"'{part}'" if isinstance(part, (str, date)) else str(part)
        for part in row
    )
    return f"({', '.join(parts)})"


_CONVERT_CATALOG = """
catalog_version: 1
vertical: probe
fx_rates:
  relation: fx_rate
  from: from_ccy
  to: to_ccy
  rate: rate
  valid_from: valid_from
  valid_to: valid_to
canonical_fields:
  amount_usd: {entity: probe, type: "decimal(12,4)", unit: currency, tax_basis: net, currency: USD}
"""


# ----------------------- #
# The catalogue


#: The typed setup every decimal-input transform is reached through.
_T0: Step = ("to_decimal", (12, 4))


CASES: tuple[Case, ...] = (
    Case("abs", (_T0, ("abs", ())), _DECIMAL, lambda text: fold((_T0, ("abs", ())), text)),
    Case("concat", (("concat", ("-eu",)),), _TEXT, lambda text: fold((("concat", ("-eu",)),), text)),
    Case(
        "convert",
        (_T0, ("convert", ("EUR", "USD", "paid_at"))),
        _DECIMAL,
        converting(FX_RATES, CONVERT_ANCHOR),
        Fixture(
            extra_fields=(("paid_at", "date"),),
            extra_mapping=('  paid_at: {from: "$.paid_at", transform: [{parse_date: ISO8601}]}',),
            value_prefix="currency_in: EUR, ",
            catalog=_CONVERT_CATALOG,
            extra_columns=(("paid_at", "VARCHAR", CONVERT_ANCHOR.isoformat()),),
            seed_sql=(
                "CREATE TABLE silver.fx_rate (from_ccy VARCHAR, to_ccy VARCHAR, "
                "rate DECIMAL(12, 4), valid_from DATE, valid_to DATE)",
                "INSERT INTO silver.fx_rate VALUES " + ", ".join(map(_rate_row, FX_RATES)),
            ),
        ),
    ),
    Case("divide", (_T0, ("divide", (3,))), _DECIMAL, lambda text: fold((_T0, ("divide", (3,))), text)),
    Case(
        "enum_map",
        (("enum_map", ("F", "female", "M", "male")),),
        _TEXT,
        lambda text: fold((("enum_map", ("F", "female", "M", "male")),), text),
    ),
    Case("json_path", (("json_path", ("$.a",)),), _JSON, lambda text: fold((("json_path", ("$.a",)),), text)),
    Case("lower", (("lower", ()),), _TEXT, lambda text: fold((("lower", ()),), text)),
    Case("multiply", (_T0, ("multiply", (2,))), _DECIMAL, lambda text: fold((_T0, ("multiply", (2,))), text)),
    Case("nullif", (("nullif", ("N/A",)),), _TEXT, lambda text: fold((("nullif", ("N/A",)),), text)),
    Case("coalesce", (("coalesce", ("missing",)),), _TEXT, lambda text: fold((("coalesce", ("missing",)),), text)),
    Case(
        "parse_date",
        (("parse_date", ("ISO8601",)),),
        _ISO_DATE,
        lambda text: fold((("parse_date", ("ISO8601",)),), text),
    ),
    Case(
        "parse_ts",
        (("parse_ts", ("ISO8601",)),),
        _TIMESTAMP,
        lambda text: fold((("parse_ts", ("ISO8601",)),), text),
    ),
    Case(
        "regex_extract",
        (("regex_extract", (r"(\d+)", 1)),),
        _TEXT,
        lambda text: fold((("regex_extract", (r"(\d+)", 1)),), text),
    ),
    Case(
        "round",
        (_T0, ("round", (2,))),
        _DECIMAL,
        lambda text: fold((_T0, ("round", (2,))), text),
    ),
    Case(
        "split_part",
        (("split_part", ("-", 2)),),
        _TEXT,
        lambda text: fold((("split_part", ("-", 2)),), text),
    ),
    Case(
        "strip_prefix",
        (("strip_prefix", ("ord-",)),),
        _TEXT,
        lambda text: fold((("strip_prefix", ("ord-",)),), text),
    ),
    Case(
        "strip_suffix",
        (("strip_suffix", ("-eu",)),),
        _TEXT,
        lambda text: fold((("strip_suffix", ("-eu",)),), text),
    ),
    Case("to_bool", (("to_bool", ()),), _BOOLEAN, lambda text: fold((("to_bool", ()),), text)),
    Case(
        "to_decimal",
        (("to_decimal", (12, 4)),),
        _DECIMAL,
        lambda text: fold((("to_decimal", (12, 4)),), text),
    ),
    Case("to_int", (("to_int", ()),), _INTEGER, lambda text: fold((("to_int", ()),), text)),
    Case("to_string", (("to_string", ()),), _TEXT, lambda text: fold((("to_string", ()),), text)),
    Case(
        "to_utc",
        (("parse_ts", ("ISO8601",)), ("to_utc", ("Europe/Paris",))),
        _TZ_TEXT,
        lambda text: fold((("parse_ts", ("ISO8601",)), ("to_utc", ("Europe/Paris",))), text),
    ),
    Case("trim", (("trim", ()),), _TEXT, lambda text: fold((("trim", ()),), text)),
    Case("upper", (("upper", ()),), _TEXT, lambda text: fold((("upper", ()),), text)),
)