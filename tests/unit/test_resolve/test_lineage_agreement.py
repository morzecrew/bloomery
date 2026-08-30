"""One relationship with two implementations, asserted to agree
(RFC 0031 §6, D7).

The battery does not test `lineage()` alone. It pins a fact that is computed
twice in this tree by different code reading the same graph, which is the
`reading-isnt-proof` case: if they disagree, one of them is wrong and a spot
check would not say which.

- **Reachability.** `compute_reachability` names the unavailable leaves that
  block a metric. The same leaves are the unavailable canonical fields in that
  metric's upstream lineage — the negative case of the general walk.

**Provenance used to be the second pair, and is not one any more.** RFC 0031 D7
shipped `_field_provenance`'s parallel read of `entity.fields[...].canonical`
beside the graph's `canonical` edges with a test holding them to the same 146
answers, so that unifying them later would be a refactor rather than a
rediscovery. It since was: the `DIRECT`/`NATIVE` decision reads those edges —
the same ones `available_canonicals` reads — and comparing it against them now
would compare the graph to itself.

The `RECIPE` half stayed with the mappings rather than moving, and the reason is
worth recording where the old test was: a `recipe:<id>` label rides on the edges
a field's `from:` aliases draw, and an alias-bound field may bind none, so the
graph is a lossy account of *that* fact and no test between them could have been
green in both directions. `test_edge_shapes_offcorpus.py` holds the two shapes
that show it. What the corpus still checks about these records lives with the
other things `resolve()` returns, in `test_resolution.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bloomery import Direction, Lineage, lineage, load_catalog, load_project, resolve
from bloomery.cli import io
from bloomery.resolve.graph import NodeKind, metric_node
from bloomery.resolve.reach import available_canonicals
from support.compiling import spec_fixture_names

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
    for name in spec_fixture_names():
        sources, catalog_text = io.read_spec_directory(str(FIXTURES / name))
        catalog = load_catalog(catalog_text) if catalog_text else None
        out.append((name, resolve(load_project(sources), catalog)))
    return out


def unavailable_in(walk: Lineage, available: frozenset[str]) -> set[str]:
    """The canonical fields in a walk that are not available.

    Extracted because both batteries below need it and a copy that drifts would
    make two implementations agree about the wrong fact — precisely the failure
    a two-implementation battery exists to catch. It takes the walk rather than
    performing one, so a caller needing both the set and the walk pays for one
    traversal.
    """
    return {
        node.name.removeprefix(CANONICAL_PREFIX)
        for node in walk.nodes
        if node.kind is NodeKind.CANONICAL_FIELD
        and node.name.removeprefix(CANONICAL_PREFIX) not in available
    }


def test_every_spec_fixture_resolves() -> None:
    """Named rather than counted. A floor cannot tell a fixture that stopped
    resolving from one that never existed, and both batteries below are only as
    wide as this sweep."""
    assert [name for name, _r in resolved_fixtures()] == list(spec_fixture_names())


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
            upstream_unavailable = unavailable_in(walk, available)
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
            unavailable = unavailable_in(walk, available)
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
