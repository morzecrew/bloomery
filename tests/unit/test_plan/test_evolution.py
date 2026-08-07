"""The RFC 0007 §5.5 worked example: ``evolution_v1..v5`` classified exactly
per the table — plan snapshots asserted as whole values (ordering is part of
the contract), plus the negative arms: the v4 → v5′ ``ContractViolation``,
the corrected drop-after-deprecation, and the ``renamed_from`` staleness."""

from __future__ import annotations

from functools import lru_cache

import pytest
from support.compiling import FIXTURES, fixture_sources, load_fixture

from bloomery import build_project_ir, load_catalog, load_project, plan
from bloomery.errors import ContractViolation, RenameTargetMissing
from bloomery.ir import ProjectIR
from bloomery.plan import BackfillScope, Change, ChangeClass, Plan

pytestmark = pytest.mark.unit

_DISCOUNT_ENTITY_LINE = '      discount: {type: "decimal(12,4)", canonical: discount}\n'
_DISCOUNT_MAPPING_LINES = '  discount:\n    recipe: direct\n    from: {discount: "$.discount"}\n'


@lru_cache(maxsize=None)
def evolution_ir(version: int) -> ProjectIR:
    project, catalog = load_fixture(f"evolution_v{version}")
    return build_project_ir(project, catalog)


def evolution_ir_without_discount(version: int) -> ProjectIR:
    """The fixture's spec with the ``discount`` field withdrawn from the
    entity model and mapping — the RFC 0007 §5.5 v5′ (and corrected) drop."""
    sources = fixture_sources(f"evolution_v{version}")
    assert _DISCOUNT_ENTITY_LINE in sources["entity_model"]
    assert _DISCOUNT_MAPPING_LINES in sources["mapping"]
    sources["entity_model"] = sources["entity_model"].replace(_DISCOUNT_ENTITY_LINE, "")
    sources["mapping"] = sources["mapping"].replace(_DISCOUNT_MAPPING_LINES, "")
    catalog_text = (FIXTURES / f"evolution_v{version}" / "catalog.yaml").read_text()
    return build_project_ir(load_project(sources), load_catalog(catalog_text))


EMPTY_SCOPE = BackfillScope(entities=(), restates_history=False)


def test_initial_deploy_is_all_additive() -> None:
    result = plan(None, evolution_ir(1))
    assert result == Plan(
        changes=(
            Change(None, "metric:gross_revenue", ChangeClass.ADDITIVE, "metric added"),
            Change("order_item", "entity:order_item", ChangeClass.ADDITIVE, "entity added"),
            Change(
                "order_item",
                "field:line_no",
                ChangeClass.ADDITIVE,
                "field added",
                new="int, required",
            ),
            Change(
                "order_item",
                "field:order_id",
                ChangeClass.ADDITIVE,
                "field added",
                new="string, required",
            ),
            Change(
                "order_item",
                "field:quantity",
                ChangeClass.ADDITIVE,
                "field added",
                new="int, optional",
            ),
            Change(
                "order_item",
                "field:unit_price",
                ChangeClass.ADDITIVE,
                "field added",
                new="decimal(10,2), optional",
            ),
        ),
        backfill_scope=EMPTY_SCOPE,
        downstream_impact=(),
    )
    assert result.breaking == ()


def test_v1_to_v2_is_additive_discount_plus_widened_unit_price() -> None:
    result = plan(evolution_ir(1), evolution_ir(2))
    assert result.changes == (
        Change(
            "order_item",
            "field:discount",
            ChangeClass.ADDITIVE,
            "field added",
            new="decimal(12,4), optional",
        ),
        Change(
            "order_item",
            "field:unit_price",
            ChangeClass.WIDENING,
            "type widened",
            old="decimal(10,2), optional",
            new="decimal(12,4), optional",
        ),
    )
    assert result.backfill_scope == EMPTY_SCOPE


def test_v2_to_v3_is_one_rename_plus_one_added_metric() -> None:
    result = plan(evolution_ir(2), evolution_ir(3))
    assert result.changes == (
        Change(None, "metric:net_revenue", ChangeClass.ADDITIVE, "metric added"),
        Change(
            "order_item",
            "field:qty",
            ChangeClass.RENAME,
            "renamed from 'quantity'",
            old="quantity",
            new="qty",
        ),
    )
    assert result.backfill_scope == EMPTY_SCOPE


def test_v3_to_v4_recipe_switch_restates_history() -> None:
    result = plan(evolution_ir(3), evolution_ir(4))
    assert result == Plan(
        changes=(
            Change(
                "order_item",
                "field:unit_price",
                ChangeClass.RESTATING,
                "semantics changed (recipe, expression, source)",
                old="direct",
                new="from_total",
            ),
        ),
        backfill_scope=BackfillScope(entities=("order_item",), restates_history=True),
        downstream_impact=("gross_revenue", "net_revenue"),
    )


def test_v4_to_v5_breaking_changes_are_returned_not_raised() -> None:
    result = plan(evolution_ir(4), evolution_ir(5))
    assert result.changes == (
        Change(None, "metric:net_revenue", ChangeClass.BREAKING, "metric removed"),
        Change(
            "order_item",
            "entity:order_item",
            ChangeClass.BREAKING,
            "scd changed",
            old="type1",
            new="type2",
        ),
    )
    assert result.breaking == result.changes
    assert result.backfill_scope == EMPTY_SCOPE


def test_v4_to_v5_prime_dropping_a_referenced_field_is_refused() -> None:
    with pytest.raises(ContractViolation) as caught:
        plan(evolution_ir(4), evolution_ir_without_discount(4))
    message = str(caught.value)
    assert "order_item.discount" in message
    assert "net_revenue" in message
    assert "prior version" in message  # the required expand/contract sequence


def test_dropping_discount_after_deprecation_is_breaking_without_raising() -> None:
    result = plan(evolution_ir(5), evolution_ir_without_discount(5))
    assert [change.subject for change in result.changes] == ["field:discount"]
    assert result.breaking == result.changes


def test_replaying_the_annotated_spec_against_the_applied_ir_is_stale() -> None:
    # After the v3 rename applies and v4 cleans the one-shot annotation,
    # replaying v3's annotated spec raises (RFC 0007 D3 staleness forcing).
    with pytest.raises(RenameTargetMissing, match="'quantity'"):
        plan(evolution_ir(4), evolution_ir(3))


def test_the_annotation_is_stale_on_an_initial_deploy() -> None:
    with pytest.raises(RenameTargetMissing):
        plan(None, evolution_ir(3))


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5])
def test_identity_is_the_empty_plan_for_every_version(version: int) -> None:
    ir = evolution_ir(version)
    assert plan(ir, ir) == Plan(changes=(), backfill_scope=EMPTY_SCOPE, downstream_impact=())
