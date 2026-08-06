"""The public ``resolve`` API and ``Resolution`` result (RFC 0005 §5.6):
ecom_basic reachable/unreachable reporting (M3's done-condition), provenance,
topo determinism under permuted input, idempotence."""

from __future__ import annotations

import pytest

from bloomery import load_project, resolve
from bloomery.ir import UnreachableMetric
from bloomery.resolve import FieldProvenance, Provenance
from support.compiling import fixture_sources, load_fixture

pytestmark = pytest.mark.unit


def test_ecom_basic_reachable_and_unreachable_reporting() -> None:
    """The M3 done-condition (RFC 0005 §12): reachable metrics named, and
    margin unreachable with the specific missing leaf `cogs`."""
    project, catalog = load_fixture("ecom_basic")
    resolution = resolve(project, catalog)
    assert resolution.reachable_metrics == (
        "average_order_value",
        "gross_revenue",
        "order_count",
    )
    assert resolution.unreachable_metrics == (
        UnreachableMetric(name="margin", missing=("cogs",)),
    )


def test_ecom_basic_provenance() -> None:
    project, catalog = load_fixture("ecom_basic")
    resolution = resolve(project, catalog)
    by_field = {(p.entity, p.field): p for p in resolution.provenance}
    assert by_field["order_item", "unit_price"] == FieldProvenance(
        entity="order_item",
        field="unit_price",
        provenance=Provenance.RECIPE,
        recipe_id="from_total",
    )
    assert by_field["order_item", "quantity"].provenance is Provenance.DIRECT
    assert by_field["order_item", "order_date"].provenance is Provenance.NATIVE
    assert by_field["order", "customer_id"].provenance is Provenance.NATIVE
    assert by_field["order", "order_id"].provenance is Provenance.NATIVE
    # Sorted by (entity, field) — RFC 0005 D6.
    keys = [(p.entity, p.field) for p in resolution.provenance]
    assert keys == sorted(keys)


def test_minimal_resolves_catalog_free() -> None:
    """RFC 0005 §5.6: a catalog-free project is direct-and-native only, with
    no reachable metrics by construction."""
    project, _ = load_fixture("minimal")
    resolution = resolve(project)
    assert resolution.reachable_metrics == ()
    assert resolution.unreachable_metrics == ()
    assert {p.provenance for p in resolution.provenance} == {Provenance.NATIVE}
    assert [n.name for n in resolution.topo_order] == [
        "source.raw__events.$.id",
        "event.event_id",
        "source.raw__events.$.kind",
        "event.kind",
        "source.raw__events.$.ts",
        "event.occurred_at",
    ]


def test_resolve_is_idempotent() -> None:
    project, catalog = load_fixture("ecom_basic")
    assert resolve(project, catalog) == resolve(project, catalog)


def test_resolution_is_invariant_under_document_key_order() -> None:
    """Reordering YAML mapping keys (dict insertion order) must not move a
    single byte of the resolution (RFC 0005 D5)."""
    sources = fixture_sources("minimal")
    reordered = dict(sources)
    reordered["mapping"] = reordered["mapping"].replace(
        'fields:\n  kind: {from: "$.kind"}\n  occurred_at: {from: "$.ts"}',
        'fields:\n  occurred_at: {from: "$.ts"}\n  kind: {from: "$.kind"}',
    )
    assert reordered["mapping"] != sources["mapping"]  # the rewrite happened
    assert resolve(load_project(sources)) == resolve(load_project(reordered))
