"""Audit predicates and literal spellings (RFC 0006 §5.6/D7).

The base of the lowering package: a value's SQL literal form and the predicate
an audit tests it with. Every other stage may read these; they read nothing.

Also home to the two predicates the *semantic* targets share — the as-of
interval (RFC 0023 D6) and a metric filter (RFC 0034 D15) — for the same
reason: each is one construct that two callers spell, and a construct spelled
twice is one that drifts.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast

from sqlglot import exp
from sqlglot.expressions.core import Expression

from bloomery.errors import guaranteed
from bloomery.ir import AuditIR, EntityIR, MartIR, MetricFilterIR
from bloomery.transforms import neutral_type
from bloomery.typing import (
    DateType,
    DecimalType,
    IntType,
    LogicalType,
    StringType,
    TimestampType,
)

# ....................... #
# Audit predicates (RFC 0006 §5.6/D7)


def column_type(entity: EntityIR, name: str) -> LogicalType:
    """The declared logical type of one entity column."""

    return guaranteed(
        (column.type for column in entity.columns if column.name == name),
        expected=f"column {name!r} on entity {entity.name!r}",
        by="the stage that lowered the column being asked about",
    )


# ....................... #


#: What a temporal literal must look like by the time it reaches a ``CAST``.
#:
#: **Trino will not cast an ISO 8601 timestamp.** Measured on Trino 483,
#: ``CAST('2024-01-01T00:00:00' AS TIMESTAMP)`` is an `INVALID_CAST_ARGUMENT`;
#: the space-separated form and a bare date both parse, and DuckDB and
#: PostgreSQL take either. The separator is not the only spelling that reaches
#: here, though — ``datetime.fromisoformat`` also accepts a lowercase ``t``, a
#: space, a trailing ``Z`` and an explicit offset, so substituting one character
#: fixes one of four inputs. The value is parsed and re-rendered instead.
#:
#: An offset is *converted*, not dropped: RFC 0028 makes ``timestamp`` zoneless
#: UTC on every port, so ``2024-01-01T09:00:00+02:00`` is the instant
#: ``2024-01-01 07:00:00`` and comparing it as though it were 09:00 would be
#: wrong by the offset. Refusing the spelling instead would lose a legitimate
#: one for no gain.
#:
#: One rule, both callers: an audit bound (RFC 0006 §5.6) and a metric filter
#: (RFC 0034 D8) build the same construct — a text literal cast to the column's
#: neutral type — and the audit path carried the un-normalized form too,
#: pre-existing and unexercised because no fixture asserts a ``min``/``max`` on
#: a timestamp column.
_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def _temporal_text(value: str, declared: LogicalType) -> str:
    """One temporal literal in the spelling every shipped dialect casts.

    Gated on the declared type rather than on whether the text happens to look
    like a date: a ``string`` column may hold ``"2024-01-01T09:00:00"`` as data,
    and rewriting it there would silently change what the comparison matches.

    A value that does not parse is returned untouched — the metric-filter
    guardrail has already refused those (RFC 0034 D9), and an audit bound has
    its own validation, so this is not the place to invent a second refusal.
    """

    if isinstance(declared, DateType):
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            return value

    if not isinstance(declared, TimestampType):
        return value

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)

    if parsed.microsecond:
        return parsed.strftime(f"{_TIMESTAMP_FORMAT}.%f")

    return parsed.strftime(_TIMESTAMP_FORMAT)


# ....................... #


def _bound_literal(value: str, bound_type: LogicalType) -> Expression:
    """A typed literal for an audit bound: numeric columns take number
    literals, everything else a string literal cast to the column type (so
    temporal comparisons never rely on engine coercion)."""

    if isinstance(bound_type, (IntType, DecimalType)):
        return exp.Literal.number(value)

    return exp.cast(exp.Literal.string(_temporal_text(value, bound_type)), neutral_type(bound_type))


# ....................... #


def enum_literal(value: str, member_type: LogicalType) -> Expression:
    """An ``accepted_values`` member literal, typed by the audited column."""

    if isinstance(member_type, IntType):
        return exp.Literal.number(value)

    return exp.Literal.string(value)


# ....................... #


def audit_predicate(entity: EntityIR, audit: AuditIR, *, violations: bool) -> Expression:
    """The predicate for one custom-bodied audit kind (``min``/``max``/
    ``regex``/``reconcile``).

    ``violations=True`` selects the failing rows (SQLMesh audit bodies pass
    when the query returns none); ``violations=False`` is the row-level
    assertion that must hold (dbt ``expression_is_true``-shaped tests). Both
    forms are built here, side by side, so the two targets cannot drift.
    """
    column = exp.column(audit.column)
    params = dict(audit.params)

    if audit.kind == "min":
        bound = _bound_literal(params["value"], column_type(entity, audit.column))
        if violations:
            return exp.LT(this=column, expression=bound)
        return exp.GTE(this=column, expression=bound)

    if audit.kind == "max":
        bound = _bound_literal(params["value"], column_type(entity, audit.column))
        if violations:
            return exp.GT(this=column, expression=bound)
        return exp.LTE(this=column, expression=bound)

    if audit.kind == "regex":
        matches = exp.RegexpLike(this=column, expression=exp.Literal.string(params["pattern"]))
        return exp.Not(this=matches) if violations else matches

    # "reconcile" — the only remaining custom kind (RFC 0006 D7): row-level
    # disagreement between the derived column and its __direct shadow.
    shadow = exp.column(params["shadow"])

    if violations:
        return exp.NullSafeNEQ(this=column, expression=shadow)

    return exp.NullSafeEQ(this=column, expression=shadow)


# ....................... #
# The as-of predicate (RFC 0023 §5.3/§5.4, D6)


def as_of_conditions(
    anchor: Expression, *, table: str, valid_from: str, valid_to: str
) -> list[Expression]:
    """``anchor >= valid_from AND (valid_to IS NULL OR anchor < valid_to)``.

    The half-open interval every validity convention uses, so a row valid to
    the instant another becomes valid matches exactly one of them rather than
    both.

    One function because there is one construct. RFC 0023 D6 kept the SCD2
    as-of join and the FX rate lookup in a single document precisely so they
    would not be designed apart, and they differ only in what they name: a
    mart's join reads a dimension's ``valid_from``/``valid_to`` under the join
    prefix, a conversion reads the rate relation's declared interval columns
    under the subquery's alias. Neither owns the shape.

    It lives in the base of the lowering package rather than beside either
    caller, because the two are sibling stages and stages compose downward.

    The open end is spelled ``IS NULL`` rather than a sentinel: both SCD2
    targets write NULL for the current version, a rate feed leaves the live
    rate open the same way — declared open, which is a statement the writer
    made and can retract — and a sentinel would have to be a literal of the
    interval's own type — which differs between a ``date`` anchor and a
    ``timestamp`` one, on three dialects. ``IS NULL`` needs no literal and no
    coercion, and says the same thing.
    """
    upper = exp.column(valid_to, table=table)
    open_ended = exp.or_(
        exp.Is(this=upper.copy(), expression=exp.null()),
        exp.LT(this=anchor.copy(), expression=upper),
    )

    # ``or_`` is annotated with the ``Condition`` base, but returns an
    # ``Expression`` here (cf. ir.nodes on ``parse_one``).
    return [
        exp.GTE(this=anchor.copy(), expression=exp.column(valid_from, table=table)),
        cast("Expression", open_ended),
    ]


# ....................... #
# The metric-filter predicate (RFC 0034 D8, D15)

#: The comparison operators, spelled once. ``in``/``not_in`` and ``is_null``
#: are shapes rather than infix operators and are built below.
_METRIC_FILTER_COMPARISONS = {
    "eq": "=",
    "ne": "<>",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
}


def _metric_filter_literal(value: str | int | bool | Decimal, declared: LogicalType) -> str:
    """One authored filter value as a SQL literal **of the column's type**.

    Typed rather than quoted-and-hoped, because two of the three shipped
    dialects do not rescue an untyped one. Measured on Trino 483:

        Cannot apply operator: decimal(12,4) <= varchar(4)
        Cannot apply operator: date <= varchar(10)

    So a filter on a decimal column written through the string carrier RFC 0015
    D5 established — ``"50.00"``, which is how an exact decimal is written in
    YAML — and a filter on any date or timestamp column were both broken on
    Trino, and worked on DuckDB and PostgreSQL only by implicit cast. Numbers
    now render unquoted and temporals render as an explicit ``CAST`` to the
    neutral type, which is the spelling :func:`_bound_literal` already uses for
    audit bounds and for the same reason.

    ``bool`` precedes ``int`` because it is a subclass of one. Strings double
    their quotes; they cannot carry a NUL or a template brace, both refused at
    parse (RFC 0034 D13) rather than escaped per target, so this needs no
    target-specific neutralization and stays shareable.
    """

    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"

    if isinstance(value, (int, Decimal)):
        return str(value)

    escaped = value.replace("'", "''")

    if isinstance(declared, (IntType, DecimalType)):
        # The string carrier for a number the guardrail has already parsed
        # (RFC 0034 D9) — it reaches SQL as the number it carries.
        return escaped

    if isinstance(declared, StringType):
        return f"'{escaped}'"

    # A temporal, or any other type whose literal is written as text: cast, so
    # the comparison never depends on the engine's coercion rules — and without
    # the ISO `T`, which Trino refuses to cast (see `_ISO_SEPARATOR`).
    return f"CAST('{_temporal_text(escaped, declared)}' AS {neutral_type(declared).sql()})"


# ....................... #


def mart_column_type(mart: MartIR, column: str) -> LogicalType:
    """The declared type of one mart column — what a metric filter's literal is
    rendered as. The guardrail has already established that the column exists
    and that the values fit it (RFC 0034 D9)."""

    return guaranteed(
        (candidate.type for candidate in mart.columns if candidate.name == column),
        expected=f"column {column!r} on mart {mart.name!r}",
        by="the metric-filter guardrail, which refuses a dimension the mart does not flatten",
    )


# ....................... #


def metric_filter_sql(clause: MetricFilterIR, *, ref: str, declared: LogicalType) -> str:
    """One metric-filter clause as SQL text, over the target's own spelling of
    the column reference (RFC 0034 D15).

    ``ref`` is what the target writes where a column goes —
    ``{{ Dimension('order_item__status') }}`` in a MetricFlow where-filter,
    ``{CUBE}.status`` in a Cube measure filter. Neither is a SQL identifier, so
    the fragment is text rather than a SQLGlot expression: an AST would have to
    carry the reference as an opaque node and be rendered straight back out.

    What *is* shared is everything that can be got wrong — the operator
    spellings, the list shape, quote doubling — because two copies of an
    escaping rule is the defect this project keeps finding in itself.

    Two invariants are relied on and neither is re-checked here, because both
    are established before an IR node exists: ``values`` has the arity its
    operator takes (``MetricFilter._arity`` refuses the rest at parse), so the
    ``is_null`` branch may index it; and each value fits the column's declared
    type (the guardrail stage, D9), so nothing is cast.
    """

    if clause.op == "is_null":
        return f"{ref} IS NULL" if clause.values[0] else f"{ref} IS NOT NULL"

    literals = [_metric_filter_literal(value, declared) for value in clause.values]

    if clause.op in ("in", "not_in"):
        keyword = "IN" if clause.op == "in" else "NOT IN"
        return f"{ref} {keyword} ({', '.join(literals)})"

    comparison = guaranteed(
        (_METRIC_FILTER_COMPARISONS[op] for op in (clause.op,) if op in _METRIC_FILTER_COMPARISONS),
        expected=f"a SQL spelling for metric-filter operator {clause.op!r}",
        by="the spec layer's FilterOpName, which is a closed vocabulary",
    )
    return f"{ref} {comparison} {literals[0]}"
