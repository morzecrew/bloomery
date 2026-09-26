"""Golden artifacts for the sqlmesh × {bigquery, postgres, trino} matrix cells
(S-0026/golden-workflow, M10 port validation): the same fixtures as the duckdb cell,
rendered through the other three dialect ports — one dialect-neutral
AST per artifact, four legal renderings. Regenerate via
``just snapshot-update``; an unexplained golden diff fails review.

The bigquery cell is this port's byte-stability rung (S-0014): it is the only
place the port's rewrites are read on the whole fixture corpus rather than on
a construction a unit test built, and the only one where a change to them
presents as a diff somebody has to explain."""

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
#: rendering surface is covered by these cells (S-0026/golden-workflow).
EXPECTED_PATHS = {
    "minimal": ["config.yaml", "models/silver/event.sql"],
    # S-0041: the union merge brings two constructs nothing else here emits —
    # `UNION ALL` between branches, and the typed `NULL` that fills a column one
    # mapping does not map. Both are rendered by the dialect port, and a
    # duckdb-only cell would leave the port's claim unproven for exactly the
    # SQL this feature added.
    "multi_source": [
        "audits/order_line_source_collision.sql",
        "config.yaml",
        "models/silver/order_line.sql",
    ],
    # The cleaned merge, on both engines. What it adds over the row above is
    # every construct P2 introduced: the dedupe `QUALIFY` over a union, a
    # metadata audit partitioned by `(_source, _source_row_id)` (S-0041/D-34),
    # a per-branch `reject_id` digest — which is spelled differently on every
    # engine (S-0033/D-83) and whose whole point is that they agree — and a
    # replay whose branches filter on `source_relation` (S-0051/D-3).
    "multi_source_quality": [
        "audits/order_line_conservation.sql",
        "audits/order_line_ingestion_metadata.sql",
        "audits/order_line_line_no_coercible.sql",
        "audits/order_line_placed_at_coercible.sql",
        "audits/order_line_source_collision.sql",
        "config.yaml",
        "models/gold/mart_data_quality.sql",
        "models/silver/order_line.sql",
        "models/silver/order_line__reject.sql",
        "replay/order_line.sql",
    ],
    "ecom_basic": [
        "config.yaml",
        "models/gold/dim_date.sql",
        "models/gold/mart_order_items.sql",
        "models/silver/order.sql",
        "models/silver/order_item.sql",
    ],
    "role_playing_dates": [
        "config.yaml",
        "models/gold/dim_date.sql",
        "models/gold/mart_orders.sql",
        "models/silver/order.sql",
    ],
}

#: ``databricks`` joins the matrix with the port (S-0016): its rewrites are
#: concentrated in exactly the SQL these cells hold — ``TIMESTAMP_NTZ`` where
#: the others say ``TIMESTAMP``, the ``:`` accessor, the backtick-quoted
#: reserved relation name, ``TO_JSON(NAMED_STRUCT(…))`` for the reject table —
#: and the artifacts are what freeze S-0016/D-8 and D-9.
DIALECTS = ["bigquery", "databricks", "postgres", "trino"]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("fixture_name", sorted(EXPECTED_PATHS))
def test_sqlmesh_dialect_golden(snapshot: Snapshot, fixture_name: str, dialect: str) -> None:
    artifacts = compile_fixture(fixture_name, dialect=dialect)
    assert [a.path for a in artifacts] == EXPECTED_PATHS[fixture_name]
    snapshot.snapshot_dir = GOLDEN / fixture_name / "sqlmesh" / dialect
    for artifact in artifacts:
        snapshot.assert_match(artifact.content, artifact.path)
    assert_no_orphans(snapshot.snapshot_dir, EXPECTED_PATHS[fixture_name])
