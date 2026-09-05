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
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bloomery.semantic import Proof, Provenance, SemanticFact, SemanticJudgement
from bloomery.semantic.plan import Aggregate, Filter, Project, Scan, SemanticPlan

if TYPE_CHECKING:
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


def build(coverage: Coverage, request: MetricRequest, *, filters: tuple[str, ...]) -> SemanticPlan:
    """The plan for one resolved request.

    ``filters`` arrives already rendered, from the same helper the
    :class:`~bloomery.planner.Explanation` uses — a plan naming its predicates
    differently from the explanation beside it would be two accounts of one
    request, which is the thing RFC 0039 §7 refuses.
    """

    mart = coverage.mart
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
