"""The single dependency DAG (RFC 0005 §5.1): node id scheme (pinned — it
reaches CircularDerivation messages and topo output), edge labels, sorting."""

from __future__ import annotations

import pytest

from bloomery.resolve.graph import (
    NodeKind,
    build_graph,
    canonical_field_node,
    entity_field_node,
    metric_node,
    source_column_node,
)
from bloomery.resolve.metrics import effective_metrics
from support.compiling import load_fixture

pytestmark = pytest.mark.unit


def test_node_id_scheme_is_kind_prefixed() -> None:
    assert source_column_node("shopify__order_lines", "$.total").name == (
        "source.shopify__order_lines.$.total"
    )
    assert entity_field_node("order_item", "unit_price").name == "order_item.unit_price"
    assert canonical_field_node("unit_price").name == "canonical.unit_price"
    assert metric_node("gross_revenue").name == "metric.gross_revenue"


def test_ecom_graph_edges_and_labels() -> None:
    project, catalog = load_fixture("ecom_basic")
    graph = build_graph(project, catalog, effective_metrics(project, catalog))

    labels = {(e.src.name, e.dst.name): e.label for e in graph.edges}
    # Recipe alias bindings: one edge per alias, labeled recipe:<id>.
    assert labels["source.shopify__order_lines.$.total", "order_item.unit_price"] == (
        "recipe:from_total"
    )
    assert labels["source.shopify__order_lines.$.qty", "order_item.unit_price"] == (
        "recipe:from_total"
    )
    # Direct mappings.
    assert labels["source.shopify__order_lines.$.qty", "order_item.quantity"] == "direct"
    assert labels["source.shopify__orders.$.id", "order.order_id"] == "direct"
    # canonical: links and metric requires.
    assert labels["order_item.unit_price", "canonical.unit_price"] == "canonical"
    assert labels["canonical.unit_price", "metric.gross_revenue"] == "requires"
    assert labels["metric.gross_revenue", "metric.average_order_value"] == "requires_metrics"
    # The unmapped canonical leaf has a node (from the catalog) but no
    # incoming canonical edge.
    assert canonical_field_node("cogs") in graph.nodes
    assert not any(e.dst.name == "canonical.cogs" and e.label == "canonical" for e in graph.edges)


def test_graph_collections_are_sorted() -> None:
    project, catalog = load_fixture("ecom_basic")
    graph = build_graph(project, catalog, effective_metrics(project, catalog))
    assert [n.name for n in graph.nodes] == sorted(n.name for n in graph.nodes)
    keys = [(e.src.name, e.dst.name, e.label) for e in graph.edges]
    assert keys == sorted(keys)


def test_node_kinds_cover_all_four() -> None:
    project, catalog = load_fixture("ecom_basic")
    graph = build_graph(project, catalog, effective_metrics(project, catalog))
    assert {n.kind for n in graph.nodes} == set(NodeKind)
