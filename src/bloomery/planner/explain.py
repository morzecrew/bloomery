"""Explanation building (RFC 0013 §5.8, D10; RFC 0011 D8): the deterministic
provenance record, assembled from the **structured**
``MetricFlowExplainResult.query_spec`` (typed objects) plus the IR — never
scraped from the SQL comments MetricFlow also emits (comments are a
rendering detail that changes between versions). Everything is translated
back into bloomery names via :mod:`bloomery.planner.names`; ``render()``
output is locked by tests.

Lowering notes (RFC 0011 D5 vocabulary, fixed strings the docs cite):

- additive → ``additive — SUM`` (or the metric's aggregation);
- semi-additive → ``semi-additive last over snapshot_day — MAX-join then
  SUM``;
- non-additive ratio → ``non-additive ratio — recomputed at the requested
  grain, not summed``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bloomery.errors import PlannerError
from bloomery.ir import Additivity, Layer, SemiAdditiveRule
from bloomery.planner.result import Explanation, MeasureExplanation

if TYPE_CHECKING:
    from metricflow.engine.metricflow_engine import MetricFlowExplainResult

    from bloomery.ir import MartIR, MetricIR, ProjectIR
    from bloomery.naming import NamingPolicy
    from bloomery.planner.coverage import Coverage
    from bloomery.planner.request import FilterExpr, JsonScalar, MetricRequest

__all__ = [
    "build",
]

_RATIO_NOTE = "non-additive ratio — recomputed at the requested grain, not summed"

_WINDOWS = {SemiAdditiveRule.LAST: "MAX", SemiAdditiveRule.FIRST: "MIN"}


def _day_column(mart: MartIR, source_column: str) -> str:
    """The day-bucket column serving a source date column — the same rule
    the emitter's ``non_additive_dimension`` lowering applies."""
    for column in mart.columns:  # sorted by name; first role wins, as emitted
        if (
            column.ref is not None
            and column.ref.dimension == "day"
            and column.source_column == source_column
        ):
            return column.name
    return source_column


def _measure_explanation(metric: MetricIR, mart: MartIR) -> MeasureExplanation:
    additivity = metric.additivity.value
    if metric.additivity is Additivity.NON_ADDITIVE:
        if metric.ratio is None:  # pragma: no cover — coverage refused earlier
            raise PlannerError(f"non-additive metric {metric.name!r} has no ratio")
        expr = f"{metric.ratio.numerator} / {metric.ratio.denominator}"
        return MeasureExplanation(metric.name, expr, additivity, _RATIO_NOTE)
    agg = (metric.agg or "sum").upper()
    expr = f"{agg}({metric.expr.sql})" if metric.expr is not None else metric.name
    if metric.additivity is Additivity.SEMI_ADDITIVE and metric.semi_additive is not None:
        policy = metric.semi_additive
        over = _day_column(mart, policy.over.qualified)
        window = _WINDOWS.get(policy.rule, policy.rule.value.upper())
        note = f"semi-additive {policy.rule.value} over {over} — {window}-join then SUM"
        return MeasureExplanation(metric.name, expr, additivity, note)
    return MeasureExplanation(metric.name, expr, additivity, f"additive — {agg}")


def _scalar(value: JsonScalar) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f"'{value}'"
    return str(value)


def _human_filter(filter_expr: FilterExpr, resolved_name: str) -> str:
    """One filter as prose in bloomery names (RFC 0011 §5.6's
    ``ordered_month between 2026-01 and 2026-03`` shape)."""
    op = filter_expr.op
    values = filter_expr.values
    if op == "is_null":
        return f"{resolved_name} is null"
    if op == "between":
        return f"{resolved_name} between {_scalar(values[0])} and {_scalar(values[1])}"
    if op in ("in", "not_in"):
        keyword = "in" if op == "in" else "not in"
        return f"{resolved_name} {keyword} ({', '.join(_scalar(v) for v in values)})"
    if op == "contains":
        return f"{resolved_name} contains {_scalar(values[0])}"
    symbols = {"eq": "=", "ne": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
    return f"{resolved_name} {symbols[op]} {_scalar(values[0])}"


def build(
    result: MetricFlowExplainResult,
    coverage: Coverage,
    ir: ProjectIR,
    request: MetricRequest,
    *,
    naming: NamingPolicy,
    policy_applied: bool,
) -> Explanation:
    """The plan's :class:`Explanation`, from the typed ``query_spec`` and IR."""
    metrics_by_name = {metric.name: metric for metric in ir.metrics}
    measures = tuple(
        _measure_explanation(metrics_by_name[spec.element_name], coverage.mart)
        for spec in result.query_spec.input_spec_order.metric_specs
        if spec.element_name in metrics_by_name
    )
    namespace, relation = naming.relation(coverage.mart.name, Layer.GOLD)
    filters = tuple(
        _human_filter(filter_expr, resolved.name)
        for filter_expr, resolved in zip(request.filters, coverage.filter_dimensions, strict=True)
    )
    return Explanation(
        mart=f"{namespace}.{relation}",
        grain=coverage.mart.grain,
        measures=measures,
        filters=filters,
        policy_applied=policy_applied,
    )
