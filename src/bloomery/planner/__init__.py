"""The query planner (S-0028; backend: S-0030; vocabulary: S-0032):
``MetricRequest`` in, ``QueryPlan`` out — a pure request-time function that
validates, refuses what it cannot answer correctly (with a typed reason —
never a plausible wrong number), and renders SQL through an embedded,
render-only MetricFlow. It never joins, never executes, and callers never
see MetricFlow types or dunder names.

Package map (S-0030/what-is-superseded-and-the-boundary-that-makes-it-reversible): ``request``/``result`` carry the stable port
types the Query Agent binds to — filters are CNF clauses
(``Predicate``/``AnyOf``, S-0032/D-3); ``parse`` is the public JSON
front door (Mongo-flavoured grammar, normalized before refusing, closed
refusal list exported as ``KNOWN_UNSUPPORTED``); ``coverage`` is the
refusal precheck run before any delegation; ``names`` bridges bloomery ↔
MetricFlow naming; ``filters`` renders where-constraints (values always
typed and escaped, one entry per clause); ``policy`` holds the row-level
scoping value object; ``explain`` builds the deterministic provenance
record; ``metricflow_planner`` is the adapter gluing them behind the
``Planner`` port.
"""

from bloomery.planner.metricflow_planner import MetricFlowPlanner, translate_mf_error
from bloomery.planner.parse import (
    KNOWN_UNSUPPORTED,
    parse_filter_json,
    parse_page_json,
    parse_sort_json,
)
from bloomery.planner.policy import RowPolicy
from bloomery.planner.request import (
    AnyOf,
    Clause,
    MetricRequest,
    Op,
    OrderDirection,
    OrderSpec,
    Predicate,
    Scalar,
    TimeGrain,
)
from bloomery.planner.result import (
    BranchSource,
    ColumnDescriptor,
    ColumnRole,
    Explanation,
    MeasureExplanation,
    QueryPlan,
)

# ----------------------- #

__all__ = [
    "KNOWN_UNSUPPORTED",
    "AnyOf",
    "Clause",
    "BranchSource",
    "ColumnDescriptor",
    "ColumnRole",
    "Explanation",
    "MeasureExplanation",
    "MetricFlowPlanner",
    "MetricRequest",
    "Op",
    "OrderDirection",
    "OrderSpec",
    "Predicate",
    "QueryPlan",
    "RowPolicy",
    "Scalar",
    "TimeGrain",
    "parse_filter_json",
    "parse_page_json",
    "parse_sort_json",
    "translate_mf_error",
]
