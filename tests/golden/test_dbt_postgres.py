"""Golden artifacts for the dbt × postgres matrix cell (RFC 0009 §5.4,
RFC 0008 §5.5): the port-abstraction proof — the SELECTs are byte-identical
to the sqlmesh × postgres cell (a unit test asserts it), only the envelopes
differ. ``scd2_customers`` exercises the snapshot lowering, ``multi_source`` the
union merge and the singular test its collision audit needs (RFC 0026). Regenerate via
``just snapshot-update``; an unexplained golden diff fails review."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_snapshot.plugin import Snapshot

from bloomery import Target
from support.compiling import assert_no_orphans, compile_fixture

pytestmark = pytest.mark.golden

GOLDEN = Path(__file__).resolve().parent

EXPECTED_PATHS = {
    "ecom_basic": [
        "dbt_project.yml",
        "macros/generate_schema_name.sql",
        "models/gold/dim_date.sql",
        "models/gold/mart_order_items.sql",
        "models/schema.yml",
        "models/silver/order.sql",
        "models/silver/order_item.sql",
        "models/sources.yml",
    ],
    # RFC 0026 §6: the fixture RFC 0024 P1 built and could only emit to
    # SQLMesh. The collision audit landing on both targets is the assertion
    # that D30 is lifted rather than routed around — and `tests/` appearing
    # here at all is the assertion that this target has a test surface.
    "multi_source": [
        "dbt_project.yml",
        "macros/generate_schema_name.sql",
        "models/silver/order_line.sql",
        "models/sources.yml",
        "tests/order_line_source_collision.sql",
    ],
    "scd2_customers": [
        "dbt_project.yml",
        "macros/generate_schema_name.sql",
        "models/schema.yml",
        "models/sources.yml",
        "snapshots/customer_snapshot.sql",
    ],
}


@pytest.mark.parametrize("fixture_name", sorted(EXPECTED_PATHS))
def test_dbt_postgres_golden(snapshot: Snapshot, fixture_name: str) -> None:
    artifacts = compile_fixture(fixture_name, target=Target.DBT, dialect="postgres")
    assert [a.path for a in artifacts] == EXPECTED_PATHS[fixture_name]
    snapshot.snapshot_dir = GOLDEN / fixture_name / "dbt" / "postgres"
    for artifact in artifacts:
        snapshot.assert_match(artifact.content, artifact.path)
    assert_no_orphans(snapshot.snapshot_dir, EXPECTED_PATHS[fixture_name])
