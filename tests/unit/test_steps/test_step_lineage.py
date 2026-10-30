"""Lineage runs through a ``sql_model`` step (#365, S-0048/D-10).

The graph is built at resolve, which saw only the wiring: what a step produces
is the manifest's, and the manifest lives in the step registry. So the step's
one out-edge went to a node named after the output, a metric over the output
read nothing, and a downstream walk from the step's input stopped at the step.
Given the registry, the step feeds each column it produces.
"""

from __future__ import annotations

import pytest

from bloomery import Direction, Project, lineage, load_project, resolve
from bloomery.resolve import pipeline
from bloomery.resolve.graph import Graph, entity_field_node, metric_node, step_node
from bloomery.steps import StepManifest, StepRegistry

pytestmark = pytest.mark.unit

ENTITY_MODEL = """spec_version: 1
entities:
  order:
    grain: one row per order
    key: [order_id]
    fields:
      order_id: {type: string, required: true}
      customer_id: {type: string}
"""

MAPPING = (
    "mapping_version: 1\nsource: shop__orders\ntarget: order\n"
    'key:\n  order_id: {from: "$.id"}\n'
    'fields:\n  customer_id: {from: "$.customer_id"}\n'
    "unmapped: ['$._ingested_at', '$._load_id', '$._source_row_id']\n"
)

STEPS = (
    "steps_version: 1\nsteps:\n  - use: customer_segments@1\n"
    "    inputs: {orders: silver.order}\n"
    "    outputs: {segment: silver.customer_segment}\n"
)

LABELS_WIRING = (
    "  - use: segment_labels@1\n    inputs: {segments: silver.customer_segment}\n"
    "    outputs: {label: silver.customer_label}\n"
)

METRICS = (
    "metrics_version: 1\nmetrics:\n  segment_customers:\n    grain: customer_segment\n"
    "    additivity: distinct_count\n    agg: count_distinct\n    expr: customer_id\n"
)


def manifest(ref: str, inputs: str, output: str, produces: tuple[str, ...]) -> StepManifest:
    return StepManifest.model_validate(
        {
            "ref": ref,
            "version": 1,
            "kind": "sql_model",
            "determinism": "pure",
            "runtime_lock": "sha256:x",
            "inputs": {inputs: {"grain": "order", "requires": ["customer_id"]}},
            "outputs": {
                output: {
                    "grain": "one row per customer",
                    "key": ["customer_id"],
                    "produces": {column: {"type": "string"} for column in produces},
                }
            },
        }
    )


SEGMENTS = manifest("customer_segments", "orders", "segment", ("customer_id", "segment"))
LABELS = manifest("segment_labels", "segments", "label", ("customer_id", "label"))

REGISTRY = StepRegistry(
    {("customer_segments", 1): SEGMENTS, ("segment_labels", 1): LABELS},
    sql_bodies={
        ("customer_segments", 1): (
            "SELECT customer_id, MAX(order_id) AS segment FROM silver.\"order\" GROUP BY 1"
        ),
        ("segment_labels", 1): "SELECT customer_id, segment AS label FROM silver.customer_segment",
    },
)


def project(*, labels: bool = False) -> Project:
    return load_project(
        {
            "entity_model": ENTITY_MODEL,
            "mapping_orders": MAPPING,
            "steps": STEPS + (LABELS_WIRING if labels else ""),
            "metrics": METRICS,
        }
    )


def edges(graph: Graph) -> set[tuple[str, str, str]]:
    return {(e.src.name, e.label, e.dst.name) for e in graph.edges}


# ....................... #


def test_the_step_feeds_each_column_it_produces() -> None:
    """The issue's second point."""
    graph = resolve(project(), steps=REGISTRY).graph

    assert {
        ("step.customer_segments", "step_output", "customer_segment.customer_id"),
        ("step.customer_segments", "step_output", "customer_segment.segment"),
    } <= edges(graph)
    assert entity_field_node("customer_segment", "segment") in graph.nodes


def test_the_step_feeds_no_node_named_after_its_output() -> None:
    """#381: an output named `profile` is not a column of what it writes, so
    with the manifest at hand the step feeds the produced columns alone."""
    wired = load_project(
        {
            "entity_model": ENTITY_MODEL,
            "mapping_orders": MAPPING,
            "steps": STEPS.replace("segment: silver.customer_segment", "profile: silver.customer_profile"),
        }
    )
    profile = manifest("customer_segments", "orders", "profile", ("customer_id", "segment"))
    graph = resolve(wired, steps=StepRegistry({("customer_segments", 1): profile})).graph

    produced = {dst for src, label, dst in edges(graph) if (src, label) == ("step.customer_segments", "step_output")}
    assert produced == {"customer_profile.customer_id", "customer_profile.segment"}
    assert entity_field_node("customer_profile", "profile") not in graph.nodes


def test_a_metric_over_a_step_output_reads_its_columns() -> None:
    """The third point: an ``expr`` edge, as over an authored entity."""
    graph = resolve(project(), steps=REGISTRY).graph

    reads = {src for src, label, dst in edges(graph) if (label, dst) == ("expr", "metric.segment_customers")}
    assert reads == {"customer_segment.customer_id"}


def test_a_downstream_walk_from_the_input_reaches_the_metric() -> None:
    graph = resolve(project(), steps=REGISTRY).graph
    walk = lineage(graph, entity_field_node("order", "customer_id"), Direction.DOWNSTREAM)

    assert {step_node("customer_segments"), metric_node("segment_customers")} <= set(walk.nodes)


def test_an_upstream_walk_from_the_metric_reaches_the_input() -> None:
    graph = resolve(project(), steps=REGISTRY).graph
    walk = lineage(graph, metric_node("segment_customers"), Direction.UPSTREAM)

    assert entity_field_node("order", "customer_id") in walk.nodes


def test_a_step_reading_another_step_reads_its_columns() -> None:
    """A step bound to another step's output reads that relation whole, as it
    reads an entity: from each column, so a walk from one of them reaches it."""
    graph = resolve(project(labels=True), steps=REGISTRY).graph

    assert {
        ("customer_segment.customer_id", "step_input", "step.segment_labels"),
        ("customer_segment.segment", "step_input", "step.segment_labels"),
    } <= edges(graph)
    walk = lineage(graph, entity_field_node("customer_segment", "segment"), Direction.DOWNSTREAM)
    assert entity_field_node("customer_label", "label") in walk.nodes


def test_without_a_registry_the_graph_is_the_wiring_alone() -> None:
    """`bloomery lineage` passes no registry: the step's out-edge is the node
    named after the output, and the step-to-step edge stands in for the
    columns."""
    graph = resolve(project(labels=True)).graph

    touching = {edge for edge in edges(graph) if "step." in edge[0] or "step." in edge[2]}
    assert touching == {
        ("order.customer_id", "step_input", "step.customer_segments"),
        ("order.order_id", "step_input", "step.customer_segments"),
        ("step.customer_segments", "step_input", "step.segment_labels"),
        ("step.customer_segments", "step_output", "customer_segment.segment"),
        ("step.segment_labels", "step_output", "customer_label.label"),
    }
    assert not any(label == "expr" for _, label, _ in edges(graph))


def test_a_step_the_registry_lacks_falls_back_to_the_wiring() -> None:
    """Refusing it is step lowering's job (`UnknownStep`); resolve still
    answers."""
    graph = resolve(project(), steps=StepRegistry({})).graph

    assert ("step.customer_segments", "step_output", "customer_segment.segment") in edges(graph)
    assert ("step.customer_segments", "step_output", "customer_segment.customer_id") not in edges(
        graph
    )


def test_the_compile_pipeline_resolves_with_its_registry() -> None:
    """The graph a compile carries, which a timeline walks, has the columns."""
    progress = None
    for _stage, reached in pipeline(project(), None, steps=REGISTRY):
        progress = reached

    assert progress is not None and progress.resolution is not None
    assert ("customer_segment.customer_id", "expr", "metric.segment_customers") in edges(
        progress.resolution.graph
    )
