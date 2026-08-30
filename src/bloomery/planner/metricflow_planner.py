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

import bloomery.planner.coverage as coverage
import bloomery.planner.explain as explain
import bloomery.planner.filters as filters
import bloomery.planner.names as names
from bloomery.errors import (
    AmbiguousDimension,
    InvalidRequest,
    PlannerError,
    UnknownMember,
    UnreachableAtGrain,
)
from bloomery.naming import DefaultNaming
from bloomery.planner.result import QueryPlan
from bloomery.runtime import sql_client_for_dialect

if TYPE_CHECKING:
    from bloomery.ir import ProjectIR
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
        wherever the coverage precheck can see the problem."""
        resolved = coverage.resolve_request(ir, request, naming=self._naming, policy=policy)
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
        return QueryPlan(
            sql=sql,
            columns=names.columns_from(
                result.query_spec, mart=resolved.mart, metrics_by_name=metrics_by_name
            ),
            mart=resolved.mart.name,
            warnings=warnings,
            explanation=explain.build(
                result,
                resolved,
                ir,
                request,
                naming=self._naming,
                policy_applied=policy is not None,
            ),
            fingerprint=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
        )
