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

# ----------------------- #

__all__ = [
    "toposort",
]

#: A node's identity here: its name paired with its kind, which is exactly the
#: key ``build_graph`` already sorts ``Graph.nodes`` by.
#:
#: **Not the name alone.** An entity-field id carries no kind prefix
#: (``<entity>.<field>``), so it can collide with any other kind's: an entity
#: named ``metric`` with a field ``revenue`` produces ``metric.revenue``, and so
#: does a metric named ``revenue``. Keyed by name, the two collapsed into one
#: entry, ``len(order)`` then disagreed with ``len(graph.nodes)`` on a graph
#: with no cycle, and the cycle path ran — where ``remaining`` was empty,
#: because nothing was actually blocked, and ``min()`` raised a bare
#: ``ValueError`` out of a package that promises named refusals.
#:
#: Keying by it also makes the length comparison below mean "a cycle" and
#: nothing else. ``build_graph`` collects its nodes into a ``set``, so its
#: graphs never repeat one — but ``Graph`` is a public frozen dataclass holding
#: a plain tuple, and a caller assembling one by hand can list a node twice.
#: Compared against ``len(graph.nodes)`` that repeat was indistinguishable from
#: a node the walk never reached, which is the same bare ``ValueError`` on the
#: same empty ``remaining``. Compared against ``len(by_key)`` it is not: a
#: repeated node collapses to the one node it names, which is what listing it
#: twice meant.
#:
#: **The other fix was to make the ids themselves unique**, giving entity fields
#: a kind prefix as every other kind already has, which would remove the
#: collision rather than accommodate it. It is the better shape and it is not
#: this change: those ids are printed by ``bloomery lineage``, pinned by tests,
#: and rendered into ``CircularDerivation`` messages (RFC 0005 §9), so it moves
#: a published spelling and belongs in a change that says so on the tin.
_NodeKey = tuple[str, str]


def _key(node: Node) -> _NodeKey:
    return (node.name, node.kind.value)


# ....................... #


def _find_cycle(
    remaining: set[_NodeKey], predecessors: dict[_NodeKey, list[_NodeKey]]
) -> list[_NodeKey]:
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
        current = min(key for key in predecessors[current] if key in remaining)
        if current in seen:
            walked = path[seen[current] :]
            walked.reverse()  # predecessor walk → dependency → dependent order
            pivot = walked.index(min(walked))
            return walked[pivot:] + walked[:pivot]
        seen[current] = len(path)
        path.append(current)


# ....................... #


def toposort(graph: Graph) -> tuple[Node, ...]:
    """The deterministic topological order of the DAG (RFC 0005 D5)."""
    by_key = {_key(node): node for node in graph.nodes}
    indegree = dict.fromkeys(by_key, 0)
    successors: dict[_NodeKey, list[_NodeKey]] = {key: [] for key in by_key}
    predecessors: dict[_NodeKey, list[_NodeKey]] = {key: [] for key in by_key}

    for edge in graph.edges:
        indegree[_key(edge.dst)] += 1
        successors[_key(edge.src)].append(_key(edge.dst))
        predecessors[_key(edge.dst)].append(_key(edge.src))

    # The heap orders by the key, so a tie on name breaks on kind — the same
    # total order `Graph.nodes` carries, rather than a second one that could
    # disagree with it.
    ready = sorted(key for key, degree in indegree.items() if degree == 0)
    order: list[Node] = []

    while ready:
        key = heapq.heappop(ready)
        order.append(by_key[key])
        for successor in successors[key]:
            indegree[successor] -= 1
            if indegree[successor] == 0:
                heapq.heappush(ready, successor)

    if len(order) != len(by_key):
        remaining = {key for key, degree in indegree.items() if degree > 0}
        cycle = _find_cycle(remaining, predecessors)
        # Names alone, not keys: the message is a lineage path a reader retypes,
        # and RFC 0005 D4 pins its rendering. Two colliding ids print the same
        # name here, which is the honest rendering of a project in which they
        # *are* the same id.
        rendered = " → ".join([name for name, _kind in [*cycle, cycle[0]]])
        msg = f"circular derivation: {rendered}"
        raise CircularDerivation(msg)

    return tuple(order)
