"""Cycle detection and the topological emission order (RFC 0005 §5.4).

Emission order is Kahn's algorithm over a sorted ready-heap — ties broken
lexicographically by node name, never by set iteration. This is the package's
main determinism hazard (spec §5.2), contained here: the sort is implemented
once and every consumer takes the order from ``Resolution``.

Any cycle raises :class:`~bloomery.errors.CircularDerivation` naming the full
cycle path, rotated to start at the lexicographically smallest node so the
same cycle always prints identically (RFC 0005 D4).
"""

from __future__ import annotations

import heapq
from typing import TYPE_CHECKING

from bloomery.errors import CircularDerivation

if TYPE_CHECKING:
    from bloomery.resolve.graph import Graph, Node

__all__ = [
    "toposort",
]


def _find_cycle(remaining: set[str], predecessors: dict[str, list[str]]) -> list[str]:
    """One cycle among ``remaining`` nodes, in dependency → dependent order.

    Every remaining node has a predecessor in ``remaining`` (edges from
    emitted nodes were already consumed), so walking smallest-predecessor
    links from the smallest remaining node must revisit a node.
    """
    start = min(remaining)
    path = [start]
    seen = {start: 0}
    current = start
    while True:
        current = min(name for name in predecessors[current] if name in remaining)
        if current in seen:
            walked = path[seen[current] :]
            walked.reverse()  # predecessor walk → dependency → dependent order
            pivot = walked.index(min(walked))
            return walked[pivot:] + walked[:pivot]
        seen[current] = len(path)
        path.append(current)


def toposort(graph: Graph) -> tuple[Node, ...]:
    """The deterministic topological order of the DAG (RFC 0005 D5)."""
    by_name = {node.name: node for node in graph.nodes}
    indegree = dict.fromkeys(by_name, 0)
    successors: dict[str, list[str]] = {name: [] for name in by_name}
    predecessors: dict[str, list[str]] = {name: [] for name in by_name}
    for edge in graph.edges:
        indegree[edge.dst.name] += 1
        successors[edge.src.name].append(edge.dst.name)
        predecessors[edge.dst.name].append(edge.src.name)

    ready = sorted(name for name, degree in indegree.items() if degree == 0)
    order: list[Node] = []
    while ready:
        name = heapq.heappop(ready)
        order.append(by_name[name])
        for successor in successors[name]:
            indegree[successor] -= 1
            if indegree[successor] == 0:
                heapq.heappush(ready, successor)

    if len(order) != len(graph.nodes):
        remaining = {name for name, degree in indegree.items() if degree > 0}
        cycle = _find_cycle(remaining, predecessors)
        rendered = " → ".join([*cycle, cycle[0]])
        msg = f"circular derivation: {rendered}"
        raise CircularDerivation(msg)
    return tuple(order)
