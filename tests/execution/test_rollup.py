"""Rollup execution (RFC 0058 D6): the number the rollup table holds against
the same request computed from the detail beneath it.

This is the acceptance the design asked for and the only one that can fail for
the reason the feature exists. A golden proves the SQL is the SQL that was
written; the corpus proves an *unsafe* rollup is refused. Neither says the safe
one is right. So the rollup is built against a real engine and every row of it
is compared to the aggregate over the relation it derives from — which is what
"the same request computed from silver" means once the mart between them has
itself been built from silver.

All assertions are `Decimal`; floats never appear (RFC 0003 D5).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import duckdb
import pytest
from support.compiling import compile_fixture
from support.execution import materialize, warehouse

pytestmark = pytest.mark.execution


@pytest.fixture
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = warehouse()
    yield connection
    connection.close()


def _seed(conn: duckdb.DuckDBPyConnection) -> None:
    """Two customers across two months, and a customer whose lines fall in
    both — so a rollup that grouped wrongly would show up as a total in the
    wrong bucket rather than as a total that happens to match."""

    conn.execute(
        "CREATE TABLE bronze.shop__orders (id VARCHAR, customer_id VARCHAR)"
    )
    conn.executemany(
        "INSERT INTO bronze.shop__orders VALUES (?, ?)",
        [("o1", "c1"), ("o2", "c2"), ("o3", "c1")],
    )
    conn.execute(
        "CREATE TABLE bronze.shop__order_lines ("
        "order_id VARCHAR, index INTEGER, price DECIMAL(12, 4), qty INTEGER, created_at VARCHAR)"
    )
    conn.executemany(
        "INSERT INTO bronze.shop__order_lines VALUES (?, ?, ?, ?, ?)",
        [
            ("o1", 1, Decimal("10.00"), 3, "2024-01-05T00:00:00"),
            ("o1", 2, Decimal("2.50"), 4, "2024-01-05T00:00:00"),
            ("o2", 1, Decimal("7.00"), 1, "2024-01-20T00:00:00"),
            # c1 again, a month later: the row that splits one customer across
            # two groups.
            ("o3", 1, Decimal("100.00"), 2, "2024-02-11T00:00:00"),
        ],
    )


def test_the_rollup_holds_what_the_detail_says_it_should(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """Every row of the rollup, against the same aggregate over its parent.

    Compared as whole result sets rather than by a total: a rollup whose groups
    are wrong can still sum to the right number overall, and that is precisely
    the failure a coarser assertion would pass.
    """

    _seed(conn)
    materialize(conn, compile_fixture("rollup_mart"))

    rolled = conn.execute(
        "SELECT order_customer_id, ordered_month, gross_revenue "
        "FROM gold.mart_order_items_monthly "
        "ORDER BY order_customer_id, ordered_month"
    ).fetchall()
    from_detail = conn.execute(
        "SELECT order_customer_id, ordered_month, SUM(unit_price * quantity) "
        "FROM gold.mart_order_items "
        "GROUP BY order_customer_id, ordered_month "
        "ORDER BY order_customer_id, ordered_month"
    ).fetchall()

    assert rolled == from_detail
    assert rolled == [
        ("c1", date(2024, 1, 1), Decimal("40.0000")),
        ("c1", date(2024, 2, 1), Decimal("200.0000")),
        ("c2", date(2024, 1, 1), Decimal("7.0000")),
    ]


def test_the_rollup_totals_what_the_silver_relation_does(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """The whole chain in one assertion: silver, the mart built from it, and
    the rollup built from the mart all agree on the total.

    The mart is a projection, so this is not a second reading of the same
    number — it is the claim that the aggregate the rollup materialized is the
    one the detail rows add up to.
    """

    _seed(conn)
    materialize(conn, compile_fixture("rollup_mart"))

    rolled = conn.execute("SELECT SUM(gross_revenue) FROM gold.mart_order_items_monthly").fetchone()
    silver = conn.execute("SELECT SUM(unit_price * quantity) FROM silver.order_item").fetchone()

    assert rolled is not None
    assert silver is not None
    assert rolled[0] == silver[0] == Decimal("247.0000")
