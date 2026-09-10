"""The consumer-evidence guard (RFC 0065 D4, `LOCKED`): a mart declaring
``requires_evidence: locked`` whose measures rest on a fact nobody wrote down.

**Strictly above RFC 0039's floor** (D2). Every fact this reads already
*closes* its obligation — a project failing the floor never reaches here — so
nothing refused below is unsound. The consumer asked a different question:
:attr:`Provenance.closes` is about soundness and :attr:`Provenance.grade` is
about authorship, and this is the one place the two answers are allowed to
differ.

**What is graded, and what is not.** A measure rests on three kinds of fact,
and only one of them can vary:

- its **additivity** is `DECLARED` by construction — ``resolve.metrics._merge``
  reads it from the metric or its template and raises when both are silent, so
  an undeclared additivity is not a weaker grade, it is a project that does not
  resolve;
- its **embedding at the mart's grain** is `DECLARED` on both sides, and
  ``GrainViolation`` has already refused the project where the two disagree;
- the **dependencies** that carry the mart's columns are the ones whose basis
  the author did not necessarily write, so they are what this iterates.

Grading the first two would add a loop that cannot refuse. They are named here
instead, so that a later change making either of them defaultable is met by a
reader who knows this file assumed otherwise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bloomery.errors import InsufficientEvidence
from bloomery.semantic import (
    BASIS_PROVENANCE,
    EvidenceGrade,
    closure,
    dependencies,
    grain_of,
)

if TYPE_CHECKING:
    from bloomery.errors import GuardrailError
    from bloomery.ir import ProjectIR
    from bloomery.spec.project import Project

# ----------------------- #

__all__ = [
    "check_evidence",
]

#: The requirement that asks for anything. ``assumed`` is the default and
#: accepts every grade a compiling project can produce, so a mart carrying it
#: is not walked at all — which is what makes absence of the annotation
#: byte-identical to not having the key (D3).
_STRICT = "locked"


def _weakest(mart_name: str, draft: ProjectIR) -> list[tuple[str, str, str]]:
    """Every carried column whose cheapest derivation is not fully `LOCKED`,
    as ``(column, basis, how)`` triples sorted for a deterministic message.

    **Cheapest, not first.** A column reachable two ways is as strong as its
    strongest route: an author who declared a relationship should not be
    refused because the compiler could also have got there through a key. The
    minimum is taken over routes, and only then compared against the
    requirement.
    """

    mart = next((m for m in draft.marts if m.name == mart_name), None)
    if mart is None:
        # Absent from the draft means it failed to flatten, and that violation
        # is already in this batch. Reporting a second leaf about its evidence
        # would name a mart the author is already being told about.
        return []

    base = next((e for e in draft.entities if e.name == mart.base), None)
    if base is None:
        return []

    reached = {
        member.ref: member for member in closure(grain_of(base.name, base.key), dependencies(draft))
    }
    weak: list[tuple[str, str, str]] = []

    for column in mart.columns:
        if not column.source_entity or not column.source_column:
            continue
        member = next(
            (
                value
                for ref, value in reached.items()
                if ref.entity == column.source_entity and ref.column == column.source_column
            ),
            None,
        )
        if member is None:
            continue
        routes = [
            {step.basis.value for step in derivation.steps} for derivation in member.derivations
        ]
        if not routes or any(
            all(BASIS_PROVENANCE[basis].grade is EvidenceGrade.LOCKED for basis in route)
            for route in routes
        ):
            continue
        cheapest = min(
            routes,
            key=lambda route: sum(
                BASIS_PROVENANCE[basis].grade is not EvidenceGrade.LOCKED for basis in route
            ),
        )
        for basis in sorted(cheapest):
            if BASIS_PROVENANCE[basis].grade is EvidenceGrade.LOCKED:
                continue
            weak.append((column.name, basis, BASIS_PROVENANCE[basis].value))

    return sorted(set(weak))


# ....................... #


def check_evidence(project: Project, draft: ProjectIR) -> list[GuardrailError]:
    """Refuse a `locked` consumer reading a measure on a weaker premise (D4).

    Over the **authored** ``MartSet`` for the requirement and the draft for the
    facts: the key is a spec assertion and never enters :class:`MartIR`, since
    ``project_fingerprint`` walks that tree and a field there would move every
    fingerprint in the corpus for projects that never type the key (D3).

    Every violation is collected rather than the first, so a project sees the
    whole of what its requirement costs in one run — a requirement met one
    refusal per compile is one a team deletes.
    """

    if project.marts is None:
        return []

    errors: list[GuardrailError] = []

    for name, mart in sorted(project.marts.marts.items()):
        if mart.requires_evidence != _STRICT:
            continue
        for column, basis, provenance in _weakest(name, draft):
            for measure in sorted(mart.measures):
                msg = (
                    f"mart {name!r} requires 'locked'; measure {measure!r} rests on column "
                    f"{column!r}, whose derivation is {provenance} — the compiler reached it "
                    f"by {basis!r} rather than from anything an author wrote (RFC 0065 §5.1). "
                    f"Fix: declare the relationship that carries {column!r}, or set "
                    f"'requires_evidence: assumed' on this mart"
                )
                errors.append(
                    InsufficientEvidence(msg, source_path=f"marts: marts.{name}.requires_evidence")
                )

    return errors
