"""A mapping's constant, run as emitted on DuckDB (#375, S-0019/D-16).

Each shop's rows carry its own name, the Woo row's NULL quantity beside it
included: the constant reads nothing, so nothing it reads can be missing.
"""

from __future__ import annotations

import pytest
from support.compiling import fixture_sources
from support.execution import materialize, warehouse

from bloomery import Target, compile_project, load_project

pytestmark = pytest.mark.execution


def test_each_shop_s_rows_carry_its_constant() -> None:
    sources = fixture_sources("multi_source")
    sources["entity_model"] = sources["entity_model"].replace(
        "      gift_note: {type: string}\n",
        "      gift_note: {type: string}\n      channel: {type: string}\n",
        1,
    )
    for key, name in (("mapping_platform", "Shopify"), ("mapping_legacy", "WooCommerce")):
        sources[key] = sources[key].replace("fields:\n", f"fields:\n  channel: {{const: {name}}}\n", 1)
    artifacts = compile_project(load_project(sources), target=Target.SQLMESH, dialect="duckdb")

    conn = warehouse()
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
    conn.execute("INSERT INTO bronze.woo__order_lines VALUES ('W7', 1, 'GHI', NULL)")
    materialize(conn, artifacts)

    rows = conn.execute(
        "SELECT order_id, channel FROM silver.order_line ORDER BY order_id"
    ).fetchall()
    assert rows == [("S1", "Shopify"), ("W7", "WooCommerce")]
