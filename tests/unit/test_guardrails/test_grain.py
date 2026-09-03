"""The grain guard (RFC 0006 §5.3, D5): the fan-out refusal on derivations
and on metric expressions spanning entities with different grains — trigger,
aggregated non-trigger, relationship naming, and both grains in the message."""

from __future__ import annotations

import pytest

from bloomery import load_catalog, load_project
from bloomery.errors import GrainMismatch
from bloomery.guardrails.grain import check_grain
from bloomery.guardrails.operands import Derivation
from bloomery.ir import (
    Additivity,
    Cardinality,
    MetricIR,
    ProjectIR,
    RelationshipIR,
    SqlExpr,
)

pytestmark = pytest.mark.unit

CATALOG = load_catalog(
    """\
catalog_version: 1
vertical: v
canonical_fields:
  price: {entity: order_item, type: "decimal(12,4)", unit: currency, tax_basis: net}
  ship: {entity: order, type: "decimal(12,4)", unit: currency, tax_basis: net}
  far_level: {entity: warehouse, type: int, unit: count}
"""
)

PROJECT = load_project(
    {
        "entity_model": """\
spec_version: 1
entities:
  order_item:
    grain: one row per line on an order
    key: [order_id, line_no]
    fields:
      order_id: {type: string, required: true}
      line_no: {type: int, required: true}
  order:
    grain: one row per order
    key: [order_id]
    fields:
      order_id: {type: string, required: true}
relationships:
  - name: item_of_order
    from: order_item
    to: order
    via: {order_id: order_id}
    cardinality: many_to_one
"""
    }
)

DRAFT = ProjectIR(
    relationships=(
        RelationshipIR(
            name="item_of_order",
            from_entity="order_item",
            to_entity="order",
            via=(("order_id", "order_id"),),
            cardinality=Cardinality.MANY_TO_ONE,
        ),
    )
)


def _derivation(entity: str, expr: str | None, *operands: str) -> Derivation:
    return Derivation(
        source_path=f"mapping[s->{entity}]: fields.f",
        source="s",
        cleaned=False,
        entity=entity,
        field="f",
        expr=expr,
        operands=operands,
        direct=None,
    )


def _check(entity: str, expr: str | None, *operands: str) -> list[Exception]:
    return list(check_grain((_derivation(entity, expr, *operands),), DRAFT, PROJECT, CATALOG))


def test_coarser_operand_joined_down_is_a_grain_mismatch() -> None:
    (violation,) = _check("order_item", "price + ship", "price", "ship")
    assert isinstance(violation, GrainMismatch)
    message = str(violation)
    assert "one row per line on an order" in message  # both grains named
    assert "one row per order" in message
    assert "relationship 'item_of_order' (many_to_one)" in message
    assert "aggregation" in message
    assert "Fix:" in message


def test_shared_grain_passes() -> None:
    assert _check("order_item", "price * 2", "price") == []


def test_aggregated_coarse_operand_passes() -> None:
    # The sanctioned way in (RFC 0006 D5): an explicit aggregation step.
    assert _check("order", "SUM(price)", "price") == []


def test_partially_aggregated_operand_still_fails() -> None:
    violations = _check("order", "SUM(price) + price", "price")
    assert [type(v) for v in violations] == [GrainMismatch]


def test_operand_absent_from_the_expression_still_fails() -> None:
    # Required at a foreign grain but never aggregated: nothing sanctions it.
    violations = _check("order_item", "price", "price", "ship")
    assert [type(v) for v in violations] == [GrainMismatch]


def test_identity_derivation_at_a_foreign_grain_fails() -> None:
    (violation,) = _check("order_item", None, "ship")
    assert isinstance(violation, GrainMismatch)


def test_inverse_relationship_direction_is_reported() -> None:
    (violation,) = _check("order", "price", "price")
    assert "relationship 'item_of_order' (one_to_many, read inversely)" in str(violation)


def test_unrelated_entities_report_no_declared_relationship() -> None:
    (violation,) = _check("order_item", "far_level", "far_level")
    message = str(violation)
    assert "no declared relationship" in message
    assert "undeclared in this project" in message  # warehouse has no grain here


def test_non_canonical_operands_are_not_grain_checked() -> None:
    # A mapping-local alias has no declared home entity (RFC 0006 D3).
    assert _check("order_item", "line_total / qty", "line_total", "qty") == []


# ....................... #
# Metric expressions


def _metric(grain: str, expr: str | None, *depends_on: str) -> MetricIR:
    return MetricIR(
        name="m",
        grain=grain,
        additivity=Additivity.ADDITIVE,
        agg="sum",
        expr=SqlExpr(expr) if expr is not None else None,
        ratio=None,
        semi_additive=None,
        depends_on=depends_on,
    )


def _check_metric(metric: MetricIR) -> list[Exception]:
    draft = ProjectIR(metrics=(metric,), relationships=DRAFT.relationships)
    return list(check_grain((), draft, PROJECT, CATALOG))


def test_metric_requires_spanning_grains_fail() -> None:
    (violation,) = _check_metric(_metric("order_item", "price + ship", "price", "ship"))
    assert isinstance(violation, GrainMismatch)
    assert violation.source_path == "metrics: metrics.m"
    assert "one row per order" in str(violation)
    assert "one row per line on an order" in str(violation)


def test_metric_with_aggregated_foreign_operand_passes() -> None:
    assert _check_metric(_metric("order_item", "price + SUM(ship)", "price", "ship")) == []


def test_metric_on_a_single_entity_passes() -> None:
    assert _check_metric(_metric("order_item", "price * 2", "price")) == []


def test_metric_without_an_expression_is_skipped() -> None:
    assert _check_metric(_metric("order_item", None, "price", "ship")) == []


def test_metric_whose_grain_names_no_entity_reports_the_span() -> None:
    (violation,) = _check_metric(_metric("", "price + ship", "price", "ship"))
    message = str(violation)
    assert "names none of them" in message
    assert "'order' (one row per order)" in message
    assert "'order_item' (one row per line on an order)" in message
