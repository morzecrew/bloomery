# targets/

One spec set, three targets, each one actually run — and the two that build
tables checked against each other row for row.

```bash
cd examples/targets
just demo
```

`just run` is the container-free part (SQLMesh, dbt, the planner). `just cube`
adds the one container.

## Why this example exists

bloomery claims three targets. The test suite proves the *artifacts*: goldens
compare bytes per (fixture × target × dialect), and the e2e tier checks each
framework accepts what it is given. None of that shows a person the thing
running — dbt building tables, Cube answering a question, a planned metric
request returning a number.

So this takes one small retailer's project and drives it all the way through:

| Step | What runs | What it proves |
|---|---|---|
| 1 | seed two DuckDB warehouses from `seed/` | the bronze the mappings read |
| 2 | `sqlmesh plan --auto-apply` | SQLMesh builds silver, the calendar and the mart |
| 3 | print each source before and after its mapping | the transform chains, as an effect |
| 4 | `dbt build` | dbt builds the same thing from the same specs |
| 5 | compare | **the two agree, row for row** |
| 6 | plan two metric requests and execute them | the planner serves a question, not a string |
| 7 | Cube answers over REST | the semantic layer reads the same mart |

Step 5 is what the example is for. A dialect port is a claim that two frameworks
given one spec produce one answer; here that is a comparison rather than a
sentence.

## The sources

Three of them, in the shape each really ships, kept in `seed/` as data files
rather than as an inline SQL string:

| File | Shape | Stands for |
|---|---|---|
| `seed/order_events.jsonl` | Newline-delimited JSON, one nested event per order | A storefront's webhook landing table |
| `seed/customers.csv` | Flat CSV | A CRM export, warts included |
| `seed/products.csv` | Flat CSV | A product catalogue export |

Everything lands as text. `all_varchar=true` on the CSVs is the honest setting
rather than a convenience: bronze is landed text, and every cast in this project
belongs to a mapping's declared transform chain. Letting DuckDB infer
`list_price_cents` as an integer would quietly do a mapping's job and hide the
`' 1250'` its `trim` step exists for.

The JSON keeps its nesting: the four top-level keys become columns and `payload`
stays a JSON *string*, which is why `$.payload.totals.gross_cents` in the
mapping is a JSON extraction off a physical column rather than a field somebody
shredded in advance.

## What the mappings clean

Everything below is *declared*, not written as SQL, and `just run` prints each
source before and after so you can check the chain did what the comment claims.

| Raw | Chain | Result |
|---|---|---|
| `Ada@Example.COM`, padded with spaces | `to_string, trim, lower` | `ada@example.com` |
| `Consumer` / `CONSUMER` / `B2B` / `b2c` / *(blank)* | `lower`, `enum_map`, `coalesce` | `consumer` / `business` / `unknown` |
| `N/A` | `nullif`, `coalesce` | `unknown` |
| `ORD-000101` | `strip_prefix: "ORD-"` | `000101` |
| `7998` (cents) | `to_decimal`, `multiply: "0.01"` | `79.98` |
| `Web` / `MOBILE-APP` / `partner-api` / `""` | `lower`, `nullif`, `enum_map`, `coalesce` | `online` / `mobile` / `partner` / `unrecorded` |
| `2023-11-02T09:12:00` (head-office local) | `parse_ts`, `to_utc: Europe/Berlin` | the same instant, in UTC |

Two of those are worth a sentence each.

**`multiply: "0.01"`, not `divide: 100`.** The two are not equivalent on every
engine: DuckDB's decimal division promotes its result to `DOUBLE`, while decimal
multiplication stays exact. A money column that silently becomes a float is
precisely the defect this project bans in its own IR, so the chain avoids it in
the SQL it emits too. The factor is quoted because an unquoted YAML `0.01` *is*
a float, and the parser says so.

**`nullif` on an empty string.** One event carries `"channel": ""`. An empty
string is not a value, it is a field the storefront failed to fill — and without
`nullif` the mart grows a silent `''` category that groups separately from every
real channel and reads as a channel in a chart.

## Why two warehouses

Both frameworks place their mart at `gold.mart_orders`. Sharing one file would
mean whichever ran second silently overwrote the other, and step 5 would be
comparing one framework against itself. Each gets its own seeded copy, so the
comparison is between two independent builds.

## The ratio metric

`average_order_value` is declared as `ratio: {numerator: revenue, denominator:
order_count}` and is deliberately **absent from the mart's `measures:`**. A
non-additive metric is never a stored number: the average of two averages is not
the average, so it is recomputed from its additive parts at whatever grain the
question is asked at. `just run` plans it by `product_category` and executes the
result, and you can watch the planner rebuild it from `SUM(revenue)` and
`SUM(order_count)` rather than reading a column.

## What the specs deliberately avoid

No union merge, no `quarantine:`, no `reconcile:`, no `coverage:`, no mart
assertions — and, following from the first of those, **no `quality:` block
anywhere**. Each is refused on dbt for a stated reason, and quality is refused
transitively: opting an entity in generates a `coercible` rule per column, those
default to quarantine, quarantine demands a retention window, and dbt lowers
neither the reject table nor its replay merge.

This example is about what all three targets *do* support, so the cleansing
above is done entirely with transform chains. `examples/lakehouse/` runs the
same shape with the quality system turned on, against a real Iceberg lakehouse;
`examples/refusals/` shows one of these refusals in full.

## Cube

Cube reads the emitted `model/` directory and opens the SQLMesh warehouse
directly with its DuckDB driver, so there is no database server in the stack.

Two things worth knowing if you adapt it:

- **The warehouse is mounted read-write.** DuckDB writes a lock file even to
  read, and a `:ro` mount fails with `Database was already closed`.
- **The healthcheck probes `/cubejs-api/v1/meta`, not `/readyz`.** In dev mode
  `/readyz` reports 500 while Cube serves queries perfectly well, and `/meta` is
  the endpoint that means something here: it returns 200 once the semantic model
  has parsed, which is the thing that can actually be wrong.

Cube's playground is on <http://localhost:4000> once `just cube` has run.

## Commands

| Command | What |
|---|---|
| `just demo` | everything |
| `just run` | SQLMesh, dbt, the comparison, the planner — no containers |
| `just cube` | start Cube and ask it the same question |
| `just emitted dbt` | list what was compiled for one target |
| `just clean` | remove both warehouses and every compiled project |
