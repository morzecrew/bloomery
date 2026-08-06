"""Naming policies (RFC 0008 §5.1): the only tenant-shaped seam — scoping is
ordinary constructor values, nothing else in the package knows the concept."""

from __future__ import annotations

import pytest

from bloomery.ir import Layer
from bloomery.naming import DefaultNaming, NamingPolicy, PrefixNaming

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
