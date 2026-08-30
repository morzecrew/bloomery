"""Operand resolution (RFC 0006 §5.2): catalog metadata is declared or
``unknown`` — never inferred — and derivations enumerate deterministically."""

from __future__ import annotations

import pytest

from bloomery.guardrails.operands import collect_derivations, operand_meta
from bloomery.spec import Entity, EntityModel, Field, Mapping, Project, RecipeFieldMapping
from support.compiling import load_fixture

pytestmark = pytest.mark.unit


def test_operand_meta_resolves_declared_catalog_metadata() -> None:
    _project, catalog = load_fixture("ecom_basic")
    meta = operand_meta("unit_price", catalog)
    assert meta is not None
    assert meta.entity == "order_item"
    assert meta.unit == "currency"
    assert meta.tax_basis == "net"
    assert meta.currency is None  # absent code — compatible by design (D4)


def test_operand_meta_is_none_for_non_canonical_names() -> None:
    _project, catalog = load_fixture("ecom_basic")
    # `line_total` is a recipe alias, not a canonical field: no metadata.
    assert operand_meta("line_total", catalog) is None


def test_operand_meta_is_none_without_a_catalog() -> None:
    assert operand_meta("unit_price", None) is None


def test_collect_derivations_orders_by_mapping_then_field() -> None:
    project, catalog = load_fixture("fanout_trap")
    derivations = collect_derivations(project, catalog)
    assert [(d.entity, d.field) for d in derivations] == [
        ("order_item", "landed_cost"),
        ("order_item", "unit_price"),
        ("order", "shipping_cost"),
    ]
    landed = derivations[0]
    assert landed.source_path == "mapping[wms__order_lines->order_item]: fields.landed_cost"
    assert landed.expr == "unit_price + shipping_cost"
    assert landed.operands == ("unit_price", "shipping_cost")
    assert landed.direct is None


def test_collect_derivations_records_the_direct_path() -> None:
    project, catalog = load_fixture("path_conflict")
    (derivation,) = collect_derivations(project, catalog)
    assert derivation.field == "net_price"
    assert derivation.direct == "$.price"


def test_collect_derivations_skips_simple_mappings() -> None:
    project, catalog = load_fixture("ecom_basic")
    derivations = collect_derivations(project, catalog)
    # `quantity` and `order_date` are simple mappings; only the recipe stays.
    assert [d.field for d in derivations] == ["unit_price"]


def _handmade_project(*, canonical: str | None) -> Project:
    entity = Entity(
        grain="one row per item",
        key=("item_id",),
        fields={
            "item_id": Field(type="string", required=True),
            "x": Field(type="int", canonical=canonical),
        },
    )
    mapping = Mapping.model_validate(
        {
            # `document` is the loader's to bind (RFC 0032 D3); this constructs
            # the model directly, so it supplies its own.
            "document": "mapping_item",
            "mapping_version": 1,
            "source": "s",
            "target": "item",
            "key": {"item_id": {"from": "$.id"}},
            "fields": {"x": {"recipe": "r", "from": {"a": "$.a"}}},
        }
    )
    return Project(
        entity_model=EntityModel(spec_version=1, entities={"item": entity}),
        mappings=(mapping,),
    )


def test_collect_derivations_guards_direct_calls_without_a_catalog() -> None:
    """Resolution rejects a recipe mapping without a catalog before the stage
    runs; the direct-call guard skips instead of crashing."""
    project = _handmade_project(canonical="x")
    assert isinstance(project.mappings[0].fields["x"], RecipeFieldMapping)
    assert collect_derivations(project, None) == ()


def test_collect_derivations_guards_direct_calls_without_a_canonical_link() -> None:
    _project, catalog = load_fixture("ecom_basic")
    project = _handmade_project(canonical=None)
    assert collect_derivations(project, catalog) == ()
