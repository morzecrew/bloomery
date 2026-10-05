# Emit dbt

Compile a project to a dbt project and run it: what appears, how checks become tests,
why `dbt build` is required, replay, schema changes on incremental models, and what dbt
cannot express.

## Compile

```console
$ bloomery compile specs/ --target dbt --dialect duckdb --out build/dbt
```

Compile into a **clean** directory: `--out` deletes nothing, so a stale replay macro or a
hand-written file would sit beside the new project. From Python, the library returns
artifacts and never touches the filesystem:

```python
from pathlib import Path

from bloomery import Target, compile_project, load_project

project = load_project({"entity_model.yaml": entity_model, "mapping.yaml": mapping})
for artifact in compile_project(project, target=Target.DBT, dialect="duckdb"):
    destination = Path("dbt_repo") / artifact.path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(artifact.content)
```

The dialect shapes SQL only, never which artifacts exist; see [dialects](dialects.md).
Choose dbt when your stack is dbt. If you are free to choose, SQLMesh expresses more.

## What appears

| Path | What it is |
|---|---|
| `dbt_project.yml` | minimal scaffold, with `vars: {bloomery_fingerprint: …}`; assumes a profile named `bloomery` |
| `models/sources.yml` | every bronze relation read, with declared freshness |
| `models/silver/<entity>.sql` | one model per SCD type 1 entity |
| `snapshots/<entity>_snapshot.sql` | one snapshot per SCD type 2 entity, replacing its model |
| `models/gold/mart_<name>.sql`, `models/gold/dim_date.sql` | the gold layer |
| `models/schema.yml` | `assert:` clauses as schema tests |
| `macros/bloomery_expression_is_true.sql` | the generic test `min`/`max`/`regex` asserts use (no `dbt deps` needed) |
| `macros/generate_schema_name.sql` | keeps `+schema:` meaning the naming policy's namespace |
| `tests/<check>.sql` | singular tests for checks that are not row predicates |
| `models/silver/<entity>__reject.sql`, `macros/replay_<entity>.sql` | quarantine and replay |
| `models/silver/<check>__reconcile.sql`, `models/gold/mart_data_quality.sql` | reconcile and the quality mart |

Every SELECT matches the SQLMesh target's byte for byte once dbt's `{{ ref() }}` and
`{{ source() }}` names resolve to the relations SQLMesh spells out; those references and
the envelope are all that differ.
Snapshots use `strategy='check'` over all columns, because the specs declare no
updated-at marker. Materialization maps `full` → `table` and both incremental kinds →
`incremental` with the entity key as `unique_key`.

## Checks become tests

- `not_null`, `enum` → dbt's `not_null` and `accepted_values` in `schema.yml`; under
  `snapshots:` for SCD2 entities.
- `min`, `max`, `regex` and the path-conflict reconcile → `bloomery_expression_is_true`.
- Grouping or joining checks → one singular test each: a merged entity's
  `<entity>_source_collision`, `<entity>_ingestion_metadata` for `dedupe:`, a mart
  `assert:`, a `coverage:` check, and a step output's `on_fail: fail` rules and declared
  references.
- `on_fail: fail` → `severity: error`; `on_fail: flag` → `severity: warn`.

### The operator contract

> On dbt, a blocking check blocks under `dbt build`. A flagging check does not block,
> unless the run passes `--warn-error`, which promotes it.

`dbt run` runs no tests, so every bloomery check goes unevaluated: **`dbt build` is a
requirement of this target.** And `--warn-error` turns a `flag` (record and keep) into a
stopped build. Schedule accordingly:

```bash
dbt build
dbt source freshness
```

Freshness from a mapping's `freshness: {warn_after: 6h, error_after: 24h}` lands in
`sources.yml` on `CAST(_ingested_at AS TIMESTAMP)`, and runs **only** under
`dbt source freshness`, never `dbt build`. It is refused unless the entity declares
`quarantine:` or `dedupe:`. `2w` is emitted as fourteen days.

## Replay

A quarantined row that a corrected mapping now accepts comes back by replay, which on
dbt is a macro:

```bash
dbt run --select silver.order_line silver.order_line__reject   # rebuild both first
dbt run-operation replay_order_line
```

Rebuild the entity **and** its reject table from the same checkout first, or the reject
table still says the row fails. The macro refuses before its first statement when the
project's `bloomery_fingerprint` var is not the fingerprint it was emitted under (a
leftover macro), or when a column it writes is missing (rebuild with `--full-refresh` on
an incremental model). On every dialect but Databricks its statements run in one
transaction; Databricks has none, so each commits on its own and a failure partway leaves
the earlier ones committed.

A re-delivery keeps `first_seen`. A `--full-refresh` of the reject table loses rows replay
already resolved; that is accepted.

## Schema changes on incremental models

Every incremental model, entities and reject tables, carries
`on_schema_change='fail'`. After a spec change adds, drops or renames a field, the next
`dbt run`/`dbt build` of that model fails with "schema out of sync" rather than building
without the column. Rebuild from scratch:

```bash
dbt build --full-refresh -s order_line order_line__reject
```

An entity with no `quarantine:` has no reject table; name the entity alone. You need not
discover this from a failed run: `bloomery plan` prints this command beside every field
added, dropped or renamed on an incremental entity, without changing the change's class.

```console
$ bloomery plan deployed/ proposed/
```

## What dbt cannot express

Refused loudly as `UnsupportedByTarget`, never approximated:

- **Tier 3 Python steps.** bloomery emits no Python-model wrapper.
- **Composite-key SCD2.** A snapshot's `unique_key` is one expression, and concatenating
  key parts would be an approximation. The same entity compiles on SQLMesh.

```text
UnsupportedByTarget: entity 'order_item' is SCD type 2 with composite key
(order_id, line_no) — dbt snapshot unique_key takes a single expression
```

`on_fail: quarantine` on a step output is refused on every target, not only dbt.

## Across projects

An imported relation is referenced as `{{ ref('<upstream export name>', '<model>') }}`
and the compile writes `dependencies.yml` naming the upstream project. The first argument
is the `name:` the upstream's exports publish, not your alias; importing from an upstream
with no export `name:` is refused on this target. Both projects must be compiled under
the same naming policy, which bloomery cannot check.

```console
$ bloomery compile platform/ --emit-ir /tmp/platform.json --out build/platform
$ bloomery compile shop/ --target dbt --upstream platform=/tmp/platform.json --out build/shop
```

## Published pages

- [Emit dbt artifacts](https://morzecrew.github.io/bloomery/latest/how-to/emit-dbt/)
