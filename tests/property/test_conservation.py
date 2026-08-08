"""The conservation law (RFC 0016 §6) — "the single best invariant".

    Every bronze row lands in exactly one of: the entity, an **unresolved**
    reject (``resolved_at IS NULL``), or the deduped count.

If it holds, rows cannot vanish — which is the one failure mode a cleansing
system must not have, and the one a survivors-only test can never see. It is
asserted here over *generated* batches rather than over the curated corpus,
because the corpus is a fixed set of specimens and this is a statement about
every batch a source could deliver: arbitrary duplicate keys, arbitrary null
and empty-string parts, arbitrary uncastable values, arbitrary arrival order.

The accounting is the RFC's, exactly. Resolved reject rows are audit history
and are excluded: a replayed row lives in the entity from then on and counting
its retained reject row too would double-count it (§5.6).

§6 also says the law is "emitted as a **runtime audit** on every production
run, not only a test" — so every example additionally runs the emitted
``<entity>_conservation`` audit and requires it to pass. A property test that
were green while the audit shipped broken would be the worst of both.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager

import duckdb
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from support.compiling import compile_fixture
from support.dirty import FIXTURE, audits_of
from support.execution import audit_body, materialize, warehouse

from bloomery.emit import ArtifactKind, EmittedArtifact

pytestmark = pytest.mark.property

ENTITY = "dirty_key"
SOURCE = "bronze.dirty__keys"

ARTIFACTS = compile_fixture(FIXTURE)
AUDITS = audits_of(ARTIFACTS)

#: Only the entity under test and its reject table — the law is per entity, and
#: rebuilding twelve entities per Hypothesis example would buy nothing.
UNDER_TEST: tuple[EmittedArtifact, ...] = tuple(
    artifact
    for artifact in ARTIFACTS
    if artifact.kind is ArtifactKind.MODEL
    and artifact.path in {f"models/silver/{ENTITY}.sql", f"models/silver/{ENTITY}__reject.sql"}
)

#: ``dirty_key`` is the entity under test because it is the only one carrying
#: **all three** legs of the law at once: a ``dedupe:`` block (so rows can be
#: deduped), quarantining rules (so rows can be diverted), and survivors.

#: The values a generated key part may take. Every one is a specimen class the
#: corpus carries: a plain key, a repeated one (so dedupe has something to do),
#: the empty string, and NULL — the last two deliberately adjacent, because
#: they belong to different rules (D19) and a lowering that conflated them
#: would move a row between legs.
_KEY_PARTS = st.sampled_from(["ORD-1", "ORD-2", "ORD-3", "", None])
_LINES = st.sampled_from(["1", "2", None])

#: Castable and uncastable amounts, plus NULL — ``coercible`` fires on the
#: middle group only, and stays silent on the last (the marker is "NULL
#: although every source it read was not").
_AMOUNTS = st.sampled_from(["10.00", "-1.5", "0", "12,50", "NaN", "", None])

#: Two loads and two instants, so recency ties happen often enough that the
#: tie-break and the final ``_source_row_id`` key are actually exercised.
_LOADS = st.sampled_from(["load_a", "load_b"])
_INSTANTS = st.sampled_from(["2026-01-05T10:00:00Z", "2026-01-05T11:00:00Z"])

Row = tuple[str, str, str, str | None, str | None, str | None]


@st.composite
def _batches(draw: st.DrawFn) -> tuple[Row, ...]:
    """A bronze batch honouring the D21 metadata contract.

    ``_source_row_id`` is NOT NULL and unique *by construction* here, because
    that is the contract the law is stated under: with a duplicated identity
    the accounting genuinely cannot balance, and the generated blocking audit —
    not this property — is what catches it (asserted in the execution tier).
    """
    size = draw(st.integers(min_value=0, max_value=12))
    return tuple(
        (
            f"r{index:03d}",
            draw(_LOADS),
            draw(_INSTANTS),
            draw(_KEY_PARTS),
            draw(_LINES),
            draw(_AMOUNTS),
        )
        for index in range(size)
    )


@contextmanager
def _run(batch: Sequence[Row]) -> Iterator[duckdb.DuckDBPyConnection]:
    """One example, in a warehouse of its own.

    A fresh connection **per example**, not a pytest fixture: Hypothesis re-runs
    the test body many times against one fixture instance, and the reject model
    is ``INCREMENTAL_BY_UNIQUE_KEY`` — it would accumulate across examples and
    the law would be asserted over a batch nobody generated.
    """
    connection = warehouse()
    try:
        _seed(connection, batch)
        materialize(connection, UNDER_TEST)
        yield connection
    finally:
        connection.close()


#: The columns the mapping acknowledges but does not map. They exist on the
#: generated relation because ``raw`` carries the whole bronze payload (§5.6) —
#: a generated batch that omitted them would be a batch the reject model cannot
#: project, which is a fact about this seed, not about the law.
_UNMAPPED = ("_case", "_expected", "_note")


def _seed(conn: duckdb.DuckDBPyConnection, batch: Sequence[Row]) -> None:
    unmapped = ", ".join(f"{name} VARCHAR" for name in _UNMAPPED)
    conn.execute(
        f"CREATE OR REPLACE TABLE {SOURCE} "
        "(_source_row_id VARCHAR, _load_id VARCHAR, _ingested_at VARCHAR, "
        f"order_id VARCHAR, line_no VARCHAR, amount VARCHAR, {unmapped})"
    )
    if batch:
        rows = [[*row, *([None] * len(_UNMAPPED))] for row in batch]
        placeholders = ", ".join("?" * len(rows[0]))
        conn.executemany(f"INSERT INTO {SOURCE} VALUES ({placeholders})", rows)


def _legs(conn: duckdb.DuckDBPyConnection) -> tuple[set[str], set[str], int]:
    """``(entity identities, unresolved reject identities, bronze rowcount)``."""
    kept = {
        str(row_id)
        for (row_id,) in conn.execute(f"SELECT _source_row_id FROM silver.{ENTITY}").fetchall()
    }
    diverted = {
        str(row_id)
        for (row_id,) in conn.execute(
            f"SELECT _source_row_id FROM silver.{ENTITY}__reject WHERE resolved_at IS NULL"
        ).fetchall()
    }
    (bronze,) = conn.execute(f"SELECT COUNT(*) FROM {SOURCE}").fetchone() or (0,)
    return kept, diverted, int(bronze)


@settings(max_examples=60, deadline=None)
@given(batch=_batches())
def test_every_bronze_row_lands_in_exactly_one_leg(batch: tuple[Row, ...]) -> None:
    with _run(batch) as conn:
        kept, diverted, bronze = _legs(conn)

    # Disjoint: no row is both kept and quarantined. The two-way split's WHERE
    # clauses are literal complements (§5.4), and this is that claim executed.
    assert kept & diverted == set()
    # Total: nothing is invented, and the deduped leg is what is left over.
    deduped = bronze - (len(kept) + len(diverted))
    assert deduped >= 0
    # Every identity that survived dedupe is accounted for, and every accounted
    # identity was actually delivered.
    delivered = {row[0] for row in batch}
    assert (kept | diverted) <= delivered


@settings(max_examples=40, deadline=None)
@given(batch=_batches())
def test_the_deduped_leg_equals_what_dedupe_actually_removed(batch: tuple[Row, ...]) -> None:
    """The third leg, computed independently of the pipeline: dedupe keeps one
    row per entity key, so what it removed is the batch size minus the number
    of distinct keys. If that disagrees with ``bronze - (kept + diverted)``, a
    row went somewhere nobody is counting."""
    with _run(batch) as conn:
        kept, diverted, bronze = _legs(conn)
        distinct = conn.execute(
            # The key as the pipeline computes it — TRY_CAST, so an uncastable
            # line_no collapses to NULL exactly as it does in the model.
            "SELECT COUNT(*) FROM (SELECT DISTINCT TRY_CAST(order_id AS TEXT) AS k1,"
            f" TRY_CAST(line_no AS BIGINT) AS k2 FROM {SOURCE}) AS _keys"
        ).fetchone()
    assert distinct is not None
    assert len(kept) + len(diverted) == int(distinct[0])
    assert bronze - (len(kept) + len(diverted)) == bronze - int(distinct[0])


@settings(max_examples=40, deadline=None)
@given(batch=_batches())
def test_the_emitted_conservation_audit_passes_on_every_batch(batch: tuple[Row, ...]) -> None:
    """§6's "not only a test": the same law, evaluated by the artifact that
    ships. An audit passes when its query returns no rows."""
    with _run(batch) as conn:
        violations = conn.execute(
            audit_body(AUDITS[f"{ENTITY}_conservation"], f"silver.{ENTITY}")
        ).fetchall()
    assert violations == []
