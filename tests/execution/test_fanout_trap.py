"""The fan-out regression suite (RFC 0009 §5.2 tier 4, spec §7.4).

``fanout_trap`` fails closed at compile time (`GrainMismatch`, RFC 0006 D5);
the execution-level assertion is **kept on purpose** — per RFC 0006 D10 it
documents *why* the compile error exists: the unguarded SQL below runs
against DuckDB and produces the 3×-wrong shipping sum the guard refuses.

The numbers: order ``o1`` has three lines (10.00 each) and one order-level
shipping cost of 9.00. The bronze export denormalizes shipping onto every
line — the naive line-grain sum counts it three times:

- correct shipping total:  9.00  (once per order)
- naive shipping total:   27.00  (once per line — 3× wrong)
- correct landed total:   30.00 + 9.00  = 39.00
- naive landed total:     30.00 + 27.00 = 57.00

All assertions are ``Decimal`` — floats never appear (RFC 0003 D5).
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import duckdb
import pytest

from bloomery import build_project_ir
from bloomery.errors import GrainMismatch, GuardrailError
from support.compiling import load_fixture

pytestmark = pytest.mark.execution


@pytest.fixture
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = duckdb.connect(":memory:")
    connection.execute("CREATE SCHEMA bronze")
    yield connection
    connection.close()


def _seed(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        "CREATE TABLE bronze.wms__order_lines ("
        "order_id VARCHAR, line_no BIGINT, price DECIMAL(12, 4), shipping DECIMAL(12, 4))"
    )
    conn.executemany(
        "INSERT INTO bronze.wms__order_lines VALUES (?, ?, ?, ?)",
        [
            ("o1", 1, Decimal("10.00"), Decimal("9.00")),
            ("o1", 2, Decimal("10.00"), Decimal("9.00")),
            ("o1", 3, Decimal("10.00"), Decimal("9.00")),
        ],
    )
    conn.execute("CREATE TABLE bronze.wms__orders (id VARCHAR, shipping DECIMAL(12, 4))")
    conn.execute("INSERT INTO bronze.wms__orders VALUES (?, ?)", ("o1", Decimal("9.00")))


def test_fanout_trap_refuses_to_compile(conn: duckdb.DuckDBPyConnection) -> None:
    """The guard fires before any SQL exists to run — fail closed."""
    project, catalog = load_fixture("fanout_trap")
    with pytest.raises(GuardrailError) as excinfo:
        build_project_ir(project, catalog)
    assert any(isinstance(leaf, GrainMismatch) for leaf in excinfo.value.collected)


def test_the_naive_sql_computes_the_wrong_number_3x(conn: duckdb.DuckDBPyConnection) -> None:
    """The hand-written naive SQL the compiler refuses to generate: shipping
    joined to line grain and summed is exactly 3× the true shipping."""
    _seed(conn)
    naive_row = conn.execute(
        "SELECT SUM(shipping), SUM(price + shipping) FROM bronze.wms__order_lines"
    ).fetchone()
    assert naive_row is not None
    naive_shipping, naive_landed = naive_row

    correct_row = conn.execute(
        "SELECT l.line_total + o.shipping FROM"
        " (SELECT order_id, SUM(price) AS line_total"
        "  FROM bronze.wms__order_lines GROUP BY order_id) AS l"
        " JOIN bronze.wms__orders AS o ON o.id = l.order_id"
    ).fetchone()
    assert correct_row is not None
    (correct_landed,) = correct_row
    correct_shipping_row = conn.execute("SELECT SUM(shipping) FROM bronze.wms__orders").fetchone()
    assert correct_shipping_row is not None
    (correct_shipping,) = correct_shipping_row

    assert isinstance(naive_shipping, Decimal)
    assert isinstance(correct_shipping, Decimal)
    assert correct_shipping == Decimal("9.00")
    assert naive_shipping == Decimal("27.00")  # 3× wrong — one copy per line
    assert naive_shipping == 3 * correct_shipping

    assert correct_landed == Decimal("39.00")
    assert naive_landed == Decimal("57.00")
    assert naive_landed != correct_landed  # why the compile error exists
