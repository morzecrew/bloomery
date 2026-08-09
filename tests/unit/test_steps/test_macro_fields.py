"""Tier 1 at the call site: a macro spliced into a mapped field (D50).

Tier 1's promise is that it costs nothing at run time — the body is spliced
into the consuming SELECT, so the model stays one query and column-level
lineage sees straight through it. That promise is only true if the splice
happens at *lowering*, which is what these assert: the macro is part of
``ColumnIR.expr`` by the time anything downstream looks, and no artifact of
its own is ever emitted.

The refusals are the same shape D47 settled for Tier 2, deliberately: the
body's placeholders and what the call site supplies must name one set.
"""

from __future__ import annotations

import pytest
from sqlglot import exp

from bloomery import build_project_ir, compile_project, load_project
from bloomery.errors import SpecParseError, StepDeterminismError, StepError, UnknownStep
from bloomery.steps import StepManifest, StepRegistry

pytestmark = pytest.mark.unit

ENTITY_MODEL = """
spec_version: 1
entities:
  customer:
    grain: one row per customer
    key: [customer_id]
    fields:
      customer_id: {type: string, required: true}
      email_domain: {type: string}
"""


def manifest(**overrides: object) -> StepManifest:
    base: dict[str, object] = {
        "ref": "extract_domain",
        "version": 1,
        "kind": "sql_macro",
        "determinism": "pure",
        "runtime_lock": "sha256:beef",
        "accepts": {"email": "string"},
        "outputs": {
            "value": {"grain": "row", "key": ["v"], "produces": {"v": {"type": "string"}}}
        },
    }
    return StepManifest.model_validate(base | overrides)


def registry(body: str = "SPLIT_PART(:email, '@', 2)", **overrides: object) -> StepRegistry:
    return StepRegistry(
        {("extract_domain", 1): manifest(**overrides)},
        macro_bodies={("extract_domain", 1): body},
    )


def mapping(field: str) -> str:
    return (
        "mapping_version: 1\ntarget: customer\nsource: bronze.crm__customers\n"
        'key:\n  customer_id: {from: "$.id"}\n'
        f"fields:\n  email_domain:\n{field}"
    )


def build(field: str, reg: StepRegistry | None = None):  # noqa: ANN201 — ProjectIR
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": mapping(field)})
    return build_project_ir(project, steps=reg if reg is not None else registry())


CALL = '    step: extract_domain@1\n    from: {email: "$.email"}\n'


def domain_expr(ir: object) -> str:
    (entity,) = [e for e in ir.entities if e.name == "customer"]  # type: ignore[attr-defined]
    (column,) = [c for c in entity.columns if c.name == "email_domain"]
    return column.expr.sql


# ....................... #
# The splice


def test_a_macro_body_is_spliced_into_the_consuming_column() -> None:
    """The whole of Tier 1: the column's expression *is* the macro body with
    its argument substituted, so the model stays one query."""
    sql = domain_expr(build(CALL))
    assert "SPLIT_PART" in sql
    assert "@" in sql
    assert ":email" not in sql and "$email" not in sql


def test_the_macro_emits_no_artifact_of_its_own() -> None:
    """Tier 1 is free at run time because it produces no model. A macro that
    emitted one would be a Tier 2 step wearing the wrong kind."""
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": mapping(CALL)})
    artifacts = compile_project(
        project, target="sqlmesh", dialect="duckdb", steps=registry()
    )
    paths = {a.path for a in artifacts}
    assert not any("extract_domain" in path for path in paths)
    assert "models/silver/customer.sql" in paths


def test_the_spliced_column_reads_the_bound_source_path() -> None:
    """Lineage sees through the macro because the argument is the ordinary
    extraction — the same node a direct `from:` would have produced.

    Asserted on the AST, not on the text: ``":email" in sql`` is true of the
    *unsubstituted* body too, so the obvious spelling of this test passed
    with the splice disabled entirely.
    """
    ir = build(CALL)
    (entity,) = [e for e in ir.entities if e.name == "customer"]
    (column,) = [c for c in entity.columns if c.name == "email_domain"]
    tree = column.expr.ast()
    assert tree.find(exp.Placeholder) is None
    assert [c.name for c in tree.find_all(exp.Column)] == ["email"]


def test_a_parameter_is_substituted_as_a_typed_literal() -> None:
    """A value authored in a spec reaches emitted SQL here, so it is built as
    an AST literal rather than interpolated — the injection boundary Tier 2
    already had to hold (D47)."""
    ir = build(
        '    step: extract_domain@1\n    from: {email: "$.email"}\n'
        "    parameters: {part: 2}\n",
        registry(
            body="SPLIT_PART(:email, '@', :part)",
            parameters={"part": {"type": "int", "default": 2}},
        ),
    )
    assert "2" in domain_expr(ir)


def test_a_parameter_value_cannot_carry_sql_into_the_body() -> None:
    ir = build(
        '    step: extract_domain@1\n    from: {email: "$.email"}\n'
        "    parameters: {sep: \"x' OR 1=1 --\"}\n",
        registry(
            body="SPLIT_PART(:email, :sep, 2)",
            parameters={"sep": {"type": "string", "default": "@"}},
        ),
    )
    sql = domain_expr(ir)
    # One escaped string literal, not a second argument and not a comment.
    assert "'x'' OR 1=1 --'" in sql
    assert "OR 1=1" not in sql.replace("'x'' OR 1=1 --'", "")


# ....................... #
# Agreement between the body and the call site


def test_a_body_referring_to_something_undeclared_is_refused() -> None:
    """The manifest is where a macro's body and its declaration meet, so a
    disagreement there is the platform's bug — caught once, rather than
    handed to every call site as a puzzle."""
    with pytest.raises(StepError, match="declares neither in accepts"):
        build(CALL, registry(body="SPLIT_PART(:email, :missing, 2)"))


def test_a_declared_name_the_body_never_uses_is_refused() -> None:
    """The other direction: a call site would be made to supply it for
    nothing."""
    with pytest.raises(StepError, match="never refers"):
        build(CALL, registry(accepts={"email": "string", "spare": "string"}))


def test_a_call_site_that_does_not_bind_what_the_macro_accepts_is_refused() -> None:
    """The message names the expected signature, which is what declaring it
    buys — before D51 the call site could only be told a placeholder was
    unfilled, never what the macro wanted."""
    with pytest.raises(StepError, match="accepts; bind it under from"):
        build("    step: extract_domain@1\n    from: {}\n")


def test_a_call_site_binding_something_unaccepted_is_refused() -> None:
    """A typo here is otherwise completely silent — the column would simply
    ignore a source path the mapping says it reads."""
    with pytest.raises(StepError, match="does not accept"):
        build('    step: extract_domain@1\n    from: {email: "$.email", nope: "$.x"}\n')


def test_a_name_declared_as_both_a_column_and_a_parameter_is_refused() -> None:
    """Refused at the *manifest* now, not at the call site: one placeholder
    cannot be filled by two things, and that is decidable from the
    declaration alone."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="cannot be filled by two things"):
        manifest(parameters={"email": {"type": "string", "default": "x"}})


# ....................... #
# Which steps may be spliced at all


def test_splicing_a_step_that_writes_a_relation_is_refused() -> None:
    """A `sql_model` or `python_model` produces a table, not a value. Naming
    one here is a tier confusion the message has to say out loud."""
    with pytest.raises(StepError, match="cannot be spliced"):
        # `accepts` is refused on a non-macro at the manifest, so a step that
        # writes a relation reaches the splice site without one — which is the
        # shape this refusal has to catch.
        build(CALL, registry(kind="sql_model", accepts={}))


def test_a_nondeterministic_macro_is_refused() -> None:
    """A macro is re-evaluated on every backfill by construction — it lives
    inside the entity's SELECT — so anything but `pure` makes a restatement
    disagree with the run it replaces."""
    with pytest.raises(StepDeterminismError, match="determinism"):
        build(CALL, registry(determinism="nondeterministic"))


def test_an_unknown_macro_ref_is_refused_naming_what_exists() -> None:
    with pytest.raises(UnknownStep):
        build('    step: nosuch@1\n    from: {email: "$.email"}\n')


def test_a_macro_with_no_registry_body_is_refused() -> None:
    """The registry carries manifests and bodies separately, so a manifest
    without its body compiles to a column that lowers to nothing at all."""
    empty = StepRegistry({("extract_domain", 1): manifest()})
    with pytest.raises(StepError, match="no macro body"):
        build(CALL, empty)


# ....................... #
# The surface itself


def test_the_field_surface_cannot_carry_a_body() -> None:
    """The security property is the absence of a surface, here as everywhere:
    a mapping may name a macro, never supply one."""
    for smuggled in ("body", "expr", "sql", "path"):
        with pytest.raises(SpecParseError, match="Extra inputs are not permitted"):
            load_project(
                {
                    "entity_model": ENTITY_MODEL,
                    "mapping": mapping(
                        f'    step: extract_domain@1\n    from: {{email: "$.email"}}\n'
                        f"    {smuggled}: something\n"
                    ),
                }
            )


def test_the_column_expression_is_a_single_expression() -> None:
    """Not a subquery, not a join — the property that keeps the model one
    query and lineage column-level."""
    ir = build(CALL)
    (entity,) = [e for e in ir.entities if e.name == "customer"]
    (column,) = [c for c in entity.columns if c.name == "email_domain"]
    tree = column.expr.ast()
    assert tree.find(exp.Select) is None


# ....................... #
# The chain form: Tier 0 and Tier 1 composed on one field (D51)


def chain_registry(**overrides: object) -> StepRegistry:
    base: dict[str, object] = {"accepts": {"v": "string"}}
    return registry(body="SPLIT_PART(:v, '@', 2)", **(base | overrides))


CHAIN = "    from: \"$.email\"\n    transform: [lower, {step: extract_domain@1}, trim]\n"


def test_a_macro_composes_with_tier_0_transforms_in_one_chain() -> None:
    """The reason the chain form exists at all: the field form binds a raw
    source path, so it cannot run a whitelist transform before the macro."""
    sql = domain_expr(build(CHAIN, chain_registry()))
    assert "LOWER" in sql
    assert "SPLIT_PART" in sql
    assert "TRIM" in sql


def test_the_running_value_fills_the_macro_s_single_accepted_column() -> None:
    ir = build(CHAIN, chain_registry())
    (entity,) = [e for e in ir.entities if e.name == "customer"]
    (column,) = [c for c in entity.columns if c.name == "email_domain"]
    tree = column.expr.ast()
    assert tree.find(exp.Placeholder) is None
    # The macro wraps the *lowered* value, not the raw extraction.
    assert "LOWER" in tree.sql()


def test_a_macro_accepting_two_columns_cannot_be_a_chain_link() -> None:
    """A chain carries exactly one running value, so a two-column macro would
    silently drop an argument. Refused, naming the surface that fits."""
    with pytest.raises(StepError, match="cannot be a link in a transform chain"):
        build(
            CHAIN,
            registry(
                body="similarity(:a, :b)", accepts={"a": "string", "b": "string"}
            ),
        )


def test_the_chain_is_typechecked_around_the_macro() -> None:
    """The point of declaring a signature (D51): the run before the macro is
    checked against what it accepts. Here `to_int` makes the running value an
    int where the macro declares it takes a string."""
    from bloomery.errors import TypeCheckError

    bad = "    from: \"$.email\"\n    transform: [to_int, {step: extract_domain@1}]\n"
    with pytest.raises(TypeCheckError):
        build(bad, chain_registry())


def test_the_macro_s_declared_output_type_starts_the_rest_of_the_chain() -> None:
    """And the other half: after the macro, checking resumes from what its
    `produces` declares rather than from whatever came in."""
    from bloomery.errors import TypeCheckError

    # `upper` takes a string; the macro declares it produces an int here, so
    # the suffix is checked against the *declared* output and refuses.
    numeric = registry(
        body="LENGTH(:v)",
        accepts={"v": "string"},
        outputs={"value": {"grain": "row", "key": ["v"], "produces": {"v": {"type": "int"}}}},
    )
    with pytest.raises(TypeCheckError):
        build("    from: \"$.email\"\n    transform: [{step: extract_domain@1}, upper]\n", numeric)


def test_a_chain_step_is_either_a_transform_or_a_step_never_both() -> None:
    with pytest.raises(SpecParseError, match="never both"):
        load_project(
            {
                "entity_model": ENTITY_MODEL,
                "mapping": mapping(
                    "    from: \"$.email\"\n"
                    "    transform: [{name: lower, step: extract_domain@1}]\n"
                ),
            }
        )
