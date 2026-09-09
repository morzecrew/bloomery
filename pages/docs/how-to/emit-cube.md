# Emit Cube artifacts

You want your marts and metrics exposed to BI through Cube's semantic layer. The Cube
target emits `cubes:` and `views:` YAML over the same gold tables the
[SQLMesh target](emit-sqlmesh.md) builds — one cube per mart, so the semantic layer and
the physical table cannot disagree.

## Compile

Everything up to the target is identical to the SQLMesh flow — load specs, then:

```python
from pathlib import Path

from bloomery import Target, compile_project, load_project

entity_model = """
spec_version: 1
entities:
  order:
    grain: one row per order
    key: [order_id]
    fields:
      order_id: {type: string, required: true}
      amount: {type: "decimal(12,2)"}
      order_date: {type: date}
"""

mapping = """
mapping_version: 1
source: shop__orders
target: order
key:
  order_id: {from: "$.id", transform: [to_string]}
fields:
  amount: {from: "$.amount", transform: [{to_decimal: [12, 2]}]}
  order_date: {from: "$.created_at", transform: [{parse_date: ISO8601}]}
"""

metrics = """
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
"""

marts = """
marts_version: 1
marts:
  orders:
    grain: order
    base: order
    flatten:
      - {date: order_date, role: ordered}
    measures: [revenue, order_count]
"""

project = load_project(
    {
        "entity_model.yaml": entity_model,
        "mapping.yaml": mapping,
        "metrics.yaml": metrics,
        "marts.yaml": marts,
    }
)
artifacts = compile_project(project, target=Target.CUBE, dialect="duckdb")
for artifact in artifacts:
    destination = Path("cube_repo") / artifact.path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(artifact.content)
```

The emitted YAML is **dialect-independent** — Cube renders SQL against its own
configured database, so the `dialect` argument does not shape these artifacts.

## What appears

Two artifacts per mart, following Cube's `model/` layout:

| Path | What it is |
|---|---|
| `model/cubes/orders.yml` | The cube: `sql_table`, dimensions, measures |
| `model/views/orders_view.yml` | One view exposing the cube's members (`includes: '*'`) |

The cube for the project above:

```yaml
cubes:
- name: orders
  sql_table: gold.mart_orders
  dimensions:
  - name: amount
    sql: amount
    type: number
  - name: order_id
    sql: order_id
    type: string
  - name: ordered_day
    sql: ordered_day
    type: time
    meta:
      granularity: day
  # ... order_date, ordered_month / ordered_quarter / ordered_week / ordered_year ...
  measures:
  - name: order_count
    type: count
    meta:
      additivity: additive
      grain: order
  - name: revenue
    type: sum
    sql: amount
    meta:
      additivity: additive
      grain: order
  - name: average_order_value
    type: number
    sql: '{revenue} / NULLIF({order_count}, 0)'
    meta:
      additivity: ratio
```

`sql_table` is the exact `(namespace, relation)` pair the SQLMesh mart model was named
with — same naming policy, same table.

## Dimensions

Every flattened mart column becomes a dimension, typed from its logical type: strings
stay `string`, `int`/`decimal` become `number`, `bool` becomes `boolean`, `date` and
`timestamp` become `time` (`variant` degrades to `string` — Cube has no semi-structured
dimension type). Date-role bucket columns are `time` dimensions with a
`meta.granularity` naming their bucket, so a Cube client can tell `ordered_month` is a
month bucket without parsing the name.

## Additivity metadata

Every measure carries `meta.additivity` and `meta.grain` from the metric's declaration;
a semi-additive measure additionally carries `meta.semi_additive` with its `over`
dimension and `rule`. Cube itself does not enforce these — the meta fields exist so
downstream consumers (and audits of Cube's behavior) can check aggregation against the
declared class instead of trusting it.

## Ratios are calculated, never stored

A non-additive ratio like `average_order_value` never emits as a stored aggregate. It
becomes a calculated `number` measure over its additive components —
`{revenue} / NULLIF({order_count}, 0)` in Cube's member templating — on the one cube
that owns both components. Cube then recomputes it at whatever grain a query groups by,
which is the only way a ratio stays correct. A spec that tries to store a non-additive
metric as a mart measure is already refused at the guardrail stage; the emitter checks
again and raises `UnsupportedByTarget` rather than approximate.

## Pre-aggregations

A [rollup](../reference/spec-schemas.md) — a mart declared under the marts document's
`rollups:` key — becomes a `pre_aggregations` entry on the cube of the mart it names:

```yaml
pre_aggregations:
  - name: order_items_monthly
    type: rollup
    measures:
      - CUBE.gross_revenue
    dimensions:
      - CUBE.order_customer_id
    time_dimension: CUBE.ordered_month
    granularity: month
```

The block lists only the measures the rollup carries and the dimensions it keeps. That
bound is the safety property: a query naming a measure the rollup could not prove
re-aggregable, or a dimension it dropped, cannot match the pre-aggregation, and Cube
answers it from the mart instead. Every measure in the block is one bloomery proved
re-aggregable over the dropped dimensions before writing it — which for `min` and `max`
is not a sum, and is the reason the proof asks about the aggregation rather than
assuming one.

A rollup adds no cube and no view. It is a key inside its parent's document, so nothing
in your Cube model gains a second surface serving the same measures, and no query is
redirected to monthly totals by bloomery. Cube decides at query time whether the
pre-aggregation can serve a request, using its own matching rules.

`time_dimension` appears when the rollup keeps exactly one role-playing date bucket —
Cube allows one per pre-aggregation, and a bucket is the only kept column carrying the
`granularity` that must accompany it. Keep none or several and every kept column is an
ordinary dimension; the pre-aggregation means the same thing and Cube simply cannot
partition it.

No `refresh_key` is emitted, so Cube's default applies. How often Cube rebuilds its
copy is a deployment decision, and bloomery has nothing to base it on.

**Cube materializes its own copy.** A `type: rollup` pre-aggregation is built by Cube
from the parent cube's table into Cube's pre-aggregation store — it does not read the
`gold.mart_order_items_monthly` table the SQLMesh and dbt targets build from the same
rollup. Emit both targets and the same aggregate is materialized twice, by two systems
on two schedules. That is deliberate: the gold model is queryable SQL for anything that
is not Cube, and the pre-aggregation is what makes Cube fast.

## What Cube cannot express

What this target cannot express is refused per construct with
`UnsupportedByTarget`, never approximated: an aggregation outside Cube's closed
set, a metric with no expression, a non-additive metric whose decomposition is
additive rather than a ratio. SCD2 and incremental materialization never reach
this target at all — and that absence is irrelevance, not error: Cube consumes
tables that SQLMesh (or dbt) builds and maintains.

## Notes

- Measure aggregations map to Cube's closed set (`sum`, `count`, `count_distinct`,
  `avg`, `min`, `max`); anything else fails loudly rather than approximate. A *rollup*
  is narrower — `sum`, `count`, `min`, `max` — because those are the four an additive
  claim survives, and only an additive measure can be pre-aggregated.
- A `count` metric emits `type: count` with no `sql` — at the mart's grain, counting
  rows equals counting the metric's key expression.
- A metric served by several marts lands as a measure on exactly one cube — the same
  cheapest-mart ownership rule the planner uses, so the surfaces agree.
- Deploy the Cube YAML together with the SQLMesh artifacts that build the gold tables
  it points at.
- The [`targets/` example](../get-started/examples.md) does exactly that in one command:
  it compiles the semantic model, brings Cube up over the warehouse SQLMesh built, and
  asks it for the same numbers through the REST API.
