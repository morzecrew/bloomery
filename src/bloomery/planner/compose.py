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
from bloomery.errors import PlannerError, guaranteed

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bloomery.dialects import DialectPort

# ----------------------- #

__all__ = [
    "Branch",
    "Measure",
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


@dataclass(frozen=True, slots=True)
class Measure:
    """One measure column of the composed statement, and where it comes from.

    ``expr`` is ``None`` for a stored measure: one branch aggregated it and the
    composition reads that branch's column. Where it is set, the column is
    **computed above the join** (RFC 0041 D3) from components the branches
    aggregated separately — which is the ordering D1 locks, since `SUM(a)/SUM(b)`
    and a row-level `a/b` aggregated afterwards are different numbers.

    ``inputs`` says what each name the expression references resolves to: the
    alias it was authored under, the index of the branch that produced it, and
    the column that branch calls it. Alias and column need not agree — a
    ratio's operand is `revenue` under both, while an RFC 0034 ``derived:``
    input is authored against an alias of its own and read from the column its
    metric is named after.
    """

    name: str
    inputs: tuple[tuple[str, int, str], ...]
    expr: Expression | None = None


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


def _bound(measure: Measure) -> Expression:
    """One computed measure's expression, with every name it references
    rebound to the branch column holding it.

    An authored expression names its inputs by alias and knows nothing about
    branches; the composition knows which branch produced each one and what
    that branch called it. Rebinding here is what keeps the two apart — the
    expression is never rewritten as text, and never re-parsed after this.

    Every column reference is checked **before** anything is rebound, and is
    refused unless it is a bare name this measure declares. Checking what
    survives the rebinding instead misses the reference that was never a
    candidate for it: a *qualified* name is not rebound and is not bare
    afterwards either, so `d - t.orders` passed and reached the SQL naming a
    relation nothing in the statement declares — or, where the qualifier
    happened to spell a branch alias, silently read another branch's column.
    The metrics guardrail does not catch it first: it compares
    ``Column.name``, and the name half of `t.orders` is a declared alias
    (logs/T-0027.md, finding 5).
    """

    lookup = {alias: (index, column) for alias, index, column in measure.inputs}
    expression = guaranteed(
        (candidate for candidate in (measure.expr,) if candidate is not None),
        expected=f"an expression for computed measure {measure.name!r}",
        by="Measure.expr, which `_projection` checks before calling this",
    )
    unbound = sorted(
        {
            column.sql()
            for column in expression.find_all(exp.Column)
            if column.table or column.name not in lookup
        }
    )

    if unbound:
        msg = (
            f"computed measure {measure.name!r} references {unbound}, which no branch "
            "produces — a composed expression reads its declared inputs by their bare "
            "names and nothing else (RFC 0041 D3)"
        )
        raise PlannerError(msg)

    def rebind(node: Expression) -> Expression:
        if isinstance(node, exp.Column) and node.name in lookup:
            index, column = lookup[node.name]
            return exp.column(column, table=_ALIAS.format(index=index))

        return node

    return expression.transform(rebind)


# ....................... #


def _ordering(field: str, direction: str, dialect: DialectPort) -> str:
    """One ``ORDER BY`` term over a projected alias.

    ``NULLS LAST`` in **both** directions, and written out rather than left to
    the engine. The key domain mints a NULL group on purpose — a group one
    branch has and another does not survives the join with a NULL key (D13,
    D18) — and SQL does not fix where a NULL sorts (logs/T-0027.md, D-177).

    Assembled around a rendered identifier rather than built as
    :class:`sqlglot.exp.Ordered`, which is the obvious spelling and elides the
    clause wherever it believes the dialect already defaults that way: two of
    the three shipped dialects come back as a bare ``x DESC``. The belief is
    right about each engine's *default*, and a default is a setting — DuckDB
    publishes `default_null_order` — so the elided form makes the answer
    depend on how the warehouse is configured. Nothing here is a request
    value: the field is a projected alias the request validated (RFC 0011 D4),
    and the direction is one of two words.

    Sorting by the alias rather than by an ordinal: all three shipped dialects
    resolve a bare name in ``ORDER BY`` to the output column before any input
    column of the same name.
    """

    return (
        f"{dialect.render(exp.column(field))} {'DESC' if direction == 'desc' else 'ASC'} NULLS LAST"
    )


# ....................... #


def _projection(
    branches: Sequence[Branch], keys: Sequence[str], measures: Sequence[Measure]
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

    projected: list[Expression] = [_aliased(exp.column(name, table=_KEYS), name) for name in keys]
    # Aliased explicitly, though a bare column reference would already come
    # back under its own name on all three dialects: the alias is what makes
    # `ColumnDescriptor.sql_alias` a promise about this statement rather than
    # an assumption about how an engine names a projected column.
    projected.extend(
        _aliased(
            _bound(measure)
            if measure.expr is not None
            else exp.column(measure.inputs[0][2], table=_ALIAS.format(index=measure.inputs[0][1])),
            measure.name,
        )
        for measure in measures
    )

    return projected


# ....................... #


def compose(
    branches: Sequence[Branch],
    *,
    keys: Sequence[str],
    measures: Sequence[Measure],
    order_by: Sequence[tuple[str, str]] = (),
    limit: int | None = None,
    dialect: DialectPort,
) -> str:
    """The composed statement, as SQL text.

    ``keys`` are the composed key columns in request order — the names the
    result carries. ``measures`` are in request order too, since a caller's
    column order is part of the answer and the branches were sorted by mart
    name rather than by what was asked for.

    ``order_by`` and ``limit`` belong **here** rather than in a branch. Either
    one pushed into a branch acts before the join: a sort inside a branch is
    undone by the join, and a limit inside one answers from a prefix of that
    branch and reports nothing about having done so (logs/T-0027.md, D-182).
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

    tail = ""

    if order_by:
        tail += "\nORDER BY " + ", ".join(
            _ordering(field, direction, dialect) for field, direction in order_by
        )

    if limit is not None:
        # An `int` the planner already clamped (RFC 0011 D4), interpolated
        # rather than parameterized because it is the planner's own number —
        # a caller's `limit` reaches here only through that clamp.
        tail += f"\nLIMIT {limit}"

    if not keys:
        # No grouping at all: each branch is a single row of totals, and the
        # answer is their cross product. There is no key domain to build, and
        # inventing one would be a group nobody asked for.
        crossed = " CROSS JOIN ".join(_ALIAS.format(index=index) for index in range(len(branches)))

        return f"WITH {', '.join(defined)}\nSELECT\n  {selected}\nFROM {crossed}{tail}"

    defined.append(f"{_KEYS} AS (\n{_key_domain(branches, keys, dialect)}\n)")
    joined = "\n".join(
        f"LEFT JOIN {_ALIAS.format(index=index)}\n"
        f"  ON {dialect.render(_matches(branch, index, keys))}"
        for index, branch in enumerate(branches)
    )

    return f"WITH {', '.join(defined)}\nSELECT\n  {selected}\nFROM {_KEYS}\n{joined}{tail}"
