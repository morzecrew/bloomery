"""The three edge shapes the fixture corpus cannot reach (RFC 0031 §6).

`identity_resolution` is the corpus's only project wiring a step and it wires
exactly one, so neither `step → step` form occurs; and no fixture declares a
`sql_macro` field, so `step:<ref@version>` occurs nowhere at all. A vocabulary
compiled from fixtures therefore could not have contained them — which is what
cost RFC 0031's first draft two table rows (D6).

`test_edge_vocabulary.py` guards the same gap by reading the builders' source.
These projects close it from the other side: they make the shapes *run*, so the
table's rows are asserted against real edges rather than against an AST walk
alone. Built inline rather than added to `tests/fixtures/`, deliberately — a
fixture is a corpus-wide input that every golden and every other sweep would
then have to account for, and these exist to exercise one branch each.
"""

from __future__ import annotations

import pytest

from bloomery import load_project
from bloomery.errors import CircularDerivation
from bloomery.resolve.graph import Edge, NodeKind, build_graph
from bloomery.resolve.order import toposort

pytestmark = pytest.mark.unit

ENTITY_MODEL = """
spec_version: 1
entities:
  customer:
    grain: one row per customer
    key: [customer_id]
    fields:
      customer_id: {type: string}
      score: {type: "decimal(12, 4)"}
  resolved:
    grain: one row per resolved customer
    key: [customer_id]
    fields:
      customer_id: {type: string}
  final:
    grain: one row per final customer
    key: [customer_id]
    fields:
      customer_id: {type: string}
"""

DIRECT_MAPPING = """
mapping_version: 1
source: raw__customers
target: customer
key:
  customer_id: {from: "$.id", transform: [to_string]}
"""

#: A Tier 1 `sql_macro` field (RFC 0017 D50) — the non-recipe arm of the same
#: `ALIAS_BOUND` branch that produces `recipe:<id>`.
MACRO_MAPPING = """
mapping_version: 1
source: raw__customers
target: customer
key:
  customer_id: {from: "$.id", transform: [to_string]}
fields:
  score:
    step: fuzzy_score@2
    from: {left: "$.a", right: "$.b"}
    parameters: {weight: 1}
"""

#: Two steps, the second reading the first's output — what `_step_edges`'
#: docstring calls "exactly the common case (one step feeding another)".
CHAINED_STEPS = """
steps_version: 1
steps:
  - use: first_step@1
    inputs: {crm: silver.customer}
    outputs: {resolved: silver.resolved}
  - use: second_step@1
    inputs: {upstream: silver.resolved}
    outputs: {final: silver.final}
"""

#: A step whose input is its own output. `silver.scratch` is deliberately not a
#: declared entity — see `test_a_self_binding_on_a_declared_entity_is_not_a_self_edge`.
SELF_BINDING_STEPS = """
steps_version: 1
steps:
  - use: loop_step@1
    inputs: {itself: silver.scratch}
    outputs: {scratch: silver.scratch}
"""


def shapes_of(edges: tuple[Edge, ...]) -> set[tuple[str, NodeKind, NodeKind]]:
    return {(edge.label.split(":")[0], edge.src.kind, edge.dst.kind) for edge in edges}


def test_one_step_feeding_another_is_a_step_to_step_edge() -> None:
    project = load_project(
        {"entity_model": ENTITY_MODEL, "mapping_c": DIRECT_MAPPING, "steps": CHAINED_STEPS}
    )
    graph = build_graph(project, None, ())

    assert ("step_input", NodeKind.STEP, NodeKind.STEP) in shapes_of(graph.edges)
    chained = [
        edge
        for edge in graph.edges
        if edge.label == "step_input" and edge.src.kind is NodeKind.STEP
    ]
    assert [(e.src.name, e.dst.name) for e in chained] == [
        ("step.first_step", "step.second_step")
    ]
    # The chain is acyclic, so it survives `toposort` and could reach lineage.
    assert toposort(graph)


def test_a_macro_bound_field_is_labelled_with_its_ref_and_version() -> None:
    project = load_project({"entity_model": ENTITY_MODEL, "mapping_c": MACRO_MAPPING})
    graph = build_graph(project, None, ())

    macro_edges = [edge for edge in graph.edges if edge.label.startswith("step:")]
    assert {edge.label for edge in macro_edges} == {"step:fuzzy_score@2"}
    # One edge per bound alias, from the source column each alias reads.
    assert sorted(edge.src.name for edge in macro_edges) == [
        "source.raw__customers.$.a",
        "source.raw__customers.$.b",
    ]
    assert all(edge.dst.name == "customer.score" for edge in macro_edges)
    assert ("step", NodeKind.SOURCE_COLUMN, NodeKind.ENTITY_FIELD) in shapes_of(graph.edges)


def test_a_self_binding_emits_a_self_edge_that_toposort_refuses() -> None:
    """D5's precondition, evidenced rather than assumed.

    The self-edge exists so cycle detection has something to find. This asserts
    the finding: a project in this shape raises before `lineage()` could be
    called on its graph, which is why the traversal needs no cycle guard.
    """
    project = load_project(
        {"entity_model": ENTITY_MODEL, "mapping_c": DIRECT_MAPPING, "steps": SELF_BINDING_STEPS}
    )
    graph = build_graph(project, None, ())

    self_edges = [edge for edge in graph.edges if edge.src == edge.dst]
    assert [(e.src.name, e.label) for e in self_edges] == [("step.loop_step", "step_input")]

    with pytest.raises(CircularDerivation, match="step.loop_step"):
        toposort(graph)


def test_a_self_binding_on_a_declared_entity_is_not_a_self_edge() -> None:
    """The self-edge branch is narrower than "a self-referencing binding".

    `_step_edges` reaches it only when the bound relation names no declared
    entity: a step whose output *is* an entity falls through to the entity
    branch and draws one edge per field instead, which is not a cycle and does
    not raise. §5.3's row says "a self-referencing binding" and this is the
    half that sentence does not carry — see ``logs/T-0005.md`` D-022.
    """
    entity_model = ENTITY_MODEL.replace(
        "  resolved:\n", "  scratch:\n    grain: one row per scratch\n    key: [customer_id]\n"
        "    fields:\n      customer_id: {type: string}\n  resolved:\n"
    )
    project = load_project(
        {"entity_model": entity_model, "mapping_c": DIRECT_MAPPING, "steps": SELF_BINDING_STEPS}
    )
    graph = build_graph(project, None, ())

    assert not [edge for edge in graph.edges if edge.src == edge.dst]
    assert ("step_input", NodeKind.ENTITY_FIELD, NodeKind.STEP) in shapes_of(graph.edges)
    # And so it is acyclic: the shape that looks like a loop in the spec is not
    # one in the graph, which is exactly why the branch above has to exist.
    assert toposort(graph)
