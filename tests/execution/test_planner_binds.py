"""Bound against inline on DuckDB (S-0097/D-4, #304): each request in
:data:`support.planning.BIND_REQUESTS`, planned under ``qmark`` and executed
with its params, returns exactly the rows the inline plan does.

Measured for D-4: DuckDB coerces a bound ``str`` to the compared column's
type, so these rows cannot tell a typed value from its text; the bound value
being a ``date``, a ``datetime`` or a ``Decimal`` is the unit tier's
assertion, and the engine differential (D-7) runs the drivers that type a
bind themselves.
"""

from __future__ import annotations

from collections.abc import Iterator

import duckdb
import pytest

from bloomery import MetricRequest, RowPolicy
from support.planning import BIND_FIXTURE, BIND_REQUESTS, bind_warehouse, fixture_ir, make_planner

pytestmark = pytest.mark.execution

PLANNER = make_planner()


@pytest.fixture(scope="module")
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = bind_warehouse()
    yield connection
    connection.close()


@pytest.mark.parametrize(("request_", "policy"), BIND_REQUESTS.values(), ids=list(BIND_REQUESTS))
def test_bound_returns_the_inline_rows(
    conn: duckdb.DuckDBPyConnection, request_: MetricRequest, policy: RowPolicy | None
) -> None:
    ir = fixture_ir(BIND_FIXTURE)
    inline = PLANNER.plan(ir, request_, dialect="duckdb", policy=policy)
    bound = PLANNER.plan(ir, request_, dialect="duckdb", policy=policy, paramstyle="qmark")
    expected = conn.execute(inline.sql).fetchall()

    assert bound.params
    assert conn.execute(bound.sql, [value for _name, value in bound.params]).fetchall() == expected
    assert any(row[1] is not None for row in expected), "a case that returns nothing proves nothing"


def test_a_zoned_value_reads_its_instant_under_any_session_zone(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB binds an aware `datetime` as TIMESTAMPTZ and reads the column in
    the session zone, and casts zoned text to TIMESTAMP by dropping the offset:
    so each spelling of the zoned request runs under a zone that is not UTC,
    held to the naive request for the same instant (S-0045)."""
    ir = fixture_ir(BIND_FIXTURE)
    naive, _ = BIND_REQUESTS["timestamp"]
    zoned, _ = BIND_REQUESTS["zoned timestamp"]
    expected = conn.execute(PLANNER.plan(ir, naive, dialect="duckdb").sql).fetchall()
    inline = PLANNER.plan(ir, zoned, dialect="duckdb")
    bound = PLANNER.plan(ir, zoned, dialect="duckdb", paramstyle="qmark")
    (zone,) = conn.execute("SELECT current_setting('TimeZone')").fetchone() or ("UTC",)

    conn.execute("SET TimeZone = 'Asia/Bangkok'")
    try:
        assert conn.execute(inline.sql).fetchall() == expected
        assert conn.execute(bound.sql, [value for _name, value in bound.params]).fetchall() == expected
    finally:
        conn.execute(f"SET TimeZone = '{zone}'")
