#!/usr/bin/env python3
"""Refuse a write outside the contract's scope, before the bytes land (S-0066/D-5).

A PreToolUse hook: claude hands the tool call on stdin, this reads the one
task contract the worktree carries, and a `Write`/`Edit` aimed outside every
`scope.allow` glob, or inside a `scope.deny` glob, is refused with the reason.
Deny wins over allow and an empty allow is unconstrained — the scope gate's
own reading (S-0002), so the hook never refuses what the gate would pass.

Three rules admit a write beyond the declared globs, the same three the scope
gate admits (S-0104): a contingent path the planner named (D-1), a file the
manifest's `scope.derived` map pairs with an in-scope source (D-5), and a
managed `AGENTS.md` beside a path in scope (D-6). The hook decides no outcome
— the battery stays the judge and convicts on the diff either way; this only
moves the same answer to before the file is written, so the attempt spends a
turn redirecting instead of a run red-lining.

Deliberately forgiving on its own failures: no contract, no payload, a shape
it cannot read — each passes. A hook that misfires by blocking turns the
unsatisfiable into a stop-loss it cannot arm, and the gate behind it loses
nothing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import globs  # the sibling copy of the engine's reading of a scope glob (D-3)

# Tool calls that name a single target file. Anything else (Bash included) is
# not a declared write and this hook has no claim on it.
PATH_KEYS = ("file_path", "notebook_path")

# The managed projection beside a directory's code (S-0054/D-7); allowed
# beside any path in scope (S-0104/D-6).
AGENTS_FILE = "AGENTS.md"

# The lock files a manifest's change rewrites, by manifest (S-0104/D-5): the
# default `scope.derived` map the scope gate applies when the manifest names
# none. This side of the seam carries its own copy — no YAML library and no
# import of the engine is available here — so the two tables must agree.
DEFAULT_DERIVED: dict[str, list[str]] = {
    "pyproject.toml": ["uv.lock", "poetry.lock", "pdm.lock"],
    "Pipfile": ["Pipfile.lock"],
    "package.json": ["package-lock.json", "pnpm-lock.yaml", "yarn.lock"],
    "Cargo.toml": ["Cargo.lock"],
    "go.mod": ["go.sum"],
}


def scope_patterns(contract: Path, key: str) -> list[str]:
    """The `scope.<key>` globs, read from the projected contract.

    The projection writes each block in one shape — `allow:` (or `deny:`,
    `contingent:`) then `- glob` lines until the next key — so it is read
    line-wise; no YAML library is on this side of the seam. A file that will
    not yield that shape yields nothing, and an inline `deny: []` is no block
    at all.
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
            inside = stripped == f"{key}:" and line[:1].isspace()
            continue

        if stripped.startswith("- "):
            patterns.append(stripped[2:].strip().strip("'\""))
        else:
            break  # the next key or the end of the block: the list is read

    return patterns


def allow_patterns(contract: Path) -> list[str]:
    return scope_patterns(contract, "allow")


def deny_patterns(contract: Path) -> list[str]:
    return scope_patterns(contract, "deny")


def contingent_patterns(contract: Path) -> list[str]:
    return scope_patterns(contract, "contingent")


def derived_map(root: Path) -> dict[str, list[str]]:
    """The manifest's `scope.derived` map (S-0104/D-5), read line-wise.

    The map names files that ride with a source, in both directions. Read the
    same way the contract's scope is: `derived:` then `source:` keys with
    `- rider` lines, until a line that is neither. A manifest that names no
    `derived:` block — or one the hook cannot read — yields the default lock
    table the scope gate applies, so the hook never refuses what the gate
    would pass.
    """

    try:
        lines = (root / ".torve" / "gates.yaml").read_text(encoding="utf-8").splitlines()
    except OSError:
        return dict(DEFAULT_DERIVED)

    found: dict[str, list[str]] = {}
    source: str | None = None
    inside = False

    for line in lines:
        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            continue

        if not inside:
            inside = stripped == "derived:"
            continue

        if stripped.startswith("- "):
            if source is not None:
                found.setdefault(source, []).append(stripped[2:].strip().strip("'\""))
            continue

        if stripped.endswith(":") and line[:1].isspace():
            source = stripped[:-1].strip().strip("'\"")
            continue

        break  # a line that is neither a source nor a rider: the block ended

    return found if inside else dict(DEFAULT_DERIVED)


def _static_prefix(pattern: str) -> str:
    """The directory part of *pattern* before its first wildcard."""

    kept: list[str] = []

    for part in pattern.split("/")[:-1]:
        if any(char in part for char in "*?["):
            break

        kept.append(part)

    return "/".join(kept)


def _beside_scoped(rel: str, patterns: list[str]) -> bool:
    """Whether *rel* is the managed `AGENTS.md` of a directory an allow glob
    reaches (S-0104/D-6): the projection sits beside the code it governs."""

    if rel.rsplit("/", 1)[-1] != AGENTS_FILE:
        return False

    where = rel[: -len(AGENTS_FILE)].rstrip("/")

    for pattern in patterns:
        prefix = _static_prefix(pattern)

        if where == prefix or (prefix and where.startswith(prefix + "/")):
            return True

    return False


def is_allowed(
    rel: str,
    patterns: list[str],
    deny: list[str] | tuple[str, ...] = (),
    contingent: list[str] | tuple[str, ...] = (),
) -> bool:
    """Whether one worktree-relative path may be written: not inside any deny
    glob, and inside some allow or contingent glob — or any path at all when
    no allow glob is declared, which is what an empty allow means to the
    scope gate.

    Beyond the globs, a managed `AGENTS.md` beside a scoped directory passes
    too (S-0104/D-6). The globs are read through the sibling copy of the
    engine's reading (D-3): gitignore's semantics, the same ones the scope
    gate itself applies, so the two never disagree about a path.
    """

    if globs.matches(rel, deny):
        return False

    if globs.matches(rel, contingent):
        return True

    if not patterns or globs.matches(rel, patterns):
        return True

    return _beside_scoped(rel, patterns)


def refusal(
    target: str,
    patterns: list[str],
    deny: list[str] | tuple[str, ...] = (),
    contingent: list[str] | tuple[str, ...] = (),
) -> str:
    if globs.matches(target, deny):
        return (
            f"refused: {target} is inside this task's scope.deny ({', '.join(deny)}). "
            "The scope gate will convict on it. Work outside the denied paths, "
            "or say in your reply why the task cannot be done without one."
        )

    listed = ", ".join([*patterns, *contingent]) if patterns or contingent else "(unconstrained)"

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
    deny = deny_patterns(contracts[0])
    contingent = contingent_patterns(contracts[0])

    # S-0104/D-5: a derived file rides with its source, both directions. Fold
    # the hits into the contingent list so one predicate decides.
    for source, riders in derived_map(root).items():
        if is_allowed(source, patterns, deny, contingent):
            contingent = [*contingent, *riders]

        if any(is_allowed(rider, patterns, deny, contingent) for rider in riders):
            contingent = [*contingent, source]

    try:
        rel = str(Path(target).resolve().relative_to(root))
    except (ValueError, OSError):
        rel = ""  # outside the worktree entirely: never allowed

    if rel and is_allowed(rel, patterns, deny, contingent):
        return 0

    sys.stderr.write(refusal(rel or target, patterns, deny, contingent) + "\n")
    return 2  # exit 2 feeds the reason back to the model and blocks the call


if __name__ == "__main__":
    sys.exit(main())
