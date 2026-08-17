"""One spec set, three targets, each one actually run.

    uv run python examples/targets/run.py            # SQLMesh + dbt + the planner
    just demo                                        # the same, plus Cube

bloomery claims three targets. The test suite proves the *artifacts* — goldens
compare bytes, and the e2e tier checks each framework accepts them. What no test
shows a person is the thing running: dbt actually building tables, Cube actually
answering a question, the planner's SQL actually returning a number.

So this example takes one project — a small retailer with three real sources —
and drives it all the way through each target:

1. **Seed** bronze from `seed/`: a CRM CSV export, a product-catalogue CSV, and
   a storefront's newline-delimited JSON events. Nothing is cleaned on the way
   in; bronze holds what the sources sent.
2. **Cleanse**, and show it. The mappings declare transform chains — trim,
   lower, `enum_map`, `nullif`, `strip_prefix`, cents-to-currency — and the
   run prints the same rows before and after so the chains are visible as an
   effect rather than as YAML.
3. **SQLMesh** — compile, `sqlmesh plan --auto-apply`, query the mart.
4. **dbt** — compile, `dbt build`, query the mart dbt built.
5. **Compare** the two marts row for row. Same specs, two frameworks, one
   answer — which is the port abstraction's whole claim, stated as a number
   rather than as prose.
6. **Plan metric requests** and *execute* them, including a ratio metric that
   is never stored and is recomputed from its additive parts at whatever grain
   the question is asked at.

Cube needs a container and lives in `just cube`; see the README.

**Each framework gets its own copy of the warehouse**, seeded identically. Both
place their mart at `gold.mart_orders`, so sharing one file would mean whichever
ran second silently overwrote the other and the comparison would be measuring
one framework twice. Separate files are what make step 5 mean anything.
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
SEED = HERE / "seed"
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

#: The bronze layer, built from `seed/` exactly as the sources shipped it.
#:
#: `all_varchar=true` on the CSVs is the honest setting, not a convenience:
#: bronze is landed text, and every cast in this project belongs to a mapping's
#: declared transform chain rather than to whatever a loader guessed. Letting
#: DuckDB infer `list_price_cents` as an integer would quietly do a mapping's
#: job and hide the ' 1250' that the `trim` step exists for.
#:
#: The events land the same way. `read_json_objects` hands back each line's raw
#: JSON text; the four top-level keys become columns and `payload` stays a JSON
#: *string* — which is what a webhook landing table actually looks like, and
#: what makes `$.payload.totals.gross_cents` in the mapping a JSON extraction
#: off a physical column rather than a pre-shredded field.
SEED_SQL = """
CREATE SCHEMA IF NOT EXISTS bronze;

CREATE OR REPLACE TABLE bronze.crm__customers AS
  SELECT * FROM read_csv('{seed}/customers.csv', header = true, all_varchar = true);

CREATE OR REPLACE TABLE bronze.catalogue__products AS
  SELECT * FROM read_csv('{seed}/products.csv', header = true, all_varchar = true);

CREATE OR REPLACE TABLE bronze.shop__order_events AS
  SELECT
    json_extract_string(json, '$.event_id')    AS event_id,
    json_extract_string(json, '$.order_ref')   AS order_ref,
    json_extract_string(json, '$.occurred_at') AS occurred_at,
    json_extract_string(json, '$.payload')     AS payload
  FROM read_json_objects('{seed}/order_events.jsonl', format = 'newline_delimited');
"""

MART = (
    "SELECT ordered_month, customer_segment, product_category, "
    "count(*) AS orders, sum(quantity) AS units, sum(amount) AS revenue "
    "FROM gold.mart_orders GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"
)

#: (headline, bronze query, silver query) — the same rows, either side of the
#: transform chains. Printed so the cleansing is visible as an effect.
CLEANSING = (
    (
        "customers: five spellings of two segments, and an email nobody can join on",
        "SELECT customer_id, email, segment, marketing_source "
        "FROM bronze.crm__customers ORDER BY customer_id",
        "SELECT customer_id, email, segment, marketing_source "
        "FROM silver.customer ORDER BY customer_id",
    ),
    (
        "products: prices in integer cents, categories in three shift keys",
        "SELECT sku, category, list_price_cents FROM bronze.catalogue__products ORDER BY sku",
        "SELECT sku, category, list_price FROM silver.product ORDER BY sku",
    ),
    (
        "orders: one JSON payload column in, eight typed columns out",
        "SELECT order_ref, payload FROM bronze.shop__order_events ORDER BY order_ref LIMIT 2",
        "SELECT order_id, customer_id, sku, quantity, amount, ship_country, channel, note "
        'FROM silver."order" ORDER BY order_id LIMIT 2',
    ),
    (
        "channels: five raw spellings and one empty string, folded to four names",
        "SELECT DISTINCT payload ->> '$.channel' AS raw "
        "FROM bronze.shop__order_events ORDER BY raw",
        'SELECT DISTINCT channel FROM silver."order" ORDER BY channel',
    ),
)

#: (metrics, dimensions, what the request is for).
REQUESTS = (
    (
        ("revenue", "order_count"),
        ("ordered_month", "customer_segment"),
        "two additive metrics, grouped two ways",
    ),
    (
        ("average_order_value",),
        ("product_category",),
        "a ratio: never stored, recomputed here from revenue and order_count",
    ),
)


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
    """Compile to one target and write the artifacts. The only bloomery step.

    Whatever an earlier compile left in the same places is removed first.
    Writing without sweeping is how a deleted spec keeps its model: SQLMesh and
    dbt both plan whatever is in the project directory, so a `.sql` file whose
    spec is gone is silently still part of the project and still gets built.
    Only the paths a compile *owns* are swept — the framework's own `target/`
    and `logs/` directories share this root and are none of our business.
    """
    artifacts = compile_project(project, target=target, dialect="duckdb", catalog=catalog)
    written = {into / artifact.path for artifact in artifacts}
    for root in sorted({into / Path(artifact.path).parts[0] for artifact in artifacts}):
        existing = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
        for stale in existing:
            if stale not in written:
                stale.unlink()
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
        connection.execute(SEED_SQL.format(seed=SEED.as_posix()))


def show(database: Path, title: str, query: str) -> list[tuple[object, ...]]:
    result = rows(database, query)
    print(f"\n  {title}")
    for row in result:
        print(f"    {row}")
    return result


def show_cleansing(database: Path) -> None:
    """The transform chains, printed as an effect rather than as YAML."""
    for headline, before, after in CLEANSING:
        print(f"\n  {headline}")
        for label, query in (("bronze", before), ("silver", after)):
            print(f"    {label}")
            for row in rows(database, query):
                print(f"      {row}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    project, catalog = load_specs()

    print("seeding bronze from seed/ into a fresh warehouse for each target")
    seed(SQLMESH_DB)
    seed(DBT_DB)

    print("\n─── SQLMesh " + "─" * 55)
    sqlmesh_root = OUT / "sqlmesh"
    print(f"  compiled {emit(project, catalog, Target.SQLMESH, sqlmesh_root)} artifacts")
    (sqlmesh_root / "config.yaml").write_text(SQLMESH_CONFIG.format(database=SQLMESH_DB))
    shell("sqlmesh", "plan", "--auto-apply", "--no-prompts", cwd=sqlmesh_root)
    from_sqlmesh = show(SQLMESH_DB, "gold.mart_orders, built by SQLMesh", MART)

    print("\n─── what the mappings cleaned " + "─" * 37)
    show_cleansing(SQLMESH_DB)

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
    ir = build_project_ir(project, catalog=catalog)
    for metrics, dimensions, note in REQUESTS:
        print(f"\n  {', '.join(metrics)} by {', '.join(dimensions)} — {note}")
        plan = planner.plan(
            ir, MetricRequest(metrics=metrics, dimensions=dimensions), dialect="duckdb"
        )
        print(textwrap.indent(plan.sql, "    "))
        print("    executed against the warehouse the targets just built:")
        for row in rows(SQLMESH_DB, plan.sql):
            print(f"      {row}")


if __name__ == "__main__":
    main()
