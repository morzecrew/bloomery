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

So this takes one plain project and drives it all the way through:

| Step | What runs | What it proves |
|---|---|---|
| 1 | seed two DuckDB warehouses | the bronze the mappings read |
| 2 | `sqlmesh plan --auto-apply` | SQLMesh builds silver, the calendar and the mart |
| 3 | `dbt build` | dbt builds the same thing from the same specs |
| 4 | compare | **the two agree, row for row** |
| 5 | plan a metric request and execute it | the planner serves a question, not a string |
| 6 | Cube answers over REST | the semantic layer reads the same mart |

Step 4 is what the example is for. A dialect port is a claim that two frameworks
given one spec produce one answer; here that is a comparison rather than a
sentence.

## Why two warehouses

Both frameworks place their mart at `gold.mart_orders`. Sharing one file would
mean whichever ran second silently overwrote the other, and step 4 would be
comparing one framework against itself. Each gets its own seeded copy, so the
comparison is between two independent builds.

## What the specs deliberately avoid

No union merge, no `quarantine:`, no `reconcile:`. Each is refused on dbt for a
stated reason — see `examples/refusals/` — and this example is about what all
three targets *do* support. `examples/lakehouse/` is where the merge and the
quality system are exercised, against a real Iceberg lakehouse.

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
