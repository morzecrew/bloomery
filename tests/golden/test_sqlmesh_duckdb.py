"""Golden artifacts per (fixture × target × dialect) (RFC 0009 §5.4): every
compiled artifact byte-compared against the checked-in file. Regenerate via
``just snapshot-update`` — golden diffs are reviewed like source code; an
unexplained diff fails review."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_snapshot.plugin import Snapshot

from support.compiling import assert_no_orphans, compile_fixture

pytestmark = pytest.mark.golden

GOLDEN = Path(__file__).resolve().parent

EXPECTED_PATHS = {
    # RFC 0017 §5.8/D16: one generated wrapper per declared output, so a
    # two-output step is two `.py` models. The extension is the point of this
    # entry — RFC 0008 D2's "artifacts are file-shaped text" is what lets a
    # Python model reuse ArtifactKind.MODEL with a different suffix.
    "step_resolution": [
        "audits/step_customer_xref_canonical_id_references_customer.sql",
        "models/silver/customer.py",
        "models/silver/customer_raw.sql",
        "models/silver/customer_xref.py",
    ],
    # RFC 0021 §5.1: identity resolution end to end on shipped mechanisms.
    # What the goldens show that `step_resolution` cannot: two *inputs* bound
    # from two sources with no shared key, an `expression` rule with
    # `on_fail: fail` attached to a step output, and a mart over the
    # step-produced entity — the D49 `canonical:` link's whole reason to exist.
    "identity_resolution": [
        "audits/step_customer_confidence_is_high.sql",
        "audits/step_customer_xref_canonical_id_references_customer.sql",
        "models/gold/dim_date.sql",
        "models/gold/mart_customers.sql",
        "models/silver/customer.py",
        "models/silver/customer_billing.sql",
        "models/silver/customer_crm.sql",
        "models/silver/customer_xref.py",
    ],
    "minimal": ["models/silver/event.sql"],
    # RFC 0024 §5.4/D5: the union merge's one generated artifact beyond the
    # model — the blocking audit that establishes what compilation cannot, that
    # the sources' key sets are disjoint. It is here rather than under a
    # `_quality_*` name because it guards the *merge*, not the quality system.
    "multi_source": [
        "audits/order_line_source_collision.sql",
        "models/silver/order_line.sql",
    ],
    # The same merge, cleaned (RFC 0024 P2 — D32-D35 — and RFC 0035). A second
    # fixture rather than blocks added to the one above, because dbt lowers no
    # reject model (RFC 0016 §5.4) and `multi_source` is the fixture both
    # targets compile: merging the two would have bought this coverage by
    # deleting that.
    "multi_source_quality": [
        "audits/order_line_conservation.sql",
        "audits/order_line_ingestion_metadata.sql",
        "audits/order_line_line_no_coercible.sql",
        "audits/order_line_placed_at_coercible.sql",
        "audits/order_line_source_collision.sql",
        "models/gold/mart_data_quality.sql",
        "models/silver/order_line.sql",
        "models/silver/order_line__reject.sql",
        "replay/order_line.sql",
    ],
    "ecom_basic": [
        "models/gold/dim_date.sql",
        "models/gold/mart_order_items.sql",
        "models/silver/order.sql",
        "models/silver/order_item.sql",
    ],
    "path_conflict": ["audits/item_net_price_reconcile.sql", "models/silver/item.sql"],
    # The same conflict on a merged entity (RFC 0024 D36, answering D28). What
    # the golden shows and the IR assertions cannot: one shadow column and one
    # reconcile audit for the entity, and a `__direct` projection per UNION ALL
    # arm reading *that* arm's own path — the fan-out D28 refused while a
    # single shadow stood for every source.
    "path_conflict_merged": [
        "audits/item_net_price_reconcile.sql",
        "audits/item_source_collision.sql",
        "models/silver/item.sql",
    ],
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
    # M12 phase 4 adds ``<entity>_conservation``: §6 asks for the conservation
    # law "emitted as a runtime audit on every production run, not only a
    # test", so it is an artifact, not just an assertion.
    "semi_additive_inventory": [
        "audits/inventory_level_conservation.sql",
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
    assert_no_orphans(snapshot.snapshot_dir, EXPECTED_PATHS[fixture_name])
