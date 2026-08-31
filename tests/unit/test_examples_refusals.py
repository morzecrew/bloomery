"""The `refusals/` example still refuses what it claims to (RFC 0009).

The runner already knows how to fail — `refuse()` raises `SystemExit` on a case
that compiles, and its docstring says why: *"An example claiming a refusal that
no longer happens is worse than no example."* That design was right and it
caught a real rot; what was missing is anything that runs it.

`examples/` is referenced by no workflow and no recipe, so the one case whose
refusal was later lifted sat broken from the commit that added it until someone
ran the script by hand. The example is shipped documentation of the project's
central claim — a plausible wrong number is a compile error — and documentation
nothing executes is a claim nobody checks.

A subprocess rather than an import, because the entry point is what rotted: the
case list, the target it compiles for and the runner's own arithmetic are all
things a reader runs, and only running it covers them together.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = REPO_ROOT / "examples" / "refusals"


def test_every_refusal_case_still_refuses() -> None:
    """The whole runner, through its own entry point.

    No warehouse and no container: every case here is decided at compile time,
    which is what makes this cheap enough to sit in the unit tier rather than
    behind the Docker gate.
    """
    result = subprocess.run(  # noqa: S603 — a fixed path, no shell, no input
        [sys.executable, str(EXAMPLE / "run.py")],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )

    assert result.returncode == 0, (
        f"the refusals example failed:\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
    )


def test_the_runner_counts_the_cases_it_actually_walks() -> None:
    """The closing line is arithmetic over the case list, so it cannot drift —
    but the *directory* can, and a case nobody lists is a case nobody runs.

    This is what makes the test above total: without it, deleting a case from
    `CASE_NOTES` and leaving its directory behind would still exit 0 while
    silently covering one case fewer.
    """
    listed = {
        line.split("/)")[0].rsplit("(", 1)[-1]
        for line in subprocess.run(  # noqa: S603 — a fixed path, no shell, no input
            [sys.executable, str(EXAMPLE / "run.py")],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            check=True,
        ).stdout.splitlines()
        if "  (" in line and line.endswith("/)")
    }
    on_disk = {path.name for path in (EXAMPLE / "cases").iterdir() if path.is_dir()}

    assert listed == on_disk, "a case directory the runner never walks, or the reverse"
