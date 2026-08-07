"""Golden artifacts for the dbt × postgres matrix cell (RFC 0009 §5.4,
RFC 0008 §5.5): the port-abstraction proof — the SELECTs are byte-identical
to the sqlmesh × postgres cell (a unit test asserts it), only the envelopes
differ. ``scd2_customers`` exercises the snapshot lowering. Regenerate via
``just snapshot-update``; an unexplained golden diff fails review."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_snapshot.plugin import Snapshot

from bloomery import Target
from support.compiling import compile_fixture

pytestmark = pytest.mark.golden

GOLDEN = Path(__file__).resolve().parent

EXPECTED_PATHS = {
    "ecom_basic": [
        "dbt_project.yml",
        "models/gold/dim_date.sql",
        "models/gold/mart_order_items.sql",
        "models/schema.yml",
        "models/silver/order.sql",
        "models/silver/order_item.sql",
        "models/sources.yml",
    ],
    "scd2_customers": [
        "dbt_project.yml",
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
