"""Planner execution acceptance (RFC 0009 §5.10, RFC 0011 D12, RFC 0013 §6):
run the SQL the MetricFlow planner renders against DuckDB marts built from
the emitted SQLMesh artifacts, and hard-code the additivity ledger — these
are the exact failure modes that make a BI product untrustworthy:

- semi-additive inventory: warehouse-A Jan 1–3 is **90, never 270**; global
  Jan 3 is **130** (A 90 + B 40 — summing across non-``over`` dimensions is
  correct); by month over three months is **three rows** (issue #241, fixed
  at the 0.211 pin);
- non-additive AOV: **2727.27**, never the 6000 of an average-of-averages
  nor the 12000/15000 family of summed ratios; by store A 10000 / B 2000;
- role-playing dates: ordered vs shipped attribution give different,
  correct totals through the planner (the M5 numbers).

Under the MetricFlow backend these assert *our mapping into MetricFlow* —
a wrong ``window_choice`` or a measure emitted where a ratio metric belongs
fails here (RFC 0011 D12)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import duckdb
import pytest

from bloomery import MetricRequest, OrderSpec
from bloomery.planner import FilterExpr
from support.compiling import compile_fixture
from support.planning import fixture_ir, make_planner, normalize_month, quantized

from .test_marts import materialize

pytestmark = pytest.mark.execution

PLANNER = make_planner()


@pytest.fixture
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = duckdb.connect(":memory:")
    connection.execute("SET TimeZone = 'UTC'")
    for schema in ("bronze", "silver", "gold"):
        connection.execute(f"CREATE SCHEMA {schema}")
    yield connection
    connection.close()


def run(
    conn: duckdb.DuckDBPyConnection, fixture: str, request: MetricRequest
) -> list[tuple[object, ...]]:
    plan = PLANNER.plan(fixture_ir(fixture), request, dialect="duckdb")
    return conn.execute(plan.sql).fetchall()


# ....................... #
# semi_additive_inventory — the amended (satisfiable) seed (RFC 0009 D20)


def _seed_inventory(conn: duckdb.DuckDBPyConnection) -> None:
    """The spike-v2 seed: A 100/80/90 over Jan 1–3, B 40 on Jan 3, plus
    Feb/Mar rows so by-month grouping yields three rows."""
    conn.execute(
        "CREATE TABLE bronze.wms__stock_levels (warehouse VARCHAR, day VARCHAR, on_hand BIGINT)"
    )
    conn.executemany(
        "INSERT INTO bronze.wms__stock_levels VALUES (?, ?, ?)",
        [
            ("A", "2024-01-01", 100),
            ("A", "2024-01-02", 80),
            ("A", "2024-01-03", 90),
            ("B", "2024-01-03", 40),
            ("A", "2024-02-10", 85),
            ("A", "2024-02-20", 75),
            ("A", "2024-03-05", 65),
            ("A", "2024-03-15", 95),
        ],
    )
    materialize(conn, compile_fixture("semi_additive_inventory"))


JAN_1_TO_3 = FilterExpr("snapshot_day", "between", ("2024-01-01", "2024-01-03"))
JAN_3 = FilterExpr("snapshot_day", "eq", ("2024-01-03",))


def test_semi_additive_warehouse_a_over_three_days_is_90_not_270(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    _seed_inventory(conn)
    request = MetricRequest(
        metrics=("stock_on_hand",),
        filters=(JAN_1_TO_3, FilterExpr("warehouse_id", "eq", ("A",))),
    )
    assert run(conn, "semi_additive_inventory", request) == [(90,)]


def test_semi_additive_global_jan_3_is_130(conn: duckdb.DuckDBPyConnection) -> None:
    """A 90 + B 40 — summing across the non-``over`` dimension is correct;
    130 is also the unscoped Jan 1–3 answer (the global MAX date is Jan 3)."""
    _seed_inventory(conn)
    assert run(
        conn,
        "semi_additive_inventory",
        MetricRequest(metrics=("stock_on_hand",), filters=(JAN_3,)),
    ) == [(130,)]
    assert run(
        conn,
        "semi_additive_inventory",
        MetricRequest(metrics=("stock_on_hand",), filters=(JAN_1_TO_3,)),
    ) == [(130,)]


def test_semi_additive_by_warehouse_on_jan_3(conn: duckdb.DuckDBPyConnection) -> None:
    _seed_inventory(conn)
    request = MetricRequest(
        metrics=("stock_on_hand",),
        dimensions=("warehouse_id",),
        filters=(JAN_3,),
        order_by=(OrderSpec("warehouse_id"),),
    )
    assert run(conn, "semi_additive_inventory", request) == [("A", 90), ("B", 40)]


def test_semi_additive_by_month_gives_three_rows(conn: duckdb.DuckDBPyConnection) -> None:
    """The issue-#241 case (RFC 0013 §9, fixed at the pin): grouping BY the
    non-additive dimension's coarser grain returns the full series — last
    value per month, then summed across warehouses."""
    _seed_inventory(conn)
    request = MetricRequest(
        metrics=("stock_on_hand",),
        dimensions=("snapshot_month",),
        order_by=(OrderSpec("snapshot_month"),),
    )
    rows = [
        (normalize_month(month), balance)
        for month, balance in run(conn, "semi_additive_inventory", request)
    ]
    assert rows == [
        (date(2024, 1, 1), 130),
        (date(2024, 2, 1), 75),
        (date(2024, 3, 1), 95),
    ]


# ....................... #
# non_additive_aov — 2727.27, never the wrong-number families


def _seed_orders(conn: duckdb.DuckDBPyConnection) -> None:
    """Store A: 10 orders totalling 100 000 (AOV 10 000); store B: 100
    orders totalling 200 000 (AOV 2 000). Overall AOV = 300 000 / 110."""
    conn.execute(
        "CREATE TABLE bronze.pos__orders ("
        "id VARCHAR, store VARCHAR, amount DECIMAL(12, 4), order_date VARCHAR)"
    )
    rows = [
        (f"a{i}", "A", Decimal("10000.00"), f"2024-01-{i % 28 + 1:02d}") for i in range(10)
    ] + [(f"b{i}", "B", Decimal("2000.00"), f"2024-01-{i % 28 + 1:02d}") for i in range(100)]
    conn.executemany("INSERT INTO bronze.pos__orders VALUES (?, ?, ?, ?)", rows)
    materialize(conn, compile_fixture("non_additive_aov"))


def test_overall_aov_is_2727_27(conn: duckdb.DuckDBPyConnection) -> None:
    _seed_orders(conn)
    rows = run(conn, "non_additive_aov", MetricRequest(metrics=("average_order_value",)))
    assert len(rows) == 1
    aov = quantized(rows[0][0])
    assert aov == Decimal("2727.27")
    # The named wrong-number families (RFC 0009 §5.10): 6000 is the
    # average-of-averages, 12000/15000 the summed-ratio shapes.
    assert aov not in {Decimal(n) for n in (6000, 12000, 15000)}


def test_aov_by_store(conn: duckdb.DuckDBPyConnection) -> None:
    _seed_orders(conn)
    request = MetricRequest(
        metrics=("average_order_value",),
        dimensions=("store",),
        order_by=(OrderSpec("store"),),
    )
    rows = [(store, quantized(value)) for store, value in run(conn, "non_additive_aov", request)]
    assert rows == [("A", Decimal("10000.00")), ("B", Decimal("2000.00"))]


def test_aov_components_stay_exact(conn: duckdb.DuckDBPyConnection) -> None:
    _seed_orders(conn)
    rows = run(conn, "non_additive_aov", MetricRequest(metrics=("order_count", "revenue")))
    count, revenue = rows[0]
    assert count == 110
    assert Decimal(str(revenue)) == Decimal("300000.00")


# ....................... #
# role_playing_dates — the M5 numbers, now through the planner


def _seed_role_playing(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        "CREATE TABLE bronze.oms__orders ("
        "id VARCHAR, amount DECIMAL(12, 4), order_date VARCHAR, ship_date VARCHAR)"
    )
    conn.executemany(
        "INSERT INTO bronze.oms__orders VALUES (?, ?, ?, ?)",
        [
            ("o1", Decimal("100.00"), "2024-01-15", "2024-01-20"),
            ("o2", Decimal("50.00"), "2024-01-31", "2024-02-02"),
            ("o3", Decimal("25.00"), "2024-02-10", "2024-02-12"),
        ],
    )
    materialize(conn, compile_fixture("role_playing_dates"))


def test_ordered_vs_shipped_attribution_through_the_planner(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """The role-playing acceptance through the planner (RFC 0011 D6): the
    same measure grouped by the two roles yields different splits — order
    attribution vs shipment attribution — and both are right (M5 numbers)."""
    _seed_role_playing(conn)
    by_role: dict[str, list[tuple[date, Decimal]]] = {}
    for role in ("ordered_month", "shipped_month"):
        request = MetricRequest(
            metrics=("revenue",), dimensions=(role,), order_by=(OrderSpec(role),)
        )
        by_role[role] = [
            (normalize_month(month), Decimal(str(total)))
            for month, total in run(conn, "role_playing_dates", request)
        ]
    assert by_role["ordered_month"] == [
        (date(2024, 1, 1), Decimal("150.00")),
        (date(2024, 2, 1), Decimal("25.00")),
    ]
    assert by_role["shipped_month"] == [
        (date(2024, 1, 1), Decimal("100.00")),
        (date(2024, 2, 1), Decimal("75.00")),
    ]
    assert by_role["ordered_month"] != by_role["shipped_month"]


# ....................... #
# multi_mart_refusal — refusal executes nothing; own metrics execute fine


def _seed_multi_mart(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        "CREATE TABLE bronze.mmr__orders (id VARCHAR, ship_cost DECIMAL(12, 4), order_date VARCHAR)"
    )
    conn.executemany(
        "INSERT INTO bronze.mmr__orders VALUES (?, ?, ?)",
        [("o1", Decimal("5.00"), "2024-01-10"), ("o2", Decimal("7.00"), "2024-01-11")],
    )
    conn.execute(
        "CREATE TABLE bronze.mmr__order_items ("
        "order_id VARCHAR, line_no BIGINT, discount DECIMAL(12, 4), item_date VARCHAR)"
    )
    conn.executemany(
        "INSERT INTO bronze.mmr__order_items VALUES (?, ?, ?, ?)",
        [
            ("o1", 1, Decimal("1.50"), "2024-01-10"),
            ("o1", 2, Decimal("2.00"), "2024-01-10"),
            ("o2", 1, Decimal("1.00"), "2024-01-11"),
        ],
    )
    materialize(conn, compile_fixture("multi_mart_refusal"))


def test_each_mart_answers_its_own_metric(conn: duckdb.DuckDBPyConnection) -> None:
    _seed_multi_mart(conn)
    shipping = run(conn, "multi_mart_refusal", MetricRequest(metrics=("shipping_cost",)))
    discount = run(conn, "multi_mart_refusal", MetricRequest(metrics=("line_discount",)))
    assert Decimal(str(shipping[0][0])) == Decimal("12.00")
    assert Decimal(str(discount[0][0])) == Decimal("4.50")
