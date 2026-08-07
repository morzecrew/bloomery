"""The additivity guard (RFC 0006 §5.4, D6, D11): non-additive metrics need
components and never materialize as stored columns; semi-additive metrics
need their policy and never aggregate their own over: dimension away."""

from __future__ import annotations

import pytest

from bloomery.errors import AdditivityViolation, NonAdditiveWithoutComponents
from bloomery.guardrails.additivity import check_additivity
from bloomery.ir import (
    Additivity,
    ColumnIR,
    DimensionRef,
    EntityIR,
    Materialization,
    MetricIR,
    ProjectIR,
    Ratio,
    SCDKind,
    SemiAdditivePolicy,
    SemiAdditiveRule,
    SourceIR,
    SqlExpr,
)
from bloomery.typing import DecimalType, StringType

pytestmark = pytest.mark.unit


def _metric(
    name: str = "m",
    *,
    additivity: Additivity,
    expr: str | None = None,
    ratio: Ratio | None = None,
    semi_additive: SemiAdditivePolicy | None = None,
    depends_on: tuple[str, ...] = (),
) -> MetricIR:
    return MetricIR(
        name=name,
        grain="item",
        additivity=additivity,
        agg="sum",
        expr=SqlExpr(expr) if expr is not None else None,
        ratio=ratio,
        semi_additive=semi_additive,
        depends_on=depends_on,
    )


def _entity(*column_names: str) -> EntityIR:
    columns = tuple(
        ColumnIR(
            name=name,
            type=DecimalType(12, 4) if name != "item_id" else StringType(),
            canonical=None,
            unit=None,
            tax_basis=None,
            expr=SqlExpr(name),
            recipe_id=None,
            renamed_from=None,
            required=False,
        )
        for name in column_names
    )
    return EntityIR(
        name="item",
        grain="one row per item",
        key=("item_id",),
        scd=SCDKind.TYPE1,
        materialization=Materialization.FULL,
        partition_by=(),
        columns=columns,
        source=SourceIR(relation="src"),
    )


POLICY = SemiAdditivePolicy(over=DimensionRef(dimension="stock_date"), rule=SemiAdditiveRule.LAST)


def test_non_additive_without_ratio_or_decomposition_is_refused() -> None:
    metric = _metric("aov", additivity=Additivity.NON_ADDITIVE)
    (violation,) = check_additivity(ProjectIR(metrics=(metric,)))
    assert isinstance(violation, NonAdditiveWithoutComponents)
    assert violation.source_path == "metrics: metrics.aov"
    assert "'aov'" in str(violation)
    assert "ratio: {numerator, denominator}" in str(violation)


def test_non_additive_with_a_ratio_passes() -> None:
    metric = _metric(
        "aov",
        additivity=Additivity.NON_ADDITIVE,
        ratio=Ratio(numerator="revenue", denominator="orders"),
    )
    assert check_additivity(ProjectIR(metrics=(metric,))) == []


def test_non_additive_with_an_additive_decomposition_passes() -> None:
    metric = _metric(
        "rate",
        additivity=Additivity.NON_ADDITIVE,
        expr="wins / attempts",
        depends_on=("attempts", "wins"),
    )
    assert check_additivity(ProjectIR(metrics=(metric,))) == []


def test_non_additive_metric_stored_as_an_entity_column_is_refused() -> None:
    """The M4 stored-number invariant (RFC 0006 D6): metrics never become
    stored entity columns — the only place storage can arise before marts."""
    metric = _metric(
        "average_order_value",
        additivity=Additivity.NON_ADDITIVE,
        ratio=Ratio(numerator="revenue", denominator="orders"),
    )
    draft = ProjectIR(entities=(_entity("item_id", "average_order_value"),), metrics=(metric,))
    (violation,) = check_additivity(draft)
    assert isinstance(violation, AdditivityViolation)
    assert "stored" in str(violation)
    assert "'average_order_value'" in str(violation)
    assert "'item'" in str(violation)


def test_non_additive_metric_with_no_column_collision_passes() -> None:
    metric = _metric(
        "aov",
        additivity=Additivity.NON_ADDITIVE,
        ratio=Ratio(numerator="revenue", denominator="orders"),
    )
    draft = ProjectIR(entities=(_entity("item_id", "net_price"),), metrics=(metric,))
    assert check_additivity(draft) == []


def test_semi_additive_without_a_policy_is_refused() -> None:
    metric = _metric("stock", additivity=Additivity.SEMI_ADDITIVE, expr="stock_level")
    (violation,) = check_additivity(ProjectIR(metrics=(metric,)))
    assert isinstance(violation, AdditivityViolation)
    assert "semi_additive: {over, rule}" in str(violation)
    assert "rule: last|first|avg|min|max" in str(violation)


def test_semi_additive_with_a_policy_passes() -> None:
    metric = _metric(
        "stock", additivity=Additivity.SEMI_ADDITIVE, expr="stock_level", semi_additive=POLICY
    )
    assert check_additivity(ProjectIR(metrics=(metric,))) == []


def test_semi_additive_aggregating_its_over_dimension_is_refused() -> None:
    metric = _metric(
        "stock",
        additivity=Additivity.SEMI_ADDITIVE,
        expr="MAX(stock_date)",
        semi_additive=POLICY,
    )
    (violation,) = check_additivity(ProjectIR(metrics=(metric,)))
    assert isinstance(violation, AdditivityViolation)
    assert "aggregates 'stock_date' away" in str(violation)


def test_semi_additive_without_an_expression_passes_the_over_check() -> None:
    metric = _metric("stock", additivity=Additivity.SEMI_ADDITIVE, semi_additive=POLICY)
    assert check_additivity(ProjectIR(metrics=(metric,))) == []


def test_additive_metrics_are_not_checked() -> None:
    metric = _metric("revenue", additivity=Additivity.ADDITIVE, expr="price * qty")
    assert check_additivity(ProjectIR(metrics=(metric,))) == []
