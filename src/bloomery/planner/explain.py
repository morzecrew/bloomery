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
  grain, not summed``;
- distinct count → ``distinct count — COUNT(DISTINCT) over the rows at the
  requested grain, never rolled up``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bloomery.errors import PlannerError, guaranteed
from bloomery.ir import COMPUTED, Additivity, Layer, SemiAdditiveRule
from bloomery.planner.names import ResolvedDimension
from bloomery.planner.request import Op, Predicate, clause_predicates
from bloomery.planner.result import BranchSource, Explanation, MeasureExplanation

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from metricflow.engine.metricflow_engine import MetricFlowExplainResult

    from bloomery.ir import MartIR, MetricInputIR, MetricIR, ProjectIR
    from bloomery.naming import NamingPolicy
    from bloomery.planner.coverage import Coverage
    from bloomery.planner.policy import RowPolicy
    from bloomery.planner.request import Clause, MetricRequest, Scalar

# ----------------------- #

__all__ = [
    "applied_predicates",
    "build",
]

_RATIO_NOTE = "non-additive ratio — recomputed at the requested grain, not summed"
_DISTINCT_NOTE = (
    "distinct count — COUNT(DISTINCT) over the rows at the requested grain, never rolled up"
)

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


def _offset_note(input_: MetricInputIR) -> str:
    """How far back one derived input reads, as prose (RFC 0034 D2)."""

    if input_.offset_window is not None:
        window = input_.offset_window
        plural = "" if window.count == 1 else "s"
        return f"{input_.alias} = {input_.metric} {window.count} {window.grain}{plural} earlier"

    if input_.offset_to_grain is not None:
        return f"{input_.alias} = {input_.metric} at the start of its {input_.offset_to_grain}"

    return f"{input_.alias} = {input_.metric}"


# ....................... #


def _derived_explanation(metric: MetricIR, additivity: str) -> MeasureExplanation:
    """A derived metric's provenance: the expression as written, and what each
    alias reads (RFC 0034 D1).

    The offsets are the part a reader cannot infer from the expression — the
    SQL that comes back joins the measure to the time spine twice and names
    neither hop — so the note spells them rather than saying "derived".
    """

    derived = guaranteed(
        (metric.derived for _ in (0,) if metric.derived is not None),
        expected=f"a derived block on metric {metric.name!r}",
        by="this function's only caller, which tests for one before calling it",
    )
    inputs = ", ".join(_offset_note(input_) for input_ in derived.inputs)
    note = f"derived — recomputed at the requested grain from {inputs}"

    return MeasureExplanation(metric.name, derived.expr.sql, additivity, note)


# ....................... #


def _cumulative_note(metric: MetricIR, agg: str) -> str | None:
    """The accumulation, when there is one (RFC 0034 D5). ``None`` says the
    metric aggregates within each period like any other."""

    if metric.cumulative is None:
        return None

    if metric.cumulative.window is not None:
        window = metric.cumulative.window
        plural = "" if window.count == 1 else "s"
        span = f"a trailing {window.count} {window.grain}{plural}"
    else:
        span = f"the start of each {metric.cumulative.grain_to_date}"

    return f"cumulative — {agg} accumulated over {span}, not per period"


# ....................... #


def _filter_note(metric: MetricIR) -> str:
    """The rows a metric is restricted to, when it is (RFC 0034 D8).

    Always said, never implied: a filtered metric that explains itself as its
    unfiltered sibling is a number the reader has no way to question.
    """

    if not metric.filter:
        return ""

    clauses = "; ".join(
        f"{clause.dimension} {clause.op} {list(clause.values)}" for clause in metric.filter
    )
    return f" (restricted to {clauses})"


# ....................... #


def _measure_explanation(metric: MetricIR, mart: MartIR | None) -> MeasureExplanation:
    """How one measure was computed.

    ``mart`` is optional because a metric the composed statement computes above
    the join belongs to no branch (RFC 0041 D3). It is read on the
    semi-additive path alone, which the composed path never reaches — §8 holds
    that class back — and a semi-additive metric arriving without one is a
    planner defect rather than a request the caller can fix.
    """

    additivity = metric.additivity.value

    if metric.derived is not None:
        return _derived_explanation(metric, additivity)

    if metric.additivity in COMPUTED:
        if metric.ratio is None:  # pragma: no cover — coverage refused earlier
            raise PlannerError(f"{additivity} metric {metric.name!r} has no ratio")
        expr = f"{metric.ratio.numerator} / {metric.ratio.denominator}"
        return MeasureExplanation(metric.name, expr, additivity, _RATIO_NOTE)

    agg = (metric.agg or "sum").upper()
    if metric.expr is None:
        expr = metric.name
    elif metric.agg == "count_distinct":
        # The SQL spelling, not the keyword's: the note beside it says
        # COUNT(DISTINCT), and the two are read together.
        expr = f"COUNT(DISTINCT {metric.expr.sql})"
    else:
        expr = f"{agg}({metric.expr.sql})"
    restriction = _filter_note(metric)

    if cumulative := _cumulative_note(metric, agg):
        return MeasureExplanation(metric.name, expr, additivity, cumulative + restriction)

    if metric.additivity is Additivity.SEMI_ADDITIVE and metric.semi_additive is not None:
        policy = metric.semi_additive
        if mart is None:  # pragma: no cover — §8 keeps the class off the composed path
            msg = (
                f"semi-additive metric {metric.name!r} has no mart to explain over — "
                "RFC 0041 §8 holds the class back from branch planning"
            )
            raise PlannerError(msg)
        over = _day_column(mart, policy.over.qualified)
        window = _WINDOWS.get(policy.rule, policy.rule.value.upper())
        note = f"semi-additive {policy.rule.value} over {over} — {window}-join then SUM"
        return MeasureExplanation(metric.name, expr, additivity, note + restriction)

    if metric.additivity is Additivity.DISTINCT_COUNT:
        return MeasureExplanation(metric.name, expr, additivity, _DISTINCT_NOTE + restriction)

    return MeasureExplanation(metric.name, expr, additivity, f"additive — {agg}{restriction}")


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


def composed_clauses(request: MetricRequest) -> tuple[str, ...]:
    """The request's filters as prose, under the names the caller used.

    A branch renders a clause under its own mart's spelling of the dimension —
    `tier` on one mart, `customer_tier` on another — and the composed answer
    applied one filter rather than one per branch. The requested name is the
    spelling every branch agreed to (RFC 0041 D12), so it is the one the
    explanation says.
    """

    return tuple(
        _human_clause(
            clause,
            tuple(
                ResolvedDimension(name=predicate.dimension)
                for predicate in clause_predicates(clause)
            ),
        )
        for clause in request.filters
    )


# ....................... #


def composed_measure(metric: MetricIR) -> MeasureExplanation:
    """How a metric computed above the join was computed (RFC 0041 D3).

    It is not any branch's measure, so no branch's explanation carries it —
    and both shapes reaching here, a ratio and an RFC 0034 ``derived:``
    metric, explain from their own decomposition rather than from a mart.
    """

    return _measure_explanation(metric, None)


# ....................... #


def applied_predicates(
    explanation: Explanation,
    request: MetricRequest,
    coverage: Coverage,
    metrics_by_name: dict[str, MetricIR],
    *,
    policy: RowPolicy | None,
) -> tuple[str, ...]:
    """Every predicate the emitted query restricts rows by, as prose, in the
    order the query applies them.

    The :class:`Explanation` scatters these on purpose — the request's filters
    read as a list, a metric's own restriction rides that measure's note, and
    the policy is a boolean, because a rendered policy value in a provenance
    block shown to the requester would disclose the scoping it enforces
    (RFC 0013 D9). A :class:`~bloomery.semantic.SemanticPlan` has the opposite
    obligation: it is lowered, not shown, and a plan naming only the request's
    filters is one a target lowers into a broader answer than the SQL beside
    it (logs/T-0021.md, D-125).
    """

    policy_predicate: tuple[str, ...] = ()
    if policy is not None:
        resolved = guaranteed(
            (dimension for dimension in (coverage.policy_dimension,) if dimension is not None),
            expected="the policy's dimension resolved against the covering mart",
            by="`coverage.resolve_request`, which resolves it or refuses the request",
        )
        policy_predicate = (_human_clause(policy.as_clause(), (resolved,)),)

    restrictions = tuple(
        dict.fromkeys(
            predicate
            for name in request.metrics
            for predicate in metric_restrictions(name, metrics_by_name)
        )
    )

    return (*policy_predicate, *explanation.filters, *restrictions)


# ....................... #


def metric_restrictions(name: str, metrics_by_name: Mapping[str, MetricIR]) -> tuple[str, ...]:
    """One metric's own ``filter:`` as prose, in authored order.

    Named separately because a metric's restriction narrows *that measure*, and
    :func:`applied_predicates` flattens every metric's into one list — correct
    for the query, which applies them all, and lossy for a plan, which has to
    say which measure each one narrows (RFC 0066 §5.5).
    """

    metric = metrics_by_name.get(name)

    if metric is None:
        return ()

    return tuple(
        _human_predicate(
            Predicate(dimension=clause.dimension, op=Op(clause.op), values=tuple(clause.values)),
            clause.dimension,
        )
        for clause in metric.filter
    )


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


# ....................... #


def merge(
    parts: Sequence[Explanation],
    *,
    order: Sequence[str],
    computed: Sequence[MeasureExplanation] = (),
    filters: tuple[str, ...] = (),
    policy_applied: bool = False,
) -> Explanation:
    """One explanation for a composed plan, from its branches' (RFC 0041 D15).

    ``measures`` come back in **request** order rather than branch order: the
    branches were sorted by mart name so the SQL is deterministic, and a
    reader of a provenance block is owed the order they asked in.

    ``mart`` and ``grain`` keep the first branch's, and ``branches`` carries
    every one — so the two long-standing fields report something true of part
    of the answer instead of a name invented for the join, and `render()`
    names all of them.

    ``computed`` carries the metrics no branch produced because the composed
    statement computes them above the join (RFC 0041 D3) — they answer to a
    requested name that appears in no part's measures. ``filters`` arrives
    already rendered under the requested spellings rather than any branch's
    (:func:`composed_clauses`), because one filter reached every branch and
    the explanation reports the request's account of it, not three.
    """

    by_name = {measure.name: measure for part in parts for measure in part.measures}
    by_name.update({measure.name: measure for measure in computed})

    return Explanation(
        mart=parts[0].mart,
        grain=parts[0].grain,
        measures=tuple(by_name[name] for name in order if name in by_name),
        filters=filters,
        policy_applied=policy_applied,
        branches=tuple(BranchSource(mart=part.mart, grain=part.grain) for part in parts),
    )
