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
match with ``IS NOT DISTINCT FROM``, so a NULL group on one side meets the
NULL group on the other instead of failing ``NULL = NULL`` and splitting into
two rows that a re-aggregation pass then has to merge.

**The shape is a key domain and left joins, not a full outer join**, and that
is a result rather than a preference. PostgreSQL refuses
``FULL JOIN … ON a IS NOT DISTINCT FROM b`` outright — *"FULL JOIN is only
supported with merge-joinable or hash-joinable join conditions"* — so the
obvious composition is a statement one of the three shipped dialects cannot
run at all. It renders on every one of them, which is why RFC 0041 D17 asks
for the engine tier rather than for the documentation (logs/T-0026.md, D-171).

So the branches become CTEs, their keys are unioned into the domain of groups
the answer has — ``UNION`` deduplicates NULL against NULL, which is the same
null semantics stated the other way round — and each branch is left-joined
back onto that domain. Every group present in any branch appears exactly once,
which is what the full outer join was for.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlglot import exp
from sqlglot.expressions.core import Expression

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

#: The name each branch's CTE is given, by position. A generated name rather
#: than the mart's: a mart name is authored and could collide with a column the
#: branch projects, and the name is never shown to anybody — `QueryPlan.marts`
#: is where a caller reads which marts answered.
_ALIAS = "branch_{index}"

#: The CTE holding every group the answer has, one row per group. Named in the
#: same generated namespace for the same reason.
_KEYS = "branch_keys"


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


def _aliased(expression: Expression, name: str) -> exp.Alias:
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


def _key_domain(branches: Sequence[Branch], keys: Sequence[str], dialect: DialectPort) -> str:
    """Every group the answer has, once — the union of the branches' keys.

    ``UNION`` and not ``UNION ALL``: the deduplication is the point, and it is
    where D13's null semantics live on this shape. SQL's set operators compare
    NULL to NULL as *not distinct*, so the NULL group of one branch and the
    NULL group of another collapse to one row exactly as a matching pair of
    ordinary keys does — the same rule as the ``IS NOT DISTINCT FROM`` below,
    stated by a different construct because that construct is the one every
    engine accepts here.
    """

    # S608 reads a SELECT built by concatenation as an injection vector. Every
    # part of this one is generated: the key expressions are sqlglot ASTs
    # rendered by the dialect port, and `branch_0` is this module's own name
    # for a CTE. No request value reaches it — those are inside the branch SQL
    # MetricFlow rendered, which this module never builds and never parses.
    return "\n  UNION\n".join(
        "  SELECT "  # noqa: S608
        + ", ".join(
            dialect.render(_aliased(_key_reference(branch, index, position), name))
            for position, name in enumerate(keys)
        )
        + f" FROM {_ALIAS.format(index=index)}"
        for index, branch in enumerate(branches)
    )


# ....................... #


def _matches(branch: Branch, index: int, keys: Sequence[str]) -> Expression:
    """How one branch is matched back onto the key domain.

    ``IS NOT DISTINCT FROM`` rather than ``=``, so the branch's NULL group
    finds the domain's NULL group instead of vanishing from the answer. Legal
    as a ``LEFT JOIN`` condition on all three shipped dialects; as a
    ``FULL JOIN`` condition it is not, which is what decided this shape.
    """

    matched: list[Expression] = [
        exp.NullSafeEQ(
            this=_key_reference(branch, index, position),
            expression=exp.column(name, table=_KEYS),
        )
        for position, name in enumerate(keys)
    ]
    # Folded rather than `functools.reduce`d: the accumulator is an
    # `Expression` and each step returns an `And`, which reduce's own signature
    # cannot express — it binds one type variable to both.
    conjunction = matched[0]

    for extra in matched[1:]:
        conjunction = exp.And(this=conjunction, expression=extra)

    return conjunction


# ....................... #


def _projection(
    branches: Sequence[Branch], keys: Sequence[str], measures: Sequence[tuple[int, str]]
) -> list[Expression]:
    """The composed SELECT list: the key domain's columns first, then measures
    in request order.

    A key is projected under **bloomery's** name rather than under any
    branch's spelling of it (logs/T-0026.md, D-165). The dunder names are
    MetricFlow's vocabulary and survive inside the branch CTEs where they are
    still MetricFlow's SQL; the composed statement is bloomery's, and
    ``ColumnDescriptor.sql_alias`` reports what it actually projects.

    Read from the key domain rather than from a branch: after a left join a
    branch's copy of the key is NULL for every group that branch does not
    have, and the domain's copy never is.
    """

    projected: list[Expression] = [
        _aliased(exp.column(name, table=_KEYS), name) for name in keys
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

    # Asked of the keyed join only. An ungrouped request composes to a
    # `CROSS JOIN` of one-row totals and has no key to match, so refusing it on
    # a dialect without null-safe equality would refuse a statement that never
    # needed the capability.
    if keys and not dialect.supports(DialectFeature.NULL_SAFE_EQUALITY):
        msg = (
            f"dialect {dialect.name!r} declares no null-safe equality, and a branch join "
            "needs one: matching on `=` drops every group whose key is NULL from the "
            "answer instead of reporting it (RFC 0041 D13, D17)"
        )
        raise PlannerError(msg)

    defined = [
        f"{_ALIAS.format(index=index)} AS (\n{branch.sql}\n)"
        for index, branch in enumerate(branches)
    ]
    selected = ",\n  ".join(dialect.render(item) for item in _projection(branches, keys, measures))

    if not keys:
        # No grouping at all: each branch is a single row of totals, and the
        # answer is their cross product. There is no key domain to build, and
        # inventing one would be a group nobody asked for.
        crossed = " CROSS JOIN ".join(_ALIAS.format(index=index) for index in range(len(branches)))

        return f"WITH {', '.join(defined)}\nSELECT\n  {selected}\nFROM {crossed}"

    defined.append(f"{_KEYS} AS (\n{_key_domain(branches, keys, dialect)}\n)")
    joined = "\n".join(
        f"LEFT JOIN {_ALIAS.format(index=index)}\n"
        f"  ON {dialect.render(_matches(branch, index, keys))}"
        for index, branch in enumerate(branches)
    )

    return f"WITH {', '.join(defined)}\nSELECT\n  {selected}\nFROM {_KEYS}\n{joined}"
