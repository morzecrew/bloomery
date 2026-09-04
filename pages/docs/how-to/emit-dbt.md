# Emit dbt artifacts

You want the same compiled project as a dbt project — models, sources, snapshots,
schema tests and singular tests. Be clear-eyed about what this target is: its job in the
architecture is proving that emission is a real port, not a SQLMesh-shaped hole. It
ships honestly — every SELECT is byte-identical to what the SQLMesh emitter renders, and
anything dbt cannot express faithfully is a loud error, never an approximation. It now
carries the whole data-quality surface too: reject tables, replay, reconcile models and
the quality mart. Do not read that as parity — Tier 3 Python steps stay refused, and the
list below says exactly which cells are still unequal.

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
| `macros/bloomery_expression_is_true.sql` | audit | The generic test the `min`/`max`/`regex` asserts name, emitted only when one does |
| `macros/generate_schema_name.sql` | config | Keeps `+schema:` meaning the naming policy's namespace, not dbt's `<target>_<custom>` |
| `tests/<check>.sql` | audit | One singular test per check with no schema-test shape — see below |
| `models/silver/<entity>__reject.sql` | model | The quarantined rows, incremental on `reject_id` |
| `macros/replay_<entity>.sql` | replay | The replay statements, as a `run-operation` — see below |
| `models/silver/<check>__reconcile.sql` | model | One comparison table per `reconcile:` check |
| `models/gold/mart_data_quality.sql` | model | One row per rule evaluation, stamped with dbt's `invocation_id` |

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
path-conflict `reconcile` audit become `bloomery_expression_is_true` tests carrying
the same row-level predicate the SQLMesh audits use. That test is bloomery's own
macro, emitted into `macros/` beside the models — not `dbt_utils`', which would leave
the project declaring a test no `dbt compile` can build until someone runs `dbt deps`
against the network. Tests for SCD2 entities attach under `snapshots:` rather than
`models:`:

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

## Singular tests, and when they run

A check that groups, joins or aggregates is not a row predicate, so no `schema.yml`
entry can carry it. dbt's own artifact for one is a **singular test**: a `.sql` file
under `tests/` whose query returns the rows that fail. bloomery writes one per check
that needs it —

| Check | File |
|---|---|
| A merged entity's collision audit | `tests/<entity>_source_collision.sql` |
| The ingestion-metadata audit (`dedupe:`) | `tests/<entity>_ingestion_metadata.sql` |
| A mart `assert:` clause | `tests/<mart>_<assertion>.sql` |
| A `coverage:` check | `tests/<check>_coverage.sql` |
| A step output's `on_fail: fail` rules | `tests/step_<output>_<rule>.sql` |
| A step output's declared references | `tests/step_<child>_<column>_references_<parent>.sql` |

— each naming its model through `ref()`, so dbt orders the test after the model it
judges. `on_fail` becomes dbt's `severity`: `fail` → `error`, `flag` → `warn`.

### The operator contract

Two sentences, and you need both. A reader given only the first has the wrong model of
this target.

> **On dbt, a blocking check blocks under `dbt build`.** A flagging check does not
> block, unless the run passes `--warn-error`, which promotes it.

`dbt run` does not run tests at all, so a project built with `dbt run` materializes its
models with every bloomery check unevaluated. **`dbt build` is a requirement of this
target, not a recommendation.** That is the cost of dbt expressing a check as a separate
node rather than as part of the model's materialization — it is also true of every
`not_null` this emitter has shipped since the beginning, which is why the merge is not
refused for it.

The mirror case is the one people miss: `--warn-error` promotes every warning to an
error, so a `flag` check — which the disposition vocabulary defines as "record it and
keep the row" — stops the build under that flag. Neither direction is a mapping error.
Both are the same fact, that on dbt a test's consequence is chosen by the invocation
rather than by the artifact. SQLMesh needs neither sentence, because there the audit
carries `blocking false` and no flag overrides it.

## What dbt cannot express

Adaptation is loud, never silent (the port rule): where dbt has no faithful equivalent,
compilation raises `UnsupportedByTarget` naming the entity and feature. **This target is
still partial, and singular tests did not change that** — what they closed is a gap in
bloomery's dbt emitter, not a gap in dbt.

Two constructs are refused, and they are unrelated to each other:

- **Tier 3 Python steps** — dbt's Python models run only on Snowflake, BigQuery and
  Databricks, and none of those is a bloomery dialect. Not a quality question, and not
  one that closes while those are the dialects.
- **`on_fail: quarantine` on a *step output*** — refused on **every** target, SQLMesh
  included: a step output has no ingestion-metadata key to build a reject table from, and
  a `steps:` wiring has no `quarantine:` block to state retention in. It shares a word
  with the entity-level `quarantine:` below and nothing else.

`quarantine:` and `reconcile:` on an entity were refused here until the reject model,
the replay macro and the comparison model landed. They are not refused now — see
[Replaying on dbt](#replaying-on-dbt).

And the notable adaptation case is **composite-key SCD2**: dbt snapshot `unique_key`
takes a single expression, and concatenating key parts would be a silent approximation,
so:

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

## Replaying on dbt

A quarantined row that a corrected delivery fixes is admitted by **replay**, and on dbt
replay is a macro you run:

```bash
dbt run --select silver.order_line__reject   # rebuild the reject table first
dbt run-operation replay_order_line
```

Rebuild first, always. Replay re-runs the *current* mapping against the rows the reject
table holds, so a reject table built before the correction landed still says the row
fails.

It is a macro rather than a `.sql` file you could paste into a client, and that is
forced rather than chosen: the statements name their relations through `{{ ref(...) }}`,
which resolves inside dbt's Jinja and nowhere else. A loose file would be runnable by
neither dbt, which does not execute files it was not given as models, nor by a SQL
client, which sees braces. The three statements run inside one explicit transaction,
because a failure between admitting the row and stamping its reject row resolved would
leave it counted in both places.

**bloomery still executes nothing.** The macro is text until you run it, exactly as the
SQLMesh replay file is.

Two things the reject table does that are worth knowing before you operate it:

- **A re-delivery keeps `first_seen`.** The incremental model reads its own current rows
  and preserves the first sighting while `last_seen` advances — which is what the
  retention window measures from.
- **`--full-refresh` loses resolved reject rows.** The rebuild sees only what is
  *currently* quarantined, so rows replay already resolved do not come back. This is
  accepted rather than prevented: the history derives from bronze that a full refresh is
  rebuilding anyway, and a model that refused to full-refresh would be one you could not
  recover.

## Byte-identical SELECTs

The SELECT inside every dbt model is rendered from the same lowered AST through the
same dialect port as the SQLMesh target — only the envelope (Jinja config header vs
`MODEL` block) differs. Diff a dbt model against its SQLMesh counterpart and the query
text matches byte for byte. That equality is the point: it demonstrates the emitters
share one lowering, so a semantics bug cannot exist in only one target's SQL.

## Notes

- The scaffold assumes a profile named `bloomery`; wire your own `profiles.yml`.
- Choose this target when your execution stack is dbt; if you are free to choose,
  [SQLMesh](emit-sqlmesh.md) is the primary target and expresses more of the IR.
- The [`targets/` example](../get-started/examples.md) runs `dbt build` on emitted
  artifacts and checks the resulting mart row for row against SQLMesh's — the claim that
  one spec set yields one answer, measured rather than asserted.
