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
    # The vertical-owned date dimension (RFC 0008 D13).
    assert catalog.date_dimension is not None
    assert catalog.date_dimension.name == "dim_date"
    assert (catalog.date_dimension.start_year, catalog.date_dimension.end_year) == (2020, 2030)


def test_fanout_trap_loads_clean() -> None:
    # Parses clean; the refusal is the guardrail stage's (RFC 0006), not parse's.
    project = load_fixture_project("fanout_trap")
    assert set(project.entity_model.entities) == {"order_item", "order"}
    (rel,) = project.entity_model.relationships
    assert rel.cardinality == "many_to_one"
    catalog = load_catalog((FIXTURES / "fanout_trap" / "catalog.yaml").read_text())
    assert catalog.canonical_fields["shipping_cost"].entity == "order"
    assert catalog.canonical_fields["landed_cost"].entity == "order_item"
    # The M5 mart-level trap: the order-grain measure on the item-grain mart.
    assert project.marts is not None
    assert project.marts.marts["order_items"].measures == ("shipping_cost",)


def test_semi_additive_inventory_loads_clean() -> None:
    project = load_fixture_project("semi_additive_inventory")
    assert set(project.entity_model.entities) == {"inventory_level"}
    assert project.metric_set is not None
    stock = project.metric_set.metrics["stock_on_hand"]
    assert stock.additivity == "semi_additive"
    assert stock.semi_additive is not None
    assert stock.semi_additive.over == "stock_date"
    assert stock.semi_additive.rule == "last"
    assert project.marts is not None
    assert project.marts.marts["inventory"].measures == ("stock_on_hand",)


def test_role_playing_dates_loads_clean() -> None:
    project = load_fixture_project("role_playing_dates")
    assert set(project.entity_model.entities) == {"order"}
    assert project.metric_set is not None
    assert project.metric_set.metrics["revenue"].additivity == "additive"
    assert project.marts is not None
    mart = project.marts.marts["orders"]
    roles = [step.role for step in mart.flatten if hasattr(step, "role")]
    assert roles == ["ordered", "shipped"]  # both roles, authored order
    assert mart.measures == ("revenue",)


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5])
def test_evolution_versions_load_clean(version: int) -> None:
    # The RFC 0007 §5.5 spec-evolution sequence (fixtures per RFC 0009).
    project = load_fixture_project(f"evolution_v{version}")
    assert set(project.entity_model.entities) == {"order_item"}
    fields = project.entity_model.entities["order_item"].fields
    assert ("discount" in fields) == (version >= 2)  # v2 adds the optional column
    assert ("qty" in fields) == (version >= 3)  # v3 renames quantity → qty
    if version == 3:
        assert fields["qty"].renamed_from == "quantity"  # one-shot annotation…
    if version >= 4:
        assert fields["qty"].renamed_from is None  # …cleaned after it applies
    assert project.metric_set is not None
    assert ("net_revenue" in project.metric_set.metrics) == (version in {3, 4})
    unit_price = project.mappings[0].fields["unit_price"]
    assert isinstance(unit_price, RecipeFieldMapping)
    assert unit_price.recipe == ("from_total" if version >= 4 else "direct")


def test_scd2_customers_loads_clean() -> None:
    # The M10 SCD type 2 fixture: sqlmesh lowers it to a native SCD kind,
    # dbt to a check-strategy snapshot (RFC 0008 §5.3/§5.5).
    project = load_fixture_project("scd2_customers")
    customer = project.entity_model.entities["customer"]
    assert customer.scd == "type2"
    assert customer.key == ("customer_id",)
    segment = customer.fields["segment"]
    assert segment.assert_ is not None
    assert segment.assert_.enum == ("business", "consumer")


def test_path_conflict_loads_clean() -> None:
    project = load_fixture_project("path_conflict")
    net_price = project.mappings[0].fields["net_price"]
    assert isinstance(net_price, RecipeFieldMapping)
    assert net_price.recipe == "from_total"
    assert net_price.direct == "$.price"  # the recorded path-conflict state
