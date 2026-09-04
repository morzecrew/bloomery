"""Engine tier (RFC 0009 §5.2 tier 5): the ecom_basic silver + mart SQL,
compiled under the postgres dialect, executed against a real PostgreSQL via
testcontainers — proving the second dialect's rendering runs, not merely
parses. Opt-in (Docker required); excluded from ``just test``."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import PurePosixPath

import psycopg
import pytest
from psycopg.types.json import Jsonb
from testcontainers.community.postgres import PostgresContainer

from bloomery.emit import ArtifactKind, EmittedArtifact
from support.compiling import compile_fixture, extract_select

pytestmark = pytest.mark.engine("postgres")


@pytest.fixture(scope="module")
def conn() -> Iterator[psycopg.Connection]:
    with PostgresContainer("postgres:16-alpine", driver=None) as container:
        connection = psycopg.connect(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(container.port)),
            user=container.username,
            password=container.password,
            dbname=container.dbname,
        )
        connection.execute("SET TIME ZONE 'UTC'")
        for schema in ("bronze", "silver", "gold"):
            connection.execute(f"CREATE SCHEMA {schema}")
        yield connection
        connection.close()


def materialize(conn: psycopg.Connection, artifacts: tuple[EmittedArtifact, ...]) -> None:
    """CREATE TABLE <namespace>.<relation> AS <the artifact's SELECT> —
    silver before gold, because mart SELECTs read the silver relations.
    Relations are quoted: ``order`` is reserved in postgres.

    Only ``MODEL`` artifacts define a relation. The stream also carries the
    project's ``config.yaml``, which has no SELECT and no namespace to put one
    in."""
    for artifact in sorted(
        (a for a in artifacts if a.kind is ArtifactKind.MODEL),
        key=lambda a: (PurePosixPath(a.path).parent.name != "silver",),
    ):
        path = PurePosixPath(artifact.path)
        namespace, relation = path.parent.name, path.stem
        conn.execute(
            f'CREATE TABLE {namespace}."{relation}" AS {extract_select(artifact.content)}'
        )


@pytest.fixture(scope="module")
def seeded(conn: psycopg.Connection) -> psycopg.Connection:
    conn.execute(
        "CREATE TABLE bronze.shopify__order_lines "
        "(order_id TEXT, index INT, total NUMERIC, qty INT, created_at TEXT)"
    )
    lines = [
        ("o1", 1, Decimal("100.00"), 10, "2024-01-02T03:04:05"),
        ("o1", 2, Decimal("59.976"), 3, "2024-01-02T04:00:00"),
        ("o2", 1, Decimal("20.00"), 2, "2024-02-05T10:00:00"),
    ]
    with conn.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO bronze.shopify__order_lines VALUES (%s, %s, %s, %s, %s)", lines
        )
        cursor.execute("CREATE TABLE bronze.shopify__orders (id TEXT, customer JSONB)")
        cursor.executemany(
            "INSERT INTO bronze.shopify__orders VALUES (%s, %s)",
            [("o1", Jsonb({"id": "c1"})), ("o2", Jsonb({"id": "c2"}))],
        )
    materialize(conn, compile_fixture("ecom_basic", dialect="postgres"))
    return conn


def test_silver_recipe_derivation_runs_on_postgres(seeded: psycopg.Connection) -> None:
    rows = seeded.execute(
        "SELECT order_id, line_no, unit_price FROM silver.order_item ORDER BY order_id, line_no"
    ).fetchall()
    # unit_price = line_total / quantity, cast to DECIMAL(12, 4) (spec §7.4).
    assert rows == [
        ("o1", 1, Decimal("10.0000")),
        ("o1", 2, Decimal("19.9920")),
        ("o2", 1, Decimal("10.0000")),
    ]


def test_silver_order_extracts_the_json_customer(seeded: psycopg.Connection) -> None:
    rows = seeded.execute(
        'SELECT order_id, customer_id FROM silver."order" ORDER BY order_id'
    ).fetchall()
    assert rows == [("o1", "c1"), ("o2", "c2")]


def test_mart_join_and_date_roles_run_on_postgres(seeded: psycopg.Connection) -> None:
    rows = seeded.execute(
        "SELECT order_id, line_no, order_customer_id, ordered_day, ordered_month"
        " FROM gold.mart_order_items ORDER BY order_id, line_no"
    ).fetchall()
    import datetime

    jan2, jan1, feb5, feb1 = (
        datetime.date(2024, 1, 2),
        datetime.date(2024, 1, 1),
        datetime.date(2024, 2, 5),
        datetime.date(2024, 2, 1),
    )
    assert rows == [
        ("o1", 1, "c1", jan2, jan1),
        ("o1", 2, "c1", jan2, jan1),
        ("o2", 1, "c2", feb5, feb1),
    ]


def test_mart_revenue_aggregates_with_decimals(seeded: psycopg.Connection) -> None:
    row = seeded.execute(
        "SELECT SUM(unit_price * quantity) FROM gold.mart_order_items"
    ).fetchone()
    assert row is not None
    # 10.0000×10 + 19.9920×3 + 10.0000×2 = 179.976
    assert row[0] == Decimal("179.9760")


def test_dim_date_calendar_runs_on_postgres(seeded: psycopg.Connection) -> None:
    import datetime

    row = seeded.execute(
        "SELECT COUNT(*), MIN(date_day), MAX(date_day) FROM gold.dim_date"
    ).fetchone()
    assert row is not None
    assert row[0] == 4018  # 2020-01-01 .. 2030-12-31, three leap years
    assert (row[1], row[2]) == (datetime.date(2020, 1, 1), datetime.date(2030, 12, 31))
