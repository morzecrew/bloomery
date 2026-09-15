"""Drive a standalone MetricFlow against one semantic-corpus case.

No bloomery import, on purpose: the column measures what MetricFlow does for a
MetricFlow user, so the manifest is authored as YAML the way its documentation
describes and the only thing borrowed from this repository is the case's data.

    python comparisons/metricflow/run.py <case-dir> <bundle-dir> <metric>...

Prints MetricFlow's own validation verdict for the manifest, then per metric the
number the rendered SQL returns against the case's rows, or the refusal.
"""

from __future__ import annotations

import pathlib
import sys

import duckdb
from metricflow.engine.metricflow_engine import MetricFlowEngine, MetricFlowQueryRequest
from metricflow.protocols.sql_client import SqlClient, SqlEngine
from metricflow.sql.render.duckdb_renderer import DuckDbSqlPlanRenderer
from metricflow_semantic_interfaces.parsing.dir_to_model import (
    parse_directory_of_yaml_files_to_semantic_manifest,
)
from metricflow_semantic_interfaces.validations.semantic_manifest_validator import (
    SemanticManifestValidator,
)
from metricflow_semantics.model.semantic_manifest_lookup import SemanticManifestLookup


class RenderOnlySqlClient(SqlClient):
    """The `SqlClient` MetricFlow's engine requires, stubbed to render only.

    MetricFlow executes through a warehouse connection it owns; this asks it
    for the SQL and runs that SQL separately, so the number below is produced
    by MetricFlow's plan and nothing else.
    """

    @property
    def sql_engine_type(self) -> SqlEngine:
        return SqlEngine.DUCKDB

    @property
    def sql_plan_renderer(self) -> DuckDbSqlPlanRenderer:
        return DuckDbSqlPlanRenderer()

    def query(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError("render-only")

    def execute(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError("render-only")

    def dry_run(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError("render-only")

    def close(self) -> None:
        pass

    def render_bind_parameter_key(self, bind_parameter_key: object) -> str:
        return f"${bind_parameter_key}"


def load(case: pathlib.Path) -> duckdb.DuckDBPyConnection:
    """The case's own schema and rows, plus the time spine MetricFlow wants."""
    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA bronze")
    con.execute((case / "schema" / "schema.sql").read_text(encoding="utf-8"))
    con.execute((case / "data" / "rows.sql").read_text(encoding="utf-8"))
    con.execute(
        "CREATE TABLE bronze.dim_date AS SELECT CAST(range AS DATE) AS date_day "
        "FROM range(DATE '2025-01-01', DATE '2025-04-01', INTERVAL 1 DAY)"
    )
    return con


def main() -> int:
    case, bundle, metrics = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3:]
    con = load(case)

    manifest = parse_directory_of_yaml_files_to_semantic_manifest(
        str(bundle / "config")
    ).semantic_manifest
    issues = SemanticManifestValidator().validate_semantic_manifest(manifest)
    print(
        f"SemanticManifestValidator: {len(issues.errors)} error(s), "
        f"{len(issues.warnings)} warning(s)"
    )
    for issue in (*issues.errors, *issues.warnings):
        print(f"  {issue}")

    engine = MetricFlowEngine(
        semantic_manifest_lookup=SemanticManifestLookup(manifest),
        sql_client=RenderOnlySqlClient(),
    )

    for metric in metrics:
        print(f"### {metric}")
        try:
            result = engine.explain(MetricFlowQueryRequest.create(metric_names=[metric]))
        except Exception as exc:  # the refusal is the measurement
            print(f"  refused when planning: {type(exc).__name__}: {exc}")
            continue
        statement = result.sql_statement
        sql = getattr(statement, "sql", statement)
        try:
            print(f"  -> {con.execute(sql).fetchall()}")
        except Exception as exc:  # the refusal is the measurement
            print(f"  refused when executing: {type(exc).__name__}: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
