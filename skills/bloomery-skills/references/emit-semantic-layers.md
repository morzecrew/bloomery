# Emit semantic layers

Emit the MetricFlow semantic manifest and the Cube data model over the gold marts a SQL
target builds. Both read marts, never raw entities: one mart becomes one semantic model
and one cube, so the semantic layer and the physical table cannot disagree.

## What both need

A semantic layer only describes marts, so the project needs a `marts` document whose
marts carry `measures:` and a date role, and a `metrics` document declaring those
measures. The gold tables themselves are built by SQLMesh or dbt: deploy those artifacts
too, under the same naming policy.

```yaml spec=metrics
metrics_version: 1
metrics:
  revenue:
    grain: order
    additivity: additive
    agg: sum
    expr: "amount"
  order_count:
    grain: order
    additivity: additive
    agg: count
    expr: "order_id"
  average_order_value:
    requires_metrics: [order_count, revenue]
    additivity: ratio
    ratio: {numerator: revenue, denominator: order_count}
```

```yaml spec=marts
marts_version: 1
marts:
  orders:
    grain: order
    base: order
    flatten:
      - {date: order_date, role: ordered}
    measures: [revenue, order_count]
```

Neither output depends on `--dialect`: MetricFlow and Cube render SQL against their own
configured warehouse.

## MetricFlow

```console
$ bloomery compile specs/ --target metricflow --out build/metricflow
```

One artifact, `semantic_manifest.json`, the file `dbt-semantic-interfaces` reads.

| In the manifest | From |
|---|---|
| one `semantic_models` entry per mart | `node_relation` is the mart's gold table, e.g. `gold.mart_orders` |
| the primary entity | the mart's grain; flattened relationships become foreign entities |
| dimensions | every flattened column; each date role a time dimension |
| measures | each mart measure, with its aggregation and time dimension |
| `metrics` | every metric, ratios as `type: ratio` over their operands |
| the time spine | the catalog's date dimension, at `gold.dim_date` |

No semantic model is ever emitted for an entity that is not a mart: that would bring back
the query-time joins marts exist to prevent. The manifest is also what bloomery's own
planner hydrates to answer metric requests, so a request is served from a mart, never by
joining models.

## Cube

```console
$ bloomery compile specs/ --target cube --out cube_repo
```

Two files per mart, in Cube's `model/` layout:

| Path | What it is |
|---|---|
| `model/cubes/<mart>.yml` | the cube: `sql_table`, dimensions, measures |
| `model/views/<mart>_view.yml` | one view exposing the cube's members (`includes: '*'`) |

`sql_table` is exactly the relation the SQL target named the mart (`gold.mart_orders`).

- **Dimensions.** Every flattened column, typed from its logical type: `string`;
  `int`/`decimal` → `number`; `bool` → `boolean`; `date`/`timestamp` → `time`; `variant`
  → `string`. Date-role buckets are `time` with `meta.granularity`.
- **Measures.** Aggregations map onto Cube's closed set: `sum`, `count`,
  `count_distinct`, `avg`, `min`, `max`. A `count` emits with no `sql`. Each carries
  `meta.additivity` and `meta.grain`, and a semi-additive one `meta.semi_additive`. Cube
  does not enforce them; they exist so a consumer can check.
- **Ratios are calculated, never stored.** `average_order_value` becomes a `number`
  measure `'{revenue} / NULLIF({order_count}, 0)'` on the one cube that owns both
  operands, so Cube recomputes it at every grain.
- **Ownership.** A metric served by several marts lands on exactly one cube: the cheapest
  `cost_hint`, ties by name, the same rule the planner uses.

### Rollups become pre-aggregations

A `rollups:` entry in the marts document becomes a `pre_aggregations` entry on its
parent's cube, listing only the measures it carries and the dimensions it keeps:

```yaml fragment
pre_aggregations:
  - name: order_items_monthly
    type: rollup
    measures: [CUBE.gross_revenue]
    dimensions: [CUBE.order_customer_id]
    time_dimension: CUBE.ordered_month
    granularity: month
```

`time_dimension` appears only when the rollup keeps exactly one date bucket. No
`refresh_key` is emitted. Cube builds its own copy from the parent cube; it does not read
the rollup's gold table that SQLMesh or dbt builds. A rollup's measures are limited to
`sum`, `count`, `min`, `max`.

## What is refused

`UnsupportedByTarget`, per construct, on either semantic layer:

- an aggregation outside the target's set;
- a metric with no expression;
- a non-additive metric whose decomposition is not a ratio;
- a mart measure whose metric was not imported alongside an imported mart (an export
  list is written by hand, so import the metrics a mart's `measures:` names).

Storing a ratio as a mart column never gets this far: it is a guardrail refusal at
compile time (see [guardrails and evidence](guardrails-and-evidence.md)). SCD2 and
incremental materialization never reach these targets: they consume tables someone
else maintains.

## Checking it end to end

Compile the SQL target and the semantic layer from the same specs, build the marts, then
point the semantic layer at the warehouse:

```console
$ bloomery compile specs/ --target sqlmesh --dialect duckdb --out build/sqlmesh
$ bloomery compile specs/ --target cube --out build/cube
$ bloomery compile specs/ --target metricflow --out build/metricflow
```

The same request through bloomery's planner, Cube's REST API and MetricFlow returns the
same number, because all three read one mart.

## Published pages

- [Emit Cube artifacts](https://morzecrew.github.io/bloomery/latest/how-to/emit-cube/)
- [The wide-mart gold layer](https://morzecrew.github.io/bloomery/latest/concepts/wide-marts/)
