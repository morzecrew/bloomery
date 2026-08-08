"""Quarantine replay, end to end (RFC 0016 §5.6/§5.7/§6): the enum-widening
walkthrough the RFC calls "the normal path, not the exception".

The whole story, in the order an operator lives it:

1. A source emits a status the spec does not know (``authorized``). The row
   fails ``in_enum`` and lands in ``<entity>__reject`` with its raw payload.
2. Bronze's incremental window moves past it. A backfill can no longer reach
   it — the row is not in bronze any more, it is in the reject table. This is
   exactly why ``Plan`` needs a ``replay_scope`` beside its ``backfill_scope``
   (§5.7): the two name different *storage*.
3. Someone widens the enum. ``plan(old, new)`` classifies the change RESTATING
   **and** names the entity in ``replay_scope``.
4. The widened models run; the rows do not come back, because bronze no longer
   has them.
5. The emitted replay MERGE runs. The rows come back — re-derived from ``raw``
   through the *current* mapping — their reject rows keep ``resolved_at`` as
   audit history, and the entity grows by exactly the number that passed.
6. Replay runs again and re-derives identical semantic state (D22).

Step 2 is simulated by deleting the aged rows from bronze, which is the only
honest way to state "not in bronze's incremental window at all". Without it the
walkthrough would prove nothing: a plain backfill would bring the rows back and
replay would be decoration.
"""

from __future__ import annotations

from collections.abc import Iterator

import duckdb
import pytest
from support.compiling import FIXTURES, fixture_sources, load_fixture
from support.dirty import FIXTURE, build_corpus
from support.execution import materialize, replay_statements

from bloomery import Target, build_project_ir, compile_project, load_catalog, load_project, plan
from bloomery.emit import ArtifactKind, EmittedArtifact
from bloomery.ir import ProjectIR
from bloomery.spec import Project

pytestmark = pytest.mark.execution

#: The enum chain as the fixture declares it, and as the widening rewrites it.
#: Spelled as the literal spec text so the "diff" this test applies is the diff
#: a reviewer would see in a pull request — a widening is a spec edit, not an
#: API call.
NARROW = "{enum_map: [paid, paid, pending, pending, refunded, refunded]}"
WIDE = (
    "{enum_map: [paid, paid, pending, pending, refunded, refunded, "
    "authorized, authorized, partially_refunded, partially_refunded]}"
)

#: The two rows the widening admits, and the one it must **not**. A
#: misspelling is not a new member: widening the enum to admit ``payed`` would
#: be wrong, so the corpus keeps it beside the real candidates.
WIDENED = ("valid_but_unmapped", "valid_but_unmapped_2")
STILL_QUARANTINED = "misspelling"

ENTITY = "dirty_status"


def _project(*, widened: bool) -> tuple[Project, ProjectIR]:
    sources = dict(fixture_sources(FIXTURE))
    if widened:
        assert NARROW in sources["mapping_enums"]
        sources["mapping_enums"] = sources["mapping_enums"].replace(NARROW, WIDE)
    project = load_project(sources)
    catalog = load_catalog((FIXTURES / FIXTURE / "catalog.yaml").read_text())
    return project, build_project_ir(project, catalog)


def _artifacts(project: Project) -> tuple[EmittedArtifact, ...]:
    _spec, catalog = load_fixture(FIXTURE)
    return compile_project(project, target=Target.SQLMESH, dialect="duckdb", catalog=catalog)


def _replay(conn: duckdb.DuckDBPyConnection, artifacts: tuple[EmittedArtifact, ...]) -> None:
    """Run the emitted replay artifact for the entity — the caller's job, which
    bloomery emits and never performs (a hard invariant)."""
    artifact = next(
        a for a in artifacts if a.kind is ArtifactKind.REPLAY and a.path.endswith(f"{ENTITY}.sql")
    )
    for statement in replay_statements(artifact):
        conn.execute(statement)


def _state(conn: duckdb.DuckDBPyConnection) -> dict[str, object]:
    """The **semantic** state D22 defines idempotence over: which rows are in
    the entity, and which reject rows have resolved. Observability columns are
    excluded on purpose — ``last_seen`` updates whenever a row is re-evaluated,
    which is an event worth recording, not an idempotence violation, and
    ``resolved_at``'s *timestamp* is the engine's clock while its
    *transition* is the semantics."""
    return {
        "winners": sorted(
            conn.execute(f"SELECT case_name, status FROM silver.{ENTITY}").fetchall()
        ),
        "resolved": sorted(
            row
            for (row,) in conn.execute(
                f"SELECT _source_row_id FROM silver.{ENTITY}__reject WHERE resolved_at IS NOT NULL"
            ).fetchall()
        ),
        "unresolved": sorted(
            row
            for (row,) in conn.execute(
                f"SELECT _source_row_id FROM silver.{ENTITY}__reject WHERE resolved_at IS NULL"
            ).fetchall()
        ),
    }


@pytest.fixture
def widened_run() -> Iterator[tuple[duckdb.DuckDBPyConnection, tuple[EmittedArtifact, ...]]]:
    """The warehouse at step 4: quarantined under the narrow spec, bronze
    window moved on, widened models applied, replay not yet run."""
    conn = build_corpus()
    conn.execute(
        "DELETE FROM bronze.dirty__enums WHERE _case IN "
        f"({', '.join(repr(case) for case in WIDENED)})"
    )
    widened_project, _ir = _project(widened=True)
    artifacts = _artifacts(widened_project)
    materialize(conn, artifacts)
    yield conn, artifacts
    conn.close()


def test_the_widening_candidates_start_out_quarantined() -> None:
    """Step 1, as a standalone fact: under the narrow spec the two real
    upstream statuses are in the reject table, unresolved, with their payload
    kept — which is what makes them replayable at all."""
    conn = build_corpus()
    try:
        rows = dict(
            conn.execute(
                f"SELECT raw ->> '$._case', raw ->> '$.raw_status' FROM silver.{ENTITY}__reject "
                "WHERE resolved_at IS NULL"
            ).fetchall()
        )
    finally:
        conn.close()
    assert rows["valid_but_unmapped"] == "authorized"
    assert rows["valid_but_unmapped_2"] == "partially_refunded"


def test_plan_names_the_entity_in_replay_scope_not_only_in_backfill_scope() -> None:
    """§5.7's whole payoff: the backfill is *computed*, not remembered — and
    computing it says a backfill alone is not enough here."""
    _narrow_project, old = _project(widened=False)
    _wide_project, new = _project(widened=True)
    result = plan(old, new)
    assert result.has_changes
    assert ENTITY in result.backfill_scope.entities
    assert result.replay_scope.entities == (ENTITY,)
    assert result.backfill_scope.restates_history


def test_plan_sees_a_widening_that_only_adds_a_spelling() -> None:
    """The other shape of the *same* edit, and the one that used to be blind.

    ``enum_map`` maps a raw spelling onto a target, so a widening either adds a
    target (above) or points a new spelling at a target that already exists —
    ``PAYED → paid``. Both admit raw values the narrow spec quarantined, but
    only the first changes an ``enum_map`` *target*, so a rule identified by
    its targets alone reported ``replay_scope == ()`` for the second while
    rows sat in the reject table (D49)."""
    _narrow_project, old = _project(widened=False)
    sources = dict(fixture_sources(FIXTURE))
    sources["mapping_enums"] = sources["mapping_enums"].replace(
        NARROW, NARROW.replace("refunded, refunded]", "refunded, refunded, PAID, paid]")
    )
    spelled = load_project(sources)
    new = build_project_ir(spelled, load_catalog((FIXTURES / FIXTURE / "catalog.yaml").read_text()))
    result = plan(old, new)
    assert result.has_changes
    assert ENTITY in result.backfill_scope.entities
    assert result.replay_scope.entities == (ENTITY,)


def test_the_backfill_alone_cannot_bring_the_rows_back(
    widened_run: tuple[duckdb.DuckDBPyConnection, tuple[EmittedArtifact, ...]],
) -> None:
    """Step 4. The models are widened and re-run, and the rows are still gone —
    because they are not in bronze. This is the assertion that makes the replay
    below load-bearing rather than redundant."""
    conn, _artifacts = widened_run
    present = conn.execute(
        f"SELECT COUNT(*) FROM silver.{ENTITY} WHERE case_name IN "
        f"({', '.join(repr(case) for case in WIDENED)})"
    ).fetchone()
    assert present == (0,)
    unresolved = conn.execute(
        f"SELECT COUNT(*) FROM silver.{ENTITY}__reject WHERE resolved_at IS NULL "
        f"AND (raw ->> '$._case') IN ({', '.join(repr(case) for case in WIDENED)})"
    ).fetchone()
    assert unresolved == (len(WIDENED),)


def test_replay_drains_the_reject_table_into_the_entity(
    widened_run: tuple[duckdb.DuckDBPyConnection, tuple[EmittedArtifact, ...]],
) -> None:
    """Step 5. The entity grows by exactly the number of rows that now pass;
    their reject rows are **retained** with ``resolved_at`` set — replay never
    deletes, retention does (§5.6) — and they drop out of the unresolved
    accounting, so nothing is counted twice."""
    conn, artifacts = widened_run
    before = conn.execute(f"SELECT COUNT(*) FROM silver.{ENTITY}").fetchone()
    unresolved_before = conn.execute(
        f"SELECT COUNT(*) FROM silver.{ENTITY}__reject WHERE resolved_at IS NULL"
    ).fetchone()
    reject_rows_before = conn.execute(f"SELECT COUNT(*) FROM silver.{ENTITY}__reject").fetchone()

    _replay(conn, artifacts)

    after = conn.execute(f"SELECT COUNT(*) FROM silver.{ENTITY}").fetchone()
    unresolved_after = conn.execute(
        f"SELECT COUNT(*) FROM silver.{ENTITY}__reject WHERE resolved_at IS NULL"
    ).fetchone()
    reject_rows_after = conn.execute(f"SELECT COUNT(*) FROM silver.{ENTITY}__reject").fetchone()

    assert before is not None and after is not None
    assert after[0] == before[0] + len(WIDENED)
    assert unresolved_before is not None and unresolved_after is not None
    assert unresolved_after[0] == unresolved_before[0] - len(WIDENED)
    assert reject_rows_after == reject_rows_before  # retained as audit history

    merged = dict(conn.execute(f"SELECT case_name, status FROM silver.{ENTITY}").fetchall())
    assert merged["valid_but_unmapped"] == "authorized"
    assert merged["valid_but_unmapped_2"] == "partially_refunded"


def test_replay_re_runs_the_current_mapping_so_the_misspelling_stays_out(
    widened_run: tuple[duckdb.DuckDBPyConnection, tuple[EmittedArtifact, ...]],
) -> None:
    """Replay is not "release the reject table" — it re-runs the *current*
    mapping and routes by the very same predicate the pipeline uses. Widening
    the enum to admit a misspelling would be wrong, and replay does not."""
    conn, artifacts = widened_run
    _replay(conn, artifacts)
    still_out = conn.execute(
        f"SELECT resolved_at FROM silver.{ENTITY}__reject "
        f"WHERE (raw ->> '$._case') = '{STILL_QUARANTINED}'"
    ).fetchall()
    assert still_out == [(None,)]
    absent = conn.execute(
        f"SELECT COUNT(*) FROM silver.{ENTITY} WHERE case_name = '{STILL_QUARANTINED}'"
    ).fetchone()
    assert absent == (0,)


def test_a_second_replay_re_derives_identical_semantic_state(
    widened_run: tuple[duckdb.DuckDBPyConnection, tuple[EmittedArtifact, ...]],
) -> None:
    """D22's idempotence, over the semantic state §5.6 defines it on: winners
    merged and ``resolved_at`` transitions, observability timestamps excluded.
    It follows from the dedupe total order — re-running re-derives the same
    winners — and it is what makes replay safe to retry after a failure."""
    conn, artifacts = widened_run
    _replay(conn, artifacts)
    once = _state(conn)
    _replay(conn, artifacts)
    assert _state(conn) == once
    assert once["unresolved"]  # the run resolved something, and not everything
    assert len(once["resolved"]) == len(WIDENED)  # type: ignore[arg-type]


def test_the_conservation_accounting_survives_the_replay(
    widened_run: tuple[duckdb.DuckDBPyConnection, tuple[EmittedArtifact, ...]],
) -> None:
    """A replayed row lives in the entity and its reject row is retained as
    audit history — counting both would double-count, which is exactly why §6's
    accounting counts only ``resolved_at IS NULL`` rejects. The sum of the two
    unresolved-scoped sides is unchanged by the replay."""
    conn, artifacts = widened_run

    def sides() -> tuple[int, int]:
        row = conn.execute(
            f"SELECT (SELECT COUNT(*) FROM silver.{ENTITY}),"
            f"       (SELECT COUNT(*) FROM silver.{ENTITY}__reject WHERE resolved_at IS NULL)"
        ).fetchone()
        assert row is not None
        return (int(row[0]), int(row[1]))

    kept_before, unresolved_before = sides()
    _replay(conn, artifacts)
    kept_after, unresolved_after = sides()
    assert kept_after + unresolved_after == kept_before + unresolved_before
