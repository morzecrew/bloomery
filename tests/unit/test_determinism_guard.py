"""Named determinism guard (RFC 0003 §5.6, RFC 0009 §5.6): parse the minimal
fixture, build a hand-constructed IR, fingerprint it, and run the full
``compile_project`` pipeline — all in two subprocesses with different
``PYTHONHASHSEED`` values; stdout (including every artifact's full content)
must be byte-identical."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "minimal"

# The script parses spec text (I/O happens here, in the test — the loaders
# stay pure), dumps the parsed project, builds the shared hand-constructed IR,
# and prints its fingerprint.
SCRIPT = """
import json
import pathlib
import sys

from bloomery import Target, compile_project, load_catalog, load_project, project_fingerprint
from bloomery import build_project_ir as build_real_ir
from bloomery.emit.metricflow import emit_manifest, manifest_json
from bloomery.naming import DefaultNaming
from support.ir_factory import build_project_ir

fixture_dir = pathlib.Path(sys.argv[1])
sources = {path.stem: path.read_text() for path in sorted(fixture_dir.glob("*.yaml"))}
project = load_project(sources)

for mapping in project.mappings:
    print(mapping.source, "->", mapping.target)
    print(json.dumps(mapping.model_dump(by_alias=True), default=str))
print(json.dumps(project.entity_model.model_dump(by_alias=True), default=str))
print(project_fingerprint(build_project_ir()))

# The full pipeline (M2+): spec -> resolve -> typecheck -> IR -> artifacts.
print(project_fingerprint(build_real_ir(project)))
for artifact in compile_project(project, target=Target.SQLMESH, dialect="duckdb"):
    print(artifact.path, artifact.kind, artifact.checksum)
    print(artifact.content)

# The second targets (M10): cube YAML and dbt artifacts must be
# hash-seed-independent too — every artifact's full bytes are compared.
eb_dir = fixture_dir.parent / "ecom_basic"
eb_sources = {
    path.stem: path.read_text()
    for path in sorted(eb_dir.glob("*.yaml"))
    if path.stem != "catalog"
}
eb_project = load_project(eb_sources)
eb_catalog = load_catalog((eb_dir / "catalog.yaml").read_text())
for target in (Target.CUBE, Target.DBT):
    for artifact in compile_project(
        eb_project, target=target, dialect="postgres", catalog=eb_catalog
    ):
        print(artifact.path, artifact.kind, artifact.checksum)
        print(artifact.content)

# The MetricFlow manifest (M6): the transformed manifest's sorted-keys JSON
# is the RFC 0014 cache payload — its bytes must be hash-seed-independent.
# non_additive_aov is the regression fixture for transform()'s
# AddInputMetricMeasuresRule, which collects a RATIO metric's input_measures
# through a builtin set — hash-seed-ordered until the emitter re-sorts them.
for manifest_fixture in ("ecom_basic", "non_additive_aov"):
    mf_dir = fixture_dir.parent / manifest_fixture
    mf_sources = {
        path.stem: path.read_text()
        for path in sorted(mf_dir.glob("*.yaml"))
        if path.stem != "catalog"
    }
    mf_catalog = load_catalog((mf_dir / "catalog.yaml").read_text())
    mf_ir = build_real_ir(load_project(mf_sources), catalog=mf_catalog)
    print(manifest_json(emit_manifest(mf_ir, naming=DefaultNaming())))
"""


def run_with_hash_seed(seed: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", SCRIPT, str(FIXTURE_DIR)],
        capture_output=True,
        text=True,
        check=False,
        env={
            "PYTHONHASHSEED": seed,
            "PYTHONPATH": f"{REPO_ROOT / 'src'}:{REPO_ROOT / 'tests'}",
        },
        cwd=REPO_ROOT,
    )


def test_output_identical_across_hash_seeds() -> None:
    first = run_with_hash_seed("0")
    second = run_with_hash_seed("1")
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first.stdout == second.stdout
    assert "blm1:" in first.stdout
