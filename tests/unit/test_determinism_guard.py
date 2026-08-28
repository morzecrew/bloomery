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
from bloomery import all_spec_schemas, evaluate
from bloomery import build_project_ir as build_real_ir
from bloomery.emit.metricflow import emit_manifest, manifest_json
from bloomery.naming import DefaultNaming
from support.ir_factory import build_project_ir

# The JSON Schema export (RFC 0020 D3) is an output like any other and rides
# this harness rather than growing a second subprocess pair. Pydantic walks
# models through dicts and sets while generating; `$defs` order and any
# constraint rendered from a set would be hash-seed-dependent without the
# canonical sort the export applies.
print(json.dumps({kind.value: schema for kind, schema in all_spec_schemas().items()}))

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

# The union merge (RFC 0024 §6, D3): a merged entity's branch order is the one
# thing about it that could drift, and it is derived from a dict grouped by
# target and a fold over the sorted result. Both artifacts ride here — the
# model whose UNION ALL carries the order, and the collision audit whose
# GROUP BY carries the composite key.
ms_dir = fixture_dir.parent / "multi_source"
ms_sources = {path.stem: path.read_text() for path in sorted(ms_dir.glob("*.yaml"))}
for artifact in compile_project(
    load_project(ms_sources), target=Target.SQLMESH, dialect="duckdb"
):
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

# Spec evidence (M19, RFC 0022): an assessment is an output like any other, and
# every tuple on it is sorted for exactly this reason. Both a COMPLETE
# evaluation and a refused one, because the refusal path has its own sort — the
# batch is unwrapped and ordered by source path, which is a list built by
# walking dicts.
for evidence_fixture in ("ecom_basic", "fanout_trap"):
    ev_dir = fixture_dir.parent / evidence_fixture
    ev_sources = {
        path.stem: path.read_text()
        for path in sorted(ev_dir.glob("*.yaml"))
        if path.stem != "catalog"
    }
    ev_catalog_path = ev_dir / "catalog.yaml"
    ev_catalog = load_catalog(ev_catalog_path.read_text()) if ev_catalog_path.exists() else None
    evidence = evaluate(load_project(ev_sources), catalog=ev_catalog)
    print(evidence.stage_reached, evidence.fingerprint)
    print(evidence.reachable, evidence.entities)
    print([(u.name, u.missing) for u in evidence.unreachable])
    print([(m.name, m.grain, m.measures, m.dimensions, m.materialization) for m in evidence.marts])
    print([(r.source_path, type(r).__name__, str(r)) for r in evidence.refusals])
    # The unresolved-work report (RFC 0030 §6). Its open set is keyed by a dict
    # built while walking `unreachable_metrics`, its gap is decided by a walk
    # over the entity model's dicts, and `options` is deliberately *not* sorted
    # — catalog order is authored (D2), so this is the one collection here whose
    # determinism rests on the parser preserving order rather than on a sort.
    print([
        (d.canonical, d.gap, d.entity, d.field, [(o.id, o.requires, o.expr) for o in d.options],
         d.blocks)
        for d in evidence.unresolved
    ])
    print([(p.entity, p.field, p.provenance, p.recipe_id) for p in evidence.provenance])
"""


# The quality-carrying fixtures, compiled with and without the *target
# framework* imported into the same process (RFC 0016). SQLMesh extends SQLGlot
# globally on import — it registers dialects and replaces generator methods —
# so a lowering that leans on a node type SQLMesh re-renders produces different
# bytes depending on who imported what. Nobody would notice locally (``just
# test`` never imports sqlmesh) and the e2e tier would start disagreeing with
# the goldens for reasons no diff explains.
FRAMEWORK_SCRIPT = """
import pathlib
import sys

if sys.argv[2] == "imported":
    import sqlmesh  # noqa: F401

from bloomery import Target, compile_project, load_catalog, load_project

for name in ("semi_additive_inventory", "dirty_corpus", "quality_precedence"):
    fixture_dir = pathlib.Path(sys.argv[1]).parent / name
    sources = {
        path.stem: path.read_text()
        for path in sorted(fixture_dir.glob("*.yaml"))
        if path.stem != "catalog"
    }
    catalog = load_catalog((fixture_dir / "catalog.yaml").read_text())
    for artifact in compile_project(
        load_project(sources), target=Target.SQLMESH, dialect="duckdb", catalog=catalog
    ):
        print(artifact.path, artifact.checksum)
        print(artifact.content)
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


def _run_framework(state: str, *, seed: str = "0") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", FRAMEWORK_SCRIPT, str(FIXTURE_DIR), state],
        capture_output=True,
        text=True,
        check=False,
        env={
            "PYTHONPATH": f"{REPO_ROOT / 'src'}:{REPO_ROOT / 'tests'}",
            "PYTHONHASHSEED": seed,
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


def test_output_identical_whether_or_not_the_target_framework_is_imported() -> None:
    """Compilation is a pure function of the specs — including of *nothing
    else in the process*. A target framework that patches SQLGlot on import is
    exactly the kind of ambient state RFC 0003's "same specs in ⇒ byte-identical
    artifacts out" rules out, and it is invisible to every other guard here:
    the hash-seed pair above imports neither, and the golden tier only imports
    sqlmesh in the e2e lane."""
    bare = _run_framework("bare")
    imported = _run_framework("imported")
    assert bare.returncode == 0, bare.stderr
    assert imported.returncode == 0, imported.stderr
    assert bare.stdout == imported.stdout


def test_the_quality_fixtures_are_identical_across_hash_seeds() -> None:
    """The cell this guard was one short of.

    One test above varies ``PYTHONHASHSEED`` over ``minimal``/``ecom_basic``/
    ``non_additive_aov``; the other varies the sqlmesh-import axis over the
    three *quality* fixtures. Neither crossed hash seeds over the quality
    fixtures — and the quality lowering is where the sets are: rule-name
    assignment, ``in_enum``'s admissible set, the flag collection's order,
    ``redact:``'s paths. "Same specs in ⇒ byte-identical artifacts out, across
    processes and hash seeds" (RFC 0003) is one claim, and a guard that names
    two axes has to cross them on the code that most needs it.
    """
    first = _run_framework("bare", seed="0")
    second = _run_framework("bare", seed="1")
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first.stdout == second.stdout
    assert first.stdout  # the fixtures compiled to something
