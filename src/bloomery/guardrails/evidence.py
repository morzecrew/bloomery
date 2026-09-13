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
    from bloomery.spec.exposures import Exposure
    from bloomery.spec.project import Project

# ----------------------- #

__all__ = [
    "EXPOSURE_IMPORTED_MESSAGE",
    "EXPOSURE_MESSAGE",
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

#: The exposure form of :data:`MESSAGE` (RFC 0065 §5.2). An exposure has no
#: facts of its own, so the sentence names **what it reads** rather than the
#: exposure's own measures, and §6 requires the metric to be named where a
#: metric is how the mart was reached — "names the metric rather than the
#: exposure" is about locating the weak thing, not about omitting the consumer
#: that is refusing.
#:
#: A fourth flat constant rather than a consumer noun templated into
#: :data:`MESSAGE`. `test_the_documented_evidence_refusal_quotes_the_template`
#: reads literal segments out of these values and asserts the page still
#: contains them; a placeholder in the opening clause would leave the guard
#: quoting a template with a hole where the noun goes, which stops it pinning
#: the sentence a reader actually sees (logs/T-0054.md).
EXPOSURE_MESSAGE = (
    "exposure {exposure} requires 'locked'; it reads mart {mart}{via}, whose column "
    "{column} the compiler reached by {bases} rather than from anything an author wrote "
    "(RFC 0065 §5.1). Fix: declare the relationship that carries {column}, or set "
    "'requires_evidence: assumed' on this exposure"
)

#: The exposure form of :data:`IMPORTED_MESSAGE`, splitting on the same fact
#: and for the same reason: the relationship *is* declared, by an importer, so
#: telling this author to declare it is advice they cannot act on (RFC 0065 D4).
EXPOSURE_IMPORTED_MESSAGE = (
    "exposure {exposure} requires 'locked'; it reads mart {mart}{via}, whose column "
    "{column} comes in through {relationships} — read out of {artifacts} rather than written "
    "here (RFC 0070 D1). Fix: author the relationship in this project and drop its "
    "'imported_from:', or set 'requires_evidence: assumed' on this exposure"
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


def _reads(exposure: Exposure, draft: ProjectIR) -> dict[str, tuple[str, ...]]:
    """Every mart an exposure's requirement reaches, keyed by mart name, valued
    by the metrics that reached it — empty where the exposure named the mart.

    An exposure has no facts of its own — it is a name, a kind, an owner and a
    list of things it reads — so its requirement is answered entirely by the
    marts beneath it (§5.2). A named **mart** reaches itself. A named
    **metric** reaches *every* mart carrying it as a measure.

    **Every mart, not the one ``measure_owners`` would pick.** That function
    answers "where is this measure emitted", and the question here is whether
    the number a dashboard reads can rest on something nobody wrote down. The
    planner selects a covering mart at request time and need not select the
    cheapest one, so a guarantee that held only for the emitter's choice would
    not hold for the read it is about.

    This is deliberately a **different quantifier** from :func:`weak_bases`,
    where one fully-`LOCKED` route acquits a column. A route is an alternative
    *proof* of one fact, so the strongest wins; a mart is a runtime *selection*
    among relations, so the weakest governs. The two are not inconsistent —
    they quantify over different things (logs/T-0054.md).

    The value is the metrics rather than a rendered phrase because the mart is
    named once by the message and the metrics are what §6 asks it to add: an
    exposure naming both a mart and a metric on it reaches it twice, and
    saying so twice repeats the mart name in one sentence.

    A name absent from the draft is **not** filtered here, deliberately. It
    would be dead code: :func:`_weak_columns` already returns nothing for a
    mart it cannot find, with the reason written there — a dangling name is
    :func:`~bloomery.guardrails.exposures.check_exposure_targets`'s refusal and
    a mart that failed to flatten is a violation in this same batch, so either
    way the author is already being told. A filter here would be a second guard
    no test could distinguish from its absence (sabotage sweep, T-0054).
    """

    reads: dict[str, set[str]] = {}

    for name in exposure.depends_on.marts:
        # Named directly, so no metric explains it. The empty set is the value,
        # not a missing key: the key is what puts the mart in scope.
        reads.setdefault(name, set())

    for metric in exposure.depends_on.metrics:
        for mart in draft.marts:
            if metric in mart.measures:
                reads.setdefault(mart.name, set()).add(metric)

    return {name: tuple(sorted(metrics)) for name, metrics in sorted(reads.items())}


# ....................... #


def check_evidence(project: Project, draft: ProjectIR) -> list[GuardrailError]:
    """Refuse a `locked` consumer reading a measure on a weaker premise (D4).

    Two consumers, one rule. A **mart** carries the requirement for the columns
    it flattens; an **exposure** carries it transitively for the marts it names
    and for every mart carrying a metric it names (§5.2).

    Over the **authored** documents for the requirement and the draft for the
    facts: the key is a spec assertion and never enters :class:`MartIR` or any
    exposure IR — there is none — since ``project_fingerprint`` walks that tree
    and a field there would move every fingerprint in the corpus for projects
    that never type the key (D3, row 17).

    Every violation is collected rather than the first, so a project sees the
    whole of what its requirement costs in one run — a requirement met one
    refusal per compile is one a team deletes.
    """

    # Read once, before either walk: one pass of the authored spec, so a
    # project cannot be strict about a relationship the same function decided
    # was authored (logs/T-0053.md). Independent of `marts`, because the
    # exposure walk needs it too.
    imported = {
        relationship.name: relationship.imported_from
        for relationship in project.entity_model.relationships
        if relationship.imported_from is not None
    }
    errors: list[GuardrailError] = []
    strict_marts: set[str] = set()

    if project.marts is not None:
        for name, mart in sorted(project.marts.marts.items()):
            if mart.requires_evidence != _STRICT:
                continue
            strict_marts.add(name)
            measures = ", ".join(repr(measure) for measure in sorted(mart.measures)) or "(none)"
            for column, bases, names in _weak_columns(name, draft, imported):
                # One leaf per weak column, naming the measures it carries,
                # rather than one per (measure, column) pair. The fact is about
                # the column; repeating it per measure makes a three-measure
                # mart print the same sentence three times, and a refusal a
                # reader skims is one they work around.
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
                        mart=repr(name),
                        measures=measures,
                        column=repr(column),
                        bases=bases,
                    )
                )
                errors.append(
                    InsufficientEvidence(msg, source_path=f"marts: marts.{name}.requires_evidence")
                )

    if project.exposures is None:
        return errors

    for name, exposure in sorted(project.exposures.exposures.items()):
        if exposure.requires_evidence != _STRICT:
            continue
        for mart_name, metrics in _reads(exposure, draft).items():
            if mart_name in strict_marts:
                # The mart's own requirement refuses the identical column set
                # two loops up, with the identical repair. Reporting it again
                # under the exposure's heading is one problem printed twice,
                # which is how a batch stops being read (D4, logs/T-0054.md).
                # Nothing goes unreported: `locked` is the only requirement
                # that asks anything, so a mart in this set asked for exactly
                # what the exposure did and its walk covered exactly these
                # columns. The skip is a duplicate suppressed, never a weaker
                # requirement standing in for a stronger one.
                continue
            # §6: name the metric. A parenthetical rather than a clause, so
            # the "whose column" that follows still attaches to the mart — as a
            # trailing clause it read as the *metric's* column, which is not a
            # thing (the column is the mart's).
            via = (
                f" (carrying metric {', '.join(repr(metric) for metric in metrics)})"
                if metrics
                else ""
            )
            for column, bases, names in _weak_columns(mart_name, draft, imported):
                msg = (
                    EXPOSURE_IMPORTED_MESSAGE.format(
                        exposure=repr(name),
                        mart=repr(mart_name),
                        via=via,
                        column=repr(column),
                        relationships=", ".join(repr(step) for step in names),
                        artifacts=", ".join(repr(imported[step]) for step in names),
                    )
                    if names
                    else EXPOSURE_MESSAGE.format(
                        exposure=repr(name),
                        mart=repr(mart_name),
                        via=via,
                        column=repr(column),
                        bases=bases,
                    )
                )
                errors.append(
                    InsufficientEvidence(
                        msg, source_path=f"exposures: exposures.{name}.requires_evidence"
                    )
                )

    return errors
