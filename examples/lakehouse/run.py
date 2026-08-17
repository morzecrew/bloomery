"""Compile the specs in this directory and build them into the lakehouse.

    docker compose -f examples/lakehouse/compose.yaml up -d --wait
    docker exec -i bloomery-lakehouse-trino-1 trino -f /dev/stdin \\
        < examples/lakehouse/seed.sql
    uv run python examples/lakehouse/run.py

What happens, in order:

1. The seven spec documents are loaded and compiled to SQLMesh artifacts for the
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
5. A few queries print what landed, so the merge and the quality flags are
   visible rather than asserted.

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

from bloomery import Target, compile_project, load_catalog, load_project

HERE = Path(__file__).parent
SPECS = HERE / "specs"
OUT = HERE / "out"

#: The emitted project is ordinary SQLMesh — nothing here is bloomery-specific.
#: ``catalog: iceberg`` is what makes an unqualified ``silver.order_line`` land
#: in the Iceberg catalog Lakekeeper serves. SQLMesh's own state goes to a local
#: DuckDB file: that is bookkeeping about plans rather than warehouse data, and
#: keeping it local means the stack needs one less published port.
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
    state_connection:
      type: duckdb
      database: {state}
default_gateway: lakehouse
model_defaults:
  dialect: trino
  start: 2026-01-01
disable_anonymized_analytics: true
"""

SHOW_WHAT_LANDED = (
    (
        "the merge: one entity, two shops, and the _source column that says which",
        "SELECT _source, count(*) AS lines, sum(amount) AS amount "
        "FROM iceberg.silver.order_line GROUP BY _source ORDER BY _source",
    ),
    (
        "gift_note is mapped by one shop only — the other branch fills a typed NULL",
        "SELECT _source, count(gift_note) AS with_note, count(*) AS lines "
        "FROM iceberg.silver.order_line GROUP BY _source ORDER BY _source",
    ),
    (
        "the quality rule flagged a row rather than dropping it",
        "SELECT customer_id, email, _quality_ok, _quality_flags "
        "FROM iceberg.silver.customer ORDER BY customer_id",
    ),
    (
        "the wide mart, joined and bucketed, ready for a metric request",
        "SELECT ordered_month, customer_segment, count(*) AS lines, "
        "sum(amount) AS revenue FROM iceberg.gold.mart_order_lines "
        "GROUP BY ordered_month, customer_segment ORDER BY 1, 2",
    ),
)


def compile_to(out: Path) -> list[str]:
    """Specs in, SQLMesh project out. The only bloomery step in this file."""
    catalog = load_catalog((SPECS / "catalog.yaml").read_text())
    project = load_project(
        {
            path.name: path.read_text()
            for path in sorted(SPECS.glob("*.yaml"))
            if path.name != "catalog.yaml"
        }
    )
    written: list[str] = []
    for artifact in compile_project(
        project, target=Target.SQLMESH, dialect="trino", catalog=catalog
    ):
        destination = out / artifact.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(artifact.content)
        written.append(artifact.path)
    return written


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

    for caption, query in SHOW_WHAT_LANDED:
        print(f"\n-- {caption}")
        print(sqlmesh("fetchdf", query).rstrip())


if __name__ == "__main__":
    main()
