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
