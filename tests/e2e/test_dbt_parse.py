"""E2E tier (S-0026/tier-contracts tier 6): ``dbt parse`` over the emitted project.

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
``dbt_utils`` dependency surfaced (S-0025/D-18), long after this tier was
written to catch exactly that class of thing. Hence the compile pass below.

**And the finding that came out of trying, now closed.** Building this tier
found that ``dbt build`` could not pass: emitted models named their inputs by
literal relation (``FROM silver.order_item``), so dbt had no dependency edges
to order them by and materialized each into the profile's target schema while
the ``FROM`` clause said ``silver``. S-0026/D-22 recorded it with two
candidate fixes and built neither, because how deep the dbt target goes is
S-0025's decision. S-0025/D-20 took **both** — they are not alternatives —
and this module now builds every fixture as well as parsing and compiling it,
with a control for the half a green build does not visibly prove.
"""

from __future__ import annotations

import datetime
import pathlib

import pytest

from support.compiling import (
    compile_fixture,
    fixture_sources,
    load_fixture,
    resolve_dbt_references,
)

from bloomery import Target, compile_project, load_project

pytestmark = pytest.mark.e2e

#: Every fixture the dbt target compiles. Enumerated rather than hand-listed
#: from memory: the refused ones are refused for stated reasons (quality
#: quarantine surfaces, reconcile blocks, python_model steps), and a fixture
#: silently dropping off this list is a coverage loss.
#:
#: ``multi_source`` and ``coverage_check`` joined when S-0043 gave this
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
    # S-0060: the two that were refused for their quality surface. One
    # carries a reject table with its replay macro and the quality mart;
    # the other adds two reconcile comparisons and their tests. They are here
    # for the reason every other fixture is — a golden proves the bytes, and
    # only dbt can say whether dbt loads, orders and runs them.
    "multi_source_quality",
    "non_additive_aov",
    "path_conflict",
    "quality_precedence",
    "role_playing_dates",
    "scd2_customers",
    # S-0003/P-1: the pair nothing combined — a historical entity with a
    # quarantine policy — whose replay writes to bronze instead of merging.
    "scd2_replay",
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
    # secret-bearing file (host, credentials), and S-0020 keeps the compiler
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
        if "{% if is_incremental() %}" in body:
            # The reject model is two pre-rendered SELECTs (S-0060/D-2). Both
            # read the same bronze relations — the incremental one additionally
            # joins `{{ this }}`, which is not a source — so the first-run arm
            # is the whole of what this needs to seed.
            body = body.partition("{% else %}")[2].partition("{% endif %}")[0]
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
    """S-0026/D-22's finding, closed (S-0025/D-20).

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


def test_dbt_resolves_an_exposure_to_the_models_it_reads(tmp_path: pathlib.Path) -> None:
    """S-0063/tests: the leg a golden cannot make.

    A well-formed ``exposures.yml`` naming a model that does not exist parses
    fine and fails at selection, so this asks dbt the question the feature
    exists to answer — ``dbt ls --select +exposure:*``, the graph operator that
    walks *upstream* from every exposure — and checks that the models come back.
    That is the whole of what "the lineage graph has a sink" means on this
    target.

    It is also the assertion that keeps §5.1's emitted block from coming back:
    a ``metric('…')`` entry fails ``dbt parse`` outright, because this emitter
    declares no metrics (logs/T-0038.md). Both exposures in ``ecom_basic``
    resolve here — one through the mart it names, one through the mart serving
    the metrics it names.
    """

    _write_project(tmp_path, "ecom_basic")
    result = _run(tmp_path, "ls", "--select", "+exposure:*", "--resource-type", "all")
    assert result.success, getattr(result, "exception", None)

    listed = set(result.result)  # type: ignore[attr-defined]
    assert {"bloomery.finance_extract", "bloomery.weekly_revenue_review"} <= {
        name.removeprefix("exposure:") for name in listed
    }
    # The upstream walk reached past the exposure itself: the mart it reads,
    # and the silver models that mart reads.
    assert "bloomery.gold.mart_order_items" in listed
    assert "bloomery.silver.order_item" in listed


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
    """S-0034/D-52 emitted the model and said plainly that dbt *parsing* it was
    S-0026's outstanding work rather than something the row claimed. This is
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
# (S-0043/blocking-and-the-two-honest-weakenings, S-0043/tests).


#: Two bronze rows sharing the composite key ``(A1, 1)`` across both shops —
#: the state S-0041/D-5's collision audit exists to stop. Written against the
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
    """S-0043's load-bearing claim, and the only evidence for it.

    Everything else about a singular test can be proved by reading: the golden
    says the file is emitted, the unit tests say what is in it, and
    ``dbt compile`` says the SQL renders. None of that distinguishes a test dbt
    runs from SQL sitting in a directory. A build that goes red on data the
    check is *about* does.

    This is also the assertion behind lifting S-0041/D-30. D30 refused a
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
    """The first of the operator contract's two sentences (S-0043/blocking-and-the-two-honest-weakenings, S-0043/D-2).

    A SQLMesh audit blocks because the framework evaluates it as part of the
    model's materialization. A dbt test is a separate node, and ``dbt run``
    does not run tests — so the same data that fails the build above passes
    here, in silence.

    This is accepted rather than worked around, on consistency: every schema
    test this emitter has shipped since S-0025 has the same property, and a
    ``not_null`` audit does not block ``dbt run`` either. Refusing the merge for
    a property shared by every existing check would apply a standard exactly
    once. What it costs is a sentence in the operator contract, and this is the
    test that says the sentence is true.
    """
    _merged_project(tmp_path, _COLLIDING)
    assert _run(tmp_path, "run").success


def test_warn_error_promotes_a_flagging_check(tmp_path: pathlib.Path) -> None:
    """The mirror sentence (S-0043/D-3), and the one a reader given only the
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
    """S-0043/D-4 is graded ``ASSUMED`` and D10 asks whoever builds this to
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


def test_the_snapshot_materializes_the_interval_under_the_names_the_ir_owns(
    tmp_path: pathlib.Path,
) -> None:
    """The claim the whole as-of design rests on, measured rather than read off
    a config (S-0040/phase-2-the-as-of-join, S-0040/D-7).

    One as-of predicate is lowered for every target, so it references one pair
    of column names. SQLMesh already spells them `valid_from`/`valid_to`; dbt
    would call them `dbt_valid_from`/`dbt_valid_to`, and the emitter passes
    `snapshot_meta_column_names` to move them. Emitting that config proves
    nothing on its own — the question is whether the *built table* has those
    columns, which only running dbt can answer.
    """
    database = tmp_path / "warehouse.duckdb"
    _write_project(tmp_path, "scd2_customers", database=str(database))
    _seed_sources(database, "scd2_customers")
    assert _run(tmp_path, "build").success

    import duckdb  # local, as `_seed_sources` does: the driver is a test dep

    connection = duckdb.connect(str(database))
    try:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info('silver.customer_snapshot')").fetchall()
        }
    finally:
        connection.close()

    assert {"valid_from", "valid_to"} <= columns
    assert "dbt_valid_from" not in columns
    assert "dbt_valid_to" not in columns


def test_dbt_reads_the_annotations_it_was_given(tmp_path: pathlib.Path) -> None:
    """S-0062's metadata, read back off dbt's own manifest.

    A green ``parse`` is not enough here, and this module already knows why:
    parse validates the *shape* of a ``schema.yml`` entry and will accept
    entries whose contents mean nothing to it. So the assertion is on the
    manifest — the node dbt built — which is the only thing that says a
    `config: grants:` block reached dbt's model config rather than sitting in
    the file being ignored.

    Both annotated fixtures, because they carry different halves: `minimal`
    has the grants and `ecom_basic` has the owner and the column
    classification.
    """
    import json

    for fixture, assertions in (
        ("minimal", ("grants",)),
        ("ecom_basic", ("owner", "classification")),
    ):
        root = tmp_path / fixture
        root.mkdir()
        _write_project(root, fixture)
        assert _run(root, "parse").success

        manifest = json.loads((root / "target" / "manifest.json").read_text())
        nodes = manifest["nodes"]

        if "grants" in assertions:
            event = next(n for n in nodes.values() if n["name"] == "event")
            assert event["config"]["grants"] == {"select": ["analyst", "reverse_etl"]}

        if "owner" in assertions:
            order = next(n for n in nodes.values() if n["name"] == "order")
            assert order["meta"]["owner"] == "commerce-platform@example.com"
            mart = next(n for n in nodes.values() if n["name"] == "mart_order_items")
            assert mart["meta"]["owner"] == "analytics@example.com"

        if "classification" in assertions:
            order = next(n for n in nodes.values() if n["name"] == "order")
            assert order["columns"]["customer_id"]["meta"] == {"classification": "pii"}


# ....................... #
# Replay on a historical entity (S-0003/P-1)

_NARROW = "\"segment IN ('smb', 'ent')\""
_WIDE = "\"segment IN ('smb', 'ent', 'startup')\""

#: ``c2`` arrives with a segment the spec does not know, so it is diverted and
#: never versioned. The orders are dated after every version dbt will write:
#: dbt stamps a version with its own wall clock, and an order dated in the past
#: is reachable from no version at all — the apparatus failure that made every
#: route read as invisible when this was first measured (logs/T-0057.md).
_CUSTOMERS = (
    {"customer_id": "c1", "segment": "smb", "signed_up_at": "2023-01-15T00:00:00"},
    {"customer_id": "c2", "segment": "startup", "signed_up_at": "2023-05-02T00:00:00"},
)
_ORDERS = (
    {"id": "o1", "customer_id": "c1", "amount": "100.00", "order_date": "2099-03-10"},
    {"id": "o2", "customer_id": "c2", "amount": "250.00", "order_date": "2099-09-20"},
)


def _write_replay_project(root: pathlib.Path, database: pathlib.Path, *, wide: bool) -> None:
    """The emitted project, with the quarantine rule optionally widened.

    The widening is a **spec** edit, which is what replay is for: the diverted
    row's payload is in the reject table, and re-running the current mapping
    against it is how the row comes back. Editing bronze instead would prove
    nothing — a row that can be fixed in bronze never needed replay.
    """
    sources = dict(fixture_sources("scd2_replay"))

    if wide:
        assert _NARROW in sources["entity_model"]
        sources["entity_model"] = sources["entity_model"].replace(_NARROW, _WIDE)

    _, catalog = load_fixture("scd2_replay")
    artifacts = compile_project(
        load_project(sources), target=Target.DBT, dialect="duckdb", catalog=catalog
    )

    for artifact in artifacts:
        path = root / artifact.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(artifact.content, encoding="utf-8")

    (root / "profiles.yml").write_text(PROFILES.format(path=str(database)), encoding="utf-8")


def _segments(database: pathlib.Path) -> dict[str, str | None]:
    import duckdb

    connection = duckdb.connect(str(database))
    try:
        return {
            str(order): segment
            for order, segment in connection.execute(
                "SELECT order_id, customer_segment FROM gold.mart_orders"
            ).fetchall()
        }
    finally:
        connection.close()


def test_the_as_of_join_finds_a_row_recovered_through_bronze(tmp_path: pathlib.Path) -> None:
    """S-0003/D-3, and the only assertion the design accepts.

    Not a row count, and not the row's presence in the snapshot: the defect
    this phase removes was a row that **landed** — merged past dbt with a NULL
    validity interval, reported as a success, and stepped over by every as-of
    join. A presence assertion passes against that. So the claim is the mart's
    own as-of join, run after dbt has versioned the row.

    The middle assertion is what makes the last one mean something: right after
    the replay macro runs, the snapshot still does not carry ``c2``. Replay did
    not write it there and never will — dbt does, on the next build, with the
    interval dbt assigns (D2, D8).
    """
    database = tmp_path / "warehouse.duckdb"
    _write_replay_project(tmp_path, database, wide=False)
    _seed_sources(database, "scd2_replay")
    _insert(
        database,
        (
            *(("crm__customers", _row(row)) for row in _CUSTOMERS),
            # No ingestion metadata on the fact: only an entity with a reject
            # table or a dedupe requires the contract (S-0033/D-21), and
            # `order` declares neither.
            *(("shop__orders", dict(row)) for row in _ORDERS),
        ),
    )
    assert _run(tmp_path, "build").success

    # The diverted row has no version, so its order is attributed to nothing.
    assert _segments(database) == {"o1": "smb", "o2": None}

    _write_replay_project(tmp_path, database, wide=True)
    assert _run(tmp_path, "run-operation", "replay_customer").success

    # Replay wrote to bronze, not to the snapshot — this is the step whose
    # apparent inaction the artifact's own header warns an operator about.
    assert _segments(database) == {"o1": "smb", "o2": None}

    assert _run(tmp_path, "build").success
    assert _segments(database) == {"o1": "smb", "o2": "startup"}


def test_the_conservation_audit_passes_when_a_version_predates_a_diverted_row(
    tmp_path: pathlib.Path,
) -> None:
    """The defect in its live form: a blocking audit stopping a correct build.

    ``c2`` is delivered with a segment the rule admits and dbt versions it.
    A later delivery of the same customer carries one the rule refuses, so it is
    diverted — and the snapshot keeps the earlier version open, because a
    framework closes a version when a new one arrives and reads no ending into
    a key its source query stopped producing. The counting form then read that
    one source row as surviving and as diverted at once and failed the build,
    before any replay ran, on data nothing is wrong with.

    Run here rather than only in tier 4 because the retained-and-still-open
    version is dbt's doing, not the harness's: the thing under test is the
    audit against what the framework actually leaves behind.
    """
    database = tmp_path / "warehouse.duckdb"
    _write_replay_project(tmp_path, database, wide=False)
    _seed_sources(database, "scd2_replay")
    _insert(
        database,
        (("crm__customers", _row({"customer_id": "c2", "segment": "ent", **_SIGNED_UP})),),
    )
    assert _run(tmp_path, "build").success

    # The same source row, re-delivered with a segment the rule refuses. It
    # wins the entity's `dedupe:`, so it is the survivor the audit counts.
    later = _row({"customer_id": "c2", "segment": "startup", **_SIGNED_UP})
    later["_ingested_at"] = datetime.datetime(2024, 6, 1)
    later["_load_id"] = "load-2"
    _insert(database, (("crm__customers", later),))

    result = _run(tmp_path, "build")
    nodes = {node.node.name: node.status for node in getattr(result.result, "results", ())}
    assert result.success, [
        node.message for node in getattr(result.result, "results", ()) if node.status != "success"
    ]
    # A green build is not the claim on its own: a project emitting no
    # conservation audit builds just as green. The audit has to have run, and
    # `pass` is dbt's word for a test whose query returned no rows.
    assert nodes.get("customer_conservation") == "pass", nodes


#: The one mapped field neither of the two deliveries above is about.
_SIGNED_UP = {"signed_up_at": "2023-05-02T00:00:00"}


def _row(values: dict[str, str]) -> dict[str, object]:
    """One bronze delivery: the mapped columns plus the ingestion metadata the
    contract requires (S-0033/D-21). The row identity is stable per row
    because replay re-delivers under it."""
    return {
        **values,
        "_ingested_at": datetime.datetime(2024, 1, 1),
        "_load_id": "load-1",
        "_source_row_id": values["customer_id"],
    }
