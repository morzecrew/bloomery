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
    guaranteed,
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
        *,
        request: MetricRequest,
        policy: RowPolicy | None,
    ) -> tuple[str, tuple[ColumnDescriptor, ...], MetricFlowExplainResult]:
        """One branch, rendered by MetricFlow as the single-mart request it is.

        The request's filters and the row policy **do** reach it, resolved
        against this branch's own mart: a restriction that could not reach
        every branch had the whole request refused before this ran
        (logs/T-0027.md, D-176), so a branch here is one that can evaluate all
        of them. They go through the same :mod:`~bloomery.planner.filters`
        pipeline the single-mart path uses — one renderer, one set of
        injection rules, policy prepended.

        ``order_by`` and ``limit`` do not. Both belong to the composed
        statement, because a branch sorted before the join has its order undone
        by it and a branch truncated before the join answers from a prefix
        (D-182).

        The metrics asked for are the branch's **components**, which for a
        computed metric are not the names the caller requested (D3).
        """

        entity = names.entity_key(resolved.mart)
        mf_request = MetricFlowQueryRequest.create(
            metric_names=names.to_mf_metrics(resolved.metrics),
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

    def _measures(
        self,
        ir: ProjectIR,
        request: MetricRequest,
        branches: tuple[coverage.Coverage, ...],
    ) -> tuple[compose.Measure, ...]:
        """Every requested metric as the composed statement produces it.

        The projection comes from :func:`coverage.composed_projection` rather
        than being read off the request a second time — the precheck accepted
        the request on exactly those projections, and a planner deriving its
        own would be RFC 0041 D11's divergence one level up. What is added
        here is the only thing coverage does not know: which branch index each
        component landed on.
        """

        owner = {
            component: index
            for index, resolved in enumerate(branches)
            for component in resolved.metrics
        }

        return tuple(
            compose.Measure(
                name=projection.name,
                inputs=tuple(
                    (alias, owner[component], component) for alias, component in projection.inputs
                )
                or ((projection.name, owner[projection.name], projection.name),),
                expr=projection.expr.ast() if projection.expr is not None else None,
            )
            for projection in coverage.composed_projection(ir, request)
        )

    # ....................... #

    def _composed(
        self,
        ir: ProjectIR,
        request: MetricRequest,
        branches: tuple[coverage.Coverage, ...],
        *,
        dialect: str,
        policy: RowPolicy | None,
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

        def branch_request(resolved: coverage.Coverage) -> MetricRequest:
            """The request as *this branch* answers it.

            Its own components rather than the caller's metrics, and neither
            `order_by` nor `limit`: both are the composed statement's
            (D-182), and `order_by` naming a metric no branch was asked for
            would not even construct — `MetricRequest` refuses an order field
            that is not a requested metric or dimension (RFC 0011 D4). The
            filters stay, because the branch is where they are applied.
            """

            return dataclasses.replace(request, metrics=resolved.metrics, order_by=(), limit=None)

        rendered = [
            self._branch(engine, resolved, metrics_by_name, request=request, policy=policy)
            for resolved in branches
        ]
        width = len(request.dimensions)
        keys = coverage.composed_keys(request, branches)
        measures = self._measures(ir, request, branches)
        limit, warnings = self._effective_limit(request)
        # A date-role dimension is answered under its re-bucketed name, so an
        # `order_by` naming the requested spelling has to be translated to the
        # one the composed statement projects (`ordered_day` → `ordered_month`).
        #
        # An identity map today, and kept rather than dropped. A date role may
        # only name a column of its mart's **base** entity, so two marts at
        # different grains cannot expose one date column as a role, and D12
        # refuses two roles of different origin — no composed request re-buckets
        # anything (logs/T-0027.md, finding 3). What is unreachable is the
        # grammar's doing rather than this planner's, and the day a mart may
        # carry a flattened role, the translation has to already be here: its
        # absence answers, it does not fail.
        effective = dict(zip(request.dimensions, keys, strict=True))
        ordering = tuple(
            (effective.get(spec.field, spec.field), spec.direction) for spec in request.order_by
        )
        projected = {*keys, *(measure.name for measure in measures)}

        # The composed statement can only order by what it projects, and the
        # field reaches `_ordering` as SQL text. `MetricRequest` already refuses
        # an order field that is not a requested metric or dimension (RFC 0011
        # D4), so this cannot fire — it is the second net `names.to_mf_order`
        # holds under the single-mart path, kept because this path builds the
        # clause itself instead of handing a name to MetricFlow.
        if unknown := sorted(field for field, _direction in ordering if field not in projected):
            raise PlannerError(  # pragma: no cover — MetricRequest refuses this first
                f"order_by names {unknown}, which the composed statement does not project "
                "— a cross-grain answer can only be ordered by its own columns (RFC 0011 D4)"
            )

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
            order_by=ordering,
            limit=limit,
            dialect=get_dialect(dialect),
        )
        # The key columns keep the type and role the branch resolved them to
        # and take the composed statement's own alias, since that is what the
        # SQL projects (logs/T-0026.md, D-165). A stored measure is already
        # what its branch called it; a computed one belongs to no branch and
        # is described here (D3).
        columns = tuple(
            dataclasses.replace(column, name=name, sql_alias=name)
            for column, name in zip(rendered[0][1][:width], keys, strict=True)
        ) + tuple(
            names.composed_column(metrics_by_name[measure.name])
            if measure.expr is not None
            else guaranteed(
                (
                    descriptor
                    for descriptor in rendered[measure.inputs[0][1]][1][width:]
                    if descriptor.name == measure.name
                ),
                expected=f"a column descriptor for measure {measure.name!r}",
                by="the branch that was asked for it, which returns one per metric",
            )
            for measure in measures
        )
        # Kept per branch as well as merged. The merged explanation speaks the
        # *requested* spelling of a dimension, which is right for a reader and
        # wrong for a branch's plan: `SemanticPlan` is lowered rather than
        # shown, so a branch whose `Filter` said `region` while its scan
        # restricts `order_region` would lower into a predicate on a column
        # that relation does not have — and the `Aggregate` beside it already
        # names the branch-local column, so the plan contradicted itself
        # (logs/T-0027.md, finding 7).
        per_branch = [
            explain.build(
                result,
                resolved,
                ir,
                branch_request(resolved),
                naming=self._naming,
                policy_applied=policy is not None,
            )
            for resolved, (_sql, _columns, result) in zip(branches, rendered, strict=True)
        ]
        explanation = explain.merge(
            per_branch,
            order=request.metrics,
            computed=tuple(
                explain.composed_measure(metrics_by_name[measure.name])
                for measure in measures
                if measure.expr is not None
            ),
            filters=explain.composed_clauses(request),
            policy_applied=policy is not None,
        )
        warnings += self._composed_warnings(request, branches)

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
                    (
                        semantic_plan.build(
                            resolved,
                            branch_request(resolved),
                            metrics_by_name,
                            filters=explain.applied_predicates(
                                branch,
                                branch_request(resolved),
                                resolved,
                                metrics_by_name,
                                policy=policy,
                            ),
                        ),
                        tuple(dimension.name for dimension in resolved.dimensions),
                    )
                    for resolved, branch in zip(branches, per_branch, strict=True)
                ],
                keys,
                request.metrics,
                # A metric computed above the join is stated by a `Compute`
                # node (RFC 0066 §5.2). It used to withhold the plan: the
                # vocabulary had no arithmetic, so the alternative was a plan
                # claiming the join produced a column it does not
                # (logs/T-0027.md, D-178).
                computed=tuple(
                    (measure.name, semantic_plan.expression(metrics_by_name[measure.name]))
                    for measure in measures
                    if measure.expr is not None
                ),
                computed_inputs=tuple(
                    dict.fromkeys(
                        column
                        for measure in measures
                        if measure.expr is not None
                        for _alias, _branch, column in measure.inputs
                    )
                ),
            ),
        )

    # ....................... #

    def _composed_warnings(
        self, request: MetricRequest, branches: tuple[coverage.Coverage, ...]
    ) -> tuple[str, ...]:
        """What a composed plan has to say about what it did not do.

        Only the `time_grain` case is left. P1 also dropped the planner's
        default limit and said so, because a limit pushed into a branch
        truncates it before the join; P2 puts the limit on the composed
        statement instead, where it means what the caller asked for
        (logs/T-0027.md, D-182).
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
            return self._composed(ir, request, branches, dialect=dialect, policy=policy)

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
