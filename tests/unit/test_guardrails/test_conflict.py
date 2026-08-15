"""Path conflict (RFC 0006 §5.5, D7): the guardrail that never raises —
derived column kept, ``__direct`` shadow added, reconcile audit emitted."""

from __future__ import annotations

import pytest

from bloomery import build_project_ir
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
    lowered = {column.name: column for column in entity.source.columns}
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
    assert [column.name for column, _ in shadows["item"]] == ["net_price__direct"]
    assert [audit.column for audit in audits["item"]] == ["net_price"]


def test_derivations_without_a_direct_path_amend_nothing() -> None:
    project, catalog = load_fixture("ecom_basic")
    draft = build_project_ir(project, catalog)
    derivations = collect_derivations(project, catalog)
    shadows, audits = path_conflict_amendments(derivations, draft)
    assert shadows == {}
    assert audits == {}
