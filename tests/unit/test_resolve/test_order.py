"""Cycle detection and topo order (RFC 0005 §5.4): lexicographic tie-breaks,
invariance under edge order, the rotated cycle message, and the id collision
that used to be reported as a cycle."""

from __future__ import annotations

import pytest

from bloomery import load_catalog, load_project
from bloomery.errors import CircularDerivation
from bloomery.resolve import resolve
from bloomery.resolve.graph import Edge, Graph, Node, NodeKind
from bloomery.resolve.order import toposort
from support.compiling import COLLIDING_ID_SOURCES

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


def test_two_nodes_may_share_a_name_and_both_are_ordered() -> None:
    """A name collision is not a cycle, and both nodes are emitted.

    Keyed by name alone, the entity field and the metric collapsed into one
    entry: `len(order)` then disagreed with `len(graph.nodes)` on an acyclic
    graph, the cycle path ran, and `_find_cycle` called `min()` on an empty
    `remaining` — nothing was actually blocked — raising a bare `ValueError`
    out of a package whose contract is named refusals.

    Asserted on both nodes rather than on "it does not raise": not raising is
    also what dropping one node quietly would look like.
    """
    resolution = resolve(load_project(COLLIDING_ID_SOURCES))

    ordered = [(node.kind, node.name) for node in resolution.topo_order]
    assert (NodeKind.ENTITY_FIELD, "metric.revenue") in ordered
    assert (NodeKind.METRIC, "metric.revenue") in ordered
    assert len(resolution.topo_order) == len(resolution.graph.nodes)


def test_a_shared_name_still_orders_dependencies_first() -> None:
    """The linearization is right, not merely complete.

    The count above would be satisfied by an order that emitted the two
    colliding nodes in either position. The entity field depends on its source
    column, so that column must precede it — which is the property the shared
    `by_name` entry destroyed by giving both nodes one indegree.
    """
    order = [(node.kind, node.name) for node in resolve(load_project(COLLIDING_ID_SOURCES)).topo_order]

    column = order.index((NodeKind.SOURCE_COLUMN, "source.raw__metrics.$.revenue"))
    field = order.index((NodeKind.ENTITY_FIELD, "metric.revenue"))
    assert column < field


def test_a_node_listed_twice_is_one_node_not_a_cycle() -> None:
    """The other way the length comparison used to lie.

    `build_graph` collects nodes into a `set`, so its graphs never repeat one —
    but `Graph` is public and holds a plain tuple, and a caller assembling one
    by hand can list a node twice. Compared against `len(graph.nodes)` that
    repeat was indistinguishable from a node the walk never reached: same bare
    `ValueError`, same empty `remaining`, on a graph with no cycle at all.
    """
    node = _node("a")
    assert toposort(Graph(nodes=(node, node), edges=())) == (node,)


def test_a_cycle_among_colliding_names_still_names_the_path() -> None:
    """The rendering stays names-only where the key is a pair.

    RFC 0005 D4 pins the message as a path a reader retypes, so the key's kind
    half must not leak into it. Two nodes sharing a name print that name twice,
    which is the honest rendering of a project in which they *are* one id.
    """
    field = Node(kind=NodeKind.ENTITY_FIELD, name="metric.revenue")
    metric = Node(kind=NodeKind.METRIC, name="metric.revenue")
    graph = Graph(
        nodes=(field, metric),
        edges=(
            Edge(src=field, dst=metric, label="requires"),
            Edge(src=metric, dst=field, label="requires"),
        ),
    )
    with pytest.raises(CircularDerivation) as excinfo:
        toposort(graph)
    assert str(excinfo.value) == "circular derivation: metric.revenue → metric.revenue → metric.revenue"
