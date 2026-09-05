"""The additivity guard (RFC 0006 §5.4, D6, D11): non-additive metrics need
components and never materialize as stored columns; semi-additive metrics
need their policy and never aggregate their own over: dimension away.

And since RFC 0038 D1/D2, the third rule: ``additivity: additive`` is checked
rather than trusted. The two false shapes it catches are an aggregate that
cannot be re-aggregated, and a measure summed across the axis its own origin
grain is taken along."""

from __future__ import annotations

import pytest
from typing import get_args

from bloomery.errors import (
    AdditivityViolation,
    FalseAdditivityClaim,
    NonAdditiveWithoutComponents,
)
from bloomery.guardrails.additivity import check_additivity
from bloomery.spec.common import AdditivityName
from bloomery.ir import (
    RESOLVABLE,
    Additivity,
    MartDimensionIR,
    MartIR,
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
    SourceColumnIR,
    SourceIR,
    SqlExpr,
)
from bloomery.typing import DateType, DecimalType, StringType

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
        sources=(
            SourceIR(
                relation="src",
                columns=tuple(
                    SourceColumnIR(name=name, expr=SqlExpr(name)) for name in column_names
                ),
            ),
        ),
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


# ----------------------- #
# RFC 0038 — an `additive` claim is checked, not trusted


def _snapshot_entity() -> EntityIR:
    """An entity keyed on an identity *and a date*: one row per account per
    day, which is what makes each row a snapshot rather than an event."""

    columns = (
        ColumnIR(
            name=name,
            type=type_,
            canonical=None,
            unit=None,
            tax_basis=None,
            renamed_from=None,
            required=False,
        )
        for name, type_ in (
            ("account_id", StringType()),
            ("as_of_day", DateType()),
            ("balance", DecimalType(12, 4)),
        )
    )
    return EntityIR(
        name="balance",
        grain="one row per account per day",
        key=("account_id", "as_of_day"),
        scd=SCDKind.TYPE1,
        materialization=Materialization.FULL,
        partition_by=(),
        columns=tuple(columns),
        sources=(SourceIR(relation="src", columns=()),),
    )


@pytest.mark.parametrize("agg", ["avg", "median", "count_distinct"])
def test_an_additive_claim_over_a_non_reaggregable_agg_is_refused(agg: str) -> None:
    """``AVG(AVG(x))`` weights each group equally instead of each row, so it is
    wrong wherever groups differ in size — which is every real dataset."""
    metric = MetricIR(
        name="average_item_price",
        grain="item",
        additivity=Additivity.ADDITIVE,
        agg=agg,
        expr=SqlExpr("price"),
        ratio=None,
        semi_additive=None,
    )
    (violation,) = check_additivity(ProjectIR(metrics=(metric,)))

    assert isinstance(violation, FalseAdditivityClaim)
    assert violation.source_path == "metrics: metrics.average_item_price"
    assert f"agg: {agg}" in str(violation)
    assert "ratio: {numerator, denominator}" in str(violation)


@pytest.mark.parametrize("agg", ["sum", "min", "max", "count"])
def test_an_additive_claim_over_a_reaggregable_agg_passes(agg: str) -> None:
    """The control that keeps the rule from being "additive is suspicious".
    A sum of sums is a sum; only the aggregates that consume their input are
    refused."""
    metric = MetricIR(
        name="revenue",
        grain="item",
        additivity=Additivity.ADDITIVE,
        agg=agg,
        expr=SqlExpr("price"),
        ratio=None,
        semi_additive=None,
    )
    assert check_additivity(ProjectIR(metrics=(metric,))) == []


def _balance_metric() -> MetricIR:
    return MetricIR(
        name="total_balance",
        grain="balance",
        additivity=Additivity.ADDITIVE,
        agg="sum",
        expr=SqlExpr("balance"),
        ratio=None,
        semi_additive=None,
    )


def _mart_exposing(column: str) -> MartIR:
    """A mart carrying the measure and offering ``column`` as a dimension —
    which is what makes the axis reachable by a rollup at all."""

    return MartIR(
        name="balances",
        grain="balance",
        base="balance",
        columns=(),
        measures=("total_balance",),
        dimensions=(MartDimensionIR(ref=DimensionRef(dimension=column), column=column),),
        joins=(),
        partition_by=(),
        materialization=Materialization.FULL,
    )


def test_an_additive_claim_on_an_exposed_snapshot_axis_is_refused() -> None:
    project = ProjectIR(
        entities=(_snapshot_entity(),),
        metrics=(_balance_metric(),),
        marts=(_mart_exposing("as_of_day"),),
    )
    (violation,) = check_additivity(project)

    assert isinstance(violation, FalseAdditivityClaim)
    assert "'as_of_day'" in str(violation)
    assert "semi_additive" in str(violation)
    # The remediation names the axis it stays additive across, not just the one
    # it does not — an author told only what is wrong re-declares it wrongly.
    assert "account_id" in str(violation)


def test_a_temporal_key_no_mart_exposes_is_not_a_false_claim() -> None:
    """The narrowing D-107 forced, and the reason it is not a weakening.

    An entity keyed ``(payment_id, paid_at)`` is one row per payment — the
    temporal column is functionally dependent on the identity and the key is
    merely redundant. Nothing in the key tells that apart from a real snapshot,
    so refusing on the key alone would tell this author to declare
    ``semi_additive`` over an axis that does not exist: a wrong instruction,
    which is worse than a missing one.
    """
    project = ProjectIR(entities=(_snapshot_entity(),), metrics=(_balance_metric(),))

    assert check_additivity(project) == []


def test_a_mart_exposing_some_other_date_does_not_expose_this_axis() -> None:
    """The mart has to offer *the temporal determinant*, not merely some date.

    A balances mart flattening `opened_on` carries the measure and has a date
    role, and still gives no way to sum across `as_of_day` — so there is no
    false claim here. Found by sabotage: replacing the column comparison with
    `True` failed nothing, because every other case in this file either has no
    mart or has the matching one.
    """
    project = ProjectIR(
        entities=(_snapshot_entity(),),
        metrics=(_balance_metric(),),
        marts=(_mart_exposing("opened_on"),),
    )

    assert check_additivity(project) == []


def test_a_mart_carrying_a_different_measure_does_not_expose_the_axis() -> None:
    """The mart has to carry *this* measure. One flattening the same column for
    some other metric says nothing about whether this one is rolled up over
    it."""
    mart = MartIR(
        name="other",
        grain="balance",
        base="balance",
        columns=(),
        measures=("something_else",),
        dimensions=(
            MartDimensionIR(ref=DimensionRef(dimension="as_of_day"), column="as_of_day"),
        ),
        joins=(),
        partition_by=(),
        materialization=Materialization.FULL,
    )
    project = ProjectIR(
        entities=(_snapshot_entity(),), metrics=(_balance_metric(),), marts=(mart,)
    )

    assert check_additivity(project) == []


def test_an_additive_claim_on_a_grain_with_no_temporal_key_passes() -> None:
    """The control. `item` is keyed on `item_id` alone, so nothing here is a
    snapshot and a sum over it is honest."""
    metric = MetricIR(
        name="revenue",
        grain="item",
        additivity=Additivity.ADDITIVE,
        agg="sum",
        expr=SqlExpr("price"),
        ratio=None,
        semi_additive=None,
    )
    entity = _entity("item_id", "price")
    assert check_additivity(ProjectIR(entities=(entity,), metrics=(metric,))) == []


def test_a_temporal_column_outside_the_key_does_not_make_a_snapshot() -> None:
    """An event entity carries a timestamp and is keyed on its own id — one
    row per order, not one row per order per day. Reading every date column
    rather than the key's would refuse most of the corpus."""
    columns = (
        ColumnIR(
            name=name, type=type_, canonical=None, unit=None,
            tax_basis=None, renamed_from=None, required=False,
        )
        for name, type_ in (
            ("order_id", StringType()),
            ("ordered_at", DateType()),
            ("amount", DecimalType(12, 4)),
        )
    )
    entity = EntityIR(
        name="order",
        grain="one row per order",
        key=("order_id",),
        scd=SCDKind.TYPE1,
        materialization=Materialization.FULL,
        partition_by=(),
        columns=tuple(columns),
        sources=(SourceIR(relation="src", columns=()),),
    )
    metric = MetricIR(
        name="revenue",
        grain="order",
        additivity=Additivity.ADDITIVE,
        agg="sum",
        expr=SqlExpr("amount"),
        ratio=None,
        semi_additive=None,
    )
    assert check_additivity(ProjectIR(entities=(entity,), metrics=(metric,))) == []


def test_a_metric_whose_grain_names_no_entity_is_left_to_its_own_guard() -> None:
    """Grain resolution is not this guard's job, and inventing a refusal here
    would give an author two errors for one mistake — the second naming
    additivity, which is not what is wrong."""
    metric = MetricIR(
        name="revenue",
        grain="nonexistent",
        additivity=Additivity.ADDITIVE,
        agg="sum",
        expr=SqlExpr("amount"),
        ratio=None,
        semi_additive=None,
    )
    assert check_additivity(ProjectIR(metrics=(metric,))) == []


def test_only_the_resolvable_members_can_reach_the_guard() -> None:
    """The canary RFC 0038 D1's closed enum owes (see logs/T-0019.md, D-105).

    Twenty sites across the emitters, the planner and the guardrails branch on
    `Additivity`, every one of them on NON_ADDITIVE or SEMI_ADDITIVE — so the
    three members D1 added are catch-alls at each of them, and mypy cannot see
    it. They are safe only while nothing mints them.

    This fails the moment resolution can produce one, which is where that
    decision has to be made rather than inherited. What those sites actually
    ask is whether a metric is a stored measure: `no` for RATIO, `yes` for
    SNAPSHOT and DISTINCT_COUNT.
    """
    # Against the authored grammar, not against itself: `AdditivityName` is
    # what a project can actually write, so this is the edge a new member has
    # to cross to become reachable. Comparing RESOLVABLE to a restatement of
    # its own contents would pass however either side changed.
    assert set(get_args(AdditivityName)) == {member.value for member in RESOLVABLE}

    assert set(Additivity) - set(RESOLVABLE) == {
        Additivity.RATIO,
        Additivity.DISTINCT_COUNT,
        Additivity.SNAPSHOT,
    }, "a member left the unreachable set without those twenty branches being revisited"
