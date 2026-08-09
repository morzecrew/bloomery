"""The tenant ``steps:`` document (RFC 0017 §5.2) — wiring, and nothing else.

The most important assertions here are about what the surface *cannot*
express: there is no field that holds a body and no field that names a file,
which is what keeps a tenant spec from becoming an arbitrary-code-execution
surface (§5.3, D3). A test that pins an absence is the only way that property
stays true as the model grows.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from bloomery import load_project
from bloomery.errors import SpecParseError
from bloomery.spec.steps import StepSet

pytestmark = pytest.mark.unit

WIRING = """
steps_version: 1
steps:
  - use: resolve_customers@3
    inputs: {raw: silver.customer_raw}
    outputs: {customer: silver.customer, customer_xref: silver.customer_xref}
    parameters: {threshold: 0.9}
"""


def _steps(text: str = WIRING) -> StepSet:
    project = load_project({"entity_model": "spec_version: 1\nentities: {}\n", "steps": text})
    assert project.steps is not None
    return project.steps


def test_the_worked_wiring_parses_and_splits_the_use() -> None:
    (wiring,) = _steps().steps
    assert (wiring.ref, wiring.version) == ("resolve_customers", 3)
    assert wiring.outputs == {"customer": "silver.customer", "customer_xref": "silver.customer_xref"}


def test_a_parameter_arrives_as_a_decimal_never_a_float() -> None:
    (wiring,) = _steps().steps
    assert wiring.parameters["threshold"] == Decimal("0.9")
    assert not isinstance(wiring.parameters["threshold"], float)


def test_the_wiring_surface_cannot_carry_a_body() -> None:
    """The security property is the *absence* of a surface, not validation of
    one — so it is asserted as an absence. ``extra="forbid"`` turns each of
    these into a parse error rather than an ignored key."""
    for smuggled in ("body", "entrypoint", "path", "module", "code", "sql", "python"):
        text = WIRING.replace(
            "    parameters: {threshold: 0.9}\n", f"    {smuggled}: something\n"
        )
        with pytest.raises(SpecParseError, match="Extra inputs are not permitted"):
            _steps(text)


def test_a_use_that_is_not_ref_at_version_is_refused() -> None:
    for bad in ("resolve_customers", "resolve_customers@", "@3", "../x@1", "resolve@0"):
        with pytest.raises(SpecParseError):
            _steps(WIRING.replace("resolve_customers@3", bad))


def test_wiring_one_step_twice_is_refused() -> None:
    """Two wirings of one step are a copy-paste or a fork attempt (§5.7);
    both want the same answer, and neither is resolved by picking one."""
    doubled = WIRING + """  - use: resolve_customers@3
    outputs: {customer: silver.other}
"""
    with pytest.raises(SpecParseError, match="wired more than once"):
        _steps(doubled)


def test_wiring_two_versions_of_one_step_is_refused() -> None:
    """Keyed on ``use``, ``@3`` and ``@4`` were two different keys and both
    compiled — while everything downstream keys on ``ref`` alone (D24: steps
    diff by ref, the DAG node is ``step.<ref>``). ``{step.ref: step}`` in
    ``plan/diff.py`` therefore kept exactly one of them, silently dropping the
    other's outputs from the plan that is supposed to restate them.

    Running two versions side by side is also the fork §5.7 refuses: a version
    bump is a step *changing*, not a second step appearing.
    """
    forked = WIRING + """  - use: resolve_customers@4
    outputs: {customer: silver.customer_v4}
"""
    with pytest.raises(SpecParseError, match="wired more than once"):
        _steps(forked)


def test_a_step_must_bind_at_least_one_output() -> None:
    with pytest.raises(SpecParseError):
        _steps(WIRING.replace(
            "    outputs: {customer: silver.customer, customer_xref: silver.customer_xref}\n",
            "    outputs: {}\n",
        ))


# ....................... #
# Quality rules on outputs (§5.2 — the RFC 0016 pairing)


QUALITY = """
steps_version: 1
steps:
  - use: resolve_customers@3
    outputs: {customer: silver.customer}
    quality:
      - {rule: expression, name: confident, expr: "confidence >= 0.8", on_fail: flag}
    applies_to: {confident: customer}
"""


def test_a_quality_rule_attaches_to_a_named_output() -> None:
    (wiring,) = _steps(QUALITY).steps
    assert wiring.quality[0].name == "confident"
    assert wiring.applies_to == {"confident": "customer"}


def test_a_rule_without_applies_to_is_refused() -> None:
    """An entity's ``quality:`` has one relation to mean; a step has several,
    so "on this step" does not lower to anything."""
    with pytest.raises(SpecParseError, match="do not say which output"):
        _steps(QUALITY.replace("    applies_to: {confident: customer}\n", ""))


def test_applies_to_pointing_at_an_unbound_output_is_refused() -> None:
    with pytest.raises(SpecParseError, match="does not bind"):
        _steps(QUALITY.replace("applies_to: {confident: customer}", "applies_to: {confident: nope}"))


def test_applies_to_naming_an_undeclared_rule_is_refused() -> None:
    with pytest.raises(SpecParseError, match="does not declare"):
        _steps(
            QUALITY.replace(
                "applies_to: {confident: customer}",
                "applies_to: {confident: customer, ghost: customer}",
            )
        )


# ....................... #
# The sixth spec kind (RFC 0002 §5.2)


def test_two_step_documents_are_refused() -> None:
    with pytest.raises(SpecParseError, match="at most one StepSet document"):
        load_project(
            {
                "entity_model": "spec_version: 1\nentities: {}\n",
                "steps_a": WIRING,
                "steps_b": WIRING,
            }
        )


def test_a_project_without_steps_has_none() -> None:
    project = load_project({"entity_model": "spec_version: 1\nentities: {}\n"})
    assert project.steps is None


def test_the_unknown_kind_message_names_steps_version() -> None:
    with pytest.raises(SpecParseError, match="steps_version"):
        load_project({"entity_model": "spec_version: 1\nentities: {}\n", "x": "nothing: 1\n"})


def test_a_bound_relation_may_not_carry_syntax() -> None:
    """These strings reach *generated source*. A binding of
    ``x", print("…"))\\n@model("y`` produced a wrapper that parsed, carried a
    second decorator and executed at model import — the injection D25 claimed
    to have closed, still open through the output binding."""
    payloads = [
        'x", print("PWNED"))\n@model("y',
        "a'; import os",
        "a\nb",
        'a"b',
        "a b",
        "../escape",
    ]
    for payload in payloads:
        doc = (
            "steps_version: 1\nsteps:\n  - use: resolve_customers@3\n"
            "    outputs: {customer: %r}\n" % payload
        )
        with pytest.raises(SpecParseError):
            _steps(doc)


def test_an_ordinary_namespaced_relation_is_accepted() -> None:
    (wiring,) = _steps(
        "steps_version: 1\nsteps:\n  - use: resolve_customers@3\n"
        "    outputs: {customer: warehouse.silver.customer}\n"
    ).steps
    assert wiring.outputs["customer"] == "warehouse.silver.customer"
