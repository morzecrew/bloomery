"""A bad value at an *inner* cast of a transform chain is quarantined, executed
(S-0033 §5.2, D-3).

`_try_cast_shape` rewrote only a chain's outermost cast: SQLGlot's `transform`
does not descend into a node it has just replaced. A money chain,
`{to_decimal: [16, 0]}` then `{multiply: "0.01"}`, therefore kept a plain inner
`CAST`, and a bronze `'abc'` aborted the whole run instead of becoming one
quarantined row. Every engine was affected; this runs it on DuckDB.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import duckdb
import pytest
from support.compiling import FIXTURES, fixture_sources
from support.execution import materialize, warehouse

from bloomery import Target, compile_project, load_catalog, load_project

pytestmark = pytest.mark.execution

FIXTURE = "semi_additive_inventory"


def _replaced(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, f"the fixture no longer reads {old!r}"
    return text.replace(old, new)


@pytest.fixture(scope="module")
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    sources = fixture_sources(FIXTURE)
    sources["entity_model"] = _replaced(
        sources["entity_model"],
        "      stock_level: {type: int, canonical: stock_level}\n",
        "      stock_level: {type: int, canonical: stock_level}\n"
        '      total: {type: "decimal(18,2)"}\n',
    )
    sources["mapping"] = _replaced(
        sources["mapping"],
        "fields:\n",
        "fields:\n"
        "  total:\n"
        '    from: "$.sum"\n'
        '    transform: [{to_decimal: [16, 0]}, {multiply: "0.01"}]\n',
    )
    catalog = load_catalog((FIXTURES / FIXTURE / "catalog.yaml").read_text(encoding="utf-8"))
    artifacts = compile_project(
        load_project(sources), target=Target.SQLMESH, dialect="duckdb", catalog=catalog
    )
    connection = warehouse("bronze", "silver", "gold")
    connection.execute(
        "CREATE TABLE bronze.wms__stock_levels (warehouse VARCHAR, day VARCHAR, "
        "on_hand VARCHAR, sku VARCHAR, sum VARCHAR, _load_id VARCHAR, "
        "_ingested_at VARCHAR, _source_row_id VARCHAR, operator_note VARCHAR)"
    )
    connection.execute(
        "INSERT INTO bronze.wms__stock_levels VALUES "
        "('w1', '2026-01-01', '5', 's1', '12345', 'L1', '2026-01-01 00:00:00', 'r1', NULL), "
        "('w2', '2026-01-02', '7', 's2', 'abc', 'L1', '2026-01-01 00:00:00', 'r2', NULL)"
    )
    materialize(connection, artifacts)
    yield connection
    connection.close()


def test_the_clean_row_keeps_its_value(conn: duckdb.DuckDBPyConnection) -> None:
    kept = conn.execute("SELECT _source_row_id, total FROM silver.inventory_level").fetchall()
    assert kept == [("r1", Decimal("123.45"))]


def test_a_bad_value_at_the_inner_cast_is_quarantined(conn: duckdb.DuckDBPyConnection) -> None:
    rejected = dict(
        conn.execute(
            "SELECT _source_row_id, failed_rules FROM silver.inventory_level__reject"
        ).fetchall()
    )
    assert "total_coercible" in rejected["r2"]
