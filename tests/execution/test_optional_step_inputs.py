"""An optional step input, executed bound and unbound (S-0034/D-61).

The empty relation an unbound input reads as is SQL no golden can prove: a cast
the engine refuses, or a derived table without the alias it needs, is
byte-stable and fails on its first run. So one body runs here twice, over the
same order lines, once with returns and once without.
"""

from __future__ import annotations

import duckdb
import pytest
from support.execution import materialize, warehouse

from bloomery import Target, compile_project, load_project
from bloomery.steps import StepManifest, StepRegistry

pytestmark = pytest.mark.execution

MANIFEST: dict[str, object] = {
    "ref": "net_units",
    "version": 1,
    "kind": "sql_model",
    "determinism": "pure",
    "runtime_lock": "sha256:x",
    "inputs": {
        "lines": {"grain": "order_line", "requires": ["product_id", "quantity"]},
        "returns": {
            "grain": "return_line",
            "optional": True,
            "columns": {"product_id": "string", "quantity": "int"},
        },
    },
    "outputs": {
        "net": {
            "grain": "one row per product",
            "key": ["product_id"],
            "produces": {"product_id": {"type": "string"}, "units": {"type": "int"}},
        }
    },
}

BODY = (
    "WITH sold AS (SELECT product_id, SUM(quantity) AS units FROM silver.order_line GROUP BY 1), "
    "returned AS (SELECT product_id, SUM(quantity) AS units FROM returns GROUP BY 1) "
    "SELECT s.product_id, s.units - COALESCE(r.units, 0) AS units "
    "FROM sold AS s LEFT JOIN returned AS r ON r.product_id = s.product_id"
)


def run(*, returns: bool) -> dict[str, int]:
    bound = ", returns: silver.return_line" if returns else ""
    project = load_project(
        {
            "entity_model": "spec_version: 1\nentities: {}\n",
            "steps": (
                "steps_version: 1\nsteps:\n  - use: net_units@1\n"
                f"    inputs: {{lines: silver.order_line{bound}}}\n"
                "    outputs: {net: silver.net_units}\n"
            ),
        }
    )
    registry = StepRegistry(
        {("net_units", 1): StepManifest.model_validate(MANIFEST)},
        sql_bodies={("net_units", 1): BODY},
    )
    artifacts = compile_project(project, target=Target.SQLMESH, dialect="duckdb", steps=registry)
    conn: duckdb.DuckDBPyConnection = warehouse("silver", "gold")
    conn.execute("CREATE TABLE silver.order_line (product_id TEXT, quantity BIGINT)")
    conn.execute("INSERT INTO silver.order_line VALUES ('a', 3), ('a', 2), ('b', 1)")
    if returns:
        conn.execute("CREATE TABLE silver.return_line (product_id TEXT, quantity BIGINT)")
        conn.execute("INSERT INTO silver.return_line VALUES ('a', 1)")
    materialize(conn, artifacts)
    return dict(conn.execute("SELECT product_id, units FROM silver.net_units").fetchall())


def test_unbound_the_body_reads_no_returns() -> None:
    assert run(returns=False) == {"a": 5, "b": 1}


def test_bound_the_same_body_reads_them() -> None:
    assert run(returns=True) == {"a": 4, "b": 1}
