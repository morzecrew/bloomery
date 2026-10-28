"""Descriptions, labels and synonyms on fields and metrics, as the spec reads
them (S-0094/D-2, D-3, D-9; #311, #313, #343)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bloomery.spec.catalog import MetricTemplate
from bloomery.spec.entity import Field
from bloomery.spec.metrics import Metric

pytestmark = pytest.mark.unit


def test_a_field_carries_a_description_a_label_and_synonyms() -> None:
    field = Field.model_validate(
        {
            "type": "string",
            "description": "  Where the order came from  ",
            "label": "Channel",
            "synonyms": ["source", "origin"],
        }
    )

    assert field.description == "Where the order came from"
    assert field.label == "Channel"
    assert field.synonyms == ("source", "origin")


@pytest.mark.parametrize("key", ["description", "label"])
def test_an_annotation_empty_after_stripping_is_refused(key: str) -> None:
    with pytest.raises(ValidationError, match="empty"):
        Field.model_validate({"type": "string", key: "   "})


def test_a_label_with_a_line_break_is_refused() -> None:
    """A label names a column in a picker or a chart title; a description is
    where a sentence goes."""
    with pytest.raises(ValidationError, match="one line"):
        Field.model_validate({"type": "string", "label": "Order\nchannel"})


@pytest.mark.parametrize("model", [Field, Metric])
def test_two_equal_synonyms_are_refused(model: type[Field] | type[Metric]) -> None:
    base = {"type": "string"} if model is Field else {"additivity": "additive"}
    with pytest.raises(ValidationError, match="appears twice"):
        model.model_validate({**base, "synonyms": ["revenue", "sales", "revenue"]})


def test_an_empty_synonym_is_refused() -> None:
    with pytest.raises(ValidationError, match="empty"):
        Metric.model_validate({"additivity": "additive", "synonyms": ["revenue", " "]})


def test_a_metric_and_a_template_carry_a_label_and_synonyms() -> None:
    metric = Metric.model_validate(
        {"additivity": "additive", "label": "Revenue", "synonyms": ["sales"]}
    )
    template = MetricTemplate.model_validate(
        {"additivity": "additive", "label": "Revenue", "synonyms": ["sales"]}
    )

    assert (metric.label, metric.synonyms) == ("Revenue", ("sales",))
    assert (template.label, template.synonyms) == ("Revenue", ("sales",))


def test_absent_synonyms_are_none_so_a_template_s_can_fill_them() -> None:
    """Absent and empty differ: an authored `[]` clears a template's synonyms."""
    assert Metric.model_validate({"additivity": "additive"}).synonyms is None
    assert Metric.model_validate({"additivity": "additive", "synonyms": []}).synonyms == ()
