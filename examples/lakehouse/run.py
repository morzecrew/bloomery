"""Compile the specs in this directory and build them into the lakehouse.

    docker compose -f examples/lakehouse/compose.yaml up -d --wait
    uv run python examples/lakehouse/seed.py \\
        | docker exec -i bloomery-lakehouse-trino-1 trino -f /dev/stdin
    uv run python examples/lakehouse/run.py

What happens, in order:

1. The eight spec documents are loaded and compiled to SQLMesh artifacts for the
   ``trino`` dialect. That is the whole of bloomery's involvement — a pure
   function from YAML strings to file-shaped artifacts, no warehouse in sight.
2. The artifacts are written into ``out/`` beside a SQLMesh ``config.yaml``
   pointing at the Trino container, making an ordinary SQLMesh project.
3. ``sqlmesh plan --auto-apply`` builds it. Silver models, the wide mart, the
   date dimension, the reject table and the quality mart all become Iceberg
   tables through Lakekeeper.
4. The generated audits run as part of that plan — including the **blocking**
   collision audit that holds the two shops' key sets disjoint. The README shows
   how to make it fire.
5. Every source is printed twice, before and after its mapping, so the declared
   transform chains are visible as an effect rather than as YAML.
6. A last set of queries prints what landed, so the merge, the dedupe, the
   quality flags and the diverted row are visible rather than asserted.

Everything after step 1 is done by **shelling out to the `sqlmesh` CLI**, not by
importing it. Two reasons: this file's imports then stay exactly what
``quickstart/run.py``'s are — bloomery and the standard library — so the
dependency gate keeps meaning what it means; and every command printed below is
one you could have typed yourself, which is the point of an example.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from textwrap import indent

from bloomery import Target, compile_project, load_catalog, load_project

HERE = Path(__file__).parent
SPECS = HERE / "specs"
OUT = HERE / "out"

#: The emitted project is ordinary SQLMesh — nothing here is bloomery-specific.
#: ``catalog: iceberg`` is what makes an unqualified ``silver.order_line`` land
#: in the Iceberg catalog Lakekeeper serves. SQLMesh's own state goes to a local
#: DuckDB file: that is bookkeeping about plans rather than warehouse data, and
#: keeping it local means the stack needs one less published port.
#:
#: ``timezone: UTC`` is the line worth explaining. Iceberg stores a bloomery
#: ``timestamp`` as ``timestamp(6) with time zone``, so writing a zoneless value
#: into it has to promote it somehow — and the zone it promotes with is the
#: **session's**, which the client takes from the machine it runs on. Left
#: unset, this example prints different instants in Berlin and in Bengaluru
#: from identical specs and identical data. The compiler is deterministic; a
#: connection is still a place a timezone can walk in, so it is pinned here.
CONFIG = """\
gateways:
  lakehouse:
    connection:
      type: trino
      host: localhost
      port: 8080
      user: bloomery
      catalog: iceberg
      http_scheme: http
      timezone: UTC
    state_connection:
      type: duckdb
      database: {state}
default_gateway: lakehouse
model_defaults:
  dialect: trino
  start: 2026-01-01
disable_anonymized_analytics: true
"""

#: (caption, bronze query, silver query) — the same rows either side of the
#: mappings, so the declared transform chains are visible as an effect.
BEFORE_AND_AFTER = (
    (
        "the CRM: five spellings of two segments, an email nobody can join on,\n"
        "  a country code with three letters, and one customer sent twice",
        "SELECT customer_id, email_address, segment, billing_country, marketing_source "
        "FROM iceberg.bronze.crm__customers ORDER BY customer_id, _source_row_id",
        "SELECT customer_id, email, segment, billing_country, marketing_source "
        "FROM iceberg.silver.customer ORDER BY customer_id",
    ),
    (
        "the catalogue: prices in integer cents, categories in three shift keys",
        "SELECT sku, category, list_price_cents FROM iceberg.bronze.catalogue__products "
        "ORDER BY sku",
        "SELECT sku, category, list_price FROM iceberg.silver.product ORDER BY sku",
    ),
    (
        "the platform shop: one nested JSON payload in, eight typed columns out",
        "SELECT order_id, position, payload FROM iceberg.bronze.shopify__order_lines "
        "ORDER BY order_id, position LIMIT 2",
        "SELECT order_id, line_no, sku, quantity, amount, discount, gift_note "
        "FROM iceberg.silver.order_line WHERE _source = 'shopify__order_lines' "
        "ORDER BY order_id, line_no LIMIT 2",
    ),
    (
        "the legacy shop: a flat CSV export, lower-case SKUs, currency not cents",
        "SELECT order_number, item_index, product_sku, line_amount, placed_at "
        "FROM iceberg.bronze.woo__order_lines ORDER BY order_number, item_index LIMIT 3",
        "SELECT order_id, line_no, sku, amount, ordered_at FROM iceberg.silver.order_line "
        "WHERE _source = 'woo__order_lines' ORDER BY order_id, line_no LIMIT 3",
    ),
)

SHOW_WHAT_LANDED = (
    (
        "the merge: one entity, two shops, and the _source column that says which",
        "SELECT _source, count(*) AS lines, sum(amount) AS amount, "
        "min(ordered_at) AS earliest FROM iceberg.silver.order_line "
        "GROUP BY _source ORDER BY _source",
    ),
    (
        "gift_note is mapped by one shop only — the other branch fills a typed NULL",
        "SELECT _source, count(gift_note) AS with_note, count(*) AS lines "
        "FROM iceberg.silver.order_line GROUP BY _source ORDER BY _source",
    ),
    (
        "the merge cleans: the legacy shop wrote 'two' where a quantity goes, and the\n"
        "  reject row names the shop it came from — one reject table, both branches",
        "SELECT source_relation, failed_rules, key_values FROM "
        "iceberg.silver.order_line__reject",
    ),
    (
        "one rule, two shops, each branch comparing against the paths it reads:\n"
        "  the platform shop's lines are untouched by the legacy shop's bad row",
        "SELECT _source, count(*) AS lines, sum(amount) AS amount "
        "FROM iceberg.silver.order_line GROUP BY _source ORDER BY _source",
    ),
    (
        "C-002 arrived in two loads; dedupe kept the later revision and only that one",
        "SELECT customer_id, email, segment, updated_at FROM iceberg.silver.customer "
        "WHERE customer_id = 'C-002'",
    ),
    (
        "the quality rules flagged rows rather than dropping them — C-003's email\n"
        "  and C-006's three-letter country code are still here, and still counted",
        "SELECT customer_id, email, _quality_ok, _quality_flags "
        "FROM iceberg.silver.customer ORDER BY customer_id",
    ),
    (
        "a row that could not be coerced was diverted, not silently nulled",
        "SELECT failed_rules, key_values, source_relation FROM "
        "iceberg.silver.customer__reject",
    ),
    (
        "and diverting it has a visible price: C-005's order line keeps its money\n"
        "  and loses its segment, because the customer it points at is not there",
        "SELECT order_id, customer_id, customer_segment, amount "
        "FROM iceberg.gold.mart_order_lines WHERE customer_segment IS NULL",
    ),
    (
        "the quality mart: one row per rule, plus an (entity) row holding the totals\n"
        "  — every rule the entity carries, whether or not it caught anything today",
        "SELECT rule, disposition, rows_evaluated AS seen, rows_failed AS failed, "
        "rows_quarantined AS held, rows_deduped AS deduped "
        "FROM iceberg.gold.mart_data_quality ORDER BY entity, rule",
    ),
    (
        "the wide mart, joined through both relationships and bucketed by month",
        "SELECT ordered_month, customer_segment, product_category, count(*) AS lines, "
        "sum(quantity) AS units, sum(amount) AS revenue "
        "FROM iceberg.gold.mart_order_lines "
        "GROUP BY ordered_month, customer_segment, product_category ORDER BY 1, 2, 3",
    ),
)


def compile_to(out: Path) -> list[str]:
    """Specs in, SQLMesh project out. The only bloomery step in this file.

    Whatever an earlier compile left in the same places is removed first.
    Writing without sweeping is how a deleted spec keeps its model: SQLMesh
    plans whatever is in the project directory, so a `.sql` file whose spec is
    gone is silently still part of the project and still gets built — and the
    audit that came with it still runs. Only the directories a compile *owns*
    are swept; `config.yaml` and SQLMesh's `state.db` live in this same root
    and are not artifacts.
    """
    catalog = load_catalog((SPECS / "catalog.yaml").read_text())
    project = load_project(
        {
            path.name: path.read_text()
            for path in sorted(SPECS.glob("*.yaml"))
            if path.name != "catalog.yaml"
        }
    )
    artifacts = compile_project(project, target=Target.SQLMESH, dialect="trino", catalog=catalog)
    written = {out / artifact.path for artifact in artifacts}
    for root in sorted({out / Path(artifact.path).parts[0] for artifact in artifacts}):
        existing = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
        for stale in existing:
            if stale not in written:
                stale.unlink()
    for artifact in artifacts:
        destination = out / artifact.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(artifact.content)
    return [artifact.path for artifact in artifacts]


def sqlmesh(*args: str) -> str:
    """Run the SQLMesh CLI inside the emitted project, echoing the command so
    the reader can run it themselves. Failure is fatal and loud: a plan that
    fails its audits is the interesting case, not one to swallow."""
    print(f"\n$ sqlmesh {' '.join(args)}")
    # The console script beside this interpreter, so `uv run` and an activated
    # virtualenv both reach the same SQLMesh. `python -m sqlmesh.cli.main`
    # imports cleanly and invokes nothing, which fails silently.
    executable = Path(sys.executable).with_name("sqlmesh")
    result = subprocess.run(  # noqa: S603 — fixed argv, no shell
        [str(executable), *args],
        cwd=OUT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stdout or "", result.stderr or "", sep="\n")
        message = f"sqlmesh {args[0]} failed with exit code {result.returncode}"
        raise SystemExit(message)
    return result.stdout


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    written = compile_to(OUT)
    print(f"compiled {len(written)} artifacts into examples/lakehouse/out/")
    for path in written:
        print(f"  {path}")

    (OUT / "config.yaml").write_text(CONFIG.format(state=OUT / "state.db"))

    print("\nbuilding it — the generated audits run as part of this plan")
    sqlmesh("plan", "--auto-apply", "--no-prompts")

    print("\n" + "=" * 72)
    print("what the mappings cleaned — the same rows, either side of the chains")
    print("=" * 72)
    for caption, before, after in BEFORE_AND_AFTER:
        print(f"\n-- {caption}")
        for label, query in (("bronze", before), ("silver", after)):
            print(f"\n  {label}")
            print(indent(sqlmesh("fetchdf", query).rstrip(), "  "))

    print("\n" + "=" * 72)
    print("what landed")
    print("=" * 72)
    for caption, query in SHOW_WHAT_LANDED:
        print(f"\n-- {caption}")
        print(sqlmesh("fetchdf", query).rstrip())


if __name__ == "__main__":
    main()
