"""Audit predicates and literal spellings (RFC 0006 §5.6/D7).

The base of the lowering package: a value's SQL literal form and the predicate
an audit tests it with. Every other stage may read these; they read nothing.
"""

from __future__ import annotations

from typing import cast

from sqlglot import exp
from sqlglot.expressions.core import Expression

from bloomery.errors import guaranteed
from bloomery.ir import AuditIR, EntityIR
from bloomery.transforms import neutral_type
from bloomery.typing import DecimalType, IntType, LogicalType

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


def _bound_literal(value: str, bound_type: LogicalType) -> Expression:
    """A typed literal for an audit bound: numeric columns take number
    literals, everything else a string literal cast to the column type (so
    temporal comparisons never rely on engine coercion)."""

    if isinstance(bound_type, (IntType, DecimalType)):
        return exp.Literal.number(value)

    return exp.cast(exp.Literal.string(value), neutral_type(bound_type))


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
