"""Building a :class:`~bloomery.semantic.SemanticPlan` from a resolved request
(RFC 0040 P1).

The plan says what bloomery decided to compute, before MetricFlow is handed
anything. At P1 it decides nothing new: the covering mart, the dimensions and
the filters all come from :func:`~bloomery.planner.coverage.resolve_request`,
which is the same precheck that ran before this existed. That is the point —
D5 makes P1 a re-expression with no capability change, so that §8's parity
suite has a fixed reference to measure P2 against.

**What authorizes the aggregate is the mart contract, not a rollup.** A P1 plan
never leaves its mart, and a mart may embed a measure only at its own grain
(RFC 0010 D2, checked by `check_grain` when the project compiles). So the
aggregate's input and output grain are the same, its proof cites R008, and no
cross-entity claim is made. Rolling a measure from its origin to a coarser
requested grain is P2, and citing a grain proof here would assert something
this phase did not check.

**P1 plans a plain measure, and says nothing about the rest.** §4's node
vocabulary is a scan, a filter, an aggregate that reduces, and a projection —
so a plan can state a request whose metrics are stored measures of the
covering mart, restricted alike, and nothing else. Three request shapes fall
outside it, and each produced a plan that read as an ordinary aggregate while
the query did something else (logs/T-0021.md, D-123, D-128, D-129):

* a **derived** metric — `average_order_value` is a ratio over `order_count`
  and `revenue`, so the requested name is not a mart measure at all; there is
  no node for the division, and the fact claiming the ratio was stored was
  simply false;
* a **cumulative** metric — `revenue_trailing_7d` *is* a mart measure, so the
  first guard let it through, and its window and `period_agg` appear nowhere
  in a plan that reads as a plain sum per day;
* a **semi-additive** metric — `stock_on_hand` is lowered as a last-per-day
  pick joined back and then summed, and the plan said `Aggregate`, which is
  the operation it is not;
* **mixed restrictions** — a metric's own filter narrows that measure alone,
  and `Filter` is a node over the scan, so a request pairing `paid_revenue`
  with `revenue` produced a plan restricting *both* to `status = 'paid'`.

`build` returns ``None`` for all three, which is what `QueryPlan.semantic`
being optional is for. Stated as one positive rule rather than three
exclusions: the shapes P1 cannot express outnumber the one it can, and a guard
written per counterexample is a guard that misses the next one — as the first
version of it did.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from bloomery.errors import PlannerError
from bloomery.ir import Additivity
from bloomery.semantic import Proof, Provenance, SemanticFact, SemanticJudgement
from bloomery.semantic.plan import (
    Aggregate,
    Compute,
    Filter,
    JoinAggregates,
    JoinBranch,
    PlanNode,
    Project,
    Scan,
    SemanticPlan,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from bloomery.ir import MartIR, MetricIR
    from bloomery.planner.coverage import Coverage
    from bloomery.planner.request import MetricRequest

# ----------------------- #

__all__ = [
    "build",
    "compose",
]


def _served_at_grain(mart_name: str, grain: str, measures: tuple[str, ...]) -> Proof:
    """R008: each measure is embedded in this mart at this mart's grain.

    One fact per measure rather than one for the mart, because the contract is
    per-measure — a mart carrying two measures is two separate claims that each
    originates here, and a single fact would let one of them be wrong without
    the proof's leaves changing.
    """

    return Proof(
        rule="R008",
        conclusion=SemanticJudgement("ServedAtGrain", (("grain", grain), ("mart", mart_name))),
        facts=tuple(
            SemanticFact(
                source=f"mart:{mart_name}.{measure}",
                provenance=Provenance.DECLARED,
                statement=f"{measure} is a measure of {mart_name}, whose grain is {grain}",
            )
            for measure in measures
        ),
    )


# ....................... #


def _restriction(metric: MetricIR) -> frozenset[tuple[str, str, frozenset[object]]]:
    """One metric's row restriction, as the set of rows it admits rather than
    as the text that was written for it.

    `resolve.build._metric_filters` keeps the authored order of both the
    clauses and each clause's values, deliberately — cosmetic in SQL, and
    load-bearing in the artifact bytes. Here it carries nothing: the clauses
    are ANDed, no operator in RFC 0015's closed vocabulary reads its values
    positionally, and a repeated member admits no extra row. So
    ``status in ('paid', 'refunded')``, ``status in ('refunded', 'paid')`` and
    ``status in ('paid', 'paid', 'refunded')`` are one restriction, and
    comparing what was written refuses plans these four nodes can state
    (logs/T-0021.md, D-130, D-131).

    Sets, and not a sorted tuple of the values' text. Text was a canonical
    *order*, and using it as the compared identity made it a canonical
    *value* too, which it is not: it flattens ``1`` and ``"1"`` onto one key
    and leaves this comparison depending on the type guardrail two layers away
    to keep them apart. A set hashes the values themselves, so distinct
    literals stay distinct and no order has to be invented for a mixture of
    `Decimal`, `str` and `bool`.
    """

    return frozenset(
        (clause.dimension, clause.op, frozenset(clause.values)) for clause in metric.filter
    )


# ....................... #


#: The classes one ``Aggregate`` node states whole: the engine applies the
#: declared aggregation to the scan's rows and nothing is picked, joined back
#: or recomputed first. A distinct count belongs here and *not* in a composed
#: plan — RFC 0041 D8 holds it out of branch planning, where it would be rolled
#: up rather than computed (logs/T-0028.md).
_PLAIN_AGGREGATE: Final = (Additivity.ADDITIVE, Additivity.DISTINCT_COUNT)


def _inputs_of(metric: MetricIR) -> tuple[str, ...] | None:
    """The stored measures ``metric`` is computed from, or ``None`` where this
    phase cannot state the computation (RFC 0066 §5.2).

    ``None`` for three different reasons, kept one answer because the caller
    has one response to all of them — the metric is not statable here:

    * it has a measure of its own, so nothing is computed and this is the
      wrong question to ask about it;
    * it is a ``derived:`` metric one of whose inputs carries an offset. That
      input is not a column of the relation the expression runs over; it is a
      second read of the same relation at a shifted range, which composes from
      branches rather than from arithmetic (RFC 0066 §5.2, §12 P4);
    * it declares neither a ratio nor a derivation, so there is nothing to
      compute it from.
    """

    if metric.ratio is not None:
        return (metric.ratio.numerator, metric.ratio.denominator)

    if metric.derived is not None:
        if any(
            item.offset_window is not None or item.offset_to_grain is not None
            for item in metric.derived.inputs
        ):
            return None

        return tuple(item.metric for item in metric.derived.inputs)

    return None


# ....................... #


def expression(metric: MetricIR) -> str:
    """One computed metric's expression, as prose rather than SQL.

    A ratio renders as the division it is: the ``NULLIF`` a target wraps the
    denominator in is a rendering decision about division by zero, and a plan
    that carried it would be stating how the SQL is spelled rather than what is
    computed (RFC 0040 D4).
    """

    if metric.ratio is not None:
        return f"{metric.ratio.numerator} / {metric.ratio.denominator}"

    derived = metric.derived
    assert derived is not None  # noqa: S101 — `_inputs_of` returned a tuple
    aliased = ", ".join(f"{item.alias} = {item.metric}" for item in derived.inputs)

    return f"{derived.expr.sql} where {aliased}"


# ....................... #


def _computed_after_aggregate(names: Sequence[str], *, over: str) -> Proof:
    """R014: each of these is computed from inputs already reduced beneath it,
    so the expression is evaluated at the requested grain and not per row.

    The premise is the mart contract rather than a rollup proof, which is
    R013's shape one level up: R012 asks whether an operand may be rolled
    between entity grains, and a metric computed over one mart rolls nothing —
    its inputs are aggregated inside the mart (logs/T-0037.md).

    ``over`` names what was reduced beneath — one mart for a single-mart plan,
    the join for a composed one. The rule is the same in both, and so is the
    thing that makes it true: the node cannot sit above nothing, because
    :meth:`SemanticPlan.check` refuses a `Compute` with no aggregate before it.
    """

    return Proof(
        rule="R014",
        conclusion=SemanticJudgement("ComputedAfterAggregate", (("over", over),)),
        facts=tuple(
            SemanticFact(
                source=f"metric:{name}",
                provenance=Provenance.DECLARED,
                statement=f"{name} has no measure of its own and is computed from ones that do",
            )
            for name in sorted(names)
        ),
    )


# ....................... #


def _partition(
    requested: Sequence[str], mart: MartIR, metrics: Mapping[str, MetricIR]
) -> tuple[tuple[str, ...], tuple[tuple[tuple[str, str], ...], tuple[str, ...]] | None]:
    """Split a request into the measures the mart stores and the metrics
    computed from them.

    Returns the stored names, and either the computed pair — output definitions
    and the input names they reference — or ``None`` where any requested metric
    is neither stored nor statable by :func:`_inputs_of`. ``None`` rather than
    an empty pair, because "nothing is computed" and "something is computed and
    this phase cannot say it" are opposite answers.
    """

    stored = tuple(name for name in requested if name in mart.measures)
    outputs: list[tuple[str, str]] = []
    inputs: list[str] = []

    for name in requested:
        if name in mart.measures or name not in metrics:
            continue

        needed = _inputs_of(metrics[name])

        if needed is None:
            return stored, None

        outputs.append((name, expression(metrics[name])))
        inputs.extend(needed)

    return stored, (tuple(outputs), tuple(dict.fromkeys(inputs)))


# ....................... #


def _plannable(request: MetricRequest, mart: MartIR, metrics: Mapping[str, MetricIR]) -> bool:
    """Whether P1's four nodes can state what this request computes.

    `Aggregate` names a rollup and no aggregation with it, so it is faithful
    only where rolling up *is* the whole operation. Four conditions, each
    naming a property rather than a metric shape that was observed to break —
    the enumerating version of this guard missed two shapes in a row:

    * every requested metric is a **stored measure of the covering mart**, so
      the R008 fact beneath the aggregate is true and no node is needed for a
      derivation;
    * every one is **a plain aggregate over the scan** — additive, or a
      distinct count computed from the mart's own rows. A semi-additive
      measure is lowered as a first/last pick over its own dimension and then
      summed, which one `Aggregate` cannot say (logs/T-0028.md);
    * none is **cumulative**, since a window and a `period_agg` are not a
      rollup at all;
    * all are **restricted alike** — a single `Filter` over the scan says one
      thing about every measure beneath it, so metrics with different
      restrictions cannot share one. Compared through :func:`_restriction`,
      which is authored order thrown away in the two places it carries no
      meaning.
    """

    requested = tuple(metrics[name] for name in request.metrics if name in metrics)
    stored, computed = _partition(request.metrics, mart, metrics)

    if computed is None:
        return False

    #: The stored measures the aggregate must carry: what was asked for
    #: directly, plus what the computed ones are built from.
    beneath = tuple(metrics[name] for name in (*stored, *computed[1]) if name in metrics)

    return (
        all(name in mart.measures for name in (*stored, *computed[1]))
        and all(metric.additivity in _PLAIN_AGGREGATE for metric in beneath)
        and not any(metric.cumulative is not None for metric in requested)
        and len({_restriction(metric) for metric in beneath}) <= 1
    )


# ....................... #


def build(
    coverage: Coverage,
    request: MetricRequest,
    metrics: Mapping[str, MetricIR],
    *,
    filters: tuple[str, ...],
) -> SemanticPlan | None:
    """The plan for one resolved request, or ``None`` where P1's vocabulary
    cannot state what the query computes.

    ``filters`` arrives already rendered, from
    :func:`~bloomery.planner.explain.applied_predicates` — the same renderers
    the :class:`~bloomery.planner.Explanation` uses, so the plan and the
    explanation are one account of one request rather than two, which is the
    thing RFC 0039 §7 refuses. It carries every predicate the query applies,
    including the ones the explanation reports elsewhere.
    """

    mart = coverage.mart

    if not _plannable(request, mart, metrics):
        return None

    dimensions = tuple(dimension.name for dimension in coverage.dimensions)
    stored, computed = _partition(request.metrics, mart, metrics)
    assert computed is not None  # noqa: S101 — `_plannable` returned False otherwise
    outputs, inputs = computed
    # What the aggregate carries: the measures asked for, plus the ones a
    # computed metric is built from. A ratio's operands are aggregated and the
    # quotient is taken over the result, which is the whole of what R014 says.
    aggregated = (*stored, *inputs)

    nodes: tuple[PlanNode, ...] = (
        Scan(relation=mart.name, grain=mart.grain),
        Filter(predicates=filters),
        Aggregate(
            input_grain=mart.grain,
            output_grain=mart.grain,
            measures=aggregated,
            dimensions=dimensions,
            proof=_served_at_grain(mart.name, mart.grain, aggregated),
        ),
    )

    if outputs:
        nodes = (
            *nodes,
            Compute(
                outputs=outputs,
                inputs=inputs,
                proof=_computed_after_aggregate([name for name, _expr in outputs], over=mart.name),
            ),
        )

    return SemanticPlan(
        (
            *nodes,
            # Request order, not sorted: a result's column order is part of the
            # answer. Dimensions before measures, which is the order the
            # emitted SELECT already uses.
            Project(columns=(*dimensions, *request.metrics)),
        )
    )


# ....................... #


def _unique_at_result_grain(branches: Sequence[JoinBranch], keys: Sequence[str]) -> Proof:
    """R010: every branch is unique at the join key, by its own aggregate.

    One fact per branch, and each one is about a node in the plan rather than
    about the warehouse — `DERIVED`, because it follows from the branch below
    it, and the branch was checked when it was constructed. This is the
    difference RFC 0041 D2 draws: a uniqueness read off data would be a
    data-dependent fact standing in for a proof (RFC 0039 D1), and the same
    join would then be authorized by whatever happened to be loaded.
    """

    return Proof(
        rule="R010",
        conclusion=SemanticJudgement("UniqueAtGrain", (("keys", ", ".join(keys) or "total"),)),
        facts=tuple(
            SemanticFact(
                source=f"branch:{_relation_of(branch.plan)}",
                provenance=Provenance.DERIVED,
                statement=(
                    f"{_relation_of(branch.plan)} is aggregated to the requested grain "
                    "before the join, so it holds one row per key"
                ),
            )
            for branch in branches
        ),
    )


# ....................... #


def _relation_of(branch: SemanticPlan) -> str:
    """The relation a branch scans — its identity in the composed plan.

    Exactly one, checked rather than assumed. Taking the first of several
    would name one relation in a fact that authorizes the whole branch, and a
    proof leaf naming the wrong relation is worse than a missing one: it reads
    as evidence.
    """

    scanned = [node.relation for node in branch.nodes if isinstance(node, Scan)]

    if len(scanned) != 1:
        msg = (
            f"a branch scans exactly one relation, got {scanned} — R010's fact is about "
            "the relation the branch aggregated, and a branch reading several has no "
            "single answer to name (RFC 0041 D2)"
        )
        raise PlannerError(msg)

    return scanned[0]


# ....................... #


def compose(
    branches: Sequence[tuple[SemanticPlan | None, tuple[str, ...]]],
    keys: Sequence[str],
    measures: Sequence[str],
    *,
    computed: Sequence[tuple[str, str]] = (),
    computed_inputs: Sequence[str] = (),
) -> SemanticPlan | None:
    """The composed plan for a cross-mart request (RFC 0041 D9, D15), or
    ``None`` where any branch could not be stated.

    Each branch arrives with **its own** names for the join keys, because two
    marts spell one dimension differently and the node has to check that a
    branch aggregated to the keys rather than to something else of the same
    width (logs/T-0026.md, D-174).

    ``computed`` carries the metrics produced by an expression *above* the join
    (RFC 0041 D3), as the pairs :class:`~bloomery.semantic.Compute` takes. It
    used to be a boolean, and a true one made the answer ``None``: §4's
    vocabulary stated no arithmetic, so naming such a metric in
    ``Project.columns`` would have claimed the join produced a column the join
    does not produce. `Compute` is the node that was missing (RFC 0066 §5.2),
    and it sits above the join for the same reason it sits above an aggregate —
    the operands are reduced first, and the expression is evaluated over the
    result.

    ``None`` still propagates from a branch that could not be stated: a join
    whose branches are only partly expressible would document one half of what
    the query computes, and half a plan reads as a whole one.
    """

    if any(plan is None for plan, _keys in branches):
        return None

    stated = tuple(
        JoinBranch(plan=plan, keys=names) for plan, names in branches if plan is not None
    )

    joined: tuple[PlanNode, ...] = (
        JoinAggregates(
            keys=tuple(keys),
            branches=stated,
            proof=_unique_at_result_grain(stated, keys),
        ),
    )

    if computed:
        joined = (
            *joined,
            Compute(
                outputs=tuple(computed),
                inputs=tuple(computed_inputs),
                proof=_computed_after_aggregate(
                    [name for name, _expr in computed], over="the branch join"
                ),
            ),
        )

    return SemanticPlan(
        (
            *joined,
            # Dimensions before measures, in request order — the same rule the
            # single-mart plan follows, and the order the composed SELECT
            # projects (RFC 0041 D9).
            Project(columns=(*keys, *measures)),
        )
    )
