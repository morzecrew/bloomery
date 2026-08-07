"""E2E tier (RFC 0009 §5.2 tier 6, M11): the SQLMesh replan no-op test.

Compiled artifacts are written into a real SQLMesh project (pinned sqlmesh,
DuckDB gateway — no containers), loaded through ``sqlmesh.Context`` (which
raises on malformed ``MODEL`` blocks), and applied with
``plan(auto_apply=True)``. Then the same specs are compiled *again*, the
files rewritten byte-identically, and a fresh ``Context`` plans against the
persisted state: the second plan must report **no changes**. That is
determinism (RFC 0003) verified through a third party — bloomery and
SQLMesh's own fingerprinting agree that nothing moved.

Builtin audits declared in the ``MODEL`` blocks (e.g. ecom_basic's
``not_null``) run during apply, so a passing apply also exercises the audit
lowering. Custom audit artifacts (``audits/*.sql``) are written by the same
scaffold — the RFC 0016 fixture emits three (the ingestion-metadata contract,
one ``on_fail: fail`` rule, and the reconcile check's **non-blocking** one), so
a passing apply also proves the ``blocking false`` grammar and the
``@execution_ds`` run-context macro against the pinned sqlmesh.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from sqlmesh import Context

from support.compiling import compile_fixture

pytestmark = pytest.mark.e2e

CONFIG_TEMPLATE = """\
gateways:
  local:
    connection:
      type: duckdb
      database: {database}
default_gateway: local
model_defaults:
  dialect: duckdb
  start: 2024-01-01
disable_anonymized_analytics: true
"""


def _seed_minimal(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("CREATE TABLE bronze.raw__events (id VARCHAR, kind VARCHAR, ts VARCHAR)")
    conn.executemany(
        "INSERT INTO bronze.raw__events VALUES (?, ?, ?)",
        [
            ("e1", "click", "2024-01-02T03:04:05"),
            ("e2", "view", "2024-02-03T04:05:06"),
        ],
    )


def _seed_ecom_basic(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        "CREATE TABLE bronze.shopify__order_lines ("
        'order_id VARCHAR, "index" BIGINT, total DECIMAL(12, 4), qty BIGINT, created_at VARCHAR)'
    )
    conn.execute(
        "INSERT INTO bronze.shopify__order_lines VALUES (?, ?, ?, ?, ?)",
        ("o1", 1, Decimal("30.00"), 3, "2024-01-02T03:04:05"),
    )
    conn.execute("CREATE TABLE bronze.shopify__orders (id VARCHAR, customer JSON)")
    conn.execute(
        "INSERT INTO bronze.shopify__orders VALUES (?, ?)",
        ("o1", '{"id": "c1"}'),
    )


def _seed_semi_additive_inventory(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        "CREATE TABLE bronze.wms__stock_levels (warehouse VARCHAR, day VARCHAR, on_hand BIGINT, "
        "operator_note VARCHAR, _ingested_at TIMESTAMP, _load_id VARCHAR, _source_row_id VARCHAR)"
    )
    conn.executemany(
        "INSERT INTO bronze.wms__stock_levels VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("A", "2024-01-01", 100, "operator note", "2024-01-01 00:00:00", "L1", "r1"),
            # Negative: fires both the flag rule and the quarantining range
            # rule, so it routes to the reject table carrying *both* names
            # (RFC 0016 D18).
            ("A", "2024-01-02", -5, "operator note", "2024-01-02 00:00:00", "L1", "r2"),
            ("B", "2024-01-01", 40, "operator note", "2024-01-01 00:00:00", "L1", "r3"),
        ],
    )


def _verify_semi_additive_inventory(conn: duckdb.DuckDBPyConnection) -> None:
    """The RFC 0016 surfaces, applied by SQLMesh itself: the two-way split, the
    reject row's ``failed_rules``, the reconcile model, and the quality mart —
    including its ``run_date``, which only has a value because **SQLMesh**
    expanded ``@execution_ds`` (bloomery never read a clock, §5.8)."""
    kept = conn.execute(
        "SELECT warehouse_id, stock_level, _quality_ok FROM silver.inventory_level "
        "ORDER BY warehouse_id, stock_date"
    ).fetchall()
    assert kept == [("A", 100, True), ("B", 40, True)]

    rejected = conn.execute(
        "SELECT _source_row_id, failed_rules, resolved_at FROM silver.inventory_level__reject"
    ).fetchall()
    assert rejected == [("r2", ["stock_level_not_negative", "stock_level_range_min"], None)]

    # The mart gained has_quality_flags as an ordinary dimension (§5.5), and
    # quarantined rows never reached it — mart rowcounts legitimately differ
    # from bronze (D15).
    mart = conn.execute(
        "SELECT warehouse_id, has_quality_flags FROM gold.mart_inventory ORDER BY warehouse_id"
    ).fetchall()
    assert mart == [("A", False), ("B", False)]

    reconciled = conn.execute(
        "SELECT warehouse_id, difference, within_tolerance "
        "FROM silver.stock_level_matches_snapshot__reconcile ORDER BY warehouse_id"
    ).fetchall()
    assert reconciled == [("A", 0, True), ("B", 0, True)]

    quality = dict(
        conn.execute(
            "SELECT rule, rows_quarantined FROM gold.mart_data_quality ORDER BY rule"
        ).fetchall()
    )
    # One row per rule evaluation plus one per reconcile check (§5.8).
    assert quality["stock_level_range_min"] == 1
    assert quality["stock_level_not_negative"] == 0  # a flag rule diverts nothing
    assert "stock_level_matches_snapshot" in quality
    (run,) = conn.execute(
        "SELECT DISTINCT run_id IS NULL, run_date IS NOT NULL FROM gold.mart_data_quality"
    ).fetchall()
    assert run == (True, True)


def _verify_minimal(conn: duckdb.DuckDBPyConnection) -> None:
    rows = conn.execute(
        "SELECT event_id, kind, occurred_at FROM silver.event ORDER BY event_id"
    ).fetchall()
    assert rows == [
        ("e1", "click", datetime(2024, 1, 2, 3, 4, 5)),
        ("e2", "view", datetime(2024, 2, 3, 4, 5, 6)),
    ]


def _verify_ecom_basic(conn: duckdb.DuckDBPyConnection) -> None:
    row = conn.execute("SELECT unit_price FROM silver.order_item").fetchone()
    assert row is not None
    unit_price = row[0]
    assert isinstance(unit_price, Decimal)
    assert unit_price == Decimal("10.00")
    mart = conn.execute(
        "SELECT order_id, line_no, quantity, order_customer_id FROM gold.mart_order_items"
    ).fetchone()
    assert mart == ("o1", 1, 3, "c1")


Seeder = Callable[[duckdb.DuckDBPyConnection], None]
Verifier = Callable[[duckdb.DuckDBPyConnection], None]

FIXTURES: dict[str, tuple[Seeder, Verifier, frozenset[str]]] = {
    "minimal": (_seed_minimal, _verify_minimal, frozenset({"silver.event"})),
    "ecom_basic": (
        _seed_ecom_basic,
        _verify_ecom_basic,
        frozenset(
            {"silver.order", "silver.order_item", "gold.dim_date", "gold.mart_order_items"}
        ),
    ),
    # The RFC 0016 fixture: split silver model, reject table, reconcile model
    # plus its non-blocking audit, and the quality mart — applied by SQLMesh
    # itself, which is the only way to know the emitted macros, the
    # ``blocking false`` audit grammar and the model dependency order are real.
    "semi_additive_inventory": (
        _seed_semi_additive_inventory,
        _verify_semi_additive_inventory,
        frozenset(
            {
                "silver.inventory_level",
                "silver.inventory_level__reject",
                "silver.stock_level_matches_snapshot__reconcile",
                "gold.dim_date",
                "gold.mart_inventory",
                "gold.mart_data_quality",
            }
        ),
    ),
}


def _write_project(root: Path, fixture: str, warehouse: Path) -> None:
    """Materialize a compiled fixture as an on-disk SQLMesh project."""
    (root / "config.yaml").write_text(CONFIG_TEMPLATE.format(database=warehouse))
    for artifact in compile_fixture(fixture):
        dest = root / artifact.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(artifact.content)


@pytest.mark.parametrize("fixture", sorted(FIXTURES))
def test_replan_is_a_no_op(fixture: str, tmp_path: Path) -> None:
    seed, verify, expected_models = FIXTURES[fixture]

    warehouse = tmp_path / "warehouse.db"
    seeding = duckdb.connect(str(warehouse))
    seeding.execute("SET TimeZone = 'UTC'")
    seeding.execute("CREATE SCHEMA bronze")
    seed(seeding)
    seeding.close()

    first = compile_fixture(fixture)
    _write_project(tmp_path, fixture, warehouse)

    # Context raises on malformed MODEL blocks — loading alone is a check.
    context = Context(paths=str(tmp_path))
    try:
        assert {model.name for model in context.models.values()} == expected_models
        plan = context.plan(no_prompts=True, auto_apply=True)
        assert plan.has_changes  # everything is new on the first apply
    finally:
        context.close()

    # Compile again from the same specs: byte-identical artifacts (RFC 0003),
    # rewritten in place so SQLMesh re-reads them from disk.
    second = compile_fixture(fixture)
    assert second == first
    _write_project(tmp_path, fixture, warehouse)

    replan_context = Context(paths=str(tmp_path))
    try:
        replan = replan_context.plan(no_prompts=True, auto_apply=True)
        assert replan.has_changes is False
        assert list(replan.new_snapshots) == []
        assert replan.modified_snapshots == {}
    finally:
        replan_context.close()

    # The first apply materialized through SQLMesh's own runner (audits
    # included); the replan changed nothing — the data is still right.
    warehouse_conn = duckdb.connect(str(warehouse), read_only=True)
    try:
        verify(warehouse_conn)
    finally:
        warehouse_conn.close()
