"""Replay on a historical entity, executed (S-0003 (§5.2), S-0026/tier-contracts tier 4).

A ``scd: type2`` entity's relation belongs to the target framework, so replay
does not merge a recovered row into it — the merge would write a version with
no validity interval, which is present, queryable and invisible to every as-of
join. It writes the row back to **bronze** instead, and the framework versions
it on its next run.

What tier 4 can assert is the half the spike could not reach: bloomery's own
bookkeeping across that route. DuckDB is not dbt and is not SQLMesh, so nothing
here versions anything; the claim that an as-of join *finds* the recovered row
(S-0003/D-3) is the e2e tier's, next door.

The specimen: two customers are delivered, and ``c2`` arrives with a segment
the spec does not know. It is diverted to ``customer__reject``. Someone widens
the rule to admit it — the enum-widening walkthrough S-0033/quarantine-one-reject-table-per-entity calls "the
normal path" — and replay re-derives the row from its stored payload.

Bronze is never edited here, only the spec: a row that could be fixed in bronze
would not need replay at all, which is the whole reason the reject table keeps
``raw``.

Three properties, in the order an operator meets them:

1. the re-delivery lands in bronze carrying the **original** ``_source_row_id``
   and a ``_load_id`` that says replay wrote it;
2. rebuilding the entity from bronze then admits the row, which is the whole
   point of routing through the pipeline rather than around it;
3. the reject row resolves on the **next** replay, not this one — resolution is
   eventually consistent on this route, and statement 2 is unchanged.
"""

from __future__ import annotations

from collections.abc import Iterator

import duckdb
import pytest

from support.compiling import extract_select, fixture_sources, load_fixture
from support.execution import replay_statements

from bloomery import Target, compile_project, load_project
from bloomery.emit import EmittedArtifact
from bloomery.quality import REPLAY_LOAD_ID

pytestmark = pytest.mark.execution

FIXTURE = "scd2_replay"

#: ``(customer_id, segment, signed_up_at, _ingested_at, _load_id,
#: _source_row_id)``. The
#: second row's segment is not one the rule admits, so it is diverted.
DELIVERY = [
    ("c1", "smb", "2023-01-15T00:00:00", "2024-01-01 00:00:00", "load-1", "r1"),
    ("c2", "startup", "2023-05-02T00:00:00", "2024-01-01 00:00:00", "load-1", "r2"),
    # Diverted for a reason the widening does not reach, so it is the row that
    # must *not* be re-delivered — "the passers go back" is a claim about which
    # rows, and a route that delivers everything satisfies every assertion
    # about the one that passed.
    ("c3", "typo", "2023-06-02T00:00:00", "2024-01-01 00:00:00", "load-1", "r3"),
]

#: The rule as the fixture declares it, and as the widening rewrites it —
#: spelled as the literal spec text, so the edit under test is the edit a
#: reviewer would see in a pull request.
NARROW = "\"segment IN ('smb', 'ent')\""
WIDE = "\"segment IN ('smb', 'ent', 'startup')\""

_BRONZE = (
    "CREATE TABLE bronze.crm__customers (customer_id VARCHAR, segment VARCHAR, "
    "signed_up_at VARCHAR, _ingested_at TIMESTAMP, _load_id VARCHAR, "
    "_source_row_id VARCHAR)"
)


def _compiled(*, wide: bool = False) -> tuple[EmittedArtifact, ...]:
    sources = dict(fixture_sources(FIXTURE))

    if wide:
        assert NARROW in sources["entity_model"]
        sources["entity_model"] = sources["entity_model"].replace(NARROW, WIDE)

    _, catalog = load_fixture(FIXTURE)
    return compile_project(
        load_project(sources), target=Target.SQLMESH, dialect="duckdb", catalog=catalog
    )


def _artifact(artifacts: tuple[EmittedArtifact, ...], path: str) -> str:
    return next(a for a in artifacts if a.path == path).content


def _rebuild(
    conn: duckdb.DuckDBPyConnection,
    relation: str,
    path: str,
    artifacts: tuple[EmittedArtifact, ...],
) -> None:
    """Build one silver relation from bronze, as a fresh table.

    A full rebuild rather than an incremental apply, because what is under test
    is which rows the pipeline *admits* out of bronze — and the framework, not
    this harness, is what would accumulate versions.
    """
    select = extract_select(_artifact(artifacts, path))
    conn.execute(f"CREATE OR REPLACE TABLE {relation} AS {select}")


@pytest.fixture
def warehouse() -> Iterator[duckdb.DuckDBPyConnection]:
    conn = duckdb.connect()
    conn.execute("CREATE SCHEMA bronze")
    conn.execute("CREATE SCHEMA silver")
    conn.execute(_BRONZE)
    conn.executemany("INSERT INTO bronze.crm__customers VALUES (?, ?, ?, ?, ?, ?)", DELIVERY)
    narrow = _compiled()
    _rebuild(conn, "silver.customer", "models/silver/customer.sql", narrow)
    _rebuild(conn, "silver.customer__reject", "models/silver/customer__reject.sql", narrow)
    yield conn
    conn.close()


def _replay(conn: duckdb.DuckDBPyConnection, artifacts: tuple[EmittedArtifact, ...]) -> None:
    artifact = next(a for a in artifacts if a.path.startswith("replay/"))
    for statement in replay_statements(artifact):
        conn.execute(statement)


def test_the_diverted_row_is_out_of_the_entity_and_in_the_reject_table(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    """The starting state, asserted rather than assumed — every claim below is
    about a row moving, and a row that was never diverted cannot move."""
    assert warehouse.execute("SELECT customer_id FROM silver.customer").fetchall() == [("c1",)]
    assert sorted(
        warehouse.execute(
            "SELECT _source_row_id, resolved_at FROM silver.customer__reject"
        ).fetchall()
    ) == [("r2", None), ("r3", None)]


def test_replay_writes_the_recovered_row_back_to_bronze_not_to_the_entity(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    """The route itself (D2).

    The entity is untouched by replay — on a type 2 entity that relation is the
    framework's — and bronze gains a delivery whose identity is the original's,
    which is what lets the reject row be resolved later rather than re-diverted
    forever under a new one.
    """
    _replay(warehouse, _compiled(wide=True))

    assert warehouse.execute("SELECT customer_id FROM silver.customer").fetchall() == [("c1",)]
    delivered = warehouse.execute(
        "SELECT customer_id, segment, _load_id, _source_row_id FROM bronze.crm__customers "
        f"WHERE _load_id = '{REPLAY_LOAD_ID}'"
    ).fetchall()
    assert delivered == [("c2", "startup", REPLAY_LOAD_ID, "r2")]


def test_the_pipeline_admits_the_re_delivered_row_and_the_next_replay_resolves_it(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    """Statements 2 and 3 are unchanged, and that is the design (D2).

    The resolution stamp tests that the reject row's identity is now in the
    entity. Nothing enters the entity during replay on this route, so the stamp
    lands one run later — after the pipeline (here) or the framework (in
    production) has admitted the re-delivery. No new column, no new state.
    """
    wide = _compiled(wide=True)
    _replay(warehouse, wide)

    assert warehouse.execute(
        "SELECT resolved_at FROM silver.customer__reject WHERE _source_row_id = 'r2'"
    ).fetchall() == [(None,)]

    _rebuild(warehouse, "silver.customer", "models/silver/customer.sql", wide)
    assert sorted(
        row[0] for row in warehouse.execute("SELECT customer_id FROM silver.customer").fetchall()
    ) == ["c1", "c2"]

    _replay(warehouse, wide)
    resolved = warehouse.execute(
        "SELECT resolved_at FROM silver.customer__reject WHERE _source_row_id = 'r2'"
    ).fetchone()
    assert resolved is not None and resolved[0] is not None


def test_re_running_replay_does_not_multiply_the_delivery(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    """Replay is idempotent (S-0033/D-22), and on this route that is a claim
    about bronze rather than about the entity.

    A second run before the framework has admitted the row re-delivers it —
    the reject row is still unresolved, so it is still a candidate — and the
    entity's `dedupe:` is what collapses the pair. That is why this route
    refuses an entity without one.
    """
    wide = _compiled(wide=True)
    _replay(warehouse, wide)
    _replay(warehouse, wide)

    _rebuild(warehouse, "silver.customer", "models/silver/customer.sql", wide)
    assert warehouse.execute(
        "SELECT COUNT(*) FROM silver.customer WHERE customer_id = 'c2'"
    ).fetchone() == (1,)


def test_a_row_that_still_fails_is_not_re_delivered(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    """The half "the passers are re-delivered" leaves implicit.

    `c3` is diverted for a reason the widening does not reach, so it is still
    quarantined after it. Writing it back to bronze would put a row the rules
    refuse into the landing zone on every run, and the pipeline would divert it
    again — a loop that looks like a working feature.
    """
    _replay(warehouse, _compiled(wide=True))

    delivered = warehouse.execute(
        "SELECT customer_id FROM bronze.crm__customers "
        f"WHERE _load_id = '{REPLAY_LOAD_ID}' ORDER BY 1"
    ).fetchall()
    assert delivered == [("c2",)]


def test_a_resolved_reject_row_is_not_re_delivered(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    """Replay's own filter, on the route where it matters most.

    A reject row keeps `resolved_at` as audit history — retention deletes it,
    never replay — so a resolved row stays in the table forever. Re-delivering
    it would put a row bronze already has back into bronze on every run, and
    `dedupe:` would hide that by collapsing the pair: the count in the entity
    stays right while the landing zone grows without bound.
    """
    wide = _compiled(wide=True)
    _replay(warehouse, wide)
    _rebuild(warehouse, "silver.customer", "models/silver/customer.sql", wide)
    _replay(warehouse, wide)  # this one stamps resolved_at

    before = warehouse.execute(
        f"SELECT COUNT(*) FROM bronze.crm__customers WHERE _load_id = '{REPLAY_LOAD_ID}'"
    ).fetchone()
    _replay(warehouse, wide)
    after = warehouse.execute(
        f"SELECT COUNT(*) FROM bronze.crm__customers WHERE _load_id = '{REPLAY_LOAD_ID}'"
    ).fetchone()

    assert before == after


def test_one_entity_key_can_have_at_most_one_candidate(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    """Why the re-delivery needs no winner selection of its own.

    The merge path picks one winner per entity key before admitting anything,
    because it writes into the entity directly. This route does not, and the
    reason is the pipeline's fixed order: dedupe runs **before** the rules
    (S-0033/fixed-pipeline-order-and-lowering), partitioned by the entity key — so at most one row per key
    ever reaches a quarantine rule, and the reject table cannot hold two
    candidates for one key. The route refuses an entity without `dedupe:`,
    which is what makes that true rather than usual.

    Two bronze deliveries on one key, both with a segment the spec refuses: the
    older one is deduped away and never becomes a reject row at all.
    """
    warehouse.executemany(
        "INSERT INTO bronze.crm__customers VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("k1", "startup", "2023-01-01T00:00:00", "2024-01-01 00:00:00", "load-1", "a"),
            ("k1", "typo", "2023-01-02T00:00:00", "2024-02-01 00:00:00", "load-2", "b"),
        ],
    )
    narrow = _compiled()
    _rebuild(warehouse, "silver.customer__reject", "models/silver/customer__reject.sql", narrow)

    assert warehouse.execute(
        "SELECT _source_row_id FROM silver.customer__reject WHERE _source_row_id IN ('a', 'b')"
    ).fetchall() == [("b",)]


def test_a_reject_is_not_resolved_by_a_version_that_predates_it(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    """A type 2 relation is a history, so membership in it is not evidence that
    *this* recovery worked.

    A source row that was admitted once, later quarantined, and now replayed
    still has its old version sitting in the entity. The plain membership test
    the type 1 route uses therefore resolved the reject row in the same run
    that re-delivered it — before the framework had versioned anything — and a
    delivery that is then not admitted leaves a drained reject row that never
    replays again. Reproduced on dbt, where the reject read resolved while the
    snapshot still held only the previous value (PR #128).

    The entity's versions are seeded by hand here, the way `test_as_of_join`
    seeds them: the framework writes them, and what is under test is the
    statement bloomery emits against what the framework left behind.
    """
    # `c2` is quarantined, and the entity already holds a version of it from a
    # delivery that predates the bad one.
    warehouse.execute(
        "INSERT INTO silver.customer BY NAME "
        "(SELECT 'c2' AS customer_id, 'ent' AS segment, NULL::TIMESTAMP AS signed_up_at, "
        "TIMESTAMP '2023-12-01' AS _ingested_at, 'load-0' AS _load_id, "
        "'r2' AS _source_row_id, [] AS _quality_flags, TRUE AS _quality_ok)"
    )
    wide = _compiled(wide=True)
    _replay(warehouse, wide)

    assert warehouse.execute(
        "SELECT resolved_at FROM silver.customer__reject WHERE _source_row_id = 'r2'"
    ).fetchall() == [(None,)]

    # The framework versions the re-delivery: a row for the same identity, now
    # newer than the reject row's own clock.
    warehouse.execute(
        "INSERT INTO silver.customer BY NAME "
        "(SELECT 'c2' AS customer_id, 'ent' AS segment, NULL::TIMESTAMP AS signed_up_at, "
        "CURRENT_TIMESTAMP::TIMESTAMP AS _ingested_at, 'load-0' AS _load_id, "
        "'r2' AS _source_row_id, [] AS _quality_flags, TRUE AS _quality_ok)"
    )
    _replay(warehouse, wide)

    resolved = warehouse.execute(
        "SELECT resolved_at FROM silver.customer__reject WHERE _source_row_id = 'r2'"
    ).fetchone()
    assert resolved is not None and resolved[0] is not None
