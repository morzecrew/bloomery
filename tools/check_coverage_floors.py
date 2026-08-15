"""Per-package coverage floors (RFC 0025 §5.2, D3/D5).

RFC 0001 §8 deferred this ratchet with a reason — *"ratchets need something to
ratchet"* — and named the release as its trigger. One floor already existed:
``src/bloomery/guardrails/*`` at 100%, encoding RFC 0009 D9's "an untested
guardrail branch is an unshipped guardrail". This generalizes it into a
declared table rather than replacing it (D3).

**A global floor is not a per-package floor.** The project sits near 99%
overall, so `--fail-under=80` can absorb a package falling to 60 without
noticing — and the packages where an uncovered line matters most are small
enough to disappear into that total. A floor per package is what makes a
regression visible where it happened.

The numbers come from measurement, one notch below current (D5): above it and
the floor fails on day one, far below it and the floor ratchets nothing.
`justfile`'s ``coverage`` recipe and CI's coverage job both run this, so the
floors have one authority.

Reports **every** package below its floor, not the first: a contributor fixing
coverage should see the whole list in one round-trip, which is the same reason
the guardrail stage batches.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from pathlib import Path

#: Where the table lives — beside the global ``fail_under`` it refines.
TABLE = ("tool", "bloomery", "coverage-floors")


def floors(root: Path) -> dict[str, float]:
    """The declared ``glob -> percentage`` table, or ``{}`` when absent."""
    node: dict[str, object] = tomllib.loads((root / "pyproject.toml").read_text())
    for key in TABLE:
        found = node.get(key)
        if not isinstance(found, dict):
            return {}
        node = found
    return {name: float(value) for name, value in node.items() if isinstance(value, (int, float))}


def measured(root: Path, glob: str) -> float | None:
    """Total coverage for the files matching ``glob``, or ``None``.

    ``None`` means the report could not be produced — no coverage data, or a
    glob matching nothing. Both are reported as failures by the caller rather
    than skipped: a floor over zero files is the vacuous pass this whole file
    exists to prevent, and it looks identical to a floor that held.
    """
    result = subprocess.run(
        [sys.executable, "-m", "coverage", "report", f"--include={glob}"],
        capture_output=True,
        text=True,
        cwd=root,
        check=False,
    )
    if result.returncode != 0:
        return None
    for line in reversed(result.stdout.splitlines()):
        if line.startswith("TOTAL") or line.startswith("src/"):
            percent = line.split()[-1].rstrip("%")
            try:
                return float(percent)
            except ValueError:
                return None
    return None


def check(root: Path) -> list[str]:
    declared = floors(root)
    if not declared:
        return [
            "pyproject.toml: no [tool.bloomery.coverage-floors] table — the "
            "per-package floors are declared there (RFC 0025 §5.2)"
        ]
    findings: list[str] = []
    for glob in sorted(declared):
        floor = declared[glob]
        actual = measured(root, glob)
        if actual is None:
            findings.append(
                f"{glob}: no coverage could be measured — the glob matches nothing, or "
                "no coverage data was collected. A floor over zero files always passes"
            )
        elif actual < floor:
            findings.append(f"{glob}: {actual:.1f}% is below its floor of {floor:.0f}%")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".", type=Path)
    root = parser.parse_args().root.resolve()

    findings = check(root)
    for finding in findings:
        print(finding)
    if findings:
        print(
            f"\ncoverage floors: {len(findings)} package(s) below floor. The floors are "
            "declared in pyproject.toml and set one notch below measured coverage "
            "(RFC 0025 D5) — a drop means new code arrived untested, not that the "
            "number needs lowering."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
