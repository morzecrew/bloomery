"""Drive a standalone MetricFlow against one semantic-corpus case.

No bloomery import, on purpose: the column measures what MetricFlow does for a
MetricFlow user, so the manifest is authored as YAML the way its documentation
describes and the only thing borrowed from this repository is the case's data.

    python comparisons/metricflow/run.py <case-dir> <bundle-dir> <request>...

A request is `metric[,metric...][/group-by[,group-by...]]`: one or more metrics
asked for together, optionally grouped, and ordered by the group-by so the rows
come back the same way every run. A plain metric name is a one-metric,
ungrouped request.

Prints MetricFlow's own validation verdict for the manifest, then per request
the rows the rendered SQL returns against the case's rows, or the refusal.

A bundle whose case needs a relation the case does not create — a view, a
pre-aggregate somebody built — carries it as `config/setup.sql`, run after the
case's own rows.
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


def load(case: pathlib.Path, bundle: pathlib.Path) -> duckdb.DuckDBPyConnection:
    """The case's own schema and rows, the bundle's setup if it has one, plus
    the time spine MetricFlow wants."""
    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA bronze")
    con.execute((case / "schema" / "schema.sql").read_text(encoding="utf-8"))
    con.execute((case / "data" / "rows.sql").read_text(encoding="utf-8"))
    setup = bundle / "config" / "setup.sql"
    if setup.exists():
        con.execute(setup.read_text(encoding="utf-8"))
    con.execute(
        "CREATE TABLE bronze.dim_date AS SELECT CAST(range AS DATE) AS date_day "
        "FROM range(DATE '2025-01-01', DATE '2025-04-01', INTERVAL 1 DAY)"
    )
    return con


def main() -> int:
    case, bundle, requests = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3:]
    con = load(case, bundle)

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

    for request in requests:
        print(f"### {request}")
        metrics, _, group_by = request.partition("/")
        groups = group_by.split(",") if group_by else []
        try:
            result = engine.explain(
                MetricFlowQueryRequest.create(
                    metric_names=metrics.split(","),
                    group_by_names=groups or None,
                    order_by_names=groups or None,
                )
            )
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
