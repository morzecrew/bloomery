"""Engine tier (RFC 0009 §5.2 tier 5): the data-quality pipeline on real
PostgreSQL — the tier D30 refused the dialect for, now that D84 gives
``TRY_CAST`` a Postgres spelling.

The assertion that matters is not that the SQL renders. It is that the *right
rows* end up quarantined: rendering was never the hard part, and D30's whole
point was that a plain ``CAST`` renders beautifully and aborts the run.

Opt-in (Docker required); excluded from ``just test``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

import psycopg
import pytest
from testcontainers.community.postgres import PostgresContainer

from support.compiling import compile_fixture, extract_select

pytestmark = pytest.mark.engine("postgres")

FIXTURE = "semi_additive_inventory"

#: One clean row and one specimen per failure mode the pipeline must catch.
ROWS = [
    ("w1", "2026-01-01", "5", "s1", "L1", "2026-01-01T00:00:00", "r1"),
    ("w2", "not-a-date", "7", "s2", "L1", "2026-01-01T00:00:00", "r2"),
    ("w3", "2026-01-02", "abc", "s3", "L1", "2026-01-01T00:00:00", "r3"),
    # The determinism specimen: postgres accepts `now` as datetime input and
    # resolves it to the transaction timestamp, so this cell would coerce to a
    # different value on every run (D84).
    ("w4", "now", "9", "s4", "L1", "2026-01-01T00:00:00", "r4"),
    # The same specimen wearing whitespace (D93). `BTRIM` defaults to spaces
    # alone, so this one survived the trim with its tab intact, missed the
    # deny-list, and coerced — the guard was comparing a string the engine
    # would never see. A tab rather than a space is the whole point.
    ("w6", "now\t", "9", "s6", "L1", "2026-01-01T00:00:00", "r6"),
    ("w7", "now\n", "9", "s7", "L1", "2026-01-01T00:00:00", "r7"),
    ("w5", "2026-01-03", "-5", "s5", "L1", "2026-01-01T00:00:00", "r5"),
]


@pytest.fixture(scope="module")
def quality_db() -> Iterator[psycopg.Connection]:
    with PostgresContainer("postgres:16-alpine", driver=None) as container:
        conn = psycopg.connect(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(container.port)),
            user=container.username,
            password=container.password,
            dbname=container.dbname,
        )
        conn.execute("SET TIME ZONE 'UTC'")
        for schema in ("bronze", "silver", "gold"):
            conn.execute(f"CREATE SCHEMA {schema}")
        conn.execute(
            "CREATE TABLE bronze.wms__stock_levels (warehouse text, day text, "
            "on_hand text, sku text, _load_id text, _ingested_at text, _source_row_id text)"
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO bronze.wms__stock_levels VALUES (%s,%s,%s,%s,%s,%s,%s)", ROWS
            )
        conn.commit()
        artifacts = [
            a
            for a in compile_fixture(FIXTURE, dialect="postgres")
            if a.path.startswith("models/silver/") and a.path.endswith(".sql")
        ]
        # The entity before its reject table: the reject model reads the same
        # staged extract, but ordering keeps a failure legible.
        for artifact in sorted(artifacts, key=lambda a: a.path.endswith("__reject.sql")):
            name = artifact.path.rsplit("/", 1)[-1].removesuffix(".sql")
            # Run-context macros have no meaning outside SQLMesh; the pipeline
            # under test is the coercion and routing, not the run window.
            body = re.sub(r"@[a-z_]+", "'2026-01-01'", extract_select(artifact.content))
            conn.execute(f'CREATE TABLE silver."{name}" AS {body}')
        conn.commit()
        yield conn
        conn.close()


def test_the_clean_row_is_the_only_one_kept(quality_db: psycopg.Connection) -> None:
    kept = quality_db.execute(
        'SELECT _source_row_id FROM silver."inventory_level" ORDER BY 1'
    ).fetchall()
    assert [row[0] for row in kept] == ["r1"]


def test_the_clean_rows_quality_ok_is_true_and_not_null(
    quality_db: psycopg.Connection,
) -> None:
    """`_quality_ok` is a two-valued claim about a row, and on Postgres it was
    three-valued.

    `array_length(ARRAY[]::text[], 1)` is **NULL** in Postgres — not 0 — so the
    generated `ARRAY_LENGTH(_quality_flags, 1) = 0` came back NULL for every row
    that failed nothing. A clean row is the common row; the column that says so
    was unknown for all of them, `NOT _quality_ok` was unknown with it, and a
    mart's `has_quality_flags` inherited that.

    The tier kept the clean row and never asked what the row *said* about
    itself, which is why rendering-and-routing tests did not see this. Asserted
    with `IS TRUE` against the value rather than through a `WHERE`, because a
    NULL is filtered out by a predicate and would look like an absent row
    rather than a wrong one.
    """
    row = quality_db.execute(
        'SELECT _quality_ok, _quality_flags FROM silver."inventory_level" '
        "WHERE _source_row_id = 'r1'"
    ).fetchone()
    assert row is not None
    quality_ok, flags = row
    assert flags == [], "the clean row carries flags — the assertion below would prove nothing"
    assert quality_ok is True, f"_quality_ok is {quality_ok!r} for a row that failed nothing"


def test_an_uncastable_value_is_quarantined_rather_than_aborting_the_run(
    quality_db: psycopg.Connection,
) -> None:
    """D30's actual failure: a plain ``CAST`` would raise here and take the
    whole run with it, which is why the dialect was refused."""
    rows = dict(
        quality_db.execute(
            'SELECT _source_row_id, failed_rules FROM silver."inventory_level__reject"'
        ).fetchall()
    )
    assert "stock_date_coercible" in rows["r2"]
    assert "stock_level_coercible" in rows["r3"]


def test_a_run_dependent_datetime_is_quarantined_not_silently_unstable(
    quality_db: psycopg.Connection,
) -> None:
    """The narrowing D84 adds. Without it postgres coerces `now` to the
    transaction timestamp and the row lands in silver carrying a value no
    backfill can reproduce — green, and unrestatable."""
    rows = dict(
        quality_db.execute(
            'SELECT _source_row_id, failed_rules FROM silver."inventory_level__reject"'
        ).fetchall()
    )
    assert "stock_date_coercible" in rows["r4"]


def test_a_run_dependent_datetime_wearing_whitespace_is_quarantined_too(
    quality_db: psycopg.Connection,
) -> None:
    """D93. The narrowing above was defeated by a tab: PostgreSQL's datetime
    scanner skips tabs, newlines and carriage returns around a special value,
    while bare ``BTRIM`` removes only spaces — so ``'now\t'`` passed
    ``pg_input_is_valid``, passed the deny-list, and cast to the transaction
    timestamp. Verified on this engine: without the fix these two rows land in
    silver carrying an unrestatable value."""
    rows = dict(
        quality_db.execute(
            'SELECT _source_row_id, failed_rules FROM silver."inventory_level__reject"'
        ).fetchall()
    )
    assert "stock_date_coercible" in rows["r6"]
    assert "stock_date_coercible" in rows["r7"]


def test_declared_rules_still_route_alongside_the_coercion_marker(
    quality_db: psycopg.Connection,
) -> None:
    """The coercion marker is one rule among many; enabling it must not
    displace the rules an author actually wrote."""
    rows = dict(
        quality_db.execute(
            'SELECT _source_row_id, failed_rules FROM silver."inventory_level__reject"'
        ).fetchall()
    )
    assert "stock_level_range_min" in rows["r5"]
    assert "stock_level_not_negative" in rows["r5"]


def test_every_bronze_row_is_accounted_for(quality_db: psycopg.Connection) -> None:
    """RFC 0016's conservation law, on the engine D30 kept it off: kept +
    quarantined equals delivered, with nothing dropped in between."""
    kept = quality_db.execute('SELECT COUNT(*) FROM silver."inventory_level"').fetchone()[0]
    rejected = quality_db.execute(
        'SELECT COUNT(*) FROM silver."inventory_level__reject"'
    ).fetchone()[0]
    assert kept + rejected == len(ROWS)
