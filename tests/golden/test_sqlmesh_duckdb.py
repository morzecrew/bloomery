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
    "ecom_basic": ["models/silver/order.sql", "models/silver/order_item.sql"],
}


@pytest.mark.parametrize("fixture_name", sorted(EXPECTED_PATHS))
def test_sqlmesh_duckdb_golden(snapshot: Snapshot, fixture_name: str) -> None:
    artifacts = compile_fixture(fixture_name, dialect="duckdb")
    assert [a.path for a in artifacts] == EXPECTED_PATHS[fixture_name]
    snapshot.snapshot_dir = GOLDEN / fixture_name / "sqlmesh" / "duckdb"
    for artifact in artifacts:
        snapshot.assert_match(artifact.content, artifact.path)
