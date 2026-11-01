"""A naming policy that names a catalog, run as emitted on DuckDB (#389,
S-0025/D-23).

Bronze stays in one attached database and silver and gold go to another, and
neither is the session's default catalog: every relation the models read or
write has to carry its catalog as a real third part, or it resolves in the
default catalog, where nothing was built. A catalog folded into the namespace
would have rendered as one quoted identifier, ``"lake.silver".order``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import duckdb
import pytest
from support.compiling import fixture_sources, load_fixture
from support.execution import DEFAULT_SCHEMAS, materialize, replay_statements, warehouse
from support.planning import normalize_month

from bloomery import MetricRequest, Target, build_project_ir, compile_project, load_project
from bloomery.emit import EmittedArtifact
from bloomery.ir import Layer
from bloomery.naming import DefaultNaming
from bloomery.planner.metricflow_planner import MetricFlowPlanner
from bloomery.runtime.hydration import LruManifestHydrator

pytestmark = pytest.mark.execution


@dataclass(frozen=True, slots=True)
class AttachedNaming:
    """Bronze in an attached Postgres, silver and gold in a lake: #389's shape."""

    def relation(self, entity: str, layer: Layer) -> tuple[str, str, str]:
        namespace, relation = DefaultNaming().relation(entity, layer)
        return ("pg" if layer is Layer.BRONZE else "lake", namespace, relation)


@pytest.fixture
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = warehouse()
    for catalog in ("pg", "lake"):
        connection.execute(f"ATTACH ':memory:' AS {catalog}")
        for schema in DEFAULT_SCHEMAS:
            connection.execute(f"CREATE SCHEMA {catalog}.{schema}")
    try:
        yield connection
    finally:
        connection.close()


def _in_bronze(conn: duckdb.DuckDBPyConnection, *statements: str) -> None:
    """Land bronze in `pg`, then hand the session back to its default catalog,
    so a reference that lost its catalog finds an empty schema there."""
    conn.execute("USE pg")
    for statement in statements:
        conn.execute(statement)
    conn.execute("USE memory")


def _rows(conn: duckdb.DuckDBPyConnection, sql: str) -> list[tuple[object, ...]]:
    return [tuple(row) for row in conn.execute(sql).fetchall()]


def _no_folded_catalog(artifacts: tuple[EmittedArtifact, ...]) -> None:
    for artifact in artifacts:
        assert re.search(r'"(?:lake|pg)\.\w+"\.', artifact.content) is None, artifact.path


def test_marts_build_across_two_attached_catalogs(conn: duckdb.DuckDBPyConnection) -> None:
    _in_bronze(
        conn,
        "CREATE TABLE bronze.oms__orders ("
        "id VARCHAR, amount DECIMAL(12, 4), order_date VARCHAR, ship_date VARCHAR)",
        "INSERT INTO bronze.oms__orders VALUES "
        "('o1', 100.00, '2024-01-15', '2024-01-20'), ('o2', 50.00, '2024-01-31', '2024-02-02'), "
        "('o3', 25.00, '2024-02-10', '2024-02-12')",
    )
    project, catalog = load_fixture("role_playing_dates")
    artifacts = compile_project(
        project, target=Target.SQLMESH, dialect="duckdb", catalog=catalog, naming=AttachedNaming()
    )
    _no_folded_catalog(artifacts)
    materialize(conn, artifacts)

    assert _rows(
        conn, "SELECT shipped_month, SUM(amount) FROM lake.gold.mart_orders GROUP BY 1 ORDER BY 1"
    ) == [(date(2024, 1, 1), Decimal("100.00")), (date(2024, 2, 1), Decimal("75.00"))]
    # A plan names the relation the models wrote.
    planner = MetricFlowPlanner(LruManifestHydrator(AttachedNaming()), naming=AttachedNaming())
    plan = planner.plan(
        build_project_ir(project, catalog),
        MetricRequest(metrics=("revenue",), dimensions=("shipped_month",)),
        dialect="duckdb",
    )
    assert sorted((normalize_month(month), revenue) for month, revenue in _rows(conn, plan.sql)) == [
        (date(2024, 1, 1), Decimal("100.00")),
        (date(2024, 2, 1), Decimal("75.00")),
    ]
    # Nothing landed in the session's own catalog.
    assert _rows(
        conn, "SELECT count(*) FROM information_schema.tables WHERE table_catalog = 'memory'"
    ) == [(0,)]


def test_a_quarantined_row_replays_within_the_lake(conn: duckdb.DuckDBPyConnection) -> None:
    """Quarantine, the reject table and replay name the lake's relations and
    read bronze's, the statements the caller runs included."""
    _in_bronze(
        conn,
        """
        CREATE TABLE bronze.shopify__order_lines (
          "order" JSON, position VARCHAR, variant JSON, quantity VARCHAR,
          properties JSON, created_at VARCHAR, financial_status VARCHAR,
          _load_id VARCHAR, _ingested_at VARCHAR, _source_row_id VARCHAR
        )
        """,
        """
        CREATE TABLE bronze.woo__order_lines (
          order_number VARCHAR, item_index VARCHAR, product_sku VARCHAR, qty VARCHAR,
          created VARCHAR, state VARCHAR,
          _load_id VARCHAR, _ingested_at VARCHAR, _source_row_id VARCHAR
        )
        """,
        "INSERT INTO bronze.shopify__order_lines VALUES (json_object('id', 'B-1'), '1', "
        "json_object('sku', 'SKU-1'), '2', json_object('gift_note', NULL), "
        "'2024-03-01T00:00:00', 'paid', 'load-1', '2024-03-10T00:00:00', 's1')",
        "INSERT INTO bronze.woo__order_lines VALUES ('B-3', '1', 'SKU-7', '1', "
        "'2024-03-03T00:00:00', 'reversed', 'load-1', '2024-03-10T00:00:00', 'w3')",
    )
    sources = fixture_sources("multi_source_quality")

    def compiled() -> tuple[EmittedArtifact, ...]:
        return compile_project(
            load_project(sources), target=Target.SQLMESH, dialect="duckdb", naming=AttachedNaming()
        )

    materialize(conn, compiled())
    assert _rows(conn, "SELECT order_id FROM lake.silver.order_line") == [("B-1",)]
    assert _rows(conn, "SELECT _source_row_id FROM lake.silver.order_line__reject") == [("w3",)]

    anchor = "{enum_map: [PROCESSING, open, COMPLETE, closed]}"
    assert sources["mapping_legacy"].count(anchor) == 1
    sources["mapping_legacy"] = sources["mapping_legacy"].replace(
        anchor, "{enum_map: [PROCESSING, open, COMPLETE, closed, reversed, closed]}"
    )
    artifacts = compiled()
    _no_folded_catalog(artifacts)
    materialize(conn, artifacts)
    (replay,) = (a for a in artifacts if a.path.endswith("replay/order_line.sql"))
    for statement in replay_statements(replay):
        conn.execute(statement)

    assert _rows(conn, "SELECT order_id FROM lake.silver.order_line ORDER BY 1") == [
        ("B-1",),
        ("B-3",),
    ]
    assert _rows(conn, "SELECT resolved_at IS NOT NULL FROM lake.silver.order_line__reject") == [
        (True,)
    ]
