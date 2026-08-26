"""Lineage: a traversal over the dependency DAG (RFC 0031 §5.1).

`resolve()` builds the graph on every call and, before this, kept only its
topological order — every node in dependency order with no edges, which is the
one thing the structure exists to say. :func:`lineage` walks it and returns the
**reachable sub-DAG**, not enumerated paths (D1): a DAG's path count is
exponential in its width, so paths make the output size a property the caller
cannot predict from an input it holds, while the induced sub-DAG is bounded by
the graph itself.

The walk needs no correctness argument of its own. ``toposort`` raises on a
cycle before anything downstream of it runs, so every graph reaching here is
acyclic and the visited set is an optimisation rather than a termination
guard (D5).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

# Runtime imports, not `TYPE_CHECKING` ones: `Lineage` and `lineage` are public
# (D2), and RFC 0018 D10 requires a public annotation to resolve at run time —
# `get_type_hints` is what `tests/unit/test_signature_closure.py` calls on every
# export, and a guarded name fails it.
from bloomery.resolve.graph import Edge, Graph, Node

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "Direction",
    "Lineage",
    "lineage",
]


class Direction(StrEnum):
    """Which way :func:`lineage` follows an edge (RFC 0031 §5.1).

    ``Edge`` points **dependency → dependent**, so upstream reads an edge
    backwards and downstream reads it forwards.

    There is deliberately no ``BOTH`` member in P1. RFC 0031 D4 leaves its
    return shape open — one merged sub-DAG, or an upstream/downstream pair —
    and defers *the member*, not only the shape: this enum is public under
    SemVer (D2), so a ``BOTH`` shipped now and reshaped later would be a
    breaking change to a published type rather than an addition to one. It
    arrives with P2, when the renderer that needs it forces D4's answer.
    See ``logs/T-0005.md`` D-019.
    """

    #: Follow edges dependent → dependency: what the root is built from.
    UPSTREAM = "upstream"
    #: Follow edges dependency → dependent: what would break if the root moved.
    DOWNSTREAM = "downstream"


@dataclass(frozen=True, slots=True)
class Lineage:
    """The sub-DAG reachable from :attr:`root` in :attr:`direction` (D1).

    :attr:`nodes` always contains :attr:`root`, so an empty lineage is a
    one-node value rather than an empty one — a source column has no upstream,
    and that is an answer rather than a miss.

    :attr:`edges` is the sub-DAG **induced** on :attr:`nodes`: every edge of the
    graph whose two endpoints are both present. An edge leaving the set is not
    carried, because a value whose edges name nodes it does not hold is not a
    sub-DAG — and dropping one is exactly what :attr:`truncated` reports.
    """

    #: The node the walk started from; always a member of :attr:`nodes`.
    root: Node
    #: The direction walked, carried so a caller holding the value alone can
    #: tell "what this is built from" from "what this feeds".
    direction: Direction
    #: Sorted by ``(name, kind)``, matching ``Graph.nodes`` (RFC 0003 §5.3).
    nodes: tuple[Node, ...]
    #: Sorted by ``(src.name, dst.name, label)``, matching ``Graph.edges``.
    edges: tuple[Edge, ...]
    #: ``True`` iff ``max_depth`` stopped the walk at an edge it would
    #: otherwise have followed (D3). Never ``True`` for an unbounded call, so
    #: no default path can return a silent partial.
    truncated: bool = False


def lineage(
    graph: Graph,
    root: Node,
    direction: Direction = Direction.UPSTREAM,
    *,
    max_depth: int | None = None,
) -> Lineage:
    """The sub-DAG reachable from ``root``, walked in ``direction`` (D1).

    **Depth is stated so two implementations cannot disagree** (RFC 0031 §5.1).
    The root is at depth 0. ``max_depth=N`` carries every node within distance
    ``N`` and every edge whose *both* endpoints are carried, so ``max_depth=0``
    returns the root alone with no edges. ``truncated`` is ``True`` iff at least
    one edge was dropped for depth — so a bounded walk from a root with no
    lineage in that direction reports ``False``, because bounding to nothing and
    finding nothing are different facts.

    A negative ``max_depth`` raises :class:`ValueError`. There is no depth below
    the root, so the caller has asked for something with no answer rather than
    for nothing, and an empty result would answer a different question.

    ``root`` need not be a member of ``graph``: a node with no edges and a node
    that is absent are the same lineage, and refusing the second would make the
    caller check membership against a tuple this function is already scanning.

    Requires an acyclic ``graph`` and does not verify it (D5) — ``resolve()``
    raises on a cycle before this can run.
    """
    if max_depth is not None and max_depth < 0:
        msg = f"max_depth must be >= 0 or None, got {max_depth}"
        raise ValueError(msg)

    # Adjacency once, rather than rescanning every edge per level: the walk is
    # otherwise O(depth x |E|) on a graph the caller may hold for many calls.
    # Both maps are built from `graph.edges`, which is already sorted, so the
    # lists inherit that order and nothing here iterates a set into output.
    outgoing: dict[Node, list[Edge]] = {}
    incoming: dict[Node, list[Edge]] = {}
    for edge in graph.edges:
        outgoing.setdefault(edge.src, []).append(edge)
        incoming.setdefault(edge.dst, []).append(edge)
    # Upstream reads an edge backwards, so the step from a node is its incoming
    # edges and the node reached is their `src`.
    step: dict[Node, list[Edge]]
    reached: Callable[[Edge], Node]
    if direction is Direction.UPSTREAM:
        step, reached = incoming, lambda edge: edge.src
    else:
        step, reached = outgoing, lambda edge: edge.dst

    seen: set[Node] = {root}
    frontier: list[Node] = [root]
    truncated = False
    depth = 0
    while frontier:
        if max_depth is not None and depth >= max_depth:
            # Every edge leaving the frontier is one the walk would have
            # followed. It is dropped for depth *unless* its far end is already
            # carried by a shorter path, in which case the induced sub-DAG keeps
            # the edge and nothing was lost.
            truncated = any(
                reached(edge) not in seen for node in frontier for edge in step.get(node, ())
            )
            break
        following: list[Node] = []
        for node in frontier:
            for edge in step.get(node, ()):
                far = reached(edge)
                if far not in seen:
                    seen.add(far)
                    following.append(far)
        frontier = following
        depth += 1

    nodes = tuple(sorted(seen, key=lambda node: (node.name, node.kind.value)))
    edges = tuple(edge for edge in graph.edges if edge.src in seen and edge.dst in seen)
    return Lineage(
        root=root,
        direction=direction,
        nodes=nodes,
        edges=edges,
        truncated=truncated,
    )
