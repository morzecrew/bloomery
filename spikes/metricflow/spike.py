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

from metricflow_semantic_interfaces.implementations.elements.dimension import (
    PydanticDimension,
    PydanticDimensionTypeParams,
)
from metricflow_semantic_interfaces.implementations.elements.entity import PydanticEntity
from metricflow_semantic_interfaces.implementations.elements.measure import PydanticMeasure
from metricflow_semantic_interfaces.implementations.metric import (
    PydanticMetric,
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
from metricflow_semantic_interfaces.type_enums import (
    AggregationType,
    DimensionType,
    EntityType,
    MetricType,
    TimeGranularity,
)
from metricflow_semantics.model.semantic_manifest_lookup import SemanticManifestLookup

from metricflow.engine.metricflow_engine import MetricFlowEngine, MetricFlowQueryRequest
from metricflow.protocols.sql_client import SqlClient, SqlEngine
from metricflow.sql.render.duckdb_renderer import DuckDbSqlPlanRenderer


class RenderOnlySqlClient(SqlClient):
    """Renders SQL. Cannot connect to anything, by construction."""

    def __init__(self, engine: SqlEngine, renderer) -> None:
        self._e, self._r = engine, renderer

    @property
    def sql_engine_type(self):
        return self._e

    @property
    def sql_plan_renderer(self):
        return self._r

    def query(self, *a, **k):
        raise NotImplementedError("render-only")

    def execute(self, *a, **k):
        raise NotImplementedError("render-only")

    def dry_run(self, *a, **k):
        raise NotImplementedError("render-only")

    def close(self):
        pass

    def render_bind_parameter_key(self, key):
        return f"${key}"


def build_manifest() -> PydanticSemanticManifest:
    order_items = PydanticSemanticModel(
        name="order_items",
        node_relation=PydanticNodeRelation(alias="mart_order_items", schema_name="gold"),
        entities=[PydanticEntity(name="order_item", type=EntityType.PRIMARY, expr="line_id")],
        measures=[
            PydanticMeasure(
                name="revenue",
                agg=AggregationType.SUM,
                expr="net_revenue",
                agg_time_dimension="ordered_at",
            ),
            PydanticMeasure(
                name="order_count",
                agg=AggregationType.COUNT,
                expr="order_id",
                agg_time_dimension="ordered_at",
            ),
        ],
        dimensions=[
            PydanticDimension(
                name="ordered_at",
                type=DimensionType.TIME,
                type_params=PydanticDimensionTypeParams(time_granularity=TimeGranularity.DAY),
            ),
            PydanticDimension(
                name="shipped_at",
                type=DimensionType.TIME,
                type_params=PydanticDimensionTypeParams(time_granularity=TimeGranularity.DAY),
            ),
            PydanticDimension(name="carrier", type=DimensionType.CATEGORICAL),
        ],
    )

    return PydanticSemanticManifest(
        semantic_models=[order_items],
        metrics=[
            PydanticMetric(
                name="revenue",
                type=MetricType.SIMPLE,
                type_params=PydanticMetricTypeParams(
                    measure=PydanticMetricInputMeasure(name="revenue")
                ),
            ),
            PydanticMetric(
                name="order_count",
                type=MetricType.SIMPLE,
                type_params=PydanticMetricTypeParams(
                    measure=PydanticMetricInputMeasure(name="order_count")
                ),
            ),
            PydanticMetric(
                name="avg_order_value",
                type=MetricType.RATIO,
                type_params=PydanticMetricTypeParams(
                    numerator=PydanticMetricInputMeasure(name="revenue"),
                    denominator=PydanticMetricInputMeasure(name="order_count"),
                ),
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
