"""Engine tier (RFC 0009 §5.2 tier 5): RFC 0028 §5's two closing tests, on
PostgreSQL and Trino.

RFC 0028 named exactly two tests as what "fixed" looks like, and both were run
by hand while the fix was written. A hand-verification is a claim with a date
on it, not a test — the argument :mod:`tests.engines.test_trino` already makes
about three other decisions — so they live here now:

1. the same ``to_utc`` value queried under two session zones yields the same
   derived date, on each engine;
2. two mappings naming *different* zones over the same instant yield the same
   derived date on Trino.

The second is the one a merged entity would have shipped: it needs no session
change, no unusual reader, nothing but two shops in two cities. Before the fix
the pair landed in different days.

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
from bloomery.ir.lower import canon
from bloomery.transforms import DEFAULT_REGISTRY

POSTGRES_IMAGE = "postgres:16-alpine"
TRINO_IMAGE = "trinodb/trino:483"

#: 23:30 in Berlin on 2026-01-06 is the instant 22:30Z, and 07:30 in Tokyo on
#: 2026-01-07 is the same instant — the pair that landed in two days.
BERLIN = ("2026-01-06 23:30:00", "Europe/Berlin")
TOKYO = ("2026-01-07 07:30:00", "Asia/Tokyo")
INSTANT_DATE = "2026-01-06"
SESSIONS = ("UTC", "Pacific/Kiritimati")


def _to_utc_sql(port_name: str, column: str, zone: str) -> str:
    """``to_utc`` as it is emitted: through the canonical text round trip."""
    built = DEFAULT_REGISTRY["to_utc"].builder(exp.column(column), zone)
    return get_dialect(port_name).render(canon(built).ast())


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
        local, _ = BERLIN
        conn.execute(f"CREATE TABLE t AS SELECT CAST('{local}' AS TIMESTAMP) AS placed_at")
        yield conn
        conn.close()


@pytest.mark.engine("postgres")
def test_postgres_to_utc_date_does_not_move_with_the_reader(
    postgres: psycopg.Connection,
) -> None:
    _, zone = BERLIN
    expression = _to_utc_sql("postgres", "placed_at", zone)
    seen = {}
    for session in SESSIONS:
        postgres.execute(f"SET TIME ZONE '{session}'")
        row = postgres.execute(f"SELECT CAST(({expression}) AS DATE) FROM t").fetchone()
        assert row is not None
        seen[session] = str(row[0])
    assert len(set(seen.values())) == 1, f"the date moved with the session zone: {seen}"
    assert next(iter(seen.values())) == INSTANT_DATE


@pytest.mark.engine("postgres")
def test_postgres_parse_ts_keeps_the_clock_that_was_written(
    postgres: psycopg.Connection,
) -> None:
    """``parse_ts`` parses a *local* wall clock — ``to_utc`` is the only door
    into UTC — so the value it produces must be the clock as written, under any
    session.

    PostgreSQL's ``to_timestamp(text, text)`` returns ``timestamptz``, having
    attached the session zone, so the same row stored a different instant
    depending on who ran it: ``+00``, ``+14`` and ``-08`` for one input. The
    port now casts back to ``timestamp``, which PostgreSQL converts *through*
    the session zone — undoing the attachment exactly (RFC 0029 §2.4).

    Guarding the value and not only the type, because the tempting wrong fix
    passes a type check: ``AT TIME ZONE 'UTC'`` also yields a zoneless
    ``timestamp`` and moves the clock to ``09:30`` under Pacific/Kiritimati.
    """
    built = DEFAULT_REGISTRY["parse_ts"].builder(exp.column("written"), "%Y-%m-%d %H:%M:%S")
    expression = get_dialect("postgres").render(canon(built).ast())
    local, _ = BERLIN
    postgres.execute(f"CREATE TABLE p AS SELECT CAST('{local}' AS TEXT) AS written")
    seen = {}
    for session in SESSIONS:
        postgres.execute(f"SET TIME ZONE '{session}'")
        row = postgres.execute(f"SELECT ({expression})::text FROM p").fetchone()
        assert row is not None
        seen[session] = row[0]
    assert len(set(seen.values())) == 1, f"the parsed clock moved with the session: {seen}"
    assert next(iter(seen.values())).startswith(local)


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
        berlin, _ = BERLIN
        tokyo, _ = TOKYO
        cursor.execute(
            f"CREATE TABLE t AS SELECT CAST('{berlin}' AS TIMESTAMP) AS berlin_local, "
            f"CAST('{tokyo}' AS TIMESTAMP) AS tokyo_local"
        )
        cursor.fetchall()
        yield cursor
        conn.close()


@pytest.mark.engine("trino")
def test_trino_to_utc_date_does_not_move_with_the_reader(
    trino_cursor: trino.dbapi.Cursor,
) -> None:
    _, zone = BERLIN
    expression = _to_utc_sql("trino", "berlin_local", zone)
    seen = {}
    for session in SESSIONS:
        trino_cursor.execute(f"SET TIME ZONE '{session}'")
        trino_cursor.fetchall()
        trino_cursor.execute(f"SELECT CAST(({expression}) AS DATE) FROM t")
        seen[session] = str(trino_cursor.fetchall()[0][0])
    assert len(set(seen.values())) == 1, f"the date moved with the session zone: {seen}"
    assert next(iter(seen.values())) == INSTANT_DATE


@pytest.mark.engine("trino")
def test_trino_two_mappings_at_one_instant_land_in_one_day(
    trino_cursor: trino.dbapi.Cursor,
) -> None:
    """The shape a merged entity ships: two shops, two zones, one instant.

    Nothing here is unusual — no session change, no reader east of the date
    line. Before the fix ``ordered_at`` carried the *mapping's* zone, so
    ``date(ordered_at)`` was the local date in whatever city the mapping named
    and this pair split one instant across ``2026-01-06`` and ``2026-01-07``.
    """
    _, berlin_zone = BERLIN
    _, tokyo_zone = TOKYO
    trino_cursor.execute("SET TIME ZONE 'UTC'")
    trino_cursor.fetchall()
    trino_cursor.execute(
        f"SELECT CAST(({_to_utc_sql('trino', 'berlin_local', berlin_zone)}) AS DATE), "
        f"CAST(({_to_utc_sql('trino', 'tokyo_local', tokyo_zone)}) AS DATE), "
        f"({_to_utc_sql('trino', 'berlin_local', berlin_zone)}) = "
        f"({_to_utc_sql('trino', 'tokyo_local', tokyo_zone)}) FROM t"
    )
    berlin_date, tokyo_date, same_instant = trino_cursor.fetchall()[0]
    assert same_instant, "the fixture no longer holds one instant in two zones"
    assert str(berlin_date) == str(tokyo_date) == INSTANT_DATE
