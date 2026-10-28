"""Descriptions, labels and synonyms reach each target's own slots and no other
(S-0094/D-1, D-5, D-6, D-7, D-9; #311, #313, #343).

`ecom_basic` annotated in three places: `unit_price` on the mart's base entity,
`customer_id` on the order the mart flattens (so its mart column is the
prefixed `order_customer_id`), and the `gross_revenue` metric.
"""

from __future__ import annotations

import json
import re

import pytest
import yaml
from support.compiling import fixture_sources, load_fixture

from bloomery import Target, compile_project, load_project

pytestmark = pytest.mark.unit


def _replaced(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, f"the fixture no longer reads {old!r}"
    return text.replace(old, new)


def _annotated() -> dict[str, str]:
    sources = fixture_sources("ecom_basic")
    sources["entity_model"] = _replaced(
        sources["entity_model"],
        '      unit_price: {type: "decimal(12,4)", canonical: unit_price}\n',
        '      unit_price: {type: "decimal(12,4)", canonical: unit_price, '
        'description: "Net unit price", label: Unit price, synonyms: [price, cost]}\n',
    )
    sources["entity_model"] = _replaced(
        sources["entity_model"],
        "      customer_id: {type: string, classification: pii}\n",
        "      customer_id: {type: string, classification: pii, description: Who ordered, "
        "label: Customer, synonyms: [buyer]}\n",
    )
    sources["metrics"] = _replaced(
        sources["metrics"],
        "    template: gross_revenue\n",
        "    template: gross_revenue\n    description: Revenue before refunds\n"
        "    label: Revenue\n    synonyms: [turnover, sales]\n",
    )
    return sources


def _artifacts(target: Target, sources: dict[str, str]) -> dict[str, str]:
    _project, catalog = load_fixture("ecom_basic")
    return {
        artifact.path: artifact.content
        for artifact in compile_project(
            load_project(sources), target=target, dialect="duckdb", catalog=catalog
        )
    }


# ....................... #
# MetricFlow


def _manifest() -> dict[str, object]:
    return json.loads(_artifacts(Target.METRICFLOW, _annotated())["semantic_manifest.json"])


def test_metricflow_carries_a_dimension_s_description_label_and_synonyms() -> None:
    (model,) = (m for m in _manifest()["semantic_models"] if m["name"] == "order_items")
    dimensions = {d["name"]: d for d in model["dimensions"]}

    for name, description, label, synonyms in (
        ("unit_price", "Net unit price", "Unit price", ["cost", "price"]),
        ("order_customer_id", "Who ordered", "Customer", ["buyer"]),
    ):
        dimension = dimensions[name]
        assert (dimension["description"], dimension["label"]) == (description, label)
        assert dimension["config"]["meta"]["synonyms"] == synonyms


def test_metricflow_carries_a_metric_s_label_and_synonyms_beside_its_owner() -> None:
    (metric,) = (m for m in _manifest()["metrics"] if m["name"] == "gross_revenue")

    assert metric["label"] == "Revenue"
    assert metric["config"]["meta"] == {
        "owner": "finance-reporting@example.com",
        "synonyms": ["sales", "turnover"],
    }


# ....................... #
# Cube


def _cube() -> dict[str, object]:
    (cube,) = yaml.safe_load(_artifacts(Target.CUBE, _annotated())["model/cubes/order_items.yml"])[
        "cubes"
    ]
    return cube


def test_cube_carries_a_dimension_s_title_description_and_synonyms() -> None:
    dimensions = {d["name"]: d for d in _cube()["dimensions"]}

    assert dimensions["unit_price"]["title"] == "Unit price"
    assert dimensions["unit_price"]["description"] == "Net unit price"
    assert dimensions["unit_price"]["meta"]["synonyms"] == ["cost", "price"]
    assert dimensions["order_customer_id"]["title"] == "Customer"
    assert dimensions["order_customer_id"]["meta"]["synonyms"] == ["buyer"]


def test_cube_carries_a_measure_s_title_description_and_synonyms() -> None:
    (measure,) = (m for m in _cube()["measures"] if m["name"] == "gross_revenue")

    assert measure["title"] == "Revenue"
    assert measure["meta"]["synonyms"] == ["sales", "turnover"]
    assert measure["description"] == "Revenue before refunds"  # Cube had none before (D-6)


# ....................... #
# dbt


def _schema() -> dict[str, dict[str, object]]:
    models = yaml.safe_load(_artifacts(Target.DBT, _annotated())["models/schema.yml"])["models"]
    return {model["name"]: model for model in models}


def test_dbt_carries_a_column_s_description_and_synonyms_and_no_label() -> None:
    (entity,) = (m for name, m in _schema().items() if name.endswith("order_item"))
    columns = {c["name"]: c for c in entity["columns"]}

    assert columns["unit_price"]["description"] == "Net unit price"
    assert columns["unit_price"]["meta"]["synonyms"] == ["cost", "price"]
    assert "label" not in columns["unit_price"]


def test_dbt_lists_a_mart_s_columns_with_their_source_s_annotations() -> None:
    (mart,) = (m for name, m in _schema().items() if name.endswith("order_items"))
    columns = {c["name"]: c for c in mart["columns"]}

    assert columns["order_customer_id"]["description"] == "Who ordered"
    assert columns["order_customer_id"]["meta"]["synonyms"] == ["buyer"]


# ....................... #
# D-1: no SELECT moves


_FINGERPRINT = re.compile(r"(?m)^.*fingerprint.*$")


@pytest.mark.parametrize("target", [Target.SQLMESH, Target.DBT, Target.CUBE, Target.METRICFLOW])
def test_an_annotation_changes_no_sql(target: Target) -> None:
    """D-1, asserted rather than assumed: with the annotations added, every SQL
    artifact is byte-identical to the unannotated one but for its fingerprint."""
    plain = _artifacts(target, fixture_sources("ecom_basic"))
    annotated = _artifacts(target, _annotated())
    sql = sorted(path for path in plain if path.endswith(".sql"))

    assert sql == sorted(path for path in annotated if path.endswith(".sql"))
    for path in sql:
        assert _FINGERPRINT.sub("", plain[path]) == _FINGERPRINT.sub("", annotated[path]), path


def test_synonyms_never_reach_a_label_or_a_description() -> None:
    text = "\n".join(
        content
        for target in (Target.CUBE, Target.METRICFLOW, Target.DBT)
        for content in _artifacts(target, _annotated()).values()
    )
    for line in text.splitlines():
        if re.search(r"\b(title|label|description)\b", line):
            assert not re.search(r"\b(turnover|buyer|cost)\b", line), line
