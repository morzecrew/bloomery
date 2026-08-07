"""Golden artifacts per (fixture × target × dialect) (RFC 0009 §5.4): every
compiled artifact byte-compared against the checked-in file. Regenerate via
``just snapshot-update`` — golden diffs are reviewed like source code; an
unexplained diff fails review."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_snapshot.plugin import Snapshot

from support.compiling import compile_fixture

pytestmark = pytest.mark.golden

GOLDEN = Path(__file__).resolve().parent

EXPECTED_PATHS = {
    "minimal": ["models/silver/event.sql"],
    "ecom_basic": [
        "models/gold/dim_date.sql",
        "models/gold/mart_order_items.sql",
        "models/silver/order.sql",
        "models/silver/order_item.sql",
    ],
    "path_conflict": ["audits/item_net_price_reconcile.sql", "models/silver/item.sql"],
    "role_playing_dates": [
        "models/gold/dim_date.sql",
        "models/gold/mart_orders.sql",
        "models/silver/order.sql",
    ],
    "scd2_customers": ["models/silver/customer.sql"],
    # The quality-carrying fixture (RFC 0016): the entity model gains the
    # generated blocking audit on the ingestion metadata (D21) and one audit
    # per ``on_fail: fail`` rule, plus the reject model the quarantine
    # disposition routes into and the replay merge that drains it (§5.6).
    # M12 phase 3 adds the reconcile model with its **non-blocking** audit
    # (§5.3) and ``gold.mart_data_quality`` (§5.8) — an ordinary gold model,
    # which is why it sits among the marts rather than in a surface of its own.
    "semi_additive_inventory": [
        "audits/inventory_level_ingestion_metadata.sql",
        "audits/inventory_level_stock_level_not_null.sql",
        "audits/stock_level_matches_snapshot_reconcile.sql",
        "models/gold/dim_date.sql",
        "models/gold/mart_data_quality.sql",
        "models/gold/mart_inventory.sql",
        "models/silver/inventory_level.sql",
        "models/silver/inventory_level__reject.sql",
        "models/silver/stock_level_matches_snapshot__reconcile.sql",
        "replay/inventory_level.sql",
    ],
}


@pytest.mark.parametrize("fixture_name", sorted(EXPECTED_PATHS))
def test_sqlmesh_duckdb_golden(snapshot: Snapshot, fixture_name: str) -> None:
    artifacts = compile_fixture(fixture_name, dialect="duckdb")
    assert [a.path for a in artifacts] == EXPECTED_PATHS[fixture_name]
    snapshot.snapshot_dir = GOLDEN / fixture_name / "sqlmesh" / "duckdb"
    for artifact in artifacts:
        snapshot.assert_match(artifact.content, artifact.path)
