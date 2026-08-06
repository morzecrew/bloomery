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
]


class NodeKind(StrEnum):
    """The four node kinds of the dependency DAG (RFC 0005 §5.1)."""

    SOURCE_COLUMN = "source_column"
    ENTITY_FIELD = "entity_field"
    CANONICAL_FIELD = "canonical_field"
    METRIC = "metric"


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
    for edge in edges:
        nodes.add(edge.src)
        nodes.add(edge.dst)

    return Graph(
        nodes=tuple(sorted(nodes, key=lambda n: n.name)),
        edges=tuple(sorted(set(edges), key=lambda e: (e.src.name, e.dst.name, e.label))),
    )
