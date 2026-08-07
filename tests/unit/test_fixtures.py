"""The fixture corpus parses clean through the public API only (RFC 0009 D4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from bloomery import load_catalog, load_project
from bloomery.spec import Project, RecipeFieldMapping

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load_fixture_project(name: str) -> Project:
    sources = {
        path.stem: path.read_text()
        for path in sorted((FIXTURES / name).glob("*.yaml"))
        if path.stem != "catalog"
    }
    return load_project(sources)


def test_minimal_loads_clean() -> None:
    project = load_fixture_project("minimal")
    assert set(project.entity_model.entities) == {"event"}
    assert len(project.mappings) == 1
    assert project.mappings[0].target == "event"
    assert project.metric_set is None
    assert project.marts is None


def test_ecom_basic_loads_clean() -> None:
    project = load_fixture_project("ecom_basic")
    assert set(project.entity_model.entities) == {"order_item", "order"}
    assert [m.target for m in project.mappings] == ["order_item", "order"]

    unit_price = project.mappings[0].fields["unit_price"]
    assert isinstance(unit_price, RecipeFieldMapping)  # catalog derivation recorded

    assert project.metric_set is not None
    aov = project.metric_set.metrics["average_order_value"]
    assert aov.additivity == "non_additive"
    assert aov.ratio is not None  # ratio metric per RFC 0009 fixture table

    assert project.marts is not None
    mart = project.marts.marts["order_items"]
    roles = [step.role for step in mart.flatten if hasattr(step, "role")]
    assert roles == ["ordered"]  # measure-carrying mart has a date role (RFC 0010 D9)
    assert mart.measures == ("gross_revenue",)


def test_ecom_basic_catalog_loads_clean() -> None:
    catalog = load_catalog((FIXTURES / "ecom_basic" / "catalog.yaml").read_text())
    assert catalog.vertical == "ecom_retail"
    assert "unit_price" in catalog.canonical_fields
    recipes = catalog.canonical_fields["unit_price"].recipes
    assert [r.id for r in recipes] == ["direct", "from_total"]  # reliability order
    aov = catalog.metric_templates["average_order_value"]
    assert aov.ratio is not None


def test_fanout_trap_loads_clean() -> None:
    # Parses clean; the refusal is the guardrail stage's (RFC 0006), not parse's.
    project = load_fixture_project("fanout_trap")
    assert set(project.entity_model.entities) == {"order_item", "order"}
    (rel,) = project.entity_model.relationships
    assert rel.cardinality == "many_to_one"
    catalog = load_catalog((FIXTURES / "fanout_trap" / "catalog.yaml").read_text())
    assert catalog.canonical_fields["shipping_cost"].entity == "order"
    assert catalog.canonical_fields["landed_cost"].entity == "order_item"


def test_semi_additive_inventory_loads_clean() -> None:
    project = load_fixture_project("semi_additive_inventory")
    assert set(project.entity_model.entities) == {"inventory_level"}
    assert project.metric_set is not None
    stock = project.metric_set.metrics["stock_on_hand"]
    assert stock.additivity == "semi_additive"
    assert stock.semi_additive is not None
    assert stock.semi_additive.over == "stock_date"
    assert stock.semi_additive.rule == "last"


def test_path_conflict_loads_clean() -> None:
    project = load_fixture_project("path_conflict")
    net_price = project.mappings[0].fields["net_price"]
    assert isinstance(net_price, RecipeFieldMapping)
    assert net_price.recipe == "from_total"
    assert net_price.direct == "$.price"  # the recorded path-conflict state
