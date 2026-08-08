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
from typing import TYPE_CHECKING

from bloomery.spec.mapping import RecipeFieldMapping

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
    label: str  # "direct" | "recipe:<id>" | "requires" | "requires_metrics" | "canonical"


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
        if isinstance(field_mapping, RecipeFieldMapping):
            label = f"recipe:{field_mapping.recipe}"
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
    """Wire each step between the relations it reads and the fields it
    produces (RFC 0017 §5.6, D11).

    Both directions matter and for different reasons. Input edges put the step
    *downstream* of whatever fills its inputs, so a change upstream reaches it
    in topological order. Output edges put every produced field downstream of
    the step, which is what lets `plan()` compute a backfill *across* it —
    the load-bearing goal (§4: "backfillability preserved across steps").

    An input relation is named as an entity field only when the wiring points
    at ``<entity>.<field>``-shaped text; a bare relation name has no field to
    hang an edge on, and inventing one would put a node in the DAG that
    nothing else in the graph agrees exists.
    """
    if project.steps is None:
        return []
    edges: list[Edge] = []
    for wiring in project.steps.steps:
        node = step_node(wiring.ref)
        edges.extend(
            Edge(src=entity_field_node(*_relation_field(bound)), dst=node, label="step_input")
            for _name, bound in sorted(wiring.inputs.items())
            if "." in bound
        )
        for _name, relation in sorted(wiring.outputs.items()):
            entity = relation.rsplit(".", 1)[-1]
            edges.append(Edge(src=node, dst=entity_field_node(entity, "*"), label="step_output"))
    return edges


def _relation_field(bound: str) -> tuple[str, str]:
    """``silver.customer_raw`` reads as the relation ``customer_raw``; the
    field half is the wildcard, because a step reads a relation whole."""
    return (bound.rsplit(".", 1)[-1], "*")


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
    for edge in edges:
        nodes.add(edge.src)
        nodes.add(edge.dst)

    return Graph(
        nodes=tuple(sorted(nodes, key=lambda n: n.name)),
        edges=tuple(sorted(set(edges), key=lambda e: (e.src.name, e.dst.name, e.label))),
    )
