"""The MetricFlow manifest emitter (RFC 0013 §5.2, R1): ``emit_manifest``
lowers :class:`~bloomery.ir.ProjectIR` marts into MetricFlow's own
``PydanticSemanticManifest`` — pure, deterministic, and returned
**post-transform** (``PydanticSemanticManifestTransformer.transform`` is
mandatory; RFC 0014 caches exactly these bytes via :func:`manifest_json`).

Deterministic choices pinned here (RFC 0013 R1; each is golden/unit-tested):

- One mart = exactly one semantic model, and never a semantic model for a
  non-mart entity — that would reintroduce the query-time joins the mart
  design exists to prevent (RFC 0013 D3). ``node_relation`` comes from
  ``NamingPolicy.relation(mart, Layer.GOLD)`` — the same pair the SQLMesh
  mart emission uses, so the manifest and the built table cannot disagree.
- A single-column base key emits a PRIMARY entity with that column as
  ``expr``; a composite key sets ``primary_entity`` on the model instead
  (MetricFlow accepts a model whose primary entity is name-only — verified
  against ``metricflow==0.211.*``).
- The from-side of each single-column ``MartIR.joins[].on`` pair becomes a
  FOREIGN entity named after the joined entity (prefix-qualified on a name
  collision); a composite ``on`` emits no entity — an entity carries one
  ``expr``. Join key columns never double as categorical dimensions.
- Only the day-grain bucket column of a date role is a TIME dimension
  (``<role>_day``, granularity DAY). The coarser bucket columns
  (week/month/quarter/year) are deliberately not emitted: MetricFlow derives
  coarser grains from the day grain (``<entity>__<role>_day__month``).
  Every other flattened non-join-key column is CATEGORICAL.
- ``agg_time_dimension`` is the day-bucket column of the mart's
  lexicographically first date role.
- A metric served by several marts lands as a measure on exactly one —
  cheapest ``cost_hint``, ties lexicographic by mart name: the selection
  rule of RFC 0010 D8, the same one the planner's coverage precheck applies,
  so emitter and planner cannot disagree (MetricFlow requires measure names
  to be unique across semantic models).
- ``SemiAdditiveRule``: ``last`` → MAX, ``first`` → MIN;
  ``avg``/``min``/``max`` are not expressible via ``non_additive_dimension``
  and raise :class:`~bloomery.errors.UnsupportedByTarget` naming the rule
  (RFC 0013 D4).
- A non-additive ratio metric is **never a measure**: it emits as a RATIO
  metric, and only when both component measures are emitted (an unservable
  ratio is simply absent — the planner's coverage precheck refuses it by
  name at request time, RFC 0013 D6).
- The time spine comes from the catalog date dimension via the naming
  policy — the same ``gold.dim_date`` relation the SQLMesh emitter builds
  (RFC 0008 D13). Marts without a declared date dimension are an
  :class:`~bloomery.errors.EmitError`: MetricFlow requires a spine for any
  ``metric_time`` group-by.
- Every collection (semantic models, entities, dimensions, measures,
  metrics) is sorted lexicographically before construction — the manifest
  is hashed and cached (RFC 0014); ordering drift would silently defeat
  the cache.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

# RFC 0013 §5.9a: metricflow_semantic_interfaces has an internal circular
# import — ``implementations.node_relation`` raises ``ImportError`` whenever
# it is the process's *first* metricflow_semantic_interfaces import. This
# import finishes ``metricflow_semantic_interfaces.protocols`` first, making
# every later MSI import (here and elsewhere) safe. Keep it the first MSI
# import in this module, and keep this module the place that owns MSI imports.
from metricflow_semantic_interfaces.implementations.semantic_manifest import (
    PydanticSemanticManifest,
)

# isort: split
from metricflow_semantic_interfaces.implementations.elements.dimension import (
    PydanticDimension,
    PydanticDimensionTypeParams,
)
from metricflow_semantic_interfaces.implementations.elements.entity import PydanticEntity
from metricflow_semantic_interfaces.implementations.elements.measure import (
    PydanticMeasure,
    PydanticNonAdditiveDimensionParameters,
)
from metricflow_semantic_interfaces.implementations.metric import (
    PydanticMetric,
    PydanticMetricInputMeasure,
    PydanticMetricTypeParams,
)
from metricflow_semantic_interfaces.implementations.node_relation import PydanticNodeRelation
from metricflow_semantic_interfaces.implementations.project_configuration import (
    PydanticProjectConfiguration,
)
from metricflow_semantic_interfaces.implementations.semantic_model import PydanticSemanticModel
from metricflow_semantic_interfaces.implementations.time_spine import (
    PydanticTimeSpine,
    PydanticTimeSpinePrimaryColumn,
)
from metricflow_semantic_interfaces.transformations.semantic_manifest_transformer import (
    PydanticSemanticManifestTransformer,
)
from metricflow_semantic_interfaces.type_enums.aggregation_type import AggregationType
from metricflow_semantic_interfaces.type_enums.dimension_type import DimensionType
from metricflow_semantic_interfaces.type_enums.entity_type import EntityType
from metricflow_semantic_interfaces.type_enums.metric_type import MetricType
from metricflow_semantic_interfaces.type_enums.time_granularity import TimeGranularity

from bloomery.emit.base import Feature, TargetCapabilities
from bloomery.errors import EmitError, UnsupportedByTarget
from bloomery.ir import Additivity, Layer, SemiAdditiveRule

if TYPE_CHECKING:
    from bloomery.ir import (
        DateDimensionIR,
        EntityIR,
        MartIR,
        MetricIR,
        ProjectIR,
    )
    from bloomery.naming import NamingPolicy

__all__ = [
    "METRICFLOW_PLANNER_CAPABILITIES",
    "emit_manifest",
    "manifest_json",
]

#: The MetricFlow planner's declared capabilities (RFC 0008 D12, RFC 0013).
#:
#: ``QUERY_TIME_JOIN`` and ``MULTI_FACT`` are absent **by deliberate policy,
#: not limitation**: MetricFlow can plan multi-hop query-time joins, but a
#: cross-grain request is *refused* at the planner's coverage precheck
#: (RFC 0013 D6) — a mart answers a request alone or not at all, which is the
#: fan-out-impossibility property the mart design (RFC 0010) exists for.
#: Do not "fix" this by adding the features.
METRICFLOW_PLANNER_CAPABILITIES = TargetCapabilities(
    supported=frozenset(
        {
            Feature.SEMI_ADDITIVE,
            Feature.NON_ADDITIVE,
            Feature.CUMULATIVE,
            Feature.DERIVED_METRIC,
            Feature.ROLE_PLAYING_DIM,
            Feature.ROW_LEVEL_SECURITY,
        }
    )
)

#: ``metric_time`` is MetricFlow's canonical query-time dimension (RFC 0013
#: R4); the spec layer already rejects it as a member name (M1) — the emitter
#: re-checks as defense in depth.
_RESERVED_NAME = "metric_time"

_AGGREGATIONS: dict[str, AggregationType] = {
    "avg": AggregationType.AVERAGE,
    "average": AggregationType.AVERAGE,
    "count": AggregationType.COUNT,
    "count_distinct": AggregationType.COUNT_DISTINCT,
    "max": AggregationType.MAX,
    "median": AggregationType.MEDIAN,
    "min": AggregationType.MIN,
    "sum": AggregationType.SUM,
    "sum_boolean": AggregationType.SUM_BOOLEAN,
}

#: RFC 0013 D4: ``last`` keeps the value at the latest ``over`` point (MAX),
#: ``first`` at the earliest (MIN); the other rules are inexpressible.
_WINDOW_CHOICES: dict[SemiAdditiveRule, AggregationType] = {
    SemiAdditiveRule.LAST: AggregationType.MAX,
    SemiAdditiveRule.FIRST: AggregationType.MIN,
}


def _aggregation(metric: MetricIR) -> AggregationType:
    aggregation = _AGGREGATIONS.get(metric.agg) if metric.agg is not None else None
    if aggregation is None:
        msg = (
            f"metric {metric.name!r} uses aggregation {metric.agg!r}, which has no MetricFlow "
            f"AggregationType mapping; supported: {sorted(_AGGREGATIONS)}"
        )
        raise UnsupportedByTarget(msg)
    return aggregation


def _non_additive_dimension(
    metric: MetricIR, mart: MartIR, day_by_source: dict[str, str]
) -> PydanticNonAdditiveDimensionParameters:
    policy = metric.semi_additive
    if policy is None:
        msg = (
            f"semi-additive metric {metric.name!r} carries no {{over, rule}} policy — "
            "nothing to lower to non_additive_dimension (RFC 0013 D4)"
        )
        raise EmitError(msg)
    window_choice = _WINDOW_CHOICES.get(policy.rule)
    if window_choice is None:
        msg = (
            f"semi-additive rule {policy.rule.value!r} of metric {metric.name!r} is not "
            "expressible via MetricFlow's non_additive_dimension (only last -> MAX and "
            "first -> MIN are; RFC 0013 D4)"
        )
        raise UnsupportedByTarget(msg)
    day_column = day_by_source.get(policy.over.qualified)
    if day_column is None:
        msg = (
            f"semi-additive metric {metric.name!r} is non-additive over "
            f"{policy.over.qualified!r}, but mart {mart.name!r} declares no date role over "
            "that column — add a {date: ..., role: ...} flatten step for it"
        )
        raise EmitError(msg)
    return PydanticNonAdditiveDimensionParameters(
        name=day_column,
        window_choice=window_choice,
        window_groupings=[],
    )


def _measure_owners(ir: ProjectIR) -> dict[str, MartIR]:
    """Metric name → the single mart its measure is emitted on: cheapest
    ``cost_hint``, ties lexicographic by mart name (RFC 0010 D8 — the same
    rule the planner's coverage precheck applies)."""
    owners: dict[str, MartIR] = {}
    for mart in ir.marts:
        for name in mart.measures:
            current = owners.get(name)
            if current is None or (mart.cost_hint, mart.name) < (
                current.cost_hint,
                current.name,
            ):
                owners[name] = mart
    return owners


def _day_columns(mart: MartIR) -> dict[str, str]:
    """Source date column → the day-bucket column serving it; when two roles
    bucket the same column, the lexicographically first role wins (columns
    are sorted by name, so first-seen is first lexicographically)."""
    day_by_source: dict[str, str] = {}
    for column in mart.columns:
        if column.ref is not None and column.ref.dimension == "day":
            day_by_source.setdefault(column.source_column, column.name)
    return day_by_source


def _entities(
    mart: MartIR, base: EntityIR
) -> tuple[list[PydanticEntity], str | None, frozenset[str]]:
    """The model's entity elements, its ``primary_entity`` (composite-key
    marts only), and the join-key columns consumed as entity expressions."""
    entities: list[PydanticEntity] = []
    primary_entity: str | None = None
    if len(base.key) == 1:
        entities.append(PydanticEntity(name=mart.grain, type=EntityType.PRIMARY, expr=base.key[0]))
    else:
        # Composite key: no single natural key column exists, so the primary
        # entity is declared name-only on the model (RFC 0013 D3).
        primary_entity = mart.grain
    used = {mart.grain}
    join_keys: set[str] = set()
    for join in mart.joins:
        join_keys.update(from_column for from_column, _to in join.on)
        if len(join.on) != 1:
            continue  # a composite join key has no single entity expr
        name = join.entity if join.entity not in used else f"{join.prefix}{join.entity}"
        if name in used:
            continue
        used.add(name)
        entities.append(PydanticEntity(name=name, type=EntityType.FOREIGN, expr=join.on[0][0]))
    entities.sort(key=lambda e: e.name)
    return entities, primary_entity, frozenset(join_keys)


def _dimensions(
    mart: MartIR, join_keys: frozenset[str], descriptions: dict[tuple[str, str], str | None]
) -> list[PydanticDimension]:
    dimensions: list[PydanticDimension] = []
    for column in mart.columns:  # sorted by name on MartIR
        description = descriptions.get((column.source_entity, column.source_column))
        if column.ref is not None:
            if column.ref.dimension != "day":
                continue  # coarser grains derive from the day dimension
            dimensions.append(
                PydanticDimension(
                    name=column.name,
                    type=DimensionType.TIME,
                    type_params=PydanticDimensionTypeParams(time_granularity=TimeGranularity.DAY),
                    description=description,
                )
            )
        elif column.name not in join_keys:
            dimensions.append(
                PydanticDimension(
                    name=column.name,
                    type=DimensionType.CATEGORICAL,
                    description=description,
                )
            )
    return dimensions


def _measures(
    mart: MartIR,
    owners: dict[str, MartIR],
    metrics_by_name: dict[str, MetricIR],
    day_by_source: dict[str, str],
) -> list[PydanticMeasure]:
    owned = [name for name in mart.measures if owners[name] is mart]  # sorted on MartIR
    measures: list[PydanticMeasure] = []
    for name in owned:
        metric = metrics_by_name[name]
        if metric.additivity is Additivity.NON_ADDITIVE:
            continue  # never a measure — RATIO metric territory (RFC 0013 D4)
        if metric.expr is None:
            msg = (
                f"metric {metric.name!r} has no expression to emit as a MetricFlow measure "
                "— only agg-over-expr metrics lower to measures (RFC 0013 §5.2)"
            )
            raise UnsupportedByTarget(msg)
        non_additive = None
        if metric.additivity is Additivity.SEMI_ADDITIVE:
            non_additive = _non_additive_dimension(metric, mart, day_by_source)
        measures.append(
            PydanticMeasure(
                name=metric.name,
                agg=_aggregation(metric),
                expr=metric.expr.sql,
                agg_time_dimension=_agg_time_dimension(mart),
                non_additive_dimension=non_additive,
            )
        )
    return measures


def _agg_time_dimension(mart: MartIR) -> str:
    """The mart's default aggregation time dimension: the day-bucket column
    of its lexicographically first date role (deterministic; RFC 0013 R1).

    A measure-carrying mart always has a date role — the guardrail stage
    refuses ``MartMissingTimeDimension`` before emission (RFC 0010 D9); the
    re-check here is the RFC 0013 D3 rule-2 defense.
    """
    roles = sorted({c.ref.role for c in mart.columns if c.ref is not None and c.ref.role})
    if not roles:
        msg = (
            f"mart {mart.name!r} carries measures but no date role reached the emitter — "
            "the guardrail stage should have refused this (RFC 0010 D9)"
        )
        raise EmitError(msg)
    return f"{roles[0]}_day"


def _semantic_model(
    mart: MartIR,
    ir: ProjectIR,
    owners: dict[str, MartIR],
    metrics_by_name: dict[str, MetricIR],
    descriptions: dict[tuple[str, str], str | None],
    naming: NamingPolicy,
) -> PydanticSemanticModel:
    base = next(entity for entity in ir.entities if entity.name == mart.base)
    namespace, relation = naming.relation(mart.name, Layer.GOLD)
    entities, primary_entity, join_keys = _entities(mart, base)
    return PydanticSemanticModel(
        name=mart.name,
        node_relation=PydanticNodeRelation(schema_name=namespace, alias=relation),
        primary_entity=primary_entity,
        entities=entities,
        dimensions=_dimensions(mart, join_keys, descriptions),
        measures=_measures(mart, owners, metrics_by_name, _day_columns(mart)),
    )


def _metrics(ir: ProjectIR, owners: dict[str, MartIR]) -> list[PydanticMetric]:
    """One SIMPLE metric per emitted measure; one RATIO metric per ratio
    whose component measures are both emitted. Sorted by name."""
    by_name = {metric.name: metric for metric in ir.metrics}
    emitted_measures = {
        name for name in owners if by_name[name].additivity is not Additivity.NON_ADDITIVE
    }
    metrics: list[PydanticMetric] = []
    for metric in ir.metrics:  # sorted by name on ProjectIR
        if metric.name in emitted_measures:
            metrics.append(
                PydanticMetric(
                    name=metric.name,
                    description=metric.description,
                    type=MetricType.SIMPLE,
                    type_params=PydanticMetricTypeParams(
                        measure=PydanticMetricInputMeasure(name=metric.name)
                    ),
                )
            )
        elif (
            metric.additivity is Additivity.NON_ADDITIVE
            and metric.ratio is not None
            and metric.ratio.numerator in emitted_measures
            and metric.ratio.denominator in emitted_measures
        ):
            metrics.append(
                PydanticMetric(
                    name=metric.name,
                    description=metric.description,
                    type=MetricType.RATIO,
                    type_params=PydanticMetricTypeParams(
                        numerator=PydanticMetricInputMeasure(name=metric.ratio.numerator),
                        denominator=PydanticMetricInputMeasure(name=metric.ratio.denominator),
                    ),
                )
            )
    return metrics


def _project_configuration(
    date_dimension: DateDimensionIR | None, naming: NamingPolicy
) -> PydanticProjectConfiguration:
    if date_dimension is None:
        return PydanticProjectConfiguration()
    # Same convention as the SQLMesh dim_date emission (RFC 0008 D13): the
    # date dimension keeps its declared relation name; the naming policy
    # shapes only the gold namespace. One definition, two emissions, no drift.
    namespace, _mart_relation = naming.relation(date_dimension.name, Layer.GOLD)
    return PydanticProjectConfiguration(
        time_spines=[
            PydanticTimeSpine(
                node_relation=PydanticNodeRelation(
                    schema_name=namespace, alias=date_dimension.name
                ),
                primary_column=PydanticTimeSpinePrimaryColumn(
                    name=f"date_{date_dimension.grain}",
                    time_granularity=TimeGranularity(date_dimension.grain),
                ),
            )
        ]
    )


def _check_reserved(manifest: PydanticSemanticManifest) -> None:
    """Defense in depth (RFC 0013 R4): the spec layer already rejects
    ``metric_time`` as a member name (M1); re-check the emitted surface."""
    names: set[str] = set()
    for model in manifest.semantic_models:
        names.add(model.name)
        names.update(entity.name for entity in model.entities)
        names.update(dimension.name for dimension in model.dimensions)
        names.update(measure.name for measure in model.measures)
    names.update(metric.name for metric in manifest.metrics)
    if _RESERVED_NAME in names:
        msg = (
            f"{_RESERVED_NAME!r} appeared in the emitted manifest — it is MetricFlow's "
            "reserved query-time dimension (RFC 0013 R4) and must be rejected at spec "
            "validation; this is a bug upstream of the emitter"
        )
        raise EmitError(msg)


def emit_manifest(ir: ProjectIR, *, naming: NamingPolicy) -> PydanticSemanticManifest:
    """Lower a project's marts to a **transformed** MetricFlow manifest.

    Pure and deterministic: same IR and naming policy in, byte-identical
    :func:`manifest_json` out, across processes and hash seeds (RFC 0013 R1).
    Raises :class:`~bloomery.errors.EmitError` when marts exist without a
    catalog ``date_dimension`` — MetricFlow requires a declared time spine
    for ``metric_time``; declare one in the catalog.
    """
    if ir.marts and ir.date_dimension is None:
        msg = (
            f"project has {len(ir.marts)} mart(s) but the catalog declares no "
            "date_dimension — MetricFlow requires a declared time spine for metric_time "
            "(RFC 0013 R1). Fix: declare catalog date_dimension "
            "(name, grain: day, start_year, end_year)"
        )
        raise EmitError(msg)
    owners = _measure_owners(ir)
    metrics_by_name = {metric.name: metric for metric in ir.metrics}
    descriptions = {
        (entity.name, column.name): column.description
        for entity in ir.entities
        for column in entity.columns
    }
    manifest = PydanticSemanticManifest(
        semantic_models=[
            _semantic_model(mart, ir, owners, metrics_by_name, descriptions, naming)
            for mart in ir.marts  # sorted by name on ProjectIR
        ],
        metrics=_metrics(ir, owners),
        project_configuration=_project_configuration(ir.date_dimension, naming),
    )
    _check_reserved(manifest)
    # transform() is mandatory: without it explain() fails loudly with
    # MetricFlowInternalError (verified, RFC 0013 §3). M8 caches the
    # *post-transform* manifest (RFC 0014 D3), so that is what we return.
    return PydanticSemanticManifestTransformer.transform(manifest)


def manifest_json(manifest: PydanticSemanticManifest, *, indent: int | None = None) -> str:
    """Deterministic sorted-keys JSON for a (transformed) manifest — the
    golden/caching serialization (RFC 0014 D5: never pickle). MetricFlow's
    manifest objects are pydantic-v1-shim models, hence ``.json()`` (typed
    ``Any`` through the shim, so the return is pinned here)."""
    return cast("str", manifest.json(sort_keys=True, indent=indent))
