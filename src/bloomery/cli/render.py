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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bloomery import Plan, Resolution

__all__ = [
    "render_plan",
    "render_resolution",
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


def render_resolution(resolution: Resolution) -> str:
    """``bloomery resolve``'s human output: what is computable, and what is
    missing for what is not.

    The unreachable half is the point of the command (RFC 0020 §5.2) — "which
    specific leaf is missing" is the question that otherwise needs a script.
    """
    lines = [f"Reachable ({len(resolution.reachable_metrics)})"]
    lines.extend(_table([(name,) for name in resolution.reachable_metrics]))
    lines.append("")
    lines.append(f"Unreachable ({len(resolution.unreachable_metrics)})")
    lines.extend(
        _table(
            [
                (metric.name, "missing: " + ", ".join(metric.missing))
                for metric in resolution.unreachable_metrics
            ]
        )
    )
    return "\n".join(lines)


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
