"""The quality mart (RFC 0016 §5.8).

Every rule evaluation as one row of an ordinary gold model. Counts only — the
reject *rows* are never exposed through the semantic layer (§7.4), and nothing
here reads a clock.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sqlglot import exp
from sqlglot.expressions.core import Expression

from bloomery.ir import (
    EntityIR,
    Layer,
    ProjectIR,
    QualityRuleIR,
    ReconcileIR,
    SCDKind,
)
from bloomery.marts import DATE_BUCKETS
from bloomery.quality import (
    ENTITY_GRAIN_ROW,
    FLAGS_COLUMN,
    QUALITY_MEASURE_COLUMNS,
    QUALITY_RUN_ROLE,
    RunContext,
    counted_entities,
    disposition,
    flag_member,
)

from .reconcile import (
    _resolved_side,  # pyright: ignore[reportPrivateUsage]
    reconcile_audit_predicate,
    reconcile_relation,
)
from .silver import (
    _EXTRACT_ALIAS,  # pyright: ignore[reportPrivateUsage]
    _arrays,  # pyright: ignore[reportPrivateUsage]
    _extract_select,  # pyright: ignore[reportPrivateUsage]
    _sole_source,  # pyright: ignore[reportPrivateUsage]
    reject_relation,
)

if TYPE_CHECKING:
    from ..base import EmitContext

# ....................... #
# The quality mart (RFC 0016 §5.8): every rule evaluation as one row of an
# ordinary gold model. Counts only — the reject *rows* are never exposed
# through the semantic layer (§7.4), and nothing here reads a clock.

_QUALITY_CTE_PREFIX = "_quality_rows_"
_FLAGS_ALIAS = "_flags"
_QUARANTINED_ALIAS = "_quarantined"
_EVALUATIONS_ALIAS = "_evaluations"
_STAMPED_ALIAS = "_stamped"
#: The per-evaluation columns a branch projects, in §5.8's schema order.
_BRANCH_COLUMNS = (
    "entity",
    "mapping",
    "rule",
    "disposition",
    *(column for column, _metric in QUALITY_MEASURE_COLUMNS),
)


def _mapping_identity(entity: EntityIR) -> str:
    """The ``mapping`` dimension's value — the same string the reject table
    records, so the two surfaces name one mapping the same way.

    **Unexercised on a merged entity, and RFC 0024 D19 is why it need not be.**
    D19 reasoned that the mart accounts per entity because this identity has no
    single value across N sources. D29 removes the question rather than
    answering it: a merged entity is refused from the quality system entirely
    in P1, so it has no rules, contributes no evaluations, and never reaches
    this mart. The sole-source read is therefore a fact, not a choice among
    branches — and it is spelled as one so that the day P2 restores the rules,
    this raises instead of naming one source for all of them.
    """
    return f"{_sole_source(entity, 'the quality mart').relation}->{entity.name}"


def _quality_rows_cte(entity: EntityIR, ctx: EmitContext) -> exp.Select | exp.Union:
    """Every row the entity's rules were evaluated over, with the flag
    collection each carries and which side of the split it landed on.

    The union of the entity and its **unresolved** rejects is exactly §6's
    conservation-law population: a replayed row lives in the entity and its
    reject row is retained as audit history with ``resolved_at`` set, so
    excluding resolved rejects is what makes a replayed row count once.
    """
    namespace, relation = ctx.naming.relation(entity.name, Layer.SILVER)
    kept = (
        exp.Select()
        .select(
            exp.alias_(exp.column(FLAGS_COLUMN), _FLAGS_ALIAS),
            exp.alias_(exp.false(), _QUARANTINED_ALIAS),
        )
        .from_(exp.table_(relation, db=namespace))
    )
    if entity.quarantine is None:
        return kept
    reject_namespace, reject_rel = ctx.naming.relation(reject_relation(entity), Layer.SILVER)
    diverted = (
        exp.Select()
        .select(
            exp.alias_(exp.column("failed_rules"), _FLAGS_ALIAS),
            exp.alias_(exp.true(), _QUARANTINED_ALIAS),
        )
        .from_(exp.table_(reject_rel, db=reject_namespace))
        .where(exp.Is(this=exp.column("resolved_at"), expression=exp.null()))
    )
    return exp.union(kept, diverted, distinct=False)


def _counted(predicate: Expression) -> Expression:
    """``COALESCE(SUM(CASE WHEN <predicate> THEN 1 ELSE 0 END), 0)`` — a count
    that is 0, never NULL, on an empty **or** never-matching partition
    (RFC 0016 D68).

    The two halves answer different things and both are needed. ``ELSE 0``
    covers the partition that has rows and matches none of them; the
    ``COALESCE`` covers the partition with no rows at all, where ``SUM`` has
    nothing to sum and returns NULL — an entity whose source delivered nothing
    this run, which is an ordinary Tuesday and not an error. Without it every
    measure of that entity's mart rows is NULL, and a NULL measure does not
    read as a small number: it drops silently out of the ``SUM`` behind
    ``quality_quarantine_rate``, so the rate answers over a population smaller
    than the one it names.
    """
    return exp.Coalesce(
        this=exp.Sum(
            this=exp.Case(
                ifs=[exp.If(this=predicate, true=exp.Literal.number(1))],
                default=exp.Literal.number(0),
            )
        ),
        expressions=[exp.Literal.number(0)],
    )


def _rows_deduped(entity: EntityIR, ctx: EmitContext) -> Expression:
    """Rows dedupe removed before the rules ran — read off the dedupe stage
    itself, not as a residual against the surviving surfaces.

    ``bronze rows − rows that survived the stage-3 QUALIFY``. Both sides are
    scalar subqueries over **this run's** population, which is what makes the
    result a count: it is a difference between two numbers measured at the same
    moment, over the same relation, and it cannot be negative because the
    subtrahend is a subset of the minuend by construction.

    It used to be ``bronze − (entity rows + unresolved rejects)``. That looks
    like the same quantity and is not: the entity is rebuilt in full each run
    while the reject table is ``INCREMENTAL_BY_UNIQUE_KEY`` and *accumulates*,
    so as soon as bronze's incremental window moves past a row that is still an
    unresolved reject, the subtrahend exceeds the minuend and the "count" goes
    negative. A count that can be negative is not a count.

    Zero where it cannot be measured honestly: an entity without ``dedupe``
    loses nothing (the subtraction would always yield 0 anyway, at the cost of
    a bronze scan), and an SCD type 2 entity stores version history rather than
    one row per source row, so the difference would not be a dedupe count.
    """
    if entity.dedupe is None or entity.scd is SCDKind.TYPE2:
        return exp.Literal.number(0)
    origin = _sole_source(entity, "the quality mart's deduped count")
    namespace, relation = ctx.naming.relation(origin.relation, Layer.BRONZE)
    bronze = (
        exp.Select()
        .select(exp.Count(this=exp.Star()))
        .from_(exp.table_(relation, db=namespace))
        .subquery()
    )
    survivors = (
        exp.Select()
        .select(exp.Count(this=exp.Star()))
        .from_(_extract_select(entity, ctx).subquery(alias=_EXTRACT_ALIAS))
        .subquery()
    )
    return exp.Sub(this=bronze, expression=survivors)


def _branch(entity: EntityIR, rule: str, verdict: str, counts: list[Expression]) -> exp.Select:
    """One mart row over an entity's population CTE, in §5.8's schema order."""
    values: list[Expression] = [
        exp.Literal.string(entity.name),
        exp.Literal.string(_mapping_identity(entity)),
        exp.Literal.string(rule),
        exp.Literal.string(verdict),
        *counts,
    ]
    return (
        exp.Select()
        .select(
            *(
                cast("Expression", exp.alias_(value, name))
                for name, value in zip(_BRANCH_COLUMNS, values, strict=True)
            )
        )
        .from_(exp.table_(f"{_QUALITY_CTE_PREFIX}{entity.name}"))
    )


def _entity_branch(entity: EntityIR, ctx: EmitContext) -> exp.Select:
    """The entity's **accounting row**: the counts that belong to the entity
    rather than to any one rule (RFC 0016 §5.8, resolved per D12 — see
    :data:`~bloomery.quality.ENTITY_GRAIN_ROW`).

    ``rows_evaluated``, ``rows_quarantined`` and ``rows_deduped`` are facts
    about the *population*: how many rows the rules ran over, how many of them
    the split diverted, how many dedupe removed first. Carrying them on every
    rule row — which is what the schema's flat shape invites — makes them fan
    out: ``SUM(rows_evaluated)`` over an entity with eight rules returns eight
    times the population, and the quarantine rate built from it is wrong by
    that factor and again by the number of rules a diverted row happened to
    trip. Giving each count exactly one row to live on is what makes every
    measure of this mart additive, which is the only property that lets §5.8's
    "a plain ``MetricRequest``" be true at *any* group-by.
    """
    return _branch(
        entity,
        ENTITY_GRAIN_ROW,
        ENTITY_GRAIN_ROW,
        [
            exp.Count(this=exp.Star()),
            exp.Literal.number(0),
            _counted(exp.column(_QUARANTINED_ALIAS)),
            _rows_deduped(entity, ctx),
        ],
    )


def _rule_branch(entity: EntityIR, rule: QualityRuleIR, *, arrays: bool) -> exp.Select:
    """One row of the quality mart: what one rule did to one entity's rows.

    Counts are read back off the **recorded** flag names (D23), never by
    re-evaluating the rule: the rule already ran upstream, the reject table no
    longer carries the source columns a re-evaluation would need, and a second
    implementation of a predicate is a second thing to keep in agreement.

    A rule row reports ``rows_failed`` and nothing else. The population counts
    beside it are the entity's, and they live on the entity's own row
    (:func:`_entity_branch`); ``rows_quarantined`` is there too, counting
    *rows* rather than rule-level diversions, because two quarantine rules
    firing on one row divert one row and not two. For a ``quarantine``-
    disposition rule ``rows_failed`` **is** the number of rows it diverted —
    firing one diverts the row — so nothing is lost by the move.
    """
    fired = flag_member(exp.column(_FLAGS_ALIAS), rule.name, arrays=arrays)
    return _branch(
        entity,
        rule.name,
        str(disposition(rule)),
        [
            exp.Literal.number(0),
            _counted(fired),
            exp.Literal.number(0),
            exp.Literal.number(0),
        ],
    )


def _reconcile_branch(check: ReconcileIR, ir: ProjectIR, ctx: EmitContext) -> exp.Select:
    """One row per reconcile check, read off its own model.

    Reconcile names share the rule-name grammar precisely so they can land in
    this ``rule`` dimension (see ``RULE_NAME_PATTERN``). ``entity`` and
    ``mapping`` name the check's **left** side: a reconcile relates two
    entities, and the left is the one whose aggregate is under test.

    A rule row, therefore counted like one: ``rows_failed`` is the number of
    compared keys outside tolerance, and the population columns stay zero. A
    reconcile's own row count is a count of *keys*, not of the left entity's
    rows — adding it to that entity's ``rows_evaluated`` would mix two grains
    under one column and put a second wrong number into the quarantine rate.
    """
    _side, entity, _keys = _resolved_side(check.left, ir)
    namespace, relation = ctx.naming.relation(reconcile_relation(check), Layer.SILVER)
    values: list[Expression] = [
        exp.Literal.string(entity.name),
        exp.Literal.string(_mapping_identity(entity)),
        exp.Literal.string(check.name),
        exp.Literal.string(str(check.on_fail)),
        exp.Literal.number(0),
        _counted(reconcile_audit_predicate()),
        exp.Literal.number(0),  # a reconcile check routes no row (§5.3)
        exp.Literal.number(0),
    ]
    return (
        exp.Select()
        .select(
            *(
                cast("Expression", exp.alias_(value, name))
                for name, value in zip(_BRANCH_COLUMNS, values, strict=True)
            )
        )
        .from_(exp.table_(relation, db=namespace))
    )


def _run_column(macro: str | None, name: str, type_name: str) -> Expression:
    """One run-context column: the engine's expression, or declared-but-NULL.

    bloomery never reads a clock (RFC 0003), so neither value can be computed
    here. Where the target framework offers a macro, its literal text is
    substituted; where it does not, the column is emitted as a typed NULL
    carrying an inline comment naming what the caller supplies — the schema
    §5.8 promises, with no pretence that a value is present.
    """
    if macro is not None:
        return cast("Expression", exp.alias_(exp.cast(exp.var(macro), type_name), name))
    column = cast(
        "Expression", exp.alias_(exp.cast(exp.null(), exp.DataType.build(type_name)), name)
    )
    column.comments = [
        (
            f" {name}: supplied by the executing engine's run context (RFC 0016 §5.8); "
            "the pinned target exposes no macro for it — fill this column in your runner "
        )
    ]
    return column


def quality_mart_select(ir: ProjectIR, ctx: EmitContext, run: RunContext) -> exp.Select:
    """``gold.mart_data_quality`` (RFC 0016 §5.8): one row per rule
    evaluation, plus one per reconcile check.

    Three nested levels, so each concern is readable on its own: the branches
    count, the middle level stamps the run context once, and the outer level
    buckets ``run_date`` into the date role's columns the way any mart's date
    role is bucketed. Each quality-carrying entity's population is a CTE, so
    an entity with ten rules is one scan, not ten.
    """
    arrays = _arrays(ctx)
    branches: list[exp.Select] = []
    # `counted_entities`, not a second filter: this loop and `carries_quality`
    # must agree exactly, or the mart is emitted with no branches to union.
    entities = counted_entities(ir)
    for entity in entities:  # sorted on ProjectIR; rules sorted on EntityIR
        branches.append(_entity_branch(entity, ctx))
        branches.extend(_rule_branch(entity, rule, arrays=arrays) for rule in entity.quality)
    branches.extend(_reconcile_branch(check, ir, ctx) for check in ir.reconcile)
    evaluations: exp.Select | exp.Union = branches[0]
    for branch in branches[1:]:
        evaluations = exp.union(evaluations, branch, distinct=False)

    stamped = (
        exp.Select()
        .select(
            *(exp.column(name, table=_EVALUATIONS_ALIAS) for name in _BRANCH_COLUMNS),
            _run_column(run.run_id, "run_id", "TEXT"),
            _run_column(run.run_date, "run_date", "DATE"),
        )
        .from_(evaluations.subquery(alias=_EVALUATIONS_ALIAS))
    )
    run_date = exp.column("run_date", table=_STAMPED_ALIAS)
    projections: dict[str, Expression] = {
        name: exp.column(name, table=_STAMPED_ALIAS)
        for name in (*_BRANCH_COLUMNS, "run_id", "run_date")
    }
    for bucket in DATE_BUCKETS:
        bucketed = exp.func("DATE_TRUNC", exp.Literal.string(bucket), run_date.copy())
        projections[f"{QUALITY_RUN_ROLE}_{bucket}"] = cast(
            "Expression",
            exp.alias_(
                exp.cast(bucketed, exp.DataType.build("DATE")), f"{QUALITY_RUN_ROLE}_{bucket}"
            ),
        )
    select = (
        exp.Select()
        # Sorted by column name, exactly as ``mart_select`` projects a mart's
        # own (sorted) columns — the emitted SELECT and ``MartIR.columns``
        # agree position by position.
        .select(*(projections[name] for name in sorted(projections)))
        .from_(stamped.subquery(alias=_STAMPED_ALIAS))
    )
    for entity in entities:
        select = select.with_(
            f"{_QUALITY_CTE_PREFIX}{entity.name}", as_=_quality_rows_cte(entity, ctx)
        )
    return select
