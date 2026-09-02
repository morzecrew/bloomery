"""Cross-spec reference validation (RFC 0005 §5.5, D7): every check kind,
error types, source paths, and per-stage batching."""

from __future__ import annotations

import pytest

from bloomery import load_catalog, load_project
from bloomery.errors import MissingReference, ResolutionError
from bloomery.resolve import resolve

pytestmark = pytest.mark.unit

ENTITY_MODEL = """\
spec_version: 1
entities:
  order_item:
    grain: one row per line
    key: [order_id]
    fields:
      order_id: {type: string, required: true}
      unit_price: {type: "decimal(12,4)", canonical: unit_price}
      note: {type: string}
"""

MAPPING = """\
mapping_version: 1
source: src__lines
target: order_item
key:
  order_id: {from: "$.id", transform: [to_string]}
fields:
  unit_price: {from: "$.price", transform: [{to_decimal: [12, 4]}]}
"""

CATALOG = """\
catalog_version: 1
vertical: test
canonical_fields:
  unit_price:
    entity: order_item
    type: decimal(12,4)
    recipes:
      - {id: direct, requires: [unit_price]}
metric_templates:
  revenue:
    requires: [unit_price]
    additivity: additive
    agg: sum
    expr: "unit_price"
"""


def test_clean_project_resolves() -> None:
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": MAPPING})
    resolve(project, load_catalog(CATALOG))


def test_unknown_mapping_target() -> None:
    mapping = MAPPING.replace("target: order_item", "target: order")
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": mapping})
    with pytest.raises(MissingReference, match="unknown entity 'order'") as excinfo:
        resolve(project, load_catalog(CATALOG))
    assert excinfo.value.source_path == "mapping[src__lines->order]: target"


def test_key_lowers_unknown_field() -> None:
    mapping = MAPPING.replace("order_id: {from", "wrong_id: {from")
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": mapping})
    with pytest.raises(ResolutionError) as excinfo:
        resolve(project, load_catalog(CATALOG))
    paths = [e.source_path for e in (excinfo.value.collected or (excinfo.value,))]
    # Both failures in one round-trip: unknown key field and the un-lowered
    # entity key column.
    assert "mapping[src__lines->order_item]: key.wrong_id" in paths
    assert "mapping[src__lines->order_item]: key" in paths


def test_fields_maps_unknown_field() -> None:
    mapping = MAPPING.replace("  unit_price: {from", "  ghost: {from")
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": mapping})
    with pytest.raises(MissingReference, match="unknown field 'ghost'") as excinfo:
        resolve(project, load_catalog(CATALOG))
    assert excinfo.value.source_path == "mapping[src__lines->order_item]: fields.ghost"


def test_field_mapped_both_as_key_and_field() -> None:
    mapping = MAPPING + '  order_id: {from: "$.dup"}\n'
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": mapping})
    with pytest.raises(ResolutionError, match="both under key: and fields:") as excinfo:
        resolve(project, load_catalog(CATALOG))
    assert excinfo.value.source_path == "mapping[src__lines->order_item]: fields.order_id"


def test_canonical_link_without_catalog() -> None:
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": MAPPING})
    with pytest.raises(MissingReference, match="no catalog was provided") as excinfo:
        resolve(project)
    assert excinfo.value.source_path == (
        "entity_model: entities.order_item.fields.unit_price.canonical"
    )


def test_unknown_canonical_field() -> None:
    model = ENTITY_MODEL.replace("canonical: unit_price", "canonical: price")
    project = load_project({"entity_model": model, "mapping": MAPPING})
    with pytest.raises(MissingReference, match="unknown canonical field 'price'"):
        resolve(project, load_catalog(CATALOG))


def test_canonical_field_entity_mismatch() -> None:
    catalog = CATALOG.replace("entity: order_item", "entity: order")
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": MAPPING})
    with pytest.raises(MissingReference, match="declared for entity 'order', not 'order_item'"):
        resolve(project, load_catalog(catalog))


def test_relationship_unknown_endpoint() -> None:
    model = ENTITY_MODEL + (
        "relationships:\n"
        "  - {name: r, from: order_item, to: order, via: {order_id: order_id},"
        " cardinality: many_to_one}\n"
    )
    project = load_project({"entity_model": model, "mapping": MAPPING})
    with pytest.raises(MissingReference, match="references unknown entity 'order'") as excinfo:
        resolve(project, load_catalog(CATALOG))
    assert excinfo.value.source_path == "entity_model: relationships[0].to"


def test_relationship_unknown_via_column() -> None:
    model = ENTITY_MODEL + (
        "relationships:\n"
        "  - {name: r, from: order_item, to: order_item, via: {ghost: order_id},"
        " cardinality: one_to_one}\n"
    )
    project = load_project({"entity_model": model, "mapping": MAPPING})
    with pytest.raises(MissingReference, match="unknown column 'ghost'") as excinfo:
        resolve(project, load_catalog(CATALOG))
    assert excinfo.value.source_path == "entity_model: relationships[0].via.ghost"


def test_metric_unknown_template() -> None:
    metrics = "metrics_version: 1\nmetrics:\n  rev: {template: revenues}\n"
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": MAPPING, "metrics": metrics})
    with pytest.raises(MissingReference, match="unknown metric template 'revenues'") as excinfo:
        resolve(project, load_catalog(CATALOG))
    assert excinfo.value.source_path == "metrics: metrics.rev.template"


def test_metric_requires_unknown_canonical() -> None:
    metrics = (
        "metrics_version: 1\n"
        "metrics:\n"
        "  rev: {requires: [ghost], additivity: additive, agg: sum, expr: ghost}\n"
    )
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": MAPPING, "metrics": metrics})
    with pytest.raises(MissingReference, match="unknown canonical field 'ghost'") as excinfo:
        resolve(project, load_catalog(CATALOG))
    assert excinfo.value.source_path == "metrics: metrics.rev.requires[0]"


def test_metric_requires_unknown_metric() -> None:
    metrics = (
        "metrics_version: 1\n"
        "metrics:\n"
        "  rev: {template: revenue}\n"
        "  aov:\n"
        "    requires_metrics: [rev, order_count]\n"
        "    additivity: non_additive\n"
        "    ratio: {numerator: rev, denominator: order_count}\n"
    )
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": MAPPING, "metrics": metrics})
    with pytest.raises(MissingReference, match="unknown metric 'order_count'") as excinfo:
        resolve(project, load_catalog(CATALOG))
    assert excinfo.value.source_path == "metrics: metrics.aov.requires_metrics[1]"


def test_reference_failures_are_batched_across_kinds() -> None:
    mapping = MAPPING.replace("target: order_item", "target: order")
    metrics = "metrics_version: 1\nmetrics:\n  rev: {template: revenues}\n"
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": mapping, "metrics": metrics})
    with pytest.raises(ResolutionError) as excinfo:
        resolve(project, load_catalog(CATALOG))
    error = excinfo.value
    assert len(error.collected) == 2
    assert all(isinstance(item, MissingReference) for item in error.collected)
    assert "mapping[src__lines->order]: target" in str(error)
    assert "metrics: metrics.rev.template" in str(error)


def test_a_derived_metric_reading_an_unknown_metric_is_a_missing_reference() -> None:
    """The reference stage runs *before* the template merge and reads the spec
    models directly, so it validates `derived.inputs` itself (RFC 0034 D3) —
    through the same `input_metrics` property the merge reads, so the two
    cannot disagree about what a derived metric depends on."""
    metrics = (
        "metrics_version: 1\n"
        "metrics:\n"
        "  revenue: {grain: order_item, additivity: additive, agg: sum, expr: unit_price}\n"
        "  revenue_yoy:\n"
        "    additivity: non_additive\n"
        "    derived:\n"
        '      expr: "current - prior"\n'
        "      inputs:\n"
        "        current: {metric: revenue}\n"
        "        prior: {metric: revenu, offset: {window: 1 year}}\n"
    )
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": MAPPING, "metrics": metrics})
    with pytest.raises(ResolutionError) as excinfo:
        resolve(project, None)
    (leaf,) = [
        error for error in excinfo.value.collected if "derived metric" in str(error)
    ]

    assert isinstance(leaf, MissingReference)
    assert "unknown metric 'revenu'" in str(leaf)
    assert leaf.source_path == "metrics: metrics.revenue_yoy.derived.inputs"
