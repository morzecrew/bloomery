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

from bloomery.emit.steps import macro_expression
from bloomery.ir import Determinism, Lineage, StepIR, StepKind, canon
from support.compiling import compile_fixture

pytestmark = pytest.mark.unit


def wrappers() -> dict[str, str]:
    return {a.path: a.content for a in compile_fixture("step_resolution")}


# ....................... #
# One wrapper per output (D16)


def test_each_declared_output_gets_its_own_wrapper() -> None:
    assert sorted(wrappers()) == ["models/silver/customer.py", "models/silver/customer_xref.py"]


def test_each_wrapper_returns_its_own_output() -> None:
    content = wrappers()
    assert 'return outputs["customer"]' in content["models/silver/customer.py"]
    assert 'return outputs["customer_xref"]' in content["models/silver/customer_xref.py"]


def test_every_wrapper_asserts_all_declared_outputs() -> None:
    """A step that lies about one output should be caught wherever the run
    starts, so each wrapper's embedded manifest carries both (D16)."""
    for content in wrappers().values():
        assert '"customer"' in content
        assert '"customer_xref"' in content
        assert "assert_step_contract(outputs, MANIFEST)" in content


# ....................... #
# It is generated code, so it must actually be code


def test_every_wrapper_parses_as_python() -> None:
    for path, content in wrappers().items():
        ast.parse(content)  # raises SyntaxError with a line number if not
        assert path.endswith(".py")


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
        and node.value.func.id == "assert_step_contract"
    ]
    assert len(calls) == 1


def test_the_embedded_manifest_uses_spec_type_spellings() -> None:
    """The contract looks declared types up in a table, so a repr like
    ``StringType()`` would match nothing and turn a mandatory check into a
    silent no-op — the failure this assertion exists to prevent."""
    content = wrappers()["models/silver/customer.py"]
    assert '"type": "string"' in content
    assert '"type": "decimal(4,3)"' in content
    assert "StringType" not in content


def test_a_decimal_parameter_is_passed_as_a_decimal() -> None:
    """The IR holds values as text so canon bytes never meet a float, but the
    step body must be *called* with the real thing."""
    content = wrappers()["models/silver/customer.py"]
    assert 'PARAMETERS = {"threshold": Decimal("0.9")}' in content
    assert '"threshold": "0.9"' not in content


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


def test_a_macro_splices_its_arguments() -> None:
    """An AST substitution, not string interpolation — which is what keeps the
    splice inside the SQLGlot-only discipline (RFC 0004 D7) and lets the model
    stay one query."""
    spliced = macro_expression(_macro("LOWER(:col)"), {"col": exp.column("email")})
    assert spliced.sql() == "LOWER(email)"


def test_a_macro_argument_the_body_ignores_is_not_an_error() -> None:
    """The caller supplies the columns in scope; a macro may use fewer than it
    is offered."""
    spliced = macro_expression(_macro("UPPER(:a)"), {"a": exp.column("x"), "b": exp.column("y")})
    assert spliced.sql() == "UPPER(x)"


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
    assert step_artifacts(ir, ctx, __import__("jinja2").Template("")) == ()


def test_a_python_model_never_reaches_a_sql_harness() -> None:
    """A latent trap worth pinning: a `python_model` wrapper is
    `ArtifactKind.MODEL` (RFC 0008 D2 — artifacts are file-shaped text, so a
    Python model needs no new kind), which means anything filtering models by
    *kind* alone would hand Python source to a SQL engine. The execution
    harness filters on the suffix; this asserts the suffix is there to filter
    on."""
    for path, content in wrappers().items():
        assert path.endswith(".py")
        assert not content.lstrip().startswith("MODEL (")
