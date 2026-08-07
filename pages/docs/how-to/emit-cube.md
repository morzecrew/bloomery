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
    additivity: non_additive
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
      additivity: non_additive
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

## What Cube capabilities mean

Each target declares which IR features it supports, and the Cube emitter's declared set
is intentionally small: the semantic features (non-additive, semi-additive metadata,
role-playing dimensions). SCD2 and incremental materialization are *absent* — and that
absence is irrelevance, not error: Cube consumes tables that SQLMesh (or dbt) builds
and maintains, so materialization concerns never reach this target. Only a feature a
target claims to support but cannot express honestly raises `UnsupportedByTarget`.

## Notes

- Measure aggregations map to Cube's closed set (`sum`, `count`, `count_distinct`,
  `avg`, `min`, `max`); anything else fails loudly rather than approximate.
- A `count` metric emits `type: count` with no `sql` — at the mart's grain, counting
  rows equals counting the metric's key expression.
- A metric served by several marts lands as a measure on exactly one cube — the same
  cheapest-mart ownership rule the planner uses, so the surfaces agree.
- Deploy the Cube YAML together with the SQLMesh artifacts that build the gold tables
  it points at.
