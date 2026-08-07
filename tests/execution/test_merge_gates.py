"""The merge gates (RFC 0016 §6): idempotence and backfill equivalence.

These two are the **executable** form of the determinism invariant (RFC 0003).
Byte-identical artifacts prove the compiler is deterministic; these prove the
artifacts *behave* deterministically once an engine runs them — which is where
a nondeterministic tie-break or an order-dependent rule actually shows up. A
dedupe whose winner is not unique passes every golden and fails here.

Both gates run over the dirty corpus rather than a clean fixture, deliberately:
the interesting rows are precisely the ones that tie, quarantine, or arrive in
the second wave.
"""

from __future__ import annotations

from collections.abc import Iterator

import duckdb
import pytest
from support.compiling import compile_fixture
from support.dirty import FIXTURE, LOAD_WAVES, build_corpus, seed_dirty_corpus
from support.execution import materialize, model_relations, snapshot, warehouse

pytestmark = pytest.mark.execution

ARTIFACTS = compile_fixture(FIXTURE)
RELATIONS = model_relations(ARTIFACTS)


@pytest.fixture(scope="module")
def full_run() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = build_corpus()
    yield connection
    connection.close()


def test_second_run_changes_nothing(full_run: duckdb.DuckDBPyConnection) -> None:
    """Idempotence: run every model again over unchanged bronze and assert the
    warehouse is untouched — every relation, every column, every row.

    Both materialization kinds are exercised by construction: the FULL entity
    models replace their tables and must land on the same rows, and the
    ``INCREMENTAL_BY_UNIQUE_KEY`` reject models upsert by ``reject_id`` and
    must not mint a second row for a re-delivered source row (D21).
    """
    before = snapshot(full_run, RELATIONS)
    materialize(full_run, ARTIFACTS)
    after = snapshot(full_run, RELATIONS)
    assert after == before


def test_a_second_independent_run_reproduces_the_same_warehouse() -> None:
    """The same specs and the same bronze, in a *different* connection, give
    the same numbers. Determinism across processes is what RFC 0003 promises,
    and a hash-seed-dependent iteration order reaching a projection list would
    fail here and nowhere else in the tier."""
    first = build_corpus()
    second = build_corpus()
    try:
        assert snapshot(second, RELATIONS) == snapshot(first, RELATIONS)
    finally:
        first.close()
        second.close()


def test_backfill_reproduces_incremental(full_run: duckdb.DuckDBPyConnection) -> None:
    """Full refresh ≡ incremental history (§6).

    The corpus arrives in two load waves. The incremental warehouse sees wave
    one, runs every model, then sees wave two and runs them again — reject
    tables accumulating by their unique key across both runs. The full-refresh
    warehouse sees both waves at once and runs the models once. The two
    warehouses must be indistinguishable.

    This is the gate that catches an order-dependent rule: ``unique`` is a
    window over the current slice and ``referential`` probes the current state
    of a sibling entity, so a rule that quietly depended on *arrival* order
    rather than on content would diverge here.
    """
    incremental = warehouse()
    try:
        for wave in range(1, LOAD_WAVES + 1):
            seed_dirty_corpus(incremental, waves=wave)
            materialize(incremental, ARTIFACTS)
        assert snapshot(incremental, RELATIONS) == snapshot(full_run, RELATIONS)
    finally:
        incremental.close()


def test_the_incremental_history_is_not_vacuous() -> None:
    """The gate above would pass trivially if wave one already contained
    everything. It does not — and this is what says so."""
    first_wave = build_corpus(waves=1)
    try:
        partial = first_wave.execute("SELECT COUNT(*) FROM bronze.dirty__numerics").fetchone()
        complete = build_corpus()
        try:
            whole = complete.execute("SELECT COUNT(*) FROM bronze.dirty__numerics").fetchone()
        finally:
            complete.close()
    finally:
        first_wave.close()
    assert partial is not None and whole is not None
    assert 0 < partial[0] < whole[0]
