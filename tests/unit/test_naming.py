"""Naming policies (S-0025/ports): the only tenant-shaped seam — scoping is
ordinary constructor values, nothing else in the package knows the concept."""

from __future__ import annotations

import pytest

from bloomery.ir import Layer
from bloomery.naming import DefaultNaming, NamingPolicy, PrefixNaming, qualified

pytestmark = pytest.mark.unit


def test_default_naming_layers() -> None:
    naming = DefaultNaming()
    assert naming.relation("raw__events", Layer.BRONZE) == ("bronze", "raw__events")
    assert naming.relation("order_item", Layer.SILVER) == ("silver", "order_item")
    assert naming.relation("order_items", Layer.GOLD) == ("gold", "mart_order_items")


def test_prefix_naming_prefixes_every_namespace() -> None:
    naming = PrefixNaming(prefix="acme")
    assert naming.relation("raw__events", Layer.BRONZE) == ("acme_bronze", "raw__events")
    assert naming.relation("order_item", Layer.SILVER) == ("acme_silver", "order_item")
    assert naming.relation("order_items", Layer.GOLD) == ("acme_gold", "mart_order_items")


def test_policies_satisfy_the_protocol() -> None:
    policies: list[NamingPolicy] = [DefaultNaming(), PrefixNaming(prefix="p")]
    for policy in policies:
        namespace, relation = policy.relation("x", Layer.SILVER)
        assert isinstance(namespace, str) and isinstance(relation, str)


def test_policies_are_frozen_values() -> None:
    with pytest.raises(AttributeError):
        PrefixNaming(prefix="a").prefix = "b"  # type: ignore[misc]


class _Attached:
    """Bronze in one attached catalog, silver and gold in another (#389)."""

    def relation(self, entity: str, layer: Layer) -> tuple[str | None, str, str]:
        namespace, relation = DefaultNaming().relation(entity, layer)
        return (None if layer is Layer.BRONZE else "lake", namespace, relation)


def test_a_pair_names_no_catalog_and_a_triple_names_one() -> None:
    assert qualified(DefaultNaming(), "order", Layer.SILVER) == (None, "silver", "order")
    assert qualified(_Attached(), "order", Layer.SILVER) == ("lake", "silver", "order")
    assert qualified(_Attached(), "src", Layer.BRONZE) == (None, "bronze", "src")


def test_a_catalog_is_a_third_part_not_part_of_the_namespace() -> None:
    """Folded into the namespace it renders as one quoted identifier, a schema
    named `lake.silver` that does not exist."""
    name = qualified(_Attached(), "order", Layer.SILVER)

    assert name.table(alias="o").sql(dialect="duckdb", identify=True) == (
        '"lake"."silver"."order" AS "o"'
    )
    assert name.dotted == "lake.silver.order"
    assert name.path == "lake/silver/order"
    assert qualified(DefaultNaming(), "order", Layer.SILVER).dotted == "silver.order"
