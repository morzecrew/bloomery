"""Disposition precedence, window-rule legality, mart arithmetic and replay
identity, executed (RFC 0016 D18/D20/D22, §5.6, §5.8).

The suite next door (``test_dirty_corpus``) asks "does each specimen land where
the corpus says". This one asks the questions a corpus cannot: what happens
when two rules of *different* dispositions fire on one row, whether a rule
whose predicate is a window function is legal in every position the lowering
puts it, whether the mart's counts survive being summed, and whether replay
still holds a grain when two reject rows resolve to one key.

Every assertion here runs SQL. A lowering bug in this area is not a shape
difference a golden would catch — it is either invalid SQL or a number that is
wrong by a factor, and only an engine can tell you which.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal

import duckdb
import pytest
from support.compiling import compile_fixture
from support.execution import audit_body, materialize, replay_statements
from support.planning import make_planner, quantized
from support.precedence import (
    BELOW_BOUND,
    DEDUPED,
    DIVERTED,
    DUPLICATE_WINNER,
    DUPLICATED_KEY,
    EVALUATED,
    FIXTURE,
    KEPT,
    NULL_SOURCE_ROW,
    QUARANTINED,
    build,
    compile_widened,
    project_ir,
    seed,
)

from bloomery import MetricRequest, Op, OrderSpec, Predicate
from bloomery.emit import ArtifactKind, EmittedArtifact
from bloomery.quality import SUPERSEDED_RULE

pytestmark = pytest.mark.execution

PLANNER = make_planner()


@pytest.fixture(scope="module")
def run() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = build()
    yield connection
    connection.close()


def _audits(artifacts: tuple[EmittedArtifact, ...]) -> dict[str, EmittedArtifact]:
    return {
        artifact.path.removeprefix("audits/").removesuffix(".sql"): artifact
        for artifact in artifacts
        if artifact.kind is ArtifactKind.AUDIT
    }


def _violations(
    conn: duckdb.DuckDBPyConnection, name: str, relation: str, *, column: str = "_source_row_id"
) -> tuple[str, ...]:
    """The identities one blocking audit reports, sorted.

    An audit passes when its query returns no rows, so this is "what stops the
    run" — read straight off the emitted artifact rather than restated.
    """
    artifact = _audits(compile_fixture(FIXTURE))[name]
    body = audit_body(artifact, relation)
    rows = conn.execute(f"SELECT {column} FROM ({body})").fetchall()
    return tuple(sorted(str(row[0]) for row in rows))


# ....................... #
# D18 — severity order `fail > quarantine > flag`


def test_a_fail_rule_stops_the_run_even_when_a_quarantine_rule_diverted_the_row(
    run: duckdb.DuckDBPyConnection,
) -> None:
    """D18's first clause: *any* failing ``fail`` rule stops the run. Routing
    happens first in the pipeline, so an audit that reads the entity sees only
    the rows the split kept — and a row that failed the blocking rule *and* a
    quarantine rule would sit in the reject table with the run carrying on. The
    audit has to see the pre-route population."""
    assert _violations(run, "q_line_amount_range_min", "silver.q_line") == BELOW_BOUND


def test_failed_rules_records_the_fail_rules_name_beside_the_quarantine_ones(
    run: duckdb.DuckDBPyConnection,
) -> None:
    """D18: **all** failed rule names are recorded, "its flag-level failures
    included". A reject row is the full account of why a row is not in the
    entity; omitting the blocking rule that also fired makes the account a
    partial one."""
    recorded = dict(
        run.execute("SELECT _source_row_id, failed_rules FROM silver.q_line__reject").fetchall()
    )
    assert sorted(recorded["r07"]) == ["amount_range_min", "code_unique", "status_in_set"]
    assert sorted(recorded["r05"]) == ["code_unique"]


def test_a_kept_row_records_the_fail_rule_it_fired(run: duckdb.DuckDBPyConnection) -> None:
    """The other half of the same account: ``r09`` fires the blocking rule and
    is diverted by nothing, so the record of its failure can only be
    ``_quality_flags``. Without it the row reads as clean everywhere the
    package looks (§5.5's ``has_quality_flags`` included)."""
    flags = dict(run.execute("SELECT _source_row_id, _quality_flags FROM silver.q_line").fetchall())
    assert sorted(flags["r09"]) == ["amount_range_min"]
    assert sorted(flags["r10"]) == []


# ....................... #
# `unique` — a window predicate in every position the lowering puts it


@pytest.mark.parametrize("disposition", ["flag", "quarantine", "fail"])
def test_unique_executes_at_every_disposition(
    run: duckdb.DuckDBPyConnection, disposition: str
) -> None:
    """A window function is legal in a projection and illegal in a ``WHERE``
    clause on every engine, and the lowering puts the same predicate in both.
    ``flag`` alone happens to survive that (a ``CASE`` projection tolerates a
    window), which is exactly why a disposition-parameterized execution test is
    the only one that catches it."""
    if disposition == "flag":
        flagged = {
            row_id
            for row_id, flags in run.execute(
                "SELECT _source_row_id, _quality_flags FROM silver.q_code"
            ).fetchall()
            if "code_flag_unique" in (flags or ())
        }
        assert flagged == {"c01", "c02"}
    elif disposition == "quarantine":
        diverted = {
            row_id
            for (row_id,) in run.execute(
                "SELECT _source_row_id FROM silver.q_code__reject"
            ).fetchall()
        }
        assert diverted == {"c03", "c04"}
    else:
        assert _violations(run, "q_code_code_fail_unique", "silver.q_code") == ("c05", "c06")


# ....................... #
# §5.2/D19 — `coercible` means the same thing at every disposition


def test_the_coercible_fail_audit_does_not_degrade_into_not_null(
    run: duckdb.DuckDBPyConnection,
) -> None:
    """``coercible`` is "the projection is NULL *although every source it reads
    was not*". A genuinely null source is a legitimate null, not a coercion
    failure — and no decision row licenses a rule whose meaning depends on its
    disposition."""
    assert _violations(run, "q_dup_note_coercible", "silver.q_dup") == ()
    present = run.execute(
        "SELECT COUNT(*) FROM silver.q_dup WHERE _source_row_id = ? AND note IS NULL",
        [NULL_SOURCE_ROW],
    ).fetchone()
    assert present == (1,)


# ....................... #
# §5.8/D12 — the mart's arithmetic


def _mart(conn: duckdb.DuckDBPyConnection, entity: str) -> dict[str, tuple[int, ...]]:
    return {
        rule: (evaluated, failed, quarantined, deduped)
        for rule, evaluated, failed, quarantined, deduped in conn.execute(
            "SELECT rule, rows_evaluated, rows_failed, rows_quarantined, rows_deduped "
            "FROM gold.mart_data_quality WHERE entity = ?",
            [entity],
        ).fetchall()
    }


def test_the_entity_level_counts_sum_to_the_entity_population(
    run: duckdb.DuckDBPyConnection,
) -> None:
    """§5.8 promises the mart is an *ordinary* semantic model, and an ordinary
    additive measure is one that survives ``SUM``. An entity-level quantity
    repeated on every rule row does not: summing it multiplies by the rule
    count, which is a number with no meaning at all."""
    totals = run.execute(
        "SELECT SUM(rows_evaluated), SUM(rows_deduped), SUM(rows_quarantined) "
        "FROM gold.mart_data_quality WHERE entity = 'q_line'"
    ).fetchone()
    assert totals == (EVALUATED, DEDUPED, QUARANTINED)


def test_rows_failed_reflects_a_fail_dispositions_rule(run: duckdb.DuckDBPyConnection) -> None:
    """A rule whose ``rows_failed`` is structurally zero reports nothing: the
    mart is where a rising failure rate is supposed to become visible, and the
    blocking rules are the ones whose firing matters most."""
    assert _mart(run, "q_line")["amount_range_min"][1] == len(BELOW_BOUND)
    assert _mart(run, "q_line")["code_unique"][1] == len(DIVERTED)


def test_the_quarantine_rate_is_the_true_rate_through_the_planner(
    run: duckdb.DuckDBPyConnection,
) -> None:
    """D12's claim, answered by the ordinary planner over the ordinary mart:
    the share of *rows* diverted, not the share of rule-evaluations that fired.
    Three of eight rows were diverted here; four rule-level diversions happened
    across them, and a rate built out of the latter is not a rate."""
    request = MetricRequest(
        metrics=("quality_quarantine_rate",),
        dimensions=("entity",),
        order_by=(OrderSpec(field="entity"),),
    )
    _project, ir = project_ir()
    plan = PLANNER.plan(ir, request, dialect="duckdb")
    rates = dict(run.execute(plan.sql).fetchall())
    assert quantized(rates["q_line"]) == quantized(Decimal(QUARANTINED) / Decimal(EVALUATED))


def test_the_two_sides_of_the_split_account_for_every_evaluated_row(
    run: duckdb.DuckDBPyConnection,
) -> None:
    """The denominator, pinned against the tables themselves."""
    sides = run.execute(
        "SELECT (SELECT COUNT(*) FROM silver.q_line),"
        "       (SELECT COUNT(*) FROM silver.q_line__reject WHERE resolved_at IS NULL)"
    ).fetchone()
    assert sides == (KEPT, QUARANTINED)


def test_rows_deduped_never_goes_negative_across_runs() -> None:
    """``rows_deduped`` is a count. The entity is rebuilt in full each run while
    the reject table accumulates, so a residual computed against the two
    surviving surfaces drifts below zero the moment bronze's window moves past
    a row that is still in the reject table — and a negative count is not a
    count."""
    conn = build()
    try:
        first = conn.execute(
            "SELECT DISTINCT rows_deduped FROM gold.mart_data_quality "
            "WHERE entity = 'q_line' AND rows_deduped <> 0"
        ).fetchall()
        assert first == [(DEDUPED,)]
        # The incremental window moves past the diverted rows: they are no
        # longer in bronze, but they are still unresolved rejects.
        conn.execute(
            "DELETE FROM bronze.q__lines WHERE _source_row_id IN "
            f"({', '.join(repr(row) for row in DIVERTED)})"
        )
        materialize(conn, compile_fixture(FIXTURE))
        second = conn.execute(
            "SELECT MIN(rows_deduped) FROM gold.mart_data_quality WHERE entity = 'q_line'"
        ).fetchone()
        assert second is not None
        assert second[0] >= 0
        assert conn.execute(
            "SELECT DISTINCT rows_deduped FROM gold.mart_data_quality "
            "WHERE entity = 'q_line' AND rows_deduped <> 0"
        ).fetchall() == [(DEDUPED,)]
    finally:
        conn.close()


# ....................... #
# §5.5 — `has_quality_flags` on a mart, and its polarity


#: The mart is over ``q_line``, so it holds exactly the rows the split kept —
#: and ``r09`` is the only one of them a rule fired on (the ``fail`` bound;
#: everything else that fired was diverted first). Spelled here because it is
#: the *whole* reason the fixture carries a mart at all.
FLAGGED_IN_MART = "C09"
CLEAN_TOTAL = Decimal("58.000000000")
FLAGGED_TOTAL = Decimal("-7.000000000")


def test_has_quality_flags_is_true_for_a_flagged_row_and_false_for_a_clean_one(
    run: duckdb.DuckDBPyConnection,
) -> None:
    """§5.5's mart dimension, asserted **in both directions**.

    A dimension nothing ever asserts TRUE for is indistinguishable from the
    constant ``FALSE`` — and the constant is the shape an inverted or dropped
    ``NOT`` produces, which no execution, conservation or replay assertion can
    see, because none of them reads the mart. Only a golden would, and §12
    budgets for golden regeneration by the wave: a reviewer reading churn they
    were told to expect is not a detector.

    The two truth values come from the same population the rest of this module
    asserts: ``r09`` fires the blocking bound and is diverted by nothing, so it
    reaches the mart carrying a flag; the rows the split diverted never reach a
    mart at all (D15), which is why the flagged one has to be a *kept* row.
    """
    rows = dict(run.execute("SELECT code, has_quality_flags FROM gold.mart_lines").fetchall())
    assert rows[FLAGGED_IN_MART] is True
    assert sorted(code for code, flagged in rows.items() if flagged is False) == [
        "C02",
        "C04",
        "C08",
        "C10",
    ]
    # The column is a real dimension, not a constant: both values occur.
    assert set(rows.values()) == {True, False}


def test_excluding_flagged_rows_is_a_plain_metric_request(
    run: duckdb.DuckDBPyConnection,
) -> None:
    """§5.5's stated payoff, executed: "revenue excluding flagged rows becomes
    a plain ``MetricRequest``".

    Asserted as a filter *and* as a group-by, because the two fail differently:
    an inverted polarity swaps the two totals under the group-by while leaving
    their sum right, and returns the wrong one under the filter. Pinning the
    values rather than their sum is what makes either visible.
    """
    _project, ir = project_ir()
    clean = PLANNER.plan(
        ir,
        MetricRequest(
            metrics=("line_amount_total",),
            filters=(Predicate("has_quality_flags", Op.EQ, (False,)),),
        ),
        dialect="duckdb",
    )
    assert run.execute(clean.sql).fetchall() == [(CLEAN_TOTAL,)]

    split = PLANNER.plan(
        ir,
        MetricRequest(
            metrics=("line_amount_total",),
            dimensions=("has_quality_flags",),
            order_by=(OrderSpec(field="has_quality_flags"),),
        ),
        dialect="duckdb",
    )
    assert run.execute(split.sql).fetchall() == [(False, CLEAN_TOTAL), (True, FLAGGED_TOTAL)]


# ....................... #
# §5.6 — the reject row's own history


def test_first_seen_is_preserved_across_a_redelivery_and_last_seen_advances() -> None:
    """§5.6: a re-delivery of the same source row lands on the **same** reject
    row and updates ``last_seen``/``_load_id``/``failed_rules``. ``first_seen``
    is the column that says when the problem started; a re-delivery that moves
    it forward destroys the one fact it exists to carry."""
    conn = build()
    try:
        before = conn.execute(
            "SELECT first_seen, last_seen FROM silver.q_line__reject WHERE _source_row_id = 'r05'"
        ).fetchone()
        conn.execute(
            "UPDATE bronze.q__lines SET _ingested_at = '2024-02-01T00:00:00Z', "
            "_load_id = 'load_b' WHERE _source_row_id = 'r05'"
        )
        materialize(conn, compile_fixture(FIXTURE))
        after = conn.execute(
            "SELECT first_seen, last_seen, _load_id FROM silver.q_line__reject "
            "WHERE _source_row_id = 'r05'"
        ).fetchone()
        assert before is not None and after is not None
        assert after[0] == before[0], "first_seen moved on a re-delivery"
        assert after[1] > before[1], "last_seen did not advance on a re-delivery"
        assert after[2] == "load_b"
        rows = conn.execute(
            "SELECT COUNT(*) FROM silver.q_line__reject WHERE _source_row_id = 'r05'"
        ).fetchone()
        assert rows == (1,)  # the same row, not a second one
    finally:
        conn.close()


def test_a_redelivery_does_not_erase_the_replay_clock() -> None:
    """D88's merge half. The reject *model* projects ``last_evaluated_at`` NULL
    — a model query may not read a clock — and that model is the merge's
    source, so the default overwrite would wipe the column on every
    re-delivery: a row would forget it had ever been replayed because the
    source delivered it again.

    The stamp is written here rather than by running a replay, which isolates
    the merge from everything else: this asserts what ``when_matched`` does
    with an existing value, and that value's provenance is
    ``test_quarantine_replay``'s business.
    """
    conn = build()
    try:
        conn.execute(
            "UPDATE silver.q_line__reject SET last_evaluated_at = TIMESTAMP '2024-03-01 00:00:00' "
            "WHERE _source_row_id = 'r05'"
        )
        conn.execute(
            "UPDATE bronze.q__lines SET _ingested_at = '2024-02-01T00:00:00Z', "
            "_load_id = 'load_b' WHERE _source_row_id = 'r05'"
        )
        materialize(conn, compile_fixture(FIXTURE))
        after = conn.execute(
            "SELECT last_evaluated_at, last_seen FROM silver.q_line__reject "
            "WHERE _source_row_id = 'r05'"
        ).fetchone()
        assert after is not None
        assert after[0] == datetime(2024, 3, 1, tzinfo=None), "the replay clock was erased"
        assert after[1] is not None  # …while the delivery clock did advance
    finally:
        conn.close()


def test_first_seen_and_last_seen_are_not_the_same_expression() -> None:
    """A window over a partition that is a singleton by construction makes
    ``MIN`` and ``MAX`` the identity, so the two columns come out structurally
    equal — indistinguishable in a fresh run, and only telling the truth about
    one of them after a re-delivery. Guarded here so the pair cannot silently
    collapse back."""
    conn = build()
    try:
        conn.execute(
            "UPDATE bronze.q__lines SET _ingested_at = '2024-02-01T00:00:00Z' "
            "WHERE _source_row_id = 'r05'"
        )
        materialize(conn, compile_fixture(FIXTURE))
        differ = conn.execute(
            "SELECT COUNT(*) FROM silver.q_line__reject WHERE first_seen <> last_seen"
        ).fetchone()
        assert differ == (1,)
    finally:
        conn.close()


# ....................... #
# D22 — replay picks one winner per key


def _replay(conn: duckdb.DuckDBPyConnection, artifacts: tuple[EmittedArtifact, ...]) -> None:
    artifact = next(
        a for a in artifacts if a.kind is ArtifactKind.REPLAY and a.path.endswith("q_dup.sql")
    )
    for statement in replay_statements(artifact):
        conn.execute(statement)


@pytest.fixture
def widened() -> Iterator[tuple[duckdb.DuckDBPyConnection, tuple[EmittedArtifact, ...]]]:
    """The warehouse after ``q_dup``'s membership set is widened: both reject
    rows on the duplicated key now pass, and replay has two candidates for one
    entity key."""
    conn = build()
    artifacts = compile_widened()
    conn.execute(f"DELETE FROM bronze.q__dups WHERE group_id = '{DUPLICATED_KEY}'")
    materialize(conn, artifacts)
    yield conn, artifacts
    conn.close()


def test_two_rejects_resolving_to_one_key_merge_as_one_row(
    widened: tuple[duckdb.DuckDBPyConnection, tuple[EmittedArtifact, ...]],
) -> None:
    """D22: "multiple rejects resolving to one key are ordered the same way" —
    by the dedupe total order, whose no-``dedupe:`` form is the stable
    source-row identity alone (D20). A merge source with no such ordering
    inserts both, and the entity quietly stops holding its declared grain."""
    conn, artifacts = widened
    _replay(conn, artifacts)
    rows = conn.execute(
        "SELECT note FROM silver.q_dup WHERE group_id = ?", [DUPLICATED_KEY]
    ).fetchall()
    assert rows == [(DUPLICATE_WINNER,)]


def test_replay_re_stamps_failed_rules_and_leaves_last_seen_on_the_data_clock() -> None:
    """§5.6: replay merges the passers "and updat[es] ``failed_rules`` … on the
    rest". A reject row re-evaluated against the current mapping and still
    failing has its account re-derived, so the reject table never ages into a
    statement about a spec nobody runs any more.

    ``last_seen`` does **not** move (RFC 0016 D70). It is one clock — the
    latest *delivery's* ``_ingested_at`` — because retention measures unresolved
    rows from it (§5.6): a column that a replay run advances makes an unresolved
    reject row immortal for as long as replay keeps running, which is §9's PII
    lake with the mitigation removed.
    """
    conn = build()
    try:
        artifacts = compile_fixture(FIXTURE)
        before = conn.execute(
            "SELECT last_seen, failed_rules FROM silver.q_dup__reject WHERE _source_row_id = 'd01'"
        ).fetchone()
        _replay(conn, artifacts)
        after = conn.execute(
            "SELECT last_seen, failed_rules, resolved_at, _ingested_at "
            "FROM silver.q_dup__reject WHERE _source_row_id = 'd01'"
        ).fetchone()
        assert before is not None and after is not None
        assert after[2] is None, "a row that still fails must not resolve"
        assert after[1] == before[1]
        assert after[0] == before[0], "replay moved last_seen off the delivery clock"
        assert after[0] == after[3], "last_seen is the latest delivery's _ingested_at"
    finally:
        conn.close()


def test_the_conservation_audit_still_passes_over_this_shape(
    run: duckdb.DuckDBPyConnection,
) -> None:
    """Every change above moves rows between the two legs of the split; §6's
    law is what says none of them fell out of both."""
    for entity in ("q_line", "q_code", "q_dup"):
        artifact = _audits(compile_fixture(FIXTURE))[f"{entity}_conservation"]
        rows = run.execute(audit_body(artifact, f"silver.{entity}")).fetchall()
        assert rows == [], entity


def test_the_seeded_population_is_what_the_fixture_documents(
    run: duckdb.DuckDBPyConnection,
) -> None:
    """The counts every assertion above is written against, asserted once so a
    seed edit fails here rather than moving an expectation somewhere else."""
    del run
    conn = build()
    try:
        seeded = conn.execute("SELECT COUNT(*) FROM bronze.q__lines").fetchone()
        assert seeded == (EVALUATED + DEDUPED,)
        diverted = tuple(
            sorted(
                row
                for (row,) in conn.execute(
                    "SELECT _source_row_id FROM silver.q_line__reject"
                ).fetchall()
            )
        )
        assert diverted == DIVERTED
    finally:
        conn.close()


def test_seeding_twice_is_idempotent() -> None:
    """``seed`` drops and recreates, so a suite may call it mid-run."""
    conn = build()
    try:
        seed(conn)
        rows = conn.execute("SELECT COUNT(*) FROM bronze.q__lines").fetchone()
        assert rows == (EVALUATED + DEDUPED,)
    finally:
        conn.close()


def test_a_replay_loser_says_why_it_is_still_out(
    widened: tuple[duckdb.DuckDBPyConnection, tuple[EmittedArtifact, ...]],
) -> None:
    """A candidate that **passes** every rule and loses the key contest stays
    unresolved, and its record has to explain that (RFC 0016 D69).

    ``_one_winner_per_key`` (D22) keeps one candidate per entity key, and the
    MERGE's ``WHEN MATCHED`` keeps the better of candidate and incumbent — so a
    passing row can be left behind by either. The third statement then
    re-derives ``failed_rules`` for every still-unresolved row, and for this one
    the honest re-derivation is *empty*: it fails nothing. ``resolved_at IS
    NULL, failed_rules = []`` reads as "quarantined for these reasons: none",
    on a row that will lose the contest for as long as it exists and can only
    leave by retention.
    """
    conn, artifacts = widened
    _replay(conn, artifacts)
    loser = conn.execute(
        "SELECT resolved_at, failed_rules FROM silver.q_dup__reject WHERE _source_row_id = 'd01'"
    ).fetchone()
    assert loser is not None
    assert loser[0] is None  # d02 won the key; d01 is not in the entity
    assert list(loser[1]) == [SUPERSEDED_RULE]
