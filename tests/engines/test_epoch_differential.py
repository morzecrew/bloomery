"""Engine tier: `parse_ts: UNIX_SECONDS` and `UNIX_MILLIS` on PostgreSQL 16 and
Trino 483, held to DuckDB's answers (S-0096/D-7, #324).

Each port spells the count as integer arithmetic from 1970. The engines' own
epoch functions were measured to answer a different wall clock under a
different session zone, so every text runs under a UTC and an Asia/Tokyo
session, plain and as the quality system shapes it. The answers are the table
DuckDB's execution test pins (`support.epoch_cases`).

Opt-in (Docker required); excluded from ``just test``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

import psycopg
import pytest
import trino
from sqlglot import exp
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.trino import TrinoContainer

from bloomery.dialects import get_dialect
from bloomery.resolve.build import _try_cast_shape  # pyright: ignore[reportPrivateUsage]
from bloomery.transforms import DEFAULT_REGISTRY
from support.epoch_cases import MILLIS, SECONDS

FORMATS = [("UNIX_SECONDS", SECONDS), ("UNIX_MILLIS", MILLIS)]
ZONES = ["UTC", "Asia/Tokyo"]


def _rendered(dialect: str, fmt: str, *, quality: bool) -> str:
    node = DEFAULT_REGISTRY["parse_ts"].builder(exp.column("x"), fmt)
    return get_dialect(dialect).render(_try_cast_shape(node) if quality else node)


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


def _postgres_answers(
    conn: psycopg.Connection, sql: str, column: str, texts: list[str | None]
) -> dict[str | None, datetime | None]:
    conn.execute("DROP TABLE IF EXISTS t")
    conn.execute(f"CREATE TABLE t (x {column})")
    answers: dict[str | None, datetime | None] = {}
    for text in texts:
        conn.execute("DELETE FROM t")
        conn.execute(f"INSERT INTO t VALUES (%s::{column})", (text,))
        row = conn.execute(f"SELECT {sql} FROM t").fetchone()
        assert row is not None
        answers[text] = row[0]
    return answers


@pytest.mark.engine("postgres")
@pytest.mark.parametrize("quality", [True, False])
@pytest.mark.parametrize("zone", ZONES)
@pytest.mark.parametrize(("fmt", "cases"), FORMATS)
def test_postgres_reads_every_text_as_duckdb_does(
    postgres: psycopg.Connection,
    fmt: str,
    cases: dict[str | None, datetime | None],
    zone: str,
    quality: bool,
) -> None:
    """Plain, a bad text is NULL rather than an aborted run, because the guard
    keeps it from the cast; shaped, the guard's own cast is `pg_input_is_valid`."""
    postgres.execute(f"SET TIME ZONE '{zone}'")
    answers = _postgres_answers(postgres, _rendered("postgres", fmt, quality=quality), "text", list(cases))

    assert answers == cases


@pytest.mark.engine("postgres")
@pytest.mark.parametrize(("fmt", "cases"), FORMATS)
def test_postgres_reads_a_count_a_loader_landed_as_bigint(
    postgres: psycopg.Connection, fmt: str, cases: dict[str | None, datetime | None]
) -> None:
    """The guard reads the value's text: PostgreSQL has no `~` over a `bigint`."""
    integral = {
        text: expected
        for text, expected in cases.items()
        if text is None or text.strip().lstrip("+-").isdigit() and len(text.strip()) <= 18
    }
    postgres.execute("SET TIME ZONE 'UTC'")
    answers = _postgres_answers(postgres, _rendered("postgres", fmt, quality=True), "bigint", list(integral))

    assert answers == integral


# ....................... #
# Trino


@pytest.fixture(scope="module")
def trino_host() -> Iterator[tuple[str, int]]:
    with TrinoContainer("trinodb/trino:483") as container:
        yield container.get_container_host_ip(), int(container.get_exposed_port(8080))


@pytest.mark.engine("trino")
@pytest.mark.parametrize("quality", [True, False])
@pytest.mark.parametrize("zone", ZONES)
@pytest.mark.parametrize(("fmt", "cases"), FORMATS)
def test_trino_reads_every_text_as_duckdb_does(
    trino_host: tuple[str, int],
    fmt: str,
    cases: dict[str | None, datetime | None],
    zone: str,
    quality: bool,
) -> None:
    host, port = trino_host
    connection = trino.dbapi.connect(
        host=host, port=port, user="bloomery", catalog="memory", schema="default", timezone=zone
    )
    sql = _rendered("trino", fmt, quality=quality)
    answers: dict[str | None, datetime | None] = {}
    for text in cases:
        literal = "CAST(NULL AS VARCHAR)" if text is None else "'" + text.replace("'", "''") + "'"
        cursor = connection.cursor()
        cursor.execute(f"SELECT {sql} FROM (VALUES {literal}) AS t(x)")
        answers[text] = cursor.fetchall()[0][0]

    assert answers == cases
