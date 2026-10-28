"""Engine tier: bound against inline on PostgreSQL 16 through psycopg
(``pyformat``) and Trino 483 through its client (``qmark``) (S-0097/D-7, Q-1;
#304).

How a driver types a bind is the driver's: psycopg sends a ``date`` as a date,
and Trino's client spells each value as a typed literal (`DATE '…'`). Every
request in :data:`support.planning.BIND_REQUESTS` must return, bound and
inline, the rows DuckDB's inline plan returns: one table of answers, held on
three engines, because the claim is agreement.

Trino refuses the *inline* plan of a request filter on a date or a timestamp
(`date >= varchar(10)`): the planner renders that literal as untyped text,
which DuckDB and PostgreSQL coerce and Trino does not. Bound, the client types
it, so those cases pass bound and are strict expected failures inline (#351).

Opt-in (Docker required); excluded from ``just test``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from datetime import datetime
from pathlib import PurePosixPath

import psycopg
import pytest
import trino
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.trino import TrinoContainer

from bloomery.emit import ArtifactKind
from support.compiling import compile_fixture, extract_select
from support.planning import (
    BIND_FIXTURE,
    BIND_REQUESTS,
    BIND_SALES,
    bind_warehouse,
    fixture_ir,
    make_planner,
)

PLANNER = make_planner()

#: `(sql, params)` to rows: params are a mapping under `pyformat` and a
#: sequence under `qmark`, and `None` runs the text with no parameters at all.
Run = Callable[[str, object], list[tuple[object, ...]]]

CASES = list(BIND_REQUESTS)


def _models(dialect: str) -> list[tuple[str, str, str]]:
    """`(schema, table, select)` per emitted model, silver before gold."""
    artifacts = sorted(
        (a for a in compile_fixture(BIND_FIXTURE, dialect=dialect) if a.kind is ArtifactKind.MODEL and a.path.endswith(".sql")),
        key=lambda a: PurePosixPath(a.path).parent.name != "silver",
    )
    return [
        (PurePosixPath(a.path).parent.name, PurePosixPath(a.path).stem, extract_select(a.content))
        for a in artifacts
    ]


#: The cases whose inline plan Trino refuses: a request filter on a date or a
#: timestamp dimension, the policy case's included.
TRINO_INLINE_REFUSED = frozenset({"date", "timestamp", "zoned timestamp", "policy"})


@pytest.fixture(scope="module")
def answers() -> dict[str, list[tuple[object, ...]]]:
    """DuckDB's inline rows per case, keyed by month as a date."""
    connection = bind_warehouse()
    ir = fixture_ir(BIND_FIXTURE)
    rows = {
        case: _keyed(connection.execute(PLANNER.plan(ir, request, dialect="duckdb", policy=policy).sql).fetchall())
        for case, (request, policy) in BIND_REQUESTS.items()
    }
    connection.close()
    assert all(any(row[1] is not None for row in found) for found in rows.values()), (
        "a case that returns nothing proves nothing"
    )
    return rows


def _keyed(rows: list[tuple[object, ...]]) -> list[tuple[object, ...]]:
    """The month key as a date: engines disagree on whether a truncated date
    comes back as a date or a timestamp, which is not this module's claim."""
    return [(row[0].date() if isinstance(row[0], datetime) else row[0], *row[1:]) for row in rows]


def _rows(run: Run, dialect: str, case: str, paramstyle: str | None) -> list[tuple[object, ...]]:
    request, policy = BIND_REQUESTS[case]
    plan = PLANNER.plan(fixture_ir(BIND_FIXTURE), request, dialect=dialect, policy=policy, paramstyle=paramstyle)
    if paramstyle is None:
        return _keyed(run(plan.sql, None))
    assert plan.params
    params: Sequence[object] | dict[str, object] = (
        dict(plan.params) if paramstyle == "pyformat" else [value for _name, value in plan.params]
    )
    return _keyed(run(plan.sql, params))


# ....................... #
# PostgreSQL


@pytest.fixture(scope="module")
def postgres() -> Iterator[Run]:
    with PostgresContainer("postgres:16-alpine", driver=None) as container:
        connection = psycopg.connect(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(container.port)),
            user=container.username,
            password=container.password,
            dbname=container.dbname,
            autocommit=True,
        )
        connection.execute("SET TIME ZONE 'UTC'")
        for schema in ("bronze", "silver", "gold"):
            connection.execute(f"CREATE SCHEMA {schema}")
        connection.execute(
            "CREATE TABLE bronze.shop__sales (id TEXT, amount TEXT, units TEXT, "
            "is_test TEXT, status TEXT, channel TEXT, sold_at TEXT, booked_at TEXT)"
        )
        with connection.cursor() as cursor:
            cursor.executemany("INSERT INTO bronze.shop__sales VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", BIND_SALES)
        for schema, table, select in _models("postgres"):
            connection.execute(f'CREATE TABLE {schema}."{table}" AS {select}')

        def run(sql: str, params: object) -> list[tuple[object, ...]]:
            return list(connection.execute(sql, params).fetchall())  # type: ignore[arg-type]

        yield run
        connection.close()


@pytest.mark.engine("postgres")
@pytest.mark.parametrize("paramstyle", [None, "pyformat"])
@pytest.mark.parametrize("case", CASES)
def test_postgres_answers_as_duckdb_does(
    postgres: Run, answers: dict[str, list[tuple[object, ...]]], case: str, paramstyle: str | None
) -> None:
    assert _rows(postgres, "postgres", case, paramstyle) == answers[case]


# ....................... #
# Trino


@pytest.fixture(scope="module")
def trino_engine() -> Iterator[Run]:
    with TrinoContainer("trinodb/trino:483") as container:
        connection = trino.dbapi.connect(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(8080)),
            user="bloomery",
            catalog="memory",
            schema="default",
        )

        def run(sql: str, params: object) -> list[tuple[object, ...]]:
            cursor = connection.cursor()
            cursor.execute(sql, params)  # type: ignore[arg-type]
            return [tuple(row) for row in cursor.fetchall()]

        for schema in ("bronze", "silver", "gold"):
            run(f"CREATE SCHEMA IF NOT EXISTS memory.{schema}", None)
        run(
            "CREATE TABLE memory.bronze.shop__sales (id varchar, amount varchar, units varchar, "
            "is_test varchar, status varchar, channel varchar, sold_at varchar, booked_at varchar)",
            None,
        )
        run(
            "INSERT INTO memory.bronze.shop__sales VALUES "
            + ", ".join("(" + ", ".join(f"'{value}'" for value in row) + ")" for row in BIND_SALES),
            None,
        )
        for schema, table, select in _models("trino"):
            run(f'CREATE TABLE memory.{schema}."{table}" AS {select}', None)
        yield run
        connection.close()


@pytest.mark.engine("trino")
@pytest.mark.parametrize("paramstyle", [None, "qmark"])
@pytest.mark.parametrize("case", CASES)
def test_trino_answers_as_duckdb_does(
    trino_engine: Run,
    answers: dict[str, list[tuple[object, ...]]],
    case: str,
    paramstyle: str | None,
    request: pytest.FixtureRequest,
) -> None:
    if paramstyle is None and case in TRINO_INLINE_REFUSED:
        request.applymarker(
            pytest.mark.xfail(
                raises=trino.exceptions.TrinoUserError,
                strict=True,
                reason="an inline date or timestamp request filter is untyped text on Trino (#351)",
            )
        )
    assert _rows(trino_engine, "trino", case, paramstyle) == answers[case]
