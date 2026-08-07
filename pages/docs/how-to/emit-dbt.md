# Emit dbt artifacts

You want the same compiled project as a dbt project — models, sources, snapshots, and
schema tests. Be clear-eyed about what this target is: its job in the architecture is
proving that emission is a real port, not a SQLMesh-shaped hole. It ships minimal but
honest — every SELECT is byte-identical to what the SQLMesh emitter renders, and
anything dbt cannot express faithfully is a loud error, never an approximation. Do not
read it as production-grade dbt scaffolding.

## Compile

```python
from pathlib import Path

from bloomery import Target, compile_project, load_project

entity_model = """
spec_version: 1
entities:
  customer:
    grain: one row per customer
    key: [customer_id]
    scd: type2
    fields:
      customer_id: {type: string, required: true}
      email: {type: string, assert: {not_null: true}}
      segment: {type: string, assert: {enum: [business, consumer]}}
"""

mapping = """
mapping_version: 1
source: crm__customers
target: customer
key:
  customer_id: {from: "$.id", transform: [to_string]}
fields:
  email: {from: "$.email", transform: [to_string]}
  segment: {from: "$.segment", transform: [to_string]}
"""

project = load_project({"entity_model.yaml": entity_model, "mapping.yaml": mapping})
artifacts = compile_project(project, target=Target.DBT, dialect="duckdb")
for artifact in artifacts:
    destination = Path("dbt_repo") / artifact.path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(artifact.content)
```

## What appears

| Path | Kind | What it is |
|---|---|---|
| `dbt_project.yml` | config | Minimal scaffold so `dbt parse` has a project |
| `models/sources.yml` | config | Every bronze relation the entities read |
| `models/silver/<entity>.sql` | model | One model per SCD type 1 entity, with a `{{ config(...) }}` header |
| `snapshots/<entity>_snapshot.sql` | model | One snapshot per SCD type 2 entity (replaces its silver model) |
| `models/gold/mart_<name>.sql`, `models/gold/dim_date.sql` | model | The same gold SELECTs SQLMesh emits |
| `models/schema.yml` | config | Asserts lowered to schema tests |

For the SCD2 project above, the snapshot is dbt's native history mechanism:

```sql
{% snapshot customer_snapshot %}
{{ config(target_schema='silver', unique_key='customer_id', strategy='check', check_cols='all') }}

SELECT
  CAST(id AS TEXT) AS customer_id,
  CAST(email AS TEXT) AS email,
  CAST(segment AS TEXT) AS segment
FROM bronze.crm__customers

{% endsnapshot %}
```

Strategy is `check` over all columns, because the specs declare no updated-at marker
and a `timestamp` strategy would have to invent one.

## Schema tests

`assert:` clauses land in `models/schema.yml`: `not_null` and `enum` map to dbt's
builtin `not_null` and `accepted_values` tests; `min`, `max`, `regex`, and the
path-conflict `reconcile` audit become `dbt_utils.expression_is_true` tests carrying
the same row-level predicate the SQLMesh audits use. Tests for SCD2 entities attach
under `snapshots:` rather than `models:`:

```yaml
version: 2
snapshots:
- name: customer_snapshot
  columns:
  - name: email
    data_tests:
    - not_null
  - name: segment
    data_tests:
    - accepted_values:
        values:
        - business
        - consumer
```

## What dbt cannot express

Adaptation is loud, never silent (the port rule): where dbt has no faithful equivalent,
compilation raises `UnsupportedByTarget` naming the entity and feature. The notable
case is **composite-key SCD2**: dbt snapshot `unique_key` takes a single expression,
and concatenating key parts would be a silent approximation, so:

```text
UnsupportedByTarget: entity 'order_item' is SCD type 2 with composite key
(order_id, line_no) — dbt snapshot unique_key takes a single expression, and
concatenating key parts would be a silent approximation (feature: scd_type_2)
```

The same entity compiles fine to [SQLMesh](emit-sqlmesh.md), whose native SCD2 kind
supports composite keys. Materialization adapts honestly where an equivalent exists:
`full` → `table`; both incremental kinds → `incremental` with the entity key as
`unique_key`, since dbt has no time-range kind and merge-on-key can never silently
duplicate rows.

## Byte-identical SELECTs

The SELECT inside every dbt model is rendered from the same lowered AST through the
same dialect port as the SQLMesh target — only the envelope (Jinja config header vs
`MODEL` block) differs. Diff a dbt model against its SQLMesh counterpart and the query
text matches byte for byte. That equality is the point: it demonstrates the emitters
share one lowering, so a semantics bug cannot exist in only one target's SQL.

## Notes

- The scaffold assumes a profile named `bloomery`; wire your own `profiles.yml`.
- `expression_is_true` tests require the `dbt_utils` package in your dbt project.
- Choose this target when your execution stack is dbt; if you are free to choose,
  [SQLMesh](emit-sqlmesh.md) is the primary target and expresses more of the IR.
