"""Engine tier (RFC 0009 §5.2 tier 5): the ecom_basic silver + mart SQL,
compiled under the trino dialect, executed against real Trino via
testcontainers — the mirror of :mod:`tests.engines.test_postgres_execution`.

:mod:`tests.engines.test_trino` executes the quality pipeline here; nothing
executed the *ordinary* path — recipe derivation, JSON extraction, the mart
join, the date roles, the generated calendar — on the engine the lakehouse
example advertises. Rendering is not execution (the lesson every file in this
directory restates), and the calendar in particular renders as
``UNNEST(SEQUENCE(...))`` here, a construction no other tier runs.

Same seed and same assertions as the Postgres mirror, so a disagreement
between the two engines is legible as a diff.

**Memory connector, not Iceberg** — the divergence from §5.2's
"trino+iceberg+minio" sketch that :mod:`tests.engines.test_trino` records
(RFC 0009 D21): bloomery emits SELECTs and models, never storage-format DDL,
so a table format would be moving parts serving no assertion here.

Opt-in (Docker required); excluded from ``just test``.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterator
from decimal import Decimal
from pathlib import PurePosixPath

import pytest
import trino
from testcontainers.community.trino import TrinoContainer

from support.compiling import compile_fixture, extract_select

pytestmark = pytest.mark.engine("trino")

#: Pinned for the reason :mod:`tests.engines.test_trino` gives: a tier that
#: silently changes engine version cannot tell a regression from an upgrade.
IMAGE = "trinodb/trino:483"

#: The Postgres mirror's seed, verbatim — the JSON payloads land as text
#: because that is how bronze arrives (VARCHAR + JSON_EXTRACT_SCALAR is the
#: emitted reading).
LINES = [
    ("o1", 1, "100.000", 10, "2024-01-02T03:04:05"),
    ("o1", 2, "59.976", 3, "2024-01-02T04:00:00"),
    ("o2", 1, "20.000", 2, "2024-02-05T10:00:00"),
]
ORDERS = [
    ("o1", '{"id": "c1"}'),
    ("o2", '{"id": "c2"}'),
]


def _run(connection: trino.dbapi.Connection, statement: str) -> list[list[object]]:
    cursor = connection.cursor()
    cursor.execute(statement)
    return cursor.fetchall()


@pytest.fixture(scope="module")
def seeded() -> Iterator[trino.dbapi.Connection]:
    with TrinoContainer(IMAGE) as container:
        connection = trino.dbapi.connect(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(8080)),
            user="bloomery",
            catalog="memory",
            schema="default",
        )
        for schema in ("bronze", "silver", "gold"):
            _run(connection, f"CREATE SCHEMA IF NOT EXISTS memory.{schema}")
        _run(
            connection,
            "CREATE TABLE memory.bronze.shopify__order_lines (order_id varchar, "
            "index integer, total decimal(12, 3), qty integer, created_at varchar)",
        )
        _run(
            connection,
            "INSERT INTO memory.bronze.shopify__order_lines VALUES "
            + ", ".join(
                f"('{order_id}', {line_no}, DECIMAL '{total}', {qty}, '{created}')"
                for order_id, line_no, total, qty, created in LINES
            ),
        )
        _run(connection, "CREATE TABLE memory.bronze.shopify__orders (id varchar, customer varchar)")
        _run(
            connection,
            "INSERT INTO memory.bronze.shopify__orders VALUES "
            + ", ".join(f"('{order_id}', '{payload}')" for order_id, payload in ORDERS),
        )
        # Silver before gold: mart SELECTs read the silver relations.
        artifacts = sorted(
            (a for a in compile_fixture("ecom_basic", dialect="trino") if a.path.endswith(".sql")),
            key=lambda a: PurePosixPath(a.path).parent.name != "silver",
        )
        for artifact in artifacts:
            path = PurePosixPath(artifact.path)
            namespace, relation = path.parent.name, path.stem
            _run(
                connection,
                f'CREATE TABLE memory.{namespace}."{relation}" AS {extract_select(artifact.content)}',
            )
        yield connection


def test_silver_recipe_derivation_runs_on_trino(seeded: trino.dbapi.Connection) -> None:
    rows = _run(
        seeded,
        "SELECT order_id, line_no, unit_price FROM memory.silver.order_item "
        "ORDER BY order_id, line_no",
    )
    # unit_price = line_total / quantity, cast to DECIMAL(12, 4) (spec §7.4).
    assert [tuple(row) for row in rows] == [
        ("o1", 1, Decimal("10.0000")),
        ("o1", 2, Decimal("19.9920")),
        ("o2", 1, Decimal("10.0000")),
    ]


def test_silver_order_extracts_the_json_customer(seeded: trino.dbapi.Connection) -> None:
    rows = _run(seeded, 'SELECT order_id, customer_id FROM memory.silver."order" ORDER BY order_id')
    assert [tuple(row) for row in rows] == [("o1", "c1"), ("o2", "c2")]


def test_mart_join_and_date_roles_run_on_trino(seeded: trino.dbapi.Connection) -> None:
    rows = _run(
        seeded,
        "SELECT order_id, line_no, order_customer_id, ordered_day, ordered_month"
        " FROM memory.gold.mart_order_items ORDER BY order_id, line_no",
    )
    jan2, jan1 = datetime.date(2024, 1, 2), datetime.date(2024, 1, 1)
    feb5, feb1 = datetime.date(2024, 2, 5), datetime.date(2024, 2, 1)
    assert [tuple(row) for row in rows] == [
        ("o1", 1, "c1", jan2, jan1),
        ("o1", 2, "c1", jan2, jan1),
        ("o2", 1, "c2", feb5, feb1),
    ]


def test_mart_revenue_aggregates_with_decimals(seeded: trino.dbapi.Connection) -> None:
    rows = _run(seeded, "SELECT SUM(unit_price * quantity) FROM memory.gold.mart_order_items")
    # 10.0000×10 + 19.9920×3 + 10.0000×2 = 179.976
    assert rows[0][0] == Decimal("179.9760")


def test_dim_date_calendar_runs_on_trino(seeded: trino.dbapi.Connection) -> None:
    """The one model with a construction no other tier executes:
    ``UNNEST(SEQUENCE(DATE, DATE, INTERVAL))`` is this dialect's calendar."""
    rows = _run(seeded, "SELECT COUNT(*), MIN(date_day), MAX(date_day) FROM memory.gold.dim_date")
    count, first, last = rows[0]
    assert count == 4018  # 2020-01-01 .. 2030-12-31, three leap years
    assert (first, last) == (datetime.date(2020, 1, 1), datetime.date(2030, 12, 31))
