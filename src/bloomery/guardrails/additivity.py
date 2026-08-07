"""The additivity guard (RFC 0006 §5.4, D6, D11).

Checked over ``MetricIR.additivity`` on the draft IR:

- A ``non_additive`` metric declared without a ``ratio`` (or an equivalent
  additive decomposition — an expression over additive dependencies) is
  :class:`~bloomery.errors.NonAdditiveWithoutComponents`: with nothing
  additive to recompute from at query time, the metric could only ever be
  answered by storing it, which the next rule forbids.
- A ``non_additive`` metric may **never** materialize as a stored number. At
  M4 the only place that could arise is an entity column sharing the metric's
  name — a stored :class:`~bloomery.errors.AdditivityViolation`; emitters
  re-refuse independently (RFC 0008), defense in depth.
- A ``semi_additive`` metric aggregates only over dimensions *other than* its
  ``over:`` dimension: a missing ``semi_additive: {over, rule}`` policy makes
  the invariant unenforceable, and an expression that explicitly aggregates
  the ``over`` dimension away violates it directly — both
  :class:`~bloomery.errors.AdditivityViolation`. The query-time lowering of
  ``rule`` is RFC 0011's, not this stage's (D11).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlglot import exp

from bloomery.errors import AdditivityViolation, GuardrailError, NonAdditiveWithoutComponents
from bloomery.ir import Additivity

if TYPE_CHECKING:
    from bloomery.ir import MetricIR, ProjectIR, SqlExpr

__all__ = [
    "check_additivity",
]


def _has_decomposition(metric: MetricIR) -> bool:
    """An expression over declared dependencies is an additive decomposition
    the planner can recompute from (RFC 0011 D5)."""
    return metric.expr is not None and metric.depends_on != ()


def _aggregates_over(expr: SqlExpr, dimension: str) -> bool:
    return any(
        col.name == dimension
        for agg in expr.ast().find_all(exp.AggFunc)
        for col in agg.find_all(exp.Column)
    )


def _check_non_additive(metric: MetricIR, draft: ProjectIR, path: str) -> list[GuardrailError]:
    violations: list[GuardrailError] = []
    if metric.ratio is None and not _has_decomposition(metric):
        msg = (
            f"metric {metric.name!r} is non_additive but declares neither a ratio nor an "
            "additive decomposition — there is nothing additive to recompute it from at "
            "query time, so it could only ever be answered by storing it, which is "
            "forbidden (RFC 0006 §5.4). Fix: add ratio: {numerator, denominator} naming "
            "its additive components (or an expr over additive dependencies)"
        )
        violations.append(NonAdditiveWithoutComponents(msg, source_path=path))
    stored = sorted(
        entity.name
        for entity in draft.entities
        for column in entity.columns
        if column.name == metric.name
    )
    if stored:
        msg = (
            f"metric {metric.name!r} is non_additive and may not be materialized as a "
            f"stored number, but entity {stored[0]!r} stores a column of that name — a "
            "stored average re-aggregates wrongly (RFC 0006 D6). Fix: store the additive "
            "components and rename either the column or the metric; the ratio is a "
            "calculated measure at query time"
        )
        violations.append(AdditivityViolation(msg, source_path=path))
    return violations


def _check_semi_additive(metric: MetricIR, path: str) -> list[GuardrailError]:
    if metric.semi_additive is None:
        msg = (
            f"metric {metric.name!r} is semi_additive but declares no semi_additive: "
            "{over, rule} policy — without the over: dimension the only-aggregate-over-"
            "other-dimensions invariant is unenforceable (RFC 0006 D11). Fix: add "
            "semi_additive: {over: <date dimension>, rule: last|first|avg|min|max}"
        )
        return [AdditivityViolation(msg, source_path=path)]
    over = metric.semi_additive.over.dimension
    if metric.expr is not None and _aggregates_over(metric.expr, over):
        msg = (
            f"metric {metric.name!r} is semi_additive over {over!r} but its expr "
            f"aggregates {over!r} away — a semi_additive metric may only be aggregated "
            "over dimensions other than its over: dimension (RFC 0006 D6). Fix: remove "
            f"the aggregation of {over!r}; the over-dimension rule "
            f"({metric.semi_additive.rule}) is applied at query time"
        )
        return [AdditivityViolation(msg, source_path=path)]
    return []


def check_additivity(draft: ProjectIR) -> list[GuardrailError]:
    """Every additivity violation across the draft's metrics."""
    violations: list[GuardrailError] = []
    for metric in draft.metrics:
        path = f"metrics: metrics.{metric.name}"
        if metric.additivity is Additivity.NON_ADDITIVE:
            violations.extend(_check_non_additive(metric, draft, path))
        elif metric.additivity is Additivity.SEMI_ADDITIVE:
            violations.extend(_check_semi_additive(metric, path))
    return violations
