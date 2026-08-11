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

**And the finding that came out of trying, now closed.** Building this tier
found that ``dbt build`` could not pass: emitted models named their inputs by
literal relation (``FROM silver.order_item``), so dbt had no dependency edges
to order them by and materialized each into the profile's target schema while
the ``FROM`` clause said ``silver``. RFC 0009 D22 recorded it with two
candidate fixes and built neither, because how deep the dbt target goes is
RFC 0008's decision. RFC 0008 D20 took **both** — they are not alternatives —
and this module now builds every fixture as well as parsing and compiling it,
with a control for the half a green build does not visibly prove.
"""

from __future__ import annotations

import pathlib

import pytest

from support.compiling import compile_fixture, resolve_dbt_references

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
      path: '{path}'
      schema: main
"""


def _write_project(root: pathlib.Path, fixture: str, *, database: str = ":memory:") -> None:
    for artifact in compile_fixture(fixture, target="dbt", dialect="duckdb"):
        path = root / artifact.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(artifact.content, encoding="utf-8")
    # bloomery emits no profiles.yml, deliberately: a profile is a *deployment*
    # secret-bearing file (host, credentials), and RFC 0003 keeps the compiler
    # free of environment. The tier supplies one, as a caller would.
    (root / "profiles.yml").write_text(PROFILES.format(path=database), encoding="utf-8")


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


def _seed_sources(database: pathlib.Path, fixture: str) -> None:
    """Create every bronze relation the project reads, **empty**.

    Columns are read off the emitted models rather than hand-listed, so a
    fixture whose mapping changes cannot leave this seeding behind. Each takes
    the type of the nearest ``CAST`` enclosing it, which is the model's own
    statement of what it expects to read: ``CAST(id AS TEXT)`` wants text, and
    ``CAST(total / qty AS DECIMAL(12, 4))`` wants two numbers — declaring that
    pair ``VARCHAR`` makes DuckDB refuse the division before the build has said
    anything about references or ordering.

    There are deliberately no rows. This tier's claim is about *structure* —
    that dbt resolves every reference, orders the models, and materializes each
    where the naming policy says — and every one of those fails on an empty
    warehouse just as loudly as on a full one: a gold model whose input has not
    been built yet errors whether or not the input would have had rows. What
    zero rows cannot check is arithmetic, which is the execution and
    equivalence tiers' job and is not restated here.
    """
    import duckdb
    from sqlglot import exp, parse_one

    def declared_type(column: exp.Column) -> str:
        node = column.parent
        while node is not None:
            if isinstance(node, exp.Cast):
                # A JSON payload is read with `->>` and cast to text; the column
                # holding it is text, not the extracted value's type.
                return "VARCHAR" if node.find(exp.JSONExtract, exp.JSONExtractScalar) else (
                    node.to.sql(dialect="duckdb")
                )
            node = node.parent
        return "VARCHAR"

    columns: dict[tuple[str, str], dict[str, str]] = {}
    for artifact in compile_fixture(fixture, target="dbt", dialect="duckdb"):
        if not artifact.path.endswith(".sql") or artifact.path.startswith("macros/"):
            continue
        body = artifact.content.partition("\n\n")[2]
        if body.rstrip("\n").endswith("{% endsnapshot %}"):
            body = body.rpartition("\n\n")[0]
        tree = parse_one(resolve_dbt_references(body.strip()), dialect="duckdb")
        # Only a `source()` survives resolution with a namespace — a `ref()`
        # resolves to a bare model name — so this selects exactly the bronze
        # relations without needing to know which they are.
        for table in tree.find_all(exp.Table):
            if not table.db:
                continue
            declared = columns.setdefault((table.db, table.name), {})
            for column in tree.find_all(exp.Column):
                if column.name:
                    declared.setdefault(column.name, declared_type(column))
    connection = duckdb.connect(str(database))
    try:
        for (namespace, relation), declared in sorted(columns.items()):
            connection.execute(f"CREATE SCHEMA IF NOT EXISTS {namespace}")
            body = ", ".join(f'"{name}" {kind}' for name, kind in sorted(declared.items()))
            connection.execute(f'CREATE TABLE {namespace}."{relation}" ({body})')
    finally:
        connection.close()


@pytest.mark.parametrize("fixture", FIXTURES)
def test_dbt_builds_the_emitted_project(fixture: str, tmp_path: pathlib.Path) -> None:
    """RFC 0009 D22's finding, closed (RFC 0008 D20).

    D22 recorded that ``dbt build`` **cannot** pass on a bloomery project and
    named two candidate fixes, neither built: emitted models referenced their
    inputs by literal relation name, so dbt had no dependency edges to order
    them by and materialized each into the profile's target schema while the
    ``FROM`` clause named ``silver``.

    Both halves have to hold for a build, and this asserts both at once —
    ordering, because a gold model that ran before its silver input would error
    on a missing relation, and placement, because its ``ref()`` resolves
    through the ``+schema`` config to the relation the naming policy names. A
    build that passes is the only thing that can say so: parse never loaded the
    DAG, and compile rendered the models without running them.
    """
    database = tmp_path / "warehouse.duckdb"
    _write_project(tmp_path, fixture, database=str(database))
    _seed_sources(database, fixture)
    result = _run(tmp_path, "build")
    assert result.success, getattr(result, "exception", None)


def test_the_build_would_notice_a_model_that_lands_in_the_wrong_schema(
    tmp_path: pathlib.Path,
) -> None:
    """The tier's control, aimed at the half a passing build proves least
    visibly. Drop the ``generate_schema_name`` override and dbt's default takes
    over: ``+schema: silver`` becomes ``main_silver``, so every model still
    *builds* — and the marts, whose ``ref()`` follows dbt's placement, still
    find their inputs. What breaks is that bloomery's relations are no longer
    where the naming policy said, which is exactly what D22 warned adopting
    ``ref()`` would cost. Asserted on the warehouse rather than the build's
    exit code, because the build does not care.
    """
    import duckdb

    database = tmp_path / "warehouse.duckdb"
    _write_project(tmp_path, "ecom_basic", database=str(database))
    _seed_sources(database, "ecom_basic")
    (tmp_path / "macros/generate_schema_name.sql").unlink()
    assert _run(tmp_path, "build").success
    connection = duckdb.connect(str(database))
    try:
        schemas = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT table_schema FROM information_schema.tables"
            ).fetchall()
        }
    finally:
        connection.close()
    assert "main_silver" in schemas, "dbt's default did not take over — the control is inert"
    assert "silver" not in schemas


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
