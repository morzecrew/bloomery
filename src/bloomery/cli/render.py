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
from typing import TYPE_CHECKING

# At run time because :func:`render_evidence` compares against ``COMPLETE``:
# the stage decides whether the counts below it are totals or a prefix, which
# is the one thing this module must not get wrong (RFC 0022 D5).
from bloomery import Direction, Stage

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bloomery import Lineage, OpenDecision, Plan, SpecEvidence, UnreachableMetric
    from bloomery.errors import BloomeryError

# ----------------------- #

__all__ = [
    "render_evidence",
    "render_lineage",
    "render_plan",
]


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

    return "\n".join(lines)


# ....................... #


def render_lineage(walk: Lineage) -> str:
    """``bloomery lineage``'s human output: a deterministic **edge list**.

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
    heading = f"{walk.root.name}  ({walk.direction.value})"

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
        *_table([(edge.src.name, f"--{edge.label}-->", edge.dst.name) for edge in walk.edges]),
    ]

    if walk.truncated:
        lines.append("")
        lines.append("  truncated: --max-depth stopped the walk; there is more beyond this")

    return "\n".join(lines)
