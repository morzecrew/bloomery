"""Lineage traversal (RFC 0031 §6): the sub-DAG shape, the depth boundary and
its ``truncated`` flag, and determinism of the emitted order.

Graphs here are hand-built. The traversal's contract is about *shape* — a
diamond, a chain, a leaf — and building those from fixtures would couple every
assertion to whichever project happens to have the shape today, which is the
coupling RFC 0031 D6 already records as having cost the label table two rows.
"""

from __future__ import annotations

import pytest

from bloomery import Direction, Lineage, lineage
from bloomery.resolve.graph import Edge, Graph, Node, NodeKind

pytestmark = pytest.mark.unit


def node(name: str, kind: NodeKind = NodeKind.ENTITY_FIELD) -> Node:
    return Node(kind=kind, name=name)


def graph_of(*edges: tuple[str, str, str]) -> Graph:
    """A graph from ``(src, dst, label)`` triples, sorted as ``build_graph``
    sorts — so a test never depends on the order it wrote its edges in."""
    built = tuple(Edge(src=node(src), dst=node(dst), label=label) for src, dst, label in edges)
    nodes = {edge.src for edge in built} | {edge.dst for edge in built}
    return Graph(
        nodes=tuple(sorted(nodes, key=lambda n: n.name)),
        edges=tuple(sorted(built, key=lambda e: (e.src.name, e.dst.name, e.label))),
    )


#: a → b → d and a → c → d: `d` is reachable from `a` by two distinct paths.
DIAMOND = graph_of(
    ("a", "b", "direct"),
    ("a", "c", "direct"),
    ("b", "d", "direct"),
    ("c", "d", "direct"),
)
#: a → b → c → d, one node per level.
CHAIN = graph_of(("a", "b", "direct"), ("b", "c", "direct"), ("c", "d", "direct"))


# ....................... #
# Shape (D1): a sub-DAG, never enumerated paths


def test_diamond_carries_the_shared_node_once_and_both_its_edges() -> None:
    """The claim that makes D1 a sub-DAG rather than paths: a node reachable
    two ways appears **once** in ``nodes`` and **twice** in ``edges``.

    Enumerating paths would give two routes and duplicate every node on them,
    which is the exponential output D1 refuses.
    """
    result = lineage(DIAMOND, node("d"), Direction.UPSTREAM)

    assert [n.name for n in result.nodes] == ["a", "b", "c", "d"]
    assert [n.name for n in result.nodes].count("a") == 1
    assert sorted((e.src.name, e.dst.name) for e in result.edges) == [
        ("a", "b"),
        ("a", "c"),
        ("b", "d"),
        ("c", "d"),
    ]
    assert result.truncated is False
    assert result.root == node("d")
    assert result.direction is Direction.UPSTREAM


def test_edges_are_induced_on_nodes_never_dangling() -> None:
    """Every edge names two nodes the value also carries.

    This is what makes ``Lineage`` self-contained: a caller can render it
    without holding the graph it came from.
    """
    for depth in (None, 0, 1, 2, 3):
        result = lineage(DIAMOND, node("d"), Direction.UPSTREAM, max_depth=depth)
        carried = set(result.nodes)
        assert all(e.src in carried and e.dst in carried for e in result.edges)


def test_downstream_is_the_other_direction_over_the_same_graph() -> None:
    upstream = lineage(CHAIN, node("d"), Direction.UPSTREAM)
    downstream = lineage(CHAIN, node("a"), Direction.DOWNSTREAM)

    assert [n.name for n in upstream.nodes] == ["a", "b", "c", "d"]
    assert [n.name for n in downstream.nodes] == ["a", "b", "c", "d"]
    # The root is a member of its own lineage in both directions.
    assert upstream.root in upstream.nodes
    assert downstream.root in downstream.nodes


def test_a_root_with_no_lineage_is_one_node_and_not_an_error() -> None:
    """A source column has no upstream, and that is an answer.

    The empty case must be a *value*, because the caller that asked "where does
    this come from" of a leaf needs "nowhere, it is a leaf" rather than a raise.
    """
    result = lineage(CHAIN, node("a"), Direction.UPSTREAM)

    assert result.nodes == (node("a"),)
    assert result.edges == ()
    assert result.truncated is False


def test_a_node_absent_from_the_graph_has_the_same_empty_lineage() -> None:
    result = lineage(CHAIN, node("nowhere"), Direction.UPSTREAM)

    assert result.nodes == (node("nowhere"),)
    assert result.edges == ()


# ....................... #
# The depth boundary (D3), stated in §5.1 so two implementations agree


def test_max_depth_zero_is_the_root_alone() -> None:
    result = lineage(CHAIN, node("d"), Direction.UPSTREAM, max_depth=0)

    assert result.nodes == (node("d"),)
    assert result.edges == ()
    assert result.truncated is True


def test_each_depth_adds_exactly_one_node_and_one_edge_on_a_chain() -> None:
    """``N`` and ``N+1`` differ by one node and one edge, which is what pins
    "distance ≤ N" against an off-by-one in either direction."""
    sizes = [
        (len(lineage(CHAIN, node("d"), Direction.UPSTREAM, max_depth=n).nodes),
         len(lineage(CHAIN, node("d"), Direction.UPSTREAM, max_depth=n).edges))
        for n in range(4)
    ]
    assert sizes == [(1, 0), (2, 1), (3, 2), (4, 3)]


def test_truncated_is_true_until_the_depth_that_first_reaches_the_leaf() -> None:
    """The flag's whole job: ``depth`` reaches everything and reports ``False``;
    ``depth - 1`` stopped short and reports ``True``."""
    assert lineage(CHAIN, node("d"), Direction.UPSTREAM, max_depth=2).truncated is True
    assert lineage(CHAIN, node("d"), Direction.UPSTREAM, max_depth=3).truncated is False
    # Past the end is still not a truncation — there was nothing left to drop.
    assert lineage(CHAIN, node("d"), Direction.UPSTREAM, max_depth=99).truncated is False


def test_bounded_to_nothing_and_nothing_there_are_different_facts() -> None:
    """``max_depth=0`` on a root with no lineage is **not** truncated.

    Both calls return one node and no edges, and only one of them stopped
    looking. Without this the flag would say "partial" for an answer that is
    complete, which is the mirror of the failure RFC 0022 D5 names.
    """
    assert lineage(CHAIN, node("a"), Direction.UPSTREAM, max_depth=0).truncated is False
    assert lineage(CHAIN, node("d"), Direction.UPSTREAM, max_depth=0).truncated is True


def test_an_edge_to_an_already_carried_node_is_not_a_truncation() -> None:
    """A diamond at exactly the depth that carries both branches keeps the
    second edge into the shared node, so nothing was dropped.

    This is the case a naive "did the frontier have any edges?" check gets
    wrong: at depth 2 the frontier still has edges, and both of their far ends
    are already present.
    """
    result = lineage(DIAMOND, node("d"), Direction.UPSTREAM, max_depth=2)

    assert [n.name for n in result.nodes] == ["a", "b", "c", "d"]
    assert len(result.edges) == 4
    assert result.truncated is False


def test_a_negative_max_depth_raises() -> None:
    """There is no depth below the root, so this is a question with no answer
    rather than a question whose answer is empty."""
    with pytest.raises(ValueError, match="max_depth must be >= 0 or None"):
        lineage(CHAIN, node("d"), Direction.UPSTREAM, max_depth=-1)


# ....................... #
# Determinism (RFC 0003 §5.3): the visited set is where this breaks


def test_order_is_stable_across_calls_and_matches_the_declared_sort() -> None:
    first = lineage(DIAMOND, node("d"), Direction.UPSTREAM)
    again = lineage(DIAMOND, node("d"), Direction.UPSTREAM)

    assert first == again
    assert list(first.nodes) == sorted(first.nodes, key=lambda n: (n.name, n.kind.value))
    assert list(first.edges) == sorted(
        first.edges, key=lambda e: (e.src.name, e.dst.name, e.label)
    )


def test_order_does_not_depend_on_the_hash_seed() -> None:
    """The walk holds a ``set`` of visited nodes, and a set iterated into
    output is precisely what RFC 0003 bans. Two interpreters with different
    hash seeds must agree byte for byte."""
    import subprocess
    import sys

    program = (
        "from bloomery import Direction, lineage;"
        "from bloomery.resolve.graph import Edge, Graph, Node, NodeKind;"
        "n=lambda s: Node(kind=NodeKind.ENTITY_FIELD, name=s);"
        "es=tuple(Edge(src=n(a), dst=n(b), label='direct')"
        " for a,b in (('a','b'),('a','c'),('b','d'),('c','d')));"
        "ns=tuple(sorted({e.src for e in es}|{e.dst for e in es}, key=lambda x: x.name));"
        "g=Graph(nodes=ns, edges=tuple(sorted(es, key=lambda e:(e.src.name,e.dst.name,e.label))));"
        "r=lineage(g, n('d'), Direction.UPSTREAM);"
        "print([x.name for x in r.nodes], [(e.src.name,e.dst.name) for e in r.edges])"
    )
    runs = {
        subprocess.run(  # noqa: S603
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            check=True,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
        ).stdout
        for seed in ("0", "1", "42", "12345")
    }
    assert len(runs) == 1, f"hash seed changed the output: {runs}"


def test_a_direction_given_as_a_plain_string_walks_that_direction() -> None:
    """`Direction` is a `StrEnum`, so `Direction.UPSTREAM == "upstream"` and the
    API invites a caller — or a CLI parsing argv — to pass the string.

    Compared by identity it would silently walk the *other* way and record the
    requested direction on the value, so the result would misreport itself.
    """
    for spelling in (Direction.UPSTREAM, "upstream"):
        walked = lineage(CHAIN, node("d"), spelling)  # type: ignore[arg-type]
        assert [n.name for n in walked.nodes] == ["a", "b", "c", "d"]
        assert walked.direction is Direction.UPSTREAM

    for spelling in (Direction.DOWNSTREAM, "downstream"):
        walked = lineage(CHAIN, node("a"), spelling)  # type: ignore[arg-type]
        assert [n.name for n in walked.nodes] == ["a", "b", "c", "d"]
        assert walked.direction is Direction.DOWNSTREAM


def test_an_unknown_direction_is_refused_including_the_deferred_both() -> None:
    """`both` is the P2 member D4 has not shaped yet. A caller spelling it must
    get a refusal rather than a silent downstream walk."""
    for spelling in ("both", "sideways", ""):
        with pytest.raises(ValueError, match="is not a valid Direction"):
            lineage(CHAIN, node("d"), spelling)  # type: ignore[arg-type]


def test_a_disconnected_node_in_the_graph_has_an_empty_lineage() -> None:
    """§6's "disconnected node": present in `nodes`, named by no edge. Distinct
    from a node absent from the graph, and from a node with edges on one side
    only — all three must answer, and none may raise."""
    isolated = Graph(nodes=(node("lonely"), node("a")), edges=())
    for direction in (Direction.UPSTREAM, Direction.DOWNSTREAM):
        walked = lineage(isolated, node("lonely"), direction)
        assert walked.nodes == (node("lonely"),)
        assert walked.edges == ()
        assert walked.truncated is False


def test_an_empty_graph_answers_rather_than_raising() -> None:
    walked = lineage(Graph(nodes=(), edges=()), node("x"), Direction.UPSTREAM)
    assert walked.nodes == (node("x"),)
    assert walked.edges == ()


def test_lineage_is_a_frozen_value() -> None:
    result = lineage(CHAIN, node("d"), Direction.UPSTREAM)
    assert isinstance(result, Lineage)
    with pytest.raises(AttributeError):
        result.truncated = True  # type: ignore[misc]
