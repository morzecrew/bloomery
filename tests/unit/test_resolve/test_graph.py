"""The single dependency DAG (RFC 0005 §5.1): node id scheme (pinned — it
reaches CircularDerivation messages and topo output), edge labels, sorting."""

from __future__ import annotations

import pytest

from bloomery import load_project
from bloomery.spec import Project
from bloomery.resolve.graph import (
    NodeKind,
    build_graph,
    canonical_field_node,
    entity_field_node,
    metric_node,
    source_column_node,
    step_node,
)
from bloomery.resolve.metrics import effective_metrics
from support.compiling import load_fixture

pytestmark = pytest.mark.unit

STEP_WIRING = """
steps_version: 1
steps:
  - use: resolve_customers@3
    inputs: {raw: silver.customer_raw}
    outputs: {customer: silver.customer}
"""


@pytest.fixture
def step_project() -> Project:
    return load_project(
        {"entity_model": "spec_version: 1\nentities: {}\n", "steps": STEP_WIRING}
    )


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


def test_node_kinds_cover_the_step_free_vocabulary() -> None:
    """``ecom_basic`` wires no step, so it exercises every kind but one. The
    claim worth keeping is that the vocabulary is *covered*, which is why the
    step half is asserted separately rather than by weakening this to a
    subset check."""
    project, catalog = load_fixture("ecom_basic")
    graph = build_graph(project, catalog, effective_metrics(project, catalog))
    assert {n.kind for n in graph.nodes} == set(NodeKind) - {NodeKind.STEP}


def test_a_wired_step_is_a_first_class_node(step_project: Project) -> None:
    """RFC 0017 D11: steps are DAG citizens. Both edge directions matter — the
    input edge puts the step downstream of what fills it, the output edge puts
    its produced fields downstream of the step, and it is the second that lets
    `plan()` compute a backfill *across* a step (§4)."""
    graph = build_graph(step_project, None, ())
    step = step_node("resolve_customers")
    assert step in graph.nodes
    labels = {(e.src.name, e.dst.name, e.label) for e in graph.edges}
    assert ("customer_raw.*", "step.resolve_customers", "step_input") in labels
    assert ("step.resolve_customers", "customer.*", "step_output") in labels


def test_a_step_with_no_wired_inputs_still_appears() -> None:
    """It exists in the lineage regardless; without the explicit node it would
    vanish from the topological order entirely (the catalog/metrics
    precedent)."""
    project = load_project(
        {
            "entity_model": "spec_version: 1\nentities: {}\n",
            "steps": (
                "steps_version: 1\nsteps:\n  - use: resolve_customers@3\n"
                "    outputs: {customer: silver.customer}\n"
            ),
        }
    )
    graph = build_graph(project, None, ())
    assert step_node("resolve_customers") in graph.nodes
