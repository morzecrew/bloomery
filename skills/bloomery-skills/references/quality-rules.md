# Quality rules

Decide in the spec what a *row* does when the data disagrees with the model: field and
row rules, dispositions, dedupe, the reject table and replay, reconcile checks, and the
quality mart.

## Rules judge rows, guardrails judge the spec

| | Guardrails | Quality rules |
|---|---|---|
| When | compile time | run time, in the warehouse |
| Input | the spec | the data |
| Failure | a compile error; nothing is emitted | a disposition per row |

No row is ever silently discarded: every rule carries a disposition, and every row ends
up somewhere countable. Declaring a rule *incoherently* (below) is still a compile-time
refusal.

## Field rules, on the mapping

A field rule sits beside the transform chain that produces the value:

```yaml spec=mapping
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
      - {rule: range, max: 1000000, on_fail: flag}
unmapped: ["$._ingested_at", "$._load_id", "$._source_row_id", "$.operator_note"]
```

The field rules are a closed set: `coercible`, `not_null`, `range`, `length`, `pattern`,
`in_enum`, `in_set`, `unique`, plus the string-only `normalize` and `charset`.

- Bounds are separate rules so `min` and `max` carry different dispositions.
- `in_enum` takes no values: its set is the `enum_map` chain's targets.
- `pattern` speaks a portable regex subset. Lookaround, backreferences, atomic groups,
  inline flags and `\A`/`\Z` are refused at parse, as is an unanchored pattern.
- `normalize` and `charset` on a non-string column are refused at parse.

Every remaining field rule, with the parameters each takes:

```yaml spec=mapping
mapping_version: 1
source: crm__customers
target: customer
key:
  customer_id: {from: "$.id", transform: [to_string]}
fields:
  email:
    from: "$.email"
    transform: [to_string]
    quality:
      - {rule: length, max: 254, on_fail: quarantine}
      - {rule: pattern, regex: "^[^@ ]+@[^@ ]+$", on_fail: flag}
      - {rule: unique, on_fail: quarantine}
  display_name:
    from: "$.name"
    transform: [to_string]
    quality:
      - {rule: normalize, form: nfc, on_fail: flag}
      - {rule: charset, forbid: ["U+200B", "U+FEFF"], on_fail: quarantine}
  tier:
    from: "$.tier"
    transform: [to_string, {enum_map: [G, gold, S, silver]}]
    quality:
      - {rule: in_enum, on_fail: flag}
  country:
    from: "$.country"
    transform: [to_string]
    quality:
      - {rule: in_set, values: [DE, FR, NL], on_fail: flag}
  signups:
    from: "$.signups"
    transform: [to_int]
    quality:
      - {rule: coercible, on_fail: flag}
unmapped: ["$._ingested_at", "$._load_id", "$._source_row_id"]
```

An entity that quarantines or dedupes needs the bronze ingestion columns `_load_id`,
`_ingested_at` and `_source_row_id`. Map them or acknowledge them in `unmapped:`, or the
compile refuses with `IngestionMetadataMissing`.

## Dispositions

`on_fail` is required on every rule; there is no default.

| Write | The row |
|---|---|
| `on_fail: flag` | passes, the rule's name appended to `_quality_flags` |
| `on_fail: quarantine` | moves to `<entity>__reject`, replayable |
| `on_fail: fail` | a blocking audit stops the run |
| `on_fail: repair` | a registered step rewrites the value, recorded in `_quality_repairs`; a row it does not fix takes the rule's `fallback` |

`repair` names its recipe beside it, a step declared in a StepSet (see
[steps-and-macros](steps-and-macros.md)), and a `fallback` that cannot itself be `repair`.
It is refused on `coercible`, `unique` and row rules, which have no value in hand to rewrite:

```yaml fragment
- rule: charset
  forbid: [U+200B, U+FFFD]
  on_fail: repair
  repair: {via: strip_invisible@1, fallback: quarantine}
```

There is no `drop`: quarantine and let retention delete. When a row fails several rules,
`fail` beats `quarantine` beats `flag`, and every failed rule is still recorded
(`failed_rules` on a diverted row, `_quality_flags` on a kept one).

**Coercion is a rule you did not write.** Any `quality:` surface on an entity opts it
into coercion routing: each cast gets an implicit `<field>_coercible` rule that
quarantines a value that will not cast. Override per field with
`{rule: coercible, on_fail: flag}`.

## Row rules, dedupe and retention, on the entity

```yaml spec=entity_model
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
      - {rule: expression, name: stock_level_not_negative, expr: "stock_level >= 0", on_fail: flag}
reconcile:
  - {name: stock_level_matches_snapshot,
     left: "sum(inventory_level.stock_level) by warehouse_id, stock_date",
     right: "inventory_level.stock_level",
     tolerance: "0.01", on_fail: flag}
```

- `expression` reads several columns and needs an authored `name`, which is what lands in
  `_quality_flags` and the quality mart.
- `referential` checks a foreign key through a declared relationship and takes
  `on_missing` (`unknown_member`, `quarantine`, `flag`), not `on_fail`:

  ```yaml fragment
  quality:
    - {rule: referential, via: item_of_order, on_missing: unknown_member}
  ```

  `unknown_member` keeps the orphan and rewrites its key to `'__unknown__'`, so totals
  stay right; it needs a single string-typed key. A relationship pointing back at its own
  entity is refused.
- `dedupe:` keeps one row per key. `keep: latest_by` without `tie_break` is
  `DedupeTieBreakMissing`; any rule weaker than `fail` on a column dedupe orders by is
  `DedupeDispositionConflict`.
- `quarantine:` is required the moment anything can quarantine, implicit coercion
  included (`QuarantineRetentionMissing`). `retention` is an integer with `h`, `d` or
  `w`; months and years are not fixed durations and are refused. A `redact:` path the
  mapping reads is `RedactionConflict`, since replay re-runs the mapping against `raw`.
- `reconcile:` sits at the document root. Each side is `<agg>(<entity>.<column>) by
  <columns>` or `<entity>.<column>`, both keyed alike. `tolerance` is a **quoted**
  decimal. `on_fail: fail` makes it a pipeline-stopping gate.

## What the compile adds

Beside the entity model: `<entity>__reject`, a replay artifact, a blocking
ingestion-metadata audit, a conservation audit (every bronze row lands in the entity,
the reject table, or the deduped count), one comparison model per reconcile check, and
`gold.mart_data_quality`. bloomery emits the replay and never runs it.

## The quality mart

`mart_data_quality` is an ordinary mart; plan requests against it like any other. Five
metric names are reserved and a project metric colliding with one is refused:
`quality_rows_evaluated`, `quality_rows_failed`, `quality_rows_quarantined`,
`quality_rows_deduped`, and the ratio `quality_quarantine_rate`. Group by `rule` for
`quality_rows_failed`; the population counts ride on one `rule = '(entity)'` row per
entity, so `SUM` over rules stays honest.

## Changing a rule

Changing a disposition is `RESTATING`. Relaxing `quarantine` to `flag` needs a
**replay**, not a backfill: the rows sit in the reject table, not in bronze's window.

```python
from bloomery import plan

migration = plan(old_ir, new_ir)
print([change.change_class.value for change in migration.changes])
print("replay:", migration.replay_scope.entities)
```

Apply `replay_scope.entities` in the order given: parents first. A child whose
`referential` rule quarantines joins the replay after its parent; one at
`unknown_member` or `flag` joins `backfill_scope`, and rows bronze no longer holds keep
their rewrite. A tightened rule restates and backfills with an empty replay scope.

## Freshness is a declaration

Every rule judges rows that arrived. A mapping can declare
`freshness: {warn_after: 6h, error_after: 24h}`; the framework measures it. Only dbt has
a source object to carry it, and it needs `quarantine:` or `dedupe:` on the entity.

## Per target and dialect

SQLMesh and dbt emit the full set with the same rows. On dbt the non-row checks are
singular tests that run under `dbt build`, never `dbt run`. Postgres has no `TRY_CAST`
keyword but the port renders an equivalent; Redshift stores `_quality_flags` as a
comma-delimited string instead of an array.

## Published pages

- [Data quality](https://morzecrew.github.io/bloomery/latest/concepts/data-quality/)
- [Add quality rules to an entity](https://morzecrew.github.io/bloomery/latest/how-to/add-quality-rules/)
