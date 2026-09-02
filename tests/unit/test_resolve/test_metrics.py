"""Template instantiation (resolve/metrics.py): merge precedence and the
missing-additivity completeness check, batched."""

from __future__ import annotations

import pytest

from bloomery import load_catalog, load_project
from bloomery.errors import ResolutionError
from bloomery.resolve.metrics import effective_metrics
from support.compiling import load_fixture

pytestmark = pytest.mark.unit

ENTITY_MODEL = """\
spec_version: 1
entities:
  order:
    grain: one row per order
    key: [order_id]
    fields:
      order_id: {type: string, required: true}
"""

MAPPING = """\
mapping_version: 1
source: src__orders
target: order
key:
  order_id: {from: "$.id", transform: [to_string]}
"""


def test_template_values_fill_the_gaps_and_own_values_win() -> None:
    project, catalog = load_fixture("ecom_basic")
    merged = {m.name: m for m in effective_metrics(project, catalog)}
    # gross_revenue is a bare template instantiation: everything from the catalog.
    gross = merged["gross_revenue"]
    assert gross.requires == ("unit_price", "quantity")
    assert gross.additivity == "additive"
    assert gross.agg == "sum"
    assert gross.expr == "unit_price * quantity"
    assert gross.grain == "order_item"
    # order_count is fully inline.
    assert merged["order_count"].agg == "count"
    # Merged output is sorted by name.
    assert list(merged) == sorted(merged)


def test_metrics_without_a_metric_set_merge_to_nothing() -> None:
    project, _ = load_fixture("minimal")
    assert effective_metrics(project, None) == ()


def test_missing_additivity_is_a_resolution_error() -> None:
    metrics = "metrics_version: 1\nmetrics:\n  bare: {agg: sum, expr: order_id}\n"
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": MAPPING, "metrics": metrics})
    with pytest.raises(ResolutionError, match="'bare' declares no additivity") as excinfo:
        effective_metrics(project, None)
    assert excinfo.value.source_path == "metrics: metrics.bare"


def test_missing_additivity_failures_are_batched() -> None:
    metrics = (
        "metrics_version: 1\n"
        "metrics:\n"
        "  bare_a: {agg: sum, expr: order_id}\n"
        "  bare_b: {agg: count, expr: order_id}\n"
    )
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": MAPPING, "metrics": metrics})
    with pytest.raises(ResolutionError) as excinfo:
        effective_metrics(project, None)
    assert len(excinfo.value.collected) == 2
    assert "metrics: metrics.bare_a" in str(excinfo.value)
    assert "metrics: metrics.bare_b" in str(excinfo.value)


# ....................... #
# Derived inputs are dependency edges (RFC 0034 D3)


DERIVED_METRICS = """\
metrics_version: 1
metrics:
  revenue: {grain: order, additivity: additive, agg: sum, expr: order_id}
  revenue_yoy:
    additivity: non_additive
    derived:
      expr: "current - prior"
      inputs:
        current: {metric: revenue}
        prior: {metric: revenue, offset: {window: 1 year}}
"""


def _effective(metrics: str) -> dict[str, object]:
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": MAPPING, "metrics": metrics})
    return {metric.name: metric for metric in effective_metrics(project, None)}


def test_derived_inputs_are_unioned_into_requires_metrics() -> None:
    """The author writes each input once. Everything downstream — reachability,
    the DAG, cycle detection, `MetricIR.depends_on` — reads `requires_metrics`
    and needs no knowledge of `derived:` at all."""
    merged = _effective(DERIVED_METRICS)

    assert merged["revenue_yoy"].requires_metrics == ("revenue",)


def test_an_explicit_requires_metrics_is_kept_alongside_the_inputs() -> None:
    """Union, not replacement: a derived metric may still declare a dependency
    its expression does not read directly."""
    merged = _effective(
        DERIVED_METRICS.replace(
            "    additivity: non_additive\n",
            "    additivity: non_additive\n    requires_metrics: [other]\n",
        )
        + "  other: {grain: order, additivity: additive, agg: count, expr: order_id}\n"
    )

    assert merged["revenue_yoy"].requires_metrics == ("other", "revenue")


def test_a_template_can_carry_the_derived_block() -> None:
    """The RFC 0034 forms merge like every other template value, and the
    inputs of a *template's* derived block become edges the same way."""
    catalog = load_catalog(
        "catalog_version: 1\n"
        "vertical: v\n"
        "metric_templates:\n"
        "  yoy:\n"
        "    additivity: non_additive\n"
        "    derived:\n"
        '      expr: "current - prior"\n'
        "      inputs:\n"
        "        current: {metric: revenue}\n"
        "        prior: {metric: revenue, offset: {window: 1 year}}\n"
    )
    project = load_project(
        {
            "entity_model": ENTITY_MODEL,
            "mapping": MAPPING,
            "metrics": (
                "metrics_version: 1\n"
                "metrics:\n"
                "  revenue: {grain: order, additivity: additive, agg: sum, expr: order_id}\n"
                "  revenue_yoy: {template: yoy}\n"
            ),
        }
    )
    merged = {metric.name: metric for metric in effective_metrics(project, catalog)}

    assert merged["revenue_yoy"].derived is not None
    assert merged["revenue_yoy"].requires_metrics == ("revenue",)
