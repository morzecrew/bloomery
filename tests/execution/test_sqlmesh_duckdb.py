"""Execution tier (RFC 0009 §5.2 tier 4): seed bronze fixture data in
in-process DuckDB, materialize every compiled model's SELECT as a silver
table, and assert numeric results with ``Decimal`` — never float (RFC 0003
D5). Houses the M3 acceptance: the ``from_total`` recipe derivation yields
``Decimal("10.00")`` (original spec §7.4)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from pathlib import PurePosixPath

import duckdb
import pytest

from bloomery.emit import EmittedArtifact
from support.compiling import compile_fixture, extract_select

pytestmark = pytest.mark.execution


@pytest.fixture
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = duckdb.connect(":memory:")
    connection.execute("SET TimeZone = 'UTC'")
    for schema in ("bronze", "silver", "gold"):
        connection.execute(f"CREATE SCHEMA {schema}")
    yield connection
    connection.close()


def materialize(conn: duckdb.DuckDBPyConnection, artifacts: tuple[EmittedArtifact, ...]) -> None:
    """CREATE TABLE <namespace>.<relation> AS <the artifact's SELECT> —
    silver before gold, because mart SELECTs read the silver relations."""
    for artifact in sorted(
        artifacts, key=lambda a: (PurePosixPath(a.path).parent.name != "silver",)
    ):
        path = PurePosixPath(artifact.path)
        namespace, relation = path.parent.name, path.stem
        conn.execute(f"CREATE TABLE {namespace}.{relation} AS {extract_select(artifact.content)}")


def test_minimal_rows_round_trip(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("CREATE TABLE bronze.raw__events (id VARCHAR, kind VARCHAR, ts VARCHAR)")
    conn.executemany(
        "INSERT INTO bronze.raw__events VALUES (?, ?, ?)",
        [
            ("e1", "click", "2024-01-02T03:04:05"),
            ("e2", "view", "2024-02-03T04:05:06"),
        ],
    )
    materialize(conn, compile_fixture("minimal"))
    rows = conn.execute(
        "SELECT event_id, kind, occurred_at FROM silver.event ORDER BY event_id"
    ).fetchall()
    assert rows == [
        ("e1", "click", datetime(2024, 1, 2, 3, 4, 5)),
        ("e2", "view", datetime(2024, 2, 3, 4, 5, 6)),
    ]


def _seed_ecom(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        "CREATE TABLE bronze.shopify__order_lines ("
        'order_id VARCHAR, "index" BIGINT, total DECIMAL(12, 4), qty BIGINT, created_at VARCHAR)'
    )
    conn.execute(
        "INSERT INTO bronze.shopify__order_lines VALUES (?, ?, ?, ?, ?)",
        ("o1", 1, Decimal("30.00"), 3, "2024-01-02T03:04:05"),
    )
    conn.execute("CREATE TABLE bronze.shopify__orders (id VARCHAR, customer JSON)")
    conn.execute(
        "INSERT INTO bronze.shopify__orders VALUES (?, ?)",
        ("o1", '{"id": "c1"}'),
    )


def test_ecom_basic_from_total_derivation_yields_decimal_10_00(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """The acceptance assertion (original spec §7.4, RFC 0009): line_total
    30.00 over quantity 3 through the recorded `from_total` recipe is exactly
    Decimal("10.00") — asserted as Decimal, never float."""
    _seed_ecom(conn)
    materialize(conn, compile_fixture("ecom_basic"))
    row = conn.execute("SELECT unit_price FROM silver.order_item").fetchone()
    assert row is not None
    unit_price = row[0]
    assert isinstance(unit_price, Decimal)
    assert unit_price == Decimal("10.00")


def test_ecom_basic_silver_tables_materialize(conn: duckdb.DuckDBPyConnection) -> None:
    _seed_ecom(conn)
    materialize(conn, compile_fixture("ecom_basic"))
    item = conn.execute("SELECT order_id, line_no, quantity FROM silver.order_item").fetchone()
    assert item == ("o1", 1, 3)
    order = conn.execute("SELECT order_id, customer_id FROM silver.order").fetchone()
    assert order == ("o1", "c1")
    order_date = conn.execute("SELECT order_date FROM silver.order_item").fetchone()
    assert order_date is not None and order_date[0] is not None
