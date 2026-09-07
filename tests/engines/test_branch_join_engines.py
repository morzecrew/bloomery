"""Engine tier (RFC 0009 §5.2 tier 5): the composed branch join returns the
same numbers on every dialect the planner speaks (RFC 0041 D13, D17).

The unit tier asserts that all three dialects *render* `IS NOT DISTINCT FROM`,
and corpus case `006-two-grains-one-request` executes a composed plan on
DuckDB. Neither says PostgreSQL and Trino run it — and D17 exists precisely
because "the documentation says they support it" is the kind of citation this
project does not accept for a construct that decides a number.

What is asserted is the property the join is for: **a NULL group key survives
and does not split**. Joined on `=` it would fail `NULL = NULL`, and the group
would appear twice with half its measures NULL on each row — a wrong answer
that looks like data, on every engine, silently.

Opt-in (Docker required); excluded from ``just test``.
"""

from __future__ import annotations

from collections.abc import Iterator
import duckdb
import psycopg
import pytest
import trino
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.trino import TrinoContainer

from bloomery.dialects import get_dialect
from bloomery.planner.compose import Branch, compose

#: Pinned rather than ``latest``: an engine tier that silently changes engine
#: version is a tier that cannot tell a regression from an upgrade.
TRINO_IMAGE = "trinodb/trino:483"
POSTGRES_IMAGE = "postgres:16-alpine"

#: Three regions and one of them NULL, small enough to check by eye. `orders`
#: is one row per order and `lines` many per order, which is why the two
#: measures cannot share a scan.
ORDERS = (("o1", "EU", 9), ("o2", "EU", 5), ("o3", "UK", 3), ("o4", None, 1))
LINES = (("o1", 2), ("o1", 2), ("o2", 1), ("o3", 4), ("o4", 7), ("o4", 1))

#: What the two aggregates are, by hand: shipping is summed per order and
#: discount per line, and the NULL region is a group like any other.
EXPECTED = {
    "EU": (14, 5),
    "UK": (3, 4),
    None: (1, 8),
}


def _branches() -> list[Branch]:
    return [
        Branch(
            sql=(
                "SELECT region AS o_region, SUM(shipping) AS shipping_total "
                "FROM cmb_orders GROUP BY region"
            ),
            keys=("o_region",),
        ),
        Branch(
            sql=(
                "SELECT o.region AS l_region, SUM(l.discount) AS discount_total "
                "FROM cmb_lines l JOIN cmb_orders o ON l.order_id = o.order_id "
                "GROUP BY o.region"
            ),
            keys=("l_region",),
        ),
    ]


def _composed(dialect: str) -> str:
    return compose(
        _branches(),
        keys=("region",),
        measures=((0, "shipping_total"), (1, "discount_total")),
        dialect=get_dialect(dialect),
    )


def _as_expected(rows: list[tuple[object, ...]]) -> dict[object, tuple[int, int]]:
    return {row[0]: (int(row[1]), int(row[2])) for row in rows}


# ....................... #


@pytest.fixture(scope="module")
def postgres() -> Iterator[psycopg.Connection]:
    with PostgresContainer(POSTGRES_IMAGE, driver=None) as container:
        conn = psycopg.connect(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(container.port)),
            user=container.username,
            password=container.password,
            dbname=container.dbname,
            autocommit=True,
        )
        conn.execute("CREATE TABLE cmb_orders (order_id TEXT, region TEXT, shipping INT)")
        conn.execute("CREATE TABLE cmb_lines (order_id TEXT, discount INT)")
        with conn.cursor() as cursor:
            cursor.executemany("INSERT INTO cmb_orders VALUES (%s, %s, %s)", ORDERS)
            cursor.executemany("INSERT INTO cmb_lines VALUES (%s, %s)", LINES)
        yield conn
        conn.close()


@pytest.fixture(scope="module")
def trino_db() -> Iterator[trino.dbapi.Connection]:
    with TrinoContainer(TRINO_IMAGE) as container:
        connection = trino.dbapi.connect(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(8080)),
            user="bloomery",
            catalog="memory",
            schema="default",
        )
        cursor = connection.cursor()
        cursor.execute("CREATE TABLE cmb_orders (order_id varchar, region varchar, shipping int)")
        cursor.fetchall()
        cursor.execute("CREATE TABLE cmb_lines (order_id varchar, discount int)")
        cursor.fetchall()
        values = ", ".join(
            f"('{order}', {'NULL' if region is None else repr(region)}, {shipping})"
            for order, region, shipping in ORDERS
        )
        cursor.execute(f"INSERT INTO cmb_orders VALUES {values}")
        cursor.fetchall()
        lines = ", ".join(f"('{order}', {discount})" for order, discount in LINES)
        cursor.execute(f"INSERT INTO cmb_lines VALUES {lines}")
        cursor.fetchall()
        yield connection


# ....................... #


def test_duckdb_is_the_reference() -> None:
    """The engine the composed join was developed against, asserted against
    hand-checked numbers rather than against itself — otherwise the two
    engine tests below compare a wrong answer with a wrong answer."""
    connection = duckdb.connect()
    connection.execute("CREATE TABLE cmb_orders (order_id TEXT, region TEXT, shipping INT)")
    connection.execute("CREATE TABLE cmb_lines (order_id TEXT, discount INT)")
    connection.executemany("INSERT INTO cmb_orders VALUES (?, ?, ?)", list(ORDERS))
    connection.executemany("INSERT INTO cmb_lines VALUES (?, ?)", list(LINES))

    try:
        rows = connection.execute(_composed("duckdb")).fetchall()
    finally:
        connection.close()

    assert _as_expected(rows) == EXPECTED


@pytest.mark.engine("postgres")
def test_postgres_runs_the_composed_join(postgres: psycopg.Connection) -> None:
    """D17's claim for PostgreSQL, executed. The NULL region is the assertion:
    it is one group here, and two half-empty rows under `=`."""
    rows = postgres.execute(_composed("postgres")).fetchall()

    assert _as_expected([tuple(row) for row in rows]) == EXPECTED


@pytest.mark.engine("trino")
def test_trino_runs_the_composed_join(trino_db: trino.dbapi.Connection) -> None:
    """D17's claim for Trino, executed."""
    cursor = trino_db.cursor()
    cursor.execute(_composed("trino"))

    assert _as_expected([tuple(row) for row in cursor.fetchall()]) == EXPECTED


def test_the_null_group_loses_its_numbers_without_null_safe_equality() -> None:
    """Why the capability is a flag rather than an assumption, demonstrated
    rather than argued.

    The key domain is a ``UNION``, so the NULL group is in the answer either
    way — what `=` costs is the *match*: `NULL = NULL` is unknown, so neither
    branch joins onto that row and both measures come back NULL. A group with
    no numbers reads as "nothing happened in this group", which is a different
    and wrong claim about the same rows.

    On DuckDB alone, because this is a property of `=` in SQL rather than of
    any one engine.
    """
    connection = duckdb.connect()
    connection.execute("CREATE TABLE cmb_orders (order_id TEXT, region TEXT, shipping INT)")
    connection.execute("CREATE TABLE cmb_lines (order_id TEXT, discount INT)")
    connection.executemany("INSERT INTO cmb_orders VALUES (?, ?, ?)", list(ORDERS))
    connection.executemany("INSERT INTO cmb_lines VALUES (?, ?)", list(LINES))
    unsafe = _composed("duckdb").replace("IS NOT DISTINCT FROM", "=")

    try:
        rows = connection.execute(unsafe).fetchall()
    finally:
        connection.close()

    by_key = {row[0]: (row[1], row[2]) for row in rows}

    assert None in EXPECTED
    assert set(by_key) == set(EXPECTED)
    assert by_key[None] == (None, None)
    assert by_key["EU"] == EXPECTED["EU"]
