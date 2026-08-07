"""Mart execution (RFC 0009 §5.2 tier 4, RFC 0010): seed bronze rows,
materialize silver then gold from the emitted SQL, and prove the role-playing
arithmetic — grouping by ``ordered_month`` vs ``shipped_month`` gives
*different, correct* totals — plus the ecom_basic mart aggregate against a
hand-computed value. All assertions are ``Decimal`` — floats never appear
(RFC 0003 D5)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import PurePosixPath

import duckdb
import pytest

from bloomery.emit import ArtifactKind, EmittedArtifact
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
    """CREATE TABLE per model artifact — silver before gold, because mart
    SELECTs read the silver relations the entity models create."""
    models = [a for a in artifacts if a.kind is ArtifactKind.MODEL]
    for artifact in sorted(models, key=lambda a: (PurePosixPath(a.path).parent.name != "silver",)):
        path = PurePosixPath(artifact.path)
        namespace, relation = path.parent.name, path.stem
        conn.execute(f"CREATE TABLE {namespace}.{relation} AS {extract_select(artifact.content)}")


# ....................... #
# role_playing_dates: ordered_* vs shipped_* give different, correct numbers


def _seed_orders(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        "CREATE TABLE bronze.oms__orders ("
        "id VARCHAR, amount DECIMAL(12, 4), order_date VARCHAR, ship_date VARCHAR)"
    )
    conn.executemany(
        "INSERT INTO bronze.oms__orders VALUES (?, ?, ?, ?)",
        [
            # o2 orders in January but ships in February — the row that makes
            # the two role groupings disagree, both correctly.
            ("o1", Decimal("100.00"), "2024-01-15", "2024-01-20"),
            ("o2", Decimal("50.00"), "2024-01-31", "2024-02-02"),
            ("o3", Decimal("25.00"), "2024-02-10", "2024-02-12"),
        ],
    )


def test_ordered_month_and_shipped_month_give_different_correct_totals(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """The role-playing acceptance (RFC 0009 D12, RFC 0010 §6): the same
    revenue measure grouped by the two roles yields different splits, and
    both are right — order attribution vs shipment attribution."""
    _seed_orders(conn)
    materialize(conn, compile_fixture("role_playing_dates"))

    by_ordered = conn.execute(
        "SELECT ordered_month, SUM(amount) FROM gold.mart_orders GROUP BY 1 ORDER BY 1"
    ).fetchall()
    by_shipped = conn.execute(
        "SELECT shipped_month, SUM(amount) FROM gold.mart_orders GROUP BY 1 ORDER BY 1"
    ).fetchall()

    # Ordered attribution: o1 + o2 land in January (100 + 50), o3 in February.
    assert by_ordered == [
        (date(2024, 1, 1), Decimal("150.00")),
        (date(2024, 2, 1), Decimal("25.00")),
    ]
    # Shipped attribution: o2's 50 moves to February (50 + 25).
    assert by_shipped == [
        (date(2024, 1, 1), Decimal("100.00")),
        (date(2024, 2, 1), Decimal("75.00")),
    ]
    assert by_ordered != by_shipped  # different — and both are correct
    total = conn.execute("SELECT SUM(amount) FROM gold.mart_orders").fetchone()
    assert total is not None and total[0] == Decimal("175.00")  # no rows lost


def test_mart_rows_stay_at_base_grain(conn: duckdb.DuckDBPyConnection) -> None:
    _seed_orders(conn)
    materialize(conn, compile_fixture("role_playing_dates"))
    row_count = conn.execute("SELECT COUNT(*) FROM gold.mart_orders").fetchone()
    assert row_count is not None and row_count[0] == 3  # one row per order


# ....................... #
# ecom_basic: the flattened mart builds and aggregates to hand-computed values


def _seed_ecom(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        "CREATE TABLE bronze.shopify__order_lines ("
        'order_id VARCHAR, "index" BIGINT, total DECIMAL(12, 4), qty BIGINT, created_at VARCHAR)'
    )
    conn.executemany(
        "INSERT INTO bronze.shopify__order_lines VALUES (?, ?, ?, ?, ?)",
        [
            ("o1", 1, Decimal("30.00"), 3, "2024-01-02T03:04:05"),
            ("o1", 2, Decimal("8.00"), 2, "2024-01-02T03:04:05"),
        ],
    )
    conn.execute("CREATE TABLE bronze.shopify__orders (id VARCHAR, customer JSON)")
    conn.execute("INSERT INTO bronze.shopify__orders VALUES (?, ?)", ("o1", '{"id": "c1"}'))


def test_ecom_basic_mart_aggregate_matches_the_hand_computed_value(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """gross_revenue over the built mart: 30.00/3 → 10.00 × 3 plus
    8.00/2 → 4.00 × 2 = 38.00 exactly — Decimal, never float."""
    _seed_ecom(conn)
    materialize(conn, compile_fixture("ecom_basic"))
    row = conn.execute(
        "SELECT SUM(unit_price * quantity), MIN(order_customer_id), MIN(ordered_month)"
        " FROM gold.mart_order_items"
    ).fetchone()
    assert row is not None
    revenue, customer_id, ordered_month = row
    assert isinstance(revenue, Decimal)
    assert revenue == Decimal("38.00")
    assert customer_id == "c1"  # the join flattened the customer in at build
    assert ordered_month == date(2024, 1, 1)


def test_dim_date_builds_the_full_declared_calendar(conn: duckdb.DuckDBPyConnection) -> None:
    """The calendar is a pure function of the catalog bounds (RFC 0008 D13):
    2020–2030 inclusive is exactly 4018 days, no clock involved."""
    _seed_ecom(conn)
    materialize(conn, compile_fixture("ecom_basic"))
    row = conn.execute(
        "SELECT COUNT(*), MIN(date_day), MAX(date_day) FROM gold.dim_date"
    ).fetchone()
    assert row == (4018, date(2020, 1, 1), date(2030, 12, 31))
