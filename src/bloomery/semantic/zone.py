"""Whether a timestamp reaching a boundary was ever an undeclared wall clock
(RFC 0074 §5.3, R018).

``parse_ts`` turns a string into a value the type system calls UTC, and the
claim that the string *was* UTC is made by the absence of a ``to_utc`` step —
the one place an assertion cannot be checked. R018 is where the assertion has
to exist: not at every use of a timestamp, but where its **absolute position is
consumed**, because that is where being five hours out changes an answer.

Three provenances discharge it, and they are the three honest ones:

* the chain converts — ``{to_utc: America/New_York}`` names the clock the wall
  clock was written on, so the instant is right and the fact is recorded;
* the mapping declared ``zone_in:`` — the case ``to_utc`` cannot express,
  because ``to_utc: UTC`` converts nothing and nobody writes it (D3);
* the value never passed ``parse_ts`` — an instant from the source, or a step
  output. It was never a wall clock, so there is no clock to name.

Anything else is a refutation. A **per-source** answer rather than a per-column
one, because a merged entity is built from several mappings and one of them may
have declared: reporting the column would name a fix in a document that is
already correct, and the author of the other one would never see it.

Like every prover here this **decides** — :mod:`bloomery.guardrails.zone`
refuses on its refutation and stays silent on its proof, so an accepted
timestamp rests on R018 rather than carrying a label computed elsewhere. The
proof is not stored, for :mod:`~bloomery.semantic.denomination`'s reason: no
later stage asks.
"""

from __future__ import annotations

from dataclasses import dataclass
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
    "UNDECLARED_SOURCE_ZONE",
    "WallClock",
    "prove_zone",
]

#: The one way this obligation fails, as the stable reason code a refutation
#: carries. One rather than a family, unlike R009's: an undeclared zone and a
#: *wrong* zone are not two refusals, because the second is not detectable at
#: all — the check is that the assertion exists and is well-formed, never that
#: it is true (RFC 0074 §9).
UNDECLARED_SOURCE_ZONE: Final = "undeclared_source_zone"

_REMEDIATION: Final = (
    "declare what clock the source writes — zone_in: UTC on this field where its wall "
    "clocks really are UTC, or {to_utc: <zone>} in its chain naming the zone they are in"
)


# ....................... #


@dataclass(frozen=True, slots=True)
class WallClock:
    """One source's lowering of one column, as the prover reads it.

    Its own type rather than a :class:`~bloomery.ir.SourceFieldIR`, for the
    reason :class:`~bloomery.semantic.denomination.Conversion` is one: the
    prover has no business knowing how the IR spells a transform chain, and the
    guardrail has none knowing what a proof needs.

    ``parsed`` and ``converted`` are the chain's answer, ``declared`` the
    mapping's. All three can be true at once — a converting chain beside a
    matching ``zone_in:`` is a redundancy the resolver already checked.
    """

    #: The bronze relation this lowering reads, which is what a refusal names:
    #: on a merged entity it is the only thing that tells the two mappings
    #: apart.
    relation: str
    parsed: bool
    converted: bool
    declared: str | None


# ....................... #


def _judgement(entity: str, column: str) -> SemanticJudgement:
    return SemanticJudgement("ZoneKnown", (("column", f"{entity}.{column}"),))


# ....................... #


def prove_zone(
    readings: Sequence[WallClock], *, entity: str, column: str, site: str
) -> Proof | Refutation:
    """Whether every source of ``entity.column`` can say which clock it read.

    ``site`` names what consumes the instant — a date role, a comparison
    against a literal instant, an as-of anchor. It reaches the refutation
    rather than the proof because it is *why this is being asked*: the same
    column carried and never compared is not a defect, and a refusal that did
    not say which use made it one would send an author looking for a boundary
    they cannot find.

    Every failing source is reported, not the first: a boundary is usually got
    wrong in the same way in each of the mappings that feed it, and one refusal
    per round-trip would make an author fix a rename twice.
    """

    undeclared = tuple(
        reading
        for reading in readings
        if reading.parsed and not reading.converted and reading.declared is None
    )

    if undeclared:
        named = ", ".join(repr(reading.relation) for reading in undeclared)

        return Refutation(
            reason=UNDECLARED_SOURCE_ZONE,
            judgement=_judgement(entity, column),
            obligations=(
                Obligation(
                    required=f"the zone {column!r} was written in, where {site}",
                    found=f"parse_ts reads a wall clock and nothing declares which: {named}",
                ),
            ),
            remediation=_REMEDIATION,
            rejected=tuple(
                SemanticFact(
                    source=f"mapping:{reading.relation}.{column}",
                    provenance=Provenance.UNKNOWN,
                    statement=(
                        f"{column!r} is parsed from a wall clock in {reading.relation!r}; "
                        "the type system then calls it UTC and no declaration says it is"
                    ),
                )
                for reading in undeclared
            ),
        )

    return Proof(
        rule="R018",
        conclusion=_judgement(entity, column),
        facts=tuple(
            SemanticFact(
                source=f"mapping:{reading.relation}.{column}",
                provenance=Provenance.DERIVED if not reading.parsed else Provenance.DECLARED,
                statement=_statement(reading, column),
            )
            for reading in readings
        ),
    )


# ....................... #


def _statement(reading: WallClock, column: str) -> str:
    """Which of the three provenances this source discharged on.

    Written out rather than collapsed into "declared", because the three are
    different facts about the world and the proof is the only place that
    survives: one says a conversion happened, one says an author asserted, and
    one says the question never arose.
    """

    if not reading.parsed:
        return f"{column!r} arrives an instant from {reading.relation!r} and was never a wall clock"

    if reading.declared is not None:
        return (
            f"{reading.relation!r} writes {column!r} on a {reading.declared} clock, declared "
            "on the mapping"
        )

    return f"{column!r} is converted out of its source clock in {reading.relation!r} by to_utc"
