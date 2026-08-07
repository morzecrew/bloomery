"""``test_row_policy_survives_every_path`` — the named MANDATORY pre-merge
test (RFC 0011 D10, RFC 0013 D9, RFC 0009 §5.10): for an exhaustive request
matrix (limits, ordering, filters, time grains; plain, ratio, and
semi-additive metrics), plan with a ``RowPolicy`` and assert — on the
**parsed AST**, never a substring ("a string check passes on a commented-out
predicate") — that the policy predicate is present in EVERY scan of the mart
relation, at or below the first aggregation over that scan.

Assert "every scan", never a fixed subquery count: the optimizer may
collapse a ratio's component subqueries into one shared scan (RFC 0013
§5.9d)."""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import pytest

from bloomery import MetricRequest, OrderSpec, RowPolicy, TimeGrain
from bloomery.planner import FilterExpr
from support.planning import audit_scans, fixture_ir, make_planner

pytestmark = pytest.mark.unit

PLANNER = make_planner()


@dataclass(frozen=True)
class Scenario:
    fixture: str
    relation: str
    policy: RowPolicy
    metrics: tuple[str, ...]
    dimension: str
    time_dimension: str
    filter_expr: FilterExpr


SCENARIOS = [
    # Semi-additive: the MAX-join plan scans the mart more than once.
    Scenario(
        fixture="semi_additive_inventory",
        relation="gold.mart_inventory",
        policy=RowPolicy("warehouse_id", "eq", "A"),
        metrics=("stock_on_hand",),
        dimension="warehouse_id",
        time_dimension="snapshot_month",
        filter_expr=FilterExpr("snapshot_day", "between", ("2024-01-01", "2024-01-03")),
    ),
    # Ratio: components may collapse to one shared scan — audit every scan.
    Scenario(
        fixture="non_additive_aov",
        relation="gold.mart_orders",
        policy=RowPolicy("store", "eq", "acme"),
        metrics=("average_order_value",),
        dimension="store",
        time_dimension="ordered_month",
        filter_expr=FilterExpr("ordered_day", "gte", ("2024-01-01",)),
    ),
    # Plain additive, multi-metric.
    Scenario(
        fixture="non_additive_aov",
        relation="gold.mart_orders",
        policy=RowPolicy("store", "eq", "acme"),
        metrics=("order_count", "revenue"),
        dimension="store",
        time_dimension="ordered_month",
        filter_expr=FilterExpr("ordered_day", "lt", ("2024-06-01",)),
    ),
]


def _requests(scenario: Scenario) -> list[MetricRequest]:
    """The exhaustive matrix: dimensions × filters × time grains × order/limit."""
    dimension_options: list[tuple[str, ...]] = [
        (),
        (scenario.dimension,),
        (scenario.time_dimension,),
        (scenario.dimension, scenario.time_dimension),
    ]
    filter_options: list[tuple[FilterExpr, ...]] = [(), (scenario.filter_expr,)]
    grain_options: list[TimeGrain | None] = [None, TimeGrain.MONTH, TimeGrain.YEAR]
    tail_options: list[tuple[tuple[OrderSpec, ...], int | None]] = [
        ((), None),
        ((OrderSpec(scenario.metrics[0], "desc"),), 7),
    ]
    requests = []
    for dimensions, filters, grain, (order_by, limit) in itertools.product(
        dimension_options, filter_options, grain_options, tail_options
    ):
        requests.append(
            MetricRequest(
                metrics=scenario.metrics,
                dimensions=dimensions,
                filters=filters,
                time_grain=grain,
                order_by=order_by,
                limit=limit,
            )
        )
    return requests


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: f"{s.fixture}-{s.metrics[0]}")
def test_row_policy_survives_every_path(scenario: Scenario) -> None:
    ir = fixture_ir(scenario.fixture)
    requests = _requests(scenario)
    assert len(requests) == 48  # the matrix stays exhaustive, not vestigial
    for request in requests:
        plan = PLANNER.plan(ir, request, dialect="duckdb", policy=scenario.policy)
        verdicts = audit_scans(
            plan.sql,
            scenario.relation,
            scenario.policy.dimension,
            str(scenario.policy.value),
        )
        assert verdicts, f"no scan of {scenario.relation} found:\n{plan.sql}"
        unprotected = [scan for scan, protected in verdicts if not protected]
        assert not unprotected, (
            f"policy predicate missing from scan(s) {unprotected} for request "
            f"{request}:\n{plan.sql}"
        )


def test_policy_alone_still_reaches_every_scan() -> None:
    """The degenerate request (metrics only, no user filters) must still be
    scoped — dropping a row policy fails open (RFC 0011 §9)."""
    ir = fixture_ir("semi_additive_inventory")
    plan = PLANNER.plan(
        ir,
        MetricRequest(metrics=("stock_on_hand",)),
        dialect="duckdb",
        policy=RowPolicy("warehouse_id", "eq", "A"),
    )
    verdicts = audit_scans(plan.sql, "gold.mart_inventory", "warehouse_id", "A")
    assert verdicts and all(protected for _scan, protected in verdicts)
