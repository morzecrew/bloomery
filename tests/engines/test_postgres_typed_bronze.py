"""Engine tier: the quality pipeline on PostgreSQL over bronze columns a loader
landed *typed* — the bronze the port's own suite never builds, since every other
Postgres engine test lands its columns as ``TEXT`` or its JSON as ``JSONB``.

Three reported failures share the shape: the emitted SQL leaned on a column
type nothing states (#305, #306, #307).

- A single-key JSON read rendered ``payload ->> 'k'``, which Postgres defines
  for ``json`` and ``jsonb`` only; over ``TEXT`` it is ``42883``. Deeper paths
  were already cast to ``json`` first.
- ``pg_input_is_valid`` takes text only, and the S-0033/D-84 guard handed it
  its operand raw — a numeric chain (``to_decimal`` then ``multiply``) or a
  typed ``_ingested_at``, and the run aborted with ``42883``.

A ``coalesce`` fallback's cast was guarded as well, so ``pg_input_is_valid``
ran over a constant, which S-0033/D-84 records as unsafe (#322).

What stays refused, on purpose: a zone-aware ``_ingested_at``. Its text spells
an offset, and S-0052's offset refusal nulls it, so the D-21 metadata audit
flags the row — as it already does on DuckDB. A loader lands ``timestamp`` or
text.

Opt-in (Docker required); excluded from ``just test``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from decimal import Decimal

import psycopg
import pytest
from testcontainers.community.postgres import PostgresContainer

from bloomery import Target, compile_project, load_catalog, load_project
from support.compiling import FIXTURES, extract_select, fixture_sources

pytestmark = pytest.mark.engine("postgres")

FIXTURE = "semi_additive_inventory"

#: One clean row, one uncastable level and one uncastable amount. The money
#: chain ends in arithmetic, so the guard's operand is numeric; the channel is a
#: single-key JSON read.
ROWS = [
    ("w1", "2026-01-01", "5", "s1", "12345", '{"channel": "web"}', "L1", "2026-01-01 00:00:00", "r1"),
    ("w2", "2026-01-02", "abc", "s2", "678", '{"channel": "shop"}', "L1", "2026-01-01 00:00:00", "r2"),
    # A bad value at the chain's *inner* cast, which stayed a plain `CAST`
    # and aborted the run until every cast in the chain was shaped.
    ("w3", "2026-01-03", "9", "s3", "abc", '{"channel": "web"}', "L1", "2026-01-01 00:00:00", "r3"),
]


def _replaced(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, f"the fixture no longer reads {old!r}"
    return text.replace(old, new)


def _artifacts() -> dict[str, str]:
    """The shared fixture plus two mapped fields, compiled for postgres."""
    sources = fixture_sources(FIXTURE)
    sources["entity_model"] = _replaced(
        sources["entity_model"],
        "      stock_level: {type: int, canonical: stock_level}\n",
        "      stock_level: {type: int, canonical: stock_level}\n"
        '      total: {type: "decimal(18,2)"}\n'
        "      channel: {type: string}\n"
        "      units: {type: int}\n",
    )
    sources["mapping"] = _replaced(
        sources["mapping"],
        "fields:\n",
        "fields:\n"
        "  total:\n"
        '    from: "$.sum"\n'
        '    transform: [{to_decimal: [16, 0]}, {multiply: "0.01"}]\n'
        '  channel: {from: "$.payload.channel"}\n'
        '  units: {from: "$.payload.units", transform: [to_int, {coalesce: 0}]}\n',
    )
    catalog = load_catalog((FIXTURES / FIXTURE / "catalog.yaml").read_text(encoding="utf-8"))
    artifacts = compile_project(
        load_project(sources), target=Target.SQLMESH, dialect="postgres", catalog=catalog
    )
    return {a.path: a.content for a in artifacts}


@pytest.fixture(scope="module")
def postgres() -> Iterator[psycopg.Connection]:
    with PostgresContainer("postgres:16-alpine", driver=None) as container:
        conn = psycopg.connect(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(container.port)),
            user=container.username,
            password=container.password,
            dbname=container.dbname,
            autocommit=True,
            # Every case recreates the same tables with other column types, and
            # a statement psycopg prepared against the last one would refuse.
            prepare_threshold=None,
        )
        conn.execute("SET TIME ZONE 'UTC'")
        yield conn
        conn.close()


def _run(conn: psycopg.Connection, *, payload: str, ingested_at: str) -> int:
    """Land bronze with the given column types, build silver, and return how
    many rows the blocking ingestion-metadata audit reports."""
    for schema in ("bronze", "silver"):
        conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        conn.execute(f"CREATE SCHEMA {schema}")
    conn.execute(
        "CREATE TABLE bronze.wms__stock_levels (warehouse text, day text, on_hand text, "
        f"sku text, sum text, payload {payload}, _load_id text, _ingested_at {ingested_at}, "
        "_source_row_id text, operator_note text)"
    )
    # psycopg binds a str as `text`, which a typed column will not take
    # implicitly; the casts are the loader's, not the pipeline's.
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO bronze.wms__stock_levels VALUES "
            f"(%s,%s,%s,%s,%s,%s::{payload},%s,%s::{ingested_at},%s,NULL)",
            ROWS,
        )
    artifacts = _artifacts()
    models = sorted(
        (path for path in artifacts if path.startswith("models/silver/") and path.endswith(".sql")),
        key=lambda path: path.endswith("__reject.sql"),
    )
    for path in models:
        name = path.rsplit("/", 1)[-1].removesuffix(".sql")
        body = re.sub(r"@[a-z_]+", "'2026-01-01'", extract_select(artifacts[path]))
        conn.execute(f'CREATE TABLE silver."{name}" AS {body}')
    audit = extract_select(artifacts["audits/inventory_level_ingestion_metadata.sql"])
    return len(conn.execute(audit.replace("@this_model", 'silver."inventory_level"')).fetchall())


@pytest.mark.parametrize("payload", ["text", "json", "jsonb"])
@pytest.mark.parametrize("ingested_at", ["text", "timestamp"])
def test_typed_bronze_builds_and_still_quarantines(
    postgres: psycopg.Connection, payload: str, ingested_at: str
) -> None:
    assert _run(postgres, payload=payload, ingested_at=ingested_at) == 0
    # `units` is absent from every payload, so the kept row reads the
    # fallback, whose cast stays plain rather than guarding a constant (#322).
    kept = postgres.execute(
        'SELECT _source_row_id, total, channel, units FROM silver."inventory_level" ORDER BY 1'
    ).fetchall()
    assert kept == [("r1", Decimal("123.45"), "web", 0)]
    rejected = dict(
        postgres.execute(
            'SELECT _source_row_id, failed_rules FROM silver."inventory_level__reject"'
        ).fetchall()
    )
    assert "stock_level_coercible" in rejected["r2"]
    assert "total_coercible" in rejected["r3"]


def test_a_zone_aware_ingested_at_is_flagged_by_the_audit_not_a_crash(
    postgres: psycopg.Connection,
) -> None:
    """The documented refusal: `timestamptz` text carries `+00`, which S-0052
    nulls, so every row fails the castability check — the same verdict DuckDB
    gives. It is an audit finding, not an aborted run."""
    flagged = _run(postgres, payload="jsonb", ingested_at="timestamptz")
    (kept,) = postgres.execute('SELECT count(*) FROM silver."inventory_level"').fetchone() or (0,)
    assert kept > 0
    assert flagged == kept
