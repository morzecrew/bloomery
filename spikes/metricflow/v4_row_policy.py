"""M4.5 verification task V4 — does a row policy reach EVERY scan of the mart?

Generates SQL for (a) a RATIO metric and (b) the semi-additive metric, each with

    where_constraints=["{{ Dimension('<entity>__tenant_key') }} = 'acme'"]

then parses the SQL with sqlglot and checks, per physical scan of the mart
relation, whether the tenant predicate is applied at or below the first
aggregation over that scan (a predicate applied only above an aggregation would
mean the aggregate — e.g. the MAX(snapshot_date) of the semi-additive plan — was
computed over other tenants' rows: the security defect the pivot doc warns
about).

Also exercises the pivot's escape-hatch question: `PydanticNodeRelation` has no
`sql` body field (fields: alias, schema_name, database, relation_name), so a
tenant-filtered node relation must point at a per-tenant filtered VIEW by name —
demonstrated executable at the end.

How to run (spike env lives OUTSIDE the repo; see spike.py header):

    uv run --project <spike-env-dir> python spikes/metricflow/v4_row_policy.py
"""

from __future__ import annotations

import sqlglot
from sqlglot import expressions as exp

from metricflow.engine.metricflow_engine import MetricFlowEngine, MetricFlowQueryRequest
from metricflow.protocols.sql_client import SqlEngine
from metricflow.sql.render.duckdb_renderer import DuckDbSqlPlanRenderer

from metricflow_semantic_interfaces.implementations.elements.dimension import PydanticDimension
from metricflow_semantic_interfaces.implementations.node_relation import PydanticNodeRelation
from metricflow_semantic_interfaces.transformations.semantic_manifest_transformer import (
    PydanticSemanticManifestTransformer,
)
from metricflow_semantic_interfaces.type_enums import DimensionType
from metricflow_semantics.model.semantic_manifest_lookup import SemanticManifestLookup

import spike
import v2_semi_additive
from spike import RenderOnlySqlClient

POLICY_VALUE = "acme"
POLICY_COLUMN = "tenant_key"


def build_engine(manifest) -> MetricFlowEngine:
    manifest = PydanticSemanticManifestTransformer.transform(manifest)
    return MetricFlowEngine(
        semantic_manifest_lookup=SemanticManifestLookup(manifest),
        sql_client=RenderOnlySqlClient(SqlEngine.DUCKDB, DuckDbSqlPlanRenderer()),
    )


def where_has_policy(select: exp.Select) -> bool:
    """True if this SELECT's WHERE compares a *tenant_key column to the policy value."""
    where = select.args.get("where")
    if where is None:
        return False
    for eq in where.find_all(exp.EQ):
        col, lit = eq.left, eq.right
        if isinstance(lit, exp.Column) and isinstance(col, exp.Literal):
            col, lit = lit, col
        if (
            isinstance(col, exp.Column)
            and col.name.endswith(POLICY_COLUMN)
            and isinstance(lit, exp.Literal)
            and lit.this == POLICY_VALUE
        ):
            return True
    return False


def select_aggregates(select: exp.Select) -> bool:
    """True if this SELECT aggregates (GROUP BY or aggregate functions in projections)."""
    if select.args.get("group"):
        return True
    return any(
        isinstance(node, exp.AggFunc)
        for projection in select.expressions
        for node in projection.walk()
    )


def audit_scans(sql: str, mart_relation: str) -> list[tuple[str, bool]]:
    """For every scan of ``mart_relation``: is the policy applied at or below the
    first aggregation over that scan?  Returns [(scan description, protected)]."""
    tree = sqlglot.parse_one(sql, dialect="duckdb")
    verdicts: list[tuple[str, bool]] = []
    for table in tree.find_all(exp.Table):
        qualified = ".".join(p.name for p in (table.args.get("db"), table.this) if p is not None)
        if qualified != mart_relation:
            continue
        protected = False
        node = table
        while True:
            select = node.find_ancestor(exp.Select)
            if select is None:
                break
            if where_has_policy(select):
                protected = True
                break
            if select_aggregates(select):
                # Aggregation computed over rows never filtered by the policy.
                break
            node = select
        alias = table.args.get("alias")
        verdicts.append((f"{qualified} AS {alias.name if alias else '?'}", protected))
    return verdicts


def report(label: str, sql: str, mart_relation: str) -> bool:
    verdicts = audit_scans(sql, mart_relation)
    all_ok = all(ok for _, ok in verdicts)
    print(f"\n=== {label}")
    print(f"    scans of {mart_relation}: {len(verdicts)}")
    for desc, ok in verdicts:
        print(f"      {'PROTECTED  ' if ok else 'UNPROTECTED'} {desc}")
    print(f"    verdict: {'PASS' if all_ok else 'FAIL — predicate missing from an inner scan'}")
    print("--- SQL ---")
    print(sql)
    return all_ok


def main() -> None:
    results = []

    # (a) RATIO metric. Add tenant_key to the order_items model first.
    ratio_manifest = spike.build_manifest()
    ratio_manifest.semantic_models[0].dimensions.append(
        PydanticDimension(name=POLICY_COLUMN, type=DimensionType.CATEGORICAL)
    )
    engine = build_engine(ratio_manifest)
    sql = engine.explain(
        MetricFlowQueryRequest.create(
            metric_names=["avg_order_value"],
            group_by_names=["order_item__carrier"],
            where_constraints=[
                f"{{{{ Dimension('order_item__{POLICY_COLUMN}') }}}} = '{POLICY_VALUE}'"
            ],
        )
    ).sql_statement.sql
    results.append(report("(a) RATIO avg_order_value by carrier + tenant policy",
                          sql, "gold.mart_order_items"))

    # (b) semi-additive metric, grouped by month (the multi-scan MAX-join plan).
    engine = build_engine(v2_semi_additive.build_manifest())
    sql = engine.explain(
        MetricFlowQueryRequest.create(
            metric_names=["inventory_balance"],
            group_by_names=["inventory__snapshot_date__month"],
            where_constraints=[
                f"{{{{ Dimension('inventory__{POLICY_COLUMN}') }}}} = '{POLICY_VALUE}'"
            ],
        )
    ).sql_statement.sql
    results.append(report("(b) SEMI-ADDITIVE inventory_balance by month + tenant policy",
                          sql, "gold.mart_inventory"))

    # (b') same, ungrouped (the V2 (a)-shape plan).
    sql = engine.explain(
        MetricFlowQueryRequest.create(
            metric_names=["inventory_balance"],
            where_constraints=[
                f"{{{{ Dimension('inventory__{POLICY_COLUMN}') }}}} = '{POLICY_VALUE}'"
            ],
        )
    ).sql_statement.sql
    results.append(report("(b') SEMI-ADDITIVE inventory_balance ungrouped + tenant policy",
                          sql, "gold.mart_inventory"))

    # Escape hatch: node_relation pointing at a per-tenant filtered VIEW.
    import duckdb

    con = v2_semi_additive.seed_duckdb()
    con.execute(
        "CREATE VIEW gold.mart_inventory_acme AS "
        "SELECT * FROM gold.mart_inventory WHERE tenant_key = 'acme'"
    )
    filtered = v2_semi_additive.build_manifest()
    filtered.semantic_models[0].node_relation = PydanticNodeRelation(
        alias="mart_inventory_acme", schema_name="gold"
    )
    engine = build_engine(filtered)
    sql = engine.explain(
        MetricFlowQueryRequest.create(
            metric_names=["inventory_balance"],
            group_by_names=["inventory__snapshot_date__month"],
        )
    ).sql_statement.sql
    rows = con.execute(sql).fetchall()
    print("\n=== escape hatch: node_relation -> per-tenant filtered view")
    print("    PydanticNodeRelation fields:",
          list(PydanticNodeRelation.__fields__.keys()), "(no `sql` body field)")
    print(f"    view-backed manifest accepted; by-month result: {rows}")

    print(f"\n{'ALL PASS' if all(results) else 'FAILURES PRESENT'}: "
          f"{sum(results)}/{len(results)} policy audits green")


if __name__ == "__main__":
    main()
