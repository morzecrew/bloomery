"""The generated key audit, executed (S-0083/D-1, S-0083/D-3, S-0083/D-6).

``<entity>_key_unique`` is blocking, so both directions matter: a repeated key
must stop the build, and the history a type2 entity keeps must not. The bodies
run as emitted, with ``@this_model`` substituted the way the framework would.
"""

from __future__ import annotations

from collections.abc import Iterator

import duckdb
import pytest

from bloomery import Target, compile_project, load_project
from bloomery.emit.sqlmesh import WHOLE_MODEL
from support.compiling import compile_fixture
from support.execution import audit_body

pytestmark = pytest.mark.execution

FIXTURE = "scd2_current"


@pytest.fixture
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = duckdb.connect()
    connection.execute("CREATE SCHEMA silver")
    connection.execute('CREATE TABLE silver."order" (order_id VARCHAR, amount INTEGER)')
    connection.execute(
        "CREATE TABLE silver.customer (customer_id VARCHAR, segment VARCHAR, "
        "valid_from TIMESTAMP, valid_to TIMESTAMP)"
    )
    yield connection
    connection.close()


def _run(conn: duckdb.DuckDBPyConnection, entity: str, relation: str) -> list[tuple[object, ...]]:
    artifact = next(
        a for a in compile_fixture(FIXTURE, dialect="duckdb") if a.path == f"audits/{entity}_key_unique.sql"
    )
    return conn.execute(audit_body(artifact, relation)).fetchall()


def test_a_repeated_key_fails_the_build(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("""INSERT INTO silver."order" VALUES ('o1', 1), ('o1', 2), ('o2', 3)""")
    assert _run(conn, "order", 'silver."order"') == [("o1", 2)]


def test_distinct_keys_pass(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("""INSERT INTO silver."order" VALUES ('o1', 1), ('o2', 3)""")
    assert _run(conn, "order", 'silver."order"') == []


def test_two_versions_with_one_current_pass(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        "INSERT INTO silver.customer VALUES "
        "('c1', 'smb', '2023-01-15', '2024-06-01'), "
        "('c1', 'ent', '2024-06-01', NULL), "
        "('c2', 'smb', '2023-05-02', NULL)"
    )
    assert _run(conn, "customer", "silver.customer") == []


def test_two_current_versions_of_one_key_fail(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        "INSERT INTO silver.customer VALUES "
        "('c1', 'smb', '2023-01-15', NULL), "
        "('c1', 'ent', '2024-06-01', NULL)"
    )
    assert _run(conn, "customer", "silver.customer") == [("c1", 2)]


def test_a_dedupe_entity_carries_no_key_audit() -> None:
    """S-0083/D-2: `dedupe` enforces the key by construction."""
    paths = {a.path for a in compile_fixture("scd2_replay", dialect="duckdb")}
    assert "audits/order_key_unique.sql" in paths
    assert "audits/customer_key_unique.sql" not in paths


# ....................... #
# The windowed form on an INCREMENTAL_BY_TIME_RANGE entity (S-0083/D-6)

_PARTITIONED_MODEL = """\
spec_version: 1
entities:
  event:
    grain: one row per event
    key: [event_id]
    materialization: incremental_by_partition
    partition_by: [event_date]
    fields:
      event_id: {type: string, required: true}
      event_date: {type: date}
"""

_PARTITIONED_MAPPING = """\
mapping_version: 1
source: raw__events
target: event
key:
  event_id: {from: "$.id", transform: [to_string]}
fields:
  event_date: {from: "$.happened_at", transform: [{parse_date: ISO8601}]}
"""

#: What the pinned SQLMesh renders ``@this_model`` to in an audit on a
#: time-range model: the physical table filtered to the run's interval.
_WINDOW = "(SELECT * FROM silver.event WHERE event_date BETWEEN '2024-01-02' AND '2024-01-02')"


def _windowed_body() -> str:
    project = load_project(
        {"entity_model": _PARTITIONED_MODEL, "mapping": _PARTITIONED_MAPPING}
    )
    artifact = next(
        a
        for a in compile_project(project, target=Target.SQLMESH, dialect="duckdb")
        if a.path == "audits/event_key_unique.sql"
    )
    _envelope, _sep, body = artifact.content.partition(");")
    assert WHOLE_MODEL in body
    return body.replace(WHOLE_MODEL, "silver.event").replace("@this_model", _WINDOW)


def test_a_partitioned_run_checks_its_own_keys_against_the_whole_model() -> None:
    conn = duckdb.connect()
    conn.execute("CREATE SCHEMA silver")
    conn.execute("CREATE TABLE silver.event (event_id VARCHAR, event_date DATE)")
    conn.execute(
        "INSERT INTO silver.event VALUES "
        # Repeated wholly before the window: an earlier run's to report.
        "('e0', '2024-01-01'), ('e0', '2024-01-01'), "
        # Written by this run, and already held by an earlier partition.
        "('e1', '2024-01-01'), ('e1', '2024-01-02'), "
        # Written by this run, once.
        "('e2', '2024-01-02')"
    )
    try:
        assert conn.execute(_windowed_body()).fetchall() == [("e1", 2)]
    finally:
        conn.close()
