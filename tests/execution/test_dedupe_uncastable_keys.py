"""Two rows whose keys fail to cast are two rows, not duplicates, executed (#315).

The dedupe window partitioned by the coerced key, and every key that fails its
cast coerces to the same NULL. Two bronze rows with different bad `day` values
then shared one partition, `ROW_NUMBER() = 1` kept one, and the other was
dropped as a dedupe loser: in neither the entity nor its reject table, a
coercion failure gone without a record.
"""

from __future__ import annotations

from collections.abc import Iterator

import duckdb
import pytest
from support.compiling import FIXTURES, fixture_sources
from support.execution import materialize, warehouse

from bloomery import Target, compile_project, load_catalog, load_project

pytestmark = pytest.mark.execution

FIXTURE = "semi_additive_inventory"

ROWS = [
    ("w1", "2026-01-01", "5", "2026-01-01 00:00:00", "r1"),
    # Two different source keys, both uncastable: two coercion failures.
    ("w2", "not-a-date", "5", "2026-01-01 00:00:00", "r2"),
    ("w2", "also-bad", "5", "2026-01-01 00:00:01", "r3"),
    # A genuine duplicate, which dedupe must still collapse to its latest row.
    ("w3", "2026-01-02", "5", "2026-01-01 00:00:00", "r4"),
    ("w3", "2026-01-02", "6", "2026-01-01 00:00:01", "r5"),
]


@pytest.fixture(scope="module")
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    catalog = load_catalog((FIXTURES / FIXTURE / "catalog.yaml").read_text(encoding="utf-8"))
    artifacts = compile_project(
        load_project(fixture_sources(FIXTURE)),
        target=Target.SQLMESH,
        dialect="duckdb",
        catalog=catalog,
    )
    connection = warehouse("bronze", "silver", "gold")
    connection.execute(
        "CREATE TABLE bronze.wms__stock_levels (warehouse VARCHAR, day VARCHAR, "
        "on_hand VARCHAR, _load_id VARCHAR, _ingested_at VARCHAR, _source_row_id VARCHAR, "
        "operator_note VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO bronze.wms__stock_levels VALUES (?, ?, ?, 'L1', ?, ?, NULL)", ROWS
    )
    materialize(connection, artifacts)
    yield connection
    connection.close()


def test_every_uncastable_key_reaches_quarantine(conn: duckdb.DuckDBPyConnection) -> None:
    rejected = dict(
        conn.execute(
            "SELECT _source_row_id, failed_rules FROM silver.inventory_level__reject"
        ).fetchall()
    )
    assert sorted(rejected) == ["r2", "r3"]
    assert all("stock_date_coercible" in rules for rules in rejected.values())


def test_a_genuine_duplicate_still_keeps_one_row(conn: duckdb.DuckDBPyConnection) -> None:
    kept = conn.execute(
        "SELECT _source_row_id, stock_level FROM silver.inventory_level ORDER BY 1"
    ).fetchall()
    assert kept == [("r1", 5), ("r5", 6)]
