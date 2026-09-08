"""Engine tier (RFC 0009 §5.2 tier 5): the composed branch join returns the
same numbers on every dialect the planner speaks (RFC 0041 D17, D18).

The unit tier asserts that all three dialects *render* the statement, and
corpus case `006-two-grains-one-request` executes a composed plan on DuckDB.
Neither says PostgreSQL and Trino run it, which is what these tests are for —
and they are also what made the statement what it is. The shape D13 first
asked for, `FULL OUTER JOIN … ON a IS NOT DISTINCT FROM b`, renders on all
three and PostgreSQL refuses to plan it: its full join is a merge or hash
join, and a null-safe condition is neither. D18 replaced it with the key
domain and left joins these tests execute. That is why D17 asks for a run
rather than for the citation every reference would have given.

What is asserted is the property the join is for: **a NULL group key keeps its
numbers**. The key domain is a `UNION`, so the group is in the answer either
way; matching on `=` costs it the join, and both measures come back NULL — a
group that reads as "nothing happened here", on every engine, silently.

Opt-in (Docker required); excluded from ``just test``.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import duckdb
import psycopg
import pytest
import trino
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.trino import TrinoContainer

from bloomery.dialects import get_dialect
from sqlglot import parse_one

from bloomery.planner.compose import Branch, Measure, compose

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


def _m(index: int, name: str) -> Measure:
    return Measure(name=name, inputs=((name, index, name),))


_MEASURES = (_m(0, "shipping_total"), _m(1, "discount_total"))


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
        measures=_MEASURES,
        dialect=get_dialect(dialect),
    )


def _duckdb() -> duckdb.DuckDBPyConnection:
    """One seeded in-memory DuckDB, for the three tests that need one.

    The reference numbers, the `=` demonstration and the ratio all read the
    same four orders and six lines; three copies of the seeding is three places
    a row can be changed in one of them.
    """

    connection = duckdb.connect()
    connection.execute("CREATE TABLE cmb_orders (order_id TEXT, region TEXT, shipping INT)")
    connection.execute("CREATE TABLE cmb_lines (order_id TEXT, discount INT)")
    connection.executemany("INSERT INTO cmb_orders VALUES (?, ?, ?)", list(ORDERS))
    connection.executemany("INSERT INTO cmb_lines VALUES (?, ?)", list(LINES))
    return connection


# ....................... #


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
        try:
            yield connection
        finally:
            connection.close()


# ....................... #


def test_duckdb_is_the_reference() -> None:
    """The engine the composed join was developed against, asserted against
    hand-checked numbers rather than against itself — otherwise the two
    engine tests below compare a wrong answer with a wrong answer."""
    connection = _duckdb()

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
    connection = _duckdb()
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


# ....................... #
# RFC 0041 P2: the statement's own tail, and computation above the join.


def _shadowing() -> list[Branch]:
    """Branches whose key column is spelled exactly as the composed alias.

    The composed statement projects the key as `region` and `branch_0` holds a
    `region` of its own, so a bare `ORDER BY region` has two candidates. All
    three dialects are documented to prefer the output column; documented is
    what D17 says is not enough.
    """

    return [
        Branch(
            sql="SELECT region, SUM(shipping) AS shipping_total FROM cmb_orders GROUP BY region",
            keys=("region",),
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


def _ordered(dialect: str, direction: str) -> str:
    return compose(
        _shadowing(),
        keys=("region",),
        measures=_MEASURES,
        order_by=(("region", direction),),
        dialect=get_dialect(dialect),
    )


#: The NULL group last whichever way the answer is sorted (logs/T-0027.md,
#: D-177), and the non-NULL groups in the order asked for.
ORDERED = {"asc": ["EU", "UK", None], "desc": ["UK", "EU", None]}


def _ratio(dialect: str) -> str:
    return compose(
        _branches(),
        keys=("region",),
        measures=(
            Measure(
                name="shipping_per_discount",
                inputs=(
                    ("shipping_total", 0, "shipping_total"),
                    ("discount_total", 1, "discount_total"),
                ),
                expr=parse_one("shipping_total / NULLIF(discount_total, 0)"),
            ),
        ),
        dialect=get_dialect(dialect),
    )


#: 14/5, 3/4 and 1/8 — the branch totals divided **after** each was aggregated.
#: A row-level division summed afterwards gives 2.5, 0.75 and 0.75 for the same
#: rows, which is the whole content of RFC 0041 D1's ordering.
#: Three decimals rather than two: 1/8 is 0.125, and rounding it half-even at
#: two places would make the expected value an artefact of the comparison.
RATIO = {"EU": Decimal("2.800"), "UK": Decimal("0.750"), None: Decimal("0.125")}


def _as_ratio(rows: list[tuple[object, ...]]) -> dict[object, Decimal]:
    return {
        row[0]: Decimal(str(row[1])).quantize(Decimal("0.001")) for row in rows if row[1] is not None
    }


@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_duckdb_sorts_the_null_group_last_either_way(direction: str) -> None:
    connection = _duckdb()

    try:
        rows = connection.execute(_ordered("duckdb", direction)).fetchall()
    finally:
        connection.close()

    assert [row[0] for row in rows] == ORDERED[direction]


@pytest.mark.engine("postgres")
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_postgres_sorts_the_null_group_last_either_way(
    postgres: psycopg.Connection, direction: str
) -> None:
    """PostgreSQL is the one whose defaults disagree with the other two — its
    `DESC` sorts NULLs first — so this is the row that would move if the clause
    were left to the engine."""
    rows = postgres.execute(_ordered("postgres", direction)).fetchall()

    assert [row[0] for row in rows] == ORDERED[direction]


@pytest.mark.engine("trino")
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_trino_sorts_the_null_group_last_either_way(
    trino_db: trino.dbapi.Connection, direction: str
) -> None:
    cursor = trino_db.cursor()
    cursor.execute(_ordered("trino", direction))

    assert [row[0] for row in cursor.fetchall()] == ORDERED[direction]


def test_duckdb_divides_after_the_aggregate() -> None:
    """RFC 0041 D1 and D3, as a number: each operand is aggregated in its own
    branch and the quotient is taken once, over the join."""
    connection = _duckdb()

    try:
        rows = connection.execute(_ratio("duckdb")).fetchall()
    finally:
        connection.close()

    assert _as_ratio(rows) == RATIO


@pytest.mark.engine("postgres")
def test_postgres_divides_after_the_aggregate(postgres: psycopg.Connection) -> None:
    rows = postgres.execute(_ratio("postgres")).fetchall()

    assert _as_ratio([tuple(row) for row in rows]) == RATIO


@pytest.mark.engine("trino")
def test_trino_divides_after_the_aggregate(trino_db: trino.dbapi.Connection) -> None:
    cursor = trino_db.cursor()
    cursor.execute(_ratio("trino"))

    assert _as_ratio([tuple(row) for row in cursor.fetchall()]) == RATIO
