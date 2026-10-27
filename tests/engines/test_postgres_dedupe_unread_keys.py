"""Engine tier: two rows whose keys fail to cast both reach quarantine on
PostgreSQL (#315).

DuckDB keeps `QUALIFY` and reads the key parts' `coercible` verdicts by alias;
PostgreSQL has no `QUALIFY`, so SQLGlot moves the window into a subquery and
inlines every alias it reads, the verdicts among them. This runs that rewrite
against the engine. The DuckDB half is `tests/execution/test_dedupe_uncastable_keys.py`.

Opt-in (Docker required); excluded from ``just test``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

import psycopg
import pytest
from testcontainers.community.postgres import PostgresContainer

from bloomery import Target, compile_project, load_catalog, load_project
from support.compiling import FIXTURES, extract_select, fixture_sources

pytestmark = pytest.mark.engine("postgres")

FIXTURE = "semi_additive_inventory"

ROWS = [
    ("w1", "2026-01-01", "5", "2026-01-01 00:00:00", "r1"),
    ("w2", "not-a-date", "5", "2026-01-01 00:00:00", "r2"),
    ("w2", "also-bad", "5", "2026-01-01 00:00:01", "r3"),
    ("w3", "2026-01-02", "5", "2026-01-01 00:00:00", "r4"),
    ("w3", "2026-01-02", "6", "2026-01-01 00:00:01", "r5"),
]


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
        )
        conn.execute("SET TIME ZONE 'UTC'")
        for schema in ("bronze", "silver"):
            conn.execute(f"CREATE SCHEMA {schema}")
        conn.execute(
            "CREATE TABLE bronze.wms__stock_levels (warehouse text, day text, on_hand text, "
            "_load_id text, _ingested_at text, _source_row_id text, operator_note text)"
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO bronze.wms__stock_levels VALUES (%s, %s, %s, 'L1', %s, %s, NULL)",
                ROWS,
            )
        catalog = load_catalog((FIXTURES / FIXTURE / "catalog.yaml").read_text(encoding="utf-8"))
        artifacts = {
            artifact.path: artifact.content
            for artifact in compile_project(
                load_project(fixture_sources(FIXTURE)),
                target=Target.SQLMESH,
                dialect="postgres",
                catalog=catalog,
            )
        }
        for path in ("models/silver/inventory_level.sql", "models/silver/inventory_level__reject.sql"):
            name = path.rsplit("/", 1)[-1].removesuffix(".sql")
            body = re.sub(r"@[a-z_]+", "'2026-01-01'", extract_select(artifacts[path]))
            conn.execute(f'CREATE TABLE silver."{name}" AS {body}')
        yield conn
        conn.close()


def test_every_uncastable_key_reaches_quarantine(postgres: psycopg.Connection) -> None:
    rejected = dict(
        postgres.execute(
            'SELECT _source_row_id, failed_rules FROM silver."inventory_level__reject"'
        ).fetchall()
    )
    assert sorted(rejected) == ["r2", "r3"]
    assert all("stock_date_coercible" in rules for rules in rejected.values())


def test_a_genuine_duplicate_still_keeps_one_row(postgres: psycopg.Connection) -> None:
    kept = postgres.execute(
        'SELECT _source_row_id, stock_level FROM silver."inventory_level" ORDER BY 1'
    ).fetchall()
    assert kept == [("r1", 5), ("r5", 6)]
