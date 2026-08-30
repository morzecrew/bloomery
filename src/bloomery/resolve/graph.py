"""The single dependency DAG (RFC 0005 §5.1): one graph over source columns,
mapped entity fields, catalog canonical fields, and metrics — reachability,
cycles, topo order, and (later) guardrail traversal all read the same
structure, so they cannot disagree about what depends on what (RFC 0005 D1).

Node ids are kind-prefixed dotted names, pinned by tests because they reach
``CircularDerivation`` messages and topo output (RFC 0005 §9).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from bloomery.spec.mapping import ALIAS_BOUND, RecipeFieldMapping

if TYPE_CHECKING:
    from bloomery.resolve.metrics import EffectiveMetric
    from bloomery.spec.catalog import Catalog
    from bloomery.spec.mapping import Mapping
    from bloomery.spec.project import Project

__all__ = [
    "Edge",
    "Graph",
    "Node",
    "NodeKind",
    "build_graph",
    "canonical_field_node",
    "entity_field_node",
    "metric_node",
    "source_column_node",
    "step_node",
]


class NodeKind(StrEnum):
    """The node kinds of the dependency DAG (RFC 0005 §5.1; ``STEP`` added by
    RFC 0017 §5.6, D11)."""

    SOURCE_COLUMN = "source_column"
    ENTITY_FIELD = "entity_field"
    CANONICAL_FIELD = "canonical_field"
    METRIC = "metric"
    STEP = "step"


@dataclass(frozen=True, slots=True)
class Node:
    """One DAG node; ``name`` is the canonical kind-prefixed dotted id."""

    kind: NodeKind
    name: str


@dataclass(frozen=True, slots=True)
class Edge:
    """One dependency edge, pointing dependency → dependent (RFC 0005 §5.1)."""

    src: Node
    dst: Node
    #: The label *family* is the part before any ``:`` — see
    #: :data:`_EDGE_SHAPES` for the closed set of
    #: ``(family, src kind, dst kind)`` triples and what each one means.
    #: Two families are parameterised: ``recipe:<id>`` and ``step:<ref@version>``.
    label: str


#: Every ``(label family, src kind, dst kind)`` the two builders below can
#: emit (RFC 0031 §5.3, D6). The label family is the part before any ``:``, so
#: the parameterised ``recipe:<id>`` and ``step:<ref@version>`` contribute
#: ``recipe`` and ``step``.
#:
#: **Read off the builders, never off the corpus.** A vocabulary compiled from
#: fixtures can only contain what some fixture exercises, and that method cost
#: RFC 0031's first draft two entries: ``identity_resolution`` is the only
#: project wiring a step and wires exactly one, so neither ``step → step`` form
#: occurs; and no fixture declares a ``sql_macro`` field, so ``step:`` occurs
#: nowhere at all. ``tests/unit/test_resolve/test_graph.py`` guards this from
#: both sides — the corpus is a subset of it, and so is an AST walk over every
#: ``Edge(...)`` construction in this module.
_EDGE_SHAPES: Final[frozenset[tuple[str, NodeKind, NodeKind]]] = frozenset(
    {
        # A mapped field: straight from a source column, via a catalog recipe,
        # or via a Tier 1 `sql_macro` (RFC 0017 D50).
        ("direct", NodeKind.SOURCE_COLUMN, NodeKind.ENTITY_FIELD),
        ("recipe", NodeKind.SOURCE_COLUMN, NodeKind.ENTITY_FIELD),
        ("step", NodeKind.SOURCE_COLUMN, NodeKind.ENTITY_FIELD),
        # The field links to a catalog canonical, which is what makes it
        # available to a metric.
        ("canonical", NodeKind.ENTITY_FIELD, NodeKind.CANONICAL_FIELD),
        ("requires", NodeKind.CANONICAL_FIELD, NodeKind.METRIC),
        ("requires_metrics", NodeKind.METRIC, NodeKind.METRIC),
        # A step reads a mapped entity whole, or another step's output. The
        # second form includes the self-edge a self-referencing binding emits
        # so that cycle detection has something to find — which means it is a
        # shape `toposort` always raises on, never one `lineage()` sees.
        ("step_input", NodeKind.ENTITY_FIELD, NodeKind.STEP),
        ("step_input", NodeKind.STEP, NodeKind.STEP),
        ("step_output", NodeKind.STEP, NodeKind.ENTITY_FIELD),
    }
)


@dataclass(frozen=True, slots=True)
class Graph:
    """The assembled DAG: nodes sorted by name, edges sorted by
    (src, dst, label) — deterministic by construction (RFC 0003 §5.3)."""

    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]


def source_column_node(relation: str, path: str) -> Node:
    """A bronze extraction, e.g. ``source.shopify__order_lines.$.total``."""
    return Node(kind=NodeKind.SOURCE_COLUMN, name=f"source.{relation}.{path}")


def entity_field_node(entity: str, field: str) -> Node:
    """A mapped entity field, e.g. ``order_item.unit_price``."""
    return Node(kind=NodeKind.ENTITY_FIELD, name=f"{entity}.{field}")


def canonical_field_node(name: str) -> Node:
    """A catalog canonical field, e.g. ``canonical.unit_price``."""
    return Node(kind=NodeKind.CANONICAL_FIELD, name=f"canonical.{name}")


def metric_node(name: str) -> Node:
    """A metric, e.g. ``metric.gross_revenue``."""
    return Node(kind=NodeKind.METRIC, name=f"metric.{name}")


def step_node(ref: str) -> Node:
    """A referenced implementation, e.g. ``step.resolve_customers``
    (RFC 0017 §5.6, D11).

    Keyed by ``ref`` alone, not ``ref@version``: the node is the *place in the
    lineage* where a step sits, and a version bump does not move it. What the
    version changes is the step's fingerprint, which is `plan()`'s business
    (D6) — encoding it in the node id would instead make an upgrade read as a
    node removed and a different one added, breaking the very lineage this
    node exists to preserve.
    """
    return Node(kind=NodeKind.STEP, name=f"step.{ref}")


def _mapping_edges(mapping: Mapping, canonical_by_field: dict[str, str | None]) -> list[Edge]:
    edges: list[Edge] = []
    for field_name, key_field in mapping.key.items():
        edges.append(
            Edge(
                src=source_column_node(mapping.source, key_field.from_),
                dst=entity_field_node(mapping.target, field_name),
                label="direct",
            )
        )
    for field_name, field_mapping in mapping.fields.items():
        dst = entity_field_node(mapping.target, field_name)
        if isinstance(field_mapping, ALIAS_BOUND):
            label = (
                f"recipe:{field_mapping.recipe}"
                if isinstance(field_mapping, RecipeFieldMapping)
                else f"step:{field_mapping.step}"
            )
            edges.extend(
                Edge(src=source_column_node(mapping.source, path), dst=dst, label=label)
                for path in field_mapping.from_.values()
            )
        else:
            edges.append(
                Edge(
                    src=source_column_node(mapping.source, field_mapping.from_),
                    dst=dst,
                    label="direct",
                )
            )
    for field_name in sorted({*mapping.key, *mapping.fields}):
        canonical = canonical_by_field.get(field_name)
        if canonical is not None:
            edges.append(
                Edge(
                    src=entity_field_node(mapping.target, field_name),
                    dst=canonical_field_node(canonical),
                    label="canonical",
                )
            )
    return edges


def _step_edges(project: Project) -> list[Edge]:
    """Wire each step between what fills its inputs and what it produces
    (RFC 0017 §5.6, D11).

    Both directions matter and for different reasons. Input edges put the step
    *downstream* of whatever fills its inputs, so a change upstream reaches it
    in topological order — and so a **cycle between two steps** is a cycle in
    this graph rather than a pipeline that deadlocks at run time. Output edges
    put the produced relation downstream of the step, which is what lets
    `plan()` compute a backfill *across* it (§4).

    An input is resolved two ways, and the second is the one that took a
    regression to learn. A binding naming a **mapped entity** draws an edge
    from each of that entity's fields — a step reads a relation whole. A
    binding naming another **step's output** draws an edge from that step's
    node directly, because a step-produced relation is not an entity and
    looking only in the entity table silently produced no edge at all, which
    is exactly the common case (one step feeding another) and exactly where
    cycle detection was lost.
    """
    if project.steps is None:
        return []
    entities = project.entity_model.entities
    producer_of: dict[str, str] = {
        relation.rsplit(".", 1)[-1]: wiring.ref
        for wiring in project.steps.steps
        for relation in wiring.outputs.values()
    }
    edges: list[Edge] = []
    for wiring in project.steps.steps:
        node = step_node(wiring.ref)
        for _name, bound in sorted(wiring.inputs.items()):
            relation = bound.rsplit(".", 1)[-1]
            producer = producer_of.get(relation)
            if producer is not None and producer != wiring.ref:
                edges.append(Edge(src=step_node(producer), dst=node, label="step_input"))
                continue
            entity = entities.get(relation)
            if entity is None:
                # A self-referencing binding lands here too, and must still
                # produce the self-edge the cycle check reads.
                if producer == wiring.ref:
                    edges.append(Edge(src=node, dst=node, label="step_input"))
                continue
            edges.extend(
                Edge(src=entity_field_node(relation, field), dst=node, label="step_input")
                for field in sorted({*entity.fields, *entity.key})
            )
        for output_name, relation in sorted(wiring.outputs.items()):
            produced = relation.rsplit(".", 1)[-1]
            edges.append(
                Edge(src=node, dst=entity_field_node(produced, output_name), label="step_output")
            )
            # A declared `canonical:` link makes the column *available*, which
            # is the whole of what a metric's reachability asks (RFC 0005
            # §5.3, RFC 0017 D49). The column node hangs off the step for the
            # same reason the output node does — so the link is reachable in
            # topological order rather than floating free of its producer.
            for column, canonical in sorted(wiring.canonical.get(output_name, {}).items()):
                field = entity_field_node(produced, column)
                edges.append(Edge(src=node, dst=field, label="step_output"))
                edges.append(
                    Edge(src=field, dst=canonical_field_node(canonical), label="canonical")
                )
    return edges


def build_graph(
    project: Project,
    catalog: Catalog | None,
    metrics: tuple[EffectiveMetric, ...],
) -> Graph:
    """Assemble the DAG from reference-clean specs (RFC 0005 §5.1).

    Source columns feed entity fields (transform chains or recipe ``from``
    aliases); mapped entity fields feed canonical fields (``canonical:``
    links); canonical fields feed metrics (``requires``); metrics feed
    metrics (``requires_metrics``).
    """
    edges: list[Edge] = []
    edges.extend(_step_edges(project))
    for mapping in project.mappings:
        entity = project.entity_model.entities[mapping.target]
        canonical_by_field = {name: field.canonical for name, field in entity.fields.items()}
        edges.extend(_mapping_edges(mapping, canonical_by_field))
    for metric in metrics:
        dst = metric_node(metric.name)
        edges.extend(
            Edge(src=canonical_field_node(leaf), dst=dst, label="requires")
            for leaf in metric.requires
        )
        edges.extend(
            Edge(src=metric_node(required), dst=dst, label="requires_metrics")
            for required in metric.requires_metrics
        )

    nodes: set[Node] = set()
    if catalog is not None:
        nodes.update(canonical_field_node(name) for name in catalog.canonical_fields)
    nodes.update(metric_node(metric.name) for metric in metrics)
    if project.steps is not None:
        # A step with no wired inputs still exists in the lineage; without
        # this it would vanish from the topological order entirely.
        nodes.update(step_node(wiring.ref) for wiring in project.steps.steps)
    # A mapped field with no edge at all, for the same reason and with the same
    # fix. Both alias-bound shapes can bind **zero** source paths: a
    # `sql_macro` whose `from` is empty — the schema's default, because a macro
    # may compute from its `parameters` alone (RFC 0017 D50) — and a recipe
    # with an empty `requires` and an `expr`. Such a field draws no edge from
    # any source column, so before this it existed nowhere in the graph:
    # absent from `topo_order`, and refused by `bloomery lineage`, whose
    # `_find_node` looks the id up in `nodes` and suggested a sibling field
    # instead — for a field the entity model declares and the emitter writes
    # a column for. (`lineage()` itself answered: it takes a root that is not
    # a member, by design.) Every ordinary mapped field is already here via
    # its incoming edge, so this adds a node only where one was missing.
    nodes.update(
        entity_field_node(mapping.target, field_name)
        for mapping in project.mappings
        for field_name in (*mapping.key, *mapping.fields)
    )
    for edge in edges:
        nodes.add(edge.src)
        nodes.add(edge.dst)

    # Both keys carry the node *kind* as a tiebreak, and both are collected
    # from a `set`. An entity-field id has no kind prefix (`<entity>.<field>`),
    # so it can collide with every other kind's: an entity named `metric` with
    # a field `revenue` produces `metric.revenue`, and so does a metric named
    # `revenue`. Sorted by name alone those two keep whatever relative order set
    # iteration gave, which varies with `PYTHONHASHSEED` — the same specs then
    # produce different `Graph.nodes` in different processes, and `topo_order`
    # derives from this order, so it reaches emitted output. RFC 0003 forbids
    # exactly that; see `logs/T-0005.md` D-025.
    return Graph(
        nodes=tuple(sorted(nodes, key=lambda n: (n.name, n.kind.value))),
        edges=tuple(
            sorted(
                set(edges),
                key=lambda e: (
                    e.src.name,
                    e.src.kind.value,
                    e.dst.name,
                    e.dst.kind.value,
                    e.label,
                ),
            )
        ),
    )
