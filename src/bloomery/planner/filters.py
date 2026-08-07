"""Filter rendering (RFC 0013 §5.6–§5.7, D8–D9) — the highest-risk surface
of the MetricFlow pivot: ``where_constraints`` are Jinja-templated strings,
i.e. string construction on the query path. Non-negotiable rules, all
enforced here and fuzz-tested (merge-blocking):

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
4. ``contains`` escapes ``%``/``_``/``\\`` and carries an ``ESCAPE`` clause;
5. numbers render through ``int``/``Decimal`` repr (floats never reach here
   — request validation refused them), dates and timestamps are
   ISO-validated then re-serialized.

The row policy is rendered through this exact pipeline and **prepended** to
the user filters (RFC 0013 D9).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from bloomery.errors import FilterTypeMismatch, InvalidRequest, PlannerError
from bloomery.planner.names import group_by_name
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
    from bloomery.planner.request import FilterExpr, JsonScalar
    from bloomery.typing import LogicalType

__all__ = [
    "to_where",
]

#: Jinja delimiter neutralization (rule 3): emitted through Jinja string
#: literals, each brace renders back to itself *after* templating — so a
#: value containing ``{{ Dimension('x') }}`` reaches the SQL as exactly that
#: text inside a string literal, never as an evaluated template.
_BRACES = {"{": '{{ "{" }}', "}": '{{ "}" }}'}

_COMPARISONS = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


def _mismatch(
    dimension: str, declared: LogicalType, value: JsonScalar, want: str
) -> FilterTypeMismatch:
    msg = (
        f"filter value {value!r} does not fit dimension {dimension!r} "
        f"({type(declared).__name__}): expected {want} — values are never cast "
        "(RFC 0013 D8)"
    )
    return FilterTypeMismatch(msg)


def _quoted(text: str, *, dimension: str) -> str:
    if "\x00" in text:
        msg = f"filter value for {dimension!r} contains a NUL byte — refused"
        raise InvalidRequest(msg)
    escaped = text.replace("'", "''")
    neutral = "".join(_BRACES.get(char, char) for char in escaped)
    return f"'{neutral}'"


def _literal(value: JsonScalar, declared: LogicalType, *, dimension: str) -> str:
    """One typed SQL literal (rules 1, 3, 5). Exhaustive over the closed
    ``LogicalType`` set; ``variant`` columns cannot be filtered."""
    match declared:
        case StringType():
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
            if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
                raise _mismatch(dimension, declared, value, "an int or Decimal")
            if isinstance(value, Decimal) and not value.is_finite():
                raise _mismatch(dimension, declared, value, "a finite number")
            return str(value)
        case DateType():
            if not isinstance(value, str):
                raise _mismatch(dimension, declared, value, "an ISO date string")
            try:
                parsed = date.fromisoformat(value)
            except ValueError as error:
                raise _mismatch(dimension, declared, value, "an ISO date string") from error
            return f"'{parsed.isoformat()}'"
        case TimestampType():
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


def _like_pattern(value: JsonScalar, declared: LogicalType, *, dimension: str) -> str:
    """The ``contains`` pattern (rule 4): wildcards escaped with ``\\`` before
    quoting, wrapped in ``%``, always paired with ``ESCAPE '\\'``."""
    if not isinstance(declared, StringType) or not isinstance(value, str):
        raise _mismatch(dimension, declared, value, "a string dimension and value")
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    quoted = _quoted(f"%{escaped}%", dimension=dimension)
    return f"{quoted} ESCAPE '\\'"


def _column_type(mart: MartIR, column: str) -> LogicalType:
    for mart_column in mart.columns:
        if mart_column.name == column:
            return mart_column.type
    raise PlannerError(  # pragma: no cover — coverage resolution guarantees it
        f"resolved dimension {column!r} is not a column of mart {mart.name!r}"
    )


def _constraint(
    filter_expr: FilterExpr,
    resolved: ResolvedDimension,
    *,
    mart: MartIR,
    entity: str,
) -> str:
    """One rendered where-constraint: a ``{{ Dimension('<validated dunder>')
    }}`` reference plus typed literals — nothing else ever enters the
    template (rule 2)."""
    reference = f"{{{{ Dimension('{group_by_name(resolved, entity=entity)}') }}}}"
    declared = _column_type(mart, resolved.name)
    dimension = resolved.name
    op = filter_expr.op
    values = filter_expr.values
    if op in _COMPARISONS:
        literal = _literal(values[0], declared, dimension=dimension)
        return f"{reference} {_COMPARISONS[op]} {literal}"
    if op == "between":
        low = _literal(values[0], declared, dimension=dimension)
        high = _literal(values[1], declared, dimension=dimension)
        return f"{reference} BETWEEN {low} AND {high}"
    if op in ("in", "not_in"):
        rendered = ", ".join(_literal(v, declared, dimension=dimension) for v in values)
        keyword = "IN" if op == "in" else "NOT IN"
        return f"{reference} {keyword} ({rendered})"
    if op == "contains":
        return f"{reference} LIKE {_like_pattern(values[0], declared, dimension=dimension)}"
    if op == "is_null":
        return f"{reference} IS NULL"
    msg = f"unknown filter operator {op!r}"  # pragma: no cover — request validation
    raise InvalidRequest(msg)  # pragma: no cover


def to_where(
    filters: tuple[FilterExpr, ...],
    filter_dimensions: tuple[ResolvedDimension, ...],
    *,
    mart: MartIR,
    entity: str,
    policy: RowPolicy | None = None,
    policy_dimension: ResolvedDimension | None = None,
) -> tuple[str, ...]:
    """Every where-constraint for the MetricFlow request, policy **first**
    (RFC 0013 D9 — the policy is always prepended to user filters).

    ``filter_dimensions`` pairs positionally with ``filters`` — both come
    from :func:`bloomery.planner.coverage.resolve_request`.
    """
    constraints: list[str] = []
    if policy is not None:
        if policy_dimension is None:  # pragma: no cover — the planner resolves it
            msg = "a row policy requires its resolved dimension"
            raise PlannerError(msg)
        constraints.append(
            _constraint(policy.as_filter(), policy_dimension, mart=mart, entity=entity)
        )
    constraints.extend(
        _constraint(filter_expr, resolved, mart=mart, entity=entity)
        for filter_expr, resolved in zip(filters, filter_dimensions, strict=True)
    )
    return tuple(constraints)
