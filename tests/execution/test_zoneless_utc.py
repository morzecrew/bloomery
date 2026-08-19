"""Execution tier (RFC 0009 §5.2 tier 4): a ``to_utc`` column reads the same
under any session zone, on DuckDB (RFC 0028 §5).

This is the half of RFC 0028 a *type* check cannot reach, and the reason the
declared-vs-produced battery is necessary but not sufficient. The defect was a
zone-aware value where the type map declares a zoneless one, and the obvious
repair — wrapping the interpretation in ``CAST(… AS TIMESTAMP)`` — satisfies
the declared type on every port while still converting through the session
zone. The type would have gone green and the dates would still have moved.

So the claim under test is about values: one instant, two sessions, one date.
:mod:`tests.engines.test_zoneless_utc` makes it on PostgreSQL and Trino, where
it also covers the shape that needs no session change at all.
"""

from __future__ import annotations

import duckdb
import pytest
from sqlglot import exp

from bloomery.dialects import get_dialect
from bloomery.ir.lower import canon
from bloomery.transforms import DEFAULT_REGISTRY

pytestmark = pytest.mark.execution

#: 23:30 in Berlin on 2026-01-06 is the instant 22:30Z — late enough that a
#: reader east of UTC sees the *next* day if the value kept a display rule.
LOCAL = "2026-01-06 23:30:00"
ZONE = "Europe/Berlin"
INSTANT_DATE = "2026-01-06"

#: Two sessions far enough apart to move a 22:30Z instant across midnight.
SESSIONS = ("UTC", "Pacific/Kiritimati")


def _to_utc_sql(port_name: str, column: str) -> str:
    """``to_utc`` as it is emitted: through the canonical text round trip."""
    built = DEFAULT_REGISTRY["to_utc"].builder(exp.column(column), ZONE)
    return get_dialect(port_name).render(canon(built).ast())


def test_a_to_utc_date_does_not_move_with_the_reader() -> None:
    connection = duckdb.connect()
    connection.execute(f"CREATE TABLE t AS SELECT CAST('{LOCAL}' AS TIMESTAMP) AS placed_at")
    expression = _to_utc_sql("duckdb", "placed_at")
    seen = {}
    for session in SESSIONS:
        connection.execute(f"SET TimeZone = '{session}'")
        seen[session] = connection.sql(
            f"SELECT CAST(({expression}) AS DATE) AS d FROM t"
        ).fetchall()[0][0]
    assert len(set(seen.values())) == 1, f"the date moved with the session zone: {seen}"
    assert str(next(iter(seen.values()))) == INSTANT_DATE


def test_the_stored_value_is_the_utc_wall_clock() -> None:
    """Not merely stable — stable at the *right* instant. A conversion that
    dropped the zone without converting would also be session-independent, and
    an hour wrong."""
    connection = duckdb.connect()
    connection.execute(f"CREATE TABLE t AS SELECT CAST('{LOCAL}' AS TIMESTAMP) AS placed_at")
    result = connection.sql(
        f"SELECT CAST(({_to_utc_sql('duckdb', 'placed_at')}) AS VARCHAR) AS v FROM t"
    ).fetchall()
    assert result[0][0].startswith("2026-01-06 22:30:00")
