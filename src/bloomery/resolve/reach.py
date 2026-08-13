"""Availability and metric reachability (RFC 0005 §5.3).

A canonical field is *available* iff some mapped entity field links to it via
``canonical:`` (with a direct mapping or a validated recipe — recipe
validation has already run). A metric is *reachable* iff every leaf of its
transitive ``requires``/``requires_metrics`` closure is available.

Unreachable metrics are results, not errors: ``missing`` names the specific
unavailable *leaves* — never intermediate metrics — because "you can't get
margin because ``cogs`` is missing" is the actionable, product-facing fact
(RFC 0005 D3). Computed only on an acyclic, reference-clean graph (cycles
raise first), so ``missing`` can never mask a structural failure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bloomery.ir import UnreachableMetric

if TYPE_CHECKING:
    from bloomery.resolve.graph import Graph
    from bloomery.resolve.metrics import EffectiveMetric

__all__ = [
    "available_canonicals",
    "compute_reachability",
]

_CANONICAL_PREFIX = "canonical."


def available_canonicals(graph: Graph) -> frozenset[str]:
    """Canonical fields with at least one incoming ``canonical`` edge — read
    from the one shared DAG (RFC 0005 D1), never recomputed from specs."""
    return frozenset(
        edge.dst.name.removeprefix(_CANONICAL_PREFIX)
        for edge in graph.edges
        if edge.label == "canonical"
    )


def compute_reachability(
    metrics: tuple[EffectiveMetric, ...], available: frozenset[str]
) -> tuple[tuple[str, ...], tuple[UnreachableMetric, ...]]:
    """Split metrics into (reachable names, unreachable + missing leaves),
    both sorted by name (RFC 0003 §5.3).

    ``missing`` names leaves and never intermediate metrics, which is D3's rule
    and the right one: the fix is always a mapping, never a metric. But for a
    metric blocked *through* another — ``average_order_value`` blocked because
    ``gross_revenue`` is — the leaf alone leaves the reader to rediscover the
    chain the compiler just walked. ``via`` records it: the required metrics
    that are themselves blocked, so "you cannot get ``average_order_value``
    because ``cogs`` is unmapped" gains "…and what it is blocking on the way is
    ``gross_revenue``".
    """
    by_name = {metric.name: metric for metric in metrics}
    memo: dict[str, tuple[frozenset[str], frozenset[str]]] = {}

    def blockage(name: str) -> tuple[frozenset[str], frozenset[str]]:
        """``(missing leaves, blocked metrics between here and them)``.

        Recursion is safe unmemoized-depth-wise because cycles raise before
        this runs (RFC 0005): reachability is computed on an acyclic,
        reference-clean graph, so ``missing`` can never mask a structural
        failure.
        """
        cached = memo.get(name)
        if cached is not None:
            return cached
        metric = by_name[name]
        missing = frozenset(leaf for leaf in metric.requires if leaf not in available)
        via: frozenset[str] = frozenset()
        for required in metric.requires_metrics:
            required_missing, required_via = blockage(required)
            if required_missing:
                # Only a *blocked* requirement joins the chain. A reachable one
                # is not on the path to anything missing, and naming it would
                # send the reader to a metric that is fine.
                missing |= required_missing
                via |= {required, *required_via}
        memo[name] = (missing, via)
        return memo[name]

    reachable: list[str] = []
    unreachable: list[UnreachableMetric] = []
    for metric in metrics:  # already sorted by name (effective_metrics)
        missing, via = blockage(metric.name)
        if missing:
            unreachable.append(
                UnreachableMetric(
                    name=metric.name, missing=tuple(sorted(missing)), via=tuple(sorted(via))
                )
            )
        else:
            reachable.append(metric.name)
    return tuple(reachable), tuple(unreachable)
