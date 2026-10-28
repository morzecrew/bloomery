"""`pick` on DuckDB, executed (S-0095, #312).

МойСклад, amoCRM and Bitrix24 keep custom fields as lists of name and value
pairs, and a mapping's `from:` cannot select one by its name. `pick` does, and
every edge case the design measured is pinned here, plus the input as the JSON
text a `from:` extraction yields, end to end.
"""

from __future__ import annotations

import duckdb
import pytest
from sqlglot import exp
from support.compiling import FIXTURES, fixture_sources
from support.execution import materialize, warehouse
from support.pick_cases import CASES, NUMERIC_FIELD

from bloomery import Target, compile_project, load_catalog, load_project
from bloomery.dialects import get_dialect
from bloomery.transforms import DEFAULT_REGISTRY
from bloomery.typing import StringType

pytestmark = pytest.mark.execution


def _answer(text: str | None, *args: str) -> str | None:
    node = DEFAULT_REGISTRY["pick"].builder(exp.column("x"), *args, input_type=StringType())
    sql = get_dialect("duckdb").render(node)
    row = duckdb.connect().execute(f"SELECT {sql} FROM (SELECT ?::VARCHAR AS x)", [text]).fetchone()
    assert row is not None
    return row[0]


@pytest.mark.parametrize("case", sorted(CASES))
def test_every_measured_list_reads_as_designed(case: str) -> None:
    text, expected = CASES[case]

    assert _answer(text, "name", "a", "value") == expected


def test_a_numeric_field_matches_the_text_of_its_number() -> None:
    text, expected = NUMERIC_FIELD

    assert _answer(text, "name", "5", "value") == expected


def test_a_take_path_reaches_into_the_element() -> None:
    """amoCRM's custom fields keep the value one list deeper."""
    amo = '[{"field_code": "UTM_SOURCE", "values": [{"value": "google"}]}]'

    assert _answer(amo, "field_code", "UTM_SOURCE", "values[0].value") == "google"


def test_a_mapping_picks_from_the_text_its_from_extracts() -> None:
    sources = fixture_sources("ecom_basic")
    old = "      customer_id: {type: string, classification: pii}\n"
    assert sources["entity_model"].count(old) == 1
    sources["entity_model"] = sources["entity_model"].replace(
        old, old + "      channel: {type: string}\n"
    )
    old = '  customer_id: {from: "$.customer.id", transform: [to_string]}\n'
    assert sources["mapping_orders"].count(old) == 1
    sources["mapping_orders"] = sources["mapping_orders"].replace(
        old,
        old + '  channel: {from: "$.attributes", transform: [{pick: [name, "Источник заказа", value]}]}\n',
    )
    catalog = load_catalog((FIXTURES / "ecom_basic" / "catalog.yaml").read_text(encoding="utf-8"))
    connection = warehouse("bronze", "silver", "gold")
    connection.execute("CREATE TABLE bronze.shopify__orders (id VARCHAR, customer JSON, attributes JSON)")
    connection.execute(
        "INSERT INTO bronze.shopify__orders VALUES (?, ?, ?)",
        ("o1", '{"id": "c1"}', '[{"name": "Источник заказа", "value": "Сайт"}]'),
    )
    connection.execute(
        "CREATE TABLE bronze.shopify__order_lines (order_id VARCHAR, \"index\" BIGINT, "
        "total DECIMAL(12, 4), qty BIGINT, created_at VARCHAR)"
    )
    materialize(
        connection,
        compile_project(load_project(sources), target=Target.SQLMESH, dialect="duckdb", catalog=catalog),
    )

    assert connection.execute("SELECT order_id, channel FROM silver.\"order\"").fetchall() == [("o1", "Сайт")]
