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

from typing import TYPE_CHECKING

from bloomery.errors import PlannerError
from bloomery.ir import Additivity
from bloomery.semantic import Proof, Provenance, SemanticFact, SemanticJudgement
from bloomery.semantic.plan import (
    Aggregate,
    Filter,
    JoinAggregates,
    JoinBranch,
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


def _plannable(request: MetricRequest, mart: MartIR, metrics: Mapping[str, MetricIR]) -> bool:
    """Whether P1's four nodes can state what this request computes.

    `Aggregate` names a rollup and no aggregation with it, so it is faithful
    only where rolling up *is* the whole operation. Four conditions, each
    naming a property rather than a metric shape that was observed to break —
    the enumerating version of this guard missed two shapes in a row:

    * every requested metric is a **stored measure of the covering mart**, so
      the R008 fact beneath the aggregate is true and no node is needed for a
      derivation;
    * every one is **additive**, since a semi-additive measure is lowered as a
      first/last pick over its own dimension and then summed, which a plain
      aggregate cannot say;
    * none is **cumulative**, since a window and a `period_agg` are not a
      rollup at all;
    * all are **restricted alike** — a single `Filter` over the scan says one
      thing about every measure beneath it, so metrics with different
      restrictions cannot share one. Compared through :func:`_restriction`,
      which is authored order thrown away in the two places it carries no
      meaning.
    """

    requested = tuple(metrics[name] for name in request.metrics if name in metrics)

    return (
        all(name in mart.measures for name in request.metrics)
        and all(metric.additivity is Additivity.ADDITIVE for metric in requested)
        and not any(metric.cumulative is not None for metric in requested)
        and len({_restriction(metric) for metric in requested}) <= 1
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

    return SemanticPlan(
        (
            Scan(relation=mart.name, grain=mart.grain),
            Filter(predicates=filters),
            Aggregate(
                input_grain=mart.grain,
                output_grain=mart.grain,
                measures=request.metrics,
                dimensions=dimensions,
                proof=_served_at_grain(mart.name, mart.grain, request.metrics),
            ),
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
) -> SemanticPlan | None:
    """The composed plan for a cross-mart request (RFC 0041 D9, D15), or
    ``None`` where any branch could not be stated.

    Each branch arrives with **its own** names for the join keys, because two
    marts spell one dimension differently and the node has to check that a
    branch aggregated to the keys rather than to something else of the same
    width (logs/T-0026.md, D-174).

    ``None`` propagates rather than being worked around: a join whose branches
    are only partly expressible would document one half of what the query
    computes, and half a plan reads as a whole one.
    """

    if any(plan is None for plan, _keys in branches):
        return None

    stated = tuple(
        JoinBranch(plan=plan, keys=names) for plan, names in branches if plan is not None
    )

    return SemanticPlan(
        (
            JoinAggregates(
                keys=tuple(keys),
                branches=stated,
                proof=_unique_at_result_grain(stated, keys),
            ),
            # Dimensions before measures, in request order — the same rule the
            # single-mart plan follows, and the order the composed SELECT
            # projects (RFC 0041 D9).
            Project(columns=(*keys, *measures)),
        )
    )
