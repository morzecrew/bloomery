"""Authored SQL is proved parseable at load (``SqlText``).

Every field here used to reach ``sqlglot.parse_one`` unguarded somewhere
downstream — the IR builder, a guardrail, an emitter — so an unparseable
expression left the compile boundary as a raw SQLGlot exception rather than as
a ``BloomeryError``. The refusal belongs at the parse stage: it is the only
place that knows the authored address, and one authored field feeds up to three
of those call sites.
"""

from __future__ import annotations

import pytest

from bloomery import load_catalog, load_project
from bloomery.errors import SpecParseError

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


def test_a_parseable_expression_still_loads() -> None:
    """The control. A validator that refused everything would pass every test
    above and be caught only by the corpus — this is the assertion that says
    the refusal is about the text rather than about the field existing."""
    loaded = load_catalog(catalog())
    assert loaded.canonical_fields["unit_price"].recipes[0].expr == "line_total / quantity"
    assert loaded.metric_templates["gross_revenue"].expr == "price * qty"


def test_a_second_statement_is_still_accepted() -> None:
    """Deliberately unchanged, and pinned so a later reading of ``SqlText``
    cannot quietly widen it.

    ``a; b`` parses — SQLGlot returns a ``Block`` rather than raising — so it
    was accepted before this validator existed and is accepted now. Refusing
    it is a *new* refusal rather than a crash fix, and the one surface where a
    trailing statement is known to be dangerous already refuses it by name
    (``guardrails/quality.py``, on an expression rule).
    """
    loaded = load_catalog(catalog(recipe="a; b"))
    assert loaded.canonical_fields["unit_price"].recipes[0].expr == "a; b"
