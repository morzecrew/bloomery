"""E2E tier (RFC 0009 §5.2 tier 6): ``dbt parse`` over the emitted project.

§5.2 names this cell in three words — "Equivalents: `dbt parse`" — and the
sentence above them is what it is for: *artifacts are valid input to the
target, not just valid SQL*. A golden proves bloomery emits the bytes it meant
to; only dbt can say whether dbt accepts them.

**What a parse proves, exactly.** ``dbt parse`` builds the manifest: it reads
``dbt_project.yml``, renders every model's Jinja — so a malformed
``{{ config(...) }}`` fails here — and validates ``schema.yml`` and
``sources.yml`` against dbt's own schemas. That is the whole of the D52 claim
this closes: the Tier 2 step model is a file dbt accepts.

**What a parse does *not* prove, corrected.** This module used to claim parse
also validates "whether a declared test is a thing dbt recognizes". It does
not, and the overclaim cost a real defect: parse accepts a test named
``utter_nonsense_not_a_test`` in silence, because it checks the *shape* of a
``schema.yml`` entry and never resolves the macro behind the name. Only
``compile`` renders the test bodies — which is where the missing
``dbt_utils`` dependency surfaced (RFC 0008 D18), long after this tier was
written to catch exactly that class of thing. Hence the compile pass below.

**What it does not prove, and the finding that came out of trying.** A parse
does not execute SQL, and ``dbt build`` on the same project **fails** — for a
reason that is bloomery's rather than the test's, and that was unrecorded until
this tier was built. Emitted dbt models reference their inputs by literal
relation name (``FROM silver.order_item``) rather than through ``{{ ref(...) }}``
or ``{{ source(...) }}``, so dbt has no dependency edges between them and
materializes each into the profile's target schema while its ``FROM`` clause
names ``silver``. See RFC 0009 D22 for the two candidate fixes; neither is
built, and this module asserts parse rather than pretending build is out of
scope for a reason of principle.
"""

from __future__ import annotations

import pathlib

import pytest

from support.compiling import compile_fixture

pytestmark = pytest.mark.e2e

#: Every fixture the dbt target compiles. Enumerated rather than hand-listed
#: from memory: the refused ones are refused for stated reasons (quality
#: quarantine surfaces, reconcile blocks, python_model steps, mart assertions),
#: and a fixture silently dropping off this list is a coverage loss.
FIXTURES = (
    "ecom_basic",
    "evolution_v1",
    "evolution_v4",
    "minimal",
    "non_additive_aov",
    "path_conflict",
    "role_playing_dates",
    "scd2_customers",
)

PROFILES = """\
bloomery:
  target: local
  outputs:
    local:
      type: duckdb
      path: ':memory:'
"""


def _write_project(root: pathlib.Path, fixture: str) -> None:
    for artifact in compile_fixture(fixture, target="dbt", dialect="duckdb"):
        path = root / artifact.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(artifact.content, encoding="utf-8")
    # bloomery emits no profiles.yml, deliberately: a profile is a *deployment*
    # secret-bearing file (host, credentials), and RFC 0003 keeps the compiler
    # free of environment. The tier supplies one, as a caller would.
    (root / "profiles.yml").write_text(PROFILES, encoding="utf-8")


def _run(root: pathlib.Path, command: str) -> object:
    from dbt.cli.main import dbtRunner

    return dbtRunner().invoke(
        [command, "--project-dir", str(root), "--profiles-dir", str(root)]
    )


@pytest.mark.parametrize("fixture", FIXTURES)
def test_dbt_accepts_the_emitted_project(fixture: str, tmp_path: pathlib.Path) -> None:
    """The tier's whole contract, per fixture. A failure here is a project dbt
    refuses to load at all — which no golden and no DuckDB execution can see,
    because both read the SQL and neither reads ``dbt_project.yml``."""
    _write_project(tmp_path, fixture)
    result = _run(tmp_path, "parse")
    assert result.success, getattr(result, "exception", None)


@pytest.mark.parametrize("fixture", FIXTURES)
def test_dbt_resolves_every_test_the_project_declares(
    fixture: str, tmp_path: pathlib.Path
) -> None:
    """The stronger claim, and the one parse cannot make (D18). Parse validates
    ``schema.yml`` against dbt's *schema* — that a test entry is well-formed —
    and stops there; it accepts a test named ``utter_nonsense_not_a_test``
    without a word. ``compile`` renders each test's body, so an unresolvable
    macro fails here and nowhere earlier.

    This is what caught bloomery emitting ``dbt_utils.expression_is_true``
    with no ``packages.yml``: every project carrying a ``min``/``max``/
    ``regex``/``reconcile`` assert declared a test dbt could not build.
    """
    _write_project(tmp_path, fixture)
    result = _run(tmp_path, "compile")
    assert result.success, getattr(result, "exception", None)


def test_a_tier_two_step_model_is_a_file_dbt_accepts(tmp_path: pathlib.Path) -> None:
    """RFC 0017 D52 emitted the model and said plainly that dbt *parsing* it was
    RFC 0009's outstanding work rather than something the row claimed. This is
    that work."""
    from bloomery import Target, compile_project, load_project
    from bloomery.steps import StepManifest, StepRegistry

    manifest = StepManifest.model_validate(
        {
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
                    "produces": {"k": {"type": "string"}},
                }
            },
        }
    )
    project = load_project(
        {
            "entity_model": "spec_version: 1\nentities: {}\n",
            "steps": (
                "steps_version: 1\nsteps:\n  - use: scored@1\n"
                "    outputs: {out: silver.scored}\n"
            ),
        }
    )
    registry = StepRegistry(
        {("scored", 1): manifest},
        sql_bodies={("scored", 1): "SELECT k FROM silver.src WHERE score > :threshold"},
    )
    for artifact in compile_project(
        project, target=Target.DBT, dialect="duckdb", steps=registry
    ):
        path = tmp_path / artifact.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(artifact.content, encoding="utf-8")
    (tmp_path / "profiles.yml").write_text(PROFILES, encoding="utf-8")
    result = _run(tmp_path, "parse")
    assert result.success, getattr(result, "exception", None)
    assert (tmp_path / "models/silver/scored.sql").exists()


def test_a_malformed_config_block_would_be_caught(tmp_path: pathlib.Path) -> None:
    """The tier's own control. A parse that passes whatever it is handed proves
    nothing about the projects above — so one model's ``config()`` is broken
    here, and dbt must refuse it."""
    _write_project(tmp_path, "minimal")
    model = tmp_path / "models/silver/event.sql"
    model.write_text(
        model.read_text(encoding="utf-8").replace(
            "{{ config(materialized='table') }}", "{{ config(materialized= }}"
        ),
        encoding="utf-8",
    )
    assert not _run(tmp_path, "parse").success
