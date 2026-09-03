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


def _iso_parse_sql(port_name: str, column: str) -> str:
    """``parse_ts: ISO8601`` as it is emitted, RFC 0036's guard included."""
    built = DEFAULT_REGISTRY["parse_ts"].builder(exp.column(column), "ISO8601")
    return get_dialect(port_name).render(canon(built).ast())


def test_the_offset_guard_refuses_an_offset_and_keeps_the_rest() -> None:
    """RFC 0036 §2's table on DuckDB, executed rather than rendered.

    Both directions from one table: the two offsets become NULL, and the
    in-contract spellings keep the exact value they had. The second half is the
    one worth running — a guard that refused something in contract would pass
    every assertion written about the refusal.

    The **lowercase** `t` separator is absent from this table and is in
    :mod:`tests.engines.test_zoneless_utc`'s, which is not an oversight:
    measured here, DuckDB's plain `CAST` *raises* on `2026-01-06t12:00:00`
    ("invalid timestamp field format") where PostgreSQL and Trino both read it.
    That predates this guard and is untouched by it — a `TRY_CAST` on a
    quality-carrying entity gives NULL, and the plain cast a bare entity emits
    aborts the run. It is RFC 0027's separator question rather than RFC 0036's
    offset one, and it is recorded in `logs/T-0013.md`.
    """
    conn = duckdb.connect()
    try:
        expression = _iso_parse_sql("duckdb", "written")
        seen = {}
        for text in (
            "2026-01-06T12:00:00",
            "2026-01-06 12:00:00",
            "2026-01-06T12:00:00Z",
            "2026-01-06T12:00:00+01:00",
            "2026-01-06T12:00:00-05:00",
        ):
            row = conn.execute(
                f"SELECT ({expression}) FROM (SELECT '{text}' AS written)"  # noqa: S608 — literals are ours
            ).fetchone()
            assert row is not None
            seen[text] = str(row[0]) if row[0] is not None else None
        assert seen == {
            "2026-01-06T12:00:00": "2026-01-06 12:00:00",
            "2026-01-06 12:00:00": "2026-01-06 12:00:00",
            "2026-01-06T12:00:00Z": "2026-01-06 12:00:00",
            "2026-01-06T12:00:00+01:00": None,
            "2026-01-06T12:00:00-05:00": None,
        }
    finally:
        conn.close()


def test_the_offset_guard_plans_over_a_bronze_column_that_is_not_text() -> None:
    """The guard's window is cast because the marker does not only sit on a
    transform chain: RFC 0016 D21's metadata audit puts it on `_ingested_at`,
    which is whatever the project landed.

    Executed rather than asserted on the rendered string, because the failure
    this guards against is a *binder* error — `substring(TIMESTAMP, INTEGER)`
    matches no function — and a rendering assertion cannot see it. It would
    have refused to compile the audit rather than refuse the value, on the one
    column no `coercible` rule can reach.
    """
    conn = duckdb.connect()
    try:
        conn.execute("CREATE TABLE bronze AS SELECT CAST('2026-01-06 09:00:00' AS TIMESTAMP) AS x")
        row = conn.execute(f"SELECT ({_iso_parse_sql('duckdb', 'x')}) FROM bronze").fetchone()
        assert row is not None
        assert str(row[0]) == "2026-01-06 09:00:00"
    finally:
        conn.close()
