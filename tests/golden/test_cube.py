"""Golden artifacts for the cube target (S-0026/golden-workflow, S-0025/cube-emitter-semantic):
one cube + one view per mart, dialect-independent YAML — so the matrix has
no dialect axis (a property test pins the independence). Regenerate via
``just snapshot-update``; an unexplained golden diff fails review."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_snapshot.plugin import Snapshot

from bloomery import Target, compile_project, load_project
from golden.roles_of_one_dimension import DOCUMENTS
from support.compiling import assert_no_orphans, compile_fixture

pytestmark = pytest.mark.golden

GOLDEN = Path(__file__).resolve().parent

EXPECTED_PATHS = {
    # S-0079/D-8: the only fixture declaring `determines:`, and the only
    # end-to-end evidence that an author can reach R020 — the wiring is
    # unobservable in every other one. Cube is asked nothing about it: R020 is
    # a compile-time premise, so this path list is a mart's ordinary two.
    "coarsening_rollup": [
        "model/cubes/orders.yml",
        "model/views/orders_view.yml",
    ],
    "ecom_basic": [
        "model/cubes/order_items.yml",
        "model/views/order_items_view.yml",
    ],
    # Cube is asked nothing about steps (S-0034/D-52) — it builds no relation
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
    # The pre-aggregation (S-0065/targets): a rollup is a key inside its
    # parent's document and produces no cube and no view of its own, which is
    # row 14 read from the emitter side. The golden is what shows that — the
    # path list below is the same two a mart without a rollup produces.
    "rollup_mart": [
        "model/cubes/order_items.yml",
        "model/views/order_items_view.yml",
    ],
    "role_playing_dates": [
        "model/cubes/orders.yml",
        "model/views/orders_view.yml",
    ],
    # Cube consumes the quality mart like any other mart (S-0033/fixed-pipeline-order-and-lowering):
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
    assert_no_orphans(snapshot.snapshot_dir, EXPECTED_PATHS[fixture_name])


def test_role_of_golden(snapshot: Snapshot) -> None:
    """Two roles of one dimension, as a Cube consumer sees them.

    The emitter is the visible half of S-0007's general role: both dimensions
    carry the same ``meta.role_of``, which is what a consumer reads to know
    that ``billing_region`` and ``shipping_region`` may be filtered, joined or
    asserted against each other.
    """
    artifacts = compile_project(load_project(DOCUMENTS), target=Target.CUBE, dialect="duckdb")
    paths = ["model/cubes/orders.yml", "model/views/orders_view.yml"]
    assert [a.path for a in artifacts] == paths
    snapshot.snapshot_dir = GOLDEN / "roles_of_one_dimension" / "cube"
    for artifact in artifacts:
        snapshot.assert_match(artifact.content, artifact.path)
    assert_no_orphans(snapshot.snapshot_dir, paths)
