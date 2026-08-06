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
    reason is `discount` — the leaf, not the intermediate metric."""
    metrics = (
        _metric("aov", requires_metrics=("net_revenue", "order_count")),
        _metric("net_revenue", requires=("unit_price", "discount")),
        _metric("order_count"),
    )
    reachable, unreachable = compute_reachability(metrics, frozenset({"unit_price"}))
    assert reachable == ("order_count",)
    assert unreachable == (
        UnreachableMetric(name="aov", missing=("discount",)),
        UnreachableMetric(name="net_revenue", missing=("discount",)),
    )


def test_leafless_metric_is_trivially_reachable() -> None:
    reachable, unreachable = compute_reachability((_metric("order_count"),), frozenset())
    assert reachable == ("order_count",)
    assert unreachable == ()
