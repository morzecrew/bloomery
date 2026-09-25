"""Golden artifacts for the sqlmesh × {postgres, snowflake, trino} matrix cells
(S-0026/golden-workflow, M10 port validation): the same fixtures as the duckdb cell,
rendered through the other three dialect ports — one dialect-neutral
AST per artifact, four legal renderings. Regenerate via
``just snapshot-update``; an unexplained golden diff fails review.

The snowflake cell is the offline half of S-0013, and carries its syntax sanity
beside it: that port has no container and no emulator at this rung, so
``sqlglot.parse`` over the compiled corpus is what stands in — evidence that
every rendering is syntax Snowflake's own parser accepts, and nothing about
what its binder or its clock would do."""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlglot
from pytest_snapshot.plugin import Snapshot

from support.compiling import assert_no_orphans, compile_fixture, extract_select

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

DIALECTS = ["postgres", "snowflake", "trino"]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("fixture_name", sorted(EXPECTED_PATHS))
def test_sqlmesh_dialect_golden(snapshot: Snapshot, fixture_name: str, dialect: str) -> None:
    artifacts = compile_fixture(fixture_name, dialect=dialect)
    assert [a.path for a in artifacts] == EXPECTED_PATHS[fixture_name]
    snapshot.snapshot_dir = GOLDEN / fixture_name / "sqlmesh" / dialect
    for artifact in artifacts:
        snapshot.assert_match(artifact.content, artifact.path)
    assert_no_orphans(snapshot.snapshot_dir, EXPECTED_PATHS[fixture_name])


@pytest.mark.parametrize("fixture_name", sorted(EXPECTED_PATHS))
def test_snowflake_renderings_are_snowflake_syntax(fixture_name: str) -> None:
    """Every statement of the snowflake cell parses as Snowflake (S-0013/tests).

    ``sqlglot.parse`` rather than a hand-split on ``;`` and ``parse_one``: the
    quality mart carries a semicolon *inside* a comment, and a splitter that
    read it as a statement boundary would fail on the comment rather than on
    the SQL. The parser does the splitting and raises on the same malformed
    statement ``parse_one`` would — which is the assertion, since each
    statement here is one ``DialectPort.render`` call.

    The SQLMesh envelope is stripped first: ``MODEL (...)`` and ``AUDIT (...)``
    are SQLMesh's grammar, not Snowflake's, and the port never rendered them.
    A replay artifact has no envelope and is parsed whole — every statement of
    it, which is what the first line claims.
    """
    for artifact in compile_fixture(fixture_name, dialect="snowflake"):
        if not artifact.path.endswith(".sql"):
            continue

        statements = sqlglot.parse(extract_select(artifact.content), read="snowflake")
        assert statements, f"{fixture_name}/{artifact.path}: no statement to check"

        if "/replay/" in artifact.path:
            whole = sqlglot.parse(artifact.content, read="snowflake")
            assert len(statements) == len(whole), f"{artifact.path}: a statement was cut"
