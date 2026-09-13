"""What currency a converted value is in, and on what basis (RFC 0061).

A conversion asserts three things — the currency its input holds, the currency
it should produce, and the date that picks the rate. Two of them were always
checkable: the output against the column's declared currency, the anchor
against a real field. The input was an assertion about the column's own values
with nothing in the spec language to check it against, so
``{convert: [JPY, USD, paid_at]}`` on euros read the yen rate, applied it to
euros, and compiled clean (logs/T-0024.md, D-155).

RFC 0061 gives the input a fact — ``currency_in:`` on the mapping's field, or
the output of the conversion before it in the same chain — and this module is
where the two meet. Phase 2 added the third shape §5.1 always admitted: the
fact may name a *column* rather than a code, for the export that carries an
amount and the currency it was taken in on the same row. What is declared is
still ``DECLARED`` — which column holds the code, not what the code is.

:func:`prove_conversion` **decides**: `resolve.build` refuses on its refutation
and accepts on its proof, so R009 is what an accepted conversion rests on
rather than a label applied to an outcome computed elsewhere (D8, see
logs/T-0025.md D-157).

The proof is not stored. Nothing reads a retained one — a conversion happens
once at compile time and no later stage asks — and building a channel to file
it in would be the same shape as the two capabilities this sequence has
already withdrawn for having no consumer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from bloomery.semantic.proof import (
    Obligation,
    Proof,
    Provenance,
    Refutation,
    SemanticFact,
    SemanticJudgement,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

# ----------------------- #

__all__ = [
    "DenominationRefusal",
    "Conversion",
    "consequence_of",
    "prove_conversion",
]


class DenominationRefusal(StrEnum):
    """What a conversion was refused for. Kept apart rather than collapsed
    into one code, because each names a different repair — the same reason
    :class:`~bloomery.semantic.RefusalReason` is a set rather than a boolean.
    """

    #: Nothing says what currency the input holds: no ``currency_in:`` on the
    #: field, and no conversion before this one in the chain.
    UNDECLARED_INPUT = "undeclared_input"
    #: A ``from`` that disagrees with the declared or derived input. One of
    #: the two is wrong and the compiler cannot tell which, which is why it
    #: reports both rather than picking.
    INPUT_DISAGREES = "input_disagrees"


# ....................... #


#: Why each refusal matters, for the caller that reports it. Kept beside the
#: remediations rather than in `resolve.build`, because a member added there
#: and not here would take its neighbour's consequence — the message would
#: describe a bug the author does not have, which is how "add a declaration"
#: reached someone whose two declarations merely disagreed (PR #114 review).
_CONSEQUENCES: Final[dict[DenominationRefusal, str]] = {
    DenominationRefusal.UNDECLARED_INPUT: (
        "a conversion out of a currency nothing declares reads the rate for a currency "
        "the values may not be in, and returns a number that is wrong by whatever the "
        "two rates differ by"
    ),
    DenominationRefusal.INPUT_DISAGREES: (
        "two authored statements disagree about what this column holds, and nothing in "
        "the spec says which is right — whichever it is, the other one picks a rate for "
        "a currency the values are not in, and the number is wrong by whatever the two "
        "rates differ by"
    ),
}


def consequence_of(reason: str) -> str:
    """What the refusal named by ``reason`` costs, in one clause.

    Takes the wire string a :class:`~bloomery.semantic.proof.Refutation` carries
    rather than the enum member, so the caller reporting a refutation does not
    have to re-derive which member produced it.
    """

    return _CONSEQUENCES[DenominationRefusal(reason)]


# ....................... #


#: Every reason, for the exhaustiveness test. A member added without a
#: remediation would otherwise reach an author as an empty string.
_REMEDIES: Final[dict[DenominationRefusal, str]] = {
    DenominationRefusal.UNDECLARED_INPUT: (
        "declare what the source holds — currency_in: <ISO-4217 code> on this field, "
        "beside from: and transform:"
    ),
    DenominationRefusal.INPUT_DISAGREES: (
        "one of the two is wrong: correct convert's first argument, or correct the "
        "declaration it disagrees with"
    ),
}


# ....................... #


@dataclass(frozen=True, slots=True)
class Conversion:
    """One ``convert`` step's declared triple, as the prover reads it.

    Its own type rather than the marker's expressions: the prover has no
    business knowing what a SQLGlot node looks like, and `resolve.build` has
    none knowing what a proof needs. Frozen and slotted like every other node
    in this package — a prover that could mutate its own input is a prover
    whose answer depends on when you read it.
    """

    from_ccy: str
    to_ccy: str
    anchor: str


# ....................... #


def _judgement(column: str, to_ccy: str) -> SemanticJudgement:
    return SemanticJudgement("Denominated", (("column", column), ("currency", to_ccy)))


# ....................... #


def _refuse(
    reason: DenominationRefusal,
    column: str,
    target: str,
    *,
    required: str,
    found: str,
    rejected: tuple[SemanticFact, ...] = (),
) -> Refutation:
    """``target`` is the chain's **final** destination, not the step that broke.

    A proof concludes about where the chain ends, and a refutation stands
    against the same judgement — otherwise a three-hop chain failing at its
    second step documents an obligation nobody asked for, and the two halves of
    one question serialize under different names (logs/T-0025.md, D-163).
    """

    return Refutation(
        reason=reason.value,
        judgement=_judgement(column, target),
        obligations=(Obligation(required=required, found=found),),
        remediation=_REMEDIES[reason],
        rejected=rejected,
    )


# ....................... #


def prove_conversion(
    conversions: Sequence[Conversion],
    *,
    column: str,
    declared_in: str | None,
    per_row: str | None,
    document: str,
) -> Proof | Refutation:
    """Whether this chain of conversions ends in a currency it can account for.

    ``conversions`` is in **chain order** — the first step first, which is the
    reverse of the order the markers are found in a lowered expression, since
    the outermost node is the last step applied. Ordering it here rather than
    at the call site is deliberate: every question this function asks is about
    what the *previous* step produced, and a caller passing them backwards
    would get answers that are individually well-formed and collectively wrong.

    ``declared_in`` is the field's ``currency_in:`` where it names a literal
    code and ``per_row`` is the column it names instead; the two are exclusive
    by the spec's type. Both absent means the input is undeclared, which is a
    refusal rather than a licence: an assertion nothing can check is
    indistinguishable from a fact, and that is the whole of RFC 0061 D1.

    **A per-row chain is walked exactly like a literal one**, because the
    opening fact is the only thing that differs: what a per-row declaration
    fixes is the *name* the first step must convert out of, and every step
    after the first converts out of a literal its predecessor produced. Written
    as one walk rather than two so that a second hop cannot be checked in one
    shape and not the other (logs/T-0052.md, D10).
    """

    if not conversions:  # pragma: no cover — the caller returns early
        raise ValueError("prove_conversion needs at least one conversion")

    first = conversions[0]
    #: What the chain sets out to produce — the judgement both a proof and a
    #: refutation are about, so that they describe one question.
    target = conversions[-1].to_ccy

    if per_row is not None:
        holding = per_row
    elif declared_in is not None:
        holding = declared_in
    else:
        return _refuse(
            DenominationRefusal.UNDECLARED_INPUT,
            column,
            target,
            required=f"what currency {column!r} holds before conversion",
            found=f"convert names {first.from_ccy!r} and nothing declares it",
            rejected=(
                SemanticFact(
                    source=f"mapping:{document}.{column}",
                    provenance=Provenance.UNKNOWN,
                    statement=(
                        f"convert asserts the input is {first.from_ccy!r}; no currency_in: "
                        "declares it and no earlier conversion produced it"
                    ),
                ),
            ),
        )

    # The declaration opens the chain; every step after the first is opened by
    # the one before it. Walking rather than checking the ends is what makes a
    # two-hop conversion expressible *and* checked: EUR -> CHF -> USD is three
    # agreements, not one.
    facts = [
        SemanticFact(
            source=f"mapping:{document}.{column}",
            provenance=Provenance.DECLARED,
            statement=(
                f"{column!r} holds the currency named by {holding!r} on each row, before conversion"
                if per_row is not None
                else f"{column!r} holds {holding} before conversion"
            ),
        )
    ]

    for index, step in enumerate(conversions):
        # Only the *first* step of a per-row chain converts out of the column;
        # what it produces is a literal, so every hop after it is compared the
        # way a literal chain's is.
        by_column = per_row is not None and index == 0

        if step.from_ccy != holding:
            return _refuse(
                DenominationRefusal.INPUT_DISAGREES,
                column,
                target,
                required=(
                    f"a conversion out of the currency column {holding!r}"
                    if by_column
                    else f"a conversion out of {holding!r}"
                ),
                found=f"convert names {step.from_ccy!r} as its input currency",
                rejected=(
                    SemanticFact(
                        source=f"mapping:{document}.{column}",
                        provenance=Provenance.DECLARED,
                        statement=(
                            f"{column!r} holds the currency named by {holding!r} on each row"
                            if by_column
                            else f"{column!r} holds {holding} at this point in the chain"
                        ),
                    ),
                ),
            )
        facts.append(
            SemanticFact(
                # The anchor belongs to the identity, not only to the
                # statement: `Proof` deduplicates by `source`, so a chain
                # reading the same pair on two different dates lost one of the
                # readings it depends on — silently, since the surviving fact
                # still looked right (logs/T-0025.md, D-163).
                source=(f"convert:{document}.{column}.{step.from_ccy}-{step.to_ccy}@{step.anchor}"),
                statement=(
                    f"a declared rate converts each row's own {step.from_ccy} to "
                    f"{step.to_ccy} as of {step.anchor}"
                    if by_column
                    else f"a declared rate converts {step.from_ccy} to {step.to_ccy} "
                    f"as of {step.anchor}"
                ),
                provenance=Provenance.DECLARED,
            )
        )
        holding = step.to_ccy

    return Proof(
        rule="R009",
        conclusion=_judgement(column, holding),
        facts=tuple(facts),
    )
