"""A constant key part, run as emitted on DuckDB (#380, S-0019/D-17).

Two shops whose own ids overlap land in one merged entity as distinct rows,
because each mapping's key carries its shop. The collision audit, which refuses
a key two sources claim, stays silent on them. And a row quarantined by one
shop's rule replays with its shop: replay re-runs the branch's lowering, and
the constant reads nothing of the payload.
"""

from __future__ import annotations

from collections.abc import Iterator

import duckdb
import pytest
from support.compiling import fixture_sources
from support.execution import audit_body, materialize, replay_statements, warehouse

from bloomery import Target, compile_project, load_project
from bloomery.emit import ArtifactKind, EmittedArtifact

pytestmark = pytest.mark.execution


def _keyed_by_shop(fixture: str) -> dict[str, str]:
    sources = fixture_sources(fixture)

    def swap(key: str, old: str, new: str) -> None:
        assert sources[key].count(old) == 1, (key, old)
        sources[key] = sources[key].replace(old, new)

    swap("entity_model", "    key: [order_id, line_no]\n", "    key: [shop, order_id, line_no]\n")
    swap(
        "entity_model",
        "      order_id: {type: string, required: true}\n",
        "      shop: {type: string, required: true}\n"
        "      order_id: {type: string, required: true}\n",
    )
    swap("mapping_platform", "key:\n", "key:\n  shop: {const: Shopify}\n")
    swap("mapping_legacy", "key:\n", "key:\n  shop: {const: WooCommerce}\n")
    return sources


def _compile(sources: dict[str, str]) -> tuple[EmittedArtifact, ...]:
    return compile_project(load_project(sources), target=Target.SQLMESH, dialect="duckdb")


def _rows(conn: duckdb.DuckDBPyConnection, sql: str) -> list[tuple[object, ...]]:
    return [tuple(row) for row in conn.execute(sql).fetchall()]


@pytest.fixture
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = warehouse()
    try:
        yield connection
    finally:
        connection.close()


def test_overlapping_ids_from_two_shops_are_two_rows(conn: duckdb.DuckDBPyConnection) -> None:
    """Both shops claim order `S1` line 1. Keyed by the ids alone this is the
    collision audit's red case (`test_multi_source`); keyed by the shop too it
    is two orders."""
    conn.execute(
        "CREATE TABLE bronze.shopify__order_lines ("
        '  "order" JSON, position INTEGER, variant JSON, quantity INTEGER, properties JSON)'
    )
    conn.execute(
        "CREATE TABLE bronze.woo__order_lines ("
        "  order_number VARCHAR, item_index INTEGER, product_sku VARCHAR, qty INTEGER)"
    )
    conn.execute(
        "INSERT INTO bronze.shopify__order_lines VALUES "
        "('{\"id\": \"S1\"}', 1, '{\"sku\": \"ABC\"}', 2, '{}')"
    )
    conn.execute("INSERT INTO bronze.woo__order_lines VALUES ('S1', 1, 'GHI', 5)")
    artifacts = _compile(_keyed_by_shop("multi_source"))
    materialize(conn, artifacts)

    assert _rows(conn, "SELECT shop, order_id, line_no, sku FROM silver.order_line ORDER BY 1") == [
        ("Shopify", "S1", 1, "ABC"),
        ("WooCommerce", "S1", 1, "GHI"),
    ]
    (collision,) = (
        a
        for a in artifacts
        if a.kind is ArtifactKind.AUDIT and a.path.endswith("_source_collision.sql")
    )
    assert _rows(conn, audit_body(collision, "silver.order_line")) == []


def _quality_bronze(conn: duckdb.DuckDBPyConnection, *, woo_state: str, shop: str = "") -> None:
    """`multi_source_quality`'s bronze, one `B-3` line from each shop; `shop`
    adds the column Shopify's export would name its shop in."""
    conn.execute(
        f"""
        CREATE TABLE bronze.shopify__order_lines (
          "order" JSON, position VARCHAR, variant JSON, quantity VARCHAR,
          properties JSON, created_at VARCHAR, financial_status VARCHAR,
          _load_id VARCHAR, _ingested_at VARCHAR, _source_row_id VARCHAR
          {", shop VARCHAR" if shop else ""}
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE bronze.woo__order_lines (
          order_number VARCHAR, item_index VARCHAR, product_sku VARCHAR, qty VARCHAR,
          created VARCHAR, state VARCHAR,
          _load_id VARCHAR, _ingested_at VARCHAR, _source_row_id VARCHAR
        )
        """
    )
    conn.execute(
        "INSERT INTO bronze.shopify__order_lines VALUES (json_object('id', 'B-3'), '1', "
        "json_object('sku', 'SKU-1'), '2', json_object('gift_note', NULL), "
        "'2024-03-01T00:00:00', 'paid', 'load-1', '2024-03-10T00:00:00', 's1'"
        + (f", '{shop}')" if shop else ")")
    )
    conn.execute(
        "INSERT INTO bronze.woo__order_lines VALUES ('B-3', '1', 'SKU-7', '1', "
        f"'2024-03-03T00:00:00', '{woo_state}', 'load-1', '2024-03-10T00:00:00', 'w3')"
    )


def test_a_shop_one_source_reads_is_judged_on_that_source_alone(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """Shopify's export names its shop and Woo's mapping sets it. The shop's
    `coercible` rule, which Shopify's read part gets, reads no sources on
    Woo's branch, so Woo's row is not quarantined for a cast it never made."""
    _quality_bronze(conn, woo_state="COMPLETE", shop="Shopify")
    sources = _keyed_by_shop("multi_source_quality")
    assert sources["mapping_platform"].count("  shop: {const: Shopify}\n") == 1
    sources["mapping_platform"] = sources["mapping_platform"].replace(
        "  shop: {const: Shopify}\n", '  shop: {from: "$.shop"}\n'
    )
    materialize(conn, _compile(sources))

    assert _rows(conn, "SELECT shop, order_id FROM silver.order_line ORDER BY 1") == [
        ("Shopify", "B-3"),
        ("WooCommerce", "B-3"),
    ]
    assert _rows(conn, "SELECT count(*) FROM silver.order_line__reject") == [(0,)]


def test_a_quarantined_row_replays_with_its_shop(conn: duckdb.DuckDBPyConnection) -> None:
    """Woo's `B-3` carries a status only Shopify's chain maps. Once Woo's chain
    learns it, replay admits the row, keyed by Woo's constant."""
    _quality_bronze(conn, woo_state="reversed")
    sources = _keyed_by_shop("multi_source_quality")
    materialize(conn, _compile(sources))

    assert _rows(conn, "SELECT shop, order_id FROM silver.order_line") == [("Shopify", "B-3")]
    assert _rows(conn, "SELECT source_relation, _source_row_id FROM silver.order_line__reject") == [
        ("woo__order_lines", "w3")
    ]

    anchor = "{enum_map: [PROCESSING, open, COMPLETE, closed]}"
    assert sources["mapping_legacy"].count(anchor) == 1
    sources["mapping_legacy"] = sources["mapping_legacy"].replace(
        anchor, "{enum_map: [PROCESSING, open, COMPLETE, closed, reversed, closed]}"
    )
    # Bronze's window has moved past `w3`, which is why it waits in the reject
    # table: only replay can admit it now, so the rebuild below cannot.
    conn.execute("DELETE FROM bronze.woo__order_lines WHERE _source_row_id = 'w3'")
    artifacts = _compile(sources)
    materialize(conn, artifacts)
    assert _rows(conn, "SELECT shop FROM silver.order_line") == [("Shopify",)]
    (replay,) = (a for a in artifacts if a.path.endswith("replay/order_line.sql"))
    for statement in replay_statements(replay):
        conn.execute(statement)

    assert _rows(conn, "SELECT shop, order_id, status FROM silver.order_line ORDER BY 1") == [
        # Shopify's chain maps `paid` to `closed`, Woo's now maps `reversed` there.
        ("Shopify", "B-3", "closed"),
        ("WooCommerce", "B-3", "closed"),
    ]
