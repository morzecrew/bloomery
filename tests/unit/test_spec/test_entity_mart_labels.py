"""Entities, marts and a step's produced columns take a `label:` (#373,
S-0094/D-12, D-13).

S-0094 labelled fields and metrics, and left out three things a person reads:
an entity, a mart, and a column a step produces. A front end kept its own
dictionary for them beside the spec, and an entity or mart added later showed
up as its bare identifier. Metadata only: no SELECT reads a label (S-0094/D-1).
"""

from __future__ import annotations

import json

import pytest
import yaml
from support.compiling import fixture_sources, load_fixture

from bloomery import Target, build_project_ir, compile_project, load_project, plan
from bloomery.errors import SpecParseError
from bloomery.ir import ProjectIR
from bloomery.plan import ChangeClass
from bloomery.steps import StepManifest, StepRegistry

pytestmark = pytest.mark.unit


def _labelled(*, order: str = "Заказы", line: str = "Строки заказов", mart: str = "Продажи") -> dict[str, str]:
    """`ecom_basic`, with labels on both entities and on its one mart."""
    sources = fixture_sources("ecom_basic")

    def swap(key: str, old: str, new: str) -> None:
        assert sources[key].count(old) == 1, (key, old)
        sources[key] = sources[key].replace(old, new)

    swap("entity_model", "  order_item:\n    grain:", f"  order_item:\n    label: {line}\n    grain:")
    swap("entity_model", "  order:\n    grain:", f"  order:\n    label: {order}\n    grain:")
    swap("marts", "  order_items:\n    grain:", f"  order_items:\n    label: {mart}\n    grain:")
    return sources


def _ir(sources: dict[str, str]) -> ProjectIR:
    _project, catalog = load_fixture("ecom_basic")
    return build_project_ir(load_project(sources), catalog)


def _artifacts(target: Target, sources: dict[str, str]) -> dict[str, str]:
    _project, catalog = load_fixture("ecom_basic")
    return {
        artifact.path: artifact.content
        for artifact in compile_project(
            load_project(sources), target=target, dialect="duckdb", catalog=catalog
        )
    }


# ....................... #
# Entities and marts


def test_an_entity_and_a_mart_carry_their_labels_into_the_ir() -> None:
    ir = _ir(_labelled())

    assert {entity.name: entity.label for entity in ir.entities} == {
        "order": "Заказы",
        "order_item": "Строки заказов",
    }
    assert [(mart.name, mart.label) for mart in ir.marts] == [("order_items", "Продажи")]


def test_absent_is_none() -> None:
    ir = _ir(fixture_sources("ecom_basic"))

    assert {entity.label for entity in ir.entities} | {mart.label for mart in ir.marts} == {None}


@pytest.mark.parametrize("label", ['""', '"two\\nlines"'])
def test_a_label_is_one_non_empty_line(label: str) -> None:
    with pytest.raises(SpecParseError):
        load_project(_labelled(mart=label))


def test_metricflow_labels_the_semantic_model_and_its_entities() -> None:
    """`order_item`'s key is composite, so its model declares the primary entity
    by name only and there is no element to label; a mart over `order` has one."""
    sources = _labelled()
    sources["marts"] += "  orders:\n    grain: order\n    base: order\n    measures: []\n"
    manifest = json.loads(_artifacts(Target.METRICFLOW, sources)["semantic_manifest.json"])
    models = {model["name"]: model for model in manifest["semantic_models"]}

    assert models["order_items"]["label"] == "Продажи"
    assert {e["name"]: e["label"] for e in models["order_items"]["entities"]} == {"order": "Заказы"}
    assert {e["name"]: e["label"] for e in models["orders"]["entities"]} == {"order": "Заказы"}
    assert models["orders"]["label"] is None


def test_cube_titles_the_cube_and_its_view() -> None:
    artifacts = _artifacts(Target.CUBE, _labelled())
    (cube,) = yaml.safe_load(artifacts["model/cubes/order_items.yml"])["cubes"]
    (view,) = yaml.safe_load(artifacts["model/views/order_items_view.yml"])["views"]

    assert (cube["title"], view["title"]) == ("Продажи", "Продажи")


def test_absent_every_artifact_is_as_before() -> None:
    for target in (Target.METRICFLOW, Target.CUBE, Target.DBT, Target.SQLMESH):
        plain = _artifacts(target, fixture_sources("ecom_basic"))
        assert not any("Продажи" in text for text in plain.values())
        manifest = plain.get("semantic_manifest.json")
        if manifest is not None:
            (model,) = (m for m in json.loads(manifest)["semantic_models"] if m["name"] == "order_items")
            assert model["label"] is None
            assert all(entity["label"] is None for entity in model["entities"])


def _sql(artifacts: dict[str, str]) -> dict[str, str]:
    """Each SQL artifact without its fingerprint line, which moves with any IR
    change, a label's included."""
    return {
        path: "\n".join(line for line in text.splitlines() if "fingerprint:" not in line)
        for path, text in artifacts.items()
        if path.endswith(".sql")
    }


def test_no_sql_reads_a_label() -> None:
    """S-0094/D-1: every model's SQL is the same with and without them."""
    for target in (Target.SQLMESH, Target.DBT):
        plain = _artifacts(target, fixture_sources("ecom_basic"))
        labelled = _artifacts(target, _labelled())
        assert _sql(labelled) == _sql(plain)


def test_a_changed_entity_or_mart_label_is_metadata_only() -> None:
    old = _ir(_labelled())
    new = _ir(_labelled(order="Заказ", mart="Выручка"))

    changes = {(c.subject, c.change_class, c.detail) for c in plan(old, new).changes}
    assert changes == {
        ("entity:order", ChangeClass.ADDITIVE, "label changed (metadata only)"),
        ("mart:order_items", ChangeClass.ADDITIVE, "label changed (metadata only)"),
    }


# ....................... #
# A step's produced column


SEGMENTS = (
    "steps_version: 1\nsteps:\n  - use: customer_segments@1\n"
    "    inputs: {orders: silver.order}\n"
    "    outputs: {segment: silver.customer_segment}\n"
)


def _registry(label: str | None) -> StepRegistry:
    segment: dict[str, object] = {"type": "string"}
    if label is not None:
        segment["label"] = label
    manifest = StepManifest.model_validate(
        {
            "ref": "customer_segments",
            "version": 1,
            "kind": "sql_model",
            "determinism": "pure",
            "runtime_lock": "sha256:x",
            "inputs": {"orders": {"grain": "order", "requires": ["customer_id"]}},
            "outputs": {
                "segment": {
                    "grain": "one row per customer",
                    "key": ["customer_id"],
                    "produces": {"customer_id": {"type": "string"}, "segment": segment},
                }
            },
        }
    )
    return StepRegistry(
        {("customer_segments", 1): manifest},
        sql_bodies={
            ("customer_segments", 1): (
                'SELECT customer_id, MAX(order_id) AS segment FROM silver."order" GROUP BY 1'
            )
        },
    )


def _step_sources() -> dict[str, str]:
    sources = fixture_sources("ecom_basic")
    sources["steps"] = SEGMENTS
    sources["marts"] += (
        "  segments:\n    grain: customer_segment\n    base: customer_segment\n    measures: []\n"
    )
    return sources


def test_a_produced_column_s_label_reaches_the_output_entity() -> None:
    _project, catalog = load_fixture("ecom_basic")
    ir = build_project_ir(load_project(_step_sources()), catalog, steps=_registry("Сегмент"))

    (entity,) = (entity for entity in ir.entities if entity.name == "customer_segment")
    assert {column.name: column.label for column in entity.columns} == {
        "customer_id": None,
        "segment": "Сегмент",
    }


def test_the_mart_over_the_output_labels_its_dimension() -> None:
    """Through the routing a mapped field's label already takes (S-0094/D-5, D-7)."""
    _project, catalog = load_fixture("ecom_basic")
    artifacts = compile_project(
        load_project(_step_sources()),
        target=Target.METRICFLOW,
        dialect="duckdb",
        catalog=catalog,
        steps=_registry("Сегмент"),
    )
    manifest = json.loads(next(a.content for a in artifacts if a.path == "semantic_manifest.json"))
    (model,) = (m for m in manifest["semantic_models"] if m["name"] == "segments")

    assert {d["name"]: d["label"] for d in model["dimensions"]}["segment"] == "Сегмент"


def test_a_produced_column_s_label_change_restates_no_step() -> None:
    """A step whose definition changes restates its outputs. A label is not
    its definition: it changes the column's metadata and nothing else."""
    _project, catalog = load_fixture("ecom_basic")
    old = build_project_ir(load_project(_step_sources()), catalog, steps=_registry("Сегмент"))
    new = build_project_ir(load_project(_step_sources()), catalog, steps=_registry("Группа"))

    changes = {(c.subject, c.change_class, c.detail) for c in plan(old, new).changes}
    assert changes == {
        ("field:segment", ChangeClass.ADDITIVE, "label changed (metadata only)")
    }
