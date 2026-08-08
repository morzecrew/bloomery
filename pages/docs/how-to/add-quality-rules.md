# Add quality rules to an entity

You have an entity whose source data misbehaves — values that will not cast, duplicate
snapshots, orphan references — and you want each of those decided in the spec rather
than in hand-written SQL beside the generated models. Declare the rules, pick a
disposition for each, and compile.

The running example is a warehouse-management feed: a WMS re-sends the same
warehouse/day stock snapshot whenever an operator corrects it, and corrections sometimes
arrive with a negative or uncastable level. Why each part is there is explained in
[Data quality](../concepts/data-quality.md); this page is the wiring.

## Declare field rules on the mapping

Field rules live beside the transform chain that produces the value, because that is
where a reader asks "and what if this does not cast?".

```yaml
mapping_version: 1
source: wms__stock_levels
target: inventory_level
key:
  warehouse_id: {from: "$.warehouse", transform: [to_string]}
  stock_date: {from: "$.day", transform: [{parse_date: ISO8601}]}
fields:
  stock_level:
    from: "$.on_hand"
    transform: [to_int]
    quality:
      - {rule: not_null, on_fail: fail}
      - {rule: range, min: 0, on_fail: quarantine}
unmapped: ["$._ingested_at", "$._load_id", "$._source_row_id", "$.operator_note"]
```

The catalogue is closed — `coercible`, `not_null`, `range`, `length`, `pattern`,
`in_enum`, `in_set`, `unique` — and every entry is listed with its parameters in the
[spec schemas reference](../reference/spec-schemas.md#field-quality-rules). Two rules
that come up immediately:

- Bounds are separate rules, so `min` and `max` can carry different dispositions.
  Writing `{rule: range, min: 0, on_fail: quarantine}` beside
  `{rule: range, max: 1000000, on_fail: flag}` is the normal shape, not a workaround.
- `in_enum` takes no values. Its admissible set *is* the `enum_map` chain's targets, so
  widening an enum means editing one list rather than two that can drift.

The `unmapped:` list is doing real work here. An entity that quarantines or dedupes
requires the bronze ingestion-metadata columns `_load_id`, `_ingested_at`, and
`_source_row_id`; listing them as the acknowledged tail is how a mapping states they
exist without mapping them. Omit them and compilation raises
`IngestionMetadataMissing`.

## Choose a disposition

`on_fail` is required on every rule — there is no default to inherit. Pick by what you
want to happen to the row:

| You want | Write | The row |
|---|---|---|
| To know, without changing anything | `on_fail: flag` | passes, its rule name appended to `_quality_flags` |
| The row held back, recoverably | `on_fail: quarantine` | moves to `inventory_level__reject`, replayable |
| The run stopped | `on_fail: fail` | a blocking audit fires, whatever else the row tripped |

There is no `drop`, deliberately. If you want rows gone, quarantine them and let
retention delete them — a deletion with a paper trail.

If a row fails several rules at once, severity decides: `fail` beats `quarantine` beats
`flag`. A `fail` rule's audit reads the rows the pipeline evaluated rather than the
finished model, so a row that quarantines *and* trips a blocking rule still stops the
run. Every rule the row failed is recorded either way — in `failed_rules` if it was
diverted, in `_quality_flags` if it was kept — so nothing about the failure is lost by
the routing.

## Add row rules on the entity

Rules that read more than one column, or another entity, belong on the entity:

```yaml
spec_version: 1
entities:
  inventory_level:
    grain: one row per warehouse per day
    key: [warehouse_id, stock_date]
    fields:
      warehouse_id: {type: string, required: true}
      stock_date: {type: date, required: true}
      stock_level: {type: int}
    dedupe: {keep: latest_by, field: _ingested_at, tie_break: [_load_id]}
    quarantine: {retention: 90d, redact: ["$.operator_note"]}
    quality:
      - {rule: expression, name: stock_level_not_negative,
         expr: "stock_level >= 0", on_fail: flag}
```

`expression` takes a boolean predicate over the entity's own columns plus an authored
`name`, because that name reaches `_quality_flags` and the quality mart where a
generated one would be unreadable.

To check a foreign key, name a declared relationship instead:

```yaml
    quality:
      - {rule: referential, via: item_of_order, on_missing: unknown_member}
```

`referential` carries `on_missing` — `unknown_member`, `quarantine`, or `flag` — not
`on_fail`. Use `unknown_member` when you want aggregates to stay correct: orphans keep
their row, their foreign key is rewritten to the reserved `'__unknown__'` member, and
the problem shows up in the dashboard instead of as a quiet shortfall. It requires a
string-typed foreign key; a non-string key is refused at compile time rather than given
a sentinel that could collide with a real value.

If the relationship's `to` side is the entity itself, compilation refuses it: the rule
lowers to a `LEFT JOIN` inside that entity's own model, and a model cannot join the
table it is being built from. Model the referenced side as a separate entity built from
the same source, or use a `reconcile` check.

## Deduplicate before the rules run

`dedupe:` keeps one row per entity key. It is not optional to say how ties break:

```yaml
    dedupe: {keep: latest_by, field: _ingested_at, tie_break: [_load_id]}
```

Omitting `tie_break` under `keep: latest_by` is the compile error
`DedupeTieBreakMissing` — two rows sharing a timestamp would make the winner arbitrary,
and a nondeterministic model makes backfills disagree with the original runs. The order
finishes with `_source_row_id`, so it is total whatever you supply.

Because the dedupe columns decide which row survives, `coercible` is forced to `fail` on
any field named by `dedupe.field` or `tie_break`. Declaring something weaker there is
`DedupeDispositionConflict`; write `on_fail: fail` or order by a different column.

## Set retention, and redact what you must not keep

Retention is required the moment anything can quarantine, because reject rows hold raw
source payloads:

```yaml
    quarantine: {retention: 90d, redact: ["$.operator_note"]}
```

`retention:` is a positive integer with one unit suffix — `h`, `d`, or `w`. Months and
years are absent on purpose: they are not fixed durations, and a retention window that
means something different in February is a legal problem rather than a convenience.

Leave the block off and compilation tells you precisely why, naming the rules that made
it necessary:

```text
GuardrailError: 1 error(s):
  - entity_model: entities.inventory_level.quarantine: entity 'inventory_level' has
    quarantine dispositions (stock_date_coercible, stock_level_coercible,
    stock_level_range_min, warehouse_id_coercible) but no quarantine: block — reject
    rows hold raw source payloads, and therefore PII, so retention is required and
    never defaulted (RFC 0016 §5.6). Note that the implicit coercible rule carries the
    quarantine default (§5.2), so an entity with any quality: surface has one even
    when nothing spells it. Fix: add quarantine: {retention: 90d}
```

Those `*_coercible` rules are the point of the message: you never wrote them. Declaring
any `quality:` surface opts the entity into coercion routing, and a failed cast
quarantines by default. Override it per field with an explicit
`{rule: coercible, on_fail: flag}` if that is not what you want.

`redact:` removes JSONPaths from `raw` and `key_values` at write time. It may not
intersect a path the mapping reads — `RedactionConflict` otherwise — because replay
re-runs the mapping against `raw`, and a redacted path is gone by then.

## Wire a reconcile check

A reconcile check catches a *correct formula over wrong data*: it compares two declared
sides and reports the disagreement. It sits at the document root, beside `entities:`,
because it belongs to no single entity.

```yaml
reconcile:
  - {name: stock_level_matches_snapshot,
     left: "sum(inventory_level.stock_level) by warehouse_id, stock_date",
     right: "inventory_level.stock_level",
     tolerance: "0.01", on_fail: flag}
```

`on_fail` decides whether the check's audit stops the run. `flag` reports and carries on
— which is usually what you want, since a disagreement is exactly when someone needs to
read the comparison table. `fail` blocks: this is the pipeline-stopping gate to reach for
when a rule's disposition is not enough.

Both sides come from a closed grammar — `<agg>(<entity>.<column>) by <columns>` or a
plain `<entity>.<column>` — and must key on the same columns, since the two sides join
on their keys. `tolerance` must be a **quoted** decimal: an unquoted `0.01` is a YAML
float, and floats never reach the IR.

This particular check is the executable statement of what dedupe promises. Exactly one
row survives per (warehouse, day), so the per-key sum must equal the per-key value.

## Compile and see what you got

```python
from bloomery import Target, compile_project, load_project

project = load_project({"entity_model": ENTITY_MODEL, "mapping": MAPPING})
artifacts = compile_project(project, target=Target.SQLMESH, dialect="duckdb")
print(sorted(artifact.path for artifact in artifacts))
```

```text
['audits/inventory_level_conservation.sql',
 'audits/inventory_level_ingestion_metadata.sql',
 'audits/inventory_level_stock_level_not_null.sql',
 'audits/stock_level_matches_snapshot_reconcile.sql',
 'models/gold/mart_data_quality.sql',
 'models/silver/inventory_level.sql',
 'models/silver/inventory_level__reject.sql',
 'models/silver/stock_level_matches_snapshot__reconcile.sql',
 'replay/inventory_level.sql']
```

Four of those are new because of the quality surface: the reject model, the blocking
audit on the ingestion-metadata contract (a null metadata column, a repeated
`_source_row_id`, or an `_ingested_at` that will not cast to timestamp), the
conservation audit (every bronze row lands in exactly one of the entity, an unresolved
reject, or the deduped count), and the replay merge. The replay artifact is not a model
— bloomery emits it and never runs it. Apply it yourself, as one unit of work, when you
have relaxed a rule and want the quarantined rows back.

## Read the quality mart

Every rule evaluation lands in `gold.mart_data_quality`, which is an ordinary mart. Ask
it the same way you ask anything else:

```python
from bloomery import (
    LruManifestHydrator, MetricFlowPlanner, MetricRequest, build_project_ir,
)
from bloomery.naming import DefaultNaming

ir = build_project_ir(project, catalog=catalog)

naming = DefaultNaming()
planner = MetricFlowPlanner(LruManifestHydrator(naming), naming=naming)

query = planner.plan(
    ir,
    MetricRequest(
        metrics=("quality_quarantine_rate", "quality_rows_quarantined"),
        dimensions=("entity", "run_month"),
    ),
    dialect="duckdb",
)
print(query.mart, [column.name for column in query.columns])
```

```text
data_quality ['entity', 'run_month', 'quality_quarantine_rate', 'quality_rows_quarantined']
```

Five metric names are reserved for it — `quality_rows_evaluated`,
`quality_rows_failed`, `quality_rows_quarantined`, `quality_rows_deduped`, and the
`quality_quarantine_rate` ratio. A project metric colliding with one of them is a
compile error, since they share one flat namespace.

Group by `rule` to ask what one predicate did — that is `quality_rows_failed`'s grain.
The other three counts describe the entity's population, so they ride on one accounting
row per entity (`rule = '(entity)'`) rather than being repeated on every rule row. That
is what keeps `SUM` honest: a repeated population count returns a multiple of the truth
as soon as you aggregate over rules.

## Check what a rule change costs before you ship it

Changing a disposition is a `RESTATING` change, and relaxing `quarantine` to `flag`
needs a **replay** rather than a backfill — the affected rows sit in the reject table,
not in bronze's incremental window:

```python
from bloomery import plan

migration = plan(old_ir, new_ir)
for change in migration.changes:
    print(change.change_class.value, change.subject, change.detail)
print("replay:", migration.replay_scope.entities)
```

```text
restating quality:stock_level_range_min quality rule changed (disposition)
replay: ('inventory_level',)
```

Backfilling without replaying would leave those rows quarantined forever. Feed
`replay_scope.entities` to whatever applies the `replay/<entity>.sql` artifacts.

## Notes

- **Targets.** SQLMesh emits the full set. The dbt emitter raises `UnsupportedByTarget`
  for the reject/replay artifacts and for `reconcile` — flag-only surfaces still emit,
  since `_quality_flags` is the same shared `SELECT` for both. Cube consumes the quality
  mart like any other mart.
- **Dialects.** Postgres has no `TRY_CAST`, so an entity carrying `coercible` rules —
  which is any entity with a `quality:` surface — cannot compile for it.
  `UnsupportedByTarget`, loudly, rather than a `CAST` that aborts the run where the spec
  said quarantine.
- **`run_id` is declared but NULL** in the quality mart on the pinned SQLMesh, which
  exposes no run-identifier macro. `run_date` comes from `@execution_ds`.
- **`pattern` uses a portable regex subset** — character classes, anchors, quantifiers;
  no lookaround, no named groups. Each pattern is validated against every registered
  dialect at compile time, because a regex that works on DuckDB and means something else
  on Trino is exactly the bug worth refusing.

Once rules are declared, [Evolve a spec safely](evolve-a-spec.md) covers the rest of the
change classes a spec edit can produce.
