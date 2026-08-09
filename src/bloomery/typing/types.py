"""The closed ``LogicalType`` set (RFC 0004 §5.1).

Seven frozen dataclasses — no ``float`` (banned package-wide, RFC 0003 D5),
no ``time``, no arrays/structs (``variant`` is the escape hatch). A
``timestamp`` in bloomery *is* UTC; ``to_utc`` is the only door in.

``parse_type`` consumes the same grammar the spec layer validates
(:data:`bloomery.spec.common.TYPE_STRING_PATTERN`), so it can only fail on
grammar the regex admits but the type set rejects — it still raises
:class:`~bloomery.errors.TypeCheckError` with the field's source path rather
than asserting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from bloomery.errors import TypeCheckError
from bloomery.spec.common import TYPE_STRING_PATTERN

__all__ = [
    "ArgKind",
    "BoolType",
    "DateType",
    "DecimalType",
    "IntType",
    "LogicalType",
    "StringType",
    "TimestampType",
    "VariantType",
    "assignable",
    "parse_type",
    "render_type",
]


class ArgKind(StrEnum):
    """Parse-level shape of one transform argument (RFC 0004 §5.2).

    Declared by a :class:`~bloomery.transforms.TransformSpec` per argument
    position and enforced by the typecheck stage (RFC 0004 §5.4) before the
    builder ever sees the value. Lives in the type layer so both the transform
    registry and the typechecker consume one vocabulary without a cycle.
    """

    STR = "str"
    INT = "int"
    #: An int or a decimal-parseable string — literal arithmetic operands.
    NUMBER = "number"
    #: A str or an int — literals mirrored into SQL as-is (coalesce/nullif).
    LITERAL = "literal"


@dataclass(frozen=True, slots=True)
class StringType:
    """Arbitrary-length UTF-8 text."""


@dataclass(frozen=True, slots=True)
class IntType:
    """64-bit signed integer."""


@dataclass(frozen=True, slots=True)
class DecimalType:
    """Fixed-point decimal with explicit precision and scale."""

    precision: int
    scale: int


@dataclass(frozen=True, slots=True)
class BoolType:
    """Boolean."""


@dataclass(frozen=True, slots=True)
class DateType:
    """Calendar date, no time component."""


@dataclass(frozen=True, slots=True)
class TimestampType:
    """Instant in time — semantically always UTC (RFC 0004 §5.1); ``to_utc``
    is how a local timestamp gets here. No zone parameter by design."""


@dataclass(frozen=True, slots=True)
class VariantType:
    """Semi-structured escape hatch for the unmapped tail."""


LogicalType = StringType | IntType | DecimalType | BoolType | DateType | TimestampType | VariantType

_TYPE_RE = re.compile(TYPE_STRING_PATTERN)

_SCALARS: dict[str, LogicalType] = {
    "string": StringType(),
    "int": IntType(),
    "bool": BoolType(),
    "date": DateType(),
    "timestamp": TimestampType(),
    "variant": VariantType(),
}


def parse_type(text: str, *, source_path: str) -> LogicalType:
    """Parse a spec-layer type string into a :data:`LogicalType`.

    Raises :class:`TypeCheckError` carrying ``source_path`` on any input
    outside the closed grammar, or on a decimal whose parameters the type set
    rejects (``precision >= 1``, ``scale <= precision``).
    """
    match = _TYPE_RE.match(text)
    if match is None:
        raise TypeCheckError(
            f"unknown type {text!r}: expected one of string, int, bool, date, "
            "timestamp, variant, decimal(p, s)",
            source_path=source_path,
        )
    scalar = _SCALARS.get(text)
    if scalar is not None:
        return scalar
    precision, scale = int(match.group(1)), int(match.group(2))
    if precision < 1:
        raise TypeCheckError(
            f"invalid type {text!r}: decimal precision must be >= 1",
            source_path=source_path,
        )
    if scale > precision:
        raise TypeCheckError(
            f"invalid type {text!r}: decimal scale ({scale}) must not exceed "
            f"precision ({precision})",
            source_path=source_path,
        )
    return DecimalType(precision=precision, scale=scale)


def assignable(actual: LogicalType, declared: LogicalType) -> bool:
    """Is a value of type ``actual`` assignable to a field declared ``declared``?

    Identity for all scalar types; anything is assignable to ``variant``;
    a decimal is assignable to a wider-or-equal declared decimal (both
    ``precision - scale`` and ``scale`` non-decreasing). Narrowing is never
    implicit (RFC 0004 §5.1).
    """
    if isinstance(declared, VariantType):
        return True
    if isinstance(actual, DecimalType) and isinstance(declared, DecimalType):
        return (
            declared.scale >= actual.scale
            and declared.precision - declared.scale >= actual.precision - actual.scale
        )
    return actual == declared


#: The spec-layer spelling of each scalar logical type — the inverse of
#: :func:`parse_type`'s grammar.
_SCALAR_NAMES: dict[type[LogicalType], str] = {
    StringType: "string",
    IntType: "int",
    BoolType: "bool",
    DateType: "date",
    TimestampType: "timestamp",
    VariantType: "variant",
}


def render_type(logical: LogicalType) -> str:
    """A logical type as the string a spec would have written.

    The round-trip partner of :func:`parse_type`, and public because three
    unrelated consumers need the *same* spelling: `plan()`'s change reprs, the
    step manifest a generated wrapper embeds (RFC 0017 §5.4), and anything
    else that reports a type back to a human. A second spelling somewhere
    would not merely be untidy — the step contract looks its declared types up
    in a table, so a repr like ``StringType()`` silently matches nothing and
    turns a mandatory check into a no-op.
    """
    if isinstance(logical, DecimalType):
        return f"decimal({logical.precision},{logical.scale})"
    return _SCALAR_NAMES[type(logical)]
