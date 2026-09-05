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

from bloomery.ir import Additivity
from bloomery.semantic import Proof, Provenance, SemanticFact, SemanticJudgement
from bloomery.semantic.plan import Aggregate, Filter, Project, Scan, SemanticPlan

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bloomery.ir import MartIR, MetricIR
    from bloomery.planner.coverage import Coverage
    from bloomery.planner.request import MetricRequest

# ----------------------- #

__all__ = [
    "build",
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
      restrictions cannot share one. Compared as sets: the clauses are ANDed,
      so two metrics restricted by the same clauses in different authored
      order are restricted identically.
    """

    requested = tuple(metrics[name] for name in request.metrics if name in metrics)

    return (
        all(name in mart.measures for name in request.metrics)
        and all(metric.additivity is Additivity.ADDITIVE for metric in requested)
        and not any(metric.cumulative is not None for metric in requested)
        and len({frozenset(metric.filter) for metric in requested}) <= 1
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
