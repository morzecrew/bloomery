"""The as-of join, executed (RFC 0023 §5.3, RFC 0009 §5.2 tier 4).

The compile-time checks next door prove the predicate is *emitted*; this
proves it is *right*, which is a different claim and the one the feature
exists for. A historical dimension is seeded the way a target's SCD2
machinery leaves it — one row per version per key, ``valid_to`` NULL on the
current one — and the mart's own emitted SQL runs over it on DuckDB.

The specimen: customer ``c1`` was ``smb`` until 2024-06-01 and ``enterprise``
after. Two orders straddle that boundary.

- ``o1`` (2024-03-10, 100.00) was placed while ``c1`` was ``smb``
- ``o2`` (2024-09-20, 250.00) was placed after the change

Point-in-time attribution means ``o1`` reports ``smb`` — the segment as it was
*then*, not the segment now. Reporting ``enterprise`` for ``o1`` is the defect
this whole feature is about: it is not a crash, it is revenue filed under the
wrong segment, and every row count stays plausible.

The second assertion is the fan-out the refusal exists for, kept for the
reason ``test_fanout_trap`` keeps its own (RFC 0006 D10): the same join
*without* the validity predicate is run here, and it returns two rows per
order and double the revenue. That is what an unanchored flatten emitted
before RFC 0023 P1 refused it.

All money is ``Decimal`` — floats never appear (RFC 0003 D5).
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Iterator
from decimal import Decimal

import duckdb
import pytest

from support.compiling import compile_fixture, extract_select

pytestmark = pytest.mark.execution

FIXTURE = "scd2_as_of"

#: ``(customer_id, segment, signed_up_at, valid_from, valid_to)`` — the shape a
#: target's SCD2 machinery leaves behind. ``valid_to`` NULL marks the version
#: that is current, which is what the emitted predicate's ``IS NULL`` arm reads.
VERSIONS = [
    ("c1", "smb", "2023-01-15", "2023-01-15", "2024-06-01"),
    ("c1", "enterprise", "2023-01-15", "2024-06-01", None),
    # A customer with one version only: the ordinary case must keep working.
    ("c2", "smb", "2023-05-02", "2023-05-02", None),
]

#: ``(order_id, customer_id, amount, order_date)``.
ORDERS = [
    ("o1", "c1", Decimal("100.00"), "2024-03-10"),  # before the segment change
    ("o2", "c1", Decimal("250.00"), "2024-09-20"),  # after it
    ("o3", "c2", Decimal("40.00"), "2024-07-04"),
]


@pytest.fixture(scope="module")
def warehouse() -> Iterator[duckdb.DuckDBPyConnection]:
    conn = duckdb.connect()
    conn.execute("CREATE SCHEMA silver")
    conn.execute("CREATE SCHEMA gold")
    conn.execute(
        "CREATE TABLE silver.customer (customer_id VARCHAR, segment VARCHAR, "
        "signed_up_at TIMESTAMP, valid_from TIMESTAMP, valid_to TIMESTAMP)"
    )
    conn.executemany("INSERT INTO silver.customer VALUES (?, ?, ?, ?, ?)", VERSIONS)
    conn.execute(
        "CREATE TABLE silver.\"order\" (order_id VARCHAR, customer_id VARCHAR, "
        "amount DECIMAL(12, 4), order_date DATE)"
    )
    conn.executemany('INSERT INTO silver."order" VALUES (?, ?, ?, ?)', ORDERS)

    artifact = next(
        a for a in compile_fixture(FIXTURE, dialect="duckdb") if a.path.endswith("mart_orders.sql")
    )
    conn.execute(f"CREATE TABLE gold.mart_orders AS {extract_select(artifact.content)}")
    yield conn
    conn.close()


def test_each_order_carries_the_segment_that_was_current_when_it_was_placed(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    """The feature, in one assertion. `o1` predates the segment change and must
    report the old segment; reporting today's would be the wrong number that
    looks right."""
    rows = warehouse.execute(
        "SELECT order_id, customer_segment FROM gold.mart_orders ORDER BY order_id"
    ).fetchall()

    assert rows == [("o1", "smb"), ("o2", "enterprise"), ("o3", "smb")]


def test_the_mart_keeps_the_base_grain(warehouse: duckdb.DuckDBPyConnection) -> None:
    """One row per order, not one per order per version — the property
    `HistoricalFanout` refuses an unanchored flatten to protect."""
    rows = warehouse.execute("SELECT COUNT(*) FROM gold.mart_orders").fetchone()
    assert rows is not None
    assert rows[0] == len(ORDERS)


def test_revenue_is_not_multiplied(warehouse: duckdb.DuckDBPyConnection) -> None:
    """The number a fan-out corrupts, asserted directly: 100 + 250 + 40."""
    total = warehouse.execute("SELECT SUM(amount) FROM gold.mart_orders").fetchone()
    assert total is not None
    assert total[0] == Decimal("390.0000")


def test_without_the_validity_predicate_the_same_join_doubles_c1(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    """Why the refusal exists, executed rather than argued (RFC 0006 D10).

    The emitted SQL is re-run with the two validity conditions stripped —
    which is exactly what an unanchored flatten produced — and `c1`'s orders
    match both versions. The row count and the revenue both double for that
    customer, and nothing in the result looks wrong.
    """
    artifact = next(
        a for a in compile_fixture(FIXTURE, dialect="duckdb") if a.path.endswith("mart_orders.sql")
    )
    select = extract_select(artifact.content)
    unguarded = re.sub(
        r"\s+AND \"order\"\.order_date >= customer_\.valid_from"
        r"\s+AND \(\s*customer_\.valid_to IS NULL OR "
        r"\"order\"\.order_date < customer_\.valid_to\s*\)",
        "",
        select,
    )
    assert unguarded != select, "the validity predicate was not found to strip"

    rows = warehouse.execute(
        f"SELECT order_id, COUNT(*) FROM ({unguarded}) AS naive "  # noqa: S608 — our own emitted SQL
        "GROUP BY order_id ORDER BY order_id"
    ).fetchall()
    assert rows == [("o1", 2), ("o2", 2), ("o3", 1)]

    total = warehouse.execute(
        f"SELECT SUM(amount) FROM ({unguarded}) AS naive"  # noqa: S608 — our own emitted SQL
    ).fetchone()
    assert total is not None
    assert total[0] == Decimal("740.0000")  # 390 correct, 350 counted twice


def test_the_anchor_is_read_from_the_base_row_not_the_run_date(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    """The join is anchored per row, so two orders of the same customer can
    legitimately disagree about that customer's attributes — which is the
    difference between point-in-time attribution and a current-view join."""
    segments = warehouse.execute(
        "SELECT DISTINCT customer_segment FROM gold.mart_orders WHERE customer_id = 'c1' "
        "ORDER BY customer_segment"
    ).fetchall()

    assert segments == [("enterprise",), ("smb",)]


def test_the_ordered_date_role_still_buckets(warehouse: duckdb.DuckDBPyConnection) -> None:
    """The anchor column doubles as a date role in this fixture; qualifying a
    join with it must not disturb its own projection."""
    rows = warehouse.execute(
        "SELECT order_id, ordered_month FROM gold.mart_orders ORDER BY order_id"
    ).fetchall()

    assert rows == [
        ("o1", datetime.date(2024, 3, 1)),
        ("o2", datetime.date(2024, 9, 1)),
        ("o3", datetime.date(2024, 7, 1)),
    ]
