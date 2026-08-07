"""The query planner (RFC 0011; backend: RFC 0013): ``MetricRequest`` in,
``QueryPlan`` out — a pure request-time function that validates, refuses
what it cannot answer correctly (with a typed reason — never a plausible
wrong number), and renders SQL through an embedded, render-only MetricFlow.
It never joins, never executes, and callers never see MetricFlow types or
dunder names.

Package map (RFC 0013 §5.1): ``request``/``result`` carry the stable port
types the Query Agent binds to; ``coverage`` is the refusal precheck run
before any delegation; ``names`` bridges bloomery ↔ MetricFlow naming;
``filters`` renders where-constraints (values always typed and escaped);
``policy`` holds the row-level scoping value object; ``explain`` builds the
deterministic provenance record; ``metricflow_planner`` is the adapter
gluing them behind the ``Planner`` port.
"""

from bloomery.planner.metricflow_planner import MetricFlowPlanner, translate_mf_error
from bloomery.planner.policy import RowPolicy
from bloomery.planner.request import FilterExpr, MetricRequest, OrderSpec, TimeGrain
from bloomery.planner.result import (
    ColumnDescriptor,
    Explanation,
    MeasureExplanation,
    QueryPlan,
)

__all__ = [
    "ColumnDescriptor",
    "Explanation",
    "FilterExpr",
    "MeasureExplanation",
    "MetricFlowPlanner",
    "MetricRequest",
    "OrderSpec",
    "QueryPlan",
    "RowPolicy",
    "TimeGrain",
    "translate_mf_error",
]
