"""The dirty-data corpus as a seedable warehouse (RFC 0016 §6).

``tests/fixtures/dirty/*.csv`` is **data**: 137 curated specimens, each with an
``_expected`` disposition under the corpus's documented default rule set.
``tests/fixtures/dirty_corpus/`` is the **spec** that judges them. This module
is the third piece — the bridge that gets the one into the other without losing
anything on the way.

**The three traps the corpus README names, handled once, here.**

1. ``all_varchar = true, allow_quoted_nulls = false`` are mandatory on every
   read. Without ``allow_quoted_nulls = false`` DuckDB collapses a quoted empty
   field into NULL and the empty-string-vs-NULL distinction the corpus is built
   around (D19: different rules own the two) silently disappears; without
   ``all_varchar`` the sniffer types ``keys.amount`` as ``DOUBLE``, and a float
   in a decimal pipeline is the corruption RFC 0003 bans outright.
2. A zero-length *line* is not a row — ``extremes.csv``'s ``zero_length_row``
   is a well-formed row whose every payload value is NULL, and it is read like
   any other.
3. Rows marked ``_expected = dialect_divergent`` carry a disposition that is a
   property of the *engine*, not of the data. :data:`DIALECT_DIVERGENT` names
   them so a suite can require "either outcome, recorded consistently" instead
   of hard-coding one.

Two seeded relations are **synthesized** rather than read, and both are the
corpus telling the suite to do so:

- ``dirty__customers`` realizes ``refs.csv``'s ``_parent_status`` column —
  present / absent / quarantined is a fact about the *referenced* side, which
  the corpus states and the suite must stand up.
- ``refs.csv`` has no payload column, yet ``quarantining_parent_row``'s note
  says plainly: "Seed this row with a failing field value." So an ``amount``
  column is synthesized, uncastable on exactly that row.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
from support.compiling import compile_fixture
from support.execution import materialize, warehouse

from bloomery.emit import ArtifactKind, EmittedArtifact

__all__ = [
    "CASE_COLUMN",
    "DIALECT_DIVERGENT",
    "DIRTY",
    "EXPECTED_COLUMN",
    "FAILING_METADATA",
    "FIXTURE",
    "FLAGGED",
    "KEPT",
    "QUARANTINED",
    "READ_FLAGS",
    "audits_of",
    "build_corpus",
    "cases",
    "corpus",
    "dispositions",
    "expected",
    "read_csv",
    "seed_dirty_corpus",
]

DIRTY = Path(__file__).resolve().parents[1] / "fixtures" / "dirty"

#: The two flags the corpus README calls mandatory. Spelled once so no suite
#: can quietly read the corpus without them.
READ_FLAGS = "header = true, all_varchar = true, allow_quoted_nulls = false"

CASE_COLUMN = "_case"
EXPECTED_COLUMN = "_expected"

#: The ``_expected`` value marking a row whose disposition belongs to the
#: dialect matrix. A suite asserts *consistency* for these, never an answer.
DIALECT_DIVERGENT = "dialect_divergent"

#: ``keys.csv``'s deliberate ingestion-metadata violations, which the D21
#: blocking audit must catch. Kept out of the ordinary seed on purpose: they
#: are specimens for a run that must **stop**, so a suite that mixed them in
#: would be asserting about a run that should never have produced numbers.
FAILING_METADATA = "fail"


def read_csv(name: str) -> str:
    """The mandated ``read_csv`` call for one corpus file."""
    return f"read_csv('{DIRTY / name}', {READ_FLAGS})"


def corpus(name: str) -> tuple[dict[str, str | None], ...]:
    """One corpus file as rows, read through DuckDB under the mandated flags.

    Through DuckDB and not Python's ``csv`` module: ``csv.DictReader`` yields
    ``''`` for an unquoted (NULL) field and cannot tell it from a quoted empty
    one, which would conflate exactly the pair the corpus exists to separate.
    """
    connection = duckdb.connect(":memory:")
    try:
        cursor = connection.execute(f"SELECT * FROM {read_csv(name)}")
        columns = [description[0] for description in cursor.description or ()]
        return tuple(dict(zip(columns, row, strict=True)) for row in cursor.fetchall())
    finally:
        connection.close()


def expected(name: str) -> dict[str, str]:
    """``{_case: _expected}`` for one corpus file — the assertion table."""
    return {
        str(row[CASE_COLUMN]): str(row[EXPECTED_COLUMN])
        for row in corpus(name)
        if row[CASE_COLUMN] is not None
    }


#: ``refs.csv``'s ``_parent_status: quarantined`` customer, and the row whose
#: own field must fail so its children become orphans *after* cleansing.
_QUARANTINED_CUSTOMER = "C-QUAR"
_QUARANTINING_ORDER = "quarantining_parent_row"

#: The synthesized payload for ``refs.csv`` — castable everywhere except the
#: one row whose note asks for a failing value.
_REFS_AMOUNT = (
    f"CASE WHEN {CASE_COLUMN} = '{_QUARANTINING_ORDER}' "
    "THEN 'not-a-number' ELSE '1.00' END AS amount"
)

#: Bronze relation → the SELECT that fills it. One entry per mapping in the
#: ``dirty_corpus`` fixture; the extremes file fans out by its own ``raw_kind``
#: column, because a single entity cannot declare ``raw_value`` decimal here
#: and timestamp there.
_SEEDS: tuple[tuple[str, str], ...] = (
    ("dirty__numerics", f"SELECT * FROM {read_csv('numerics.csv')}"),
    ("dirty__dates", f"SELECT * FROM {read_csv('dates.csv')}"),
    ("dirty__enums", f"SELECT * FROM {read_csv('enums.csv')}"),
    ("dirty__unicode", f"SELECT * FROM {read_csv('unicode.csv')}"),
    # One bronze relation, two mappings: `dirty_ref` judges it under the
    # corpus default, `dirty_ref_routed` under the routing dispositions (§6).
    ("dirty__refs", f"SELECT *, {_REFS_AMOUNT} FROM {read_csv('refs.csv')}"),
    ("dirty__ref_parents", f"SELECT *, {_REFS_AMOUNT} FROM {read_csv('refs.csv')}"),
    (
        "dirty__extremes_decimal",
        f"SELECT * FROM {read_csv('extremes.csv')} WHERE raw_kind = 'decimal'",
    ),
    (
        "dirty__extremes_integer",
        f"SELECT * FROM {read_csv('extremes.csv')} WHERE raw_kind = 'integer'",
    ),
    (
        "dirty__extremes_timestamp",
        f"SELECT * FROM {read_csv('extremes.csv')} WHERE raw_kind = 'timestamp'",
    ),
    (
        "dirty__extremes_text",
        # The two rows whose ``raw_kind`` is itself NULL — ``empty_string_vs_null``
        # and ``zero_length_row`` — belong here: they are the pair that only stays
        # distinguishable under ``allow_quoted_nulls = false``.
        f"SELECT * FROM {read_csv('extremes.csv')} WHERE raw_kind = 'string' OR raw_kind IS NULL",
    ),
)

#: The customer side of ``refs.csv``'s ``_parent_status``. ``C-100`` is present
#: and clean; ``C-QUAR`` is present in bronze and fails its own ``coercible``
#: rule, so it never reaches silver. Every other fk in the file is *absent* by
#: simply not being here.
_CUSTOMERS = (
    ("load_seed", "2026-01-05T09:00:00Z", "cus_001", "C-100", "1"),
    ("load_seed", "2026-01-05T09:00:00Z", "cus_002", _QUARANTINED_CUSTOMER, "not-an-int"),
)


def _keys_select(*, metadata_violations: bool) -> str:
    rows = f"SELECT * FROM {read_csv('keys.csv')}"
    if metadata_violations:
        return rows
    return f"{rows} WHERE {EXPECTED_COLUMN} <> '{FAILING_METADATA}'"


#: The number of distinct ``_load_id`` values every corpus file carries. The
#: corpus is delivered in two waves, which is what makes an *incremental*
#: history expressible against it at all (§6's backfill-equivalence gate).
LOAD_WAVES = 2


def _through_wave(select: str, waves: int | None) -> str:
    """``select`` restricted to its first ``waves`` load ids, or unrestricted.

    "First" is lexicographic over the file's own distinct ``_load_id`` values,
    which is a genuine order here (``…_a`` before ``…_b``) and, more to the
    point, is a *property of the data* rather than a constant this module
    invents — so a corpus file that grows a third wave is picked up without
    editing anything.
    """
    if waves is None:
        return select
    return (
        f"SELECT * FROM ({select}) AS _batch WHERE _load_id IN ("
        f"  SELECT _load_id FROM (SELECT DISTINCT _load_id FROM ({select}) AS _ids"
        f"  ORDER BY _load_id LIMIT {waves}) AS _wave)"
    )


def seed_dirty_corpus(
    conn: duckdb.DuckDBPyConnection,
    *,
    metadata_violations: bool = False,
    waves: int | None = None,
) -> None:
    """Fill every bronze relation the ``dirty_corpus`` fixture maps.

    ``metadata_violations`` includes ``keys.csv``'s six deliberate D21
    violations — a null ``_source_row_id``, a duplicated one, a null or
    uncastable ``_ingested_at``, a null ``_load_id``. They are excluded by
    default because their ``_expected`` is ``fail``: the generated blocking
    audit must **stop** that run, so the numbers it would otherwise produce are
    not numbers anyone should assert on.

    ``waves`` seeds only the first *n* load ids of every file — the arriving
    history a backfill has to reproduce in one shot.
    """
    for relation, select in _SEEDS:
        conn.execute(f"CREATE OR REPLACE TABLE bronze.{relation} AS {_through_wave(select, waves)}")
    keys = _keys_select(metadata_violations=metadata_violations)
    conn.execute(f"CREATE OR REPLACE TABLE bronze.dirty__keys AS {_through_wave(keys, waves)}")
    conn.execute("DROP TABLE IF EXISTS bronze.dirty__customers")
    conn.execute(
        "CREATE TABLE bronze.dirty__customers "
        "(_load_id VARCHAR, _ingested_at VARCHAR, _source_row_id VARCHAR, "
        "customer_id VARCHAR, tier VARCHAR)"
    )
    conn.executemany("INSERT INTO bronze.dirty__customers VALUES (?, ?, ?, ?, ?)", list(_CUSTOMERS))


# ....................... #
# The built warehouse and how a suite reads a disposition off it

#: The spec project that judges the corpus.
FIXTURE = "dirty_corpus"

#: The three observable outcomes of one bronze row that reached a table. The
#: fourth — "in neither the entity nor the reject" — has no name here on
#: purpose: it shows up as an identity *missing* from
#: :func:`dispositions`, and the caller compares against what it seeded. That
#: is the failure §6 says a survivors-only test cannot see, so it must be
#: visible as an absence rather than hidden behind a label.
KEPT = "pass"
FLAGGED = "flag"
QUARANTINED = "quarantine"


def build_corpus(
    *, metadata_violations: bool = False, waves: int | None = None
) -> duckdb.DuckDBPyConnection:
    """Seed bronze, compile the fixture, materialize every model — the whole
    dirty run in one call."""
    conn = warehouse()
    seed_dirty_corpus(conn, metadata_violations=metadata_violations, waves=waves)
    materialize(conn, compile_fixture(FIXTURE))
    return conn


def audits_of(artifacts: tuple[EmittedArtifact, ...]) -> dict[str, EmittedArtifact]:
    """The emitted audits by audit name (``audits/<name>.sql`` → ``<name>``)."""
    return {
        Path(artifact.path).stem: artifact
        for artifact in artifacts
        if artifact.kind is ArtifactKind.AUDIT
    }


def cases(name: str) -> dict[str, str]:
    """``{_source_row_id: _case}`` for one corpus file.

    ``_source_row_id`` rather than the payload key, because it is the one
    column present on *both* sides of the two-way split — the entity carries it
    through (D21) and the reject schema is built around it — so one lookup
    reads a row's disposition wherever it landed.
    """
    return {
        str(row["_source_row_id"]): str(row[CASE_COLUMN])
        for row in corpus(name)
        if row["_source_row_id"] is not None and row[CASE_COLUMN] is not None
    }


def dispositions(
    conn: duckdb.DuckDBPyConnection, entity: str
) -> dict[str, tuple[str, tuple[str, ...]]]:
    """``{_source_row_id: (disposition, fired rule names)}`` for one entity.

    **Both sides of the split**, which is the whole point (RFC 0016 §6): a test
    that only reads the entity "cannot tell correctly-quarantined from silently
    dropped". A row absent from both tables is simply absent from the result,
    and the caller compares against the seeded identities to find it.
    """
    result: dict[str, tuple[str, tuple[str, ...]]] = {}
    for row_id, flags in conn.execute(
        f"SELECT _source_row_id, _quality_flags FROM silver.{entity}"
    ).fetchall():
        rules = tuple(flags or ())
        result[str(row_id)] = (FLAGGED if rules else KEPT, rules)
    for row_id, rules in conn.execute(
        f"SELECT _source_row_id, failed_rules FROM silver.{entity}__reject "
        "WHERE resolved_at IS NULL"
    ).fetchall():
        result[str(row_id)] = (QUARANTINED, tuple(rules or ()))
    return result
