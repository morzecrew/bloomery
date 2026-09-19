"""Golden MetricFlow manifests per mart fixture (S-0030/tests): the
*transformed* manifest's sorted-keys JSON, byte-compared against the
checked-in ``<fixture>/metricflow/manifest.json``. Regenerate via
``just snapshot-update``; a diff on a MetricFlow version bump is *review*,
not failure — the execution tests (M7) are the correctness gate."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_snapshot.plugin import Snapshot

from bloomery import build_project_ir, load_catalog, load_project
from golden.roles_of_one_dimension import CATALOG, DOCUMENTS
from bloomery.emit.metricflow import emit_manifest, manifest_json
from bloomery.naming import DefaultNaming
from support.compiling import load_fixture

pytestmark = pytest.mark.golden

GOLDEN = Path(__file__).resolve().parent

MART_FIXTURES = [
    "ecom_basic",
    "multi_mart_refusal",
    "non_additive_aov",
    # The only golden that carries the S-0050 shapes: DERIVED with both
    # offset forms, CUMULATIVE with both window forms, and a SIMPLE metric with
    # a where-filter. It is a manifest golden and nothing else — a metric shape
    # never reaches the mart SQL, so the SQLMesh and dbt matrices would gain a
    # fixture and no information, and Cube refuses this project outright
    # (S-0050/D-11), which its own unit test pins by message.
    "period_over_period",
    "role_playing_dates",
    "semi_additive_inventory",
]


@pytest.mark.parametrize("fixture_name", MART_FIXTURES)
def test_metricflow_manifest_golden(snapshot: Snapshot, fixture_name: str) -> None:
    project, catalog = load_fixture(fixture_name)
    manifest = emit_manifest(build_project_ir(project, catalog), naming=DefaultNaming())
    snapshot.snapshot_dir = GOLDEN / fixture_name / "metricflow"
    snapshot.assert_match(manifest_json(manifest, indent=2) + "\n", "manifest.json")


def test_role_of_manifest_golden(snapshot: Snapshot) -> None:
    """Two roles of one dimension, as a MetricFlow consumer sees them.

    MSI has no free-form metadata on a dimension, so the shared dimension
    travels on each foreign entity's ``role`` — two entities, one role, where
    two bare prefixes said nothing to relate them (S-0007/what-each-fact-buys).
    """
    manifest = emit_manifest(build_project_ir(load_project(DOCUMENTS), load_catalog(CATALOG)), naming=DefaultNaming())
    snapshot.snapshot_dir = GOLDEN / "roles_of_one_dimension" / "metricflow"
    snapshot.assert_match(manifest_json(manifest, indent=2) + "\n", "manifest.json")
