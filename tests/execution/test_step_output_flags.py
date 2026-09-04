"""A flagged Tier 2 step output, executed (RFC 0051 §5.3).

The wrap is a projection over a **subquery alias** rather than over a bronze
relation, which is a binding no golden can prove: a model that references
``_extract.k`` where the alias projects something else is byte-stable, review-
clean, and fails on its first run. So this module runs the emitted model as
emitted, over a seeded source, and reads the two generated columns back.
"""

from __future__ import annotations

import duckdb
import pytest
from support.execution import materialize, warehouse

from bloomery import Target, compile_project, load_project
from bloomery.steps import StepManifest, StepRegistry

pytestmark = pytest.mark.execution

ENTITY_MODEL = "spec_version: 1\nentities: {}\n"

WIRING = (
    "steps_version: 1\nsteps:\n  - use: scored@1\n"
    "    outputs: {out: silver.scored}\n"
    "    quality:\n"
    '      - {rule: expression, name: confident, expr: "score >= 0.8", on_fail: flag}\n'
    "    applies_to: {confident: out}\n"
)

MANIFEST: dict[str, object] = {
    "ref": "scored",
    "version": 1,
    "kind": "sql_model",
    "determinism": "pure",
    "runtime_lock": "sha256:x",
    "outputs": {
        "out": {
            "grain": "one row per scored key",
            "key": ["k"],
            "produces": {"k": {"type": "string"}, "score": {"type": "decimal(4,3)"}},
        }
    },
}

BODY = "SELECT k, score FROM silver.src"


@pytest.fixture(scope="module")
def run() -> duckdb.DuckDBPyConnection:
    project = load_project({"entity_model": ENTITY_MODEL, "steps": WIRING})
    registry = StepRegistry(
        {("scored", 1): StepManifest.model_validate(MANIFEST)},
        sql_bodies={("scored", 1): BODY},
    )
    artifacts = compile_project(
        project, target=Target.SQLMESH, dialect="duckdb", steps=registry
    )
    conn = warehouse("silver", "gold")
    conn.execute("CREATE TABLE silver.src (k TEXT, score DECIMAL(4,3))")
    conn.execute(
        "INSERT INTO silver.src VALUES ('a', 0.95), ('b', 0.40), ('c', 0.80)"
    )
    materialize(conn, artifacts)
    return conn


def test_the_flag_column_names_the_rule_on_the_rows_that_fail(
    run: duckdb.DuckDBPyConnection,
) -> None:
    rows = dict(
        run.execute(
            "SELECT k, list_contains(_quality_flags, 'confident') FROM silver.scored"
        ).fetchall()
    )
    # 0.80 is inside the rule's own boundary — a `>=` written as `>` upstream
    # would only show up on this row.
    assert rows == {"a": False, "b": True, "c": False}


def test_no_row_is_routed_away(run: duckdb.DuckDBPyConnection) -> None:
    """`flag` marks, it never diverts (RFC 0016 §5.2) — and a step output has
    no reject table for a diverted row to land in."""
    assert run.execute("SELECT COUNT(*) FROM silver.scored").fetchone() == (3,)


def test_quality_ok_agrees_with_the_flag_array(
    run: duckdb.DuckDBPyConnection,
) -> None:
    assert run.execute(
        "SELECT COUNT(*) FROM silver.scored WHERE _quality_ok <> (LEN(_quality_flags) = 0)"
    ).fetchone() == (0,)


def test_the_quality_mart_counts_the_failure(run: duckdb.DuckDBPyConnection) -> None:
    """The mart reads `_quality_flags` off the relation the wrap created — the
    binding that would fail if the two disagreed about the column."""
    assert run.execute(
        "SELECT rows_failed FROM gold.mart_data_quality "
        "WHERE entity = 'scored' AND rule = 'confident'"
    ).fetchone() == (1,)
