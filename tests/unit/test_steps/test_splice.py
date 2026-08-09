"""Tier 1 splicing (RFC 0017 §5.1, D50).

The substitution itself, isolated from the call sites that use it. Both
properties asserted here are what make Tier 1 "free at runtime": the result is
one expression, so the consuming model stays one query, and the substitution
is over an AST, so an argument is data rather than syntax.
"""

from __future__ import annotations

import pytest
from sqlglot import exp, parse_one

from bloomery.steps.splice import placeholders, splice

pytestmark = pytest.mark.unit


def test_a_macro_splices_its_arguments() -> None:
    """An AST substitution, not string interpolation — which is what keeps the
    splice inside the SQLGlot-only discipline (RFC 0004 D7) and lets the model
    stay one query."""
    spliced = splice(parse_one("LOWER(:col)"), {"col": exp.column("email")})
    assert spliced.sql() == "LOWER(email)"


def test_an_argument_the_body_ignores_is_not_an_error_here() -> None:
    """Agreement is the *call site's* refusal (D50), because only it knows
    whether an unused name is a typo or a column it legitimately has in
    scope. This function substitutes what it is given and nothing more."""
    spliced = splice(parse_one("UPPER(:a)"), {"a": exp.column("x"), "b": exp.column("y")})
    assert spliced.sql() == "UPPER(x)"


def test_a_placeholder_used_twice_gets_two_independent_nodes() -> None:
    """One tree cannot have two parents. Sharing the argument node between
    positions produced an expression that rendered once and then mutated its
    own other occurrence under any later transform."""
    argument = exp.column("v")
    spliced = splice(parse_one("COALESCE(:x, :x)"), {"x": argument})
    assert spliced.sql() == "COALESCE(v, v)"
    found = list(spliced.find_all(exp.Column))
    assert len(found) == 2
    assert found[0] is not found[1]


def test_an_unsubstituted_placeholder_survives_as_itself() -> None:
    """So the call site's agreement check has something to catch: a body whose
    placeholder nothing filled must not silently become valid SQL."""
    spliced = splice(parse_one("LOWER(:col)"), {})
    assert placeholders(spliced) == {"col"}


def test_placeholders_reads_the_macro_signature_off_the_body() -> None:
    """A manifest's `inputs` are relation-shaped — grain and required columns —
    which a macro has none of: it consumes columns, in an expression. The body
    is the only honest statement of what it needs."""
    assert placeholders(parse_one("similarity(:left, :right) * :weight")) == {
        "left",
        "right",
        "weight",
    }


def test_a_body_with_no_placeholders_has_an_empty_signature() -> None:
    assert placeholders(parse_one("CURRENT_DATE")) == frozenset()
