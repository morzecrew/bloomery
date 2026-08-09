"""The closed ``reconcile:`` side grammar (RFC 0016 §5.3).

The grammar is the whole refusal surface: what parses is emitted as a
comparison AST, and what does not is a compile error naming the shapes that
do. Both halves are tested here — the accepted shapes at the parser, the
refusals at the guardrail stage that carries the message an author reads.
"""

from __future__ import annotations

import pytest
from support.compiling import fixture_sources, load_fixture

from bloomery import build_project_ir, load_project
from bloomery.errors import GuardrailError
from bloomery.quality import RECONCILE_AGGREGATES, parse_side

pytestmark = pytest.mark.unit


# ....................... #
# The two accepted shapes


@pytest.mark.parametrize("agg", RECONCILE_AGGREGATES)
def test_every_aggregate_in_the_closed_vocabulary_parses(agg: str) -> None:
    side = parse_side(f"{agg}(order_item.line_total) by order_id")
    assert side is not None
    assert (side.entity, side.column, side.agg, side.by) == (
        "order_item",
        "line_total",
        agg,
        ("order_id",),
    )
    assert side.aggregated


def test_the_aggregate_shape_takes_several_by_columns() -> None:
    side = parse_side("sum(inventory_level.stock_level) by warehouse_id, stock_date")
    assert side is not None
    assert side.by == ("warehouse_id", "stock_date")


def test_the_plain_column_shape_carries_no_keys_of_its_own() -> None:
    """Its keys are the entity's declared key, which only the model knows —
    the parser deliberately does not guess."""
    side = parse_side("order.total_amount")
    assert side is not None
    assert (side.entity, side.column, side.agg, side.by) == ("order", "total_amount", None, ())
    assert not side.aggregated


@pytest.mark.parametrize(
    "text",
    [
        "  sum( order_item . line_total )  by  order_id  ",
        "SUM(order_item.line_total) by order_id",
    ],
)
def test_whitespace_and_case_do_not_change_the_parse(text: str) -> None:
    side = parse_side(text)
    assert side is not None
    assert (side.agg, side.entity, side.column, side.by) == (
        "sum",
        "order_item",
        "line_total",
        ("order_id",),
    )


# ....................... #
# Everything else is outside the grammar


@pytest.mark.parametrize(
    "text",
    [
        "median(order_item.line_total) by order_id",  # aggregate outside the vocabulary
        "sum(order_item.line_total)",  # aggregate with no `by`
        "sum(line_total) by order_id",  # unqualified column
        "order_item.line_total * 2",  # arithmetic
        "SELECT SUM(line_total) FROM order_item",  # SQL
        "sum(order_item.line_total) by",  # empty key list
        "order_item.line_total.deep",  # not a two-part reference
        "",
    ],
)
def test_shapes_outside_the_grammar_do_not_parse(text: str) -> None:
    assert parse_side(text) is None


# ....................... #
# The guardrail refusals (the message an author actually reads)


def _with_reconcile(block: str, *, extra_entity: str = "") -> tuple[str, ...]:
    """The quality fixture with its ``reconcile:`` list replaced, and
    optionally one more entity declared (and deliberately left unmapped)."""
    sources = dict(fixture_sources("semi_additive_inventory"))
    head, _sep, _tail = sources["entity_model"].partition("\nreconcile:")
    if extra_entity:
        head = head.replace("\nrelationships:", f"\n{extra_entity}\nrelationships:", 1)
        if extra_entity not in head:
            head = f"{head}\n{extra_entity}"
    sources["entity_model"] = f"{head}\nreconcile:\n{block}"
    _project, catalog = load_fixture("semi_additive_inventory")
    with pytest.raises(GuardrailError) as excinfo:
        build_project_ir(load_project(sources), catalog)
    return (str(excinfo.value),)


def test_an_unparseable_side_names_the_supported_shapes() -> None:
    (message,) = _with_reconcile(
        '  - {name: bad, left: "stock_level * 2", right: "inventory_level.stock_level",\n'
        '     tolerance: "0.01", on_fail: flag}\n'
    )
    assert "unparseable left side" in message
    assert "supported shapes are" in message
    assert "'<entity>.<column>'" in message
    # The reason, not just the rule: a reconcile side is declared, never SQL.
    assert "specs never contain implementations" in message


def test_an_unknown_entity_is_refused() -> None:
    (message,) = _with_reconcile(
        '  - {name: bad, left: "sum(nosuch.stock_level) by warehouse_id",\n'
        '     right: "inventory_level.stock_level", tolerance: "0.01", on_fail: flag}\n'
    )
    assert "names entity 'nosuch'" in message


def test_an_unknown_column_is_refused_naming_the_known_ones() -> None:
    (message,) = _with_reconcile(
        '  - {name: bad, left: "sum(inventory_level.nosuch) by warehouse_id, stock_date",\n'
        '     right: "inventory_level.stock_level", tolerance: "0.01", on_fail: flag}\n'
    )
    assert "reads nosuch on entity 'inventory_level'" in message
    assert "stock_level" in message


def test_sides_keyed_differently_are_refused_naming_both() -> None:
    """The one rule the grammar cannot express: the two sides join on their
    keys, so they have to be the same columns."""
    (message,) = _with_reconcile(
        '  - {name: bad, left: "sum(inventory_level.stock_level) by warehouse_id",\n'
        '     right: "inventory_level.stock_level", tolerance: "0.01", on_fail: flag}\n'
    )
    assert "left by ['warehouse_id']" in message
    assert "right by ['stock_date', 'warehouse_id']" in message


def test_duplicate_check_names_are_refused() -> None:
    check = (
        '  - {{name: dup, left: "sum(inventory_level.stock_level) by warehouse_id, stock_date",\n'
        '     right: "inventory_level.stock_level", tolerance: "{tolerance}", on_fail: flag}}\n'
    )
    (message,) = _with_reconcile(
        check.format(tolerance="0.01") + check.format(tolerance="1.00")
    )
    assert "'dup' is declared more than once" in message


def test_a_repeated_by_column_is_refused() -> None:
    """Each ``by`` column becomes an output column of the side's derived
    relation and a grain column of the model, so a repeat emits two columns of
    one name and a join condition PostgreSQL reads as ambiguous (verified
    live). Nothing downstream deduped it: the unknown-column check works over
    a *set*, and the key-agreement check sorts both sides — so the same repeat
    on both sides passed every existing test."""
    (message,) = _with_reconcile(
        '  - {name: dup_by,\n'
        '     left: "sum(inventory_level.stock_level) by warehouse_id, warehouse_id",\n'
        '     right: "inventory_level.stock_level", tolerance: "0.01", on_fail: flag}\n'
    )
    assert "repeats warehouse_id in its by clause" in message
    assert "ambiguous" in message


def test_a_side_naming_a_declared_but_unmapped_entity_is_refused() -> None:
    """``build_project_ir`` builds one silver entity per *mapping*, so a
    declared entity nothing targets has no relation for a reconcile to read.
    Resolving against the declared set let it through to emission, where it
    surfaced as an unbatched ``EmitError`` after the guardrail stage had
    already reported the project clean."""
    (message,) = _with_reconcile(
        '  - {name: ghostly, left: "inventory_level.stock_level",\n'
        '     right: "ghost.stock_level", tolerance: "0.01", on_fail: flag}\n',
        extra_entity=(
            "  ghost:\n"
            "    grain: one row per ghost\n"
            "    key: [warehouse_id]\n"
            "    fields:\n"
            "      warehouse_id: {type: string, required: true}\n"
            "      stock_level: {type: int}\n"
        ),
    )
    assert "no silver relation is built" in message
    # Named both ways since RFC 0017 D49: a step output has a relation without
    # a mapping, so "no mapping targets it" stopped being the whole reason.
    assert "neither the target of a mapping nor the output of a step" in message
