"""load_project: kind detection via version keys, document cardinality rules,
per-document error batching (RFC 0002 §5.5, D6)."""

from __future__ import annotations

import pytest

from bloomery import load_project
from bloomery.errors import BloomeryError, SpecParseError
from bloomery.spec import EntityModel, Mapping, MartSet, MetricSet

pytestmark = pytest.mark.unit

ENTITY_MODEL = """
spec_version: 1
entities:
  event:
    grain: one row per event
    key: [event_id]
    fields:
      event_id: {type: string, required: true}
"""

MAPPING = """
mapping_version: 1
source: raw__events
target: event
key:
  event_id: {from: "$.id", transform: [to_string]}
"""

METRICS = """
metrics_version: 1
metrics:
  event_count: {additivity: additive, agg: count, expr: event_id, grain: event}
"""

MARTS = """
marts_version: 1
marts:
  events:
    grain: event
    base: event
    flatten: [{date: occurred_at, role: occurred}]
    measures: [event_count]
"""


def test_kind_detection_all_four_kinds() -> None:
    project = load_project(
        {
            "entity_model": ENTITY_MODEL,
            "mappings/events": MAPPING,
            "metrics": METRICS,
            "marts": MARTS,
        }
    )
    assert isinstance(project.entity_model, EntityModel)
    assert isinstance(project.mappings[0], Mapping)
    assert isinstance(project.metric_set, MetricSet)
    assert isinstance(project.marts, MartSet)


def test_optional_documents_absent() -> None:
    project = load_project({"entity_model": ENTITY_MODEL, "m": MAPPING})
    assert project.metric_set is None
    assert project.marts is None


def test_mappings_ordered_by_document_name() -> None:
    mapping_b = MAPPING.replace("raw__events", "raw__events_b")
    project = load_project(
        {"entity_model": ENTITY_MODEL, "mappings/b": mapping_b, "mappings/a": MAPPING}
    )
    assert [m.source for m in project.mappings] == ["raw__events", "raw__events_b"]


def test_project_is_frozen() -> None:
    project = load_project({"entity_model": ENTITY_MODEL})
    with pytest.raises(AttributeError):
        project.mappings = ()  # type: ignore[misc]


def test_unknown_kind() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        load_project({"entity_model": ENTITY_MODEL, "junk": "who_am_i: 1\n"})
    assert excinfo.value.source_path == "junk"
    assert "unknown spec kind" in str(excinfo.value)


def test_ambiguous_kind() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        load_project({"doc": "spec_version: 1\nmapping_version: 1\n"})
    assert excinfo.value.source_path == "doc"
    assert "ambiguous spec kind" in str(excinfo.value)


def test_catalog_not_part_of_project() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        load_project({"entity_model": ENTITY_MODEL, "catalog": "catalog_version: 1\nvertical: x\n"})
    assert excinfo.value.source_path == "catalog"
    assert "load_catalog" in str(excinfo.value)


def test_missing_entity_model() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        load_project({"m": MAPPING})
    assert "exactly one EntityModel" in str(excinfo.value)


def test_duplicate_entity_model_documents() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        load_project({"a_model": ENTITY_MODEL, "b_model": ENTITY_MODEL})
    message = str(excinfo.value)
    assert "exactly one EntityModel" in message
    # the duplicate documents are named
    assert "a_model" in message
    assert "b_model" in message


def test_duplicate_metric_set_documents() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        load_project({"entity_model": ENTITY_MODEL, "m1": METRICS, "m2": METRICS})
    assert "at most one MetricSet" in str(excinfo.value)


def test_duplicate_mart_set_documents() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        load_project({"entity_model": ENTITY_MODEL, "g1": MARTS, "g2": MARTS})
    assert "at most one MartSet" in str(excinfo.value)


def test_two_errors_in_one_document_batched() -> None:
    bad = (
        "spec_version: 1\n"
        "entities:\n"
        "  e:\n"
        "    grain: g\n"
        "    key: [k]\n"
        "    fields:\n"
        "      a: {type: nope}\n"
        "      b: {type: string, surprise: 1}\n"
    )
    with pytest.raises(SpecParseError) as excinfo:
        load_project({"entity_model": bad})
    err = excinfo.value
    assert len(err.collected) == 2
    assert "entity_model: entities.e.fields.a.type" in str(err)
    assert "entity_model: entities.e.fields.b.surprise" in str(err)
    assert all(isinstance(item, SpecParseError) for item in err.collected)


def test_errors_across_documents_batched_into_one() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        load_project(
            {
                "entity_model": ENTITY_MODEL,
                "bad_mapping": "mapping_version: 1\nsource: s\n",  # missing target/key
                "bad_metrics": "metrics_version: 1\nmetrics:\n  m: {additivity: nope}\n",
            }
        )
    message = str(excinfo.value)
    assert "bad_mapping: target" in message
    assert "bad_mapping: key" in message
    assert "bad_metrics: metrics.m.additivity" in message


def test_duplicate_yaml_key_inside_project_document() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        load_project({"entity_model": ENTITY_MODEL + "spec_version: 2\n"})
    assert excinfo.value.source_path == "entity_model"
    assert "duplicate key" in str(excinfo.value)


def test_all_loader_errors_are_bloomery_errors() -> None:
    with pytest.raises(BloomeryError):
        load_project({})
