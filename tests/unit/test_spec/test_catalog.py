"""The Catalog spec kind (RFC 0002 §5.5; original spec §3.2)."""

from __future__ import annotations

import pytest

from bloomery import load_catalog
from bloomery.errors import SpecParseError

pytestmark = pytest.mark.unit

HAPPY = """
catalog_version: 1
vertical: ecom_retail
canonical_fields:
  unit_price:
    entity: order_item
    type: decimal(12,4)
    unit: currency
    tax_basis: net
    currency: EUR
    recipes:
      - {id: direct, requires: [unit_price]}
      - {id: from_total, requires: [line_total, quantity], expr: "line_total / quantity"}
canonical_relationships:
  - {from: order_item, to: order, via: order_id, cardinality: many_to_one}
metric_templates:
  gross_revenue:
    requires: [unit_price, quantity]
    grain: order_item
    additivity: additive
    agg: sum
    expr: "unit_price * quantity"
  average_order_value:
    requires_metrics: [net_revenue, order_count]
    additivity: non_additive
    ratio: {numerator: net_revenue, denominator: order_count}
  stock_on_hand:
    requires: [stock_level]
    additivity: semi_additive
    agg: sum
    semi_additive: {over: date, rule: last}
"""


def test_happy_parse() -> None:
    catalog = load_catalog(HAPPY)
    assert catalog.catalog_version == 1
    assert catalog.vertical == "ecom_retail"
    field = catalog.canonical_fields["unit_price"]
    assert field.unit == "currency"
    assert field.tax_basis == "net"
    assert field.currency == "EUR"
    assert [r.id for r in field.recipes] == ["direct", "from_total"]
    assert field.recipes[0].expr is None
    assert field.recipes[1].requires == ("line_total", "quantity")
    rel = catalog.canonical_relationships[0]
    assert (rel.from_, rel.to, rel.via, rel.cardinality) == (
        "order_item",
        "order",
        "order_id",
        "many_to_one",
    )
    aov = catalog.metric_templates["average_order_value"]
    assert aov.ratio is not None
    assert aov.ratio.numerator == "net_revenue"
    soh = catalog.metric_templates["stock_on_hand"]
    assert soh.semi_additive is not None
    assert soh.semi_additive.rule == "last"


def test_models_are_frozen() -> None:
    catalog = load_catalog(HAPPY)
    with pytest.raises(Exception, match="frozen"):
        catalog.vertical = "other"  # type: ignore[misc]


def test_missing_version_key() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        load_catalog("vertical: x\n")
    assert excinfo.value.source_path == "catalog"
    assert "catalog_version" in str(excinfo.value)


def test_unknown_key_rejected() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        load_catalog("catalog_version: 1\nvertical: x\nsurprise: 1\n")
    assert excinfo.value.source_path == "catalog: surprise"


def test_bad_type_grammar() -> None:
    text = (
        "catalog_version: 1\nvertical: x\n"
        "canonical_fields:\n  f:\n    entity: e\n    type: decimal(12;4)\n"
    )
    with pytest.raises(SpecParseError) as excinfo:
        load_catalog(text)
    assert excinfo.value.source_path == "catalog: canonical_fields.f.type"


def test_bad_unit_enum() -> None:
    text = (
        "catalog_version: 1\nvertical: x\n"
        "canonical_fields:\n  f:\n    entity: e\n    type: int\n    unit: kilograms\n"
    )
    with pytest.raises(SpecParseError) as excinfo:
        load_catalog(text)
    assert excinfo.value.source_path == "catalog: canonical_fields.f.unit"


def test_bad_currency_code() -> None:
    text = (
        "catalog_version: 1\nvertical: x\n"
        "canonical_fields:\n  f:\n    entity: e\n    type: int\n    currency: euros\n"
    )
    with pytest.raises(SpecParseError) as excinfo:
        load_catalog(text)
    assert excinfo.value.source_path == "catalog: canonical_fields.f.currency"


def test_recipe_requires_is_required() -> None:
    text = (
        "catalog_version: 1\nvertical: x\n"
        "canonical_fields:\n  f:\n    entity: e\n    type: int\n"
        "    recipes: [{id: direct}]\n"
    )
    with pytest.raises(SpecParseError) as excinfo:
        load_catalog(text)
    assert excinfo.value.source_path == "catalog: canonical_fields.f.recipes[0].requires"


def test_date_dimension_parses_with_defaults() -> None:
    text = "catalog_version: 1\nvertical: x\ndate_dimension: {start_year: 2020, end_year: 2030}\n"
    catalog = load_catalog(text)
    assert catalog.date_dimension is not None
    assert catalog.date_dimension.name == "dim_date"
    assert catalog.date_dimension.grain == "day"
    assert (catalog.date_dimension.start_year, catalog.date_dimension.end_year) == (2020, 2030)


def test_date_dimension_is_optional() -> None:
    assert load_catalog("catalog_version: 1\nvertical: x\n").date_dimension is None


def test_date_dimension_rejects_inverted_bounds() -> None:
    text = "catalog_version: 1\nvertical: x\ndate_dimension: {start_year: 2030, end_year: 2020}\n"
    with pytest.raises(SpecParseError) as excinfo:
        load_catalog(text)
    assert excinfo.value.source_path == "catalog: date_dimension"
    assert "end_year must be >= start_year" in str(excinfo.value)


def test_date_dimension_rejects_non_day_grain() -> None:
    text = (
        "catalog_version: 1\nvertical: x\n"
        "date_dimension: {grain: hour, start_year: 2020, end_year: 2030}\n"
    )
    with pytest.raises(SpecParseError) as excinfo:
        load_catalog(text)
    assert excinfo.value.source_path == "catalog: date_dimension.grain"
