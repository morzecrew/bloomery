"""The graph shapes the fixture corpus cannot reach (RFC 0031 §6).

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

Two projects here reach no *edge* shape at all — they are the fields that draw
**no edge**, which is how the graph came to lose them. Same reason for being
here: the corpus binds a source path for every mapped field, so nothing in it
exercises the empty `from:` that both alias-bound shapes allow.
"""

from __future__ import annotations

import pytest

from bloomery import load_catalog, load_project, resolve
from bloomery.errors import CircularDerivation
from bloomery.resolve.graph import Edge, NodeKind, build_graph, entity_field_node
from bloomery.resolve.order import toposort
from bloomery.resolve.resolution import Provenance

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

#: The same macro field binding **no** source path — the schema's default,
#: because a macro may compute from its `parameters` alone (RFC 0017 D50). It
#: is the shape that draws no edge at all, and so the one the graph used to
#: lose the field over entirely.
PATHLESS_MACRO_MAPPING = """
mapping_version: 1
source: raw__customers
target: customer
key:
  customer_id: {from: "$.id", transform: [to_string]}
fields:
  score:
    step: constant_score@1
    parameters: {weight: 1}
"""

#: A recipe that requires nothing and carries an `expr` — `resolve_recipe` only
#: insists on a single requirement where `expr` is *omitted*, so this is legal,
#: and it compiles to a constant column. The other zero-path shape.
CONSTANT_RECIPE_CATALOG = """
catalog_version: 1
vertical: probe
canonical_fields:
  score:
    entity: customer
    type: "decimal(12, 4)"
    unit: currency
    tax_basis: net
    recipes:
      - {id: flat, requires: [], expr: "0.20"}
canonical_relationships: []
metric_templates: {}
"""

LINKED_ENTITY_MODEL = ENTITY_MODEL.replace(
    'score: {type: "decimal(12, 4)"}',
    'score: {type: "decimal(12, 4)", canonical: score}',
)

CONSTANT_RECIPE_MAPPING = """
mapping_version: 1
source: raw__customers
target: customer
key:
  customer_id: {from: "$.id", transform: [to_string]}
fields:
  score: {recipe: flat, from: {}}
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


def test_a_field_binding_no_source_path_is_still_a_node() -> None:
    """A mapped field with no edge at all still exists (RFC 0005 §5.1).

    `build_graph` collects entity-field nodes from its edges, and this field
    draws none — so before mapped fields were added explicitly it was in the
    graph nowhere: no node, absent from `topo_order`, and refused by `bloomery
    lineage`, which looks an id up in `nodes` and answered "did you mean:
    customer.customer_id" — for a column the emitter writes.

    `lineage()` itself was never the one refusing: it documents that a root
    need not be a member of the graph, so it returned a bare root before this
    fix as well as after. That is why the assertion is on the node and the
    topological order rather than on a walk — a walk agreed either way, and
    the order is what shows the field rejoining the emission sequence.
    """
    project = load_project(
        {"entity_model": ENTITY_MODEL, "mapping_c": PATHLESS_MACRO_MAPPING}
    )
    graph = build_graph(project, None, ())

    score = entity_field_node("customer", "score")
    assert score in graph.nodes
    assert not [edge for edge in graph.edges if score in (edge.src, edge.dst)], (
        "the point of this shape is that it draws no edge — if it draws one, "
        "the test no longer covers the case it names"
    )
    assert score in toposort(graph)


def test_a_pathless_recipe_field_keeps_its_recipe_id() -> None:
    """The recorded decision survives a field with no edge to carry its label.

    A `recipe:<id>` label rides on the edges the field's `from:` aliases draw,
    so a recipe binding none has nowhere to put it. Provenance takes the id
    from the mapping for exactly that reason: reporting this field `DIRECT` —
    which its `canonical:` link would otherwise make it — would lose the
    upstream choice the compiler is forbidden to re-make (RFC 0005 D2).
    """
    project = load_project(
        {"entity_model": LINKED_ENTITY_MODEL, "mapping_c": CONSTANT_RECIPE_MAPPING}
    )
    resolution = resolve(project, load_catalog(CONSTANT_RECIPE_CATALOG))

    score = [entry for entry in resolution.provenance if entry.field == "score"]
    assert [(e.provenance, e.recipe_id) for e in score] == [(Provenance.RECIPE, "flat")]
    assert not [edge for edge in resolution.graph.edges if edge.label.startswith("recipe:")], (
        "no recipe edge exists to read the id off — that is what this test is about"
    )


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
