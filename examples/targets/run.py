"""One spec set, three targets, each one actually run.

    uv run python examples/targets/run.py            # SQLMesh + dbt + the planner
    just demo                                        # the same, plus Cube

bloomery claims three targets. The test suite proves the *artifacts* — goldens
compare bytes, and the e2e tier checks each framework accepts them. What no test
shows a person is the thing running: dbt actually building tables, Cube actually
answering a question, the planner's SQL actually returning a number.

So this example takes one project and drives it all the way through each target
against the same DuckDB file:

1. **Seed** three bronze tables — the sources the mappings read.
2. **SQLMesh** — compile, `sqlmesh plan --auto-apply`, query the mart.
3. **dbt** — compile, `dbt build`, query the mart dbt built.
4. **Compare** the two marts row for row. Same specs, two frameworks, one
   answer — which is the port abstraction's whole claim, stated as a number
   rather than as prose.
5. **Plan a metric request** and *execute* it, so the planner is shown serving
   a question rather than printing SQL nobody runs.

Cube needs a container and lives in `just cube`; see the README.

**Each framework gets its own copy of the warehouse**, seeded identically. Both
place their mart at `gold.mart_orders`, so sharing one file would mean whichever
ran second silently overwrote the other and the comparison would be measuring
one framework twice. Separate files are what make step 4 mean anything.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import duckdb

from bloomery import (
    LruManifestHydrator,
    MetricFlowPlanner,
    MetricRequest,
    Target,
    build_project_ir,
    compile_project,
    load_catalog,
    load_project,
)
from bloomery.naming import DefaultNaming
from bloomery.spec import Catalog, Project

HERE = Path(__file__).parent
SPECS = HERE / "specs"
OUT = HERE / "out"
SQLMESH_DB = OUT / "warehouse-sqlmesh.duckdb"
DBT_DB = OUT / "warehouse-dbt.duckdb"

SQLMESH_CONFIG = """\
gateways:
  local:
    connection:
      type: duckdb
      database: {database}
default_gateway: local
model_defaults:
  dialect: duckdb
  start: 2024-01-01
disable_anonymized_analytics: true
"""

# bloomery emits no profiles.yml, deliberately: a profile carries hosts and
# credentials, and the compiler stays free of environment (RFC 0003). Supplying
# one is the caller's job — here, three lines.
DBT_PROFILES = """\
bloomery:
  target: local
  outputs:
    local:
      type: duckdb
      path: '{database}'
      schema: dbt
"""

#: The bronze layer both frameworks read. Column names are the ones the mappings
#: name in their `from:` — that correspondence is the entire contract between a
#: source table and a mapping.
SEED = """
CREATE SCHEMA IF NOT EXISTS bronze;
CREATE OR REPLACE TABLE bronze.crm__customers AS
  SELECT * FROM (VALUES
    ('C-001', 'consumer'), ('C-002', 'business'), ('C-003', 'consumer')
  ) AS t(id, segment);
CREATE OR REPLACE TABLE bronze.shop__orders AS
  SELECT * FROM (VALUES
    ('O-1', 'C-001', 42.50, DATE '2024-01-12'),
    ('O-2', 'C-002', 17.25, DATE '2024-01-19'),
    ('O-3', 'C-001',  8.00, DATE '2024-02-03'),
    ('O-4', 'C-003', 99.99, DATE '2024-02-27')
  ) AS t(id, customer_id, amount, created_at);
"""


def load_specs() -> tuple[Project, Catalog]:
    catalog = load_catalog((SPECS / "catalog.yaml").read_text())
    project = load_project(
        {
            path.name: path.read_text()
            for path in sorted(SPECS.glob("*.yaml"))
            if path.name != "catalog.yaml"
        }
    )
    return project, catalog


def emit(project: Project, catalog: Catalog, target: Target, into: Path) -> int:
    """Compile to one target and write the artifacts. The only bloomery step."""
    artifacts = compile_project(project, target=target, dialect="duckdb", catalog=catalog)
    for artifact in artifacts:
        destination = into / artifact.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(artifact.content)
    return len(artifacts)


def shell(executable: str, *args: str, cwd: Path) -> None:
    """Run a framework CLI, echoing the command. Failure is fatal: a target that
    cannot build the project is the finding, not something to summarize."""
    print(f"  $ {executable} {' '.join(args)}")
    binary = Path(sys.executable).with_name(executable)
    result = subprocess.run(  # noqa: S603 — fixed argv, no shell
        [str(binary), *args], cwd=cwd, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        print(result.stdout or "", result.stderr or "", sep="\n")
        message = f"{executable} {args[0]} failed ({result.returncode})"
        raise SystemExit(message)


def rows(database: Path, query: str) -> list[tuple[object, ...]]:
    with duckdb.connect(str(database)) as connection:
        return connection.execute(query).fetchall()


def seed(database: Path) -> None:
    """A fresh warehouse holding only the bronze the mappings read."""
    database.unlink(missing_ok=True)
    with duckdb.connect(str(database)) as connection:
        connection.execute(SEED)


def show(database: Path, title: str, query: str) -> list[tuple[object, ...]]:
    result = rows(database, query)
    print(f"\n  {title}")
    for row in result:
        print(f"    {row}")
    return result


MART = (
    "SELECT ordered_month, customer_segment, count(*) AS orders, "
    "sum(amount) AS revenue FROM gold.mart_orders GROUP BY 1, 2 ORDER BY 1, 2"
)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    project, catalog = load_specs()

    print("seeding bronze into a fresh warehouse for each target")
    seed(SQLMESH_DB)
    seed(DBT_DB)

    print("\n─── SQLMesh " + "─" * 55)
    sqlmesh_root = OUT / "sqlmesh"
    print(f"  compiled {emit(project, catalog, Target.SQLMESH, sqlmesh_root)} artifacts")
    (sqlmesh_root / "config.yaml").write_text(SQLMESH_CONFIG.format(database=SQLMESH_DB))
    shell("sqlmesh", "plan", "--auto-apply", "--no-prompts", cwd=sqlmesh_root)
    from_sqlmesh = show(SQLMESH_DB, "gold.mart_orders, built by SQLMesh", MART)

    print("\n─── dbt " + "─" * 59)
    dbt_root = OUT / "dbt"
    print(f"  compiled {emit(project, catalog, Target.DBT, dbt_root)} artifacts")
    (dbt_root / "profiles.yml").write_text(DBT_PROFILES.format(database=DBT_DB))
    shell(
        "dbt", "build", "--project-dir", str(dbt_root), "--profiles-dir", str(dbt_root),
        cwd=dbt_root,
    )
    from_dbt = show(DBT_DB, "gold.mart_orders, built by dbt", MART)

    print("\n─── the two agree " + "─" * 49)
    if from_sqlmesh == from_dbt:
        print(f"  identical: {len(from_sqlmesh)} rows, same values")
        print("  one spec set, two frameworks, one answer — which is what a")
        print("  dialect port is for, measured rather than asserted")
    else:
        print(f"  MISMATCH\n    sqlmesh: {from_sqlmesh}\n    dbt:     {from_dbt}")
        raise SystemExit("the two targets disagree")

    print("\n─── Cube " + "─" * 58)
    cube_root = OUT / "cube"
    print(f"  compiled {emit(project, catalog, Target.CUBE, cube_root)} artifacts")
    print("  a semantic model over the mart, for `just cube` to serve")

    print("\n─── the planner " + "─" * 51)
    naming = DefaultNaming()
    planner = MetricFlowPlanner(LruManifestHydrator(naming), naming=naming)
    plan = planner.plan(
        build_project_ir(project, catalog=catalog),
        MetricRequest(metrics=("revenue",), dimensions=("ordered_month",)),
        dialect="duckdb",
    )
    print(textwrap.indent(plan.sql, "  "))
    print("  executed against the warehouse the targets just built:")
    for row in rows(SQLMESH_DB, plan.sql):
        print(f"    {row}")


if __name__ == "__main__":
    main()
