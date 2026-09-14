"""RFC 0060 §6: does a row admitted by route X become visible to the as-of join?

Three routes against one project. The acceptance is D3's: the mart's own as-of
join *finding* the row, never the row being present in the relation.
"""
import pathlib, shutil, sys, tempfile
sys.path.insert(0, "tests")
import duckdb
from support.compiling import compile_fixture

FIXTURE = "scd2_as_of"
PROFILES = """\
bloomery:
  target: local
  outputs:
    local: {type: duckdb, path: '%s', schema: main}
"""

def seed(db):
    c = duckdb.connect(str(db))
    try:
        c.execute("CREATE SCHEMA IF NOT EXISTS bronze")
        c.execute("CREATE TABLE bronze.crm__customers (id VARCHAR, segment VARCHAR, signed_up_at VARCHAR)")
        c.execute("CREATE TABLE bronze.shop__orders (id VARCHAR, customer_id VARCHAR, amount DECIMAL(12,4), order_date VARCHAR)")
        c.executemany("INSERT INTO bronze.crm__customers VALUES (?,?,?)",
                      [("c1", "smb", "2024-01-01T00:00:00")])
        c.executemany("INSERT INTO bronze.shop__orders VALUES (?,?,?,?)",
                      [("o1", "c1", 10, "2099-06-01"), ("o2", "c2", 99, "2099-06-02")])
    finally:
        c.close()

def write(root, db, edit=None):
    for a in compile_fixture(FIXTURE, target="dbt", dialect="duckdb"):
        p = root / a.path
        p.parent.mkdir(parents=True, exist_ok=True)
        content = a.content
        if edit is not None:
            content = edit(a.path, content)
        p.write_text(content, encoding="utf-8")
    (root / "profiles.yml").write_text(PROFILES % db, encoding="utf-8")

def dbt(root, *args):
    from dbt.cli.main import dbtRunner
    r = dbtRunner().invoke([*args, "--project-dir", str(root), "--profiles-dir", str(root), "-q"])
    if not r.success:
        raise SystemExit(f"dbt {args}: {getattr(r, 'exception', None)}")
    return r

def rows(db, sql):
    c = duckdb.connect(str(db))
    try:
        return c.execute(sql).fetchall()
    finally:
        c.close()

def report(label, db):
    snap = rows(db, "SELECT customer_id, segment, valid_from, valid_to FROM silver.customer_snapshot ORDER BY customer_id, valid_from")
    mart = rows(db, "SELECT order_id, customer_id, customer_segment FROM gold.mart_orders ORDER BY order_id")
    print(f"\n--- {label}")
    print("  snapshot:", snap)
    print("  as-of mart:", mart)
    baseline = [m for m in mart if m[1] == "c1" and m[2] is not None]
    found = [m for m in mart if m[1] == "c2" and m[2] is not None]
    # The control first. A run in which the as-of join finds *nothing* has
    # abstained, not answered: the first attempt dated its orders 2024 while
    # dbt stamps valid_from with its own run clock, so `order_date >= valid_from`
    # was false for every row and all three routes reported "invisible".
    print(f"  baseline row c1 found by the join: {bool(baseline)}"
          f"{'' if baseline else '   <-- APPARATUS BROKEN, result unreadable'}")
    print(f"  as-of join FINDS the recovered row: {bool(found)}")
    return bool(baseline) and bool(found)

def fresh(tag):
    root = pathlib.Path(tempfile.mkdtemp(prefix=f"spike-{tag}-"))
    db = root / "warehouse.duckdb"
    seed(db)
    return root, db

results = {}

# ---------- Route A: the shipped merge, entity columns only ----------
root, db = fresh("a")
write(root, db)
dbt(root, "build")
c = duckdb.connect(str(db))
c.execute("INSERT INTO silver.customer_snapshot (customer_id, segment, signed_up_at) VALUES ('c2','ent',TIMESTAMP '2024-02-01 00:00:00')")
c.close()
dbt(root, "run", "--select", "mart_orders")
results["A — merge past the framework (the shipped defect)"] = report("route A", db)
shutil.rmtree(root)

# ---------- Route B (§5.2): write the row to bronze, run the pipeline ----------
root, db = fresh("b")
write(root, db)
dbt(root, "build")
c = duckdb.connect(str(db))
c.execute("INSERT INTO bronze.crm__customers VALUES ('c2','ent','2024-02-01T00:00:00')")
c.close()
dbt(root, "build")
results["B — §5.2, the row arrives through bronze"] = report("route B", db)
shutil.rmtree(root)

# ---------- Route C (§5.1): the snapshot's source gains a __replayed arm ----------
root, db = fresh("c")
def union_arm(path, content):
    if path != "snapshots/customer_snapshot.sql":
        return content
    marker = "FROM {{ source('bronze', 'crm__customers') }}"
    assert marker in content, "the snapshot stopped reading bronze this way"
    return content.replace(marker, marker + """

UNION ALL

SELECT
  CAST(customer_id AS TEXT) AS customer_id,
  CAST(segment AS TEXT) AS segment,
  CAST(signed_up_at AS TIMESTAMP) AS signed_up_at,
  CAST([] AS TEXT[]) AS _quality_flags,
  TRUE AS _quality_ok
FROM silver.customer__replayed""")
c = duckdb.connect(str(db))
c.execute("CREATE SCHEMA IF NOT EXISTS silver")
c.execute("CREATE TABLE silver.customer__replayed (customer_id VARCHAR, segment VARCHAR, signed_up_at TIMESTAMP)")
c.close()
write(root, db, edit=union_arm)
dbt(root, "build")
c = duckdb.connect(str(db))
c.execute("INSERT INTO silver.customer__replayed VALUES ('c2','ent',TIMESTAMP '2024-02-01 00:00:00')")
c.close()
dbt(root, "build")
results["C — §5.1, a __replayed arm in the entity's source"] = report("route C", db)
shutil.rmtree(root)

print("\n" + "=" * 62)
for label, ok in results.items():
    print(f"  {'FOUND   ' if ok else 'INVISIBLE'}  {label}")
