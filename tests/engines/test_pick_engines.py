"""Engine tier: `pick` on PostgreSQL 16 and Trino 483, held to DuckDB's answers
(S-0095/D-4, #312).

Each list in `support.pick_cases` runs as the text a `from:` extraction yields
and as a JSON value, and every answer must be the one DuckDB's execution test
pins, the numeric match field included, which the design's measurement did
not cover.

Opt-in (Docker required); excluded from ``just test``.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
import trino
from sqlglot import exp
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.trino import TrinoContainer

from bloomery.dialects import get_dialect
from bloomery.transforms import DEFAULT_REGISTRY
from bloomery.typing import LogicalType, StringType, VariantType
from support.pick_cases import CASES, NUMERIC_FIELD

#: `(case, list, match text, expected)`: every measured list, and the numeric field.
ROWS = [(name, text, "a", expected) for name, (text, expected) in sorted(CASES.items())] + [
    ("numeric match field", NUMERIC_FIELD[0], "5", NUMERIC_FIELD[1])
]


def _rendered(dialect: str, text: str, input_type: LogicalType) -> str:
    node = DEFAULT_REGISTRY["pick"].builder(
        exp.column("x"), "name", text, "value", input_type=input_type
    )
    return get_dialect(dialect).render(node)


# ....................... #
# PostgreSQL


@pytest.fixture(scope="module")
def postgres() -> Iterator[psycopg.Connection]:
    with PostgresContainer("postgres:16-alpine", driver=None) as container:
        conn = psycopg.connect(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(container.port)),
            user=container.username,
            password=container.password,
            dbname=container.dbname,
            autocommit=True,
            prepare_threshold=None,
        )
        yield conn
        conn.close()


@pytest.mark.engine("postgres")
@pytest.mark.parametrize("column", ["text", "jsonb"])
@pytest.mark.parametrize(("case", "items", "text", "expected"), ROWS, ids=[row[0] for row in ROWS])
def test_postgres_picks_as_duckdb_does(
    postgres: psycopg.Connection,
    column: str,
    case: str,
    items: str | None,
    text: str,
    expected: str | None,
) -> None:
    if column == "jsonb" and case == "text that is not json":
        pytest.skip("a jsonb column cannot hold text that is not JSON")
    input_type = VariantType() if column == "jsonb" else StringType()
    postgres.execute("DROP TABLE IF EXISTS t")
    postgres.execute(f"CREATE TABLE t (x {column})")
    postgres.execute(f"INSERT INTO t VALUES (%s::{column})", (items,))
    row = postgres.execute(f"SELECT {_rendered('postgres', text, input_type)} FROM t").fetchone()

    assert row is not None
    assert row[0] == expected


# ....................... #
# Trino


@pytest.fixture(scope="module")
def trino_cursor() -> Iterator[trino.dbapi.Cursor]:
    with TrinoContainer("trinodb/trino:483") as container:
        connection = trino.dbapi.connect(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(8080)),
            user="bloomery",
            catalog="memory",
            schema="default",
        )
        yield connection.cursor()


@pytest.mark.engine("trino")
@pytest.mark.parametrize("value", [False, True])
@pytest.mark.parametrize(("case", "items", "text", "expected"), ROWS, ids=[row[0] for row in ROWS])
def test_trino_picks_as_duckdb_does(
    trino_cursor: trino.dbapi.Cursor,
    value: bool,
    case: str,
    items: str | None,
    text: str,
    expected: str | None,
) -> None:
    if value and case == "text that is not json":
        pytest.skip("a JSON value cannot be text that is not JSON")
    literal = "CAST(NULL AS VARCHAR)" if items is None else "'" + items.replace("'", "''") + "'"
    source = f"json_parse({literal})" if value else literal
    sql = _rendered("trino", text, VariantType() if value else StringType())
    trino_cursor.execute(f"SELECT {sql} FROM (VALUES {source}) AS t(x)")

    assert trino_cursor.fetchall()[0][0] == expected
