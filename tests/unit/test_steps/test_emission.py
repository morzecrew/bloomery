"""Step emission (RFC 0017 §5.8, D8/D16).

The wrapper is *generated Python*, which makes one assertion non-negotiable
and easy to forget: it has to parse. A golden pins the bytes, but a golden
would happily pin a syntax error — so the shape is checked with ``ast`` here,
where a failure says what is wrong.
"""

from __future__ import annotations

import ast

import pytest
from sqlglot import exp, parse_one

from bloomery.emit.base import EmittedArtifact
from bloomery.ir import Determinism, Lineage, StepIR, StepKind, canon
from support.compiling import compile_fixture

pytestmark = pytest.mark.unit


def wrappers() -> dict[str, str]:
    """The generated Python models only — a step also emits the D16
    cross-output consistency audits, which are ordinary SQL."""
    return {
        a.path: a.content
        for a in compile_fixture("step_resolution")
        if a.path.endswith(".py")
    }


# ....................... #
# One wrapper per output (D16)


def test_each_declared_output_gets_its_own_wrapper() -> None:
    assert sorted(wrappers()) == ["models/silver/customer.py", "models/silver/customer_xref.py"]


def test_each_wrapper_returns_its_own_output() -> None:
    content = wrappers()
    assert "return _blm_outputs['customer']" in content["models/silver/customer.py"]
    assert "return _blm_outputs['customer_xref']" in content["models/silver/customer_xref.py"]


def test_every_wrapper_asserts_all_declared_outputs() -> None:
    """A step that lies about one output should be caught wherever the run
    starts, so each wrapper's embedded manifest carries both (D16)."""
    for content in wrappers().values():
        assert "'customer'" in content
        assert "'customer_xref'" in content
        assert "_blm_assert(_blm_outputs, _blm_manifest)" in content


# ....................... #
# It is generated code, so it must actually be code


def test_every_wrapper_parses_as_python() -> None:
    for path, content in wrappers().items():
        ast.parse(content)  # raises SyntaxError with a line number if not
        assert path.endswith(".py")


def test_the_wrapper_binds_its_state_inside_the_function() -> None:
    """SQLMesh computes a Python model's dependencies by serializing the
    module globals the function references and rebuilding them in a fresh
    environment. A global holding a non-literal value — the `Decimal`
    parameter — failed to reconstruct there, so the model did not load at all:
    ``name 'Decimal' is not defined``, before anything ran. Nothing caught it
    because the wrapper was only ever `ast.parse`d, never loaded."""
    tree = ast.parse(wrappers()["models/silver/customer_xref.py"])
    # Every binding form, not just `ast.Assign`: the first version of this
    # collected plain assignments only, so reintroducing the defect as an
    # *annotated* assignment (`PARAMETERS: dict = {...}`) kept it green while
    # SQLMesh refused to load the model. The real check is the e2e tier, which
    # loads the emitted project through SQLMesh; this is the cheap sentinel.
    bound = {
        target.id
        for node in tree.body
        for target in (
            [*node.targets] if isinstance(node, ast.Assign)
            else [node.target] if isinstance(node, ast.AnnAssign)
            else []
        )
        if isinstance(target, ast.Name)
    }
    assert bound == set()


def test_the_contract_call_is_unconditional() -> None:
    """§5.4: non-optional and non-configurable *by construction*. The
    assertion sits in the function body at statement level — not behind an
    ``if``, a flag, or a ``try`` — and that is checked structurally rather
    than by grepping, because a grep would pass on a commented-out call."""
    tree = ast.parse(wrappers()["models/silver/customer.py"])
    (function,) = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    calls = [
        node
        for node in function.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "_blm_assert"
    ]
    assert len(calls) == 1


def test_the_wrapper_imports_the_contract_by_its_declared_path() -> None:
    """RFC 0018 D3: the shallow, declared path — not the module path.

    `assert_step_contract` is imported *by generated artifacts living in
    consumer repositories*, which made `bloomery.steps.contract` de-facto
    public API with nothing declaring it and no test protecting it: renaming
    the module would break every previously-generated wrapper at run time,
    with no compile-time warning anywhere. Promoting the name to
    `bloomery.steps.__all__` and emitting that path is what turns a rename
    into a visible diff. Checked structurally, since a grep would pass on the
    string appearing in a comment.

    The deep path keeps working — this adds a supported route rather than
    removing an unsupported one — and costs nothing: both spellings execute
    `bloomery/__init__.py`, measured at ~1015 modules either way, so the
    laziness RFC 0017 D22 records is unaffected.
    """
    for source in wrappers().values():
        imports = [
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.ImportFrom)
            and any(alias.name == "assert_step_contract" for alias in node.names)
        ]
        assert [node.module for node in imports] == ["bloomery.steps"]
        assert [alias.asname for node in imports for alias in node.names] == ["_blm_assert"]


def test_the_contract_is_declared_public_by_the_package_that_ships_it() -> None:
    """The other half of D3: emitting the shallow path would be a lie if the
    name were not declared there."""
    import bloomery.steps

    assert "assert_step_contract" in bloomery.steps.__all__
    assert callable(bloomery.steps.assert_step_contract)
    assert "assert_step_contract" in dir(bloomery.steps), (
        "the lazy loader hides names from dir() unless __dir__ lists them, and "
        "editors and tab-completion read dir()"
    )


def test_the_embedded_manifest_uses_spec_type_spellings() -> None:
    """The contract looks declared types up in a table, so a repr like
    ``StringType()`` would match nothing and turn a mandatory check into a
    silent no-op — the failure this assertion exists to prevent."""
    content = wrappers()["models/silver/customer.py"]
    assert "'type': 'string'" in content
    assert "'type': 'decimal(4,3)'" in content
    assert "StringType" not in content


def test_a_decimal_parameter_is_passed_as_a_decimal() -> None:
    """The IR holds values as text so canon bytes never meet a float, but the
    step body must be *called* with the real thing."""
    content = wrappers()["models/silver/customer.py"]
    assert "_blm_parameters = {'threshold': _blm_Decimal('0.9')}" in content
    assert "'threshold': '0.9'" not in content


def test_the_wrapper_imports_the_manifest_entrypoint() -> None:
    content = wrappers()["models/silver/customer.py"]
    assert "from platform_steps.resolve_customers import resolve" in content


def test_the_wrapper_is_deterministic() -> None:
    assert wrappers() == wrappers()


# ....................... #
# Tier 1 splices, and emits nothing of its own (§5.1)


def _macro(body: str) -> StepIR:
    return StepIR(
        ref="score",
        version=1,
        kind=StepKind.SQL_MACRO,
        determinism=Determinism.PURE,
        runtime_lock="sha256:x",
        lineage=Lineage.COLUMN,
        outputs=(),
        body=canon(parse_one(body)),
    )


def test_a_macro_emits_no_artifact_of_its_own() -> None:
    """Tier 1's whole point: it lives inside a consuming model's SELECT, so
    column-level lineage sees straight through it."""
    from bloomery.emit.base import EmitContext
    from bloomery.emit.steps import step_artifacts
    from bloomery.dialects import get_dialect
    from bloomery.ir import ProjectIR
    from bloomery.naming import DefaultNaming

    ctx = EmitContext(fingerprint="blm1:t", naming=DefaultNaming(), dialect=get_dialect("duckdb"))
    ir = ProjectIR(steps=(_macro("LOWER(:col)"),))
    blank = __import__("jinja2").Template("")
    assert step_artifacts(ir, ctx, blank, blank) == ()


def test_a_python_model_never_reaches_a_sql_harness() -> None:
    """A latent trap: a `python_model` wrapper is `ArtifactKind.MODEL` (RFC
    0008 D2 — artifacts are file-shaped text, so a Python model needs no new
    kind), so anything filtering models by *kind* alone hands Python source to
    a SQL engine.

    This drives the real harness rather than asserting the suffix and calling
    it proof: the first version of this test named ``execution.materialize``
    in its docstring, never called it, and passed with the filter reverted.
    """
    import duckdb

    from support.execution import materialize

    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE SCHEMA IF NOT EXISTS silver")
        connection.execute("CREATE SCHEMA IF NOT EXISTS bronze")
        connection.execute(
            "CREATE TABLE bronze.crm__customers AS SELECT 'crm' AS system, "
            "'c1' AS id, 'a@x' AS email, 'Ada' AS name"
        )
        # Raises if the harness hands DuckDB a `.py` model; creates nothing,
        # because a step body is platform code this harness never runs.
        # Raises if the harness hands DuckDB a `.py` model. The fixture's one
        # ordinary SQL model (`customer_raw`, the step's input) does run — the
        # assertion is that the two `.py` wrappers did not.
        materialize(connection, compile_fixture("step_resolution"))
        built = {
            row[0]
            for row in connection.execute("SELECT table_name FROM duckdb_tables()").fetchall()
        }
        # The seed table is mine;  is the fixture's one SQL
        # model. Neither  wrapper produced a relation, which is the point.
        assert built == {"crm__customers", "customer_raw"}
    finally:
        connection.close()


def test_a_declared_reference_attaches_its_audit_to_the_child_model() -> None:
    """An audit nothing references never runs: SQLMesh loads a bare `AUDIT` as
    a *model* audit, executed only where a model's `audits` names it. Nothing
    named it, so D40's blocking check was inert — and the test that "proved"
    it ran the extracted SELECT straight against DuckDB, with SQLMesh never in
    the loop."""
    content = wrappers()
    child = content["models/silver/customer_xref.py"]
    assert "audits=['step_customer_xref_canonical_id_references_customer']" in child
    # And the sibling it reads is declared, or SQLMesh resolves it to a
    # virtual-layer view that does not exist on a first plan — the audit
    # failing the run it exists to protect (D44).
    assert "depends_on=['silver.customer', 'silver.customer_raw']" in child
    # The parent holds no reference, so it carries neither.
    assert "audits=" not in content["models/silver/customer.py"]
    assert "depends_on=" not in content["models/silver/customer.py"]


def test_an_undeclared_coincidence_emits_no_audit() -> None:
    """Two outputs sharing a column name by accident must not earn a mutual
    pair of blocking audits asserting their key sets are identical — the
    failure that teaches people to ignore audits."""
    from bloomery.emit.base import EmitContext
    from bloomery.emit.steps import consistency_audits
    from bloomery.dialects import get_dialect
    from bloomery.ir import StepColumnIR, StepOutputIR
    from bloomery.naming import DefaultNaming
    from bloomery.typing import StringType

    def output(name: str) -> StepOutputIR:
        return StepOutputIR(
            name=name,
            relation=f"silver.{name}",
            grain=name,
            key=("id",),
            columns=(StepColumnIR(name="id", type=StringType(), required=True),),
        )

    step = StepIR(
        ref="s",
        version=1,
        kind=StepKind.PYTHON_MODEL,
        determinism=Determinism.PURE,
        runtime_lock="x",
        lineage=Lineage.COARSE,
        entrypoint="p.m:f",
        outputs=(output("customer"), output("product")),
    )
    ctx = EmitContext(fingerprint="blm1:t", naming=DefaultNaming(), dialect=get_dialect("duckdb"))
    assert consistency_audits(step, ctx) == ()


# ....................... #
# Tier 2 parameters (§10's open question, settled)


SQL_MANIFEST: dict[str, object] = {
    "ref": "scored",
    "version": 1,
    "kind": "sql_model",
    "determinism": "pure",
    "runtime_lock": "sha256:x",
    "outputs": {
        "out": {"grain": "g", "key": ["k"], "produces": {"k": {"type": "string"}}},
    },
}


def sql_step(body: str, parameters: dict[str, object], wired: str) -> str:
    """Compile a one-step Tier 2 project and return the emitted *query* — the
    text after the ``MODEL (...)`` block.

    The header is excluded deliberately: it carries a hex fingerprint, and an
    assertion like ``"7" in artifact`` passes against that hex without the
    substitution happening at all. Two of these tests did exactly that.
    """
    from bloomery import compile_project, load_project
    from bloomery.steps import StepManifest, StepRegistry

    manifest = StepManifest.model_validate(SQL_MANIFEST | {"parameters": parameters})
    project = load_project(
        {
            "entity_model": "spec_version: 1\nentities: {}\n",
            "steps": (
                "steps_version: 1\nsteps:\n  - use: scored@1\n"
                "    outputs: {out: silver.scored}\n"
                f"    parameters: {wired}\n"
            ),
        }
    )
    registry = StepRegistry({("scored", 1): manifest}, sql_bodies={("scored", 1): body})
    artifacts = compile_project(
        project, target="sqlmesh", dialect="duckdb", steps=registry
    )
    content = next(a.content for a in artifacts if a.path == "models/silver/scored.sql")
    _header, _, query = content.partition(");")
    return query


def test_a_sql_model_parameter_reaches_the_body() -> None:
    """The gap this settles: the value was carried in the IR — so it changed
    the fingerprint and restated the step — and never reached the SQL, which
    emitted a bare ``$threshold`` placeholder. An author wrote a parameter,
    got no parameter, and got no error."""
    sql = sql_step(
        "SELECT k FROM silver.src WHERE score > :threshold",
        {"threshold": {"type": "decimal(4,3)", "default": "0.85"}},
        "{threshold: 0.9}",
    )
    assert "0.9" in sql
    assert "threshold" not in sql


@pytest.mark.parametrize(
    ("declared", "wired", "expected"),
    [
        ("int", "{p: 7}", "7"),
        ("decimal", "{p: 0.25}", "0.25"),
        ("string", "{p: 'abc'}", "'abc'"),
        ("bool", "{p: true}", "TRUE"),
        ("date", "{p: '2024-01-01'}", "'2024-01-01'"),
    ],
)
def test_each_parameter_type_renders_its_own_literal(
    declared: str, wired: str, expected: str
) -> None:
    """The declared type decides the spelling. Inferring it from how the
    digits look is the guessing game D20 already refused on the Python side."""
    sql = sql_step("SELECT k FROM silver.src WHERE c = :p", {"p": {"type": declared}}, wired)
    assert expected in sql


def test_a_parameter_value_cannot_carry_sql_into_the_body() -> None:
    """The substitution builds an AST literal, so a value is data wherever it
    lands. String interpolation here would be RFC 0013's injection boundary
    reopened in the one place a spec value reaches emitted SQL."""
    sql = sql_step(
        "SELECT k FROM silver.src WHERE c = :p",
        {"p": {"type": "string"}},
        "{p: \"x' OR 1=1 --\"}",
    )
    # Present as *data*: one escaped string literal, still one comparison.
    assert "'x'' OR 1=1 --'" in sql
    tree = parse_one(sql, read="duckdb")
    assert tree is not None
    literals = [n.this for n in tree.find_all(exp.Literal) if n.is_string]
    assert literals == ["x' OR 1=1 --"]
    assert tree.find(exp.Or) is None


def test_a_placeholder_the_manifest_does_not_declare_is_refused() -> None:
    """Otherwise it emits unsubstituted and the engine meets an unknown macro
    variable — the silent-hole failure this whole change closes."""
    from bloomery.errors import StepError

    with pytest.raises(StepError, match="does not declare"):
        sql_step(
            "SELECT k FROM silver.src WHERE score > :nope",
            {"threshold": {"type": "decimal", "default": "0.85"}},
            "{threshold: 0.9}",
        )


def test_a_declared_parameter_the_body_never_uses_is_refused() -> None:
    """A parameter that changes the fingerprint and no SQL restates the step
    and reproduces identical data — the same "believing something is pinned
    that is not" D18(c) refused for a seed on a pure step."""
    from bloomery.errors import StepError

    with pytest.raises(StepError, match="never uses"):
        sql_step(
            "SELECT k FROM silver.src",
            {"threshold": {"type": "decimal", "default": "0.85"}},
            "{threshold: 0.9}",
        )


def test_a_placeholder_whose_parameter_has_no_value_is_refused() -> None:
    """Declared is not the same as *resolved*. A manifest parameter with no
    default that the wiring never sets resolves to nothing, so it reached emit
    as an unsubstituted ``$p`` — the same silent hole, one path over. The
    check has to compare the body against the values the step will actually
    run with, not against the names the manifest lists."""
    from bloomery.errors import StepError

    with pytest.raises(StepError, match="no value"):
        sql_step("SELECT k FROM silver.src WHERE c = :p", {"p": {"type": "int"}}, "{}")


def test_a_variant_parameter_in_a_body_is_refused_rather_than_guessed() -> None:
    """`variant` is semi-structured, and its literal spelling differs per
    engine — DuckDB, Postgres and Trino do not agree on how a JSON value is
    written. Rendering it as a string literal is a guess that compiles and
    compares wrongly, which is what RFC 0006 exists to refuse. Named as the
    escape hatch, not built: it needs a per-dialect literal hook."""
    from bloomery.errors import StepError

    with pytest.raises(StepError, match="variant"):
        sql_step(
            "SELECT k FROM silver.src WHERE c = :p",
            {"p": {"type": "variant", "default": "xyz"}},
            "{}",
        )


# ....................... #
# Quality rules on step outputs (D39: the `on_fail: fail` subset)


QUALITY_MANIFEST: dict[str, object] = {
    "ref": "resolve_customers",
    "version": 3,
    "kind": "python_model",
    "entrypoint": "platform_steps.resolve_customers:resolve",
    "determinism": "pure",
    "runtime_lock": "sha256:a91f",
    "outputs": {
        "customer": {
            "grain": "customer",
            "key": ["canonical_id"],
            "produces": {
                "canonical_id": {"type": "string", "required": True},
                "confidence": {"type": "decimal(4,3)"},
            },
        }
    },
}


def quality_step(on_fail: str = "fail") -> tuple[EmittedArtifact, ...]:
    from bloomery import compile_project, load_project
    from bloomery.steps import StepManifest, StepRegistry

    manifest = StepManifest.model_validate(QUALITY_MANIFEST)
    project = load_project(
        {
            "entity_model": "spec_version: 1\nentities: {}\n",
            "steps": (
                "steps_version: 1\nsteps:\n  - use: resolve_customers@3\n"
                "    outputs: {customer: silver.customer}\n"
                "    quality:\n"
                "      - {rule: expression, name: confident, "
                f'expr: "confidence >= 0.8", on_fail: {on_fail}}}\n'
                "    applies_to: {confident: customer}\n"
            ),
        }
    )
    registry = StepRegistry({("resolve_customers", 3): manifest})
    return compile_project(project, target="sqlmesh", dialect="duckdb", steps=registry)


def test_a_fail_rule_on_a_step_output_emits_a_blocking_audit() -> None:
    """D39's tractable subset. A step-produced relation has no SELECT to route
    rows into — the wrapper writes it in Python — but an audit reads the
    relation after the fact, which is exactly what `on_fail: fail` means."""
    audits = {a.path for a in quality_step() if a.path.startswith("audits/")}
    assert audits == {"audits/step_customer_confident.sql"}


def test_the_audit_is_named_by_the_model_that_owns_the_output() -> None:
    """SQLMesh loads a bare AUDIT as a *model* audit and runs it only where a
    model's `audits:` names it — the defect D42 records. An emitted audit
    nothing references never runs."""
    wrapper = next(
        a.content for a in quality_step() if a.path == "models/silver/customer.py"
    )
    assert "audits=['step_customer_confident']" in wrapper


def test_the_audit_returns_the_violating_rows() -> None:
    """An audit passes when its query returns nothing, so the body has to be
    the *violation*, not the assertion."""
    body = next(
        a.content for a in quality_step() if a.path == "audits/step_customer_confident.sql"
    )
    assert "NOT" in body or "<" in body
    assert "confidence" in body


@pytest.mark.parametrize(
    ("disposition", "expected"),
    [
        ("flag", "a python_model cannot carry"),
        ("quarantine", "which no step tier can lower"),
    ],
)
def test_a_routed_rule_on_a_python_model_output_is_refused(
    disposition: str, expected: str
) -> None:
    """`quality_step` wires a Tier 3 step, which is the tier neither
    disposition can reach — and the two are refused for *different* reasons
    (RFC 0051 §5.3), so each is matched on its own message rather than on the
    `on_fail: fail` both happen to name in their fix.

    `flag` fails on this tier only: a Tier 2 body is a SELECT and carries it.
    `quarantine` fails on every tier, because a step output has no ingestion
    key for a reject table and a wiring has no `quarantine:` block.
    """
    from bloomery.errors import StepError

    with pytest.raises(StepError, match=expected):
        quality_step(disposition)


def test_the_step_output_entity_carries_the_rule() -> None:
    """The rule lands on the synthesized entity rather than on a new StepIR
    field: `EntityIR.quality` already exists, so nothing about the IR's shape
    changes and no fingerprint moves for a project that declares no rule."""
    from bloomery import build_project_ir, load_project
    from bloomery.steps import StepManifest, StepRegistry

    manifest = StepManifest.model_validate(QUALITY_MANIFEST)
    project = load_project(
        {
            "entity_model": "spec_version: 1\nentities: {}\n",
            "steps": (
                "steps_version: 1\nsteps:\n  - use: resolve_customers@3\n"
                "    outputs: {customer: silver.customer}\n"
                "    quality:\n"
                '      - {rule: expression, name: confident, expr: "confidence >= 0.8", '
                "on_fail: fail}\n"
                "    applies_to: {confident: customer}\n"
            ),
        }
    )
    ir = build_project_ir(project, steps=StepRegistry({("resolve_customers", 3): manifest}))
    (entity,) = [e for e in ir.entities if e.name == "customer"]
    assert [rule.name for rule in entity.quality] == ["confident"]
    assert entity.quality[0].kind == "expression"


# ....................... #
# A flagged Tier 2 output (RFC 0051 §5.3)


FLAG_WIRING = (
    "steps_version: 1\nsteps:\n  - use: scored@1\n"
    "    outputs: {out: silver.scored}\n"
    "    quality:\n"
    '      - {rule: expression, name: keyed, expr: "k IS NOT NULL", on_fail: flag}\n'
    "    applies_to: {keyed: out}\n"
)

PLAIN_WIRING = (
    "steps_version: 1\nsteps:\n  - use: scored@1\n    outputs: {out: silver.scored}\n"
)


def _tier_two_model(wiring: str) -> str:
    from bloomery import compile_project, load_project
    from bloomery.steps import StepManifest, StepRegistry

    project = load_project(
        {"entity_model": "spec_version: 1\nentities: {}\n", "steps": wiring}
    )
    registry = StepRegistry(
        {("scored", 1): StepManifest.model_validate(SQL_MANIFEST)},
        sql_bodies={("scored", 1): "SELECT k FROM silver.src"},
    )
    artifacts = compile_project(project, target="sqlmesh", dialect="duckdb", steps=registry)
    return next(a.content for a in artifacts if a.path == "models/silver/scored.sql")


def test_a_flag_rule_puts_the_generated_columns_on_the_tier_two_relation() -> None:
    """The whole point of lifting the refusal: an author writes a rule and the
    relation carries the verdict. Read off the emitted model, not off the IR —
    the IR carried the rule before this shipped and emitted nothing."""
    model = _tier_two_model(FLAG_WIRING)
    assert "_quality_flags" in model
    assert "_quality_ok" in model
    # The rule's own predicate, negated by `verdict`, reaches the projection.
    assert "keyed" in model
    # The body is still in there, wrapped rather than replaced.
    assert "silver.src" in model


def test_an_unflagged_tier_two_output_is_unchanged() -> None:
    """D11's asymmetry: the two columns are conditional on the rule, not on
    the tier — so every existing step artifact stays byte-identical."""
    model = _tier_two_model(PLAIN_WIRING)
    assert "_quality_flags" not in model
    assert "_quality_ok" not in model
