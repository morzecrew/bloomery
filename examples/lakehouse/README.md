# lakehouse/

The compiler, running against a real lakehouse. Seven spec documents become
SQLMesh artifacts, SQLMesh builds them into Apache Iceberg tables through a
[Lakekeeper](https://lakekeeper.io) REST catalog over MinIO, and Trino queries
the result.

Nothing in the stack is a bloomery dependency. bloomery is a pure function from
YAML to artifacts — it opens no socket and writes no table. The stack is here so
you can watch what it emits actually build something.

## Run it

```bash
docker compose -f examples/lakehouse/compose.yaml up -d --wait
docker exec -i bloomery-lakehouse-trino-1 trino -f /dev/stdin < examples/lakehouse/seed.sql
uv run python examples/lakehouse/run.py
```

First run pulls four images and takes a few minutes; after that it is seconds.
Tear it down with `docker compose -f examples/lakehouse/compose.yaml down -v` —
all state is in `tmpfs`, so nothing survives and nothing to clean up.

MinIO's console is on <http://localhost:9001> (`minio-admin` /
`minio-admin-password`) if you want to see the Parquet and metadata files
appear; Trino is on <http://localhost:8080>.

## What the specs say

| File | Kind | What it declares |
|---|---|---|
| `specs/catalog.yaml` | Catalog | The canonical `amount` field, the `revenue` template built on it, the `dim_date` calendar |
| `specs/entity_model.yaml` | EntityModel | `order_line` (merged from two shops) and `customer` (inside the quality system), and the relationship between them |
| `specs/mapping_platform.yaml` | Mapping | `shopify__order_lines` → `order_line` |
| `specs/mapping_legacy.yaml` | Mapping | `woo__order_lines` → **the same** `order_line` |
| `specs/mapping_crm.yaml` | Mapping | `crm__customers` → `customer` |
| `specs/metrics.yaml` | MetricSet | `revenue` from the template, `line_count` inline |
| `specs/marts.yaml` | MartSet | One wide mart at order-line grain |

Two mappings naming one `target:` is the entire syntax for a merge. There is no
`union:` kind and no `sources:` list — the thing that makes an entity
multi-source is that more than one document points at it.

## What you should see

**The merge.** One `silver.order_line` table fed by both shops, with a `_source`
column recording which row came from where:

```
                _source  lines  amount
   shopify__order_lines      4  144.93
       woo__order_lines      3   94.96
```

**A column one shop does not have.** `gift_note` is mapped by the platform shop
only, so the legacy branch of the `UNION ALL` projects a typed NULL — which is
what keeps the two arms the same width.

**A quality rule that flags rather than drops.** `C-003`'s email is not an
address. The row is kept and marked, so counts stay honest:

```
   customer_id             email  _quality_ok                _quality_flags
         C-003      not-an-email        False [email_looks_like_an_address]
```

Note `C-002` arrives as `GRACE@EXAMPLE.COM` and lands as `grace@example.com`:
the `trim`/`lower` chain runs *before* the rule judges the value, so the check
sees the produced column rather than whatever the source happened to send.

**The wide mart**, customer joined in and `ordered_at` expanded into
day/week/month/quarter/year buckets — the dimensions a metric request is served
from.

## Break it on purpose

The claim worth not taking on faith is the **blocking** collision audit.
bloomery generates it for every merged entity because disjointness is the one
condition of a merge that compilation cannot establish — the compiler has no
data. So it becomes a runtime check that stops the build rather than a warning
nobody reads.

Give both shops the same key:

```bash
docker exec bloomery-lakehouse-trino-1 trino --execute \
  "INSERT INTO iceberg.bronze.woo__order_lines VALUES
   ('SH-1001', BIGINT '1', 'C-001', 'SKU-DUP', BIGINT '1', DECIMAL '9.99', '2026-03-01 00:00:00')"

cd examples/lakehouse/out && uv run sqlmesh plan --auto-apply --restate-model 'silver.order_line'
```

The plan fails and the table is not published:

```
'order_line_source_collision' audit error: 1 row failed
Error: Plan application failed.
```

Undo it with `DELETE FROM iceberg.bronze.woo__order_lines WHERE product_sku = 'SKU-DUP'`
and restate again.

**Why a restate rather than re-running `run.py`.** SQLMesh plans on *model*
changes. Editing bronze data changes no model, so a plain plan correctly decides
there is nothing to do — the audit runs when the model is rebuilt, and
`--restate-model` is what asks for that.

## The stack

| Service | Role |
|---|---|
| `lakekeeper` | Iceberg REST catalog — owns table metadata |
| `postgres` | Lakekeeper's metadata store |
| `minio` | S3-compatible object store holding the actual data files |
| `trino` | The engine SQLMesh executes against |
| `minio-init`, `lakekeeper-migrate`, `lakekeeper-bootstrap` | One-shot setup: bucket, schema migration, warehouse creation |

SQLMesh keeps its own state in a DuckDB file under `out/`. That is bookkeeping
about plans rather than warehouse data, and keeping it local means the stack
needs one less published port.

Credentials are hard-coded demo values on a private Docker network. Do not lift
this stack into anything that matters.

## Not covered here

- **dbt and Cube.** The same specs compile to both (`Target.DBT`, `Target.CUBE`)
  — but a merged entity is refused on dbt, because its collision audit has no
  honest dbt equivalent and a merge without that check double-counts in silence.
- **Nested source paths.** Every mapping here reads a flat column so the demo
  does not depend on JSON handling differing between engines. `$.a.b` extracts
  from a JSON column; the test corpus under `tests/fixtures/` shows that shape.
- **Metric requests.** `examples/quickstart/` plans one and prints the SQL and
  its explanation.
