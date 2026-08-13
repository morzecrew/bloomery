"""Compilation is a pure function — enforced structurally, in CI.

RFC 0003 §5.5 and RFC 0001 D6: compiling does no I/O and reads no ambient
state. Inputs are strings, outputs are artifacts, and the same specs produce
byte-identical bytes across processes and hash seeds.

A pre-commit ``pygrep`` hook has banned four spellings under ``src/bloomery/``
since M1. Two things were wrong with it, and this script is the fix for both
(RFC 0019 D6):

* **It was not a CI gate.** ``just quality`` runs the gitleaks hook and no
  other, so ``git commit --no-verify`` — and CI itself — skipped it entirely. A
  guard CI does not run is a convention.
* **Its vocabulary was four spellings.** It never named the *imports* that make
  I/O possible in the first place, so ``import requests`` passed.

This replaces the hook rather than sitting beside it: two guards over one
invariant drift apart, and the one that is quieter wins by default.

It is not a substitute for the behavioural tests. A step could still reach a
clock through an import bloomery does not name, which is why the cross-hash-seed
determinism tests exist. What this moves is the *common* failure — from a test
run to a line number on every pull request.

Run by ``just quality``; exits non-zero with one line per finding.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

#: Top-level modules that make I/O or ambient reads possible. Matched on the
#: import's root, so ``bloomery.dialects.duckdb`` — a dialect module that shares
#: a name with the engine driver — is untouched.
BANNED_IMPORTS = frozenset(
    {
        "boto3",
        "duckdb",
        "httpx",
        "os",
        "pathlib",
        "random",
        "requests",
        "secrets",
        "socket",
        "sqlalchemy",
        "tempfile",
    }
)

#: Dotted call suffixes that read a clock or a random source. Matched on the
#: end of the dotted name, so both ``datetime.now()`` and
#: ``datetime.datetime.now()`` are caught, while a method of one's own called
#: ``.now()`` is not.
BANNED_CALLS = frozenset(
    {
        "datetime.now",
        "datetime.today",
        "datetime.utcnow",
        "time.monotonic",
        "time.perf_counter",
        "time.time",
        "uuid.uuid1",
        "uuid.uuid4",
    }
)

#: Whole modules whose every attribute is nondeterministic. Also banned as
#: imports above — the attribute rule alone misses ``from random import
#: choice``, where the call is spelled ``choice(...)`` and names no module.
BANNED_MODULES_BY_ATTRIBUTE = frozenset({"random", "secrets"})

#: Ambient state read as an attribute rather than called.
BANNED_ATTRIBUTES = frozenset({"os.environ", "os.getenv"})

#: Paths exempt from the import ban, each for a stated reason. Relative to the
#: package root.
#:
#: ``steps/contract.py`` runs at *run time*, inside a generated wrapper in a
#: consumer's warehouse — not during compilation. It imports nothing beyond
#: ``bloomery.errors`` today (RFC 0017), so it passes as written; the entry
#: exists so that a future addition there is a decision someone makes rather
#: than a rule someone slips past.
#: ``cli/io.py`` is the command line's one door to a filesystem (RFC 0020 D5,
#: D12). A command line has to reach a disk; what this entry buys is that
#: exactly one file may, so the tree and the guard say the same thing. The
#: exemption is deliberately *not* ``cli/`` — a package-wide carve-out would
#: let the argument parser or the renderer open a file while the docstring in
#: ``cli/io.py`` still claimed one module did.
ALLOWLIST: dict[str, str] = {
    "cli/io.py": "the CLI's single filesystem door (RFC 0020 D5/D12)",
    "steps/contract.py": "run-time contract assertion, not a compile stage (RFC 0017)",
}


class Finding:
    """One violation, with enough to fix it without opening the file."""

    def __init__(self, path: Path, line: int, message: str) -> None:
        self.path = path
        self.line = line
        self.message = message

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


def dotted(node: ast.expr) -> str:
    """The dotted name of an attribute chain, or ``""`` if it is not one."""
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return ""
    parts.append(current.id)
    return ".".join(reversed(parts))


def import_roots(node: ast.Import | ast.ImportFrom) -> list[str]:
    """The top-level module each import reaches.

    A relative import (``from .foo import bar``) reaches nothing outside the
    package and returns nothing.
    """
    if isinstance(node, ast.Import):
        return [alias.name.split(".", 1)[0] for alias in node.names]
    if node.level:
        return []
    return [node.module.split(".", 1)[0]] if node.module else []


def alias_map(tree: ast.Module) -> dict[str, str]:
    """Local name → the dotted path it actually names.

    Without this, `from datetime import datetime as dt` followed by `dt.now()`
    reads as the dotted name `dt.now`, which matches no banned suffix and walks
    straight through. Resolving the root against what was imported is what
    closes that: `dt` resolves to `datetime.datetime`, so the call spells
    `datetime.datetime.now` and is caught.
    """
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for entry in node.names:
                aliases[entry.asname or entry.name.split(".", 1)[0]] = entry.name
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for entry in node.names:
                aliases[entry.asname or entry.name] = f"{node.module}.{entry.name}"
    return aliases


def resolve(name: str, aliases: dict[str, str]) -> str:
    """A dotted name with its root expanded through the import that bound it."""
    root, _, rest = name.partition(".")
    target = aliases.get(root)
    if target is None:
        return name
    return f"{target}.{rest}" if rest else target


def inspect_module(path: Path, package_root: Path) -> list[Finding]:
    relative = path.relative_to(package_root).as_posix()
    exempt = relative in ALLOWLIST
    findings: list[Finding] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    aliases = alias_map(tree)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom) and not exempt:
            for root in import_roots(node):
                if root in BANNED_IMPORTS:
                    findings.append(
                        Finding(
                            path,
                            node.lineno,
                            f"imports {root!r} — compilation does no I/O and reads no "
                            f"ambient state (RFC 0003 §5.5)",
                        )
                    )
        elif isinstance(node, ast.Call):
            spelled = dotted(node.func)
            if not spelled:
                continue
            name = resolve(spelled, aliases)
            root = name.split(".", 1)[0]
            if root in BANNED_MODULES_BY_ATTRIBUTE or any(
                name == banned or name.endswith(f".{banned}") for banned in BANNED_CALLS
            ):
                findings.append(
                    Finding(
                        path,
                        node.lineno,
                        f"calls {spelled}() — no ambient clock or randomness under "
                        f"src/bloomery (RFC 0003 §5.5)",
                    )
                )
        elif isinstance(node, ast.Attribute):
            spelled = dotted(node)
            name = resolve(spelled, aliases)
            if name in BANNED_ATTRIBUTES:
                findings.append(
                    Finding(
                        path,
                        node.lineno,
                        f"reads {spelled} — the environment is an input, never read",
                    )
                )

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root",
        nargs="?",
        default="src/bloomery",
        type=Path,
        help="package root to check (default: src/bloomery)",
    )
    arguments = parser.parse_args()
    root: Path = arguments.root

    if not root.is_dir():
        print(f"purity: {root} is not a directory", file=sys.stderr)
        return 2

    findings: list[Finding] = []
    for path in sorted(root.rglob("*.py")):
        findings.extend(inspect_module(path, root))

    for finding in findings:
        print(finding)

    if findings:
        # One stream, so the summary follows the findings it counts rather than
        # racing them through separate buffers.
        print(
            f"\npurity: {len(findings)} violation(s). Compilation takes its inputs as "
            f"arguments — a clock, an id or a path read here breaks byte-identical "
            f"recompilation (RFC 0003)."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
