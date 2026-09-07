"""The composed branch join (RFC 0041 D9): bloomery's own SQL over branches
MetricFlow rendered.

Each branch arrives already aggregated to the requested grain — it is exactly
the single-mart request this planner answered before RFC 0041, rendered
unchanged — so what is left is to line the branches up on the key they share
and project one row per key. That join is bloomery's, not the engine's, and
this module is the whole of it.

**Why bloomery composes rather than asking MetricFlow to.** The engine will
combine multi-metric requests itself, and renders correct SQL when it does.
It reaches that shape by joining marts at row level to unify two spellings of
one dimension — `order__region` against `order_item__order_region` — and it is
the engine, not bloomery, that decides such a join is safe. RFC 0040 D6 puts
that decision here; D9 is where the document says so.

**Branch SQL is opaque.** It is inlined verbatim as a derived table and never
parsed: a round trip through a second SQL library to re-render what the first
one already rendered can only change the query, and every way it could change
it is a wrong number. What this module builds are the expressions *around* the
branches — the coalesced keys, the null-safe equality, the projection — and
those are sqlglot ASTs rendered through the dialect port, never text.

**Null semantics are bloomery's, once, for every dialect (D13).** The keys
join with ``IS NOT DISTINCT FROM``, so a NULL group on one side meets the NULL
group on the other instead of failing ``NULL = NULL`` and splitting into two
rows that a re-aggregation pass then has to merge. All three shipped dialects
render that spelling identically.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlglot import exp

from bloomery.dialects import DialectFeature
from bloomery.errors import PlannerError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bloomery.dialects import DialectPort

# ----------------------- #

__all__ = [
    "Branch",
    "compose",
]

#: The alias each branch subquery is given, by position. A generated name
#: rather than the mart's: a mart name is authored and could collide with a
#: column the branch projects, and the alias is never shown to anybody —
#: `QueryPlan.marts` is where a caller reads which marts answered.
_ALIAS = "branch_{index}"


@dataclass(frozen=True, slots=True)
class Branch:
    """One rendered branch, and the columns the composition reads from it.

    ``keys`` pairs positionally with :func:`compose`'s ``keys``: entry *i* is
    what *this* branch calls the *i*-th composed key. The two differ whenever
    the branches reach one dimension through different flattenings, which is
    the case the join exists for (RFC 0041 D12).
    """

    sql: str
    keys: tuple[str, ...]


def _aliased(expression: exp.Expression, name: str) -> exp.Alias:
    """``expression AS name``, built rather than parsed.

    :func:`sqlglot.expressions.alias_` would do it and is typed to return the
    library's loose base class, which the dialect port does not accept — and
    widening the port to take it would widen what every dialect promises to
    render, for one call site's convenience.
    """

    return exp.Alias(this=expression, alias=exp.to_identifier(name))


# ....................... #


def _key_reference(branch: Branch, index: int, position: int) -> exp.Column:
    return exp.column(branch.keys[position], table=_ALIAS.format(index=index))


# ....................... #


def _coalesced(references: Sequence[exp.Column]) -> exp.Expression:
    """``COALESCE`` over the references, or the reference itself when there is
    one — a one-argument ``COALESCE`` is legal everywhere and reads as though
    a second branch went missing."""

    first, *rest = references

    return exp.Coalesce(this=first, expressions=list(rest)) if rest else first


# ....................... #


def _join_condition(branches: Sequence[Branch], index: int) -> exp.Expression:
    """How branch ``index`` meets everything joined before it.

    Against the ``COALESCE`` of the earlier branches rather than against the
    first of them: after a full outer join, a key present only on the second
    branch sits in the second branch's column and is NULL in the first, so
    comparing the third branch to the first alone would drop every group the
    first did not have.
    """

    if not branches[index].keys:
        # No grouping at all: each branch is a single row of totals, and the
        # join is the cross product of one row with one row. `ON TRUE` says
        # that; omitting the condition would make it a syntax error, and
        # inventing a key would make it a lie.
        return exp.true()

    matched: list[exp.Expression] = [
        exp.NullSafeEQ(
            this=_key_reference(branches[index], index, position),
            expression=_coalesced(
                [
                    _key_reference(branch, earlier, position)
                    for earlier, branch in enumerate(branches[:index])
                ]
            ),
        )
        for position in range(len(branches[index].keys))
    ]

    return functools.reduce(lambda left, right: exp.And(this=left, expression=right), matched)


# ....................... #


def _projection(
    branches: Sequence[Branch], keys: Sequence[str], measures: Sequence[tuple[int, str]]
) -> list[exp.Expression]:
    """The composed SELECT list: coalesced keys first, then measures in
    request order.

    A key is projected under **bloomery's** name rather than under either
    branch's spelling of it (logs/T-0026.md, D-165). The dunder names are
    MetricFlow's vocabulary and survive inside the branch subqueries where
    they are still MetricFlow's SQL; the composed statement is bloomery's, and
    ``ColumnDescriptor.sql_alias`` reports what it actually projects.
    """

    projected: list[exp.Expression] = [
        _aliased(
            _coalesced(
                [_key_reference(branch, index, position) for index, branch in enumerate(branches)]
            ),
            name,
        )
        for position, name in enumerate(keys)
    ]
    # Aliased explicitly, though a bare column reference would already come
    # back under its own name on all three dialects: the alias is what makes
    # `ColumnDescriptor.sql_alias` a promise about this statement rather than
    # an assumption about how an engine names a projected column.
    projected.extend(
        _aliased(exp.column(name, table=_ALIAS.format(index=index)), name)
        for index, name in measures
    )

    return projected


# ....................... #


def compose(
    branches: Sequence[Branch],
    *,
    keys: Sequence[str],
    measures: Sequence[tuple[int, str]],
    dialect: DialectPort,
) -> str:
    """The composed statement, as SQL text.

    ``keys`` are the composed key columns in request order — the names the
    result carries. ``measures`` are ``(branch index, measure name)`` pairs,
    also in request order, since a caller's column order is part of the answer
    and the branches were sorted by mart name rather than by what was asked
    for.
    """

    if len(branches) < 2:
        msg = (
            f"a composed statement joins at least two branches, got {len(branches)} — "
            "a single branch is planned without one (RFC 0041 §3)"
        )
        raise PlannerError(msg)

    if not dialect.supports(DialectFeature.NULL_SAFE_EQUALITY):
        msg = (
            f"dialect {dialect.name!r} declares no null-safe equality, and a branch join "
            "needs one: joining on `=` drops every group whose key is NULL from the "
            "answer instead of reporting it (RFC 0041 D13, D17)"
        )
        raise PlannerError(msg)

    selected = ",\n  ".join(dialect.render(item) for item in _projection(branches, keys, measures))
    lines = [f"SELECT\n  {selected}", f"FROM (\n{branches[0].sql}\n) AS {_ALIAS.format(index=0)}"]
    lines.extend(
        f"FULL OUTER JOIN (\n{branch.sql}\n) AS {_ALIAS.format(index=index)}\n"
        f"  ON {dialect.render(_join_condition(branches, index))}"
        for index, branch in enumerate(branches[1:], start=1)
    )

    return "\n".join(lines)
