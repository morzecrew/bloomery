"""The MetricFlow planner adapter (RFC 0013 §5.3, R2): the shipped backend
behind RFC 0011's ``Planner`` port. ``plan()`` validates, runs the coverage
precheck (refusal before delegation — RFC 0013 D6), hydrates the manifest
lookup through the injected :class:`~bloomery.runtime.LruManifestHydrator`,
drives ``MetricFlowEngine.explain()`` — which renders SQL and **never
executes** (the render-only client raises on every execution member) — and
translates the result back into a :class:`~bloomery.planner.result.QueryPlan`
in bloomery names.

MetricFlow types never cross the port boundary (RFC 0013 D2): its
exceptions are translated into the RFC 0011 taxonomy at :func:`translate_mf_error`
(an unrecognized one becomes a plain ``PlannerError`` preserving the
message), and its spec objects are consumed inside
:mod:`bloomery.planner.names` / :mod:`bloomery.planner.explain` only.

``limit`` is clamped to ``max_limit`` (default 50 000, RFC 0011 D4);
clamping appends a ``QueryPlan.warnings`` entry, as does a ``time_grain``
with no date-role dimension to apply to.
"""

from __future__ import annotations

import dataclasses
import hashlib
from typing import TYPE_CHECKING

from metricflow.engine.metricflow_engine import (
    MetricFlowEngine,
    MetricFlowQueryRequest,
    OutputColumnOrderMode,
)
from metricflow_semantics.errors.error_classes import (
    InvalidQueryException,
    InvalidQuerySyntax,
    MetricFlowException,
    MetricNotFoundError,
    UnknownMetricError,
)

import bloomery.planner.compose as compose
import bloomery.planner.coverage as coverage
import bloomery.planner.explain as explain
import bloomery.planner.filters as filters
import bloomery.planner.names as names
from bloomery.dialects import get_dialect
from bloomery.errors import (
    AmbiguousDimension,
    InvalidRequest,
    PlannerError,
    UnknownMember,
    UnreachableAtGrain,
)
from bloomery.naming import DefaultNaming
from bloomery.planner import semantic_plan
from bloomery.planner.result import ColumnDescriptor, QueryPlan
from bloomery.runtime import sql_client_for_dialect

if TYPE_CHECKING:
    from metricflow.engine.metricflow_engine import MetricFlowExplainResult

    from bloomery.ir import MetricIR, ProjectIR
    from bloomery.naming import NamingPolicy
    from bloomery.planner.policy import RowPolicy
    from bloomery.planner.request import MetricRequest
    from bloomery.runtime import LruManifestHydrator

# ----------------------- #

__all__ = [
    "MetricFlowPlanner",
    "translate_mf_error",
]

#: Message fragments classifying ``InvalidQueryException`` — MetricFlow
#: raises one class for many causes; the coverage precheck catches nearly
#: all of them first, so this table is the belt-and-braces second net.
_UNKNOWN_FRAGMENTS = ("does not match", "unknown", "not found", "no matching items")


def translate_mf_error(error: MetricFlowException) -> PlannerError:
    """One MetricFlow exception as its bloomery-taxonomy equivalent
    (RFC 0013 D2): callers never catch a MetricFlow class. Unrecognized
    errors become a plain :class:`PlannerError` preserving the message."""
    message = str(error)

    if isinstance(error, InvalidQuerySyntax):
        return InvalidRequest(f"MetricFlow rejected the request syntax: {message}")

    if isinstance(error, (UnknownMetricError, MetricNotFoundError)):
        return UnknownMember(message)

    if isinstance(error, InvalidQueryException):
        lowered = message.lower()
        if "ambiguous" in lowered:
            return AmbiguousDimension(message)
        if any(fragment in lowered for fragment in _UNKNOWN_FRAGMENTS):
            return UnknownMember(message)
        if "join" in lowered or "common semantic model" in lowered:
            return UnreachableAtGrain(message)
        return InvalidRequest(message)

    return PlannerError(f"MetricFlow failed to plan the request: {message}")


# ....................... #


class MetricFlowPlanner:
    """RFC 0011's ``Planner`` port, backed by an embedded MetricFlow.

    ``naming`` must be the policy the hydrated manifests were emitted with
    (it shapes the gold relations named in refusal messages and
    explanations); it defaults to :class:`~bloomery.naming.DefaultNaming`,
    matching :class:`~bloomery.runtime.LruManifestHydrator`'s build path.

    **Safe to share across threads.** Every attribute below is set here and
    only read afterwards; :meth:`plan` takes the IR, the request and the
    dialect as arguments and holds no state between calls, so one planner
    serving a whole service is the intended shape rather than a tolerated
    one. The obligations that remain are the hydrator's — see
    :class:`~bloomery.runtime.LruManifestHydrator`.
    """

    def __init__(
        self,
        hydrator: LruManifestHydrator,
        max_limit: int = 50_000,
        default_limit: int | None = None,
        *,
        naming: NamingPolicy | None = None,
    ) -> None:
        self._hydrator = hydrator
        self._max_limit = max_limit
        self._default_limit = default_limit
        self._naming = naming if naming is not None else DefaultNaming()

    # ....................... #

    def _effective_limit(self, request: MetricRequest) -> tuple[int | None, tuple[str, ...]]:
        limit = request.limit if request.limit is not None else self._default_limit

        if limit is not None and limit > self._max_limit:
            warning = (
                f"limit {limit} exceeds the planner's max_limit {self._max_limit}; "
                f"clamped to {self._max_limit}"
            )
            return self._max_limit, (warning,)

        return limit, ()

    # ....................... #

    def _branch(
        self,
        engine: MetricFlowEngine,
        resolved: coverage.Coverage,
        metrics_by_name: dict[str, MetricIR],
    ) -> tuple[str, tuple[ColumnDescriptor, ...], MetricFlowExplainResult]:
        """One branch, rendered by MetricFlow as the single-mart request it is.

        No filters, no order and no limit reach it: RFC 0041 P1 declines the
        composed path when the request carries any of them, because each would
        have to be applied *after* the join and applying it per branch answers
        from a narrowed or truncated branch instead (logs/T-0026.md, D-168).
        """

        entity = names.entity_key(resolved.mart)
        mf_request = MetricFlowQueryRequest.create(
            metric_names=names.to_mf_metrics(resolved.metrics),
            group_by_names=names.to_mf_group_by(resolved.dimensions, entity=entity),
            output_column_order_mode=OutputColumnOrderMode.INPUT_ORDER,
        )

        try:
            result = engine.explain(mf_request)
        except MetricFlowException as error:
            raise translate_mf_error(error) from error

        return (
            result.sql_statement.sql,
            names.columns_from(
                result.query_spec, mart=resolved.mart, metrics_by_name=metrics_by_name
            ),
            result,
        )

    # ....................... #

    def _composed(
        self,
        ir: ProjectIR,
        request: MetricRequest,
        branches: tuple[coverage.Coverage, ...],
        *,
        dialect: str,
    ) -> QueryPlan:
        """A cross-mart request, answered by joining branch aggregates
        (RFC 0041 D9).

        Every branch is a request this planner already answered; what is new
        is the statement around them, which is bloomery's own SQL and carries
        bloomery's null semantics (D13). The branches arrive sorted by mart
        name so two runs compose the same query; the result's **columns** stay
        in request order, because that is part of the answer.
        """

        metrics_by_name = {metric.name: metric for metric in ir.metrics}
        lookup = self._hydrator.get(ir)
        engine = MetricFlowEngine(
            semantic_manifest_lookup=lookup, sql_client=sql_client_for_dialect(dialect)
        )
        rendered = [self._branch(engine, resolved, metrics_by_name) for resolved in branches]
        width = len(request.dimensions)
        keys = _composed_keys(request, branches, [columns for _sql, columns, _r in rendered])
        owner = {
            metric: index for index, resolved in enumerate(branches) for metric in resolved.metrics
        }
        measures = tuple((owner[metric], metric) for metric in request.metrics)
        sql = compose.compose(
            [
                compose.Branch(
                    sql=branch_sql,
                    keys=tuple(column.sql_alias for column in columns[:width]),
                )
                for branch_sql, columns, _result in rendered
            ],
            keys=keys,
            measures=measures,
            dialect=get_dialect(dialect),
        )
        # The key columns keep the type and role the branch resolved them to
        # and take the composed statement's own alias, since that is what the
        # SQL projects (logs/T-0026.md, D-165). The measures are already what
        # their branch called them.
        columns = tuple(
            dataclasses.replace(column, name=name, sql_alias=name)
            for column, name in zip(rendered[0][1][:width], keys, strict=True)
        ) + tuple(
            descriptor
            for index, metric in measures
            for descriptor in rendered[index][1][width:]
            if descriptor.name == metric
        )
        explanation = explain.merge(
            [
                explain.build(
                    result,
                    resolved,
                    ir,
                    dataclasses.replace(request, metrics=resolved.metrics),
                    naming=self._naming,
                    policy_applied=False,
                )
                for resolved, (_sql, _columns, result) in zip(branches, rendered, strict=True)
            ],
            order=request.metrics,
        )
        warnings = self._composed_warnings(request, branches)

        return QueryPlan(
            sql=sql,
            columns=columns,
            mart=branches[0].mart.name,
            marts=tuple(resolved.mart.name for resolved in branches),
            warnings=warnings,
            explanation=explanation,
            fingerprint=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
            semantic=semantic_plan.compose(
                [
                    semantic_plan.build(
                        resolved,
                        dataclasses.replace(request, metrics=resolved.metrics),
                        metrics_by_name,
                        filters=(),
                    )
                    for resolved in branches
                ],
                keys,
                request.metrics,
            ),
        )

    # ....................... #

    def _composed_warnings(
        self, request: MetricRequest, branches: tuple[coverage.Coverage, ...]
    ) -> tuple[str, ...]:
        """What a composed plan has to say about what it did not do.

        The default limit is the one that matters. It is a guard against an
        unbounded result, and a composed statement cannot inherit it: a limit
        pushed into a branch truncates that branch *before* the join, which
        answers from a prefix and reports no warning at all. So it is dropped
        and said out loud, rather than applied where it would be wrong. A
        limit the caller asked for explicitly never reaches here — the
        precheck refuses that request (RFC 0041 §13a).
        """

        warnings: tuple[str, ...] = ()

        if request.time_grain is not None and not any(
            dimension.role is not None for resolved in branches for dimension in resolved.dimensions
        ):
            warnings += (
                (
                    f"time_grain {request.time_grain.value!r} has no date-role dimension "
                    "in the request to apply to; ignored"
                ),
            )

        if self._default_limit is not None:
            warnings += (
                (
                    f"the planner's default limit {self._default_limit} is not applied to a "
                    "cross-mart request: a limit inside a branch truncates it before the "
                    "join, so the answer is unbounded"
                ),
            )

        return warnings

    # ....................... #

    def plan(
        self,
        ir: ProjectIR,
        request: MetricRequest,
        *,
        dialect: str,
        policy: RowPolicy | None = None,
    ) -> QueryPlan:
        """Pure request-time planning: SQL text plus metadata out, nothing
        executed (RFC 0011 D1). Refusals raise the RFC 0011 taxonomy —
        ``UnknownMember`` / ``UnreachableAtGrain`` / ``AmbiguousDimension`` /
        ``InvalidRequest`` / ``FilterTypeMismatch`` — before delegation
        wherever the coverage precheck can see the problem.

        A request whose measures live on several marts is answered by
        :meth:`_composed` when RFC 0041 P1's conditions hold, and refused by
        the precheck exactly as before when they do not — the branch is taken
        on the precheck's answer rather than on a second reading of the
        request here."""
        branches = coverage.resolve_branches(ir, request, naming=self._naming, policy=policy)

        if len(branches) > 1:
            return self._composed(ir, request, branches, dialect=dialect)

        resolved = branches[0]
        entity = names.entity_key(resolved.mart)
        warnings: tuple[str, ...] = ()

        if request.time_grain is not None and not any(
            dimension.role is not None for dimension in resolved.dimensions
        ):
            warnings += (
                (
                    f"time_grain {request.time_grain.value!r} has no date-role dimension "
                    "in the request to apply to; ignored"
                ),
            )

        limit, limit_warnings = self._effective_limit(request)
        warnings += limit_warnings
        dimensions_by_request = dict(zip(request.dimensions, resolved.dimensions, strict=True))
        mf_request = MetricFlowQueryRequest.create(
            metric_names=names.to_mf_metrics(request.metrics),
            group_by_names=names.to_mf_group_by(resolved.dimensions, entity=entity),
            where_constraints=list(
                filters.to_where(
                    request.filters,
                    resolved.filter_dimensions,
                    mart=resolved.mart,
                    entity=entity,
                    policy=policy,
                    policy_dimension=resolved.policy_dimension,
                )
            )
            or None,
            order_by_names=names.to_mf_order(
                request.order_by,
                entity=entity,
                metrics=request.metrics,
                dimensions=dimensions_by_request,
            )
            or None,
            limit=limit,
            # metricflow 0.212 replaced the boolean
            # `order_output_columns_by_input_order=True` with this enum. The
            # successor value is `INPUT_ORDER`; the parameter's own default is
            # `LEGACY_TYPE_GROUPED`, which orders columns within each spec group
            # "in an arbitrary order that depends on how MF generates the SQL"
            # — so dropping the argument rather than porting it would trade a
            # deterministic column order for an engine-internal one, and RFC 0003
            # forbids that (`sql` is fingerprinted, and `columns` is a contract).
            output_column_order_mode=OutputColumnOrderMode.INPUT_ORDER,
        )
        lookup = self._hydrator.get(ir)
        engine = MetricFlowEngine(
            semantic_manifest_lookup=lookup,
            sql_client=sql_client_for_dialect(dialect),
        )

        try:
            result = engine.explain(mf_request)
        except MetricFlowException as error:
            raise translate_mf_error(error) from error

        sql = result.sql_statement.sql
        metrics_by_name = {metric.name: metric for metric in ir.metrics}
        explanation = explain.build(
            result,
            resolved,
            ir,
            request,
            naming=self._naming,
            policy_applied=policy is not None,
        )
        return QueryPlan(
            sql=sql,
            columns=names.columns_from(
                result.query_spec, mart=resolved.mart, metrics_by_name=metrics_by_name
            ),
            mart=resolved.mart.name,
            warnings=warnings,
            explanation=explanation,
            fingerprint=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
            # Built from the same `Coverage` and the same renderers the
            # explanation reads, so the two are one account of the request
            # rather than two (RFC 0039 §7) — over every predicate the query
            # applies, not only the ones the explanation lists as `filters`.
            semantic=semantic_plan.build(
                resolved,
                request,
                metrics_by_name,
                filters=explain.applied_predicates(
                    explanation, request, resolved, metrics_by_name, policy=policy
                ),
            ),
        )


# ....................... #


def _composed_keys(
    request: MetricRequest,
    branches: tuple[coverage.Coverage, ...],
    columns: list[tuple[ColumnDescriptor, ...]],
) -> tuple[str, ...]:
    """What the composed statement calls each joined key.

    One dimension has one name per mart that reaches it — `tier` on the mart
    based at `customer`, `customer_tier` one hop away, `order_customer_tier`
    two — and the composed projection has to choose one
    (logs/T-0026.md, D-165). It takes **the name the caller asked for**: every
    branch's column is the same dimension by D12, so no branch's spelling is
    more the answer than another's, and the request's own name is the one
    spelling the caller can predict.

    The exception is a date-role dimension, which is answered under its
    *effective* name — `ordered_month` for `ordered_day` under a monthly
    ``time_grain``, exactly as a single-mart plan answers it. Every branch
    agrees on that name when the composed path opens at all, since two marts
    reaching one date column through different roles have different
    provenance and D12 refuses them (logs/T-0026.md, D-169).
    """

    return tuple(
        columns[0][position].name if branches[0].dimensions[position].role is not None else name
        for position, name in enumerate(request.dimensions)
    )
