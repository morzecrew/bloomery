"""A per-unit field read through a chain of many-to-one relationships (#382,
S-0023/D-15).

A marketplace sale reaches the product through the marketplace's item, so its
cost of goods reads the product's unit cost two relationships down. Every hop
is many-to-one, so each sale still reads exactly one product row, and the
rate is copied onto the sale as it is one hop down. The mart flattens both,
and the metric reads the column the product's cost lands in.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from bloomery import Project, Target, build_project_ir, compile_project, load_catalog, load_project
from bloomery.errors import GrainMismatch, GuardrailError
from bloomery.guardrails.grain import check_grain
from bloomery.guardrails.operands import Derivation
from bloomery.ir import Cardinality, RelationshipIR
from bloomery.spec import Catalog

pytestmark = pytest.mark.unit

ENTITY_MODEL = """spec_version: 1
entities:
  marketplace_sale:
    grain: one row per sale
    key: [sale_id]
    fields:
      sale_id: {type: string, required: true}
      item_id: {type: string}
      quantity: {type: int, canonical: sale_quantity}
      sold_at: {type: timestamp}
  marketplace_item:
    grain: one row per marketplace item
    key: [item_id]
    fields:
      item_id: {type: string, required: true}
      product_id: {type: string}
  product:
    grain: one row per product
    key: [product_id]
    fields:
      product_id: {type: string, required: true}
      buy_price_kop: {type: int, canonical: product_cost}
      shipping_kop: {type: int, canonical: product_shipping}
relationships:
  - name: sale_of_item
    from: marketplace_sale
    to: marketplace_item
    via: {item_id: item_id}
    cardinality: many_to_one
  - name: item_of_product
    from: marketplace_item
    to: product
    via: {product_id: product_id}
    cardinality: {item_cardinality}
"""

MAPPINGS = {
    "mapping_sales": (
        "mapping_version: 1\nsource: mp__sales\ntarget: marketplace_sale\n"
        'key:\n  sale_id: {from: "$.id"}\n'
        'fields:\n  item_id: {from: "$.item"}\n'
        '  quantity: {from: "$.qty", transform: [to_int]}\n'
        '  sold_at: {from: "$.at", transform: [{parse_ts: ISO8601}], zone_in: UTC}\n'
    ),
    "mapping_items": (
        "mapping_version: 1\nsource: mp__items\ntarget: marketplace_item\n"
        'key:\n  item_id: {from: "$.id"}\n'
        'fields:\n  product_id: {from: "$.product"}\n'
    ),
    "mapping_products": (
        "mapping_version: 1\nsource: shop__products\ntarget: product\n"
        'key:\n  product_id: {from: "$.id"}\n'
        'fields:\n  buy_price_kop: {from: "$.cost", transform: [to_int]}\n'
        '  shipping_kop: {from: "$.ship", transform: [to_int]}\n'
    ),
}

CATALOG = """catalog_version: 1
vertical: v
canonical_fields:
  sale_quantity:
    entity: marketplace_sale
    type: int
    unit: count
    recipes: [{id: direct, requires: [sale_quantity]}]
  product_cost:
    entity: product
    type: int
    unit: currency
    tax_basis: net
    per_unit: true
    recipes: [{id: direct, requires: [product_cost]}]
  product_shipping:
    entity: product
    type: int
    unit: currency
    tax_basis: net
    recipes: [{id: direct, requires: [product_shipping]}]
date_dimension: {name: dim_date, grain: day, start_year: 2020, end_year: 2030}
metric_templates:
  marketplace_cost_of_goods:
    requires: [sale_quantity, product_cost]
    grain: marketplace_sale
    additivity: additive
    agg: sum
    expr: product_cost * sale_quantity
  marketplace_shipping:
    requires: [sale_quantity, product_shipping]
    grain: marketplace_sale
    additivity: additive
    agg: sum
    expr: product_shipping * sale_quantity
"""

MART = (
    "marts_version: 1\nmarts:\n  marketplace_sales:\n    grain: marketplace_sale\n"
    "    base: marketplace_sale\n    flatten:\n"
    "      - {via: sale_of_item, prefix: item_}\n"
    "      - {via: item_of_product, prefix: product_}\n"
    "      - {date: sold_at, role: sold}\n"
    "    measures: [{measures}]\n"
)


def _project(
    measures: tuple[str, ...] = ("marketplace_cost_of_goods",),
    *,
    item_cardinality: str = "many_to_one",
) -> Project:
    metrics = "".join(f"  {name}: {{template: {name}}}\n" for name in measures)
    return load_project(
        {
            "entity_model": ENTITY_MODEL.replace("{item_cardinality}", item_cardinality),
            **MAPPINGS,
            "metrics": "metrics_version: 1\nmetrics:\n" + metrics,
            "marts": MART.replace("{measures}", ", ".join(measures)),
        }
    )


def _catalog() -> Catalog:
    return load_catalog(CATALOG)


def _refusal(project: Project) -> GrainMismatch:
    with pytest.raises(GuardrailError) as refused:
        build_project_ir(project, _catalog())

    (leaf,) = (leaf for leaf in refused.value.collected if isinstance(leaf, GrainMismatch))
    return leaf


# ....................... #


def test_a_per_unit_field_two_relationships_down_compiles() -> None:
    ir = build_project_ir(_project(), _catalog())

    assert "marketplace_cost_of_goods" in {metric.name for metric in ir.metrics}


def test_the_mart_measures_the_column_the_far_entity_was_flattened_into() -> None:
    artifacts = {
        artifact.path: artifact.content
        for artifact in compile_project(
            _project(), target=Target.METRICFLOW, dialect="duckdb", catalog=_catalog()
        )
    }
    (model,) = json.loads(artifacts["semantic_manifest.json"])["semantic_models"]
    (measure,) = model["measures"]

    assert measure["expr"] == "product_buy_price_kop * quantity"


def test_an_amount_two_relationships_down_is_still_a_fan_out() -> None:
    """The refusal names the chain it was reached by, and offers the
    declaration, which would admit the field if it were a rate."""
    leaf = _refusal(_project(("marketplace_cost_of_goods", "marketplace_shipping")))

    assert "'product_shipping'" in str(leaf)
    assert "relationships 'sale_of_item', 'item_of_product'" in str(leaf)
    assert "declare per_unit: true" in str(leaf)


def test_a_one_to_many_hop_breaks_the_chain() -> None:
    """One item of many products: a sale reads several product rows, and a rate
    copied from each is summed per sale. Declared per unit or not, the
    expression must aggregate it."""
    leaf = _refusal(_project(item_cardinality="one_to_many"))

    assert "'product_cost'" in str(leaf)
    assert "per_unit" not in str(leaf)


def test_a_derivation_reads_the_chain_declared_from_the_parent_side() -> None:
    """`product` one_to_many `marketplace_item` is the hop the item's
    many_to_one is, read the other way round, and a derivation reads the same
    rule a metric does."""
    project = _project()
    draft = build_project_ir(project, _catalog())
    inverted = tuple(
        replace(
            rel,
            from_entity=rel.to_entity,
            to_entity=rel.from_entity,
            via=tuple((theirs, ours) for ours, theirs in rel.via),
            cardinality=Cardinality.ONE_TO_MANY,
        )
        if rel.name == "item_of_product"
        else rel
        for rel in draft.relationships
    )
    derivation = Derivation(
        source_path="mapping[s->marketplace_sale]: fields.cost",
        source="s",
        cleaned=False,
        entity="marketplace_sale",
        field="cost",
        expr="product_cost * sale_quantity",
        operands=("sale_quantity", "product_cost"),
        direct=None,
    )
    violations = check_grain(
        (derivation,), replace(draft, relationships=inverted), project, _catalog()
    )

    assert [one for one in violations if one.source_path == derivation.source_path] == []


def test_of_two_routes_to_the_far_entity_the_refusal_names_the_one_listed_first() -> None:
    """A sale reaching the product through its item and through a listing
    alike: the walk is breadth first in the IR's relationship order, so the
    chain a refusal names does not depend on how the walk met the other one."""
    project = _project()
    draft = build_project_ir(project, _catalog())
    listing = (
        RelationshipIR(
            name="sale_of_listing",
            from_entity="marketplace_sale",
            to_entity="listing",
            via=(("listing_id", "listing_id"),),
            cardinality=Cardinality.MANY_TO_ONE,
        ),
        RelationshipIR(
            name="listing_of_product",
            from_entity="listing",
            to_entity="product",
            via=(("product_id", "product_id"),),
            cardinality=Cardinality.MANY_TO_ONE,
        ),
    )
    derivation = Derivation(
        source_path="mapping[s->marketplace_sale]: fields.shipping",
        source="s",
        cleaned=False,
        entity="marketplace_sale",
        field="shipping",
        expr="product_shipping * sale_quantity",
        operands=("sale_quantity", "product_shipping"),
        direct=None,
    )

    def named(relationships: tuple[RelationshipIR, ...]) -> str:
        violations = check_grain(
            (derivation,), replace(draft, relationships=relationships), project, _catalog()
        )
        (violation,) = (one for one in violations if one.source_path == derivation.source_path)
        return str(violation)

    assert "relationships 'sale_of_item', 'item_of_product'" in named(
        (*draft.relationships, *listing)
    )
    assert "relationships 'sale_of_listing', 'listing_of_product'" in named(
        (*listing, *draft.relationships)
    )
