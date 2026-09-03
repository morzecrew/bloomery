"""Path-conflict execution (RFC 0006 §5.5/§6): both columns materialize and
the reconciliation audit surfaces exactly the rows where they disagree."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import duckdb
import pytest

from bloomery.emit import ArtifactKind
from support.compiling import compile_fixture, extract_select
from support.execution import warehouse

pytestmark = pytest.mark.execution


@pytest.fixture
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = warehouse("bronze", "silver")
    yield connection
    connection.close()


def _seed(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        "CREATE TABLE bronze.shop__items ("
        "id VARCHAR, total DECIMAL(12, 4), qty BIGINT, price DECIMAL(12, 4))"
    )
    conn.executemany(
        "INSERT INTO bronze.shop__items VALUES (?, ?, ?, ?)",
        [
            ("i1", Decimal("30.00"), 3, Decimal("10.00")),  # paths agree
            ("i2", Decimal("30.00"), 3, Decimal("11.00")),  # paths disagree
        ],
    )


def test_both_columns_execute_and_the_audit_finds_the_disagreement(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    _seed(conn)
    artifacts = compile_fixture("path_conflict")
    model = next(a for a in artifacts if a.kind is ArtifactKind.MODEL)
    audit = next(a for a in artifacts if a.kind is ArtifactKind.AUDIT)

    conn.execute(f"CREATE TABLE silver.item AS {extract_select(model.content)}")
    rows = conn.execute(
        "SELECT item_id, net_price, net_price__direct FROM silver.item ORDER BY item_id"
    ).fetchall()
    assert rows == [
        ("i1", Decimal("10.00"), Decimal("10.00")),
        ("i2", Decimal("10.00"), Decimal("11.00")),
    ]

    audit_select = extract_select(audit.content).replace("@this_model", "silver.item")
    disagreeing = conn.execute(audit_select).fetchall()
    assert [row[0] for row in disagreeing] == ["i2"]  # row-level disagreement


def _seed_merged(conn: duckdb.DuckDBPyConnection) -> None:
    """Two shops, disjoint keys, and each carrying the direct price at its own
    path — `$.price` on one relation and `$.unit_amount` on the other, neither
    of which exists on the other's table."""
    conn.execute(
        "CREATE TABLE bronze.shopify__items ("
        "order_ref VARCHAR, position BIGINT, total DECIMAL(12, 4), quantity BIGINT, "
        "price DECIMAL(12, 4))"
    )
    conn.executemany(
        "INSERT INTO bronze.shopify__items VALUES (?, ?, ?, ?, ?)",
        [
            ("o1", 1, Decimal("30.00"), 3, Decimal("10.00")),  # paths agree
            ("o1", 2, Decimal("30.00"), 3, Decimal("11.00")),  # paths disagree
        ],
    )
    conn.execute(
        "CREATE TABLE bronze.woo__items ("
        "order_number VARCHAR, item_index BIGINT, line_gross DECIMAL(12, 4), qty BIGINT, "
        "unit_amount DECIMAL(12, 4))"
    )
    conn.executemany(
        "INSERT INTO bronze.woo__items VALUES (?, ?, ?, ?, ?)",
        [
            ("o2", 1, Decimal("50.00"), 5, Decimal("10.00")),  # paths agree
            ("o2", 2, Decimal("50.00"), 5, Decimal("12.50")),  # paths disagree
        ],
    )


def test_a_merged_entity_reconciles_each_branch_against_its_own_path(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """RFC 0024 D36 executed. The claim a compile-time assertion cannot make:
    the union runs, each branch's shadow reads a column that exists on *that*
    relation, and the reconcile audit finds one disagreement per shop.

    A single shadow for the whole entity — the shape D28 refused — would not
    fail an IR assertion here, it would fail at run time with a binder error
    naming `price` on `woo__items`.
    """
    _seed_merged(conn)
    artifacts = compile_fixture("path_conflict_merged")
    model = next(
        a for a in artifacts if a.kind is ArtifactKind.MODEL and a.path.endswith("item.sql")
    )
    audit = next(
        a
        for a in artifacts
        if a.kind is ArtifactKind.AUDIT and "reconcile" in a.path
    )

    conn.execute(f"CREATE TABLE silver.item AS {extract_select(model.content)}")
    rows = conn.execute(
        "SELECT _source, order_id, line_no, net_price, net_price__direct "
        "FROM silver.item ORDER BY order_id, line_no"
    ).fetchall()
    assert rows == [
        ("shopify__items", "o1", 1, Decimal("10.00"), Decimal("10.00")),
        ("shopify__items", "o1", 2, Decimal("10.00"), Decimal("11.00")),
        ("woo__items", "o2", 1, Decimal("10.00"), Decimal("10.00")),
        ("woo__items", "o2", 2, Decimal("10.00"), Decimal("12.50")),
    ]

    audit_select = extract_select(audit.content).replace("@this_model", "silver.item")
    disagreeing = conn.execute(audit_select).fetchall()
    # One per shop, and the pair is the point: an audit reading one branch's
    # shadow for both would have found either two rows from one source or none.
    assert len(disagreeing) == 2
