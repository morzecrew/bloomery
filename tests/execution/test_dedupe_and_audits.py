"""Dedupe semantics and the blocking audits, executed (RFC 0016 §5.4/D20/D21).

``keys.csv`` is the corpus file built for this module: seven specimens that
walk the dedupe total order down to its last sort key, four that pin the null
and empty-string key parts, and six **deliberate ingestion-metadata
violations** whose ``_expected`` is ``fail`` — rows the generated blocking
audit must stop the run on.

The two halves are seeded separately on purpose. A run carrying the metadata
violations is a run that must not produce numbers, so mixing them into the
ordinary seed would make every other assertion a statement about a run that
should never have happened.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from decimal import Decimal

import duckdb
import pytest
from bloomery.emit.lowering import _candidate_wins
from bloomery.ir import DedupeIR
from support.compiling import compile_fixture
from support.plan_ir import entity as plan_entity
from support.dirty import (
    FIXTURE,
    KEPT,
    QUARANTINED,
    audits_of,
    build_corpus,
    cases,
    dispositions,
)
from support.execution import audit_body

pytestmark = pytest.mark.execution

#: The audits the dirty fixture's entities carry, compiled once.
AUDITS = audits_of(compile_fixture(FIXTURE))


@pytest.fixture(scope="module")
def clean_run() -> Iterator[duckdb.DuckDBPyConnection]:
    """The ordinary seed: ``keys.csv`` minus its six metadata violations."""
    connection = build_corpus()
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def violating_run() -> Iterator[duckdb.DuckDBPyConnection]:
    """The seed the D21 audit exists for. The models still *build* — SQLMesh
    audits run after the model, which is exactly why the audit is blocking:
    the table exists and is wrong, and the run must not continue past it."""
    connection = build_corpus(metadata_violations=True)
    yield connection
    connection.close()


def _by_case(conn: duckdb.DuckDBPyConnection) -> dict[str, tuple[str, tuple[str, ...]]]:
    landed = dispositions(conn, "dirty_key")
    return {case: landed[row_id] for row_id, case in cases("keys.csv").items() if row_id in landed}


# ....................... #
# The total order (D20)


def test_the_dedupe_winner_is_the_newest_and_the_loser_is_not_in_the_entity(
    clean_run: duckdb.DuckDBPyConnection,
) -> None:
    landed = _by_case(clean_run)
    assert landed["exact_duplicate_newer"] == (KEPT, ())
    assert "exact_duplicate_older" not in landed  # neither entity nor reject


def test_a_recency_tie_is_broken_by_the_declared_tie_break_column(
    clean_run: duckdb.DuckDBPyConnection,
) -> None:
    """THE case D6 makes ``tie_break`` mandatory for: identical
    ``_ingested_at``, so recency cannot decide, and ``load_a`` loses to
    ``load_b`` on DESC. The twins carry *different amounts*, so a wrong
    tie-break is observable in the value and not only in the row identity."""
    landed = _by_case(clean_run)
    assert landed["tie_on_recency_higher_load"] == (KEPT, ())
    assert "tie_on_recency_lower_load" not in landed
    amount = clean_run.execute(
        "SELECT amount FROM silver.dirty_key WHERE order_id = 'ORD-1002'"
    ).fetchone()
    assert amount == (Decimal("22.000000000"),)


def test_when_every_declared_sort_key_ties_the_source_row_identity_decides(
    clean_run: duckdb.DuckDBPyConnection,
) -> None:
    """D20: after ``field`` DESC and the tie-breaks, the final sort key is
    ``_source_row_id`` DESC — so no two rows can compare equal and the winner
    is unique *by construction*. Without it the winner would be arbitrary and
    a backfill would disagree with the original run."""
    landed = _by_case(clean_run)
    assert landed["tie_through_load_id_higher_srid"] == (KEPT, ())
    assert "tie_through_load_id_lower_srid" not in landed
    amount = clean_run.execute(
        "SELECT amount FROM silver.dirty_key WHERE order_id = 'ORD-1003'"
    ).fetchone()
    assert amount == (Decimal("33.000000000"),)


def test_near_duplicates_that_only_collide_after_normalization_stay_two_rows(
    clean_run: duckdb.DuckDBPyConnection,
) -> None:
    """The corpus records the fact, the spec states the policy: no trim/lower
    is declared, so ``ORD-1004``/``ord-1004`` and the padded/clean ``ORD-1005``
    pair are four distinct keys and dedupe sees no duplicate at all."""
    landed = _by_case(clean_run)
    for case in (
        "case_variant_upper",
        "case_variant_lower",
        "whitespace_variant_padded",
        "whitespace_variant_clean",
    ):
        assert landed[case] == (KEPT, ()), case


def test_dedupe_losers_are_counted_never_silently_vanished(
    clean_run: duckdb.DuckDBPyConnection,
) -> None:
    """The whole point of ``rows_deduped`` (§5.8): a loser leaves the entity
    and leaves a *number* behind. Three losers in ``keys.csv``, reported once
    on the entity's accounting row — dedupe happens once, before any rule, so
    the count belongs to the entity and summing it must give three, not three
    per rule."""
    total = clean_run.execute(
        "SELECT SUM(rows_deduped) FROM gold.mart_data_quality WHERE entity = 'dirty_key'"
    ).fetchone()
    assert total == (3,)
    bronze, silver, rejects = clean_run.execute(
        "SELECT (SELECT COUNT(*) FROM bronze.dirty__keys),"
        "       (SELECT COUNT(*) FROM silver.dirty_key),"
        "       (SELECT COUNT(*) FROM silver.dirty_key__reject WHERE resolved_at IS NULL)"
    ).fetchone() or (0, 0, 0)
    assert bronze - (silver + rejects) == 3


def test_null_and_empty_key_parts_quarantine_on_different_rules(
    clean_run: duckdb.DuckDBPyConnection,
) -> None:
    """A key is only as non-null as its weakest part — and the empty STRING
    beside the NULL is non-null, so it needs a different rule. Conflating the
    two silently drops half the specimens."""
    landed = _by_case(clean_run)
    assert landed["null_key_part_order_id"] == (QUARANTINED, ("order_id_present",))
    assert landed["null_key_part_line_no"] == (QUARANTINED, ("line_no_present",))
    assert landed["empty_string_key_part"] == (QUARANTINED, ("order_id_not_empty",))


# ....................... #
# The D21 blocking audit — the run stops


def _metadata_violations(
    conn: duckdb.DuckDBPyConnection, relation: str = "silver.dirty_key"
) -> list[str | None]:
    cursor = conn.execute(audit_body(AUDITS["dirty_key_ingestion_metadata"], relation))
    columns = [description[0] for description in cursor.description or ()]
    index = columns.index("_source_row_id")
    return sorted((row[index] for row in cursor.fetchall()), key=str)


def test_the_metadata_audit_passes_on_a_conforming_batch(
    clean_run: duckdb.DuckDBPyConnection,
) -> None:
    """An audit passes when its query returns no rows — the control that makes
    the failing case below mean something."""
    assert _metadata_violations(clean_run) == []


def test_the_metadata_audit_stops_the_run_on_the_deliberate_violations(
    violating_run: duckdb.DuckDBPyConnection,
) -> None:
    """D21/D25's data properties, caught at run time because no compiler can
    check them: a NULL ``_source_row_id``, a duplicated one (both rows), a
    NULL ``_ingested_at``, an uncastable one, a NULL ``_load_id``. The audit
    is declared in the MODEL block with no ``blocking false``, so a non-empty
    result *is* the run stopping."""
    assert _metadata_violations(violating_run) == [
        None,
        "key_017",
        "key_018",
        "key_019",
        "key_dup",
        "key_dup",
    ]


def test_the_metadata_audit_is_declared_blocking_on_the_model(
    clean_run: duckdb.DuckDBPyConnection,
) -> None:
    """Blocking is the default in the target's grammar, so the assertion is
    that the audit is *referenced* and carries no relaxation — unlike the
    reconcile audit beside it, which declares ``blocking false`` on purpose."""
    del clean_run
    model = next(
        artifact
        for artifact in compile_fixture(FIXTURE)
        if artifact.path == "models/silver/dirty_key.sql"
    )
    assert "audits (dirty_key_ingestion_metadata, dirty_key_conservation)" in model.content
    assert "blocking false" not in AUDITS["dirty_key_ingestion_metadata"].content
    assert "blocking false" in AUDITS["key_amount_matches_row_reconcile"].content


def test_a_duplicated_source_row_id_also_breaks_the_conservation_accounting(
    violating_run: duckdb.DuckDBPyConnection,
) -> None:
    """A second, independent alarm on the same rows. ``reject_id`` and the
    conservation scoping are both built on ``_source_row_id`` being unique, so
    when it is not, the accounting stops adding up — which is why the metadata
    violation cannot be downgraded to a flag."""
    violations = violating_run.execute(
        audit_body(AUDITS["dirty_key_conservation"], "silver.dirty_key")
    ).fetchall()
    assert violations != []


def test_an_uncastable_recency_field_stops_the_run(
    violating_run: duckdb.DuckDBPyConnection,
) -> None:
    """D25/D31, the third condition of the audit. ``_ingested_at`` is
    ingestion metadata, not a mapped field, so D6's forcing of ``coercible``
    to ``fail`` never reaches it and no rule is generated — the audit is the
    only thing standing between an uncastable recency value and a dedupe
    order that is silently undefined."""
    assert "key_018" in _metadata_violations(violating_run)


def test_a_castable_recency_field_is_not_a_metadata_violation() -> None:
    """The non-trigger, on a pair that differs in exactly one value.

    Without it the assertion above would also pass for an audit that flagged
    every row — and the corpus rows all carry *some* other reason to be a
    violation or not, so the isolating case is built here: two rows with
    distinct, non-null identities and non-null loads, one ``_ingested_at``
    that parses and one that does not.
    """
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            "CREATE TABLE probe AS SELECT * FROM (VALUES"
            "  ('load_a', '2026-01-05T10:00:00Z', 'castable'),"
            "  ('load_a', 'not a timestamp', 'uncastable')"
            ") AS _rows(_load_id, _ingested_at, _source_row_id)"
        )
        assert _metadata_violations(connection, "probe") == ["uncastable"]
    finally:
        connection.close()


# ....................... #
# The replay comparison agrees with the dedupe order (RFC 0016 D20)


def test_the_replay_comparison_agrees_with_the_dedupe_order_on_nulls() -> None:
    """The replay MERGE and the pipeline's ``QUALIFY`` are the only two places
    the D20 total order is expressed, and they must decide every pair the same
    way — including pairs a nullable ``dedupe.field``/``tie_break`` produces.

    They did not. The MERGE compared row constructors, ``(a, b) > (c, d)``,
    which reads like the same question but orders NULL as the *largest* value
    — the inverse of the ``DESC NULLS LAST`` the pipeline ranks by. Both
    directions were wrong: a candidate that ranked first was not merged (and
    its reject row was then stamped ``(superseded)``, asserting another row
    won its key — false), and a candidate whose sort value was NULL evicted a
    non-null incumbent, restating the entity against the order D20 states.

    Asserted exhaustively rather than by specimen: for every pair over a
    domain that includes NULL, the emitted predicate must equal "the candidate
    sorts first and the two are not identical". A single hand-picked pair
    would have missed one of the two directions.
    """
    entity = plan_entity(dedupe=DedupeIR(keep="latest_by", field="a", tie_break=("b",)))
    predicate = (
        _candidate_wins(entity)
        .sql(dialect="duckdb")
        .replace("_replay.", "c_")
        .replace("_target.", "t_")
    )
    domain: tuple[int | None, ...] = (None, 1, 2)
    connection = duckdb.connect(":memory:")
    try:
        disagreements: list[str] = []
        for cand_a, cand_b, inc_a, inc_b in itertools.product(domain, repeat=4):
            row = (
                f"SELECT {_sql_literal(cand_a)} AS c_a, {_sql_literal(cand_b)} AS c_b, "
                f"{_sql_literal(inc_a)} AS t_a, {_sql_literal(inc_b)} AS t_b, "
                "'r1' AS c__source_row_id, 'r1' AS t__source_row_id"
            )
            merged = connection.execute(f"SELECT ({predicate}) FROM ({row})").fetchone()
            assert merged is not None
            ranked = connection.execute(
                f"SELECT who FROM (SELECT 'c' AS who, {_sql_literal(cand_a)} AS a, "
                f"{_sql_literal(cand_b)} AS b UNION ALL SELECT 't', {_sql_literal(inc_a)}, "
                f"{_sql_literal(inc_b)}) ORDER BY a DESC NULLS LAST, b DESC NULLS LAST LIMIT 1"
            ).fetchone()
            assert ranked is not None
            wins = ranked[0] == "c" and (cand_a, cand_b) != (inc_a, inc_b)
            if bool(merged[0]) is not wins:
                disagreements.append(f"({cand_a},{cand_b}) vs ({inc_a},{inc_b})")
        assert not disagreements, f"MERGE and dedupe order disagree on: {disagreements}"
    finally:
        connection.close()


def _sql_literal(value: int | None) -> str:
    return "NULL" if value is None else str(value)
