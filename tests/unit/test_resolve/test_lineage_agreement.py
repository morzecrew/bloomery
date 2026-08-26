"""Two relationships with two implementations each, asserted to agree
(RFC 0031 §6, D7).

Neither battery tests `lineage()` alone. Each pins a fact that is computed
twice in this tree by different code reading the same graph, which is the
`reading-isnt-proof` case: if they disagree, one of them is wrong and a spot
check would not say which.

- **Provenance.** `_field_provenance` walks the *project's mappings*; the graph
  encodes the same fact in its edges. RFC 0031 D7 keeps both deliberately and
  makes this the check that keeps them honest, so that whoever unifies them
  later starts from a green test rather than an assumption.
- **Reachability.** `compute_reachability` names the unavailable leaves that
  block a metric. The same leaves are the unavailable canonical fields in that
  metric's upstream lineage — the negative case of the general walk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bloomery import Direction, lineage, load_catalog, load_project, resolve
from bloomery.cli import io
from bloomery.resolve.graph import NodeKind, entity_field_node, metric_node
from bloomery.resolve.reach import available_canonicals
from bloomery.resolve.resolution import Provenance

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parents[3] / "tests" / "fixtures"
CANONICAL_PREFIX = "canonical."


def resolved_fixtures() -> list[tuple[str, object]]:
    """Every fixture that loads and resolves, with its `Resolution`.

    `Resolution` now carries the graph it was computed from (D2), which is what
    lets both batteries below read *the* graph rather than rebuilding one that
    might differ.
    """
    out = []
    for directory in sorted(FIXTURES.iterdir()):
        if not directory.is_dir():
            continue
        try:
            sources, catalog_text = io.read_spec_directory(str(directory))
            project = load_project(sources)
            catalog = load_catalog(catalog_text) if catalog_text else None
            out.append((directory.name, resolve(project, catalog)))
        except Exception:  # noqa: BLE001 — a fixture that cannot resolve is not the subject
            continue
    return out


def test_the_corpus_resolves_widely_enough_to_prove_anything() -> None:
    assert len(resolved_fixtures()) >= 15


def test_graph_edges_and_field_provenance_agree() -> None:
    """`RECIPE` iff an incoming `recipe:` edge; `DIRECT` iff an outgoing
    `canonical` edge; `NATIVE` iff neither.

    The order matters and is the part a reading gets wrong: a recipe field may
    *also* carry a canonical link, so `recipe:` is checked first. And `DIRECT`
    is decided by the canonical link rather than by an incoming `direct` edge —
    every non-recipe mapped field has one of those whether or not it links to a
    canonical, so that edge cannot separate `DIRECT` from `NATIVE`.
    """
    checked = 0
    for name, resolution in resolved_fixtures():
        graph = resolution.graph  # type: ignore[attr-defined]
        incoming: dict[str, set[str]] = {}
        linked: set[str] = set()
        for edge in graph.edges:
            incoming.setdefault(edge.dst.name, set()).add(edge.label)
            if edge.label == "canonical":
                linked.add(edge.src.name)

        for record in resolution.provenance:  # type: ignore[attr-defined]
            node_name = entity_field_node(record.entity, record.field).name
            labels = incoming.get(node_name, set())
            if any(label.startswith("recipe:") for label in labels):
                expected = Provenance.RECIPE
            elif node_name in linked:
                expected = Provenance.DIRECT
            else:
                expected = Provenance.NATIVE
            assert record.provenance is expected, (
                f"{name}: {node_name} is {record.provenance} "
                f"but the graph says {expected} (labels={sorted(labels)})"
            )
            checked += 1

    assert checked >= 140, f"only {checked} provenance records compared"


def test_unreachable_missing_leaves_are_the_unavailable_canonicals_upstream() -> None:
    """`compute_reachability`'s `missing` and the upstream walk are the same
    fact reached two ways.

    A metric is unreachable because some leaf it needs is unavailable. Walking
    upstream from the metric reaches every canonical field it depends on,
    transitively through `requires_metrics`; the unavailable ones among those
    are exactly `missing`.
    """
    compared = 0
    for name, resolution in resolved_fixtures():
        graph = resolution.graph  # type: ignore[attr-defined]
        available = available_canonicals(graph)
        for unreachable in resolution.unreachable_metrics:  # type: ignore[attr-defined]
            walk = lineage(graph, metric_node(unreachable.name), Direction.UPSTREAM)
            upstream_unavailable = {
                node.name.removeprefix(CANONICAL_PREFIX)
                for node in walk.nodes
                if node.kind is NodeKind.CANONICAL_FIELD
                and node.name.removeprefix(CANONICAL_PREFIX) not in available
            }
            assert upstream_unavailable == set(unreachable.missing), (
                f"{name}: {unreachable.name} is blocked on {sorted(unreachable.missing)} "
                f"but its upstream lineage says {sorted(upstream_unavailable)}"
            )
            compared += 1

    assert compared > 0, "no unreachable metric in the corpus — this battery proved nothing"


def test_reachable_metrics_have_no_unavailable_canonical_upstream() -> None:
    """The converse, which is what stops the battery above passing vacuously.

    Without it, a `lineage()` that returned nothing at all would satisfy the
    unreachable case for any metric whose `missing` happened to be empty.
    """
    compared = reached_something = 0
    for name, resolution in resolved_fixtures():
        graph = resolution.graph  # type: ignore[attr-defined]
        available = available_canonicals(graph)
        for metric_name in resolution.reachable_metrics:  # type: ignore[attr-defined]
            walk = lineage(graph, metric_node(metric_name), Direction.UPSTREAM)
            unavailable = {
                node.name.removeprefix(CANONICAL_PREFIX)
                for node in walk.nodes
                if node.kind is NodeKind.CANONICAL_FIELD
                and node.name.removeprefix(CANONICAL_PREFIX) not in available
            }
            assert not unavailable, f"{name}: {metric_name} is reachable but {unavailable} is not"
            compared += 1
            reached_something += len(walk.nodes) > 1

    assert compared > 0, "no reachable metric in the corpus"
    # Non-vacuity, at corpus level rather than per metric. A `lineage()` that
    # returned only its root would satisfy the assertion above for free — but
    # *some* metrics legitimately have no upstream at all: `ecom_basic`'s
    # `order_count` is `agg: count` with `requires=()`, so it depends on no
    # canonical field and its empty walk is the right answer, not a miss. That
    # is the case §5.5 has in mind when it says an empty lineage is an answer.
    assert reached_something > 0, "every reachable metric returned a bare root"
