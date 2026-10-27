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
