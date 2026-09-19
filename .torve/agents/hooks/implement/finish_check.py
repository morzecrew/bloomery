#!/usr/bin/env python3
"""A finishing check that can pass, carrying its own ceiling (S-0066/D-6).

A Stop hook: when the attempt says it is done, ask the worktree three
questions it can actually answer — do the contract's acceptance commands
pass, does the log still owe an entry for a LOCKED row the diff touches, and
has the spec projection drifted — and block the stop with the answer
attached.

The acceptance commands are run here, on the attempt's behalf, and reach it
only when they fail (S-0077/D-1): an attempt that would otherwise run the
suite to see green does not need to, because green is the condition of being
allowed to stop. The same block names the governed rows the diff touches
with no entry against them (S-0077/D-2), over the diff the battery will
read rather than over the working tree's status, so the attempt writes the
entries instead of polling for them. Both are reverted if attempts per
landing rises, whatever happens to the turn count they were meant to remove
(S-0077/D-3).

The ceiling is the point. A condition the model cannot clear (drift outside
its scope, say) would otherwise re-fire every turn until the turn budget
died; one block is on offer and then the check is done talking, because the
gate, not the hook, is what decides the attempt. One block therefore carries
every finding at once — a block spent on the log alone would leave the
acceptance unrun for the rest of the attempt.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

CEILING = 1
"""Blocks this check may ever hand out. One: the stop it blocks plus the
stop that passes is two turns, which is what an unattended night spends on a
hook that was wrong — not a turn budget."""

ACCEPTANCE_TIMEOUT = 1800
"""Seconds one acceptance command may take before the check stops waiting.
A command that never returns is not a finding this hook can report: the
battery runs the same command outside the session and stays the judge."""

ACCEPTANCE_TAIL = 3000
"""Characters of a failing command's output that reach the attempt. The end
is where the verdict is — the summary line and the failures above it — so
what a noisy command loses is its head."""


def acceptance_commands(contract: Path) -> list[str]:
    """The contract's acceptance commands, read from the projected file.

    Read line-wise, the way the write-time guard reads the scope block: no
    YAML library is on this side of the seam, and the projection writes the
    list in one shape — a top-level `acceptance:` then `- command` lines. A
    file that will not yield that shape yields nothing, and nothing to run
    is a finish with nothing to say.
    """

    try:
        lines = contract.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    commands: list[str] = []
    inside = False

    for line in lines:
        stripped = line.strip()

        if not inside:
            inside = stripped == "acceptance:" and not line[:1].isspace()
            continue

        if stripped.startswith("- "):
            commands.append(stripped[2:].strip().strip("'\""))
        else:
            break  # the next key, or the end of the file: the list is read

    return commands


def failures(root: Path, commands: list[str]) -> list[str]:
    """The acceptance commands that did not pass, each with its output.

    A green command returns nothing, which is the whole point: green is the
    condition of being allowed to stop, not something to read. A command
    that could not be run at all is not a failing one — an inquiry that
    fails is not a finding.
    """

    problems: list[str] = []

    for command in commands:
        try:
            # A shell string is what an acceptance command is: the contract
            # writes pipes and `||` into it, and splitting it would run
            # something the battery will not.
            run = subprocess.run(  # nosec B602
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=root,
                timeout=ACCEPTANCE_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError):
            continue

        if run.returncode == 0:
            continue

        output = (run.stdout + run.stderr).strip()
        tail = output[-ACCEPTANCE_TAIL:]

        if len(tail) < len(output):
            tail = "…\n" + tail

        problems.append(
            f"the acceptance command `{command}` failed — it was run for you, "
            f"so this is what the battery will see:\n{tail}"
        )

    return problems


def _git(root: Path, *args: str) -> str | None:
    """What the git command printed, or None when it could not be run or
    refused — a question git cannot answer is not a finding."""

    try:
        run = subprocess.run(["git", *args], capture_output=True, text=True, cwd=root)
    except OSError:
        return None

    return run.stdout if run.returncode == 0 else None


def touched_paths(root: Path) -> list[str]:
    """The files the battery's diff will carry: everything changed since the
    base the gates resolve — committed or not — plus what is untracked.

    `git status` alone is not that set (S-0077/D-2). An attempt that commits
    its work leaves a clean status and a diff full of governed files, so a
    silence check asked over the status agrees with the gate exactly when it
    does not matter. The base is resolved the way the gate context resolves
    it; with no base at all, uncommitted changes are all a diff could carry.
    """

    merge = next(
        (
            found.strip()
            for base in ("origin/main", "main")
            if (found := _git(root, "merge-base", base, "HEAD"))
        ),
        "",
    )

    if merge:
        changed = (_git(root, "diff", "--name-only", "-M", merge) or "").splitlines()
    else:
        changed = [
            line[3:].split(" -> ")[-1].strip("'\"")
            for line in (_git(root, "status", "--porcelain") or "").splitlines()
            if line[3:].strip()
        ]

    changed += (_git(root, "ls-files", "--others", "--exclude-standard") or "").splitlines()

    return sorted({path for path in changed if path})


def owed_entries(root: Path, task_id: str, touched: list[str]) -> list[str]:
    """The LOCKED rows those files are governed by with no entry citing them,
    each as the engine states it, and how to write them (S-0077/D-2).

    The set is the one `decisions-reported` convicts on, so the attempt has
    no reason to ask for it again — which is the round trip this replaces.
    """

    if not touched:
        return []

    args = ["uv", "run", "torve", "log", "owed", task_id, "--format", "json"]
    args += [one for path in touched for one in ("--touched", path)]

    try:
        run = subprocess.run(args, capture_output=True, text=True, cwd=root)
    except OSError:
        return []

    if run.returncode != 0:
        return []

    try:
        rows = [str(one) for one in json.loads(run.stdout)["owed"]]
    except (ValueError, KeyError, TypeError):  # an unparseable answer is no answer
        return []

    if not rows:
        return []

    howto = (
        f"write them in one `uv run torve log divergence {task_id} …` call, one "
        "--decision/--grade/--kind/--class/--claim/--evidence/--action row each; "
        "that is every entry owed, so there is nothing left to ask for"
    )

    return [f"the log owes an entry — {row}" for row in rows] + [howto]


def drifted_files(root: Path) -> list[str]:
    """The projected files the corpus check says have drifted, worktree-relative,
    or nothing when the check could not be asked."""

    try:
        run = subprocess.run(
            ["uv", "run", "torve", "spec", "project", "--check", "--format", "json"],
            capture_output=True,
            text=True,
            cwd=root,
        )
    except OSError:
        return []

    try:
        return [str(rel) for rel in json.loads(run.stdout)["drifted"]]
    except (ValueError, KeyError, TypeError):  # an unparseable answer is no answer
        return []


def drift_owed(contract: Path, drifted: list[str]) -> list[str]:
    """The drift this attempt can be asked to fix: the projected files inside
    the contract's scope, and no others.

    Drift is a fact about the base as often as about the attempt — seven
    acceptances landed on bloomery without the projection being re-run, and
    every attempt cut from that base was told to project thirty directories
    it could not write (`operator/finish-hook-convicts-base-drift`). The
    scope is what the attempt may write, so it is also the extent of what
    this check may owe it; drift outside it is the base's, and the gate that
    reads the projection stays the judge of that.
    """

    if not drifted:
        return []

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import scope_guard  # the sibling hook's reading of the contract's globs

    allow = scope_guard.allow_patterns(contract)
    deny = scope_guard.deny_patterns(contract)
    owed = [rel for rel in drifted if scope_guard.is_allowed(rel, allow, deny)]

    if not owed:
        return []

    return [
        "the spec projection has drifted inside this contract's scope — run "
        "`uv run torve spec project` and commit what it writes: " + ", ".join(owed)
    ]


def question() -> list[str]:
    """What the attempt still owes, as of this stop, or nothing if asked
    and clean. None when the check itself could not run — an inquiry that
    fails is not a finding, and a hook must not convict on its own outage."""

    root = Path.cwd()
    # Assembled part-wise, the way the runner assembles its own: a committed
    # file that named the engine's runtime path in one literal is the
    # dependency the layout ledger exists to catch.
    contracts = sorted((root / ".torve" / "tasks").glob("*/contract.yaml"))

    if len(contracts) != 1:
        return []

    task_id = contracts[0].parent.name
    problems: list[str] = failures(root, acceptance_commands(contracts[0]))

    problems += owed_entries(root, task_id, touched_paths(root))
    problems += drift_owed(contracts[0], drifted_files(root))

    return problems


def main() -> int:
    counter = Path(f"/tmp/torve-finish-blocked-{Path.cwd().name}")

    try:
        count = int(counter.read_text().strip())
    except (OSError, ValueError):
        count = 0

    if count >= CEILING:
        return 0  # the ceiling is spent; the gate decides from here

    problems = question()

    if not problems:
        return 0

    counter.write_text(str(count + 1))
    # One finding per line: a failing command brings its own output with it,
    # and joining those inline would bury the short findings in it.
    sys.stdout.write(json.dumps({"decision": "block", "reason": "\n".join(problems)}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
