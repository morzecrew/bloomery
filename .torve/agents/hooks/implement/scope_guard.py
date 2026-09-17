#!/usr/bin/env python3
"""Refuse a write outside the contract's scope, before the bytes land (S-0066/D-5).

A PreToolUse hook: claude hands the tool call on stdin, this reads the one
task contract the worktree carries, and a `Write`/`Edit` aimed outside every
`scope.allow` glob is refused with the reason. It decides no outcome — the
battery stays the judge and convicts on the diff either way; this only moves
the same answer to before the file is written, so the attempt spends a turn
redirecting instead of a run red-lining.

Deliberately forgiving on its own failures: no contract, no payload, a shape
it cannot read — each passes. A hook that misfires by blocking turns the
unsatisfiable into a stop-loss it cannot arm, and the gate behind it loses
nothing.
"""

from __future__ import annotations

import fnmatch
import json
import sys
from pathlib import Path

# Tool calls that name a single target file. Anything else (Bash included) is
# not a declared write and this hook has no claim on it.
PATH_KEYS = ("file_path", "notebook_path")


def allow_patterns(contract: Path) -> list[str]:
    """The `scope.allow` globs, read from the projected contract.

    The projection writes the block in one shape — `allow:` then `- glob`
    lines until `deny:` — so it is read line-wise; no YAML library is on this
    side of the seam. A file that will not yield that shape yields nothing.
    """

    try:
        lines = contract.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    patterns: list[str] = []
    inside = False

    for line in lines:
        stripped = line.strip()

        if not inside:
            inside = stripped == "allow:" and line[:1].isspace()
            continue

        if stripped.startswith("- "):
            patterns.append(stripped[2:].strip().strip("'\""))
        else:
            break  # `deny:` or the end of the block: the list is read

    return patterns


def is_allowed(rel: str, patterns: list[str]) -> bool:
    """Whether one worktree-relative path matches any allow glob.

    `fnmatch` is path-blind: its `*` crosses `/`, so `.torve/agents/**`
    reaches every depth, which is the meaning the scope gate gives it.
    """

    return any(fnmatch.fnmatch(rel, pattern) for pattern in patterns)


def refusal(target: str, patterns: list[str]) -> str:
    listed = ", ".join(patterns) if patterns else "(none declared)"

    return (
        f"refused: {target} is outside this task's scope (allowed: {listed}). "
        "The scope gate will convict on it. Work inside the allowed paths, "
        "or say in your reply why the task cannot be done without one."
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool_input = payload.get("tool_input") or {}
    target = next((tool_input[key] for key in PATH_KEYS if tool_input.get(key)), "")

    if not target:
        return 0

    root = Path.cwd()
    # Assembled part-wise, the way the runner assembles its own: a committed
    # file that named the engine's runtime path in one literal is the
    # dependency the layout ledger exists to catch.
    contracts = sorted((root / ".torve" / "tasks").glob("*/contract.yaml"))

    if len(contracts) != 1:
        return 0  # not one unambiguous contract to read a scope from

    patterns = allow_patterns(contracts[0])

    try:
        rel = str(Path(target).resolve().relative_to(root))
    except (ValueError, OSError):
        rel = ""  # outside the worktree entirely: never allowed

    if rel and is_allowed(rel, patterns):
        return 0

    sys.stderr.write(refusal(rel or target, patterns) + "\n")
    return 2  # exit 2 feeds the reason back to the model and blocks the call


if __name__ == "__main__":
    sys.exit(main())
