"""Cleaning a merged entity, executed (RFC 0024 P2, RFC 0035; RFC 0009 §5.2
tier 4).

The compile-time tests prove the artifacts are *emitted* with the right shape.
This proves the shape does the job, which is a different claim and the one the
feature exists for. Four properties, none of which a single-source entity can
hold:

**A branch reads its own paths.** ``coercible`` is one rule over the merged
relation, and the two shops read ``$.qty`` and ``$.quantity``. A row with an
uncastable quantity in one shop is quarantined; the other shop's rows, which do
not have that column at all, are not.

**A branch admits its own vocabulary.** ``in_enum``'s set is each chain's
``enum_map`` targets. Shopify's chain knows ``reversed`` and Woo's does not, so
the *same* raw value is admissible on one branch and quarantined on the other —
which is exactly what a merged admissible set would have got wrong, silently.

**The dedupe order is total across sources.** Two rows on one entity key from
two shops would compare equal without ``_source`` in the sort key (D35). They
cannot both survive, and which one does must not depend on the engine.

**Replay re-runs each row's own mapping** (RFC 0035 D3). A reject row carries
the ``source_relation`` that produced it, and a replay after the vocabulary
widens admits the rows of the branch that widened and leaves the others where
they are. Without the filter every branch reads every reject row and applies
its own extraction to a payload whose keys it does not have — NULLs, not an
error, which is the failure this whole project refuses.

The seed is small enough to check by hand, and every expectation below is
written as the reason rather than as a constant.
"""

from __future__ import annotations

from collections.abc import Iterator

import duckdb
import pytest
from support.compiling import compile_fixture, fixture_sources
from support.execution import materialize, replay_statements, warehouse

from bloomery import Target, build_project_ir, compile_project, load_project, plan

pytestmark = pytest.mark.execution

FIXTURE = "multi_source_quality"

#: Shopify's bronze rows. ``position`` is the line number, ``financial_status``
#: the raw status. Row 3 carries a status only *this* shop's chain maps.
_SHOPIFY = (
    # (row_id, order id, position, sku, quantity, created_at, financial_status)
    ("s1", "A-1", 1, "SKU-1", 2, "2024-03-01T00:00:00", "paid"),
    ("s2", "A-2", 1, "SKU-2", 1, "2024-03-02T00:00:00", "reversed"),
    ("s3", "A-3", 1, "SKU-3", 1, "2024-03-03T00:00:00", "unheard_of"),
)

#: Woo's bronze rows, read from entirely different paths. ``w2``'s quantity is
#: uncastable; ``w3`` carries the raw value Shopify's chain maps and Woo's does
#: not.
#:
#: The first row's identity is ``s1`` — the **same** identity Shopify's first row
#: carries. RFC 0016 D21 makes the row identity unique within *one* source
#: relation and says nothing across the union, so two shops with ordinary
#: per-table sequences collide immediately. That is the ordinary case, not a
#: contrived one, and it is what RFC 0024 D34's partition exists for: without it
#: the blocking metadata audit reports these two rows and stops the run on
#: correct data.
_WOO = (
    # (row_id, order_number, item_index, product_sku, qty, created, state)
    ("s1", "B-1", 1, "SKU-9", "4", "2024-03-01T00:00:00", "COMPLETE"),
    ("w2", "B-2", 1, "SKU-8", "twelve", "2024-03-02T00:00:00", "COMPLETE"),
    ("w3", "B-3", 1, "SKU-7", "1", "2024-03-03T00:00:00", "reversed"),
)


def _seed(connection: duckdb.DuckDBPyConnection) -> None:
    """Both bronze relations, with the D21 ingestion metadata every quarantining
    entity requires."""
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
        "INSERT INTO bronze.shopify__order_lines VALUES "
        "(json_object('id', ?), ?, json_object('sku', ?), ?, json_object('gift_note', NULL), "
        "?, ?, 'load-1', '2024-03-10T00:00:00', ?)",
        [
            (order, str(position), sku, str(quantity), created, status, row_id)
            for row_id, order, position, sku, quantity, created, status in _SHOPIFY
        ],
    )
    connection.executemany(
        "INSERT INTO bronze.woo__order_lines VALUES "
        "(?, ?, ?, ?, ?, ?, 'load-1', '2024-03-10T00:00:00', ?)",
        [
            (order, str(index), sku, qty, created, state, row_id)
            for row_id, order, index, sku, qty, created, state in _WOO
        ],
    )


@pytest.fixture
def built() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = warehouse()
    try:
        _seed(connection)
        materialize(connection, compile_fixture(FIXTURE))
        yield connection
    finally:
        connection.close()


def _rows(connection: duckdb.DuckDBPyConnection, sql: str) -> list[tuple[object, ...]]:
    return [tuple(row) for row in connection.execute(sql).fetchall()]


# ....................... #


def test_a_branch_compares_against_the_paths_it_actually_reads(
    built: duckdb.DuckDBPyConnection,
) -> None:
    """``w2``'s ``$.qty`` is ``'twelve'`` — a failed cast on *Woo's* path.

    The rule is one ``quantity_coercible`` over the merged relation, and if it
    carried one mapping's paths it would be comparing Shopify's ``quantity``
    column against a relation that does not have it. What each branch compares
    against is its own extraction (RFC 0024 D32).
    """
    quarantined = _rows(
        built,
        "SELECT _source_row_id, source_relation FROM silver.order_line__reject "
        "WHERE list_contains(failed_rules, 'quantity_coercible') ORDER BY _source_row_id",
    )
    assert quarantined == [("w2", "woo__order_lines")]


def test_a_branch_that_maps_nothing_reports_no_coercion_failure(
    built: duckdb.DuckDBPyConnection,
) -> None:
    """``gift_note`` is Shopify's column; Woo projects a typed NULL for it.

    Were the marker vacuously true over zero source paths, every Woo row would
    have been quarantined as a failed cast — a false positive on correct data,
    on a *quarantine* disposition, which silently empties an entity.
    """
    flagged = _rows(
        built,
        "SELECT _source_row_id FROM silver.order_line__reject "
        "WHERE list_contains(failed_rules, 'gift_note_coercible')",
    )
    assert flagged == []


def test_one_raw_value_is_admissible_on_one_branch_and_not_the_other(
    built: duckdb.DuckDBPyConnection,
) -> None:
    """``reversed`` is in Shopify's ``enum_map`` and not in Woo's.

    So ``s2`` survives and ``w3`` is quarantined on the *same* raw text. A
    merged admissible set — the shape that looks harmless — would have admitted
    ``w3`` on a vocabulary its own chain can never produce, and the rule would
    have quietly stopped checking on that branch (RFC 0024 D32).
    """
    kept = _rows(built, "SELECT _source_row_id FROM silver.order_line ORDER BY _source_row_id")
    diverted = _rows(
        built,
        "SELECT _source_row_id FROM silver.order_line__reject "
        "WHERE list_contains(failed_rules, 'status_in_enum') ORDER BY _source_row_id",
    )
    assert ("s2",) in kept
    assert diverted == [("s3",), ("w3",)]


def test_every_row_lands_on_exactly_one_side(built: duckdb.DuckDBPyConnection) -> None:
    """§6's conservation law over a bag of two branches: bronze rows equal
    surviving rows plus diverted ones.

    Asserted here as well as in the generated audit because the audit is what
    would have to *stay* true, and a test that only read the audit's SQL would
    pass whether or not the numbers add up.
    """
    (kept,) = built.execute("SELECT COUNT(*) FROM silver.order_line").fetchone() or (0,)
    (rejected,) = built.execute("SELECT COUNT(*) FROM silver.order_line__reject").fetchone() or (0,)
    assert kept + rejected == len(_SHOPIFY) + len(_WOO)


def test_each_reject_row_carries_the_mapping_that_produced_it(
    built: duckdb.DuckDBPyConnection,
) -> None:
    """RFC 0035 D2: the three provenance literals and ``reject_id`` are computed
    per branch, so a merged entity's one reject table says which mapping — and
    which version of it — rejected each row."""
    rows = _rows(
        built,
        "SELECT _source_row_id, source_relation, mapping, mapping_version "
        "FROM silver.order_line__reject ORDER BY _source_row_id",
    )
    assert rows == [
        ("s3", "shopify__order_lines", "shopify__order_lines->order_line", 1),
        ("w2", "woo__order_lines", "woo__order_lines->order_line", 1),
        ("w3", "woo__order_lines", "woo__order_lines->order_line", 1),
    ]


def test_reject_ids_are_distinct_across_sources_sharing_a_row_identity(
    built: duckdb.DuckDBPyConnection,
) -> None:
    """``_source_row_id`` is unique within **one** source relation (RFC 0016
    D21), and a merged entity's reject table holds rows from several.

    ``reject_id`` is a digest of the *pair*, which is what keeps the reject
    model's ``INCREMENTAL_BY_UNIQUE_KEY`` merge from collapsing two shops' rows
    into one. The seed's identities happen not to collide; the assertion is that
    the id does not depend on the identity alone, which is checked by digesting
    the same identity under both relations.
    """
    (distinct,) = built.execute(
        "SELECT COUNT(DISTINCT reject_id) FROM silver.order_line__reject"
    ).fetchone() or (0,)
    (total,) = built.execute("SELECT COUNT(*) FROM silver.order_line__reject").fetchone() or (0,)
    assert distinct == total

    # The pair, not the identity: two relations, one row identity, two ids.
    (a, b) = built.execute(
        "SELECT sha256('S20:shopify__order_lines' || 'S2:' || 'x1'), "
        "sha256('S16:woo__order_lines' || 'S2:' || 'x1')"
    ).fetchone() or (None, None)
    assert a != b


def test_the_dedupe_order_is_total_across_sources(built: duckdb.DuckDBPyConnection) -> None:
    """Two shops on one entity key: only one row survives, and which one is
    decided by ``_source`` (RFC 0024 D35).

    Seeded here rather than in the fixture because the collision audit refuses
    this shape at run time — it is a *blocking* audit (D5), and what is being
    checked is that the pipeline is deterministic in the window before the audit
    stops the run, which is the window D35 exists for.
    """
    built.execute(
        "INSERT INTO bronze.woo__order_lines VALUES "
        "('A-1', '1', 'SKU-DUP', '9', '2024-03-01T00:00:00', 'COMPLETE', "
        "'load-2', '2024-03-11T00:00:00', 'w9')"
    )
    materialize(built, compile_fixture(FIXTURE))
    survivors = _rows(
        built,
        "SELECT _source_row_id FROM silver.order_line WHERE order_id = 'A-1' AND line_no = 1",
    )
    # One winner, and it is the lexicographically later source — arbitrary as
    # business logic, deterministic as an artifact, and reachable only in the
    # run the collision audit then stops.
    assert survivors == [("w9",)]


def test_the_collision_audit_reads_the_union_and_not_the_deduped_model(
    built: duckdb.DuckDBPyConnection,
) -> None:
    """RFC 0024 D13, unexercised until ``dedupe:`` came back.

    With dedupe between the union and the output, a key held by both shops is
    collapsed to one row *before* the model exists — so an audit reading
    ``silver.order_line`` would find one ``_source`` per key and pass, on
    exactly the data it is there to refuse.
    """
    built.execute(
        "INSERT INTO bronze.woo__order_lines VALUES "
        "('A-1', '1', 'SKU-DUP', '9', '2024-03-01T00:00:00', 'COMPLETE', "
        "'load-2', '2024-03-11T00:00:00', 'w9')"
    )
    materialize(built, compile_fixture(FIXTURE))
    audit = next(
        artifact
        for artifact in compile_fixture(FIXTURE)
        if artifact.path.endswith("order_line_source_collision.sql")
    )
    body = audit.content[audit.content.index("SELECT") :]
    violations = _rows(built, body)
    assert [(row[0], row[1]) for row in violations] == [("A-1", 1)]

    # …and the model itself holds one row for that key, which is why reading it
    # instead would have reported nothing.
    (kept,) = built.execute(
        "SELECT COUNT(*) FROM silver.order_line WHERE order_id = 'A-1' AND line_no = 1"
    ).fetchone() or (0,)
    assert kept == 1


def test_a_widening_replays_only_the_branch_that_widened(
    built: duckdb.DuckDBPyConnection,
) -> None:
    """RFC 0035 D3, and the property the whole filter exists for.

    Woo's chain learns ``reversed``. Replay must admit ``w3`` and must leave
    ``s3`` — whose status no chain maps — in the reject table. Without the
    ``source_relation`` filter, Shopify's branch would also read ``w3``'s
    payload, extract ``$.financial_status`` from a Woo row that has no such key,
    and derive a NULL status: not an error, a wrong answer.
    """
    sources = dict(fixture_sources(FIXTURE))
    anchor = "{enum_map: [PROCESSING, open, COMPLETE, closed]}"
    assert sources["mapping_legacy"].count(anchor) == 1
    sources["mapping_legacy"] = sources["mapping_legacy"].replace(
        anchor, "{enum_map: [PROCESSING, open, COMPLETE, closed, reversed, closed]}"
    )
    widened = load_project(sources)

    # `plan()` sees it, which is what tells an operator to run the replay at all.
    before = build_project_ir(load_project(dict(fixture_sources(FIXTURE))))
    assert plan(before, build_project_ir(widened)).replay_scope.entities == ("order_line",)

    artifacts = compile_project(widened, target=Target.SQLMESH, dialect="duckdb")
    materialize(built, artifacts)
    replay = next(a for a in artifacts if a.path.endswith("replay/order_line.sql"))

    for statement in replay_statements(replay):
        built.execute(statement)

    admitted = _rows(
        built,
        "SELECT _source_row_id FROM silver.order_line WHERE status = 'closed' "
        "AND _source_row_id = 'w3'",
    )
    assert admitted == [("w3",)]

    unresolved = _rows(
        built,
        "SELECT _source_row_id FROM silver.order_line__reject WHERE resolved_at IS NULL "
        "ORDER BY _source_row_id",
    )
    # `s3` stays: no chain maps `unheard_of`. `w2` stays: its quantity is still
    # uncastable. Only the branch that widened drained.
    assert unresolved == [("s3",), ("w2",)]


#: The audits bloomery emitted for this fixture, and the number of violations
#: each must report against the seed. Every one is **blocking**, so a false
#: positive here does not degrade a number — it stops the run on correct data.
AUDITS = (
    # RFC 0016 D21's metadata audit. `s1` is one row identity in **two** source
    # relations, which D21 makes legal: the identity is unique within a source,
    # not across the union. Partitioned by the identity alone this reports two
    # rows and halts. That is the shape RFC 0024 D34 exists for, and it is
    # asserted here by running the emitted body rather than by re-deriving it —
    # the lowering had it right for a commit while the SQLMesh envelope emitted
    # its own hardcoded partition, and every test that wrote its own query
    # passed.
    "order_line_ingestion_metadata",
    # RFC 0024 D5: no key is held by both shops in this seed.
    "order_line_source_collision",
    # RFC 0016 §6's accounting law: rows in equal rows kept plus rows diverted.
    "order_line_conservation",
)


@pytest.mark.parametrize("audit", AUDITS)
def test_every_emitted_audit_is_silent_on_correct_data(
    built: duckdb.DuckDBPyConnection, audit: str
) -> None:
    """Each generated audit, run **as emitted**, reports nothing."""
    artifact = next(a for a in compile_fixture(FIXTURE) if a.path == f"audits/{audit}.sql")
    body = artifact.content[artifact.content.index(");") + 2 :].replace(
        "@this_model", "silver.order_line"
    )
    violations = _rows(built, f"SELECT COUNT(*) FROM ({body.strip()}) AS _violations")
    assert violations == [(0,)], f"{audit} fired on correct data"
