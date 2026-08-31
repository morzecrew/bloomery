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

**All three examples are here, two of them whole and one of them halved.**
`refusals/` and `quickstart/` are pure — compile, parse and plan, no engine and
no container — so they run end to end through their own entry points.

`lakehouse/` is covered at its **first step only**, and the split is the
example's own: its docstring says the compile to SQLMesh artifacts "is the whole
of bloomery's involvement — a pure function from YAML strings to file-shaped
artifacts, no warehouse in sight", and everything after it shells out to the
`sqlmesh` CLI against a seven-service compose stack. Step 1 is what rots when
*this* repository changes, and it is free to check.

Rebuilding that stack in pytest was considered and refused, on a decision this
repository already took: `tests/engines/test_trino.py` diverges from RFC 0009
§5.2's sketched "trino+iceberg+minio (compose)" tier for exactly this reason —
"bloomery emits SELECTs and models and never storage-format DDL, so an object
store and a table format would be three more moving parts serving no assertion
here" (RFC 0009 D21). A second copy of `compose.yaml` living in the test suite
would be two accounts of one stack, drifting.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from bloomery import Target, compile_project, load_catalog, load_project

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


# ....................... #
# lakehouse/ — step 1 only, which is where bloomery's involvement ends


def test_the_lakehouse_specs_compile_for_trino() -> None:
    """The example's step 1, which needs no warehouse to check.

    Steps 2–6 shell out to `sqlmesh` against Trino, Lakekeeper and MinIO. Step 1
    is a pure function from YAML strings to artifacts, and it is the step that
    breaks when a spec in `specs/` drifts out of what bloomery accepts, or when
    the `trino` dialect stops emitting something the example depends on — the
    failures this repository can cause, as opposed to the ones a container can.
    """
    specs = EXAMPLES / "lakehouse" / "specs"
    catalog = load_catalog((specs / "catalog.yaml").read_text())
    documents = {
        path.name: path.read_text()
        for path in sorted(specs.glob("*.yaml"))
        if path.name != "catalog.yaml"
    }

    artifacts = compile_project(
        load_project(documents), target=Target.SQLMESH, dialect="trino", catalog=catalog
    )

    assert {artifact.path for artifact in artifacts} >= {
        "models/silver/order_line.sql",
        "models/gold/mart_order_lines.sql",
        "audits/order_line_source_collision.sql",
    }


def test_the_lakehouse_merge_and_its_blocking_audit_are_emitted() -> None:
    """The two claims the README makes about this example, in the SQL.

    `order_line` is built by two mappings — the example exists to show a union
    merge — and RFC 0024 D5 makes the disjointness audit blocking, because the
    compiler has no data with which to establish the key sets are disjoint. A
    merge that silently stopped unioning, or an audit that stopped being
    emitted, would leave the README describing a thing the artifacts no longer
    do, and the compile above would still pass.
    """
    specs = EXAMPLES / "lakehouse" / "specs"
    catalog = load_catalog((specs / "catalog.yaml").read_text())
    documents = {
        path.name: path.read_text()
        for path in sorted(specs.glob("*.yaml"))
        if path.name != "catalog.yaml"
    }
    artifacts = {
        artifact.path: artifact.content
        for artifact in compile_project(
            load_project(documents), target=Target.SQLMESH, dialect="trino", catalog=catalog
        )
    }

    order_line = artifacts["models/silver/order_line.sql"]
    assert "UNION ALL" in order_line, "the merge stopped being a union"
    for relation in ("bronze.shopify__order_lines", "bronze.woo__order_lines"):
        assert relation in order_line, f"{relation} dropped out of the merge"

    assert "blocking false" not in artifacts["audits/order_line_source_collision.sql"]
