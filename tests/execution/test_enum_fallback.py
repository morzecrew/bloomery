"""An `enum_map` with a `"*"` fallback, executed on DuckDB (S-0096/D-1, #323).

amoCRM closes every pipeline in status 142 (won) or 143 (lost), and any other id
means the deal is open. Without a fallback the chain needed a nulling step ahead
of `enum_map` for `coalesce` to catch the unlisted ids, and that step turned the
implicit `coercible` rule off on a quality-carrying entity.
"""

from __future__ import annotations

from collections.abc import Iterator

import duckdb
import pytest
from support.compiling import FIXTURES, fixture_sources
from support.execution import materialize, warehouse

from bloomery import Target, build_project_ir, compile_project, load_catalog, load_project

pytestmark = pytest.mark.execution

FIXTURE = "semi_additive_inventory"


def _replaced(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, f"the fixture no longer reads {old!r}"
    return text.replace(old, new)


def _sources() -> dict[str, str]:
    sources = fixture_sources(FIXTURE)
    sources["entity_model"] = _replaced(
        sources["entity_model"],
        "      stock_level: {type: int, canonical: stock_level}\n",
        "      stock_level: {type: int, canonical: stock_level}\n      outcome: {type: string}\n",
    )
    sources["mapping"] = _replaced(
        sources["mapping"],
        "fields:\n",
        "fields:\n"
        "  outcome:\n"
        '    from: "$.status"\n'
        '    transform: [{enum_map: ["142", won, "143", lost, "*", open]}]\n',
    )
    return sources


def _catalog():  # noqa: ANN202 — Catalog
    return load_catalog((FIXTURES / FIXTURE / "catalog.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    artifacts = compile_project(
        load_project(_sources()), target=Target.SQLMESH, dialect="duckdb", catalog=_catalog()
    )
    connection = warehouse("bronze", "silver", "gold")
    connection.execute(
        "CREATE TABLE bronze.wms__stock_levels (warehouse VARCHAR, day VARCHAR, "
        "on_hand VARCHAR, status VARCHAR, _load_id VARCHAR, _ingested_at VARCHAR, "
        "_source_row_id VARCHAR, operator_note VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO bronze.wms__stock_levels VALUES (?, ?, '5', ?, 'L1', '2026-01-01 00:00:00', ?, NULL)",
        [
            ("w1", "2026-01-01", "142", "r1"),
            ("w2", "2026-01-01", "143", "r2"),
            ("w3", "2026-01-01", "31234", "r3"),
            ("w4", "2026-01-01", None, "r4"),
        ],
    )
    materialize(connection, artifacts)
    yield connection
    connection.close()


def test_listed_ids_map_and_every_other_id_takes_the_fallback(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    rows = conn.execute(
        "SELECT _source_row_id, outcome FROM silver.inventory_level ORDER BY 1"
    ).fetchall()

    assert rows == [("r1", "won"), ("r2", "lost"), ("r3", "open"), ("r4", None)]


def test_the_implicit_coercible_rule_stays_on() -> None:
    """The fallback nulls nothing, so the field keeps the rule the reporter's
    nulling step had turned off."""
    ir = build_project_ir(load_project(_sources()), _catalog())
    (entity,) = (entity for entity in ir.entities if entity.name == "inventory_level")

    assert "outcome_coercible" in {rule.name for rule in entity.quality}
