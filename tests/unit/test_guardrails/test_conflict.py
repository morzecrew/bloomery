"""Path conflict (RFC 0006 §5.5, D7): the guardrail that never raises —
derived column kept, ``__direct`` shadow added, reconcile audit emitted."""

from __future__ import annotations

import pytest

from bloomery import build_project_ir, load_catalog, load_project
from bloomery.guardrails.conflict import path_conflict_amendments
from bloomery.guardrails.operands import collect_derivations
from bloomery.ir import AuditIR
from bloomery.typing import DecimalType
from support.compiling import load_fixture

pytestmark = pytest.mark.unit


def test_both_columns_and_the_reconcile_audit_land_in_the_ir() -> None:
    project, catalog = load_fixture("path_conflict")
    ir = build_project_ir(project, catalog)
    (entity,) = ir.entities
    by_name = {column.name: column for column in entity.columns}
    # The shadow lands in **both** halves, and that is the property worth
    # pinning (RFC 0024 D26): a schema column with no projection is a column
    # the SELECT cannot produce, and it would compile clean.
    lowered = {column.name: column for column in entity.sources[0].columns}
    assert sorted(by_name) == ["item_id", "net_price", "net_price__direct", "quantity"]
    assert sorted(lowered) == sorted(by_name)

    derived = by_name["net_price"]
    assert lowered["net_price"].recipe_id == "from_total"  # the recorded decision
    assert lowered["net_price"].expr.sql == "CAST(total / qty AS DECIMAL(12, 4))"

    shadow = by_name["net_price__direct"]
    assert lowered["net_price__direct"].expr.sql == "CAST(price AS DECIMAL(12, 4))"
    assert shadow.type == DecimalType(12, 4)
    assert shadow.canonical == derived.canonical  # same canonical field
    assert shadow.unit == derived.unit
    assert shadow.tax_basis == derived.tax_basis
    assert lowered["net_price__direct"].recipe_id is None
    assert not shadow.required

    assert entity.audits == (
        AuditIR(kind="reconcile", column="net_price", params=(("shadow", "net_price__direct"),)),
    )


def test_amendments_are_computed_per_entity() -> None:
    project, catalog = load_fixture("path_conflict")
    draft = build_project_ir(project, catalog)
    derivations = collect_derivations(project, catalog)
    shadows, audits = path_conflict_amendments(derivations, draft)
    assert sorted(shadows) == ["item"]
    assert [shadow.column.name for shadow in shadows["item"]] == ["net_price__direct"]
    assert sorted(shadows["item"][0].projections) == ["shop__items"]
    assert [audit.column for audit in audits["item"]] == ["net_price"]


def test_a_merged_entity_gets_one_shadow_and_one_projection_per_source() -> None:
    """RFC 0024 D36. The arity is the whole finding: the schema half is
    per *entity* and the lowering half is per *source*.

    Grouping is what decides it — a merged entity has one derivation per
    mapping for the same field, so appending per derivation would hand the
    entity two columns of one name and emit the reconcile audit twice.
    """
    project, catalog = load_fixture("path_conflict_merged")
    draft = build_project_ir(project, catalog)
    derivations = collect_derivations(project, catalog)
    shadows, audits = path_conflict_amendments(derivations, draft)
    (shadow,) = shadows["item"]
    assert shadow.column.name == "net_price__direct"
    assert sorted(shadow.projections) == ["shopify__items", "woo__items"]
    # Each branch reads *its own* mapping's path. `$.price` does not exist on
    # `woo__items`, which is what D28 refused while one shadow stood for all.
    assert shadow.projections["shopify__items"].expr.sql == "CAST(price AS DECIMAL(12, 4))"
    assert shadow.projections["woo__items"].expr.sql == "CAST(unit_amount AS DECIMAL(12, 4))"
    assert [audit.column for audit in audits["item"]] == ["net_price"]


def test_a_merged_entity_carries_the_shadow_on_every_branch_of_the_ir() -> None:
    """The amendment reaching the IR, which is what the SELECT is built from.

    Asserted apart from the function above because the two can disagree: the
    amendments are computed per source and *applied* in `guardrails.stage`,
    and a stage that dropped the fan-out would attach one branch's projection
    to both — a `$.price` extraction off a relation that has no `$.price`.
    """
    project, catalog = load_fixture("path_conflict_merged")
    ir = build_project_ir(project, catalog)
    (entity,) = ir.entities
    assert "net_price__direct" in {column.name for column in entity.columns}
    lowered = {
        source.relation: next(
            column for column in source.columns if column.name == "net_price__direct"
        )
        for source in entity.sources
    }
    assert sorted(lowered) == ["shopify__items", "woo__items"]
    assert lowered["shopify__items"].expr.sql == "CAST(price AS DECIMAL(12, 4))"
    assert lowered["woo__items"].expr.sql == "CAST(unit_amount AS DECIMAL(12, 4))"
    assert entity.audits == (
        AuditIR(kind="reconcile", column="net_price", params=(("shadow", "net_price__direct"),)),
    )


def test_a_branch_that_does_not_map_the_column_gets_a_typed_null_shadow() -> None:
    """The case D36's refusal deliberately does not reach (RFC 0024 §5.2 rule
    3): one mapping declares the optional field with a `direct:` path and the
    other does not declare the field at all.

    There is nothing to refuse — a mapping with no field mapping has nowhere to
    hang a `direct:` — so the branch is NULL-filled for the shadow exactly as
    it already is for the derived column, and the reconcile audit compares NULL
    against NULL and reports nothing. Before the fill this raised
    `InvariantViolated` at compile time on a legal spec.
    """
    sources = {
        "entity_model": """\
spec_version: 1
entities:
  event:
    grain: one row per event
    key: [event_id]
    fields:
      event_id: {type: string, required: true}
      kind: {type: string, canonical: kind}
""",
        "mapping_a": """\
mapping_version: 1
source: src_a
target: event
key:
  event_id: {from: "$.identifier", transform: [to_string]}
fields:
  kind:
    recipe: passthrough
    from: {value: "$.type"}
    direct: "$.kind_direct"
""",
        "mapping_b": """\
mapping_version: 1
source: src_z
target: event
key:
  event_id: {from: "$.id", transform: [to_string]}
""",
    }
    catalog = load_catalog("""\
catalog_version: 1
vertical: ecom_retail
canonical_fields:
  kind:
    entity: event
    type: string
    recipes:
      - {id: passthrough, requires: [value], expr: "value"}
""")
    ir = build_project_ir(load_project(sources), catalog)
    (entity,) = ir.entities
    lowered = {
        source.relation: next(
            column for column in source.columns if column.name == "kind__direct"
        ).expr.sql
        for source in entity.sources
    }
    # Typed, not a bare NULL: an untyped null makes the union's column type
    # depend on which branch the engine reads first.
    assert lowered == {"src_a": "CAST(kind_direct AS TEXT)", "src_z": "CAST(NULL AS TEXT)"}


def test_derivations_without_a_direct_path_amend_nothing() -> None:
    project, catalog = load_fixture("ecom_basic")
    draft = build_project_ir(project, catalog)
    derivations = collect_derivations(project, catalog)
    shadows, audits = path_conflict_amendments(derivations, draft)
    assert shadows == {}
    assert audits == {}
