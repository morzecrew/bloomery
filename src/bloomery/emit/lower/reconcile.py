"""Reconcile models and their audits (RFC 0016 §5.3/§5.4).

"The check that catches a *correct formula over wrong data*." Both sides come
from the closed grammar in :mod:`bloomery.quality.reconcile` and are built as
SQLGlot ASTs; no string SQL is ever concatenated here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sqlglot import exp
from sqlglot.expressions.core import Expression

from bloomery.errors import EmitError, guaranteed
from bloomery.ir import (
    CoverageIR,
    EntityIR,
    Layer,
    MartAssertIR,
    MartIR,
    OnFail,
    ProjectIR,
    ReconcileIR,
    RelationshipIR,
)
from bloomery.quality import (
    RECONCILE_SUFFIX,
    ReconcileSide,
    conjunction,
    disjunction,
    grouped,
    parse_side,
)
from bloomery.typing import IntType, LogicalType

from .predicates import _bound_literal  # pyright: ignore[reportPrivateUsage]
from .silver import _this_model  # pyright: ignore[reportPrivateUsage]

if TYPE_CHECKING:
    from ..base import EmitContext

# ....................... #
# Reconcile (RFC 0016 §5.3/§5.4): one model plus a non-blocking audit per
# check — "the check that catches a *correct formula over wrong data*". The
# two sides come from the closed grammar in :mod:`bloomery.quality.reconcile`
# and are built as a SQLGlot AST like everything else here; no string SQL ever
# reaches an artifact.

_LEFT_ALIAS = "_left"
_RIGHT_ALIAS = "_right"
#: The compared keys themselves, as a relation. See :func:`reconcile_select`.
_KEYS_ALIAS = "_keys"
_LEFT_VALUE = "left_value"
_RIGHT_VALUE = "right_value"

_AGGREGATES: dict[str, type[exp.AggFunc]] = {
    "avg": exp.Avg,
    "count": exp.Count,
    "max": exp.Max,
    "min": exp.Min,
    "sum": exp.Sum,
}


def coverage_audit_name(check: CoverageIR) -> str:
    """``<check>_coverage`` — the audit's name and artifact path, suffixed the
    way a reconcile check's relation is (RFC 0016 D90)."""
    return f"{check.name}_coverage"


def coverage_owner(check: CoverageIR, ir: ProjectIR) -> RelationshipIR:
    """The relationship a coverage check reads. Total by construction: the
    guardrail stage refuses an unresolvable name before emission runs."""
    return guaranteed(
        (rel for rel in ir.relationships if rel.name == check.relationship),
        expected=f"relationship {check.relationship!r} named by coverage check {check.name!r}",
        by="_check_coverage (RFC 0016 D90)",
    )


def coverage_audit_select(check: CoverageIR, ir: ProjectIR, ctx: EmitContext) -> exp.Select:
    """The audit body: rows of the **referenced** entity with too few
    dependents (RFC 0016 D90).

    ``LEFT JOIN`` from the referenced side and ``COUNT`` of a *from-side*
    column, never ``COUNT(*)``: an unmatched left row still produces one output
    row, so ``COUNT(*)`` would answer 1 for a referenced row with no dependents
    at all and the check would pass on exactly the rows it exists to find.

    Only the *referenced* side is named: the dependent side is ``@this_model``,
    because the audit is attached to that entity's model and the macro is the
    one reference SQLMesh rewrites inside an AUDIT body (D29). The referenced
    side is a sibling and has to be declared in ``depends_on`` — the trap D40
    closed for step audits. See D90 on why the audit hangs off the dependent
    side and not the other.
    """
    relationship = coverage_owner(check, ir)
    to_namespace, to_relation = ctx.naming.relation(relationship.to_entity, Layer.SILVER)
    referenced = exp.table_(to_relation, db=to_namespace, alias=_COVERAGE_TO)
    # The dependent side is ``@this_model``: the audit is attached to that
    # entity's model, and the macro is the one reference SQLMesh *does* rewrite
    # inside an AUDIT body (D29). Naming the relation instead would resolve to
    # the virtual-layer view and put the model in its own ``depends_on``.
    dependent = _this_model(_COVERAGE_FROM)
    on = conjunction(
        [
            exp.EQ(
                this=exp.column(from_column, table=_COVERAGE_FROM),
                expression=exp.column(to_column, table=_COVERAGE_TO),
            )
            for from_column, to_column in relationship.via
        ]
    )
    keys = [exp.column(name, table=_COVERAGE_TO) for name in _referenced_key(relationship, ir)]
    matched = exp.Count(this=exp.column(relationship.via[0][0], table=_COVERAGE_FROM))
    return (
        exp.Select()
        .select(*[key.copy() for key in keys], exp.alias_(matched.copy(), "matched"))
        .from_(referenced)
        .join(dependent, on=on, join_type="LEFT")
        .group_by(*[key.copy() for key in keys])
        .having(exp.LT(this=matched.copy(), expression=exp.Literal.number(check.minimum)))
    )


def _referenced_key(relationship: RelationshipIR, ir: ProjectIR) -> tuple[str, ...]:
    """The referenced entity's declared key — what identifies a row the audit
    reports, so a failure names the customer rather than a row number."""
    entity = guaranteed(
        (e for e in ir.entities if e.name == relationship.to_entity),
        expected=f"entity {relationship.to_entity!r} on the referenced side of "
        f"relationship {relationship.name!r}",
        by="_check_coverage (RFC 0016 D91)",
    )
    return entity.key


#: Aliases for the two sides of a coverage audit. Fixed rather than derived
#: from entity names, which could collide with each other on a self-referencing
#: relationship.
_COVERAGE_TO = "_referenced"
_COVERAGE_FROM = "_dependent"


def mart_assert_name(mart: MartIR, clause: MartAssertIR) -> str:
    """``<mart>_<assertion>`` — the audit's name, and its artifact path.

    Prefixed by the mart because audit names share one namespace across the
    project (the same reason a rule name is prefixed by its column), and two
    marts asserting ``revenue_present`` are two different checks.
    """
    return f"{mart.name}_{clause.name}"


def mart_assert_select(mart: MartIR, clause: MartAssertIR) -> exp.Select:
    """The audit body for one mart assertion (RFC 0016 D89).

    ``SELECT <by…>, <agg>(<measure>) AS value FROM @this_model [GROUP BY <by…>]
    HAVING <agg>(<measure>) < min OR <agg>(<measure>) > max`` — an audit passes
    when it returns no rows, so this projects the offending **groups**, with
    the value beside them: a failure a human has to open the warehouse to
    understand is a failure report that gets ignored.

    A bare ``HAVING`` with no ``GROUP BY`` is the whole-mart form and is legal
    on all three shipped dialects (the implicit single group), so the empty
    ``by`` needs no second shape.

    **Three-valued logic applies here as everywhere else** (D19): the bound
    comparisons are the same ``<``/``>`` a ``range`` rule uses, so an aggregate
    that comes back NULL — which is what every aggregate but ``count`` does
    over an empty group — leaves the predicate ``UNKNOWN`` and the assertion
    silent. That is the honest answer for a group with no rows, and it is
    *also* why an assertion cannot see a group that is missing altogether:
    there is no row to aggregate and therefore no group at all.
    """
    alias = "_mart"
    aggregate = _AGGREGATES[clause.agg](this=exp.column(clause.column, table=alias))
    bound_type = _assert_bound_type(mart, clause)
    params = dict(clause.params)
    parts: list[Expression] = []
    if "min" in params:
        parts.append(
            exp.LT(this=aggregate.copy(), expression=_bound_literal(params["min"], bound_type))
        )
    if "max" in params:
        parts.append(
            exp.GT(this=aggregate.copy(), expression=_bound_literal(params["max"], bound_type))
        )
    grouped_by = [exp.column(name, table=alias) for name in clause.by]
    select = (
        exp.Select()
        .select(*[column.copy() for column in grouped_by], exp.alias_(aggregate.copy(), "value"))
        .from_(_this_model(alias))
    )
    if grouped_by:
        select = select.group_by(*[column.copy() for column in grouped_by])
    return select.having(disjunction(parts))


def _assert_bound_type(mart: MartIR, clause: MartAssertIR) -> LogicalType:
    """The type an assertion's bounds are literals of.

    ``count`` answers in rows however the column is typed; every other
    aggregate answers in the column's own type, so a ``min``/``max`` over a
    date compares against a date literal rather than against a string the
    engine has to coerce — the same reason :func:`_bound_literal` is typed at
    all.
    """
    if clause.agg == "count":
        return IntType()
    return guaranteed(
        (column.type for column in mart.columns if column.name == clause.column),
        expected=f"column {clause.column!r} on mart {mart.name!r}",
        by="_check_asserts (RFC 0016 D89)",
    )


def reconcile_relation(check: ReconcileIR) -> str:
    """``<check>__reconcile`` — one relation per check, mirroring the reject
    table's naming (RFC 0016 §5.3)."""
    return f"{check.name}{RECONCILE_SUFFIX}"


def _resolved_side(text: str, ir: ProjectIR) -> tuple[ReconcileSide, EntityIR, tuple[str, ...]]:
    """One side parsed and bound to its entity, with the keys it compares by.

    Both grammar shapes produce the same thing — one value per key — which is
    what makes the comparison a plain join. The aggregate shape is keyed by
    its ``by`` columns; the plain-column shape by the entity's declared key.
    """
    side = parse_side(text)
    entity = next(
        (e for e in ir.entities if side is not None and e.name == side.entity),
        None,
    )
    if side is None or entity is None:  # pragma: no cover — the guardrail stage refuses both
        msg = (
            f"reconcile side {text!r} did not parse or names an unbuilt entity — the "
            "guardrail stage should have refused this (RFC 0016 §5.3)"
        )
        raise EmitError(msg)
    return side, entity, side.by if side.aggregated else tuple(entity.key)


def reconcile_keys(check: ReconcileIR, ir: ProjectIR) -> tuple[str, ...]:
    """The grain of a check's model: the columns its left side compares by
    (the guardrail stage has already refused sides keyed differently)."""
    _side, _entity, keys = _resolved_side(check.left, ir)
    return keys


def _reconcile_side(
    text: str, ir: ProjectIR, ctx: EmitContext, *, value: str
) -> tuple[exp.Select, tuple[str, ...]]:
    """One side lowered to a keyed value relation: ``(select, key columns)``."""
    side, _entity, keys = _resolved_side(text, ir)
    namespace, relation = ctx.naming.relation(side.entity, Layer.SILVER)
    select = exp.Select().from_(exp.table_(relation, db=namespace))
    if side.agg is None:
        return (
            select.select(
                *(exp.column(key) for key in keys),
                exp.alias_(exp.column(side.column), value),
            ),
            keys,
        )
    aggregated = _AGGREGATES[side.agg](this=exp.column(side.column))
    return (
        select.select(*(exp.column(key) for key in keys), exp.alias_(aggregated, value)).group_by(
            *(exp.column(key) for key in keys)
        ),
        keys,
    )


def reconcile_select(check: ReconcileIR, ir: ProjectIR, ctx: EmitContext) -> exp.Select:
    """The ``<check>__reconcile`` model: both sides, their difference, and the
    tolerance verdict, one row per compared key.

    The shape is **the set of compared keys, outer-joined to each side**: a
    ``_keys`` CTE unions the two sides' key columns, and the sides hang off it
    by ``LEFT JOIN``. That is a full outer join written the long way, and it
    keeps what a ``FULL JOIN`` was there for — a key present on one side only
    is the loudest disagreement there is, and an inner join would hide exactly
    that by returning fewer rows instead of a failing one. Such a row's
    ``difference`` is NULL and its ``within_tolerance`` is FALSE: the
    ``COALESCE`` collapses the three-valued comparison at this one seam, the
    same way the routing predicate does (§5.4), because a verdict column has
    to be a verdict.

    Both the union and the joins are **null-safe**, and that is not a nicety.
    ``GROUP BY`` and ``=`` disagree about NULL: the aggregate side groups every
    NULL key into one group, and an ordinary ``=`` then refuses to match the
    group it just built. The two halves of one query would be reading the same
    column by two different rules. Executed, a NULL-keyed group that *agrees*
    came back as two rows — one per side, both keyed NULL, both
    ``within_tolerance = FALSE``, both with a NULL ``difference`` — so a check
    whose data was correct reported two failures and named neither. That is a
    wrong number, not a conservative one. ``UNION`` (distinct) settles the key
    set by the same rule ``GROUP BY`` used, and ``IS NOT DISTINCT FROM`` reads
    it back the same way.

    A key field may be nullable: ``Field.required`` defaults to ``False`` and
    nothing forces a key's to be true, so this is reachable from both grammar
    shapes rather than only from an aggregate ``by``.

    **Why not one ``FULL JOIN ... ON a IS NOT DISTINCT FROM b``**, which says
    all of this in a single line and renders identically on all three
    dialects: PostgreSQL refuses to *execute* it. Its full join is planned as a
    merge or hash join only, and neither ``IS NOT DISTINCT FROM`` nor the
    ``a = b OR (a IS NULL AND b IS NULL)`` spelling of it is merge- or
    hash-joinable there — both come back as ``FULL JOIN is only supported with
    merge-joinable or hash-joinable join conditions`` (verified on
    ``postgres:16-alpine``). The restriction is on ``FULL`` alone, so the same
    condition under a ``LEFT`` join is accepted, which is what this shape
    buys. DuckDB and Trino take either form; one shape is emitted for all
    three, because a reconcile check that compares NULL keys on two engines
    and not the third is worse than one that is verbose everywhere.

    The keys are projected from ``_keys`` rather than as
    ``COALESCE(_left.k, _right.k)``: the union already decided what the
    compared key *is*, and reading it from there is both shorter and the only
    spelling that cannot disagree with the join.
    """
    left, left_keys = _reconcile_side(check.left, ir, ctx, value=_LEFT_VALUE)
    right, right_keys = _reconcile_side(check.right, ir, ctx, value=_RIGHT_VALUE)
    # The guardrail stage has already refused sides keyed differently, so the
    # two key sets agree; join on the sorted order for deterministic bytes and
    # project in the left side's authored order.
    joined = sorted(set(left_keys) & set(right_keys))
    difference = exp.Abs(
        this=exp.Sub(
            this=exp.column(_LEFT_VALUE, table=_LEFT_ALIAS),
            expression=exp.column(_RIGHT_VALUE, table=_RIGHT_ALIAS),
        )
    )
    within = exp.Coalesce(
        this=grouped(
            exp.LTE(
                this=difference.copy(),
                # ``tolerance`` is a Decimal in the IR (RFC 0003 D5): it
                # reaches SQL as a numeric *literal*, never a float.
                expression=exp.Literal.number(str(check.tolerance)),
            )
        ),
        expressions=[exp.false()],
    )
    projections: list[Expression] = [
        cast("Expression", exp.column(key, table=_KEYS_ALIAS)) for key in left_keys
    ]
    projections.extend(
        (
            exp.column(_LEFT_VALUE, table=_LEFT_ALIAS),
            exp.column(_RIGHT_VALUE, table=_RIGHT_ALIAS),
            cast("Expression", exp.alias_(difference.copy(), "difference")),
            cast("Expression", exp.alias_(within, "within_tolerance")),
        )
    )
    return (
        exp.Select()
        .with_(_LEFT_ALIAS, as_=left)
        .with_(_RIGHT_ALIAS, as_=right)
        .with_(_KEYS_ALIAS, as_=_key_universe(joined))
        .select(*projections)
        .from_(exp.table_(_KEYS_ALIAS))
        .join(exp.table_(_LEFT_ALIAS), on=_keys_match(_LEFT_ALIAS, joined), join_type="LEFT")
        .join(exp.table_(_RIGHT_ALIAS), on=_keys_match(_RIGHT_ALIAS, joined), join_type="LEFT")
    )


def _key_universe(keys: list[str]) -> exp.Union:
    """Every key either side compares by, once.

    ``UNION`` rather than ``UNION ALL``: the deduplication *is* the point, and
    it is the same rule the aggregate side's ``GROUP BY`` already applied — two
    NULL keys are one key. Both branches project ``keys`` in the same sorted
    order, because a set operation matches columns by position and the two
    sides may declare theirs in different authored orders.
    """
    return exp.Union(
        this=exp.Select()
        .select(*(exp.column(key, table=_LEFT_ALIAS) for key in keys))
        .from_(exp.table_(_LEFT_ALIAS)),
        expression=exp.Select()
        .select(*(exp.column(key, table=_RIGHT_ALIAS) for key in keys))
        .from_(exp.table_(_RIGHT_ALIAS)),
        distinct=True,
    )


def _keys_match(side: str, keys: list[str]) -> Expression:
    """``_keys.k IS NOT DISTINCT FROM <side>.k`` for every compared key."""
    return conjunction(
        [
            exp.NullSafeEQ(
                this=exp.column(key, table=_KEYS_ALIAS),
                expression=exp.column(key, table=side),
            )
            for key in keys
        ]
    )


def reconcile_audit_predicate() -> Expression:
    """The violating-row predicate of a check's audit: rows outside tolerance.

    ``within_tolerance`` is already two-valued, so ``NOT`` is total here.
    """
    return exp.Not(this=exp.column("within_tolerance"))


def reconcile_audit_blocking(check: ReconcileIR) -> bool:
    """Whether a reconcile check's audit **stops the run** (RFC 0016 §5.3).

    ``reconcile`` carries an ``on_fail`` like every other disposition-bearing
    surface, and §5.3 gives it a job no rule can do: "a pipeline-stopping
    orphan gate, where genuinely wanted, is expressed as a ``reconcile`` check
    instead". That sentence is only true if ``on_fail: fail`` actually blocks.
    Emitting the same non-blocking audit for all three values made the field
    decoration — the mart said ``disposition = 'fail'`` while the run carried
    on regardless.

    ``flag`` stays non-blocking, and deliberately so: a reconcile disagreement
    means the numbers are wrong, which is exactly when a human needs to read
    the comparison table, and stopping the run would withhold the evidence.

    ``quarantine`` also lowers non-blocking — a reconcile check compares two
    aggregates and routes **no row** (§5.4's table: "separate model +
    non-blocking audit"), so there is nothing for a quarantine disposition to
    divert. Refusing the value belongs to the spec surface, where ``on_fail``
    is typed; treating it as "report, do not stop" is the conservative reading
    until that refusal lands.
    """
    return check.on_fail is OnFail.FAIL
