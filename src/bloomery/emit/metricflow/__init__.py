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
- A ``derived:`` metric is never a measure either, and emits as a DERIVED
  metric over aliased inputs, each carrying its ``offset_window`` or
  ``offset_to_grain`` (RFC 0034 D1/D2). Which metrics are emitted at all is
  a *fixed point* rather than one pass — a derived metric may read another —
  and the same absence rule applies: inputs not all emitted, metric absent.
- A ``cumulative:`` metric keeps its own measure and emits as a CUMULATIVE
  metric carrying ``cumulative_type_params`` (D5). The legacy
  ``type_params.window``/``grain_to_date`` pair stays pinned to ``None``:
  writing both would leave two accounts of one window in the manifest.
  ``period_agg`` is pinned to MetricFlow's own ``FIRST`` — it decides what a
  cumulative metric means at a grain coarser than its accumulation, and
  bloomery does not invent a divergence from the ecosystem there.
- A ``filter:`` emits as the metric's ``where_filters`` intersection — an
  intersection being an AND, which is what the clauses are (D8). The
  dimension is spelled ``{entity}__{column}``, the only name MetricFlow's
  resolver accepts inside a where-filter; the comparison and the literal
  escaping come from the lowering package, shared with Cube (D15).
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

from typing import TYPE_CHECKING

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
from metricflow_semantic_interfaces.implementations.filters.where_filter import (
    PydanticWhereFilter,
    PydanticWhereFilterIntersection,
)
from metricflow_semantic_interfaces.implementations.metric import (
    PydanticCumulativeTypeParams,
    PydanticMetric,
    PydanticMetricInput,
    PydanticMetricInputMeasure,
    PydanticMetricTimeWindow,
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
from metricflow_semantic_interfaces.type_enums.period_agg import PeriodAggregation
from metricflow_semantic_interfaces.type_enums.time_granularity import TimeGranularity

from bloomery.emit.base import ArtifactKind, EmittedArtifact
from bloomery.emit.lower import mart_column_type, measure_owners, metric_filter_sql
from bloomery.errors import EmitError, UnsupportedByTarget, guaranteed
from bloomery.ir import Additivity, Layer, SemiAdditiveRule

if TYPE_CHECKING:
    from bloomery.emit.base import EmitContext
    from bloomery.ir import (
        DateDimensionIR,
        EntityIR,
        MartIR,
        MetricFilterIR,
        MetricIR,
        ProjectIR,
        TimeWindow,
    )
    from bloomery.naming import NamingPolicy

# ----------------------- #

__all__ = [
    "MANIFEST_PATH",
    "MetricFlowEmitter",
    "emit_manifest",
    "entity_key",
    "manifest_json",
    "measure_owners",
]

#: ``metric_time`` is MetricFlow's canonical query-time dimension (RFC 0013
#: R4); the spec layer already rejects it as a member name (M1) — the emitter
#: re-checks as defense in depth.
_RESERVED_NAME = "metric_time"


def entity_key(mart: MartIR) -> str:
    """The dunder prefix of every group-by item on a mart's semantic model:
    its grain entity name.

    One definition, three readers. It is the PRIMARY entity's name in the
    single-column-key shape and the model's ``primary_entity`` in the composite
    one (:func:`_entities`); it prefixes the dimension inside a metric filter's
    where-clause (RFC 0034 D8); and the planner spells every requested group-by
    with it. The planner's :func:`bloomery.planner.names.entity_key` delegates
    here rather than repeating ``mart.grain`` — a rule two modules must agree on
    and that is defined in neither is the defect this codebase keeps finding in
    itself.
    """

    return mart.grain


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


# ....................... #


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


# ....................... #


def _day_columns(mart: MartIR) -> dict[str, str]:
    """Source date column → the day-bucket column serving it; when two roles
    bucket the same column, the lexicographically first role wins (columns
    are sorted by name, so first-seen is first lexicographically)."""
    day_by_source: dict[str, str] = {}

    for column in mart.columns:
        if column.ref is not None and column.ref.dimension == "day":
            day_by_source.setdefault(column.source_column, column.name)

    return day_by_source


# MSI's pydantic-v1-shim models declare their optional fields without explicit
# defaults (pydantic's implicit-optional), which strict type checkers read as
# *required* constructor arguments. Every unused optional field below is
# therefore pinned to its ``None`` default explicitly — identical runtime
# models and bytes, but honest under strict typing.


# ....................... #


def _entities(
    mart: MartIR, base: EntityIR | None
) -> tuple[list[PydanticEntity], str | None, frozenset[str]]:
    """The model's entity elements, its ``primary_entity`` (composite-key
    marts only), and the join-key columns consumed as entity expressions.

    ``base`` is ``None`` for the quality mart (RFC 0016 §5.8): it has no
    silver entity underneath it, so there is no natural key column to make a
    PRIMARY entity's ``expr`` — it takes the same name-only ``primary_entity``
    the composite-key case does, which MetricFlow accepts.
    """
    entities: list[PydanticEntity] = []
    primary_entity: str | None = None

    if base is not None and len(base.key) == 1:
        entities.append(
            PydanticEntity(
                name=entity_key(mart),
                type=EntityType.PRIMARY,
                expr=base.key[0],
                description=None,
                role=None,
                config=None,
            )
        )
    else:
        # Composite key: no single natural key column exists, so the primary
        # entity is declared name-only on the model (RFC 0013 D3).
        primary_entity = entity_key(mart)

    used = {entity_key(mart)}
    join_keys: set[str] = set()

    for join in mart.joins:
        join_keys.update(from_column for from_column, _to in join.on)
        if len(join.on) != 1:
            continue  # a composite join key has no single entity expr
        name = join.entity if join.entity not in used else f"{join.prefix}{join.entity}"
        if name in used:
            continue
        used.add(name)
        entities.append(
            PydanticEntity(
                name=name,
                type=EntityType.FOREIGN,
                expr=join.on[0][0],
                description=None,
                role=None,
                config=None,
            )
        )

    entities.sort(key=lambda e: e.name)

    return entities, primary_entity, frozenset(join_keys)


# ....................... #


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
                    metadata=None,
                    config=None,
                )
            )
        elif column.name not in join_keys:
            dimensions.append(
                PydanticDimension(
                    name=column.name,
                    type=DimensionType.CATEGORICAL,
                    description=description,
                    type_params=None,
                    metadata=None,
                    config=None,
                )
            )

    return dimensions


# ....................... #


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
                description=None,
                create_metric=None,
                agg_params=None,
                metadata=None,
            )
        )

    return measures


# ....................... #


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


# ....................... #


def _semantic_model(
    mart: MartIR,
    ir: ProjectIR,
    owners: dict[str, MartIR],
    metrics_by_name: dict[str, MetricIR],
    descriptions: dict[tuple[str, str], str | None],
    naming: NamingPolicy,
) -> PydanticSemanticModel:
    base = next((entity for entity in ir.entities if entity.name == mart.base), None)
    namespace, relation = naming.relation(mart.name, Layer.GOLD)
    entities, primary_entity, join_keys = _entities(mart, base)
    return PydanticSemanticModel(
        name=mart.name,
        node_relation=PydanticNodeRelation(schema_name=namespace, alias=relation),
        primary_entity=primary_entity,
        entities=entities,
        dimensions=_dimensions(mart, join_keys, descriptions),
        measures=_measures(mart, owners, metrics_by_name, _day_columns(mart)),
        defaults=None,
        description=None,
        metadata=None,
        config=None,
    )


# ....................... #


def _metric_input(name: str) -> PydanticMetricInput:
    """A name-only ratio component. MSI coerces a ``PydanticMetricInputMeasure``
    into exactly this shape at validation time; constructing it directly says
    what is meant (and is byte-identical in the serialized manifest)."""

    return PydanticMetricInput(
        name=name, filter=None, alias=None, offset_window=None, offset_to_grain=None
    )


# ....................... #


def _time_window(window: TimeWindow | None) -> PydanticMetricTimeWindow | None:
    """One IR window as MetricFlow's own (RFC 0034 D2). The grain is already
    singular and already one of ``day|week|month|quarter|year`` — the spec
    grammar establishes both — so this is a rename, not a translation."""

    if window is None:
        return None

    return PydanticMetricTimeWindow(count=window.count, granularity=window.grain)


# ....................... #


def _derived_input(
    alias: str, metric: str, window: TimeWindow | None, to_grain: str | None
) -> PydanticMetricInput:
    """One input of a DERIVED metric: the metric read, the alias its expression
    references, and the offset it is read at (RFC 0034 D1)."""

    return PydanticMetricInput(
        name=metric,
        filter=None,
        alias=alias,
        offset_window=_time_window(window),
        offset_to_grain=to_grain,
    )


# ....................... #


def _where(
    filters: tuple[MetricFilterIR, ...], *, mart: MartIR
) -> PydanticWhereFilterIntersection | None:
    """A metric's ``filter:`` list as MetricFlow's where-filter intersection —
    an intersection being an AND, which is what the clauses are (RFC 0034 D8).

    The dimension is spelled the way MetricFlow names a group-by item,
    ``{entity}__{column}``; the comparison, list shape and literal escaping come
    from the shared renderer, so this target and Cube cannot disagree about
    them (D15).
    """

    if not filters:
        return None

    entity = entity_key(mart)

    return PydanticWhereFilterIntersection(
        where_filters=[
            PydanticWhereFilter(
                where_sql_template=metric_filter_sql(
                    clause,
                    ref=f"{{{{ Dimension('{entity}__{clause.dimension}') }}}}",
                    declared=mart_column_type(mart, clause.dimension),
                )
            )
            for clause in filters
        ]
    )


# ....................... #


def _type_params(
    *,
    measure: PydanticMetricInputMeasure | None = None,
    numerator: PydanticMetricInput | None = None,
    denominator: PydanticMetricInput | None = None,
    expr: str | None = None,
    metrics: list[PydanticMetricInput] | None = None,
    cumulative: PydanticCumulativeTypeParams | None = None,
) -> PydanticMetricTypeParams:
    """``PydanticMetricTypeParams`` with every field this emitter does not use
    pinned to its ``None`` default (see the implicit-optional note above).

    ``window``/``grain_to_date`` stay pinned even though RFC 0034 lowers
    cumulative metrics: they are the *legacy* spelling of what
    ``cumulative_type_params`` now carries, and writing both would leave two
    accounts of one window in the manifest for MSI's transformer to reconcile.
    """

    return PydanticMetricTypeParams(
        measure=measure,
        numerator=numerator,
        denominator=denominator,
        expr=expr,
        window=None,
        grain_to_date=None,
        metrics=metrics,
        conversion_type_params=None,
        cumulative_type_params=cumulative,
        metric_aggregation_params=None,
    )


# ....................... #


def _emittable(ir: ProjectIR, owners: dict[str, MartIR]) -> frozenset[str]:
    """Every metric name this manifest will carry.

    Three rounds rather than one, because a metric may be defined over another
    (RFC 0034 D1): measures first, then the ratios whose components are
    measures, then derived metrics over anything already established —
    including other derived metrics — to a fixed point. It terminates because
    the resolution DAG is acyclic and each round adds at least one name or
    stops.

    A metric whose inputs are not all emitted is simply absent, which is what
    this emitter has always done with an unservable ratio: the planner's
    coverage precheck refuses it by name at request time (RFC 0013 D6), where
    the message can say which measure no mart carries.
    """

    by_name = {metric.name: metric for metric in ir.metrics}
    measures = {name for name in owners if by_name[name].additivity is not Additivity.NON_ADDITIVE}
    emitted = set(measures)
    emitted.update(
        metric.name
        for metric in ir.metrics
        if metric.additivity is Additivity.NON_ADDITIVE
        and metric.ratio is not None
        and metric.ratio.numerator in measures
        and metric.ratio.denominator in measures
    )

    while True:
        grown = {
            metric.name
            for metric in ir.metrics
            if metric.derived is not None
            and metric.name not in emitted
            and all(input_.metric in emitted for input_ in metric.derived.inputs)
        }
        if not grown:
            return frozenset(emitted)
        emitted |= grown


# ....................... #


def _metric(
    metric: MetricIR, owners: dict[str, MartIR], emitted: frozenset[str]
) -> PydanticMetric | None:
    """One metric in MetricFlow's four shapes, or ``None`` when this manifest
    does not carry it.

    SIMPLE for a metric with a measure, CUMULATIVE when that measure carries a
    window (RFC 0034 D5), RATIO for the fixed two-component decomposition, and
    DERIVED for the general expression over aliased inputs (D1). ``filter:``
    rides on the metric in every shape that can have one — a derived metric is
    refused one at the guardrail stage (D9's sibling refusal), so ``owners``
    always has the mart whose entity key names the filter's dimension.
    """

    if metric.name not in emitted:
        return None

    if metric.derived is not None:
        return PydanticMetric(
            name=metric.name,
            description=metric.description,
            type=MetricType.DERIVED,
            type_params=_type_params(
                expr=metric.derived.expr.sql,
                metrics=[
                    _derived_input(
                        input_.alias, input_.metric, input_.offset_window, input_.offset_to_grain
                    )
                    for input_ in metric.derived.inputs
                ],
            ),
            filter=None,
            metadata=None,
            config=None,
        )

    if metric.additivity is Additivity.NON_ADDITIVE:
        ratio = guaranteed(
            (metric.ratio for _ in (0,) if metric.ratio is not None),
            expected=f"a ratio or derived decomposition on non-additive metric {metric.name!r}",
            by="the additivity guardrail, which refuses a non-additive metric without one",
        )
        return PydanticMetric(
            name=metric.name,
            description=metric.description,
            type=MetricType.RATIO,
            type_params=_type_params(
                numerator=_metric_input(ratio.numerator),
                denominator=_metric_input(ratio.denominator),
            ),
            filter=None,
            metadata=None,
            config=None,
        )

    measure = PydanticMetricInputMeasure(name=metric.name, filter=None, alias=None)
    where = _where(metric.filter, mart=owners[metric.name])

    if metric.cumulative is None:
        return PydanticMetric(
            name=metric.name,
            description=metric.description,
            type=MetricType.SIMPLE,
            type_params=_type_params(measure=measure),
            filter=where,
            metadata=None,
            config=None,
        )

    return PydanticMetric(
        name=metric.name,
        description=metric.description,
        type=MetricType.CUMULATIVE,
        type_params=_type_params(
            measure=measure,
            cumulative=PydanticCumulativeTypeParams(
                window=_time_window(metric.cumulative.window),
                grain_to_date=metric.cumulative.grain_to_date,
                # Authored, not pinned. This decides what a cumulative metric
                # means when the request asks for a grain coarser than the
                # accumulation, and bloomery defaults it to `last` rather than
                # to MetricFlow's `first` — see `PeriodAggregationName`, which
                # carries the measurement that decided it.
                period_agg=PeriodAggregation(metric.cumulative.period_agg),
                metric=None,
            ),
        ),
        filter=where,
        metadata=None,
        config=None,
    )


# ....................... #


def _metrics(ir: ProjectIR, owners: dict[str, MartIR]) -> list[PydanticMetric]:
    """Every emitted metric, in ``ProjectIR`` order — which is sorted by name."""

    emitted = _emittable(ir, owners)
    built = (_metric(metric, owners, emitted) for metric in ir.metrics)

    return [metric for metric in built if metric is not None]


# ....................... #


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


# ....................... #


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


# ....................... #


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

    owners = measure_owners(ir)
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
    transformed = PydanticSemanticManifestTransformer.transform(manifest)

    # transform()'s AddInputMetricMeasuresRule collects each metric's
    # input_measures through a builtin set, so their order is hash-seed
    # dependent — the one nondeterminism in an otherwise deterministic
    # pipeline, surfaced by any RATIO metric (two input measures). Re-sort
    # here: the manifest is hashed, cached, and golden-byte-compared
    # (RFC 0013 R1, RFC 0014 D5); ordering drift would flake goldens and
    # silently defeat the cache.
    for metric in transformed.metrics:
        metric.type_params.input_measures = sorted(
            metric.type_params.input_measures, key=lambda measure: measure.name
        )

    return transformed


# ....................... #


def manifest_json(manifest: PydanticSemanticManifest, *, indent: int | None = None) -> str:
    """Deterministic sorted-keys JSON for a (transformed) manifest — the
    golden/caching serialization (RFC 0014 D5: never pickle). MetricFlow's
    manifest objects are pydantic-v1-shim models, hence ``.json()`` (mypy sees
    ``Any`` through the shim, so the result is pinned via annotation — a
    ``cast`` would be flagged as unnecessary by pyright, which sees ``str``)."""
    payload: str = manifest.json(sort_keys=True, indent=indent)
    return payload


# ....................... #


#: The one artifact this target emits. At the root rather than under a
#: namespace: a MetricFlow project holds a single top-level manifest, and
#: nothing else in the emitted tree competes for the name (RFC 0051 D5).
MANIFEST_PATH = "semantic_manifest.json"


class MetricFlowEmitter:
    """RFC 0051 §5.1: the manifest :func:`emit_manifest` already builds, as a
    file-shaped artifact a caller can write.

    The fourth core target, and the only one that emits no models: MetricFlow
    consumes relations the SQLMesh or dbt artifacts build, and describes what
    they *mean*. Everything below the artifact envelope is
    :func:`emit_manifest`, unchanged and shared with the planner's hydrator —
    a second lowering here would be two accounts of one manifest.
    """

    name = "metricflow"

    # ....................... #

    def emit(self, ir: ProjectIR, ctx: EmitContext) -> tuple[EmittedArtifact, ...]:
        """The semantic manifest as one JSON artifact, or nothing.

        A project with no marts emits **no artifact**, the rule
        :class:`~bloomery.emit.cube.CubeEmitter` applies for the same reason:
        MetricFlow has no silver surface, so a martless project has nothing to
        describe, and an empty manifest is a file claiming a semantic layer
        that is not there.

        :func:`emit_manifest`'s missing-``date_dimension``
        :class:`~bloomery.errors.EmitError` propagates unchanged (RFC 0051 D4)
        — it is the refusal the planner already gives, and a second spelling of
        it here is how the two come to disagree.

        ``indent=2`` rather than compact: the manifest is a file a human reads
        when a metric resolves oddly, and :func:`manifest_json` sorts keys
        either way, so the bytes stay deterministic (RFC 0003 §5.5).

        **The one emitted artifact carrying no fingerprint header**, and the
        exemption is stated here rather than left to be noticed. Every other
        target prefixes its files with ``-- fingerprint: blm1:…`` so a reader
        can tell applied from spec (RFC 0008 D9); this artifact is JSON that
        MetricFlow's own loader parses, and a comment line would make it
        invalid rather than annotated. The manifest has no free-form field to
        carry the value instead. What a caller loses is drift detection *on
        this file*: :class:`~bloomery.emit.EmittedArtifact` still carries
        ``checksum``, and the fingerprint of the compile that produced it is
        on every sibling artifact of the same run.
        """

        if not ir.marts:
            return ()

        content = manifest_json(emit_manifest(ir, naming=ctx.naming), indent=2)

        return (
            EmittedArtifact.create(
                path=MANIFEST_PATH,
                content=content.rstrip("\n") + "\n",
                kind=ArtifactKind.MODEL,
            ),
        )
