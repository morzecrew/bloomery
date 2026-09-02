"""Engine tier (RFC 0009 §5.2 tier 5): the RFC 0034 metric forms — a derived
metric with an offset, both cumulative windows, and a filtered metric — planned
per dialect and **executed** against real PostgreSQL and real Trino.

Every other tier in this repository executes SQL that bloomery *emitted*. These
constructs are different in kind: bloomery emits a manifest, and MetricFlow
renders the query, per dialect, at request time. So the SQL under test here is
the one thing no golden can pin and no compile-path test can reach — a
self-join over the time spine on one engine, a window on another, and nothing
in the compiler to notice if a dialect renders it differently.

The seed and the expected numbers are the DuckDB execution tier's, verbatim
(`tests/execution/test_period_over_period.py` states the arithmetic). That is
the whole design: **one table of expectations, asserted on three engines**, so a
dialect that disagrees shows up as a value, not as an absence. Postgres and
Trino share every case here rather than mirroring each other in two files,
because the claim is agreement and a claim about agreement should be written
once.

Opt-in (Docker required); excluded from ``just test``.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import PurePosixPath

import psycopg
import pytest
import trino
from support.compiling import compile_fixture, extract_select
from support.planning import fixture_ir, make_planner
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.trino import TrinoContainer

from bloomery import MetricRequest, TimeGrain

FIXTURE = "period_over_period"

PLANNER = make_planner()

#: Pinned for the reason :mod:`tests.engines.test_trino` gives: a tier that
#: silently changes engine version cannot tell a regression from an upgrade.
TRINO_IMAGE = "trinodb/trino:483"
POSTGRES_IMAGE = "postgres:16-alpine"

#: ``(id, amount, units, is_test, status, channel, sold_at)`` — the DuckDB
#: tier's seed, unchanged, because a different seed would make a disagreement
#: between engines unreadable.
SALES = [
    ("s01", "100.00", "1", "false", "paid", "web", "2023-03-15"),
    ("s02", "100.00", "1", "false", "paid", "web", "2024-03-01"),
    ("s03", "7.00", "1", "false", "paid", "store", "2024-03-04"),
    ("s04", "50.00", "2", "false", "refunded", "web", "2024-03-05"),
    ("s05", "100.00", "1", "false", "paid", "store", "2024-03-11"),
    ("s06", "40.00", "1", "false", "paid", "store", "2023-04-10"),
    ("s07", "40.00", "1", "false", "paid", "store", "2024-04-10"),
    ("s08", "60.00", "3", "false", "paid", "web", "2024-05-02"),
]

_D = Decimal


def _day(year: int, month: int, day: int) -> datetime.date:
    return datetime.date(year, month, day)


#: ``(id, metrics, dimension, grain, {date: (values…)})`` — each case is one
#: request and the rows it must produce, on every engine. Only the named dates
#: are asserted: a request that reaches the time spine returns one row per spine
#: period, and a period nothing happened in carries no claim.
CASES: list[tuple[str, tuple[str, ...], str, TimeGrain, dict]] = [
    (
        "year-over-year",
        ("revenue", "revenue_yoy"),
        "sold_month",
        TimeGrain.MONTH,
        {
            # 257 − 100: March 2024 against March 2023, not against February.
            _day(2024, 3, 1): (_D("257.0000"), _D("157.0000")),
            # Unchanged year: a real zero, not a null.
            _day(2024, 4, 1): (_D("40.0000"), _D("0.0000")),
            # No 2023-05 behind it: no comparison, rather than an invented one.
            _day(2024, 5, 1): (_D("60.0000"), None),
        },
    ),
    (
        "offset-to-period-start",
        ("revenue", "revenue_vs_month_start"),
        "sold_day",
        TimeGrain.DAY,
        {
            _day(2024, 3, 1): (_D("100.0000"), _D("0.0000")),
            _day(2024, 3, 4): (_D("7.0000"), _D("-93.0000")),
            _day(2024, 3, 5): (_D("50.0000"), _D("-50.0000")),
        },
    ),
    (
        "month-to-date",
        ("revenue", "revenue_mtd"),
        "sold_day",
        TimeGrain.DAY,
        {
            _day(2024, 3, 1): (_D("100.0000"), _D("100.0000")),
            _day(2024, 3, 4): (_D("7.0000"), _D("107.0000")),
            _day(2024, 3, 5): (_D("50.0000"), _D("157.0000")),
            _day(2024, 3, 11): (_D("100.0000"), _D("257.0000")),
            # A day with no sale still carries the running total forward.
            _day(2024, 3, 6): (None, _D("157.0000")),
            # ...and April accumulates April, never March's 257.
            _day(2024, 4, 10): (_D("40.0000"), _D("40.0000")),
        },
    ),
    (
        "trailing-window",
        ("revenue", "revenue_trailing_7d"),
        "sold_day",
        TimeGrain.DAY,
        {
            # Half-open at the far end: 03-04 is exactly seven days before
            # 03-11 and is out; seen from 03-10 it is six days back and in.
            _day(2024, 3, 11): (_D("100.0000"), _D("150.0000")),
            _day(2024, 3, 10): (None, _D("57.0000")),
        },
    ),
    (
        "filtered-metric",
        ("revenue", "paid_revenue"),
        "sold_month",
        TimeGrain.MONTH,
        {
            # The refunded 50 is excluded by the metric, not by the request.
            _day(2024, 3, 1): (_D("257.0000"), _D("207.0000")),
            _day(2024, 4, 1): (_D("40.0000"), _D("40.0000")),
        },
    ),
    (
        # The case a string-typed filter cannot reach: Trino refuses
        # `decimal <= varchar` and `date <= varchar` with a TYPE_MISMATCH, so a
        # filter on anything but a string column was broken there and rescued
        # on the other two only by implicit cast. Two clauses, both non-string.
        "typed-filter",
        ("revenue", "large_recent_revenue"),
        "sold_month",
        TimeGrain.MONTH,
        {
            # 100 + 50 + 100: the 7.00 on 03-04 is below the amount bound.
            _day(2024, 3, 1): (_D("257.0000"), _D("250.0000")),
            _day(2024, 5, 1): (_D("60.0000"), _D("60.0000")),
            # April's only sale is 40.00, under the bound — the filter can reach
            # empty, which an implicit-cast comparison quietly would not.
            _day(2024, 4, 1): (_D("40.0000"), None),
        },
    ),
]

IDS = [case[0] for case in CASES]


def planned_sql(metrics: tuple[str, ...], dimension: str, grain: TimeGrain, dialect: str) -> str:
    return PLANNER.plan(
        fixture_ir(FIXTURE),
        MetricRequest(metrics=metrics, dimensions=(dimension,), time_grain=grain),
        dialect=dialect,
    ).sql


def as_date(value: object) -> datetime.date:
    """The group-by key as a date. Engines disagree about whether a truncated
    date comes back as ``date`` or ``timestamp``, and that disagreement is not
    what this module is about."""

    if isinstance(value, datetime.datetime):
        return value.date()

    assert isinstance(value, datetime.date)
    return value


def check(run: Callable[[str], list[tuple[object, ...]]], case_index: int, dialect: str) -> None:
    """One case, executed on one engine, against the shared expectations."""

    _label, metrics, dimension, grain, expected = CASES[case_index]
    rows = {as_date(row[0]): tuple(row[1:]) for row in run(planned_sql(metrics, dimension, grain, dialect))}

    for day, values in expected.items():
        assert day in rows, f"{dialect}: no row for {day}"
        assert rows[day] == values, f"{dialect} {day}: {rows[day]} != {values}"


# ....................... #
# PostgreSQL


@pytest.fixture(scope="module")
def postgres() -> Iterator[Callable[[str], list[tuple[object, ...]]]]:
    with PostgresContainer(POSTGRES_IMAGE, driver=None) as container:
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
        connection.execute(
            "CREATE TABLE bronze.shop__sales (id TEXT, amount TEXT, units TEXT, "
            "is_test TEXT, status TEXT, channel TEXT, sold_at TEXT)"
        )
        with connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO bronze.shop__sales VALUES (%s, %s, %s, %s, %s, %s, %s)", SALES
            )
        for artifact in sorted(
            (a for a in compile_fixture(FIXTURE, dialect="postgres") if a.path.endswith(".sql")),
            key=lambda a: PurePosixPath(a.path).parent.name != "silver",
        ):
            path = PurePosixPath(artifact.path)
            connection.execute(
                f'CREATE TABLE {path.parent.name}."{path.stem}" AS '
                f"{extract_select(artifact.content)}"
            )

        def run(sql: str) -> list[tuple[object, ...]]:
            return list(connection.execute(sql).fetchall())

        yield run
        connection.close()


@pytest.mark.engine("postgres")
@pytest.mark.parametrize("case_index", range(len(CASES)), ids=IDS)
def test_the_planned_query_runs_on_postgres(
    postgres: Callable[[str], list[tuple[object, ...]]], case_index: int
) -> None:
    check(postgres, case_index, "postgres")


# ....................... #
# Trino


@pytest.fixture(scope="module")
def trino_engine() -> Iterator[Callable[[str], list[tuple[object, ...]]]]:
    with TrinoContainer(TRINO_IMAGE) as container:
        connection = trino.dbapi.connect(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(8080)),
            user="bloomery",
            catalog="memory",
            schema="default",
        )

        def run(sql: str) -> list[tuple[object, ...]]:
            cursor = connection.cursor()
            cursor.execute(sql)
            return [tuple(row) for row in cursor.fetchall()]

        for schema in ("bronze", "silver", "gold"):
            run(f"CREATE SCHEMA IF NOT EXISTS memory.{schema}")
        run(
            "CREATE TABLE memory.bronze.shop__sales (id varchar, amount varchar, "
            "units varchar, is_test varchar, status varchar, channel varchar, sold_at varchar)"
        )
        run(
            "INSERT INTO memory.bronze.shop__sales VALUES "
            + ", ".join("(" + ", ".join(f"'{value}'" for value in row) + ")" for row in SALES)
        )
        for artifact in sorted(
            (a for a in compile_fixture(FIXTURE, dialect="trino") if a.path.endswith(".sql")),
            key=lambda a: PurePosixPath(a.path).parent.name != "silver",
        ):
            path = PurePosixPath(artifact.path)
            run(
                f'CREATE TABLE memory.{path.parent.name}."{path.stem}" AS '
                f"{extract_select(artifact.content)}"
            )
        yield run
        connection.close()


@pytest.mark.engine("trino")
@pytest.mark.parametrize("case_index", range(len(CASES)), ids=IDS)
def test_the_planned_query_runs_on_trino(
    trino_engine: Callable[[str], list[tuple[object, ...]]], case_index: int
) -> None:
    check(trino_engine, case_index, "trino")
