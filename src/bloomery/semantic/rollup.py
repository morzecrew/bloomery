"""Whether a mart may be re-aggregated to a coarser grain — the rollup
obligation (RFC 0058 §5.2, P1).

A rollup is a mart built from another mart by grouping its rows on a subset of
its dimensions: daily revenue from order lines, monthly from daily. It is read
*instead of* the detail table, so a wrong one does not error — it answers, and
it answers quickly, which is the plausible-but-wrong class this compiler exists
to refuse.

**The grain half is already discharged** (RFC 0058 D12). §5.2 called the
obligation a functional-dependency question, which it was when the source was
an entity; it is not one when the source is a mart. Two facts settle it.
:class:`~bloomery.semantic.GrainRef` admits only entity *key* columns —
``_unknown`` in :mod:`bloomery.semantic.closure` refuses every other
determinant — while a rollup's target is a set of mart columns, of which
``customer_segment`` is not a key and a date-role bucket like ``ordered_month``
is not an entity column at all. And it needs no re-derivation anyway: a mart is
a fact table at exactly its base entity's grain and carries measures only at
that grain (RFC 0010 D2, refused by ``GrainViolation`` where it is built), so
every column of it is determined by that grain and grouping on a subset
partitions rows the mart has already proved. That is R008, and citing it is
what this module does with the grain question.

What is left is the second question, and it is the whole of R013: **may this
measure be re-aggregated across whatever the rollup drops?** The aggregation
class answers it — RFC 0038 closed that word at six members and made the claim
checked rather than trusted, so what closes the obligation is a declaration the
compiler has already refused to take on faith.

Vocabulary, not a stage. Nothing in the compile pipeline consults this: RFC 0058
§12's P2 is what gives a rollup a spec key, an IR node and a guardrail that
refuses on the answer here, and §9's first risk is that this feature gets built
early because it looks like an emitter feature. The obligation is invisible from
the emitter, which is why it is built first and where it can be read.

Two things a reader might expect here and will not find. **Row 14's exclusion**
— a rollup is never a measure owner and never a covering mart — governs the
planner and the emitters, not this module; a rollup mart handed here is a
question about arithmetic, not about which mart serves a request. And **no
escape hatch** (RFC 0058 D3, `LOCKED`): nothing an author can declare makes a
refused class admissible. A hand-authored permission is an assertion nothing
checks, and it would end up disagreeing with the proof beside it — the second
source of truth §2 says this obligation exists to avoid.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from bloomery.ir import Additivity
from bloomery.semantic.proof import (
    Obligation,
    Proof,
    Provenance,
    Refutation,
    SemanticFact,
    SemanticJudgement,
)

if TYPE_CHECKING:
    from bloomery.ir import MartIR, MetricIR, ProjectIR

# ----------------------- #

__all__ = [
    "prove_mart_rollup",
    "prove_measure_rollup",
]


@dataclass(frozen=True, slots=True)
class _ClassRefusal:
    """The refusal an aggregation class earns when a rollup would carry it.

    ``found`` and ``remediation`` are per class rather than shared, because
    each names a different repair and "unsafe" naming none is the collapse
    :class:`~bloomery.semantic.RefusalReason` refuses one level down.
    """

    reason: str
    found: str
    remediation: str


#: Aggregation class → the refusal it earns, or ``None`` where the class is
#: admitted (RFC 0058 D13). Written out member by member and **subscripted**,
#: never read with ``.get``: a member added to :class:`~bloomery.ir.Additivity`
#: without a decision here raises at the first measure that carries it, where a
#: fallback would silently admit it — and admitting one silently is the whole
#: failure this obligation exists to prevent.
#: ``test_every_additivity_has_a_rollup_answer`` turns that into a failure at
#: the commit rather than at a call site.
#:
#: Admitted is not the same as summed. ``RATIO`` is admitted and never summed —
#: it is rebuilt from operands at the coarse grain, which :func:`_prove_ratio`
#: checks and R012 already states.
_REFUSALS: Final[dict[Additivity, _ClassRefusal | None]] = {
    Additivity.ADDITIVE: None,
    Additivity.RATIO: None,
    Additivity.SEMI_ADDITIVE: _ClassRefusal(
        reason="semi_additive_rollup_unsupported",
        found="declared semi_additive, which is not additive along its own over: dimension",
        remediation=(
            "a semi-additive measure reaches a coarser grain by first/last selection along "
            "its over: dimension rather than by summing, and no rule supplies that yet — "
            "leave it off the rollup and request it at the grain it originates"
        ),
    ),
    Additivity.NON_ADDITIVE: _ClassRefusal(
        reason="non_additive_not_summable",
        found="declared non_additive, so it is recomputed from components rather than stored",
        remediation=(
            "a non-additive measure is never a stored aggregate — declare it as "
            "additivity: ratio with ratio: {numerator, denominator} and carry both "
            "operands on the rollup, so it is rebuilt at the coarse grain"
        ),
    ),
    Additivity.DISTINCT_COUNT: _ClassRefusal(
        reason="distinct_count_not_reaggregable",
        found="declared distinct_count, and summing per-group distinct counts double-counts",
        remediation=(
            "an identity present in two groups is counted once by the question and twice "
            "by the sum; re-aggregating one needs a disjointness proof no rule supplies "
            "(RFC 0041 D8) — count it at the grain the question is asked at"
        ),
    ),
    Additivity.SNAPSHOT: _ClassRefusal(
        reason="snapshot_needs_time_selection",
        found="declared snapshot, which is point-in-time state",
        remediation=(
            "a snapshot needs explicit time selection — first, last or as-of — before any "
            "cross-time aggregation, and a rollup performs the aggregation without one"
        ),
    ),
}


def _judgement(mart: MartIR, keep: tuple[str, ...], measure: str = "") -> SemanticJudgement:
    kept = ", ".join(keep)
    operands = (("mart", mart.name), ("keep", kept))

    if not measure:
        return SemanticJudgement("RollupMart", operands)

    return SemanticJudgement("MartRollup", (*operands, ("measure", measure)))


# ....................... #


def _kept(keep: tuple[str, ...]) -> tuple[str, ...]:
    """The kept dimensions, canonical.

    Deduplicated and sorted rather than refused, the way
    :class:`~bloomery.semantic.RollupContext` treats a repeated anchor: naming
    one dimension twice is one grouping stated twice, and it means the same
    rollup. What that class refuses is a *conflict*, and two spellings of one
    kept dimension are not one.
    """

    return tuple(sorted(set(keep)))


# ....................... #


def _grouping_refusal(
    mart: MartIR, kept: tuple[str, ...], judgement: SemanticJudgement
) -> Refutation | None:
    """Whether the grouping itself is askable, or ``None`` where it is.

    Three ways it is not, and all three are the same mistake in different
    directions: a rollup grouping by nothing, one grouping by a column the mart
    does not have, and one grouping by *every* column, which drops nothing and
    is the parent mart under a second name.

    Shared by both entry points rather than owned by :func:`prove_mart_rollup`,
    because :func:`prove_measure_rollup` is public too and the class question
    never reads ``keep`` — so it would answer all three. One guard meets every
    caller, or only the entry point that happens to validate is safe to call.
    """

    if not kept:
        return Refutation(
            reason="no_kept_dimensions",
            judgement=judgement,
            obligations=(
                Obligation(
                    required=f"group {mart.name!r} by the dimensions the rollup keeps",
                    found="the rollup keeps no dimension",
                ),
            ),
            remediation=(
                "a rollup states the dimensions it keeps and derives what it drops "
                "(RFC 0058 D4) — name at least one"
            ),
        )

    requestable = {dimension.ref.qualified for dimension in mart.dimensions}
    unknown = tuple(name for name in kept if name not in requestable)

    if unknown:
        return Refutation(
            reason="unknown_dimension",
            judgement=judgement,
            obligations=(
                Obligation(
                    required=f"keep {', '.join(unknown)} on a rollup of {mart.name!r}",
                    found=f"mart {mart.name!r} has no such dimension",
                ),
            ),
            remediation=(
                f"the rollup groups the mart's own columns — {mart.name!r} offers "
                f"{', '.join(sorted(requestable)) or 'none at all'}"
            ),
            rejected=tuple(
                SemanticFact(
                    source=f"dimension:{mart.name}.{name}",
                    provenance=Provenance.UNKNOWN,
                    statement="no such dimension on this mart",
                )
                for name in unknown
            ),
        )

    if set(kept) != requestable:
        return None

    # A rollup is a mart at a *coarser* grain than the one it derives from
    # (RFC 0058 §1), and one keeping every column is the parent under a second
    # name. Refused rather than proved, even though the proof would be true —
    # re-aggregating over nothing is sound, and answering "yes" here would
    # authorize a duplicate gold table that costs storage and answers nothing
    # faster, which is the opposite of the reason the feature exists.
    return Refutation(
        reason="drops_nothing",
        judgement=judgement,
        obligations=(
            Obligation(
                required=f"roll {mart.name!r} up to a coarser grain",
                found=f"the rollup keeps every column of {mart.name!r}, so it drops none",
            ),
        ),
        remediation=(
            "a rollup is read instead of the detail table and is coarser than it — drop "
            "at least one dimension, or read the mart itself"
        ),
    )


# ....................... #


def _mart_contract(mart: MartIR, metric: MetricIR) -> Proof:
    """R008 — the grain half, cited rather than re-derived (RFC 0058 D12).

    Both leaves are `DECLARED`: an author wrote the mart's grain and the
    metric's, and ``GrainViolation`` refuses the project where they disagree,
    so this is a declaration the compiler has already refused to take on faith.
    """

    return Proof(
        rule="R008",
        conclusion=SemanticJudgement(
            "EmbeddedAtMartGrain",
            (("mart", mart.name), ("measure", metric.name), ("grain", mart.grain)),
        ),
        facts=(
            SemanticFact(
                source=f"mart:{mart.name}",
                provenance=Provenance.DECLARED,
                statement=f"{mart.name} is a fact table at the grain of {mart.grain}",
            ),
            SemanticFact(
                source=f"metric:{metric.name}",
                provenance=Provenance.DECLARED,
                statement=f"{metric.name} originates at {metric.grain}",
            ),
        ),
    )


# ....................... #


def _metric(project: ProjectIR, name: str) -> MetricIR | None:
    return next((candidate for candidate in project.metrics if candidate.name == name), None)


# ....................... #


def _prove_ratio(
    metric: MetricIR,
    mart: MartIR,
    keep: tuple[str, ...],
    project: ProjectIR,
    judgement: SemanticJudgement,
) -> Proof | Refutation:
    """A ratio is rebuilt on the rollup, never summed onto it (R012).

    Two obligations its operands carry that R012's own statement does not.
    They must be **carried by the mart**, because a quotient recomputed from
    operands the rollup does not store is recomputed from nothing — the Cube
    emitter already drops a named ratio whose components are absent, and a
    rollup that proved anyway would certify a measure that never lands. And
    each must be **additive**, not merely admitted here: an operand that is
    itself a ratio would send this function back through the same question, and
    nothing in the spec layer forbids two ratios naming each other, so
    "admitted" as RFC 0058 D13 words it has no termination argument. Additive
    operands terminate by construction and are the only ones R011 grants
    anyway (logs/T-0033.md).
    """

    if metric.ratio is None:
        return Refutation(
            reason="not_a_ratio",
            judgement=judgement,
            obligations=(
                Obligation(
                    required=f"rebuild {metric.name} on {mart.name!r}",
                    found=f"{metric.name} declares no ratio to rebuild from",
                ),
            ),
            remediation=(
                "a metric recomputed at the requested grain declares its operands — "
                "additivity: ratio with ratio: {numerator, denominator}"
            ),
        )

    carried = set(mart.measures)
    #: The operands' proofs and nothing else. A ratio is not *embedded* in the
    #: mart — it is calculated from measures that are — so citing R008 for the
    #: quotient itself would conclude `EmbeddedAtMartGrain` about something the
    #: mart never stores. Each operand carries that premise in its own subtree,
    #: which is R012's argument exactly: a ratio is sound at the target grain
    #: when its inputs are, and `prove_ratio_reconstruction` premises the same
    #: way.
    premises: list[Proof] = []

    for name in (metric.ratio.numerator, metric.ratio.denominator):
        if name not in carried:
            return Refutation(
                reason="operand_not_carried",
                judgement=judgement,
                obligations=(
                    Obligation(
                        required=f"rebuild {metric.name} from {name} on the rollup",
                        found=f"{name} is not a measure of mart {mart.name!r}",
                    ),
                ),
                remediation=(
                    f"a ratio is stored as its operands — name {name} among the mart's "
                    "measures, so the rollup carries something to divide"
                ),
            )

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
                remediation=(
                    f"a ratio's operands are metrics of this project — declare {name}, or "
                    f"point {metric.name}'s ratio: at one that exists"
                ),
                # `UNKNOWN` and not `DECLARED`: unlike a wrong additivity there
                # is no fact here at all — the name reaches nothing.
                rejected=(
                    SemanticFact(
                        source=f"metric:{name}",
                        provenance=Provenance.UNKNOWN,
                        statement="no such metric",
                    ),
                ),
            )

        if operand.additivity is not Additivity.ADDITIVE:
            return Refutation(
                reason="operand_not_additive",
                judgement=judgement,
                obligations=(
                    Obligation(
                        required=f"sum {name} to the grain {metric.name} is rebuilt at",
                        found=f"{name} is declared {operand.additivity.value}",
                    ),
                ),
                remediation=(
                    "a ratio is exactly as sound as the two sums beneath it — give "
                    f"{metric.name} additive operands, or ask it at the grain its "
                    "operands originate"
                ),
                rejected=(
                    SemanticFact(
                        source=f"metric:{name}",
                        provenance=Provenance.DECLARED,
                        statement=f"additivity is {operand.additivity.value}",
                    ),
                ),
            )

        answer = prove_measure_rollup(operand, mart, keep, project)

        if isinstance(answer, Refutation):
            # The operand is additive, so the class question cannot refuse it
            # and this recursion is one level deep. What can still refuse is
            # the grain premise: an operand at a different grain from the mart
            # is not this mart's to sum, and its own refutation says so more
            # precisely than any wording here would.
            return answer

        premises.append(answer)

    return Proof(
        rule="R013",
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


# ....................... #


def prove_measure_rollup(
    metric: MetricIR,
    mart: MartIR,
    keep: tuple[str, ...],
    project: ProjectIR,
) -> Proof | Refutation:
    """Whether ``metric`` survives a rollup of ``mart`` that keeps ``keep``.

    Four questions before the class question, and the order is what makes each
    refusal the useful one. Is the **grouping** askable — a rollup grouping by
    nothing, or by a column the mart does not have, is not one, and the class
    question would answer it anyway because it never reads ``keep``. Is the
    measure **on this mart** — a rollup re-aggregates what its parent stores,
    and a measure that is not there has no rollup to survive. Is it at the
    mart's **grain** — R008's premise, and the answer that tells an author
    about a mart rather than about a word. Does it **have** a measure at all —
    an aggregation with no aggregation is not a hard case, it is a
    contradiction. Only then, may it be summed.

    The grain check re-asks what ``GrainViolation`` already refuses when a
    project compiles, and asks it anyway. A proof is evidence, and one built
    over a caller's mart that nothing had validated would certify exactly the
    fan-out RFC 0010 D2 exists to prevent.
    """

    kept = _kept(keep)
    judgement = _judgement(mart, kept, metric.name)

    grouping = _grouping_refusal(mart, kept, judgement)

    if grouping is not None:
        return grouping

    if metric.name not in mart.measures:
        return Refutation(
            reason="measure_not_carried",
            judgement=judgement,
            obligations=(
                Obligation(
                    required=f"re-aggregate {metric.name} from mart {mart.name!r}",
                    found=f"mart {mart.name!r} does not carry {metric.name}",
                ),
            ),
            remediation=(
                "a rollup re-aggregates what its parent stores — name the measure among "
                "the mart's measures, or roll up from the mart that carries it"
            ),
            # `DECLARED`: the mart's measure list exists and is the author's,
            # and what is wrong with it is an absence rather than the list.
            rejected=(
                SemanticFact(
                    source=f"mart:{mart.name}",
                    provenance=Provenance.DECLARED,
                    statement=f"carries {', '.join(mart.measures) or 'no measure'}",
                ),
            ),
        )

    if metric.grain != mart.grain:
        return Refutation(
            reason="not_the_mart_grain",
            judgement=judgement,
            obligations=(
                Obligation(
                    required=f"re-aggregate {metric.name} from mart {mart.name!r}",
                    found=f"{metric.name} originates at {metric.grain}, the mart at {mart.grain}",
                ),
            ),
            remediation=(
                "a measure is embedded in a mart only at that mart's grain (RFC 0010 D2) — "
                "roll up from the mart the measure originates on"
            ),
            rejected=(
                SemanticFact(
                    source=f"metric:{metric.name}",
                    provenance=Provenance.DECLARED,
                    statement=f"originates at {metric.grain}",
                ),
            ),
        )

    refused = _REFUSALS[metric.additivity]

    if refused is not None:
        return Refutation(
            reason=refused.reason,
            judgement=judgement,
            obligations=(
                Obligation(
                    required=f"re-aggregate {metric.name} onto a rollup of {mart.name!r}",
                    found=refused.found,
                ),
            ),
            remediation=refused.remediation,
            # `DECLARED` rather than `UNKNOWN`: the word is written down and is
            # the wrong one for a rollup. Reporting it as absent would send an
            # author to declare something that is already there.
            rejected=(
                SemanticFact(
                    source=f"metric:{metric.name}",
                    provenance=Provenance.DECLARED,
                    statement=f"additivity is {metric.additivity.value}",
                ),
            ),
        )

    if metric.additivity is Additivity.RATIO:
        return _prove_ratio(metric, mart, kept, project, judgement)

    if metric.agg is None:
        # Below the class question rather than beside it. `additive` is a claim
        # about a measure, and this metric has none to make it about: nothing
        # in the spec or guardrail layer refuses the shape — `_has_no_measure`
        # in `guardrails/metrics` says so, and refuses it only under
        # `cumulative:` — so it reaches here declared additive with nothing to
        # sum. Below, because a `distinct_count` with no aggregation is better
        # answered by its class than by this, and a ratio legitimately has no
        # aggregation of its own and never reaches this line.
        #
        # The condition is the **aggregation**, not the pair. A metric with an
        # `expr:` and no `agg:` is a column expression rather than a measure —
        # there is nothing to sum it with — and reading the pair let such a
        # metric prove here and then refuse at emit, which puts a refusal
        # behind a target and so behind `bloomery check`, which reaches none
        # (RFC 0044 D1; logs/T-0034.md).
        return Refutation(
            reason="nothing_to_aggregate",
            judgement=judgement,
            obligations=(
                Obligation(
                    required=f"sum {metric.name} onto a rollup of {mart.name!r}",
                    found=f"{metric.name} declares no agg:",
                ),
            ),
            remediation=(
                "an additive measure is re-aggregated by summing the one it emits, and a "
                "metric with no aggregation emits none — declare the agg: this aggregates "
                "with, or decompose it and carry the components the rollup would rebuild "
                "it from"
            ),
            # `UNKNOWN` and not `DECLARED`: unlike a wrong additivity there is
            # no fact here at all — nothing says how this metric aggregates.
            rejected=(
                SemanticFact(
                    source=f"metric:{metric.name}",
                    provenance=Provenance.UNKNOWN,
                    statement="no aggregation declared",
                ),
            ),
        )

    return Proof(
        rule="R013",
        conclusion=judgement,
        premises=(_mart_contract(mart, metric),),
        facts=(
            SemanticFact(
                source=f"metric:{metric.name}",
                provenance=Provenance.DECLARED,
                statement=f"{metric.name} is declared additive",
            ),
        ),
    )


# ....................... #


def prove_mart_rollup(
    mart: MartIR,
    keep: tuple[str, ...],
    project: ProjectIR,
) -> Proof | Refutation:
    """Whether a rollup of ``mart`` keeping ``keep`` may carry every measure
    ``mart`` carries (RFC 0058 §5.2, D5 `LOCKED`).

    One answer for one declaration, refusing on the first measure that fails
    rather than collecting the failures. Each class refusal names a different
    repair, and one refutation carrying several would have to pick one reason
    code for all of them — the collapse into "unsafe" that
    :class:`~bloomery.semantic.RefusalReason` refuses one level down, arriving
    here instead. ``mart.measures`` is sorted, so which failure is reported is
    a property of the spec rather than of a traversal.
    """

    kept = _kept(keep)
    judgement = _judgement(mart, kept)

    grouping = _grouping_refusal(mart, kept, judgement)

    if grouping is not None:
        return grouping

    if not mart.measures:
        # Decided rather than inherited. Every measure of an empty set is
        # trivially re-aggregable, so a reduction over `all(...)` would prove
        # this rollup — and a proof resting on nothing is the one thing a
        # closed-world checker may never report as proven (RFC 0039 D1).
        return Refutation(
            reason="no_measures",
            judgement=judgement,
            obligations=(
                Obligation(
                    required=f"re-aggregate the measures of {mart.name!r}",
                    found=f"mart {mart.name!r} carries no measure",
                ),
            ),
            remediation=(
                "a rollup exists to pre-aggregate measures; a mart with none has nothing "
                "to pre-aggregate and is a distinct list of its dimensions"
            ),
        )

    premises: list[Proof] = []

    for name in mart.measures:
        metric = _metric(project, name)

        if metric is None:
            return Refutation(
                reason="unknown_measure",
                judgement=judgement,
                obligations=(
                    Obligation(
                        required=f"read {name} as a measure of mart {mart.name!r}",
                        found=f"{name} is not a metric of this project",
                    ),
                ),
                remediation=(
                    f"a mart's measures name metrics — declare {name}, or drop it from "
                    f"{mart.name!r}'s measures"
                ),
                rejected=(
                    SemanticFact(
                        source=f"metric:{name}",
                        provenance=Provenance.UNKNOWN,
                        statement="no such metric",
                    ),
                ),
            )

        answer = prove_measure_rollup(metric, mart, kept, project)

        if isinstance(answer, Refutation):
            return answer

        premises.append(answer)

    return Proof(
        rule="R013",
        conclusion=judgement,
        premises=tuple(premises),
        facts=(
            SemanticFact(
                source=f"mart:{mart.name}",
                provenance=Provenance.DECLARED,
                statement=f"{mart.name} carries {', '.join(mart.measures)}",
            ),
        ),
    )
