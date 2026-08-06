"""Cycle detection and topo order (RFC 0005 §5.4): lexicographic tie-breaks,
invariance under edge order, and the rotated cycle message."""

from __future__ import annotations

import pytest

from bloomery import load_catalog, load_project
from bloomery.errors import CircularDerivation
from bloomery.resolve import resolve
from bloomery.resolve.graph import Edge, Graph, Node, NodeKind
from bloomery.resolve.order import toposort

pytestmark = pytest.mark.unit


def _node(name: str) -> Node:
    return Node(kind=NodeKind.METRIC, name=name)


def _graph(names: list[str], edges: list[tuple[str, str]]) -> Graph:
    return Graph(
        nodes=tuple(_node(n) for n in names),
        edges=tuple(Edge(src=_node(a), dst=_node(b), label="requires_metrics") for a, b in edges),
    )


def test_topo_is_a_valid_linearization_with_lexicographic_ties() -> None:
    graph = _graph(["a", "b", "c", "d"], [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")])
    assert [n.name for n in toposort(graph)] == ["a", "b", "c", "d"]


def test_topo_ties_break_lexicographically_without_edges() -> None:
    graph = _graph(["z", "x", "y"], [])
    assert [n.name for n in toposort(graph)] == ["x", "y", "z"]


def test_topo_is_invariant_under_edge_order() -> None:
    edges = [("b", "a"), ("c", "b"), ("d", "c")]
    forward = _graph(["a", "b", "c", "d"], edges)
    backward = _graph(["d", "c", "b", "a"], list(reversed(edges)))
    assert toposort(forward) == toposort(backward)


def test_cycle_message_is_rotated_to_the_smallest_node() -> None:
    graph = _graph(["c", "a", "b"], [("c", "a"), ("a", "b"), ("b", "c")])
    with pytest.raises(CircularDerivation) as excinfo:
        toposort(graph)
    assert str(excinfo.value) == "circular derivation: a → b → c → a"


def test_cycle_detection_ignores_clean_side_branches() -> None:
    graph = _graph(
        ["root", "m1", "m2", "leafless"],
        [("root", "m1"), ("m1", "m2"), ("m2", "m1")],
    )
    with pytest.raises(CircularDerivation) as excinfo:
        toposort(graph)
    assert str(excinfo.value) == "circular derivation: m1 → m2 → m1"


ENTITY_MODEL = """\
spec_version: 1
entities:
  order:
    grain: one row per order
    key: [order_id]
    fields:
      order_id: {type: string, required: true}
"""

MAPPING = """\
mapping_version: 1
source: src__orders
target: order
key:
  order_id: {from: "$.id", transform: [to_string]}
"""


def test_metric_on_metric_cycle_through_resolve() -> None:
    metrics = (
        "metrics_version: 1\n"
        "metrics:\n"
        "  beta: {requires_metrics: [alpha], additivity: additive, agg: sum}\n"
        "  alpha: {requires_metrics: [beta], additivity: additive, agg: sum}\n"
    )
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": MAPPING, "metrics": metrics})
    with pytest.raises(CircularDerivation) as excinfo:
        resolve(project, load_catalog("catalog_version: 1\nvertical: test\n"))
    assert str(excinfo.value) == (
        "circular derivation: metric.alpha → metric.beta → metric.alpha"
    )


def test_self_cycle_is_named() -> None:
    metrics = (
        "metrics_version: 1\n"
        "metrics:\n"
        "  ouroboros: {requires_metrics: [ouroboros], additivity: additive, agg: sum}\n"
    )
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": MAPPING, "metrics": metrics})
    with pytest.raises(CircularDerivation) as excinfo:
        resolve(project, load_catalog("catalog_version: 1\nvertical: test\n"))
    assert str(excinfo.value) == (
        "circular derivation: metric.ouroboros → metric.ouroboros"
    )
