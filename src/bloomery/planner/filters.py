"""Filter rendering (RFC 0013 §5.6–§5.7, D8–D9; per-clause form per
RFC 0015 §5.4) — the highest-risk surface of the MetricFlow pivot:
``where_constraints`` are Jinja-templated strings, i.e. string construction
on the query path. Non-negotiable rules, all enforced here and fuzz-tested
(merge-blocking):

1. values are **never** interpolated raw — every literal goes through the
   typed renderer below, validated against the mart column's declared
   :class:`~bloomery.typing.LogicalType` (``FilterTypeMismatch`` on
   contradiction, never a cast);
2. the dimension name inside ``{{ Dimension('…') }}`` comes only from a
   validated :class:`~bloomery.planner.names.ResolvedDimension` via
   :mod:`bloomery.planner.names` — never from user input;
3. string literals double single quotes, refuse NUL, and neutralize Jinja
   delimiters character-by-character (``{`` → ``{{ "{" }}``) so template
   syntax inside a *value* survives as an inert SQL literal;
4. ``like``/``ilike`` operands are SQL ``LIKE`` **patterns** (RFC 0015
   decision 13): caller-owned wildcards with a fixed ``ESCAPE '\\'`` clause;
   the renderer adds nothing beyond injection safety — no auto-wrapping, no
   wildcard escaping (callers write ``\\%``/``\\_``/``\\\\`` themselves);
5. numbers render through ``int``/``Decimal`` repr (floats never survive
   request construction — RFC 0015 D5); a ``str`` operand against a decimal
   dimension is the string carrier (RFC 0015 D5): parsed as ``Decimal``
   here, non-finite refused as ``InvalidLiteral``, and **no SQL cast is
   ever emitted**; dates and timestamps are ISO-validated then
   re-serialized.

One ``where_constraints`` entry is emitted per :class:`Clause` (RFC 0015
D11): an :class:`AnyOf` group renders as a parenthesized ``OR``-join —
always parenthesized, because ``policy AND a OR b`` leaks every row
matching ``b``. ``ilike`` lowers portably as ``LOWER(x) LIKE
LOWER(pattern)``: DuckDB and Postgres have ``ILIKE`` but Trino does not,
and the neutral lowering keeps one rendering per clause across all three
dialects. This is a **portability choice**, not a claim of perfect
equivalence: ``LOWER``/``LOWER`` and a native ``ILIKE`` can diverge on
locale-dependent Unicode case folding (Turkish dotted ``İ``, German ``ß``);
for ASCII data — the overwhelming BI case — they agree, and one rendering
across all dialects beats per-dialect divergence (the ``\\`` escape
character is caseless either way).

The row policy is rendered through this exact pipeline and **prepended** to
the user filters (RFC 0013 D9), via ``RowPolicy.as_clause()``.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING
from uuid import UUID

from bloomery.errors import (
    FilterTypeMismatch,
    InvalidLiteral,
    InvalidRequest,
    PlannerError,
)
from bloomery.planner.names import group_by_name
from bloomery.planner.request import COMPARISON_OPS, AnyOf, Op, clause_predicates
from bloomery.typing import (
    BoolType,
    DateType,
    DecimalType,
    IntType,
    StringType,
    TimestampType,
)

if TYPE_CHECKING:
    from bloomery.ir import MartIR
    from bloomery.planner.names import ResolvedDimension
    from bloomery.planner.policy import RowPolicy
    from bloomery.planner.request import Clause, Predicate, Scalar
    from bloomery.typing import LogicalType

# ----------------------- #

__all__ = [
    "to_where",
]

#: Jinja delimiter neutralization (rule 3): emitted through Jinja string
#: literals, each brace renders back to itself *after* templating — so a
#: value containing ``{{ Dimension('x') }}`` reaches the SQL as exactly that
#: text inside a string literal, never as an evaluated template.
_BRACES = {"{": '{{ "{" }}', "}": '{{ "}" }}'}

_COMPARISONS = {
    Op.EQ: "=",
    Op.NE: "<>",
    Op.GT: ">",
    Op.GTE: ">=",
    Op.LT: "<",
    Op.LTE: "<=",
}


def _mismatch(
    dimension: str, declared: LogicalType, value: Scalar, want: str
) -> FilterTypeMismatch:
    msg = (
        f"filter value {value!r} does not fit dimension {dimension!r} "
        f"({type(declared).__name__}): expected {want} — values are never cast "
        "(RFC 0013 D8)"
    )
    return FilterTypeMismatch(msg)


# ....................... #


def _quoted(text: str, *, dimension: str) -> str:
    if "\x00" in text:
        msg = f"filter value for {dimension!r} contains a NUL byte — refused"
        raise InvalidRequest(msg)

    escaped = text.replace("'", "''")
    neutral = "".join(_BRACES.get(char, char) for char in escaped)
    return f"'{neutral}'"


# ....................... #


def _decimal_carrier(value: str, declared: LogicalType, *, dimension: str) -> Decimal:
    """The string carrier (RFC 0015 D5): an exact decimal bound JSON numbers
    cannot express, parsed here — never cast in SQL. Non-finite forms
    (``NaN``/``Infinity``/``-Infinity``) are ``InvalidLiteral``: ``lt
    'NaN'`` fails open on Postgres and matches every row."""

    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise _mismatch(dimension, declared, value, "a decimal number") from error

    if not parsed.is_finite():
        msg = (
            f"filter value {value!r} for dimension {dimension!r} is non-finite — "
            "NaN/Infinity comparisons fail open, refused (RFC 0015 D5)"
        )
        raise InvalidLiteral(msg)

    return parsed


# ....................... #


def _literal(value: Scalar, declared: LogicalType, *, dimension: str) -> str:
    """One typed SQL literal (rules 1, 3, 5). Exhaustive over the closed
    ``LogicalType`` set; ``variant`` columns cannot be filtered."""

    match declared:
        case StringType():
            if isinstance(value, UUID):
                return _quoted(str(value), dimension=dimension)
            if not isinstance(value, str):
                raise _mismatch(dimension, declared, value, "a string")
            return _quoted(value, dimension=dimension)
        case BoolType():
            if not isinstance(value, bool):
                raise _mismatch(dimension, declared, value, "a bool")
            return "TRUE" if value else "FALSE"
        case IntType():
            if isinstance(value, bool) or not isinstance(value, int):
                raise _mismatch(dimension, declared, value, "an int")
            return str(value)
        case DecimalType():
            if isinstance(value, str):
                return str(_decimal_carrier(value, declared, dimension=dimension))
            if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
                raise _mismatch(dimension, declared, value, "an int, Decimal, or carrier string")
            if isinstance(value, Decimal) and not value.is_finite():
                msg = (
                    f"filter value {value!r} for dimension {dimension!r} is non-finite — "
                    "NaN/Infinity comparisons fail open, refused (RFC 0015 D5)"
                )
                raise InvalidLiteral(msg)
            return str(value)
        case DateType():
            if isinstance(value, datetime):
                raise _mismatch(dimension, declared, value, "an ISO date")
            if isinstance(value, date):
                return f"'{value.isoformat()}'"
            if not isinstance(value, str):
                raise _mismatch(dimension, declared, value, "an ISO date string")
            try:
                parsed = date.fromisoformat(value)
            except ValueError as error:
                raise _mismatch(dimension, declared, value, "an ISO date string") from error
            return f"'{parsed.isoformat()}'"
        case TimestampType():
            if isinstance(value, datetime):
                return f"'{value.isoformat(sep=' ')}'"
            if not isinstance(value, str):
                raise _mismatch(dimension, declared, value, "an ISO timestamp string")
            try:
                parsed_ts = datetime.fromisoformat(value)
            except ValueError as error:
                raise _mismatch(dimension, declared, value, "an ISO timestamp string") from error
            return f"'{parsed_ts.isoformat(sep=' ')}'"
        case _:
            msg = (
                f"dimension {dimension!r} has type {type(declared).__name__}, which "
                "cannot be filtered (RFC 0013 D8)"
            )
            raise FilterTypeMismatch(msg)


# ....................... #


def _pattern_literal(value: Scalar, declared: LogicalType, *, dimension: str) -> str:
    """One ``like``/``ilike`` pattern (rule 4): the caller-owned pattern as a
    quoted literal with the fixed ``ESCAPE`` clause appended by the caller —
    nothing escaped here beyond injection safety (quote doubling, NUL,
    Jinja neutralization)."""

    if not isinstance(declared, StringType) or not isinstance(value, str):
        raise _mismatch(dimension, declared, value, "a string dimension and pattern")

    return _quoted(value, dimension=dimension)


# ....................... #


def _column_type(mart: MartIR, column: str) -> LogicalType:
    for mart_column in mart.columns:
        if mart_column.name == column:
            return mart_column.type

    raise PlannerError(  # pragma: no cover — coverage resolution guarantees it
        f"resolved dimension {column!r} is not a column of mart {mart.name!r}"
    )


# ....................... #


def _predicate(
    predicate: Predicate,
    resolved: ResolvedDimension,
    *,
    mart: MartIR,
    entity: str,
) -> str:
    """One rendered predicate: a ``{{ Dimension('<validated dunder>') }}``
    reference plus typed literals — nothing else ever enters the template
    (rule 2)."""
    reference = f"{{{{ Dimension('{group_by_name(resolved, entity=entity)}') }}}}"
    declared = _column_type(mart, resolved.name)
    dimension = resolved.name
    op = predicate.op
    values = predicate.values

    if op in COMPARISON_OPS:
        literal = _literal(values[0], declared, dimension=dimension)
        return f"{reference} {_COMPARISONS[op]} {literal}"

    if op in (Op.IN, Op.NOT_IN):
        rendered = ", ".join(_literal(v, declared, dimension=dimension) for v in values)
        keyword = "IN" if op is Op.IN else "NOT IN"
        return f"{reference} {keyword} ({rendered})"

    if op in (Op.LIKE, Op.ILIKE):
        subject = reference if op is Op.LIKE else f"LOWER({reference})"
        matches: list[str] = []
        for value in values:
            pattern = _pattern_literal(value, declared, dimension=dimension)
            pattern = pattern if op is Op.LIKE else f"LOWER({pattern})"
            matches.append(f"{subject} LIKE {pattern} ESCAPE '\\'")
        if len(matches) == 1:
            return matches[0]
        return f"({' OR '.join(matches)})"  # multi-pattern OR semantics (RFC 0015 §5.1)

    if op is Op.IS_NULL:
        keyword = "IS NULL" if values[0] else "IS NOT NULL"
        return f"{reference} {keyword}"

    msg = f"unknown filter operator {op!r}"  # pragma: no cover — request validation
    raise InvalidRequest(msg)  # pragma: no cover


# ....................... #


def _clause(
    clause: Clause,
    resolutions: tuple[ResolvedDimension, ...],
    *,
    mart: MartIR,
    entity: str,
) -> str:
    """One rendered where-constraint per clause (RFC 0015 D11): an ``AnyOf``
    group is a parenthesized ``OR``-join — **always** parenthesized, since
    the constraints are ANDed and ``policy AND a OR b`` leaks every row
    matching ``b``."""
    predicates = clause_predicates(clause)
    rendered = tuple(
        _predicate(predicate, resolved, mart=mart, entity=entity)
        for predicate, resolved in zip(predicates, resolutions, strict=True)
    )

    if isinstance(clause, AnyOf):
        return f"({' OR '.join(rendered)})"

    return rendered[0]  # a bare Predicate clause renders unwrapped


# ....................... #


def to_where(
    filters: tuple[Clause, ...],
    filter_dimensions: tuple[tuple[ResolvedDimension, ...], ...],
    *,
    mart: MartIR,
    entity: str,
    policy: RowPolicy | None = None,
    policy_dimension: ResolvedDimension | None = None,
) -> tuple[str, ...]:
    """Every where-constraint for the MetricFlow request — one entry per
    clause (RFC 0015 D11), policy **first** (RFC 0013 D9 — the policy is
    always prepended to user filters).

    ``filter_dimensions`` pairs positionally with ``filters`` — one inner
    tuple of resolutions per clause, pairing with that clause's predicates —
    both come from :func:`bloomery.planner.coverage.resolve_request`.
    """
    constraints: list[str] = []

    if policy is not None:
        if policy_dimension is None:  # pragma: no cover — the planner resolves it
            msg = "a row policy requires its resolved dimension"
            raise PlannerError(msg)
        constraints.append(
            _predicate(policy.as_clause(), policy_dimension, mart=mart, entity=entity)
        )

    constraints.extend(
        _clause(clause, resolutions, mart=mart, entity=entity)
        for clause, resolutions in zip(filters, filter_dimensions, strict=True)
    )

    return tuple(constraints)
