"""M4.5 verification task V2 — semi-additive grouping (pivot doc §7, issue #241 gate).

Builds a `semi_additive_inventory` manifest (measure `balance`, SUM, with
non_additive_dimension window_choice=MAX over `snapshot_date`; categorical
`warehouse`), renders SQL with the RenderOnlySqlClient, then EXECUTES that SQL
against an in-process DuckDB seeded with:

    warehouse A: Jan 1 = 100, Jan 2 = 80, Jan 3 = 90
    warehouse B: Jan 3 = 40
    warehouse A: Feb 10 = 85, Feb 20 = 75, Mar 5 = 65, Mar 15 = 95

Cases (expected under last-value-then-sum-across-warehouses semantics):
  (a)  balance, no time group-by, Jan 1-3 filter
       -> 130 globally (A=90 + B=40 on the MAX date, NOT the naive 310)
       -> 90 when scoped to warehouse A (NOT the naive 270)
       [The pivot doc quotes "90" for the unscoped 3-day filter; with B=40
        seeded on Jan 3 that is unsatisfiable under global MAX — see
        VERIFICATION.md V2 for the fixture-seed erratum.]
  (b)  balance by warehouse, Jan 3 only        -> A=90, B=40; total 130
  (c)  balance by month over Jan..Mar          -> THREE rows: Jan=130, Feb=75, Mar=95
       (the issue #241 case: grouping BY the non-additive dimension's grain)

How to run (spike env lives OUTSIDE the repo; see spike.py header):

    uv run --project <spike-env-dir> python spikes/metricflow/v2_semi_additive.py
"""

from __future__ import annotations

import duckdb
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

SEED_ROWS = [
    ("2024-01-01", "A", 100),
    ("2024-01-02", "A", 80),
    ("2024-01-03", "A", 90),
    ("2024-01-03", "B", 40),
    ("2024-02-10", "A", 85),
    ("2024-02-20", "A", 75),
    ("2024-03-05", "A", 65),
    ("2024-03-15", "A", 95),
]


def build_manifest(window_groupings: list[str] | None = None) -> PydanticSemanticManifest:
    inventory = PydanticSemanticModel(
        name="inventory",
        node_relation=PydanticNodeRelation(alias="mart_inventory", schema_name="gold"),
        entities=[
            PydanticEntity(name="inventory", type=EntityType.PRIMARY, expr="snapshot_id"),
        ],
        measures=[
            PydanticMeasure(
                name="balance",
                agg=AggregationType.SUM,
                expr="balance",
                agg_time_dimension="snapshot_date",
                non_additive_dimension=PydanticNonAdditiveDimensionParameters(
                    name="snapshot_date",
                    window_choice=AggregationType.MAX,
                    window_groupings=window_groupings or [],
                ),
            ),
        ],
        dimensions=[
            PydanticDimension(
                name="snapshot_date",
                type=DimensionType.TIME,
                type_params=PydanticDimensionTypeParams(time_granularity=TimeGranularity.DAY),
            ),
            PydanticDimension(name="warehouse", type=DimensionType.CATEGORICAL),
            PydanticDimension(name="tenant_key", type=DimensionType.CATEGORICAL),
        ],
    )
    return PydanticSemanticManifest(
        semantic_models=[inventory],
        metrics=[
            PydanticMetric(
                name="inventory_balance",
                type=MetricType.SIMPLE,
                type_params=PydanticMetricTypeParams(
                    measure=PydanticMetricInputMeasure(name="balance")
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
    manifest = PydanticSemanticManifestTransformer.transform(manifest)
    return MetricFlowEngine(
        semantic_manifest_lookup=SemanticManifestLookup(manifest),
        sql_client=RenderOnlySqlClient(SqlEngine.DUCKDB, DuckDbSqlPlanRenderer()),
    )


def seed_duckdb() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("CREATE SCHEMA gold")
    con.execute(
        "CREATE TABLE gold.mart_inventory ("
        "snapshot_id INTEGER, snapshot_date DATE, warehouse VARCHAR,"
        " tenant_key VARCHAR, balance INTEGER)"
    )
    for i, (d, w, b) in enumerate(SEED_ROWS):
        con.execute(
            "INSERT INTO gold.mart_inventory VALUES (?, ?, ?, ?, ?)", [i, d, w, "acme", b]
        )
    con.execute(
        "CREATE TABLE gold.dim_date AS "
        "SELECT unnest(generate_series(DATE '2024-01-01', DATE '2024-12-31',"
        " INTERVAL 1 DAY))::DATE AS date_day"
    )
    return con


def explain_sql(engine: MetricFlowEngine, **kwargs) -> str:
    return engine.explain(MetricFlowQueryRequest.create(**kwargs)).sql_statement.sql


def run_case(con, engine, label, expected, **kwargs) -> bool:
    sql = explain_sql(engine, **kwargs)
    rows = con.execute(sql).fetchall()
    ok = rows == expected
    print(f"\n=== {label}: {'PASS' if ok else 'FAIL'}")
    print(f"    got      {rows}")
    print(f"    expected {expected}")
    print("--- SQL ---")
    print(sql)
    return ok


def main() -> None:
    con = seed_duckdb()
    engine = build_engine(build_manifest())
    jan_1_to_3 = (
        "{{ TimeDimension('inventory__snapshot_date', 'day') }}"
        " BETWEEN '2024-01-01' AND '2024-01-03'"
    )
    results = []

    # (a) no time group-by, Jan 1-3 filter — global and warehouse-A-scoped variants.
    results.append(
        run_case(
            con, engine, "(a-global) balance, Jan 1-3, no group-by -> 130 (not 310)",
            [(130,)], metric_names=["inventory_balance"], where_constraints=[jan_1_to_3],
        )
    )
    results.append(
        run_case(
            con, engine, "(a-scoped) balance, Jan 1-3, warehouse A only -> 90 (not 270)",
            [(90,)], metric_names=["inventory_balance"],
            where_constraints=[jan_1_to_3, "{{ Dimension('inventory__warehouse') }} = 'A'"],
        )
    )

    # (b) by warehouse on Jan 3.
    results.append(
        run_case(
            con, engine, "(b) balance by warehouse, Jan 3 -> A=90, B=40",
            [("A", 90), ("B", 40)],
            metric_names=["inventory_balance"], group_by_names=["inventory__warehouse"],
            where_constraints=[
                "{{ TimeDimension('inventory__snapshot_date', 'day') }} = '2024-01-03'"
            ],
            order_by_names=["inventory__warehouse"],
        )
    )
    results.append(
        run_case(
            con, engine, "(b-total) balance, Jan 3, no group-by -> 130",
            [(130,)], metric_names=["inventory_balance"],
            where_constraints=[
                "{{ TimeDimension('inventory__snapshot_date', 'day') }} = '2024-01-03'"
            ],
        )
    )

    # (c) by month over three months — the issue #241 case.
    # DuckDB's DATE_TRUNC('month', DATE) yields TIMESTAMP, hence datetimes here.
    import datetime

    three_months = [
        (datetime.datetime(2024, 1, 1), 130),
        (datetime.datetime(2024, 2, 1), 75),
        (datetime.datetime(2024, 3, 1), 95),
    ]
    results.append(
        run_case(
            con, engine,
            "(c) balance by month, Jan..Mar -> THREE rows (Jan=130, Feb=75, Mar=95)",
            three_months,
            metric_names=["inventory_balance"],
            group_by_names=["inventory__snapshot_date__month"],
            order_by_names=["inventory__snapshot_date__month"],
        )
    )
    # (c') same grouping expressed through metric_time.
    results.append(
        run_case(
            con, engine,
            "(c') balance by metric_time__month -> THREE rows",
            three_months,
            metric_names=["inventory_balance"],
            group_by_names=["metric_time__month"],
            order_by_names=["metric_time__month"],
        )
    )

    print(f"\n{'ALL PASS' if all(results) else 'FAILURES PRESENT'}: "
          f"{sum(results)}/{len(results)} cases green")


if __name__ == "__main__":
    main()
