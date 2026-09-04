"""e2e (RFC 0009 §5.2): the quality artifacts dbt refused until RFC 0052 —
the reject table, its replay macro and the quality mart — **executed**, not
parsed.

This tier exists because the two things RFC 0052 §9 names as risks are both
invisible to everything cheaper. The reject model's ``{% if is_incremental() %}``
arm does not run on a first build, so a green ``dbt build`` proves the branch
nobody reads; and ``ref()`` inside a ``run-operation`` macro is a claim about
dbt's renderer that no golden can make. Both are asserted here by building
twice with a re-delivery in between, and by running the macro.
"""

from __future__ import annotations

import pathlib
from collections.abc import Iterator

import pytest

from support.compiling import compile_fixture

pytestmark = pytest.mark.e2e

FIXTURE = "multi_source_quality"

PROFILES = """\
bloomery:
  target: local
  outputs:
    local:
      type: duckdb
      path: '{path}'
      schema: main
"""

#: Shopify's bronze rows. ``s2`` carries an unmappable status and is the row
#: this module quarantines, replays and re-delivers; the other two pass every
#: rule and are here so the entity is not empty, which would let a broken
#: reject model look like a clean one.
_SHOPIFY = (
    ("s1", "A-1", 1, "SKU-1", "2", "2024-03-01T00:00:00", "paid"),
    ("s2", "A-2", 1, "SKU-2", "not_a_number", "2024-03-02T00:00:00", "paid"),
)

_INSERT = (
    "INSERT INTO bronze.shopify__order_lines VALUES "
    "(json_object('id', ?), ?, json_object('sku', ?), ?, json_object('gift_note', NULL), "
    "?, ?, 'load-1', ?, ?)"
)


def _seed(database: pathlib.Path) -> None:
    """Both bronze relations with the D21 ingestion metadata a quarantining
    entity requires. Woo is created and left empty: the entity is a union, so
    the relation has to exist, and this module's claims are all about one
    branch."""
    import duckdb

    connection = duckdb.connect(str(database))
    try:
        connection.execute("CREATE SCHEMA IF NOT EXISTS bronze")
        connection.execute(
            """
            CREATE TABLE bronze.shopify__order_lines (
              "order" JSON, position VARCHAR, variant JSON, quantity VARCHAR,
              properties JSON, created_at VARCHAR, financial_status VARCHAR,
              _load_id VARCHAR, _ingested_at VARCHAR, _source_row_id VARCHAR
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE bronze.woo__order_lines (
              order_number VARCHAR, item_index VARCHAR, product_sku VARCHAR, qty VARCHAR,
              created VARCHAR, state VARCHAR,
              _load_id VARCHAR, _ingested_at VARCHAR, _source_row_id VARCHAR
            )
            """
        )
        connection.executemany(
            _INSERT,
            [
                (order, str(position), sku, quantity, created, status, "2024-03-10T00:00:00", row)
                for row, order, position, sku, quantity, created, status in _SHOPIFY
            ],
        )
    finally:
        connection.close()


def _write_project(root: pathlib.Path, database: pathlib.Path) -> None:
    for artifact in compile_fixture(FIXTURE, target="dbt", dialect="duckdb"):
        path = root / artifact.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(artifact.content, encoding="utf-8")
    (root / "profiles.yml").write_text(PROFILES.format(path=database), encoding="utf-8")


def _dbt(root: pathlib.Path, *args: str) -> object:
    from dbt.cli.main import dbtRunner

    return dbtRunner().invoke(
        [*args, "--project-dir", str(root), "--profiles-dir", str(root)]
    )


def _rows(database: pathlib.Path, sql: str) -> list[tuple[object, ...]]:
    import duckdb

    connection = duckdb.connect(str(database))
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


@pytest.fixture
def built(tmp_path: pathlib.Path) -> Iterator[tuple[pathlib.Path, pathlib.Path]]:
    """The project, built once. ``run`` rather than ``build``: the fixture's
    blocking metadata audit is a *test*, and this module's subject is the
    models — a test failing on seeded data would stop the run before the reject
    table this asserts about exists."""
    database = tmp_path / "warehouse.duckdb"
    _seed(database)
    _write_project(tmp_path, database)
    result = _dbt(tmp_path, "run")
    assert result.success, getattr(result, "exception", None)
    yield tmp_path, database


def test_the_first_build_quarantines_the_row_that_fails_a_rule(
    built: tuple[pathlib.Path, pathlib.Path],
) -> None:
    """The floor everything below stands on. If the reject table were empty
    here, every assertion about preservation and replay would pass vacuously."""
    _root, database = built
    rejected = _rows(database, "SELECT _source_row_id FROM silver.order_line__reject")
    assert rejected == [("s2",)]
    admitted = _rows(database, "SELECT _source_row_id FROM silver.order_line ORDER BY 1")
    assert admitted == [("s1",)]


def test_a_re_delivery_keeps_first_seen_and_advances_last_seen(
    built: tuple[pathlib.Path, pathlib.Path],
) -> None:
    """RFC 0052 D1, and the reason §6 makes *two* builds a requirement.

    The first build takes the ``{% else %}`` arm, so a green single build says
    nothing about the branch that preserves anything. Here the same source row
    is delivered again with a later ``_ingested_at``, and the second build has
    to keep ``first_seen`` at the original delivery while ``last_seen`` moves —
    which on SQLMesh is a ``when_matched`` clause and here is a ``COALESCE``
    against ``{{ this }}`` in the model's own projection.
    """
    import duckdb

    root, database = built
    before = _rows(database, "SELECT first_seen, last_seen FROM silver.order_line__reject")
    assert before and before[0][0] == before[0][1], (
        "first_seen and last_seen must start equal, or the assertion below proves nothing"
    )

    connection = duckdb.connect(str(database))
    try:
        connection.execute(
            _INSERT,
            # A later `created_at`, because that is the entity's dedupe field:
            # two deliveries agreeing on it (and on the tie-breaks) are
            # indistinguishable, and the survivor is then arbitrary — which
            # would leave this test asserting that a re-delivery nothing kept
            # did not move `last_seen`.
            ("A-2", "1", "SKU-2", "still_not_a_number", "2024-03-05T00:00:00", "paid",
             "2024-03-20T00:00:00", "s2"),
        )
    finally:
        connection.close()

    assert _dbt(root, "run").success
    after = _rows(
        database,
        "SELECT first_seen, last_seen, _source_row_id FROM silver.order_line__reject",
    )
    assert len(after) == 1, "the re-delivery landed on a second row — unique_key is inert"
    assert after[0][0] == before[0][0], "first_seen moved with the re-delivery"
    assert after[0][1] > before[0][1], "last_seen did not advance"


def test_replay_admits_the_row_a_corrected_delivery_fixes(
    built: tuple[pathlib.Path, pathlib.Path],
) -> None:
    """RFC 0052 D3/D14, executed. The macro's relations are named through
    ``ref()``, which resolves only inside dbt's Jinja, and its three statements
    run as one unit of work.

    The correction is delivered to bronze, the reject table is rebuilt so it
    reflects the current mapping, and the macro then merges the passer into the
    entity and stamps its reject row resolved.
    """
    import duckdb

    root, database = built
    connection = duckdb.connect(str(database))
    try:
        connection.execute(
            _INSERT,
            # Later on the dedupe field, so the correction is the row the
            # union keeps (see the re-delivery test).
            ("A-2", "1", "SKU-2", "7", "2024-03-05T00:00:00", "paid",
             "2024-03-20T00:00:00", "s2"),
        )
    finally:
        connection.close()

    assert _dbt(root, "run").success
    result = _dbt(root, "run-operation", "replay_order_line")
    assert result.success, getattr(result, "exception", None)

    admitted = _rows(
        database, "SELECT _source_row_id, quantity FROM silver.order_line ORDER BY 1"
    )
    assert ("s2", 7) in admitted, "replay did not admit the corrected row"
    resolved = _rows(
        database,
        "SELECT resolved_at IS NOT NULL FROM silver.order_line__reject "
        "WHERE _source_row_id = 's2'",
    )
    assert resolved == [(True,)], "the reject row was not stamped resolved"


def test_a_full_refresh_loses_resolved_reject_history(
    built: tuple[pathlib.Path, pathlib.Path],
) -> None:
    """RFC 0052 D13, asserted rather than prevented.

    ``--full-refresh`` drops the relation and takes the ``{% else %}`` arm,
    whose SELECT sees only currently-quarantined rows — so a row that replay
    resolved does not come back. The contract says so, and a model that refused
    to full-refresh would be one an operator cannot recover; what would be
    wrong is discovering it in production, so it is pinned here.
    """
    import duckdb

    root, database = built
    connection = duckdb.connect(str(database))
    try:
        connection.execute("UPDATE silver.order_line__reject SET resolved_at = CURRENT_TIMESTAMP")
    finally:
        connection.close()
    assert _rows(
        database, "SELECT COUNT(*) FROM silver.order_line__reject WHERE resolved_at IS NOT NULL"
    ) == [(1,)]

    assert _dbt(root, "run", "--full-refresh").success
    assert _rows(
        database, "SELECT COUNT(*) FROM silver.order_line__reject WHERE resolved_at IS NOT NULL"
    ) == [(0,)], "the resolved row survived a full refresh — D13 describes a loss that did not happen"


def test_the_two_targets_reject_tables_agree_row_for_row(tmp_path: pathlib.Path) -> None:
    """RFC 0052 D12 — the leg that turns per-artifact parity into a claim about
    the rows.

    Per-artifact goldens cannot make it: the two targets emit different bytes on
    purpose, so nothing that compares files can say the tables end up the same.
    And the mechanisms genuinely differ — SQLMesh preserves `first_seen` in a
    `when_matched` clause the engine applies during a merge, dbt resolves it in
    the model's own projection and lets the write replace a whole row. Two
    designs for one sentence in RFC 0016 §5.6; this is what checks they say it.

    **One bronze, copied rather than seeded twice.** The seed runs once and the
    file is duplicated, so the inputs are byte-identical by construction — two
    seeding routines kept in step is what would have made a divergence
    ambiguous.

    **Two runs on each side**, because the first is where the two agree by
    default: dbt's `{% else %}` arm and SQLMesh's initial `CREATE TABLE AS` are
    the same SELECT. The re-delivery is what puts the incremental branch and
    the `when_matched` clause against each other.
    """
    import shutil

    import duckdb

    from support.execution import materialize

    seeded = tmp_path / "seeded.duckdb"
    _seed(seeded)
    dbt_database = tmp_path / "dbt.duckdb"
    sqlmesh_database = tmp_path / "sqlmesh.duckdb"
    shutil.copy(seeded, dbt_database)
    shutil.copy(seeded, sqlmesh_database)

    redelivery = (
        "A-2", "1", "SKU-2", "still_not_a_number", "2024-03-05T00:00:00", "paid",
        "2024-03-20T00:00:00", "s2",
    )

    _write_project(tmp_path, dbt_database)
    assert _dbt(tmp_path, "run").success
    connection = duckdb.connect(str(dbt_database))
    try:
        connection.execute(_INSERT, redelivery)
    finally:
        connection.close()
    assert _dbt(tmp_path, "run").success

    artifacts = compile_fixture(FIXTURE, dialect="duckdb")
    connection = duckdb.connect(str(sqlmesh_database))
    try:
        connection.execute("SET TimeZone = 'UTC'")
        for schema in ("silver", "gold"):
            connection.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        materialize(connection, artifacts)
        connection.execute(_INSERT, redelivery)
        materialize(connection, artifacts)
    finally:
        connection.close()

    columns = (
        "reject_id, source_relation, mapping, mapping_version, failed_rules, key_values, "
        "_load_id, _ingested_at, _source_row_id, first_seen, last_seen, resolved_at, "
        "last_evaluated_at"
    )
    query = f"SELECT {columns} FROM silver.order_line__reject ORDER BY reject_id"
    connection = duckdb.connect(str(dbt_database))
    try:
        from_dbt = connection.execute(query).fetchall()
    finally:
        connection.close()
    connection = duckdb.connect(str(sqlmesh_database))
    try:
        from_sqlmesh = connection.execute(query).fetchall()
    finally:
        connection.close()

    assert from_dbt, "an empty comparison agrees with anything"
    assert from_dbt == from_sqlmesh
    # `raw` is excluded above because it is a JSON payload whose two engines
    # may key it differently; the columns compared are the ones RFC 0016 §5.6
    # gives meanings to, and `first_seen` versus `last_seen` is the pair the
    # two mechanisms could disagree about.
    assert from_dbt[0][columns.split(", ").index("first_seen")] != from_dbt[0][
        columns.split(", ").index("last_seen")
    ], "the re-delivery did not separate first_seen from last_seen — the comparison is vacuous"
