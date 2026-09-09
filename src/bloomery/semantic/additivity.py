"""Whether a measure may be *summed* once its values are allowed to travel
(RFC 0039 §3 — the additive-rollup and derived-ratio rules).

Two questions look like one and are not. :func:`~bloomery.semantic.can_roll_up`
answers whether values originating at one grain may reach another; it says
nothing about what to do with them when they arrive. A measure whose grain
proof is perfect can still be wrong to add up — an average, a distinct count, a
ratio — and one rule conflating the two could not refuse the second while
granting the first, which is corpus case 002's whole shape.

So the additive obligation composes *with* the grain proof rather than inside
it: :func:`prove_additive_rollup` takes ``prove_rollup``'s answer as a premise
and adds the one fact that answer never reads. Nothing in this package read
additivity before (logs/T-0029.md), which is why this is a second obligation
rather than a refinement of an existing one.

**Expressed, not substituted** (RFC 0039 D3, `LOCKED`). `guardrails/additivity`
still refuses a false additivity claim when a project compiles, and this does
not replace it. What this adds is the ability to *state* the reasoning, which a
guardrail that answers by staying silent cannot do.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bloomery.ir import Additivity
from bloomery.semantic.closure import prove_rollup
from bloomery.semantic.nodes import NO_CONTEXT
from bloomery.semantic.proof import (
    Obligation,
    Proof,
    Provenance,
    Refutation,
    SemanticFact,
    SemanticJudgement,
)

if TYPE_CHECKING:
    from bloomery.ir import MetricIR, ProjectIR
    from bloomery.semantic.nodes import GrainRef, RollupContext

# ----------------------- #

__all__ = [
    "prove_additive_rollup",
    "prove_ratio_reconstruction",
]


def _judgement(kind: str, metric: str, source: GrainRef, target: GrainRef) -> SemanticJudgement:
    return SemanticJudgement(
        kind, (("measure", metric), ("from", source.label), ("to", target.label))
    )


# ....................... #


def _metric(project: ProjectIR, name: str) -> MetricIR | None:
    return next((candidate for candidate in project.metrics if candidate.name == name), None)


# ....................... #


def prove_additive_rollup(
    metric: MetricIR,
    source: GrainRef,
    target: GrainRef,
    project: ProjectIR,
    context: RollupContext = NO_CONTEXT,
) -> Proof | Refutation:
    """Whether ``metric`` may be summed from ``source`` to ``target``.

    Two obligations, in the order that makes the refusal useful. The grain
    question first, because its refutation is the more specific one: "these
    values may not travel this way" tells an author about a relationship, and
    reporting "this measure is not additive" over a route that does not exist
    would send them to fix the wrong thing. Where the grain proof refuses, that
    refutation is returned unchanged — it *is* the smallest failed obligation
    (§6), and its judgement says which of the two questions failed.

    The additivity fact is `DECLARED`: an author wrote `additivity: additive`
    and owns it. RFC 0038 closed that word at six members and made the claim
    checked rather than trusted, so what closes this obligation is a
    declaration the compiler has already refused to take on faith.
    """

    judgement = _judgement("AdditiveRollup", metric.name, source, target)
    origins = {column.entity for column in source.determinants}

    # The caller names the grain to sum *from*, and a measure that does not
    # originate there is the fan-out case 001 is about — summed once per row of
    # a finer grain it was copied onto. Checked rather than trusted: a proof is
    # evidence, and one built from a source the caller got wrong would certify
    # exactly the duplication this sequence exists to refuse
    # (logs/T-0029.md, finding 1).
    if origins != {metric.grain}:
        return Refutation(
            reason="not_the_origin_grain",
            judgement=judgement,
            obligations=(
                Obligation(
                    required=f"sum {metric.name} from {source.label}",
                    found=f"{metric.name} originates at {metric.grain}",
                ),
            ),
            remediation=(
                "ask from the grain the measure originates at — a measure summed from a "
                "finer grain it was copied onto is counted once per copy"
            ),
            rejected=(
                SemanticFact(
                    source=f"metric:{metric.name}",
                    provenance=Provenance.DECLARED,
                    statement=f"originates at {metric.grain}",
                ),
            ),
        )

    grain = prove_rollup(source, target, project, context)

    if isinstance(grain, Refutation):
        return grain

    if metric.additivity is not Additivity.ADDITIVE:
        return Refutation(
            reason="not_additive",
            judgement=judgement,
            obligations=(
                Obligation(
                    required=f"sum {metric.name} from {source.label} to {target.label}",
                    found=f"{metric.name} is declared {metric.additivity.value}",
                ),
            ),
            remediation=(
                "a non-additive measure is recomputed at the requested grain rather than "
                "summed from a coarser one — declare its decomposition, or request it at "
                "the grain it originates"
            ),
            # `DECLARED` rather than `UNKNOWN`: the additivity is written down
            # and is the wrong one. Reporting it as absent would send an author
            # to declare a word that is already there.
            rejected=(
                SemanticFact(
                    source=f"metric:{metric.name}",
                    provenance=Provenance.DECLARED,
                    statement=f"additivity is {metric.additivity.value}",
                ),
            ),
        )

    return Proof(
        rule="R011",
        conclusion=judgement,
        premises=(grain,),
        facts=(
            SemanticFact(
                source=f"metric:{metric.name}",
                provenance=Provenance.DECLARED,
                statement=f"{metric.name} is declared additive",
            ),
        ),
    )


# ....................... #


def prove_ratio_reconstruction(
    metric: MetricIR,
    source: GrainRef,
    target: GrainRef,
    project: ProjectIR,
    context: RollupContext = NO_CONTEXT,
) -> Proof | Refutation:
    """Whether ``metric``'s ratio may be *recomputed* at ``target``.

    A ratio is never rolled up; it is rebuilt. `SUM(num) / SUM(den)` at the
    requested grain and a stored quotient aggregated afterwards are different
    numbers, and the second is the one a warehouse hands you for free. So the
    obligation is not "may this quotient be summed" — it never may — but "may
    each operand be summed to here", and the ratio follows from the two.

    That is why the premises are :func:`prove_additive_rollup` answers rather
    than a rule of this one's own: the reconstruction is sound exactly when the
    reconstruction's *inputs* are, and stating it any other way would let a
    ratio over a non-additive operand prove itself.
    """

    judgement = _judgement("RatioReconstruction", metric.name, source, target)

    if metric.ratio is None:
        return Refutation(
            reason="not_a_ratio",
            judgement=judgement,
            obligations=(
                Obligation(
                    required=f"reconstruct {metric.name} at {target.label}",
                    found=f"{metric.name} declares no ratio to reconstruct from",
                ),
            ),
            remediation=(
                "a metric recomputed at the requested grain declares its operands — "
                "additivity: ratio with ratio: {numerator, denominator}"
            ),
        )

    operands = (metric.ratio.numerator, metric.ratio.denominator)
    premises: list[Proof] = []

    for name in operands:
        operand = _metric(project, name)

        if operand is None:
            return Refutation(
                reason="operand_unreachable",
                judgement=judgement,
                obligations=(
                    Obligation(
                        required=f"read {name} as an operand of {metric.name}",
                        found=f"{name} is not a metric of this project",
                    ),
                ),
                # `UNKNOWN` and not `DECLARED`: unlike a wrong additivity, there
                # is no fact here at all — the name reaches nothing.
                rejected=(
                    SemanticFact(
                        source=f"metric:{name}",
                        provenance=Provenance.UNKNOWN,
                        statement="no such metric",
                    ),
                ),
            )

        answer = prove_additive_rollup(operand, source, target, project, context)

        if isinstance(answer, Refutation):
            return answer

        premises.append(answer)

    return Proof(
        rule="R012",
        conclusion=judgement,
        premises=tuple(premises),
        facts=(
            SemanticFact(
                source=f"metric:{metric.name}",
                provenance=Provenance.DECLARED,
                statement=(
                    f"{metric.name} is {metric.ratio.numerator} / {metric.ratio.denominator}"
                ),
            ),
        ),
    )
