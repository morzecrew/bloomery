"""M4.5 verification task V3 — hydration cost at realistic tenant scale.

Builds a synthetic manifest of ~30 semantic models / ~90 metrics programmatically
and measures (median of >=20 runs, time.perf_counter):

    PydanticSemanticManifestTransformer.transform()
    manifest.json() size (bytes)
    PydanticSemanticManifest.parse_raw()
    SemanticManifestLookup() construction
    cold hydration = parse_raw + lookup   (the RFC 0014 L2->L1 path)
    engine.explain() for a simple one-metric one-dimension query

plus the tracemalloc resident delta for 5 simultaneously-hydrated lookups.

Compare against the pivot doc §1.3 numbers (23 ms / 15 ms / 13 ms / ~29 ms cold /
1.6 MB) and RFC 0014's 50 ms-cold / 10 ms-warm budgets.

How to run (spike env lives OUTSIDE the repo; see spike.py header):

    uv run --project <spike-env-dir> python spikes/metricflow/v3_hydration.py
"""

from __future__ import annotations

import statistics
import time
import tracemalloc

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
from metricflow.protocols.sql_client import SqlEngine
from metricflow.sql.render.duckdb_renderer import DuckDbSqlPlanRenderer

from spike import RenderOnlySqlClient  # same directory

N_MODELS = 30
MEASURES_PER_MODEL = 3  # 90 measures -> 90 simple metrics
DIMS_PER_MODEL = 6  # 1 time dim + 5 categorical
RUNS = 25


def build_synthetic_manifest() -> PydanticSemanticManifest:
    models, metrics = [], []
    for m in range(N_MODELS):
        name = f"mart_{m:02d}"
        entity = f"entity_{m:02d}"
        measures = [
            PydanticMeasure(
                name=f"{name}_measure_{k}",
                agg=AggregationType.SUM,
                expr=f"col_{k}",
                agg_time_dimension="event_at",
            )
            for k in range(MEASURES_PER_MODEL)
        ]
        dims = [
            PydanticDimension(
                name="event_at",
                type=DimensionType.TIME,
                type_params=PydanticDimensionTypeParams(time_granularity=TimeGranularity.DAY),
            )
        ] + [
            PydanticDimension(name=f"dim_{d}", type=DimensionType.CATEGORICAL)
            for d in range(DIMS_PER_MODEL - 1)
        ]
        models.append(
            PydanticSemanticModel(
                name=name,
                node_relation=PydanticNodeRelation(alias=name, schema_name="gold"),
                entities=[PydanticEntity(name=entity, type=EntityType.PRIMARY, expr="pk")],
                measures=measures,
                dimensions=dims,
            )
        )
        metrics.extend(
            PydanticMetric(
                name=f"{name}_metric_{k}",
                type=MetricType.SIMPLE,
                description=f"Synthetic metric {k} on {name}, for hydration benchmarking.",
                type_params=PydanticMetricTypeParams(
                    measure=PydanticMetricInputMeasure(name=f"{name}_measure_{k}")
                ),
            )
            for k in range(MEASURES_PER_MODEL)
        )
    return PydanticSemanticManifest(
        semantic_models=models,
        metrics=metrics,
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


def bench(label: str, fn, runs: int = RUNS) -> float:
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    med = statistics.median(times)
    print(f"{label:<50} median {med:8.2f} ms  (min {min(times):.2f}, max {max(times):.2f})")
    return med


def main() -> None:
    raw = build_synthetic_manifest()
    print(
        f"synthetic manifest: {len(raw.semantic_models)} semantic models, "
        f"{len(raw.metrics)} metrics"
    )

    t_transform = bench(
        "transform()", lambda: PydanticSemanticManifestTransformer.transform(raw.copy(deep=True))
    )
    transformed = PydanticSemanticManifestTransformer.transform(raw.copy(deep=True))
    payload = transformed.json()
    print(f"{'.json() payload size':<50} {len(payload) / 1024:8.1f} KB")
    t_parse = bench("parse_raw()", lambda: PydanticSemanticManifest.parse_raw(payload))
    parsed = PydanticSemanticManifest.parse_raw(payload)
    t_lookup = bench("SemanticManifestLookup()", lambda: SemanticManifestLookup(parsed))

    def cold():
        SemanticManifestLookup(PydanticSemanticManifest.parse_raw(payload))

    t_cold = bench("cold hydration (parse_raw + lookup)", cold)

    lookup = SemanticManifestLookup(parsed)
    engine = MetricFlowEngine(
        semantic_manifest_lookup=lookup,
        sql_client=RenderOnlySqlClient(SqlEngine.DUCKDB, DuckDbSqlPlanRenderer()),
    )
    req = MetricFlowQueryRequest.create(
        metric_names=["mart_00_metric_0"], group_by_names=["entity_00__dim_0"]
    )
    t_explain = bench("engine.explain() simple query", lambda: engine.explain(req))

    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    held = [SemanticManifestLookup(PydanticSemanticManifest.parse_raw(payload)) for _ in range(5)]
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()
    delta = sum(s.size_diff for s in after.compare_to(before, "filename"))
    print(
        f"{'tracemalloc delta, 5 hydrated lookups':<50} {delta / 1024 / 1024:8.2f} MB total, "
        f"{delta / 5 / 1024 / 1024:.2f} MB per lookup"
    )
    assert len(held) == 5

    print("\n--- verdict vs budgets ---")
    print(f"pivot doc claims: transform 23ms, parse 15ms, lookup 13ms, cold ~29ms, 1.6MB/tenant")
    print(f"measured:         transform {t_transform:.0f}ms, parse {t_parse:.0f}ms, "
          f"lookup {t_lookup:.0f}ms, cold {t_cold:.0f}ms")
    print(f"RFC 0014 budgets: 50ms cold ({'PASS' if t_cold <= 50 else 'FAIL'}), "
          f"10ms warm (L1 hit is a dict lookup — trivially met; explain is "
          f"{t_explain:.0f}ms/query, budgeted separately)")


if __name__ == "__main__":
    main()
