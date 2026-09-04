"""The single dependency DAG (RFC 0005 §5.1): node id scheme (pinned — it
reaches CircularDerivation messages and topo output), edge labels, sorting."""

from __future__ import annotations

import pytest

from bloomery import load_project
from bloomery.ir import NODE_ID_PREFIXES
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

STEP_ENTITIES = """
spec_version: 1
entities:
  customer_raw:
    grain: one row per source row
    key: [source_id]
    fields:
      source_id: {type: string, required: true}
      email: {type: string}
"""


@pytest.fixture
def step_project() -> Project:
    return load_project({"entity_model": STEP_ENTITIES, "steps": STEP_WIRING})


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
    # A step reads a relation *whole*, so every field of the input entity
    # feeds it — not a synthetic `customer_raw.*` node, which had no producer
    # and no consumer and made the lineage claim false.
    assert ("customer_raw.email", "step.resolve_customers", "step_input") in labels
    assert ("customer_raw.source_id", "step.resolve_customers", "step_input") in labels
    assert ("step.resolve_customers", "customer.customer", "step_output") in labels
    # Both ends: a regression reintroducing a `customer.*` *destination*
    # passed the one-sided version of this assertion.
    assert not any(
        endpoint.endswith(".*") for src, dst, _ in labels for endpoint in (src, dst)
    )


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


# ....................... #
# Determinism when two kinds share a name (RFC 0003; logs/T-0005.md D-025)


#: An entity literally named `metric` with a field `revenue` produces the node
#: name `metric.revenue` — the same string `metric_node("revenue")` produces.
#: Entity-field ids carry no kind prefix, so they can collide with every other
#: kind's prefix: `metric.`, `canonical.`, `step.`, `source.`.
COLLIDING_ENTITY = """
spec_version: 1
entities:
  metric:
    grain: one row per thing
    key: [revenue]
    fields:
      revenue: {type: string}
"""
COLLIDING_MAPPING = """
mapping_version: 1
source: raw__things
target: metric
key:
  revenue: {from: "$.r", transform: [to_string]}
"""
COLLIDING_METRICS = """
metrics_version: 1
metrics:
  revenue:
    grain: thing
    additivity: additive
    agg: count
    expr: "revenue"
"""


def colliding_graph() -> object:
    project = load_project(
        {
            "entity_model": COLLIDING_ENTITY,
            "mapping_c": COLLIDING_MAPPING,
            "metrics": COLLIDING_METRICS,
        }
    )
    return build_graph(project, None, effective_metrics(project, None))


def test_two_kinds_can_share_a_node_name() -> None:
    """The premise. If this ever stops being true the ordering test below is
    vacuous, so it is asserted rather than assumed."""
    shared = [node for node in colliding_graph().nodes if node.name == "metric.revenue"]  # type: ignore[attr-defined]

    assert len(shared) == 2
    assert {node.kind for node in shared} == {NodeKind.ENTITY_FIELD, NodeKind.METRIC}


def test_nodes_sharing_a_name_are_ordered_by_kind_not_by_hash() -> None:
    """`build_graph` collects nodes in a `set` and sorts them.

    Sorted by `name` alone, two nodes sharing a name keep whatever relative
    order the set iteration gave — which varies with `PYTHONHASHSEED`, so the
    same specs produced different `Graph.nodes` in different processes. That is
    the invariant CLAUDE.md states as non-negotiable, and `topo_order` derives
    from this order, so it reaches emitted output.
    """
    graph = colliding_graph()
    shared = [node for node in graph.nodes if node.name == "metric.revenue"]  # type: ignore[attr-defined]

    # Deterministic and stated: ties break on the kind's value, ascending.
    assert [node.kind.value for node in shared] == sorted(node.kind.value for node in shared)


def test_node_order_is_identical_across_hash_seeds() -> None:
    """The cross-process form of the test above — the one that actually caught
    it, since a single process can produce the right order by luck."""
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415

    program = (
        "from bloomery import load_project;"
        "from bloomery.resolve.graph import build_graph;"
        "from bloomery.resolve.metrics import effective_metrics;"
        f"p = load_project({{'entity_model': {COLLIDING_ENTITY!r},"
        f" 'mapping_c': {COLLIDING_MAPPING!r}, 'metrics': {COLLIDING_METRICS!r}}});"
        "g = build_graph(p, None, effective_metrics(p, None));"
        "print([(n.kind.value, n.name) for n in g.nodes])"
    )
    outputs = {
        subprocess.run(  # noqa: S603
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            check=True,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
        ).stdout
        for seed in ("0", "1", "42", "7", "12345", "999", "31337")
    }
    assert len(outputs) == 1, f"node order varied with the hash seed: {outputs}"


# ....................... #
# The reservation's drift gate (RFC 0051 §5.2, D8)


def test_every_prefixed_builder_uses_a_reserved_name() -> None:
    """The guardrail that reserves the four names sits below ``resolve`` and
    cannot import this module, so the two lists are pinned together here
    rather than by an import. A fifth node kind with a new prefix fails this
    test instead of quietly escaping the reservation.

    ``entity_field_node`` is deliberately absent: it is the one builder that
    emits no prefix, which is the whole reason the others' are reserved.
    """
    ids = (
        source_column_node("shopify__orders", "$.total").name,
        canonical_field_node("unit_price").name,
        metric_node("gross_revenue").name,
        step_node("resolve_customers").name,
    )
    assert {node_id.split(".", 1)[0] for node_id in ids} == set(NODE_ID_PREFIXES)
    assert entity_field_node("order_item", "unit_price").name == "order_item.unit_price"
