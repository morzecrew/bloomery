"""The RFC corpus and its retirement index agree — enforced structurally, in CI.

RFC 0025 §5.4: designs are retired by deleting them, and 2,142 citations of the
form ``RFC NNNN`` across source, tests and docs name files that are therefore
not in the tree. `rfcs/RETIRED.md` is what makes those citations followable, and
it is hand-appended in the retiring change (RFC 0025 D7) — which means it is
exactly the kind of file that silently falls behind.

Three invariants. The first two are structural and run anywhere; the third
needs history.

* **A number is used exactly once.** Every number below the index's next-free
  claim appears in exactly one of ``rfcs/`` and ``RETIRED.md``, and in only one
  document within each. A number in both says a retired design came back; in
  neither, that a retirement skipped its row — the failure that makes the table
  untrustworthy, because a reader who finds one gap stops believing the rest.
* **The index's next-free claim is still free.** No number at or above it is
  live or retired, since ``INDEX.md`` promises numbers are never reused and a
  stale claim is how the promise breaks.
* **A retired row names a commit that actually retired it.** The SHA must
  resolve and must have deleted a file matching that number under ``rfcs/``.
  A typo'd SHA is worse than a missing row: the row reads as recoverable and
  sends the reader to a commit that never held the document.

A row that looks like a table entry and parses as nothing is reported rather
than skipped — silently dropping it would let the table display an entry every
check treats as absent.

Deliberately *not* checked: the titles. Verifying one means reading the deleted
document, which needs history the structural half deliberately runs without —
and a SHA that cannot be resolved already fails the third invariant.

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


def live_files(rfcs: Path) -> dict[str, list[str]]:
    """Filenames in the tree, grouped by the number they claim.

    A ``dict`` rather than a ``set`` because two files can claim one number,
    and collapsing them would hide it: both would be "accounted for", and the
    one-document-per-number invariant would go unchecked by the only gate CI
    runs.
    """
    grouped: dict[str, list[str]] = {}
    for path in sorted(rfcs.glob("*.md")):
        if match := RFC_FILE.match(path.name):
            grouped.setdefault(match["number"], []).append(path.name)
    return grouped


def retired_rows(retired: Path) -> tuple[list[tuple[str, str]], list[str]]:
    """``([(number, sha)], [unparseable lines])`` from the table.

    Unparseable rows are returned rather than dropped. A line that looks like a
    table row to a reader and matches nothing here is the worst of both: the
    table shows an entry, and every check behaves as though it is absent. For a
    number below the next-free claim the completeness check catches it by
    accident; above it, nothing would.
    """
    rows: list[tuple[str, str]] = []
    malformed: list[str] = []
    for raw in retired.read_text().splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        if match := ROW.match(line):
            rows.append((match["number"], match["sha"]))
        elif not set(line) <= set("|- :") and not line.startswith("| #"):
            malformed.append(line)
    return rows, malformed


def next_free(index: Path) -> str | None:
    match = NEXT_FREE.search(index.read_text())
    return match["number"] if match else None


def _git(root: Path, *args: str) -> str | None:
    """``git`` output, or ``None`` when the command could not be answered.

    ``None`` covers every way this environment can lack an answer — no ``git``
    on ``PATH``, no repository, a shallow clone that does not hold the object.
    They collapse deliberately: the caller's response to all three is the same,
    and letting ``FileNotFoundError`` escape would end a `just quality` run in a
    traceback rather than a finding.
    """
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            cwd=root,
            check=False,
        )
    except OSError:  # FileNotFoundError (no git) is one of these
        return None
    return result.stdout if result.returncode == 0 else None


def deleted_in(sha: str, root: Path) -> set[str]:
    """RFC numbers whose file this commit deleted under ``rfcs/``.

    An unreadable commit yields the empty set, which the caller reports as "did
    not delete it" — the honest reading, since a SHA nobody can resolve is no
    more useful to a reader following a citation than a wrong one.
    """
    output = _git(root, "show", "--diff-filter=D", "--name-only", "--format=", sha, "--", "rfcs/")
    if output is None:
        return set()
    return {
        match["number"]
        for line in output.splitlines()
        if (match := RFC_FILE.match(Path(line.strip()).name))
    }


def history_available(root: Path) -> bool:
    """Whether this checkout can resolve historical commits at all.

    False in a shallow clone — the normal case in CI, since `actions/checkout`
    defaults to depth 1 — and equally false with no repository or no ``git``.
    The structural half of this check runs regardless; only the SHA half needs
    history, and it is skipped rather than failed, because a gate that cannot
    run in CI is a gate that gets removed.
    """
    output = _git(root, "rev-parse", "--is-shallow-repository")
    return output is not None and output.strip() == "false"


def check(root: Path) -> list[str]:
    rfcs = root / "rfcs"
    index, retired = rfcs / "INDEX.md", rfcs / "RETIRED.md"

    if not retired.is_file():
        return [f"{retired}: missing — every retirement appends a row here (RFC 0025 §5.4)"]

    findings: list[str] = []
    live = live_files(rfcs)
    rows, malformed = retired_rows(retired)
    retired_numbers = [number for number, _ in rows]

    findings += [f"RETIRED.md: unreadable row — {line}" for line in malformed]

    findings += [
        f"rfcs/: {number} is claimed by more than one document ({', '.join(names)})"
        for number, names in sorted(live.items())
        if len(names) > 1
    ]

    duplicates = sorted({n for n in retired_numbers if retired_numbers.count(n) > 1})
    findings += [f"RETIRED.md: {n} appears in more than one row" for n in duplicates]

    findings += [
        f"RETIRED.md: {n} is listed as retired, but rfcs/{n}-*.md is in the tree"
        for n in sorted(set(live) & set(retired_numbers))
    ]

    claimed = next_free(index)
    if claimed is None:
        findings.append("INDEX.md: no 'next free number is **NNNN**' claim to check against")
    else:
        accounted = set(live) | set(retired_numbers)
        findings += [
            f"RETIRED.md: {number:04d} is neither live nor retired — a retirement "
            f"skipped its row, or the number was never used"
            for number in range(1, int(claimed))
            if f"{number:04d}" not in accounted
        ]
        # A number at or above the next-free claim — live or retired — means the
        # index is about to mint one that is already taken, and INDEX.md
        # promises numbers are never reused. Checked structurally rather than
        # through the SHA, because the SHA half is the half that can be skipped.
        findings += [
            f"{'rfcs/' if number in live else 'RETIRED.md'}: {number} is in use but the "
            f"index's next free number is {claimed} — a spent number is about to be "
            f"minted again"
            for number in sorted(accounted)
            if int(number) >= int(claimed)
        ]

    if not history_available(root):
        findings.append(
            "note: no usable history (shallow clone, no repository, or no git) — "
            "retiring commits not verified; the structural checks above did run"
        )
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
