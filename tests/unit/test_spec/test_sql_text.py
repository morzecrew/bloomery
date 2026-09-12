"""Authored SQL is proved parseable at load (``SqlText``).

Every field here used to reach ``sqlglot.parse_one`` unguarded somewhere
downstream — the IR builder, a guardrail, an emitter — so an unparseable
expression left the compile boundary as a raw SQLGlot exception rather than as
a ``BloomeryError``. The refusal belongs at the parse stage: it is the only
place that knows the authored address, and one authored field feeds up to three
of those call sites.
"""

from __future__ import annotations

import re

import pytest

from sqlglot import exp, parse_one

from bloomery import load_catalog, load_project
from bloomery.errors import SpecParseError
from support.compiling import FIXTURES

pytestmark = pytest.mark.unit

#: The two ways SQLGlot refuses, and they are **not** one class.
#: ``TokenError`` is ``ParseError``'s *sibling* under ``SqlglotError``, so a
#: handler narrowed to ``ParseError`` passes the second case and fails the
#: first — which is how this defect survived the door that was already
#: guarded. Every refusal below is asserted against both.
UNPARSEABLE = pytest.mark.parametrize(
    "expr",
    ["SELECT 'abc", "line_total /"],
    ids=["tokenizer", "parser"],
)


def catalog(*, recipe: str = "line_total / quantity", template: str = "price * qty") -> str:
    return f"""
catalog_version: 1
vertical: ecom_retail
canonical_fields:
  unit_price:
    entity: order_item
    type: decimal(12,4)
    recipes:
      - {{id: from_total, requires: [line_total, quantity], expr: "{recipe}"}}
metric_templates:
  gross_revenue:
    requires: [unit_price]
    grain: order_item
    additivity: additive
    agg: sum
    expr: "{template}"
"""


def metrics(*, expr: str = "order_id", derived: str = "a + b") -> str:
    return f"""
metrics_version: 1
metrics:
  order_count:
    grain: order
    additivity: additive
    agg: count
    expr: "{expr}"
  growth:
    additivity: non_additive
    derived:
      expr: "{derived}"
      inputs:
        a: {{metric: order_count}}
        b: {{metric: order_count, offset: {{window: 1 month}}}}
"""


# ....................... #
# The four doors


@UNPARSEABLE
def test_a_recipe_expression_must_parse(expr: str) -> None:
    with pytest.raises(SpecParseError) as excinfo:
        load_catalog(catalog(recipe=expr))
    assert "not parseable SQL" in str(excinfo.value)
    assert excinfo.value.source_path == (
        "catalog: canonical_fields.unit_price.recipes[0].expr"
    )


@UNPARSEABLE
def test_a_metric_template_expression_must_parse(expr: str) -> None:
    """Parsed whether or not anything instantiates the template.

    Reachability is not a licence: a template nobody uses today is used by the
    metric somebody adds tomorrow, and "accepted because nothing reached it"
    turns that addition into the change that broke the build.
    """
    with pytest.raises(SpecParseError) as excinfo:
        load_catalog(catalog(template=expr))
    assert excinfo.value.source_path == "catalog: metric_templates.gross_revenue.expr"


@UNPARSEABLE
def test_a_metric_expression_must_parse(expr: str) -> None:
    with pytest.raises(SpecParseError) as excinfo:
        load_project({"metrics": metrics(expr=expr)})
    assert excinfo.value.source_path == "metrics: metrics.order_count.expr"


@UNPARSEABLE
def test_a_derived_metric_expression_must_parse(expr: str) -> None:
    with pytest.raises(SpecParseError) as excinfo:
        load_project({"metrics": metrics(derived=expr)})
    assert excinfo.value.source_path == "metrics: metrics.growth.derived.expr"


# ....................... #
# What the refusal is worth


def test_two_bad_expressions_in_one_document_are_one_batched_refusal() -> None:
    """RFC 0002 D6, which is the reason this lives at the parse stage: an
    author fixing one typo at a time is the failure mode the batching exists
    to remove, and a validator that raised per field would reintroduce it."""
    with pytest.raises(SpecParseError) as excinfo:
        load_catalog(catalog(recipe="a +", template="b +"))
    paths = [error.source_path for error in excinfo.value.collected]
    assert paths == [
        "catalog: canonical_fields.unit_price.recipes[0].expr",
        "catalog: metric_templates.gross_revenue.expr",
    ]


def test_an_expression_too_deep_to_parse_is_refused_rather_than_crashing() -> None:
    """SQLGlot's parser recurses on nesting depth, so several hundred nested
    parentheses exhaust the stack instead of raising a SQLGlot error.

    Pre-existing — the same expression crashed the IR builder before this
    validator existed, and it still crashes every other ``parse_one`` in the
    tree. What changed is that these four fields are now parsed *here* first,
    so this is the one place that can stop it, and a boundary that is total
    except for one input class is not total.
    """
    deep = "(" * 400 + "line_total" + ")" * 400
    with pytest.raises(SpecParseError) as excinfo:
        load_catalog(catalog(recipe=deep))
    assert "not parseable SQL" in str(excinfo.value)


def test_a_parseable_expression_still_loads() -> None:
    """The control. A validator that refused everything would pass every test
    above and be caught only by the corpus — this is the assertion that says
    the refusal is about the text rather than about the field existing."""
    loaded = load_catalog(catalog())
    assert loaded.canonical_fields["unit_price"].recipes[0].expr == "line_total / quantity"
    assert loaded.metric_templates["gross_revenue"].expr == "price * qty"


def test_the_validator_returns_the_authored_text_byte_for_byte() -> None:
    """A validator on this path is free to *rewrite* what it validates, and
    one that did would be invisible.

    The authored string is what reaches the IR and therefore the project
    fingerprint (RFC 0003), so normalising it here — returning
    ``parse_one(expr).sql()`` instead of ``expr`` — would move every
    fingerprint in every project. Sabotaged exactly that way, the whole
    default test profile stayed green: the fixture corpus is already written in
    SQLGlot's own spelling, so the rewrite is a no-op on every input the suite
    owns. This test is the one that is not.
    """
    # SQLGlot renders this as `line_total / quantity`. Surrounding whitespace
    # is deliberately *not* part of the case: `SpecModel` sets
    # `str_strip_whitespace`, so a `.strip()` here is a true no-op rather than
    # an undetected rewrite — a second guard, found by asking why that mutant
    # survived instead of assuming a blind test.
    authored = "line_total/quantity"
    loaded = load_catalog(catalog(recipe=authored))
    assert loaded.canonical_fields["unit_price"].recipes[0].expr == authored


def test_a_second_statement_is_refused() -> None:
    """Parsing is necessary and not sufficient.

    ``a; b`` *parses* — SQLGlot returns a ``Block`` rather than raising — so an
    earlier revision of this file pinned it as deliberately accepted, on the
    reasoning that refusing it would be a new refusal rather than a crash fix.
    That was wrong on its own terms. Every field here is spliced into a larger
    expression rather than executed, so the trailing statement lands *inside*
    the cast the column is wrapped in:

        CAST(total / qty; DROP TABLE x AS DECIMAL(12, 4))

    which SQLGlot will not re-parse, so it crashed the emitter with the same
    raw ``ParseError`` this validator exists to prevent. The quality guardrail
    reached the same refusal from the same reasoning for an expression rule
    (RFC 0016 D95).
    """
    with pytest.raises(SpecParseError) as excinfo:
        load_catalog(catalog(recipe="total / qty; DROP TABLE x"))
    assert "more than one statement" in str(excinfo.value)
    assert excinfo.value.source_path == "catalog: canonical_fields.unit_price.recipes[0].expr"


def test_a_second_statement_is_refused_on_every_field() -> None:
    """One door per field, so each is asserted rather than assumed from the
    shared annotation — a field that lost the annotation would pass the test
    above and fail here."""
    with pytest.raises(SpecParseError):
        load_catalog(catalog(template="a; b"))
    with pytest.raises(SpecParseError):
        load_project({"metrics": metrics(expr="a; b")})
    with pytest.raises(SpecParseError):
        load_project({"metrics": metrics(derived="a; b")})


@pytest.mark.parametrize(
    ("statement", "named"),
    [("SELECT 1", "SELECT"), ("INSERT INTO t VALUES (1)", "INSERT"), ("DELETE FROM t", "DELETE")],
)
def test_a_statement_is_refused(statement: str, named: str) -> None:
    """A `Block` was the special case; a statement is the general one.

    `SELECT 1` parses to a perfectly good `Select` and splices to
    `CAST(SELECT 1 AS DECIMAL(12, 4))`, which fails exactly the way `a; b`
    did. The scalar check is a re-parse into a `Condition` — SQLGlot's own
    name for the expression grammar — and the message names the statement it
    found, because "not an expression" without saying what it *is* leaves the
    author guessing (PR #111 review).
    """
    with pytest.raises(SpecParseError) as excinfo:
        load_catalog(catalog(recipe=statement))
    assert f"a {named} statement, not an expression" in str(excinfo.value)


def test_the_scalar_check_does_not_replace_the_block_check() -> None:
    """Both, not one.

    The review that produced the scalar check also asked for the `Block` check
    to be removed in its favour. It cannot be: `parse_one("a; b",
    into=exp.Condition)` returns a `Block` rather than raising, so the scalar
    check alone admits the multi-statement case. Asserted on SQLGlot directly
    rather than through the validator, because that is the fact the two-check
    structure rests on — and if a future SQLGlot makes the scalar check
    sufficient, this is the test that says so.
    """
    assert isinstance(parse_one("a; b", into=exp.Condition), exp.Block)


def test_every_expression_the_corpus_owns_is_a_scalar_expression() -> None:
    """The scalar check is a *narrowing*, so the thing worth pinning is what
    it does not narrow away.

    Every `expr:` authored in the fixture corpus, parsed the way the validator
    parses it. A refusal here means a legal expression was made illegal, which
    no unit test over hand-written inputs would catch.
    """
    authored = set()
    for path in (FIXTURES).rglob("*.yaml"):
        text = path.read_text()
        authored.update(re.findall(r'expr:\s*"([^"]+)"', text))
        authored.update(re.findall(r"expr:\s*'([^']+)'", text))

    assert len(authored) > 20, "corpus scan found almost nothing — the regex stopped matching"
    for expression in sorted(authored):
        parse_one(expression, into=exp.Condition)
