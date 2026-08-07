"""Golden MetricFlow manifests per mart fixture (RFC 0013 §6): the
*transformed* manifest's sorted-keys JSON, byte-compared against the
checked-in ``<fixture>/metricflow/manifest.json``. Regenerate via
``just snapshot-update``; a diff on a MetricFlow version bump is *review*,
not failure — the execution tests (M7) are the correctness gate."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_snapshot.plugin import Snapshot

from bloomery import build_project_ir
from bloomery.emit.metricflow import emit_manifest, manifest_json
from bloomery.naming import DefaultNaming
from support.compiling import load_fixture

pytestmark = pytest.mark.golden

GOLDEN = Path(__file__).resolve().parent

MART_FIXTURES = ["ecom_basic", "role_playing_dates", "semi_additive_inventory"]


@pytest.mark.parametrize("fixture_name", MART_FIXTURES)
def test_metricflow_manifest_golden(snapshot: Snapshot, fixture_name: str) -> None:
    project, catalog = load_fixture(fixture_name)
    manifest = emit_manifest(build_project_ir(project, catalog), naming=DefaultNaming())
    snapshot.snapshot_dir = GOLDEN / fixture_name / "metricflow"
    snapshot.assert_match(manifest_json(manifest, indent=2) + "\n", "manifest.json")
