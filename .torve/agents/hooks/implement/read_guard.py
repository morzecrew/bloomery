#!/usr/bin/env python3
"""Answer a large out-of-scope read with the file's shape instead of its bytes.

A PreToolUse hook on `Read`, beside the write guard that shares this directory.
Measured on T-0407: seven calls carried 70% of an attempt's orientation bytes,
and the worst of them read `harness.py` — a file outside the contract's scope —
four times over for 36,772 bytes, plus `ledger.py` whole at 26,554. A byte that
lands at request *r* is re-sent on every request after it, so those reads were
paid some sixty times each.

The prompt already advises reading in ranges (S-0076/D-4) and the same attempt
ignored it, which is the difference this file exists to exercise: advice the
model may route around, against a mechanism at the boundary it cannot. The
model is not refused an answer — it is handed the outline the pack already
built, which is what a whole-file read was being used to obtain.

Deliberately forgiving, like its neighbour: no contract, no pack, a file it
cannot size, anything in scope, anything small — each passes untouched. A hook
that misfires by blocking costs an attempt its turn for nothing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scope_guard import allow_patterns, deny_patterns, is_allowed

# Below this a whole file is cheaper than the round trip that would replace it.
# 8,000 bytes is roughly the threshold dsh's own result pruner uses (8,192),
# reached independently: it is about where one result stops being a fact and
# starts being a document.
LARGE = 8_000
# What the pack's symbol index spells, one line per definition: `path:line what`.
SYMBOLS = Path(".torve") / "context" / "symbols.txt"
# An outline is an answer, not a second document: `harness.py` alone defines
# eighty-four names, and a reply that long is the thing being refused wearing a
# different hat. Past this the tail is counted rather than listed.
ROWS = 48


def outline(rel: str) -> list[str]:
    """The definitions the pack already recorded for one path."""

    try:
        lines = SYMBOLS.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    return [line for line in lines if line.startswith(f"{rel}:")]


def answer(rel: str, size: int, rows: list[str]) -> str:
    head = (
        f"not read: {rel} is outside this task's scope and is {size:,} bytes, which "
        f"would be re-sent on every request for the rest of this attempt."
    )

    if not rows:
        return (
            f"{head} Read the part you need instead — `sed -n 'A,Bp' {rel}` — "
            "or grep it for the name you are after."
        )

    shown = rows[:ROWS]
    rest = len(rows) - len(shown)

    return "\n".join(
        [
            f"{head} Its shape, from the pack's symbol index:",
            "",
            *shown,
            *([f"... and {rest} more definitions; grep the file for one."] if rest else []),
            "",
            (
                f"Read the range you need with `sed -n 'A,Bp' {rel}`, or grep it. The "
                "whole file is available that way; this only refuses it in one piece."
            ),
        ]
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    target = (payload.get("tool_input") or {}).get("file_path") or ""

    if not target:
        return 0

    # A ranged read is the shape being asked for; never refuse one.
    if any(key in (payload.get("tool_input") or {}) for key in ("offset", "limit")):
        return 0

    root = Path.cwd()
    contracts = sorted((root / ".torve" / "tasks").glob("*/contract.yaml"))

    if len(contracts) != 1:
        return 0

    try:
        path = Path(target).resolve()
        rel = str(path.relative_to(root))
        size = path.stat().st_size
    except (ValueError, OSError):
        return 0

    if size < LARGE or is_allowed(rel, allow_patterns(contracts[0]), deny_patterns(contracts[0])):
        return 0

    sys.stderr.write(answer(rel, size, outline(rel)) + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
