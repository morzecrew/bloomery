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
#: quarantine surfaces, reconcile blocks, python_model steps), and a fixture
#: silently dropping off this list is a coverage loss.
#:
#: ``multi_source`` and ``coverage_check`` joined when RFC 0026 gave this
#: target a test surface — one for the union merge's collision audit, one for a
#: check that joins two relations and groups. Both are here rather than only in
#: a golden because a golden proves the bytes and only dbt can say whether dbt
#: *runs* them.
FIXTURES = (
    "coverage_check",
    "ecom_basic",
    "evolution_v1",
    "evolution_v4",
    "minimal",
    "multi_source",
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


def _run(root: pathlib.Path, command: str, *flags: str) -> object:
    from dbt.cli.main import dbtRunner

    return dbtRunner().invoke(
        [command, "--project-dir", str(root), "--profiles-dir", str(root), *flags]
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


# ....................... #
# Singular tests: that dbt *runs* them, and what happens when they fail
# (RFC 0026 §5.5, §6).


#: Two bronze rows sharing the composite key ``(A1, 1)`` across both shops —
#: the state RFC 0024 D5's collision audit exists to stop. Written against the
#: fixture's two mappings: each shop reads its own paths, so the same entity key
#: is spelled differently on each side, which is the merge's whole premise.
_COLLIDING = (
    (
        "shopify__order_lines",
        {
            "order": '{"id": "A1"}',
            "position": 1,
            "variant": '{"sku": "S"}',
            "properties": "{}",
            "quantity": 1,
        },
    ),
    ("woo__order_lines", {"order_number": "A1", "item_index": 1, "product_sku": "S", "qty": 1}),
)

#: The same two rows with the legacy shop's key moved out of the way. Disjoint
#: key sets are what the merge *requires*, so this is a project that should
#: build clean — and it is the control for the pair above, because a build that
#: failed on both would say nothing about the audit.
_DISJOINT = (
    _COLLIDING[0],
    ("woo__order_lines", {"order_number": "B2", "item_index": 1, "product_sku": "S", "qty": 1}),
)


def _insert(database: pathlib.Path, rows: tuple[tuple[str, dict[str, object]], ...]) -> None:
    """Put rows in the bronze relations ``_seed_sources`` created empty.

    Separate from that function rather than folded into it, because its "there
    are deliberately no rows" doctrine is right for what it does: the structural
    claims it serves fail just as loudly on an empty warehouse, and seeding
    every fixture would make every build slower to prove nothing extra. What
    *needs* rows is a check firing, and that is exactly two tests.

    Columns are **named**, not positional. ``_seed_sources`` derives a
    relation's column set from every column the model mentions, so a merged
    entity's two bronze tables both carry the union of both branches' columns —
    a positional insert would silently depend on that, and on its ordering.
    """
    import duckdb

    connection = duckdb.connect(str(database))
    try:
        for relation, values in rows:
            columns = ", ".join(f'"{name}"' for name in values)
            placeholders = ", ".join("?" for _ in values)
            connection.execute(
                f'INSERT INTO bronze."{relation}" ({columns}) VALUES ({placeholders})',
                list(values.values()),
            )
    finally:
        connection.close()


def _merged_project(
    tmp_path: pathlib.Path, rows: tuple[tuple[str, dict[str, object]], ...]
) -> pathlib.Path:
    database = tmp_path / "warehouse.duckdb"
    _write_project(tmp_path, "multi_source", database=str(database))
    _seed_sources(database, "multi_source")
    _insert(database, rows)
    return database


def test_a_seeded_collision_fails_dbt_build(tmp_path: pathlib.Path) -> None:
    """RFC 0026's load-bearing claim, and the only evidence for it.

    Everything else about a singular test can be proved by reading: the golden
    says the file is emitted, the unit tests say what is in it, and
    ``dbt compile`` says the SQL renders. None of that distinguishes a test dbt
    runs from SQL sitting in a directory. A build that goes red on data the
    check is *about* does.

    This is also the assertion behind lifting RFC 0024 D30. D30 refused a
    merged entity here because the merge is not correct without the audit;
    emitting the audit is only an answer if the audit actually stops a run.
    """
    _merged_project(tmp_path, _COLLIDING)
    assert not _run(tmp_path, "build").success


def test_the_same_project_builds_clean_on_disjoint_keys(tmp_path: pathlib.Path) -> None:
    """The control. A build that failed whatever the data said would prove the
    project broken rather than the check working — and the merge's own
    precondition is that the key sets are disjoint, so this is the shape a
    correct project has."""
    _merged_project(tmp_path, _DISJOINT)
    assert _run(tmp_path, "build").success


def test_dbt_run_does_not_evaluate_the_check_at_all(tmp_path: pathlib.Path) -> None:
    """The first of the operator contract's two sentences (RFC 0026 §5.5, D2).

    A SQLMesh audit blocks because the framework evaluates it as part of the
    model's materialization. A dbt test is a separate node, and ``dbt run``
    does not run tests — so the same data that fails the build above passes
    here, in silence.

    This is accepted rather than worked around, on consistency: every schema
    test this emitter has shipped since RFC 0008 has the same property, and a
    ``not_null`` audit does not block ``dbt run`` either. Refusing the merge for
    a property shared by every existing check would apply a standard exactly
    once. What it costs is a sentence in the operator contract, and this is the
    test that says the sentence is true.
    """
    _merged_project(tmp_path, _COLLIDING)
    assert _run(tmp_path, "run").success


def test_warn_error_promotes_a_flagging_check(tmp_path: pathlib.Path) -> None:
    """The mirror sentence (RFC 0026 D3), and the one a reader given only the
    first will get wrong.

    ``on_fail: flag`` means "record it and keep going" everywhere else in
    bloomery, and it maps exactly onto dbt's ``severity='warn'``. But dbt lets
    the *invocation* choose the consequence in both directions: ``--warn-error``
    promotes every warning to an error, so a flagging check stops the build
    under that flag. Neither this nor ``dbt run`` skipping a blocking check is a
    mapping error; both are the same fact about dbt, that a test's consequence
    is the invocation's to choose.

    ``coverage_check`` is the fixture because its check is declared
    ``on_fail: flag`` — the disposition under test — and a customer with no
    orders is exactly what it looks for.
    """
    database = tmp_path / "warehouse.duckdb"
    _write_project(tmp_path, "coverage_check", database=str(database))
    _seed_sources(database, "coverage_check")
    _insert(database, (("crm__customers", {"id": "c1", "name": "Silent"}),))
    assert _run(tmp_path, "build").success
    assert not _run(tmp_path, "build", "--warn-error").success


def test_a_native_test_names_its_column_where_a_singular_test_names_the_check(
    tmp_path: pathlib.Path,
) -> None:
    """RFC 0026 D4 is graded ``ASSUMED`` and D10 asks whoever builds this to
    "confirm the readability claim against real ``dbt test`` output rather than
    take it from here". This is that confirmation.

    The claim is that a native test is the better lowering *where dbt has an
    equivalent*, because it names its column in test output and a hand-rolled
    query does not. dbt names a generic test node from its model, column and
    arguments — ``not_null_customer_email`` — and a singular test from its
    filename, so a check with a column has its column in the output only if it
    stayed a schema test.

    So the split survives measurement: keeping ``not_null`` and ``enum`` native
    is worth the second mechanism, and routing everything through singular
    tests would have traded that away for uniformity.
    """
    _write_project(tmp_path, "scd2_customers", database=str(tmp_path / "warehouse.duckdb"))
    _seed_sources(tmp_path / "warehouse.duckdb", "scd2_customers")
    result = _run(tmp_path, "build")
    assert result.success, getattr(result, "exception", None)
    names = {node.node.name for node in result.result}
    # The column is in the node's own name — which is the whole of D4's claim.
    assert any(name.startswith("not_null_") and "email" in name for name in names), names
    assert any(name.startswith("accepted_values_") and "segment" in name for name in names), names
