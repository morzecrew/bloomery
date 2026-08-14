"""Golden artifacts for the cube target (RFC 0009 §5.4, RFC 0008 §5.4):
one cube + one view per mart, dialect-independent YAML — so the matrix has
no dialect axis (a property test pins the independence). Regenerate via
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
        "model/cubes/order_items.yml",
        "model/views/order_items_view.yml",
    ],
    # Cube is asked nothing about steps (RFC 0017 D52) — it builds no relation
    # — and yet it serves a mart whose base entity a step produced. That is the
    # asymmetry worth a golden: the step is invisible here, which is exactly
    # what D36/D37 promise a downstream consumer.
    "identity_resolution": [
        "model/cubes/customers.yml",
        "model/views/customers_view.yml",
    ],
    "non_additive_aov": [
        "model/cubes/orders.yml",
        "model/views/orders_view.yml",
    ],
    "role_playing_dates": [
        "model/cubes/orders.yml",
        "model/views/orders_view.yml",
    ],
    # Cube consumes the quality mart like any other mart (RFC 0016 §5.4):
    # nothing target-specific about it, which is the point of §5.8's "ordinary
    # semantic model".
    "semi_additive_inventory": [
        "model/cubes/data_quality.yml",
        "model/cubes/inventory.yml",
        "model/views/data_quality_view.yml",
        "model/views/inventory_view.yml",
    ],
}


@pytest.mark.parametrize("fixture_name", sorted(EXPECTED_PATHS))
def test_cube_golden(snapshot: Snapshot, fixture_name: str) -> None:
    artifacts = compile_fixture(fixture_name, target=Target.CUBE)
    assert [a.path for a in artifacts] == EXPECTED_PATHS[fixture_name]
    snapshot.snapshot_dir = GOLDEN / fixture_name / "cube"
    for artifact in artifacts:
        snapshot.assert_match(artifact.content, artifact.path)
