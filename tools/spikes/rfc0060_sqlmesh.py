"""RFC 0060 §6, the SQLMesh half. Same three routes, same acceptance."""
import pathlib, shutil, sys, tempfile
sys.path.insert(0, "tests")
import duckdb
from sqlmesh import Context
from support.compiling import compile_fixture

FIXTURE = "scd2_as_of"
CONFIG = """\
gateways:
  local:
    connection: {type: duckdb, database: %s}
default_gateway: local
model_defaults: {dialect: duckdb, start: 2024-01-01}
disable_anonymized_analytics: true
"""

def seed(db):
    c = duckdb.connect(str(db))
    try:
        c.execute("CREATE SCHEMA IF NOT EXISTS bronze")
        c.execute("CREATE TABLE bronze.crm__customers (id VARCHAR, segment VARCHAR, signed_up_at VARCHAR)")
        c.execute("CREATE TABLE bronze.shop__orders (id VARCHAR, customer_id VARCHAR, amount DECIMAL(12,4), order_date VARCHAR)")
        c.execute("INSERT INTO bronze.crm__customers VALUES ('c1','smb','2024-01-01T00:00:00')")
        c.executemany("INSERT INTO bronze.shop__orders VALUES (?,?,?,?)",
                      [("o1","c1",10,"2099-06-01"), ("o2","c2",99,"2099-06-02")])
    finally:
        c.close()

def write(root, db, edit=None):
    for a in compile_fixture(FIXTURE):
        p = root / a.path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(edit(a.path, a.content) if edit else a.content)
    (root / "config.yaml").write_text(CONFIG % db)

def apply(root):
    ctx = Context(paths=root)
    ctx.plan(auto_apply=True, no_prompts=True)
    return ctx

def refresh(root):
    """The next scheduled run, which is what actually re-reads the source.

    Two apparatus facts, both measured. `plan` compares *code*, and new bronze
    rows are not a code change — a second plan reports nothing to do and the
    model never executes, which reads exactly like the framework declining to
    version the row. And `run` alone is not enough either: with no missing
    intervals there is nothing to process, so the execution time has to advance
    the way a daily cron advances it.
    """
    ctx = Context(paths=root)
    ctx.run(execution_time="2026-09-17", ignore_cron=True)
    return ctx

def rows(db, sql):
    c = duckdb.connect(str(db))
    try:
        return c.execute(sql).fetchall()
    finally:
        c.close()

def report(label, db):
    snap = rows(db, "SELECT customer_id, segment, valid_from, valid_to FROM silver.customer ORDER BY customer_id, valid_from")
    mart = rows(db, "SELECT order_id, customer_id, customer_segment, order_date FROM gold.mart_orders ORDER BY order_id")
    baseline = [m for m in mart if m[1] == "c1" and m[2] is not None]
    found = [m for m in mart if m[1] == "c2" and m[2] is not None]
    present = [s for s in snap if s[0] == "c2"]
    print(f"\n--- {label}")
    print("  entity:", snap)
    print("  as-of mart:", mart)
    print(f"  baseline row c1 found by the join: {bool(baseline)}"
          f"{'' if baseline else '   <-- APPARATUS BROKEN, result unreadable'}")
    # Present-but-invisible and never-arrived are different answers, and only
    # the first is the defect this RFC is about. Asked separately so a route
    # the framework simply did not run cannot read as a route that failed.
    print(f"  the row reached the entity at all: {bool(present)}"
          f"{'' if present else '   <-- the framework never saw it; not a verdict on the route'}")
    # And the third way a route can read "invisible" without being broken: the
    # order is dated before the interval the framework assigned, so the corpus
    # cannot reach the row whatever the route did. The baseline check does not
    # cover this — on SQLMesh the first version is stamped at the epoch, so
    # `c1` is reachable from any date while `c2` is not (measured; a sweep
    # turned the routes invisible without tripping the baseline).
    # Read out of the row rather than held as a constant: a constant drifts
    # from the seed, which is how the first version of this guard passed a
    # deliberately broken corpus (a sweep changed the seed and not the constant).
    ordered = next((m[3] for m in mart if m[1] == "c2"), None)
    stamped = next((s[2] for s in present if s[2] is not None), None)
    if not found and ordered is not None and stamped is not None:
        import datetime as _dt
        at = _dt.datetime.combine(ordered, _dt.time()) if isinstance(ordered, _dt.date) and not isinstance(ordered, _dt.datetime) else ordered
        if at < stamped:
            print(f"  <-- the order is dated {ordered} and the framework stamped valid_from "
                  f"{stamped}; the corpus cannot reach the row and this is not a verdict "
                  "on the route")
    print(f"  as-of join FINDS the recovered row: {bool(found)}")
    return bool(baseline) and bool(found)

def fresh(tag):
    root = pathlib.Path(tempfile.mkdtemp(prefix=f"spike-sm-{tag}-"))
    db = root / "warehouse.duckdb"
    seed(db)
    return root, db

results = {}

def physical(db, name):
    """The table `silver.<name>` is a view over. SQLMesh's virtual layer means
    the relation bloomery's replay artifact names is not the one that holds
    rows — measured, not assumed."""
    c = duckdb.connect(str(db))
    try:
        found = c.execute(
            "SELECT table_schema || '.' || table_name FROM information_schema.tables "
            "WHERE table_type = 'BASE TABLE' AND table_name LIKE ?", [f"silver__{name}__%"]
        ).fetchone()
    finally:
        c.close()
    return found[0]

# Route A — write past the framework
root, db = fresh("a"); write(root, db); apply(root)
c = duckdb.connect(str(db))
# The emitted replay MERGE names `silver.customer`, which SQLMesh publishes as
# a *view*. Recorded here because it is a second failure the RFC never measured:
try:
    c.execute("INSERT INTO silver.customer (customer_id, segment, signed_up_at) VALUES ('c2','ent',TIMESTAMP '2024-02-01')")
    print("note: silver.customer accepted a direct insert")
except Exception as exc:
    print(f"note: the relation the replay merge names refuses the write -> {type(exc).__name__}: {exc}")
# So the simulation writes to the physical table the view reads, which is the
# most favourable reading of what the shipped merge would achieve.
c.execute(f"INSERT INTO {physical(db, 'customer')} (customer_id, segment, signed_up_at) VALUES ('c2','ent',TIMESTAMP '2024-02-01')")
c.close()
apply(root)
results["A — merge past the framework (the shipped defect)"] = report("route A", db)
shutil.rmtree(root, ignore_errors=True)

# Route B (§5.2) — the row arrives through bronze
root, db = fresh("b"); write(root, db); apply(root)
c = duckdb.connect(str(db))
c.execute("INSERT INTO bronze.crm__customers VALUES ('c2','ent','2024-02-01T00:00:00')")
c.close()
refresh(root)
results["B — §5.2, the row arrives through bronze"] = report("route B", db)
shutil.rmtree(root, ignore_errors=True)

# Route C (§5.1) — a __replayed arm in the entity's source
root, db = fresh("c")
def union_arm(path, content):
    if not path.endswith("customer.sql"):
        return content
    assert "FROM bronze.crm__customers" in content, "the model stopped reading bronze this way"
    return content.rstrip().rstrip(";") + """
UNION ALL
SELECT
  CAST(customer_id AS TEXT) AS customer_id,
  CAST(segment AS TEXT) AS segment,
  CAST(signed_up_at AS TIMESTAMP) AS signed_up_at,
  CAST([] AS TEXT[]) AS _quality_flags,
  TRUE AS _quality_ok
FROM silver.customer__replayed
"""
c = duckdb.connect(str(db))
c.execute("CREATE SCHEMA IF NOT EXISTS silver")
c.execute("CREATE TABLE silver.customer__replayed (customer_id VARCHAR, segment VARCHAR, signed_up_at TIMESTAMP)")
c.close()
write(root, db, edit=union_arm); apply(root)
c = duckdb.connect(str(db))
c.execute("INSERT INTO silver.customer__replayed VALUES ('c2','ent',TIMESTAMP '2024-02-01')")
c.close()
refresh(root)
results["C — §5.1, a __replayed arm in the entity's source"] = report("route C", db)
shutil.rmtree(root, ignore_errors=True)

# ---------- Correction: does a changed row rewrite its version or add one? ----------
# Routes A, B and C all admit a key the entity did not have. RFC 0060 §10 asks a
# different question — whether replay corrects history or adds to it — and a row
# that only ever *arrives* cannot answer it (found in review of PR #121).
root, db = fresh("correct")
write(root, db)
apply(root)
c = duckdb.connect(str(db))
c.execute("UPDATE bronze.crm__customers SET segment = 'ent' WHERE id = 'c1'")
c.close()
refresh(root)
versions = rows(db, "SELECT customer_id, segment, valid_from, valid_to FROM silver.customer ORDER BY valid_from")
print("\n--- correcting an existing row, through bronze")
print("  versions of c1:", versions)
print(f"  the old version is retained: {len(versions) > 1}")
print(f"  the old version was closed rather than rewritten: "
      f"{any(v[3] is not None for v in versions)}")

# And the other half of the same question: can the history be rewritten at all?
# Cited by `logs/T-0057.md`, so it has to run here rather than in a probe that
# was deleted — a citation naming a command this script does not contain is not
# evidence (found in review of PR #121).
print("\n--- asking SQLMesh to restate the entity")
try:
    Context(paths=root).plan(
        auto_apply=True, no_prompts=True, restate_models=["silver.customer"]
    )
    after = rows(db, "SELECT COUNT(*) FROM silver.customer")
    print(f"  the plan returned; versions now: {after[0][0]}"
          f" (was {len(versions)}) — watch the console line above for a refusal")
except Exception as exc:
    print(f"  refused: {type(exc).__name__}: {exc}")

print("\n" + "=" * 62)
for label, ok in results.items():
    print(f"  {'FOUND    ' if ok else 'INVISIBLE'}  {label}")
