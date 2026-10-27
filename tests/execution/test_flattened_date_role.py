"""A date role over a column flattened through a to-one step, executed
(S-0027/D-11, D-12, #310).

A line rarely carries its document's date at the source, so a line-grain mart
gets the order's date by flattening the order. Before D-11 the role had to name
a base column, and projects copied the order's date onto every line at
ingestion. Here the lines keep their own `order_date` (January) while the order
was placed in February, so the two roles must bucket differently, and the
`placed` buckets must come from the joined order.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import duckdb
import pytest
from support.compiling import FIXTURES, fixture_sources
from support.execution import materialize, warehouse

from bloomery import Target, build_project_ir, compile_project, load_catalog, load_project
from bloomery.errors import GuardrailError, UndeclaredZone

pytestmark = pytest.mark.execution

FIXTURE = "ecom_basic"


def _replaced(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, f"the fixture no longer reads {old!r}"
    return text.replace(old, new)


def _sources(*, zone: bool = True) -> dict[str, str]:
    sources = fixture_sources(FIXTURE)
    sources["entity_model"] = _replaced(
        sources["entity_model"],
        "      customer_id: {type: string, classification: pii}\n",
        "      customer_id: {type: string, classification: pii}\n"
        "      placed_at: {type: timestamp}\n",
    )
    placed = (
        '  placed_at:\n    from: "$.placed_at"\n'
        + ("    transform: [{parse_ts: ISO8601}, {to_utc: Europe/Paris}]\n" if zone else "    transform: [{parse_ts: ISO8601}]\n")
    )
    sources["mapping_orders"] = _replaced(
        sources["mapping_orders"],
        '  customer_id: {from: "$.customer.id", transform: [to_string]}\n',
        '  customer_id: {from: "$.customer.id", transform: [to_string]}\n' + placed,
    )
    sources["marts"] = _replaced(
        sources["marts"],
        "      - {date: order_date, role: ordered}\n",
        "      - {date: order_date, role: ordered}\n      - {date: order_placed_at, role: placed}\n",
    )
    return sources


def _catalog():  # noqa: ANN202 — Catalog
    return load_catalog((FIXTURES / FIXTURE / "catalog.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = warehouse()
    yield connection
    connection.close()


def test_the_buckets_come_from_the_joined_order(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        "CREATE TABLE bronze.shopify__order_lines ("
        'order_id VARCHAR, "index" BIGINT, total DECIMAL(12, 4), qty BIGINT, created_at VARCHAR)'
    )
    conn.executemany(
        "INSERT INTO bronze.shopify__order_lines VALUES (?, ?, ?, ?, ?)",
        [
            ("o1", 1, Decimal("30.00"), 3, "2024-01-02T03:04:05"),
            ("o1", 2, Decimal("8.00"), 2, "2024-01-02T03:04:05"),
        ],
    )
    conn.execute("CREATE TABLE bronze.shopify__orders (id VARCHAR, customer JSON, placed_at VARCHAR)")
    conn.execute(
        "INSERT INTO bronze.shopify__orders VALUES (?, ?, ?)",
        ("o1", '{"id": "c1"}', "2024-02-01T10:00:00"),
    )
    artifacts = compile_project(
        load_project(_sources()), target=Target.SQLMESH, dialect="duckdb", catalog=_catalog()
    )
    materialize(conn, artifacts)
    rows = conn.execute(
        "SELECT line_no, ordered_month, placed_day, placed_month FROM gold.mart_order_items ORDER BY 1"
    ).fetchall()
    assert rows == [
        (1, date(2024, 1, 1), date(2024, 2, 1), date(2024, 2, 1)),
        (2, date(2024, 1, 1), date(2024, 2, 1), date(2024, 2, 1)),
    ]


@pytest.mark.parametrize("target", [Target.DBT, Target.METRICFLOW, Target.CUBE])
def test_every_target_compiles_the_flattened_role(target: Target) -> None:
    """SQLMesh and dbt share the mart lowering that stopped on a bucket it could
    not find an owner for; MetricFlow and Cube read the built mart's columns."""
    artifacts = compile_project(
        load_project(_sources()), target=target, dialect="duckdb", catalog=_catalog()
    )
    assert artifacts


def test_the_joined_entity_s_clock_must_be_declared() -> None:
    """The buckets trace to `order.placed_at`, so the zone guard reads the
    order's wall clock. Traced to the mart's prefixed name instead, an
    undeclared clock on the joined entity would pass."""
    with pytest.raises(GuardrailError) as excinfo:
        build_project_ir(load_project(_sources(zone=False)), _catalog())
    refusals = [error for error in excinfo.value.collected if isinstance(error, UndeclaredZone)]
    assert refusals and "order.placed_at" in str(refusals[0])
