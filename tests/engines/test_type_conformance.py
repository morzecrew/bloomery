"""Engine tier (RFC 0009 §5.2 tier 5): the declared-vs-produced type battery
on PostgreSQL and Trino (RFC 0028 D5).

Same corpus as :mod:`tests.execution.test_type_conformance`, which carries the
argument for why the check is an engine question rather than an emit-time one.
Two engines rather than one module each, because the whole point is that the
three ports must agree with the *same* declaration: a divergence registered on
one and absent on another is the interesting shape, and it is only legible
when they are read side by side.

Opt-in (Docker required); excluded from ``just test``.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
import trino
from support.type_conformance import assert_matches_known, canonical, measure, source_columns
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.trino import TrinoContainer

from bloomery.dialects import get_dialect
from bloomery.dialects.base import DialectPort

#: Pinned, matching the sibling engine modules: a tier whose engine version can
#: change under it cannot tell a regression from an upgrade.
POSTGRES_IMAGE = "postgres:16-alpine"
TRINO_IMAGE = "trinodb/trino:483"


def _literal(value: str) -> str:
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _probe_table(port: DialectPort) -> str:
    """One row, one column per case, each column the case's declared *input*
    type — a real column rather than a folded constant, since PostgreSQL
    evaluates a folded one at plan time (RFC 0016 D84)."""
    columns = ", ".join(
        f"CAST({_literal(value)} AS {physical}) AS {name}"
        for name, physical, value in source_columns(port)
    )
    return f"CREATE TABLE probe AS SELECT {columns}"


# ....................... #
# PostgreSQL


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
        conn.execute("SET TIME ZONE 'UTC'")
        conn.execute(_probe_table(get_dialect("postgres")))
        yield conn
        conn.close()


@pytest.mark.engine("postgres")
def test_declared_types_are_what_postgres_produces(postgres: psycopg.Connection) -> None:
    port = get_dialect("postgres")

    def run(sql: str) -> str:
        # A view rather than the cursor's OID, because `format_type` keeps the
        # typmod — and `numeric(12, 4)` versus a bare `numeric` is one of the
        # divergences this battery exists to see.
        try:
            postgres.execute("DROP VIEW IF EXISTS probe_view")
            postgres.execute(f"CREATE VIEW probe_view AS {sql}")
            postgres.execute(sql).fetchone()
        except psycopg.Error as error:
            return f"error:{error.sqlstate}"
        row = postgres.execute(
            "SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute AS a "
            "JOIN pg_class AS r ON r.oid = a.attrelid "
            "WHERE r.relname = 'probe_view' AND a.attname = 'probe'"
        ).fetchone()
        assert row is not None
        return canonical(row[0], dialect="postgres")

    assert_matches_known(measure(port, run), port="postgres")


# ....................... #
# Trino


@pytest.fixture(scope="module")
def trino_cursor() -> Iterator[trino.dbapi.Cursor]:
    with TrinoContainer(TRINO_IMAGE) as container:
        conn = trino.dbapi.connect(
            host=container.get_container_host_ip(),
            port=container.get_exposed_port(8080),
            user="bloomery",
            catalog="memory",
            schema="default",
        )
        cursor = conn.cursor()
        cursor.execute(_probe_table(get_dialect("trino")))
        cursor.fetchall()
        yield cursor
        conn.close()


@pytest.mark.engine("trino")
def test_declared_types_are_what_trino_produces(trino_cursor: trino.dbapi.Cursor) -> None:
    port = get_dialect("trino")

    def run(sql: str) -> str:
        try:
            trino_cursor.execute(sql)
            trino_cursor.fetchall()
        except trino.exceptions.TrinoUserError as error:
            return f"error:{error.error_name}"
        return canonical(trino_cursor.description[0][1], dialect="trino")

    assert_matches_known(measure(port, run), port="trino")
