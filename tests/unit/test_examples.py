"""The shipped examples still do what they claim (RFC 0009).

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

**Two of the three examples are here.** `refusals/` and `quickstart/` are pure —
compile, parse and plan, with no engine and no container — so they belong in
the unit tier and cost about a second between them. `lakehouse/` is not: it runs
`sqlmesh plan` against a live Trino, which is Tier 5/6 work behind the Docker
gate, and putting it here would make `just test` require a warehouse. It is
named rather than silently omitted, because "the examples are covered" would
otherwise read as all of them.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = REPO_ROOT / "examples"
EXAMPLE = EXAMPLES / "refusals"


def run_example(name: str) -> subprocess.CompletedProcess[str]:
    """One example, through its own entry point, from the repository root."""
    return subprocess.run(  # noqa: S603 — a fixed path, no shell, no input
        [sys.executable, str(EXAMPLES / name / "run.py")],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )


def test_every_refusal_case_still_refuses() -> None:
    """The whole runner, through its own entry point.

    No warehouse and no container: every case here is decided at compile time,
    which is what makes this cheap enough to sit in the unit tier rather than
    behind the Docker gate.
    """
    result = run_example("refusals")

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


# ....................... #
# quickstart/ (RFC 0009 — the example the README's first page sends people to)


def test_quickstart_runs_end_to_end() -> None:
    """Compile, parse a JSON filter, plan a metric — all three phases.

    Asserted on the phases rather than only on the exit code, because this
    example has no self-check of its own: `refusals/` raises when a case stops
    refusing, and nothing here raises if the planner quietly returns an empty
    plan or the compile writes no artifact. The three markers are the three
    things the example exists to show, and each names a different subsystem.

    It writes into `examples/quickstart/out`, which the example's own
    `.gitignore` covers — running it is what is being tested, so it is run
    where it lives rather than copied somewhere neutral.
    """
    result = run_example("quickstart")

    assert result.returncode == 0, (
        f"the quickstart example failed:\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
    )
    assert "wrote " in result.stdout, "compiled nothing"
    assert "filter clause(s) from JSON" in result.stdout, "parsed no filter"
    assert "-- plan.sql --" in result.stdout, "planned no metric"


def test_quickstart_plans_a_query_rather_than_an_empty_one() -> None:
    """The marker above proves the section printed, not that it holds SQL.

    A planner returning an empty string would satisfy every assertion in the
    test above — the heading is printed unconditionally. This reads what came
    after it, which is the difference between "the example ran" and "the
    example did what the README says it does".
    """
    stdout = run_example("quickstart").stdout
    sql = stdout.split("-- plan.sql --", 1)[1].split("-- plan.explanation", 1)[0]

    assert "SELECT" in sql.upper(), f"no query in the planned SQL:\n{sql[:400]}"
    assert "revenue" in sql, "the requested metric is not in its own plan"
