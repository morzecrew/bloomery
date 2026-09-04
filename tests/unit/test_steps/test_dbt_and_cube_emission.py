"""Steps on the two non-SQLMesh targets (RFC 0017 D31 → D52).

D31 refused steps on dbt and Cube wholesale, on the grounds that "their output
relations would simply be missing". Held up per target, that sentence turns out
to be two different claims:

- **Cube builds nothing.** It emits cubes and views over marts and no silver
  model, no reject table, no replay statement and no audit for anything — a
  project full of quality rules compiles to two files and refuses none of it.
  So "the relation would be missing" was never a reason to refuse *here*; it is
  equally true of every silver entity, and always has been.
- **dbt builds.** So a step must either emit or refuse, per tier: a
  ``sql_model`` is a SELECT and dbt is made of SELECTs, while a
  ``python_model`` runs only on Snowflake, BigQuery and Databricks — none of
  which is one of bloomery's dialects.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from support.compiling import compile_fixture

from bloomery import Target, compile_project, load_project
from bloomery.emit import ArtifactKind, EmittedArtifact
from bloomery.errors import UnsupportedByTarget
from bloomery.steps import StepManifest, StepRegistry

pytestmark = pytest.mark.unit

#: The golden tree, so the absent `dbt/` directory can be asserted rather than
#: noticed.
GOLDEN = Path(__file__).resolve().parents[2] / "golden"

ENTITY_MODEL = "spec_version: 1\nentities: {}\n"

STEPS = (
    "steps_version: 1\nsteps:\n  - use: scored@1\n    outputs: {out: silver.scored}\n"
)

PYTHON_STEPS = (
    "steps_version: 1\nsteps:\n  - use: resolved@2\n    outputs: {out: silver.resolved}\n"
)

BODY = "SELECT k, score FROM silver.src WHERE score > :threshold"

SQL_MANIFEST: dict[str, object] = {
    "ref": "scored",
    "version": 1,
    "kind": "sql_model",
    "determinism": "pure",
    "runtime_lock": "sha256:x",
    "parameters": {"threshold": {"type": "decimal(4,3)", "default": "0.85"}},
    "outputs": {
        "out": {
            "grain": "one row per scored key",
            "key": ["k"],
            "produces": {"k": {"type": "string"}, "score": {"type": "decimal(4,3)"}},
        }
    },
}

PYTHON_MANIFEST: dict[str, object] = {
    "ref": "resolved",
    "version": 2,
    "kind": "python_model",
    "entrypoint": "platform_steps.resolve:run",
    "determinism": "pure",
    "runtime_lock": "sha256:y",
    "lineage": "coarse",
    "outputs": {
        "out": {"grain": "g", "key": ["k"], "produces": {"k": {"type": "string"}}},
    },
}


def registry(manifest: dict[str, object], body: str | None = BODY) -> StepRegistry:
    parsed = StepManifest.model_validate(manifest)
    key = (str(manifest["ref"]), int(str(manifest["version"])))
    if body is None:
        return StepRegistry({key: parsed})
    return StepRegistry({key: parsed}, sql_bodies={key: body})


def compile_steps(
    target: Target,
    manifest: dict[str, object] = SQL_MANIFEST,
    steps: str = STEPS,
    body: str | None = BODY,
) -> tuple[EmittedArtifact, ...]:
    project = load_project({"entity_model": ENTITY_MODEL, "steps": steps})
    return compile_project(
        project, target=target, dialect="duckdb", steps=registry(manifest, body)
    )


def paths(artifacts: tuple[EmittedArtifact, ...]) -> list[str]:
    return [artifact.path for artifact in artifacts]


# ....................... #
# dbt: Tier 2 emits


def test_a_sql_model_step_emits_a_dbt_model_at_the_relation_it_writes() -> None:
    artifacts = compile_steps(Target.DBT)
    assert "models/silver/scored.sql" in paths(artifacts)


def test_the_dbt_model_carries_the_same_select_sqlmesh_emits() -> None:
    """The claim the shared lowering exists to make: one SELECT, two
    envelopes. A step whose body meant something different per target would be
    the drift RFC 0008 D4 is arranged to prevent."""
    dbt = next(a for a in compile_steps(Target.DBT) if a.path == "models/silver/scored.sql")
    sqlmesh = next(
        a for a in compile_steps(Target.SQLMESH) if a.path == "models/silver/scored.sql"
    )
    body = dbt.content.partition("{{ config(materialized='table') }}")[2].strip()
    assert body == sqlmesh.content.partition(");")[2].strip()
    assert "0.85" in body  # the parameter was substituted, not left as a placeholder
    assert ":threshold" not in body


def test_the_step_output_does_not_also_emit_an_ordinary_entity_model() -> None:
    """A step output is an entity in the DAG (D36), and its lowered ``expr`` is
    the column referring to itself — so emitting the ordinary entity model
    beside the step's would produce a model selecting from the relation it
    defines, and two models writing one relation."""
    assert paths(compile_steps(Target.DBT)).count("models/silver/scored.sql") == 1


def test_a_macro_needs_no_dbt_step_artifact_at_all() -> None:
    """Tier 1 was never target-specific: it is spliced into the consuming
    SELECT at lowering, so by the time any emitter sees the IR it is already
    inside whichever model reads it."""
    artifacts = compile_steps(Target.DBT, steps="steps_version: 1\nsteps: []\n", body=None)
    assert not [a for a in artifacts if a.path.startswith("models/silver/")]


# ....................... #
# dbt: what it still refuses, and why


def test_dbt_refuses_a_python_model_naming_the_adapter_reason() -> None:
    """Narrower than D31's blanket refusal and for a concrete reason: dbt has
    Python models, but only on Snowflake, BigQuery and Databricks, and none of
    bloomery's three dialects is one of them."""
    with pytest.raises(UnsupportedByTarget, match="resolved@2"):
        compile_steps(Target.DBT, PYTHON_MANIFEST, steps=PYTHON_STEPS, body=None)


def test_the_identity_fixture_has_no_dbt_golden_because_dbt_refuses_it() -> None:
    """Why `tests/golden/identity_resolution/` holds `sqlmesh/` and `cube/` and
    no `dbt/` — stated as a test so the absence reads as a decision.

    RFC 0021 §6 asked for SQLMesh *and* dbt goldens for this fixture. dbt
    cannot emit a `python_model` step at all (RFC 0017 D52): its Python models
    run on Snowflake, BigQuery and Databricks, and none of bloomery's three
    dialects is one of them. An identity resolver is Tier 3 by construction —
    fuzzy matching is the thing SQL cannot express — so this fixture is exactly
    the shape dbt refuses.
    """
    with pytest.raises(UnsupportedByTarget) as caught:
        compile_fixture("identity_resolution", target=Target.DBT, dialect="postgres")
    assert "python_model" in str(caught.value)
    assert not (GOLDEN / "identity_resolution" / "dbt").exists()


def test_a_step_whose_output_carries_an_audit_emits_it_as_a_singular_test() -> None:
    """RFC 0026, the fourth lifted refusal.

    A step audit is a whole-query check — a join between siblings (D40) or a
    blocking rule body (D39) — and the old refusal was right that no schema
    test carries either. A singular test carries both, and the body is built
    with dbt's own spelling of "the relation this audit judges" rather than
    with ``@this_model`` rewritten afterwards (RFC 0026 D10).
    """
    wired = (
        "steps_version: 1\nsteps:\n  - use: scored@1\n    outputs: {out: silver.scored}\n"
        "    quality:\n"
        "      - {rule: expression, name: score_present, "
        'expr: "score IS NOT NULL", on_fail: fail}\n'
        "    applies_to: {score_present: out}\n"
    )
    artifacts = compile_steps(Target.DBT, steps=wired)
    (test,) = [a for a in artifacts if a.path.startswith("tests/")]
    assert test.path == "tests/step_scored_score_present.sql"
    assert "{{ ref('scored') }}" in test.content
    assert "@this_model" not in test.content
    assert "{{ config(severity='error') }}" in test.content


def test_the_same_step_with_no_audits_emits_no_test() -> None:
    """The audits are *built* rather than inferred from the presence of a
    step, so a Tier 2 step with none contributes no test — and the model still
    emits, which is what the refusal used to take away."""
    artifacts = compile_steps(Target.DBT)
    assert artifacts
    assert not [a for a in artifacts if a.path.startswith("tests/")]


# ....................... #
# Cube: nothing about building is its to refuse


@pytest.mark.parametrize("manifest", [SQL_MANIFEST, PYTHON_MANIFEST])
def test_cube_compiles_a_step_wiring_project_of_any_tier(manifest: dict[str, object]) -> None:
    """Including Tier 3, which dbt refuses. Cube does not execute the step, or
    the model, or anything else — it reads whatever table the build target
    maintained, and is deliberately silent about how."""
    sql = manifest is SQL_MANIFEST
    steps = STEPS if sql else PYTHON_STEPS
    # No marts, so Cube has nothing to describe — and, crucially, no error.
    assert compile_steps(Target.CUBE, manifest, steps=steps, body=BODY if sql else None) == ()


def test_cube_emits_no_audit_for_a_project_that_is_full_of_them() -> None:
    """The control for the argument above: refusing a step on Cube singled out
    one build-side declaration among many it already leaves alone."""
    from support.compiling import compile_fixture

    artifacts = compile_fixture("dirty_corpus", target="cube")
    assert artifacts
    assert not [
        a for a in artifacts if a.kind in {ArtifactKind.AUDIT, ArtifactKind.REPLAY}
    ]
    assert {a.path.split("/")[1] for a in artifacts} == {"cubes", "views"}


# ....................... #
# A flagged Tier 2 output, on both targets that build (RFC 0051 §5.3)


FLAG_STEPS = (
    "steps_version: 1\nsteps:\n  - use: scored@1\n    outputs: {out: silver.scored}\n"
    "    quality:\n"
    '      - {rule: expression, name: keyed, expr: "k IS NOT NULL", on_fail: flag}\n'
    "    applies_to: {keyed: out}\n"
)


def test_a_flagged_tier_two_output_carries_the_columns() -> None:
    artifacts = compile_steps(Target.SQLMESH, steps=FLAG_STEPS)
    model = next(a for a in artifacts if a.path == "models/silver/scored.sql")
    assert "_quality_flags" in model.content
    assert "_quality_ok" in model.content


def test_the_sqlmesh_quality_mart_counts_the_flagged_step_output() -> None:
    """The column the wrap adds is the column the mart reads. These two
    disagreeing is a gold model selecting something no relation has.
    """
    mart = next(
        a for a in compile_steps(Target.SQLMESH, steps=FLAG_STEPS) if "mart_data_quality" in a.path
    )
    assert "_quality_flags" in mart.content
    assert "'scored' AS entity" in mart.content


def test_a_flag_rule_on_a_step_output_now_reaches_the_dbt_wrap() -> None:
    """This refused until RFC 0052 §5.4, and not for a reason about steps: a
    flagged step output puts a *quality mart* in the project exactly as a
    flagged mapped entity does, and the mart was what dbt refused.

    That is why the wrap lives in ``step_output_body``, above the envelope
    split, rather than in the SQLMesh path that could exercise it. The
    arrangement was right and untestable on this target; it is testable now,
    which is the whole reason `logs/T-0014.md` D-073 pointed at this RFC.
    """
    artifacts = compile_steps(Target.DBT, steps=FLAG_STEPS)
    model = next(a for a in artifacts if a.path == "models/silver/scored.sql")
    assert "_quality_flags" in model.content
    assert "_quality_ok" in model.content
    # The mart the refusal was actually about is emitted too, and it reads the
    # column the wrap just added — the pair SQLMesh has been asserting since
    # RFC 0051 and dbt could not.
    mart = next(a for a in artifacts if "mart_data_quality" in a.path)
    assert "scored" in mart.content
