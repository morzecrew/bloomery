"""Human-readable output for the command line (RFC 0020 §5.2, D6).

Hand-rolled, because the alternative is a runtime dependency on ``rich`` or
``tabulate`` for cosmetics in a library whose dependency discipline is one of
its properties. Two columns aligned on the widest cell is the whole
requirement, and it is eleven lines.

Nothing here decides anything: every function takes a value the public API
returned and turns it into text. The machine-readable rendering of the same
values lives in :mod:`bloomery.cli.serialize`, so the two never argue about
what a plan *is* — one formats, the other converts.
"""

from __future__ import annotations

import textwrap
from collections import Counter
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

# At run time because :func:`render_evidence` compares against ``COMPLETE``:
# the stage decides whether the counts below it are totals or a prefix, which
# is the one thing this module must not get wrong (RFC 0022 D5).
from bloomery import Direction, EvidenceGrade, Stage

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from bloomery import (
        Lineage,
        OpenDecision,
        Plan,
        SemanticPlan,
        SpecEvidence,
        Timeline,
        UnreachableMetric,
    )
    from bloomery.errors import BloomeryError

# ----------------------- #

__all__ = [
    "render_check",
    "render_evidence",
    "render_evidence_grades",
    "render_lineage",
    "render_plan",
    "render_timeline",
]

#: A project that adopted no `id:` has no label to print, and every lookup
#: falls through to the node id — which is then the name (RFC 0062 D3).
_NO_LABELS: Final[Mapping[str, str]] = MappingProxyType({})


def _table(rows: Sequence[tuple[str, ...]], *, indent: str = "  ") -> list[str]:
    """Rows padded to the widest cell per column, last column unpadded.

    Unpadded because trailing whitespace on the last column is invisible in a
    terminal and very visible in a diff of captured output.
    """

    if not rows:
        return []

    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    lines: list[str] = []

    for row in rows:
        cells = [cell.ljust(widths[index]) for index, cell in enumerate(row[:-1])]
        lines.append((indent + "  ".join([*cells, row[-1]])).rstrip())

    return lines


# ....................... #


#: The surfaces ``bloomery check`` reports, in the order §3 lists them and with
#: the sentence each line makes. A tuple rather than a chain of ``lines.append``
#: so the set is one readable thing: D5 calls the *set* the adjustable half of
#: the decision, and a category added or dropped should be a one-line diff here
#: rather than an edit spread through a renderer.
CHECKED_SURFACES: tuple[tuple[str, str], ...] = (
    ("entities", "resolved"),
    ("relationships", "checked"),
    ("measures", "type-check"),
    ("marts", "checked"),
    ("rollups", "proven"),
    ("conversions", "proven"),
    ("temporal_joins", "anchored"),
)
#: Rollups are ``proven`` where marts are ``checked``, and the difference is
#: real rather than decorative: a mart's leaves say a flatten step resolved and
#: a grain matched, while a rollup reaches the IR only if R013 produced a
#: derivation for every measure it carries (RFC 0058 D5). One is the absence of
#: a violation, the other is a positive proof, and this collection has spent
#: four RFCs on that distinction.
#:
#: Marts are ``checked`` and not ``safe``, which is §3's word. A guardrail
#: refusal is reported over the draft IR the stage was handed, so a project
#: refused for a reason that has nothing to do with its marts prints its mart
#: count beside that refusal, and the stage never finished ruling on them.
#: Every other verb here names a stage that completed before the count was
#: taken; ``safe`` would name a verdict nothing reached.


def render_evidence_grades(plan: SemanticPlan) -> str:
    """The facts a plan rests on, each with the grade a consumer reads
    (RFC 0065 P1).

    **Visible before it is enforced**, which is the whole of P1: no requirement
    exists yet and nothing is refused, so the only thing this can do is let a
    team see how much of its semantics somebody wrote down and how much the
    compiler defaulted — §12's "useful number nobody currently has".

    The tally is a count per grade and never a ratio, a score or an average
    (§4). Counting how many facts are declared answers a question; dividing it
    by the total invents a number that reads as a quality measure of a project,
    which is the thing this design refuses to be.

    Facts are deduplicated across the plan's proofs, and the honest statement is
    that no plan in the fixture corpus currently produces a duplicate: a
    cross-mart request yields three proofs and four distinct leaves. The dedup
    is here because ``Proof.leaves`` already applies it *within* a proof, so a
    tally that skipped it across proofs would count one fact as two the first
    time two nodes rested on the same premise — and a count that can lie about
    how much of a project is declared is worse than no count.
    """

    facts = tuple(sorted({fact for proof in plan.proofs for fact in proof.leaves}))

    if not facts:
        return "Evidence\n  (no facts — this plan carries no proof)"

    tally = Counter(fact.provenance.grade for fact in facts)
    counted = ", ".join(f"{tally[grade]} {grade.value}" for grade in EvidenceGrade if tally[grade])
    lines = [f"Evidence ({counted})"]

    for fact in facts:
        lines.append(f"  {fact.provenance.grade.value.upper():<8}{fact.source}")
        lines.extend(
            textwrap.wrap(
                fact.statement, width=WRAP, initial_indent=" " * 10, subsequent_indent=" " * 10
            )
        )

    return "\n".join(lines)


# ....................... #


def render_check(evidence: SpecEvidence) -> str:
    """``bloomery check``'s human output: what was checked, and what refused.

    A summary, where :func:`render_evidence` is a worklist. The two read the
    same value and answer different questions — "is what this project declares
    sound" against "which metrics can I compute and what is missing for the
    rest" — which is why the counts here are surfaces and the counts there are
    metric names (RFC 0044 D7, settled in ``logs/T-0030.md``).

    **Whether a refused project prints counts depends on whether one was
    computed, not on whether it was refused.** A pipeline that stopped before
    building an IR has no counts to print, and says they are *unavailable* —
    not that no surface was checked, which is a different claim and a false
    one: the stages that ran checked plenty, and what is missing is the
    arithmetic over an IR nobody built. A zero would read as a checked surface
    holding nothing, which is the misreading
    :attr:`~bloomery.SpecEvidence.checked` is ``None`` rather than zeroed to
    prevent. One that stopped *after* building a draft IR — refused
    two stages later — has counts that are real, and they are printed under
    the stage that says they are a prefix.

    **No total, no percentage, and no "obligations proven" line.** The first
    two would imply coverage nobody proved (D5); the third has no denominator,
    because nothing in a project declares a request to prove one against
    (D8, settled in the same log).
    """

    lines = [f"Stage: {evidence.stage_reached.value}"]

    if evidence.stage_reached is not Stage.COMPLETE:
        lines.append("  analysis stopped here — every count below is a prefix, not a total")

    if evidence.fingerprint is not None:
        lines.append(f"Fingerprint: {evidence.fingerprint}")

    lines.append("")

    if evidence.checked is None:
        lines.append("Checked-surface counts unavailable — no IR was built to count from.")
    else:
        lines.extend(
            _table(
                [
                    (str(getattr(evidence.checked, field)), field.replace("_", " "), verb)
                    for field, verb in CHECKED_SURFACES
                ]
            )
        )

    lines.extend(("", f"{len(evidence.refusals)} refusal(s)"))

    for refusal in evidence.refusals:
        lines.extend(_refusal(refusal))

    return "\n".join(lines)


# ....................... #


def render_evidence(evidence: SpecEvidence) -> str:
    """``bloomery resolve``'s human output: what is computable, what is
    missing for what is not, and what the pipeline refused.

    **The stage comes first, and that is a decision rather than a layout.**
    Every count below it is empty in two different situations that mean
    opposite things — "nothing unreachable" and "reachability was never
    computed" (RFC 0022 D5) — and a reader who skims the numbers without the
    stage draws the wrong one. Printing it first is the loudest this can be
    made; it cannot be made impossible.

    A refused spec still prints its reachability. That is the whole of the
    re-point: before this, `resolve` either printed reachability *or* raised,
    and a spec mid-draft is exactly when an author wants both.

    **Open decisions print here** (RFC 0030 D7, settled in ``logs/T-0007.md``
    D-033). The table already prints one row per unreachable metric; an open
    decision is that same fact with the edit attached, and it is bounded by the
    same set — a decision exists only for a canonical some metric requires. What
    it prints of each option is the id, never the alias slots: see
    :func:`_decision_row`.

    :attr:`~bloomery.SpecEvidence.provenance` is **not** printed, for the reason
    :attr:`~bloomery.SpecEvidence.entities` is not: it is a per-field enumeration
    of what a spec already says, and it is on the value and in ``--format json``
    for the loop that reads it. A worklist is what a person reads; a memory is
    what an agent reads.

    :attr:`~bloomery.SpecEvidence.entities` is deliberately **not** printed, and
    is stated here so a later reader does not read the omission as an oversight.
    The command answers "which metrics are computable, and what is missing for
    the rest"; an entity list is neither reachability nor a refusal, and the
    relations a project declares are what ``bloomery compile`` prints paths for.
    It is on the value and in ``--format json``, which is where the CLI's
    not-a-lossier-surface promise lives (RFC 0020 D4) — the table has always
    been a summary, as ``render_plan`` is of a ``Plan``.
    """
    lines = [f"Stage: {evidence.stage_reached.value}"]

    if evidence.stage_reached is not Stage.COMPLETE:
        lines.append("  analysis stopped here — every count below is a prefix, not a total")

    if evidence.fingerprint is not None:
        lines.append(f"Fingerprint: {evidence.fingerprint}")

    lines.extend(("", f"Reachable ({len(evidence.reachable)})"))
    lines.extend(_table([(name,) for name in evidence.reachable]))
    lines.extend(("", f"Unreachable ({len(evidence.unreachable)})"))
    lines.extend(
        _table(
            [
                (metric.name, "missing: " + ", ".join(metric.missing), _via(metric))
                for metric in evidence.unreachable
            ]
        )
    )

    if evidence.unresolved:
        lines.extend(("", f"Open decisions ({len(evidence.unresolved)})"))
        lines.extend(_table([_decision_row(decision) for decision in evidence.unresolved]))

    if evidence.marts:
        lines.extend(("", f"Marts ({len(evidence.marts)})"))
        lines.extend(_table([(mart.name, f"grain: {mart.grain}") for mart in evidence.marts]))

    if evidence.refusals:
        lines.extend(("", f"Refusals ({len(evidence.refusals)})"))
        for refusal in evidence.refusals:
            lines.extend(_refusal(refusal))

    return "\n".join(lines)


# ....................... #


#: Where a wrapped refusal message breaks. A constant rather than the terminal's
#: width, which would make the same spec render differently in two windows and
#: put a terminal read inside a package whose output is supposed to be a pure
#: function of its input.
WRAP = 88


def _via(metric: UnreachableMetric) -> str:
    """``via: a, b`` — the blocked metrics between this one and its missing
    leaves, or nothing at all when it is blocked on its own.

    An empty third column rather than a second table: a reader scanning the
    unreachable list wants one row per metric, and most rows have no chain.
    """

    return ("via: " + ", ".join(metric.via)) if metric.via else ""


# ....................... #


def _decision_row(decision: OpenDecision) -> tuple[str, ...]:
    """One open decision: what is missing, where the edit goes, what may be
    recorded there (RFC 0030 D7; ``logs/T-0007.md`` D-033).

    **Ids only, and never a recipe's ``requires``.** The alias slots are the
    half of the join that a reader cannot act on from a terminal — they are
    bound in a mapping's ``from:``, against source paths the CLI has not read —
    and printing them is what would turn this from the most actionable line
    ``bloomery resolve`` prints into the dump RFC 0030 D7 weighs it against.
    ``--format json`` carries them, which is where the lossless surface lives
    (RFC 0020 D4).

    The order of the ids is the **catalog's** and is never re-sorted here
    (RFC 0030 D2). It is authored information — recipes are ordered by
    reliability — and a renderer that alphabetized it would be destroying it at
    the last possible moment.
    """
    target = f"{decision.entity}.{decision.field}" if decision.field else decision.entity
    options = ", ".join(option.id for option in decision.options) or "(no recipes)"
    return (
        decision.canonical,
        decision.gap.value,
        target,
        options,
        "blocks: " + ", ".join(decision.blocks),
    )


# ....................... #


def _refusal(refusal: BloomeryError) -> list[str]:
    """One refusal as a source path and its wrapped message.

    Not a table row. Every refusal message is a paragraph by design — the claim,
    why it is wrong, then ``Fix:`` — and RFC 0002's whole argument for that
    shape is that the reader should not have to look anything up. Truncating to
    a column would cut the fix off every one of them, so the path leads and the
    message is wrapped under it.
    """
    head = f"  {refusal.source_path or '(no source path)'}"
    body = textwrap.wrap(
        f"{type(refusal).__name__}: {refusal}",
        width=WRAP,
        initial_indent="    ",
        subsequent_indent="      ",
    )
    return [head, *body]


# ....................... #


def render_plan(plan: Plan) -> str:
    """``bloomery plan``'s human output: every classified change, then scope.

    The breaking count is called out separately because it is the number a
    reader decides on — RFC 0007's expand/contract rule makes the rest
    informational and that one blocking.
    """

    if not plan.has_changes:
        return "No changes."

    lines = [f"Changes ({len(plan.changes)}, {len(plan.breaking)} breaking)"]
    lines.extend(
        _table(
            [(change.change_class.value, change.subject, change.detail) for change in plan.changes]
        )
    )
    lines.append("")
    lines.append("Backfill scope")
    entities = plan.backfill_scope.entities
    lines.extend(_table([(name,) for name in entities]) if entities else ["  (none)"])
    replay = plan.replay_scope.entities

    if replay:
        lines.append("")
        lines.append("Quarantine replay scope")
        lines.extend(_table([(name,) for name in replay]))

    if plan.downstream_impact:
        lines.append("")
        lines.append("Downstream metrics")
        lines.extend(_table([(name,) for name in plan.downstream_impact]))

    cited = [
        (change.subject, ", ".join(change.citations)) for change in plan.changes if change.citations
    ]

    if cited:
        lines.append("")
        # Its own section rather than a wider `detail` column: a rename's
        # citation list is as long as the project makes it, and a table cell
        # that grows with the project takes every other row's alignment with
        # it (RFC 0062 §5.3).
        lines.append("Renamed — what cited the old name")
        lines.extend(_table(cited))

    # Last, because it is the section a reader acts on rather than reads:
    # everything above says what changes, and this says who to tell.
    if plan.affected_exposures:
        lines.append("")
        lines.append("Affected exposures")
        lines.extend(_table([(name,) for name in plan.affected_exposures]))

    return "\n".join(lines)


# ....................... #


def render_lineage(walk: Lineage, labels: Mapping[str, str] = _NO_LABELS) -> str:
    """``bloomery lineage``'s human output: a deterministic **edge list**.

    ``labels`` is :func:`~bloomery.node_labels` for the project walked, and
    every id is printed through it (RFC 0062 §5.4): a reader sees
    ``metric.gross_revenue`` where the project adopted ``id: mtr_7f3a9c``,
    because the name is what a person reads and the id is what a script keys
    on. ``--format json`` carries both, so nothing is lost by not printing it
    here. A project that adopted no id passes an empty map and every lookup
    falls through to the id, which is the name.

    One line per edge, in :attr:`Lineage.edges` order, aligned on the widest
    source. Not a tree — RFC 0031 D1 returns a sub-DAG, and a tree cannot draw
    one: a node reachable two ways is either repeated, which re-creates the
    exponential output D1 exists to avoid, or drawn once with its second edge
    dropped, which loses the fact that two things feed it.

    An empty walk prints the root and says so rather than printing nothing. A
    source column has no upstream and that is an answer, so the reader needs to
    see the question was asked and came back empty — an empty stdout reads as a
    command that failed.

    Every one of these sentences names its direction, so
    :attr:`Direction.BOTH` needs its own pair: a merged walk has two
    directions, and a node with nothing on either side is not "a leaf in that
    direction".

    **Empty and bounded-to-empty are different answers, and each gets its own
    line.** ``--max-depth 0`` on a node that has lineage returns no edges *and*
    sets ``truncated``: calling that a leaf and then adding "there is more
    beyond this" states both halves of a contradiction, and the half a reader
    acts on — "leaf" — is the false one. Only a walk that was not cut may call
    its root a leaf.

    ``truncated`` is stated whenever it is set, because a bounded answer that
    does not say it is bounded is the failure RFC 0022 D5 names.
    """
    heading = f"{labels.get(walk.root.name, walk.root.name)}  ({walk.direction.value})"

    if not walk.edges:
        if walk.direction is Direction.BOTH:
            # "both" is not a direction the other branch's sentences can name:
            # they read "no both lineage" and "this node has both lineage", and
            # the leaf line is false as well as ungrammatical — a merged walk
            # has two directions, so there is no "that direction" to be a leaf in.
            absent = (
                "  no lineage in either direction — nothing feeds this node and"
                " nothing derives from it"
            )
            cut = (
                "  --max-depth stopped the walk before its first edge —"
                " this node has lineage, and none of it is shown"
            )
        else:
            absent = f"  no {walk.direction.value} lineage — this node is a leaf in that direction"
            cut = (
                "  --max-depth stopped the walk before its first edge — this node has"
                f" {walk.direction.value} lineage, and none of it is shown"
            )
        return "\n".join([heading, cut if walk.truncated else absent])

    lines = [
        heading,
        *_table(
            [
                (
                    labels.get(edge.src.name, edge.src.name),
                    f"--{edge.label}-->",
                    labels.get(edge.dst.name, edge.dst.name),
                )
                for edge in walk.edges
            ]
        ),
    ]

    if walk.truncated:
        lines.append("")
        lines.append("  truncated: --max-depth stopped the walk; there is more beyond this")

    return "\n".join(lines)


# ....................... #


def render_timeline(walk: Timeline) -> str:
    """``bloomery timeline``'s human output: the versions, then what moved.

    Two blocks, because the value answers two questions and a reader arrives
    with one of them. **Which versions carried this** is the entries, one line
    each in the order supplied — never sorted, because RFC 0069 D1 says this
    project does not read a label, and sorting them would be reading them.
    **What moved** is the changes, each naming the node it is about.

    The node ids are printed as they arrive. A change already carries the
    *name* spelling of the node it names, and the heading is the spelling the
    reader typed — relabelling that would answer a question they did not ask,
    and there are N versions here, each with its own label map.

    **A timeline with no changes prints that it has none**, for the reason
    :func:`render_lineage` prints an empty walk: "this has not moved since
    March" is the answer a reader came for at least as often as the other, and
    an empty stdout reads as a command that failed. Which of the three reasons
    it has none is stated, because "nothing moved" and "there was nothing to
    compare" are different facts and only one of them is about the node.
    """

    versions = len(walk.entries)
    changes = len(walk.changes)
    present = sum(1 for entry in walk.entries if entry.present)
    counted = (
        f"{versions} version{'' if versions == 1 else 's'},"
        f" {changes} change{'' if changes == 1 else 's'}"
    )
    lines = [f"{walk.node}  ({counted})", ""]

    lines.extend(
        _table([(entry.label, "present" if entry.present else "absent") for entry in walk.entries])
    )

    if not walk.changes:
        lines.append("")
        if present == 0:
            # Absent everywhere is the command's refusal rather than a
            # rendering — but this function is public and a caller can build
            # the value, so it says what it sees rather than claiming nothing
            # moved about a node that was never there.
            lines.append("  this node is in none of these versions")
        elif present == 1:
            lines.append("  one version carries this node — there is nothing to compare it to")
        else:
            lines.append("  no definition change across these versions")
        return "\n".join(lines)

    lines.append("")

    for change in walk.changes:
        lines.append(f"  {change.before} -> {change.after}  {change.node}  ({change.matched_by})")
        lines.extend(
            _table(
                [
                    (
                        delta.facet.value,
                        delta.field,
                        "" if delta.old is None else delta.old,
                        # A facet whose value has no compact spelling — a
                        # filter is a tuple of records — renders as neither
                        # side, and an arrow between two absences points at
                        # nothing. The field name is the answer there, so the
                        # row is the field and stops.
                        "" if delta.old is None and delta.new is None else "->",
                        "" if delta.new is None else delta.new,
                    )
                    for delta in change.facets
                ],
                indent="      ",
            )
        )

    return "\n".join(lines)
