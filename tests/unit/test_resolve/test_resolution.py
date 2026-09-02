"""The public ``resolve`` API and ``Resolution`` result (RFC 0005 §5.6):
ecom_basic reachable/unreachable reporting (M3's done-condition), provenance,
topo determinism under permuted input, idempotence."""

from __future__ import annotations

import pytest

from bloomery import evaluate, load_catalog, load_project, resolve
from bloomery.ir import UnreachableMetric
from bloomery.resolve import FieldProvenance, Provenance
from bloomery.cli import io
from support.compiling import (
    FIXTURES,
    fixture_sources,
    load_fixture,
    spec_fixture_names,
)

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
        mapping="mapping_order_items",
        provenance=Provenance.RECIPE,
        recipe_id="from_total",
    )
    assert by_field["order_item", "quantity"].provenance is Provenance.DIRECT
    assert by_field["order_item", "order_date"].provenance is Provenance.NATIVE
    assert by_field["order", "customer_id"].provenance is Provenance.NATIVE
    assert by_field["order", "order_id"].provenance is Provenance.NATIVE
    # Sorted by (entity, field, mapping) — RFC 0005 D6, RFC 0032 D7.
    keys = [(p.entity, p.field, p.mapping) for p in resolution.provenance]
    assert keys == sorted(keys)


def test_every_mapped_field_appears_exactly_once() -> None:
    """The report's *population*, swept over the corpus and named.

    Every mapped field, key fields included, exactly once **per mapping that
    builds it** (RFC 0032 D1) — which is the invariant that replaced "last
    write wins", and the one a future change to the merged shape would break
    first. It says nothing about the provenance *kind*, which is pinned above;
    this is the width, and the corpus is the only place wide enough to measure
    it. A change to the number below is a change to the corpus or to the
    population and should be read as one, which is why it is named rather than
    floored: a floor cannot tell a fixture that stopped resolving from one that
    never existed.
    """
    swept = 0
    for name in spec_fixture_names():
        project, catalog = load_fixture(name)
        mapped = {
            (mapping.target, field, mapping.document)
            for mapping in project.mappings
            for field in (*mapping.key, *mapping.fields)
        }
        reported = [
            (entry.entity, entry.field, entry.mapping)
            for entry in resolve(project, catalog).provenance
        ]
        assert len(reported) == len(set(reported)), f"{name}: a field is reported twice"
        assert set(reported) == mapped, f"{name}: the report and the mappings disagree"
        swept += len(mapped)

    # RFC 0031 §3 measured 146 when the key was `(entity, field)`. Keying on
    # the mapping too adds the 4 facts `multi_source`'s merged `order_line`
    # could not represent — the whole of what RFC 0032 recovers in this corpus,
    # reported as a number rather than a claim.
    assert swept == 162, f"{swept} mapped (entity, field, mapping) triples across the corpus"


def test_every_mappings_document_is_a_real_document() -> None:
    """The identity is total and correct across the corpus, not merely set.

    Every mapping's `document` must be a key of the spec directory it was read
    from. A field that is present but wrong — an empty string, a stale name,
    the same name on every mapping — satisfies "the report names a mapping" and
    sends a reader to a document that does not exist, which is worse than the
    omission it replaced.
    """
    swept = 0
    for name in spec_fixture_names():
        sources, _catalog = io.read_spec_directory(str(FIXTURES / name))
        documents = set(sources)
        for mapping in load_project(sources).mappings:
            assert mapping.document in documents, (
                f"{name}: mapping for {mapping.target!r} names {mapping.document!r}, "
                f"which is not one of {sorted(documents)}"
            )
            swept += 1

    assert swept > 0, "no mapping in the corpus — this proved nothing"


def test_renaming_a_mapping_document_moves_the_report_and_nothing_else() -> None:
    """RFC 0032 D4's boundary, asserted rather than intended.

    The identity is a filename, so a rename *is* a change of identity — which
    is only acceptable because nothing durable is keyed on it. That is a claim
    about reach, and reach is the thing a later change breaks without noticing:
    threading `document` into an IR node would leave every test here green
    while making a renamed file a rebuild, since the fingerprint is what a plan
    compares.

    Both halves, because either alone is satisfiable by a mistake. A stable
    fingerprint with unchanged provenance would mean the rename never took.
    """
    sources, catalog_text = io.read_spec_directory(str(FIXTURES / "multi_source"))
    renamed = {f"zz_{name}": text for name, text in sources.items() if "mapping" in name}
    renamed |= {name: text for name, text in sources.items() if "mapping" not in name}
    assert set(renamed) != set(sources), "the rename must actually rename something"

    catalog = load_catalog(catalog_text) if catalog_text else None
    before = evaluate(load_project(sources), catalog=catalog)
    after = evaluate(load_project(renamed), catalog=catalog)

    assert before.fingerprint == after.fingerprint, "a rename must not be a rebuild"
    assert [(e.entity, e.field) for e in before.provenance] == [
        (e.entity, e.field) for e in after.provenance
    ]
    assert [e.mapping for e in before.provenance] != [e.mapping for e in after.provenance], (
        "the report is the one thing a rename does move"
    )


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
