"""M4.5 reference implementation — MetricFlow as an embedded render-only library.

Reproduces rfcs/_bloomery-metricflow-pivot.md §2 against the actually-installed
metricflow==0.211.0. Confirms: manifest constructible in code, transform() mandatory,
RenderOnlySqlClient renders SQL with no connection, SQL shape matches the pivot doc.

How to run (spike env lives OUTSIDE the repo so the repo venv is untouched):

    uv run --project <spike-env-dir> python spikes/metricflow/spike.py

where <spike-env-dir> is a uv project declaring:
    bloomery (editable path dep), metricflow==0.211.*, duckdb, sqlmesh>=0.150,
    pydantic>=2.9   (python 3.14; see spikes/metricflow/VERIFICATION.md §V1)

Do NOT `uv add metricflow` to the repo itself until V1's recommendation is applied.
"""

from __future__ import annotations

from typing import NoReturn

from metricflow.engine.metricflow_engine import MetricFlowEngine, MetricFlowQueryRequest
from metricflow.protocols.sql_client import SqlClient, SqlEngine
from metricflow.sql.render.duckdb_renderer import DuckDbSqlPlanRenderer
from metricflow.sql.render.sql_plan_renderer import SqlPlanRenderer
from metricflow_semantic_interfaces.implementations.elements.dimension import (
    PydanticDimension,
    PydanticDimensionTypeParams,
)
from metricflow_semantic_interfaces.implementations.elements.entity import PydanticEntity
from metricflow_semantic_interfaces.implementations.elements.measure import PydanticMeasure
from metricflow_semantic_interfaces.implementations.metric import (
    PydanticMetric,
    PydanticMetricInput,
    PydanticMetricInputMeasure,
    PydanticMetricTypeParams,
)
from metricflow_semantic_interfaces.implementations.node_relation import PydanticNodeRelation
from metricflow_semantic_interfaces.implementations.project_configuration import (
    PydanticProjectConfiguration,
)
from metricflow_semantic_interfaces.implementations.semantic_manifest import (
    PydanticSemanticManifest,
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
from metricflow_semantics.model.semantic_manifest_lookup import SemanticManifestLookup


class RenderOnlySqlClient(SqlClient):
    """Renders SQL. Cannot connect to anything, by construction."""

    def __init__(self, engine: SqlEngine, renderer: SqlPlanRenderer) -> None:
        self._e, self._r = engine, renderer

    @property
    def sql_engine_type(self) -> SqlEngine:
        return self._e

    @property
    def sql_plan_renderer(self) -> SqlPlanRenderer:
        return self._r

    def query(self, *a: object, **k: object) -> NoReturn:
        raise NotImplementedError("render-only")

    def execute(self, *a: object, **k: object) -> NoReturn:
        raise NotImplementedError("render-only")

    def dry_run(self, *a: object, **k: object) -> NoReturn:
        raise NotImplementedError("render-only")

    def close(self) -> None:
        pass

    def render_bind_parameter_key(self, bind_parameter_key: object) -> str:
        return f"${bind_parameter_key}"


def _metric_input(name: str) -> PydanticMetricInput:
    """A name-only ratio component with every optional field pinned to None."""
    return PydanticMetricInput(
        name=name, filter=None, alias=None, offset_window=None, offset_to_grain=None
    )


def build_manifest() -> PydanticSemanticManifest:
    # MSI's pydantic-v1 models declare optional fields without explicit
    # defaults, which pyright reads as required constructor arguments — every
    # unused optional field is pinned to its None default explicitly.
    order_items = PydanticSemanticModel(
        name="order_items",
        node_relation=PydanticNodeRelation(alias="mart_order_items", schema_name="gold"),
        entities=[
            PydanticEntity(
                name="order_item",
                type=EntityType.PRIMARY,
                expr="line_id",
                description=None,
                role=None,
                config=None,
            )
        ],
        measures=[
            PydanticMeasure(
                name="revenue",
                agg=AggregationType.SUM,
                expr="net_revenue",
                agg_time_dimension="ordered_at",
                description=None,
                create_metric=None,
                agg_params=None,
                metadata=None,
            ),
            PydanticMeasure(
                name="order_count",
                agg=AggregationType.COUNT,
                expr="order_id",
                agg_time_dimension="ordered_at",
                description=None,
                create_metric=None,
                agg_params=None,
                metadata=None,
            ),
        ],
        dimensions=[
            PydanticDimension(
                name="ordered_at",
                type=DimensionType.TIME,
                type_params=PydanticDimensionTypeParams(time_granularity=TimeGranularity.DAY),
                description=None,
                metadata=None,
                config=None,
            ),
            PydanticDimension(
                name="shipped_at",
                type=DimensionType.TIME,
                type_params=PydanticDimensionTypeParams(time_granularity=TimeGranularity.DAY),
                description=None,
                metadata=None,
                config=None,
            ),
            PydanticDimension(
                name="carrier",
                type=DimensionType.CATEGORICAL,
                description=None,
                type_params=None,
                metadata=None,
                config=None,
            ),
        ],
        defaults=None,
        description=None,
        primary_entity=None,
        metadata=None,
        config=None,
    )

    return PydanticSemanticManifest(
        semantic_models=[order_items],
        metrics=[
            PydanticMetric(
                name="revenue",
                type=MetricType.SIMPLE,
                type_params=PydanticMetricTypeParams(
                    measure=PydanticMetricInputMeasure(name="revenue", filter=None, alias=None),
                    numerator=None,
                    denominator=None,
                    expr=None,
                    window=None,
                    grain_to_date=None,
                    metrics=None,
                    conversion_type_params=None,
                    cumulative_type_params=None,
                    metric_aggregation_params=None,
                ),
                description=None,
                filter=None,
                metadata=None,
                config=None,
            ),
            PydanticMetric(
                name="order_count",
                type=MetricType.SIMPLE,
                type_params=PydanticMetricTypeParams(
                    measure=PydanticMetricInputMeasure(name="order_count", filter=None, alias=None),
                    numerator=None,
                    denominator=None,
                    expr=None,
                    window=None,
                    grain_to_date=None,
                    metrics=None,
                    conversion_type_params=None,
                    cumulative_type_params=None,
                    metric_aggregation_params=None,
                ),
                description=None,
                filter=None,
                metadata=None,
                config=None,
            ),
            PydanticMetric(
                name="avg_order_value",
                type=MetricType.RATIO,
                type_params=PydanticMetricTypeParams(
                    # MSI coerces an input *measure* into PydanticMetricInput at
                    # validation; construct the coerced shape directly.
                    numerator=_metric_input("revenue"),
                    denominator=_metric_input("order_count"),
                    measure=None,
                    expr=None,
                    window=None,
                    grain_to_date=None,
                    metrics=None,
                    conversion_type_params=None,
                    cumulative_type_params=None,
                    metric_aggregation_params=None,
                ),
                description=None,
                filter=None,
                metadata=None,
                config=None,
            ),
        ],
        project_configuration=PydanticProjectConfiguration(
            time_spines=[
                PydanticTimeSpine(
                    node_relation=PydanticNodeRelation(alias="dim_date", schema_name="gold"),
                    primary_column=PydanticTimeSpinePrimaryColumn(
                        name="date_day", time_granularity=TimeGranularity.DAY
                    ),
                )
            ]
        ),
    )


def build_engine(manifest: PydanticSemanticManifest) -> MetricFlowEngine:
    manifest = PydanticSemanticManifestTransformer.transform(manifest)  # REQUIRED
    return MetricFlowEngine(
        semantic_manifest_lookup=SemanticManifestLookup(manifest),
        sql_client=RenderOnlySqlClient(SqlEngine.DUCKDB, DuckDbSqlPlanRenderer()),
    )


def main() -> None:
    engine = build_engine(build_manifest())
    result = engine.explain(
        MetricFlowQueryRequest.create(
            metric_names=["revenue"],
            group_by_names=["order_item__shipped_at__month", "order_item__carrier"],
            where_constraints=["{{ Dimension('order_item__carrier') }} = 'DHL'"],
            order_by_names=["-revenue"],
            limit=5,
        )
    )
    print(result.sql_statement.sql)


if __name__ == "__main__":
    main()
