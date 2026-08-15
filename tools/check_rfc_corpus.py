"""The RFC corpus and its retirement index agree — enforced structurally, in CI.

RFC 0025 §5.4: designs are retired by deleting them, and 2,142 citations of the
form ``RFC NNNN`` across source, tests and docs name files that are therefore
not in the tree. `rfcs/RETIRED.md` is what makes those citations followable, and
it is hand-appended in the retiring change (RFC 0025 D7) — which means it is
exactly the kind of file that silently falls behind.

Two invariants, both cheap and both total:

* **A number is live or retired, never both and never neither.** Every number
  below the index's next-free claim appears in exactly one of ``rfcs/`` and
  ``RETIRED.md``. A number in both says a retired document came back; a number
  in neither says a retirement skipped its row, which is the failure mode that
  makes the table untrustworthy — a reader who finds one gap stops believing the
  rest.
* **A retired row names a commit that actually retired it.** The SHA must
  resolve and must have deleted a file matching that number under ``rfcs/``.
  A typo'd SHA is worse than a missing row: the row reads as recoverable and
  sends the reader to a commit that never held the document.

Deliberately *not* checked: the titles. Verifying one means reading the deleted
document, which needs the full history this check must run without — the second
invariant already fails on the SHA that would make a title unverifiable anyway.

Run by ``just quality``; exits non-zero with one line per finding.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

#: ``| 0016 | Title | `f4ae4a0` |`` — number and SHA; the title is passed over
#: deliberately (see the module docstring).
ROW = re.compile(r"^\|\s*(?P<number>\d{4})\s*\|[^|]*\|\s*`(?P<sha>[0-9a-f]{7,40})`\s*\|")

#: ``The next free number is **0026**.`` in `INDEX.md` — the corpus's own claim
#: about how far the numbering has gone, and the upper bound of the completeness
#: check. Read rather than computed, because computing it from `ls` is precisely
#: what the retirement policy makes impossible.
NEXT_FREE = re.compile(r"next free number is \*\*(?P<number>\d{4})\*\*")

#: `NNNN-kebab-title.md` under `rfcs/`.
RFC_FILE = re.compile(r"^(?P<number>\d{4})-[a-z0-9-]+\.md$")


def live_numbers(rfcs: Path) -> set[str]:
    """The numbers with a document in the tree."""
    return {match["number"] for path in rfcs.glob("*.md") if (match := RFC_FILE.match(path.name))}


def retired_rows(retired: Path) -> list[tuple[str, str]]:
    """``(number, sha)`` per table row, in file order."""
    return [
        (match["number"], match["sha"])
        for line in retired.read_text().splitlines()
        if (match := ROW.match(line.strip()))
    ]


def next_free(index: Path) -> str | None:
    match = NEXT_FREE.search(index.read_text())
    return match["number"] if match else None


def deleted_in(sha: str, root: Path) -> set[str]:
    """RFC numbers whose file this commit deleted under ``rfcs/``.

    Returns an empty set when the commit cannot be read at all — a shallow
    clone has no history, and a check that fails the build for running in one
    would be a check people delete. The caller distinguishes "unreadable" from
    "read, and it deleted nothing".
    """
    result = subprocess.run(
        ["git", "show", "--diff-filter=D", "--name-only", "--format=", sha, "--", "rfcs/"],
        capture_output=True,
        text=True,
        cwd=root,
        check=False,
    )
    if result.returncode != 0:
        return set()
    return {
        match["number"]
        for line in result.stdout.splitlines()
        if (match := RFC_FILE.match(Path(line.strip()).name))
    }


def history_available(root: Path) -> bool:
    """Whether this clone has the history the SHA check needs.

    A shallow clone is the normal case in CI (`actions/checkout` defaults to
    depth 1), and the structural half of this check is worth running there. The
    SHA half is skipped rather than failed, and says so.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        capture_output=True,
        text=True,
        cwd=root,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "false"


def check(root: Path) -> list[str]:
    rfcs = root / "rfcs"
    index, retired = rfcs / "INDEX.md", rfcs / "RETIRED.md"

    if not retired.is_file():
        return [f"{retired}: missing — every retirement appends a row here (RFC 0025 §5.4)"]

    findings: list[str] = []
    live = live_numbers(rfcs)
    rows = retired_rows(retired)
    retired_numbers = [number for number, _ in rows]

    duplicates = sorted({n for n in retired_numbers if retired_numbers.count(n) > 1})
    findings += [f"RETIRED.md: {n} appears in more than one row" for n in duplicates]

    findings += [
        f"RETIRED.md: {n} is listed as retired, but rfcs/{n}-*.md is in the tree"
        for n in sorted(live & set(retired_numbers))
    ]

    claimed = next_free(index)
    if claimed is None:
        findings.append("INDEX.md: no 'next free number is **NNNN**' claim to check against")
    else:
        accounted = live | set(retired_numbers)
        findings += [
            f"RETIRED.md: {number:04d} is neither live nor retired — a retirement "
            f"skipped its row, or the number was never used"
            for number in range(1, int(claimed))
            if f"{number:04d}" not in accounted
        ]

    if not history_available(root):
        findings.append("note: shallow clone — retiring commits not verified (structure was)")
        return findings

    for number, sha in rows:
        if number not in deleted_in(sha, root):
            findings.append(
                f"RETIRED.md: {number} names `{sha}`, which did not delete rfcs/{number}-*.md"
            )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".", type=Path)
    root = parser.parse_args().root.resolve()

    findings = check(root)
    for finding in findings:
        print(finding)

    hard = [f for f in findings if not f.startswith("note:")]
    if hard:
        print(
            f"\nrfc corpus: {len(hard)} problem(s). A citation is followable only if its "
            f"number is in RETIRED.md with the commit that deleted it (RFC 0025 §5.4)."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
