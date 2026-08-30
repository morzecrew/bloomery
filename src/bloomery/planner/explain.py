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
from bloomery.planner.request import Op, clause_predicates
from bloomery.planner.result import Explanation, MeasureExplanation

if TYPE_CHECKING:
    from metricflow.engine.metricflow_engine import MetricFlowExplainResult

    from bloomery.ir import MartIR, MetricIR, ProjectIR
    from bloomery.naming import NamingPolicy
    from bloomery.planner.coverage import Coverage
    from bloomery.planner.names import ResolvedDimension
    from bloomery.planner.request import Clause, MetricRequest, Predicate, Scalar

# ----------------------- #

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


# ....................... #


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


# ....................... #


_SYMBOLS = {Op.EQ: "=", Op.NE: "!=", Op.GT: ">", Op.GTE: ">=", Op.LT: "<", Op.LTE: "<="}


def _scalar(value: Scalar) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"

    if isinstance(value, str):
        return f"'{value}'"

    return str(value)


# ....................... #


def _human_predicate(predicate: Predicate, resolved_name: str) -> str:
    """One predicate as prose in bloomery names (RFC 0011 §5.6 shape,
    vocabulary per RFC 0015 §5.1)."""
    op = predicate.op
    values = predicate.values

    if op is Op.IS_NULL:
        return f"{resolved_name} is null" if values[0] else f"{resolved_name} is not null"

    if op in (Op.IN, Op.NOT_IN):
        keyword = "in" if op is Op.IN else "not in"
        return f"{resolved_name} {keyword} ({', '.join(_scalar(v) for v in values)})"

    if op in (Op.LIKE, Op.ILIKE):
        # Multi-pattern like/ilike is an OR of repeated predicates (RFC 0015
        # §5.1) — the renderer emits exactly that, so the prose says it
        # rather than hiding the disjunction behind a value list.
        return " OR ".join(f"{resolved_name} {op.value} {_scalar(v)}" for v in values)

    return f"{resolved_name} {_SYMBOLS[op]} {_scalar(values[0])}"


# ....................... #


def _human_clause(clause: Clause, resolutions: tuple[ResolvedDimension, ...]) -> str:
    """One clause as prose — always built from the ``Clause`` objects, never
    by parsing rendered SQL (RFC 0015 D11); an ``AnyOf`` group joins its
    members with `` OR ``."""
    rendered = tuple(
        _human_predicate(predicate, resolved.name)
        for predicate, resolved in zip(clause_predicates(clause), resolutions, strict=True)
    )
    return " OR ".join(rendered)


# ....................... #


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
        _human_clause(clause, resolutions)
        for clause, resolutions in zip(request.filters, coverage.filter_dimensions, strict=True)
    )
    return Explanation(
        mart=f"{namespace}.{relation}",
        grain=coverage.mart.grain,
        measures=measures,
        filters=filters,
        policy_applied=policy_applied,
    )
