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

from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from collections.abc import Set as AbstractSet

from bloomery.errors import InsufficientEvidence
from bloomery.semantic import (
    BASIS_PROVENANCE,
    MAX_DERIVATIONS,
    EvidenceGrade,
    Provenance,
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
    "IMPORTED_MESSAGE",
    "MESSAGE",
    "Step",
    "check_evidence",
    "weak_bases",
]

#: One hop of a route, as the grade reads it: ``(basis, relationship)``, where
#: the relationship is ``None`` for ``entity_key``. It is
#: :attr:`~bloomery.semantic.FunctionalDependency.via` verbatim, which is what
#: keeps this from being a second notion of "which edge".
type Step = tuple[str, str | None]

#: The refusal, as a template rather than an f-string at the raise site.
#:
#: **A constant because the docs quote it.** `pages/docs/concepts/` shows this
#: message rendered, and a documented message is a hand-copy of a string that
#: lives here — the two drifted twice inside one PR series (T-0041), once when
#: the message was restructured in review and once when a basis it named was
#: deleted. `test_the_documented_evidence_refusal_quotes_the_template` reads
#: the literal segments out of this value and asserts the page still contains
#: them, so the copy cannot silently stop being one.
#:
#: The placeholders are named rather than positional so the segments between
#: them are what a reader of the page sees, and `{column}` appearing twice is
#: deliberate: the refusal names the column again in the fix, because a reader
#: who has scrolled past the first mention is the reader who needs it.
MESSAGE = (
    "mart {mart} requires 'locked'; its measures ({measures}) rest on column "
    "{column}, which the compiler reached by {bases} rather than from anything "
    "an author wrote (RFC 0065 §5.1). Fix: declare the relationship that carries "
    "{column}, or set 'requires_evidence: assumed' on this mart"
)

#: The refusal for a column reached only through an **imported**
#: relationship, which is a different sentence and a different repair
#: (RFC 0070 §1). :data:`MESSAGE` tells an author to declare the relationship,
#: and here one is declared — by an importer, in a document they may not have
#: read. Sending them to declare it again is advice they cannot act on, which
#: is the remedy-free refusal RFC 0065 D4 forbids.
IMPORTED_MESSAGE = (
    "mart {mart} requires 'locked'; its measures ({measures}) rest on column "
    "{column}, carried by {relationships} — read out of {artifacts} rather than "
    "written here (RFC 0070 D1). Fix: author the relationship in this project and "
    "drop its 'imported_from:', or set 'requires_evidence: assumed' on this mart"
)

#: The requirement that asks for anything. ``assumed`` is the default and
#: accepts every grade a compiling project can produce, so a mart carrying it
#: is not walked at all — which is what makes absence of the annotation
#: byte-identical to not having the key (D3).
_STRICT = "locked"


def _grade(step: Step, imported: Mapping[str, str]) -> EvidenceGrade:
    """One step's grade: the basis table, overlaid per relationship.

    :data:`~bloomery.semantic.BASIS_PROVENANCE` is keyed by basis *kind*, so on
    its own it says the same thing about every ``many_to_one`` in a project.
    A relationship an importer wrote was not authored here whatever its
    cardinality, and that is the question this grade answers (RFC 0070 D1) —
    so a step naming one grades `ASSUMED` before the table is consulted.

    ``via`` is ``None`` for ``entity_key``, which traverses no relationship and
    therefore cannot have been imported; it takes the table's answer. The
    ``is not None`` test is **narrowing, not a guard** — ``imported`` is keyed
    by relationship name, so a ``None`` would miss anyway — and it is written
    out because a reader checking whether a key hop can be imported should
    find the answer here rather than deduce it from the key type.
    """

    basis, via = step

    if via is not None and via in imported:
        return Provenance.IMPORTED_VERIFIED.grade

    return BASIS_PROVENANCE[basis].grade


# ....................... #


def weak_bases(
    routes: Iterable[AbstractSet[Step]], imported: Mapping[str, str] = MappingProxyType({})
) -> tuple[str, ...]:
    """The sub-`LOCKED` bases of a column, or empty if it is strong enough.

    A route is a set of ``(basis, relationship)`` steps rather than of basis
    names, because the grade is a property of the edge and not of the kind of
    edge: two ``many_to_one`` hops differ when one of them was imported
    (RFC 0070 D1). ``imported`` is the set of relationship names an artifact
    supplied, read from the authored spec by :func:`check_evidence`.

    Split out because it is the whole of the rule and the corpus cannot
    exercise it: no column in any fixture is reached two ways, so a suite built
    from fixtures alone cannot tell "as strong as its strongest route" from
    "every route must be strong" — and the second is a different rule, not a
    stricter reading of the first. It is asked directly instead.

    A column with **no** route is not weak: it is a determinant of the origin
    grain, which is the grain itself and is argued for by nothing. Neither is
    one whose route list is at :data:`~bloomery.semantic.MAX_DERIVATIONS`,
    where the list is not known to be complete — see the branch below.
    """

    routes = list(routes)

    if any(
        all(_grade(step, imported) is EvidenceGrade.LOCKED for step in route) for route in routes
    ):
        return ()

    if len(routes) >= MAX_DERIVATIONS:
        # `closure` keeps at most `MAX_DERIVATIONS` routes per member and drops
        # the rest by signature order, so a member holding that many may have
        # had a stronger one discarded. Refusing here would be a refusal the
        # author cannot act on — the route they declared might be the one that
        # was dropped — and a requirement that refuses without a remedy is the
        # failure this whole design was regraded to avoid (#102). Abstaining
        # costs a refusal that is not certain; refusing costs one that is
        # wrong.
        return ()

    return tuple(
        sorted(
            {
                # The basis, not the relationship. This feeds `MESSAGE`,
                # which names *how* the compiler reached the column because
                # its reader's repair is to declare an edge of that kind.
                # `IMPORTED_MESSAGE` names the relationship instead, and takes
                # it from `names` below — there the edge is already declared
                # and the kind is not what the author acts on.
                step[0]
                for route in routes
                for step in route
                if _grade(step, imported) is not EvidenceGrade.LOCKED
            }
        )
    )


# ....................... #


def _weak_columns(
    mart_name: str, draft: ProjectIR, imported: Mapping[str, str]
) -> list[tuple[str, str, tuple[str, ...]]]:
    """Every carried column no route reaches under `LOCKED`, as ``(column,
    bases)`` pairs sorted for a message that does not move between runs.

    **A column is as strong as its strongest route.** An author who declared a
    relationship is not refused because the compiler could also have got there
    through a key, so one fully-`LOCKED` route acquits the column. Only where
    *every* route is weak does it report, and then it names the weak bases of
    all of them — which route the compiler would have taken changes the
    sentence and not the verdict, and picking one would be a choice no test
    could observe.
    """

    mart = next((m for m in draft.marts if m.name == mart_name), None)
    base = next((e for e in draft.entities if e.name == mart.base), None) if mart else None

    if mart is None or base is None:
        # Absent from the draft means the mart failed to flatten, and that
        # violation is already in this batch. A second leaf about its evidence
        # would name a mart the author is being told about anyway.
        return []

    reached = {
        (member.ref.entity, member.ref.column): member
        for member in closure(grain_of(base.name, base.key), dependencies(draft))
    }
    weak: list[tuple[str, str, tuple[str, ...]]] = []

    for column in mart.columns:
        member = reached.get((column.source_entity, column.source_column))
        if member is None:
            continue
        bases = weak_bases(
            (
                {(step.basis.value, step.via) for step in derivation.steps}
                for derivation in member.derivations
            ),
            imported,
        )
        if not bases:
            continue

        # Which imported relationships were on the weak routes, so the message
        # can name them. Only those actually traversed: a project may import a
        # relationship this column never goes through, and naming it would
        # point the author at the wrong line.
        names = sorted(
            {
                step.via
                for derivation in member.derivations
                for step in derivation.steps
                if step.via is not None and step.via in imported
            }
        )
        weak.append((column.name, ", ".join(repr(basis) for basis in bases), tuple(names)))

    return sorted(weak)


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

    # Read here rather than at the call site, beside the `requires_evidence`
    # read this function already does: one walk of the authored spec, two
    # facts, so a project cannot be strict about a relationship the same
    # function decided was authored (logs/T-0053.md).
    imported = {
        relationship.name: relationship.imported_from
        for relationship in project.entity_model.relationships
        if relationship.imported_from is not None
    }
    errors: list[GuardrailError] = []

    for name, mart in sorted(project.marts.marts.items()):
        if mart.requires_evidence != _STRICT:
            continue
        measures = ", ".join(repr(measure) for measure in sorted(mart.measures)) or "(none)"
        for column, bases, names in _weak_columns(name, draft, imported):
            # One leaf per weak column, naming the measures it carries, rather
            # than one per (measure, column) pair. The fact is about the column;
            # repeating it per measure makes a three-measure mart print the same
            # sentence three times, and a refusal a reader skims is one they
            # work around.
            msg = (
                IMPORTED_MESSAGE.format(
                    mart=repr(name),
                    measures=measures,
                    column=repr(column),
                    relationships=", ".join(repr(via) for via in names),
                    artifacts=", ".join(repr(imported[via]) for via in names),
                )
                if names
                else MESSAGE.format(
                    mart=repr(name), measures=measures, column=repr(column), bases=bases
                )
            )
            errors.append(
                InsufficientEvidence(msg, source_path=f"marts: marts.{name}.requires_evidence")
            )

    return errors
