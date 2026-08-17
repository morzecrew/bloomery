# lakehouse/

The compiler, running against a real lakehouse. Eight spec documents become
SQLMesh artifacts, SQLMesh builds them into Apache Iceberg tables through a
[Lakekeeper](https://lakekeeper.io) REST catalog over MinIO, and Trino queries
the result.

Nothing in the stack is a bloomery dependency. bloomery is a pure function from
YAML to artifacts — it opens no socket and writes no table. The stack is here so
you can watch what it emits actually build something.

## Run it

```bash
cd examples/lakehouse
just demo
```

That is `up`, `seed` and `run` in order. First run pulls four images and takes a
few minutes; after that it is under a minute. `just` on its own lists everything
the example can do; `just down` tears the stack down, and since every service is
`tmpfs`-backed nothing survives and there is nothing to clean up.

**After editing anything in `seed/`, use `just rebuild`.** SQLMesh plans on
*model* changes, so changing bronze data and re-running correctly does nothing —
restating is how you ask for the rebuild, and it is also what makes the
generated audits run again.

MinIO's console is on <http://localhost:9001> (`minio-admin` /
`minio-admin-password`) if you want to see the Parquet and metadata files
appear; Trino is on <http://localhost:8080>.

## The sources

Four bronze relations, in the shape each source really ships. They live in
`seed/` as data files rather than as SQL, and `seed.py` translates them into the
`CREATE TABLE` statements Trino runs — inventing no values and cleaning nothing,
because cleaning is the mappings' job.

| File | Shape | Stands for |
|---|---|---|
| `seed/shopify_order_lines.jsonl` | Newline-delimited JSON, one nested event per line | A storefront's webhook landing table |
| `seed/woo_order_lines.csv` | Flat CSV, decimal currency, lower-case SKUs | A legacy shop's nightly export |
| `seed/crm_customers.csv` | Flat CSV with ingestion metadata | A CRM snapshot, warts included |
| `seed/products.csv` | Flat CSV | A product catalogue export |

**Everything lands as `VARCHAR`**, except the one timestamp the quarantine
contract requires. That is the honest setting rather than a convenience: bronze
is landed text, and every cast in this project belongs to a mapping's declared
transform chain. A loader that helpfully typed `list_price_cents` as an integer
would be doing a mapping's job and hiding the `' 1250'` that its `trim` step
exists for.

The JSON keeps its nesting. Each event's top-level keys become columns and the
payload stays a JSON *string*, which is what a webhook landing table actually
looks like — and it is what makes `$.payload.pricing.line_total_cents` in the
mapping a JSON extraction off a physical column rather than a field somebody's
ingester shredded in advance. `just seed-sql` prints the SQL without running it.

## What the specs say

| File | Kind | What it declares |
|---|---|---|
| `specs/catalog.yaml` | Catalog | The canonical `amount` field, the `revenue` template built on it, the `dim_date` calendar |
| `specs/entity_model.yaml` | EntityModel | `order_line` (merged from two shops), `customer` (inside the quality system), `product` (outside it), the relationships, one coverage check and one reconcile check |
| `specs/mapping_platform.yaml` | Mapping | `shopify__order_lines` → `order_line`, out of nested JSON |
| `specs/mapping_legacy.yaml` | Mapping | `woo__order_lines` → **the same** `order_line`, out of flat CSV |
| `specs/mapping_crm.yaml` | Mapping | `crm__customers` → `customer`, with the field-level quality rules |
| `specs/mapping_catalogue.yaml` | Mapping | `catalogue__products` → `product` |
| `specs/metrics.yaml` | MetricSet | `revenue` from the template, `line_count` and `units` inline, `average_line_value` as a ratio |
| `specs/marts.yaml` | MartSet | One wide mart at order-line grain, with a blocking mart assertion |

Two mappings naming one `target:` is the entire syntax for a merge. There is no
`union:` kind and no `sources:` list — the thing that makes an entity
multi-source is that more than one document points at it.

## What you should see

`run.py` prints every source twice, before and after its mapping, so the
transform chains are visible as an effect rather than as YAML. Then it prints
what landed.

**Cleansing that is declared, not coded.** The CRM ships five spellings of two
segments, an email nobody can join on, a country code with three letters, and
`N/A` in a column that means "no value". The chains fold them:

```
  bronze                                   silver
  C-001    Ada@Example.COM   Consumer      C-001  ada@example.com      consumer
  C-002   GRACE@EXAMPLE.COM       B2B      C-002  grace@example.com    business
  C-006 barbara@example.com       b2c      C-006  barbara@example.com  consumer
```

**Cents to currency, exactly.** Both the catalogue and the platform shop bill in
integer cents, and the chains convert with `multiply: "0.01"` rather than
`divide: 100`. That is not a stylistic choice: decimal division promotes to a
float on some engines, and money that silently becomes a float is the defect
this project bans in its own IR. The factor is quoted because an unquoted YAML
`0.01` *is* a float.

**The merge.** One `silver.order_line` table fed by both shops, with a `_source`
column recording which row came from where — and two shops that agree about
nothing else:

```
                _source  lines  amount            earliest
   shopify__order_lines      7  438.91 2026-01-04 10:15:00
       woo__order_lines      5  417.97 2026-01-06 12:00:00
```

**A column one shop does not have.** `gift_note` is mapped by the platform shop
only, so the legacy branch of the `UNION ALL` projects a typed NULL — which is
what keeps the two arms the same width.

**A duplicate resolved by policy rather than by luck.** The CRM exports a full
snapshot per load, so `C-002` arrives twice — once as `GRACE@EXAMPLE.COM` in the
January 5th load and once as `grace@example.com` in the January 19th one.
`dedupe: {keep: latest_by, field: updated_at}` states which copy wins. Without
it the key would simply not be unique, and every downstream join would fan out.

**Quality rules that flag rather than drop.** `C-003`'s email is not an address
and `C-006`'s billing country has three letters. Both rows are kept and marked,
so counts stay honest:

```
   customer_id                email  _quality_ok            _quality_flags
         C-003         not-an-email        False           [email_pattern]
         C-006  barbara@example.com        False  [billing_country_length]
```

The chain runs *before* the rule judges the value, so `pattern` sees
`ada@example.com` and never the padded, shouting spelling above. And `enum_map` folds the
segment aliases while `in_set` disposes of whatever is left over — a chain
rewrites, a rule judges, and keeping the two apart is what lets a source widen
its vocabulary without silently widening yours.

**A row that could not be coerced, diverted rather than nulled.** `C-005`'s
`signed_up_at` reads `last tuesday`. bloomery generates a `coercible` rule per
column for an entity in the quality system — *the projection is NULL although
every source it read was not* — and that rule defaults to quarantine. So the row
does not join `silver.customer` and does not become a silent NULL; it lands in
`silver.customer__reject` with the rule that caught it, its key, and the raw
payload it arrived with:

```
               failed_rules               key_values source_relation
  [signed_up_at_coercible]  {"customer_id":"C-005"}  crm__customers
```

That `raw` column is why `quarantine:` demands a retention window rather than
defaulting one — reject rows hold source payloads, and therefore PII.

**And diverting a row has a visible price.** `C-005` still placed an order, so
`WOO-5003` sits in the mart with its money and without its segment:

```
   order_id customer_id customer_segment  amount
   WOO-5003       C-005             None    75.0
```

That is the honest outcome, not a bug: quarantine trades a wrong attribute for a
missing one, and the mart shows you which rows paid the price.

**One entity outside the system entirely.** `product` declares no `quality:`
block, and gets no reject table, no `_quality_flags` column and no retention
obligation. Opting in is per entity, and this is what opting out looks like.

**The quality mart** lists every rule the project carries, whether or not it
caught anything, plus an `(entity)` row holding the totals — `6` rows seen, `1`
held back, `1` deduplicated.

**The wide mart**, both dimensions joined through declared relationships and
`ordered_at` expanded into day/week/month/quarter/year buckets — the dimensions
a metric request is served from.

## Break it on purpose

The claim worth not taking on faith is the **blocking** collision audit.
bloomery generates it for every merged entity because disjointness is the one
condition of a merge that compilation cannot establish — the compiler has no
data. So it becomes a runtime check that stops the build rather than a warning
nobody reads.

Give both shops the same key:

```bash
just break-it
```

The plan fails and the table is not published:

```
'order_line_source_collision' audit error: 1 row failed
Error: Plan application failed.
```

Undo it with `just fix-it`.

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

The gateway pins `timezone: UTC`. Iceberg stores a bloomery `timestamp` as
`timestamp(6) with time zone`, so writing a zoneless value into it has to
promote it somehow — and the zone it promotes with is the *session's*, which the
client takes from the machine it runs on. Left unset, this example prints
different instants in Berlin and in Bengaluru from identical specs and identical
data. The compiler is deterministic; a connection is still a place a timezone
can walk in.

Credentials are hard-coded demo values on a private Docker network. Do not lift
this stack into anything that matters.

## Not covered here

- **dbt and Cube.** The same shape compiles to both, but a merged entity, a
  quarantine policy, a reconcile check, a coverage check and a mart assertion
  are all refused on dbt — each for a stated reason. `examples/targets/` runs a
  project that stays inside what all three targets support, and
  `examples/refusals/` shows one of these refusals in full.
- **Metric requests.** `examples/quickstart/` plans one and prints the SQL and
  its explanation; `examples/targets/` plans two and executes them.
