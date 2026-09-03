"""Availability and reachability (RFC 0005 §5.3): missing names *leaves*,
never intermediate metrics, computed over the one shared DAG."""

from __future__ import annotations

import pytest

from bloomery.ir import UnreachableMetric
from bloomery.resolve.graph import build_graph
from bloomery.resolve.metrics import EffectiveMetric, effective_metrics
from bloomery.resolve.reach import available_canonicals, compute_reachability
from support.compiling import load_fixture

pytestmark = pytest.mark.unit


def _metric(
    name: str,
    requires: tuple[str, ...] = (),
    requires_metrics: tuple[str, ...] = (),
) -> EffectiveMetric:
    return EffectiveMetric(
        name=name,
        requires=requires,
        requires_metrics=requires_metrics,
        grain=None,
        additivity="additive",
        agg="sum",
        expr=None,
        ratio=None,
        semi_additive=None,
        cumulative=None,
        derived=None,
        filter=(),
        description=None,
        source_path=f"metrics: metrics.{name}",
    )


def test_availability_reads_the_graph() -> None:
    project, catalog = load_fixture("ecom_basic")
    graph = build_graph(project, catalog, effective_metrics(project, catalog))
    assert available_canonicals(graph) == frozenset({"unit_price", "quantity"})


def test_reachable_metric_with_all_leaves_available() -> None:
    metrics = (_metric("revenue", requires=("unit_price", "quantity")),)
    reachable, unreachable = compute_reachability(metrics, frozenset({"unit_price", "quantity"}))
    assert reachable == ("revenue",)
    assert unreachable == ()


def test_missing_names_the_specific_leaves_sorted() -> None:
    metrics = (_metric("margin", requires=("unit_price", "cogs", "allocations")),)
    reachable, unreachable = compute_reachability(metrics, frozenset({"unit_price"}))
    assert reachable == ()
    assert unreachable == (UnreachableMetric(name="margin", missing=("allocations", "cogs")),)


def test_missing_propagates_leaves_through_requires_metrics() -> None:
    """RFC 0005 §5.3: if AOV requires net_revenue which requires discount, the
    reason is `discount` — the leaf, not the intermediate metric.

    ``via`` carries the intermediate *beside* it rather than in place of it
    (RFC 0022 D11): the fix is still the mapping, and the chain is what the
    reader would otherwise have to re-walk to see why fixing it helps AOV.
    """
    metrics = (
        _metric("aov", requires_metrics=("net_revenue", "order_count")),
        _metric("net_revenue", requires=("unit_price", "discount")),
        _metric("order_count"),
    )
    reachable, unreachable = compute_reachability(metrics, frozenset({"unit_price"}))
    assert reachable == ("order_count",)
    assert unreachable == (
        UnreachableMetric(name="aov", missing=("discount",), via=("net_revenue",)),
        UnreachableMetric(name="net_revenue", missing=("discount",)),
    )


def test_via_names_only_the_blocked_requirements() -> None:
    """``order_count`` is required by AOV and is perfectly reachable, so naming
    it would send the reader to a metric that is fine. Only a requirement that
    is itself blocked is on the path to something missing."""
    metrics = (
        _metric("aov", requires_metrics=("net_revenue", "order_count")),
        _metric("net_revenue", requires=("discount",)),
        _metric("order_count"),
    )
    _reachable, unreachable = compute_reachability(metrics, frozenset())
    aov = next(metric for metric in unreachable if metric.name == "aov")
    assert aov.via == ("net_revenue",)


def test_via_is_the_whole_chain_not_just_the_first_link() -> None:
    """Two hops. A reader fixing ``discount`` wants to know that ``gross`` and
    ``net_revenue`` both unblock with it — otherwise the chain has to be walked
    by hand, which is the walk the compiler just did."""
    metrics = (
        _metric("aov", requires_metrics=("net_revenue",)),
        _metric("net_revenue", requires_metrics=("gross",)),
        _metric("gross", requires=("discount",)),
    )
    _reachable, unreachable = compute_reachability(metrics, frozenset())
    aov = next(metric for metric in unreachable if metric.name == "aov")
    assert aov.missing == ("discount",)
    assert aov.via == ("gross", "net_revenue")


def test_via_is_empty_when_the_metric_is_blocked_on_its_own_leaves() -> None:
    metrics = (_metric("margin", requires=("cogs",)),)
    _reachable, unreachable = compute_reachability(metrics, frozenset())
    assert unreachable == (UnreachableMetric(name="margin", missing=("cogs",), via=()),)


def test_leafless_metric_is_trivially_reachable() -> None:
    reachable, unreachable = compute_reachability((_metric("order_count"),), frozenset())
    assert reachable == ("order_count",)
    assert unreachable == ()
