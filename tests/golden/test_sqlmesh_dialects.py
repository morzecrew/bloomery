"""Golden artifacts for the sqlmesh × {trino, postgres} matrix cells
(RFC 0009 §5.4, M10 port validation): the same fixtures as the duckdb cell,
rendered through the second and third dialect ports — one dialect-neutral
AST per artifact, three legal renderings. Regenerate via
``just snapshot-update``; an unexplained golden diff fails review."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_snapshot.plugin import Snapshot

from support.compiling import assert_no_orphans, compile_fixture

pytestmark = pytest.mark.golden

GOLDEN = Path(__file__).resolve().parent

#: The full three-dialect matrix runs where the fixture exercises dialect-
#: sensitive rendering (JSON extraction, timezone shift, date bucketing,
#: reserved-word quoting); the remaining fixtures stay duckdb-only — their
#: rendering surface is covered by these cells (RFC 0009 §5.4).
EXPECTED_PATHS = {
    "minimal": ["models/silver/event.sql"],
    # RFC 0024: the union merge brings two constructs nothing else here emits —
    # `UNION ALL` between branches, and the typed `NULL` that fills a column one
    # mapping does not map. Both are rendered by the dialect port, and a
    # duckdb-only cell would leave the port's claim unproven for exactly the
    # SQL this feature added.
    "multi_source": [
        "audits/order_line_source_collision.sql",
        "models/silver/order_line.sql",
    ],
    # The cleaned merge, on both engines. What it adds over the row above is
    # every construct P2 introduced: the dedupe `QUALIFY` over a union, a
    # metadata audit partitioned by `(_source, _source_row_id)` (RFC 0024 D34),
    # a per-branch `reject_id` digest — which is spelled differently on every
    # engine (RFC 0016 D83) and whose whole point is that they agree — and a
    # replay whose branches filter on `source_relation` (RFC 0035 D3).
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
    "role_playing_dates": [
        "models/gold/dim_date.sql",
        "models/gold/mart_orders.sql",
        "models/silver/order.sql",
    ],
}

DIALECTS = ["postgres", "trino"]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("fixture_name", sorted(EXPECTED_PATHS))
def test_sqlmesh_dialect_golden(snapshot: Snapshot, fixture_name: str, dialect: str) -> None:
    artifacts = compile_fixture(fixture_name, dialect=dialect)
    assert [a.path for a in artifacts] == EXPECTED_PATHS[fixture_name]
    snapshot.snapshot_dir = GOLDEN / fixture_name / "sqlmesh" / dialect
    for artifact in artifacts:
        snapshot.assert_match(artifact.content, artifact.path)
    assert_no_orphans(snapshot.snapshot_dir, EXPECTED_PATHS[fixture_name])
