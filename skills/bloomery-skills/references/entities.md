# Entities

Declare an entity in the EntityModel: grain, key, typed fields, the sources that feed it,
SCD type, materialization, retention and arrival lag, dedupe, relationships, and the key
audit bloomery generates.

## The EntityModel document

Exactly one per project, keyed by `spec_version: 1`. It says what one tenant's data
*means*, independent of how any source spells it.

```yaml spec=entity_model
spec_version: 1
entities:
  order:
    grain: one row per order
    key: [order_id]
    partition_by: [days(order_date)]
    fields:
      order_id: {type: string, required: true}
      customer_id: {type: string}
      total_amount: {type: "decimal(12,2)"}
      order_date: {type: date, assert: {not_null: true}}
      status: {type: string, assert: {enum: [placed, paid, refunded]}}
  order_item:
    grain: one row per line on an order
    key: [order_id, line_no]
    fields:
      order_id: {type: string, required: true}
      line_no: {type: int, required: true}
      unit_price: {type: "decimal(12,4)", canonical: unit_price}
      quantity: {type: int, canonical: quantity, assert: {min: 0}}
relationships:
  - {name: item_of_order, from: order_item, to: order, via: {order_id: order_id}, cardinality: many_to_one}
```

| Top-level key | Required | Holds |
|---|---|---|
| `spec_version` | yes | `1` |
| `entities` | yes | map name → entity |
| `relationships` | no | declared joins, read by marts and the fan-out guardrail |
| `reconcile` | no | cross-entity checks (a quality concern) |

Entity names `canonical`, `exposure`, `mart`, `metric`, `source` and `step` are reserved:
they are lineage node-id prefixes.

## Entity keys

| Key | Required | Meaning |
|---|---|---|
| `grain` | yes | prose; appears in error messages and explanations |
| `key` | yes | field names, authored order kept |
| `fields` | yes | map name → field |
| `scd` | no | `type1` (default) or `type2` |
| `partition_by` | no | bare columns or `days(col)`, `months(col)`, `years(col)`, `hours(col)` |
| `materialization` | no | `full`, `incremental_by_key`, `incremental_by_partition` |
| `dedupe` | no | keep one row per key |
| `quarantine` | no | reject-table policy with `retention` |
| `arrival_lag` | no | how late a row may land |
| `quality` | no | row rules (`expression`, `referential`) |
| `owner`, `grants` | no | annotations |

## Fields

| Key | Meaning |
|---|---|
| `type` | `string`, `int`, `bool`, `date`, `timestamp` (always UTC), `variant`, `decimal(p,s)` |
| `required` | every mapping targeting the entity must supply it |
| `canonical` | link to a catalog canonical field: makes it count toward metric reachability and carries the catalog's `unit`, `tax_basis` and `currency` onto the column |
| `assert` | `min`, `max`, `not_null`, `enum`, `regex`: audits that observe, never route rows |
| `renamed_from` | a one-shot rename annotation read by `plan()` |
| `classification` | `public`, `internal`, `pii`, `secret` |

`metric_time` and the generated columns (`_quality_flags`, `_quality_ok`,
`_quality_repairs`, `_load_id`, `_ingested_at`, `_source_row_id`, `has_quality_flags`,
`_source`) are reserved field names.

## Sources

An entity is fed by mappings: each Mapping names it as its `target:`. One mapping is the
ordinary case. Several mappings naming one target make the entity the `UNION ALL` of them,
for sources in one shared key space with disjoint keys. Sources with different key spaces
need identity resolution (a step), not a merge.

## SCD type

`scd: type1` (the default) holds the current row per key. `scd: type2` keeps history: one
row per version per key, with `valid_from` / `valid_to` columns on both SQLMesh and dbt.
A historical entity changes how marts read it: a mart flattening it needs `as_of:` or
`reading: current`, and a mart based on it needs `reading: current`. A merged entity may not
be `type2`.

## Materialization

**bloomery derives defaults; it never infers intent.** With `partition_by` set the default
is `incremental_by_partition`, otherwise `full`. Write `materialization:` to override. An
`scd: type2` entity takes the target's SCD form whatever `materialization:` says: SQLMesh's
`SCD_TYPE_2_BY_COLUMN` kind, and a dbt snapshot.

```yaml spec=entity_model
spec_version: 1
entities:
  event:
    grain: one row per tracked event
    key: [event_id]
    partition_by: [days(event_date)]
    materialization: incremental_by_partition
    arrival_lag: 30h
    fields:
      event_id: {type: string, required: true}
      event_date: {type: date}
```

On Trino, `days(col)` is emitted as `day(col)` for the Iceberg connector. A Trino Hive
catalog takes no transform: partition by a `date` column instead.

## Arrival lag

`arrival_lag` (a duration such as `6h`, `30h`, `2d`) says how late a row may land after its
interval ran. It is allowed only on an `incremental_by_partition` entity at `scd: type1`.
On SQLMesh it sets `interval_unit 'day'` and `lookback` to the lag in whole days rounded up
(`30h` is `lookback 2`). dbt needs nothing: its incremental merge already catches late rows.

## Retention: quarantine

An entity whose rules can send rows to a reject table must say how long reject rows live.
There is no default, because reject rows hold raw source payloads.

```yaml fragment
quarantine:
  retention: 90d
  redact: ["$.operator_note"]
```

Durations take `h`, `d` or `w`; months and years are refused. `redact` removes whole
top-level bronze columns from stored payloads: a path's first segment names the column, so
`$.customer.email` strips all of `customer`, siblings included. A redacted column may hold
no path the mapping reads (`RedactionConflict`).

## Dedupe

```yaml fragment
dedupe:
  keep: latest_by
  field: updated_at
  tie_break: [revision]
```

Keeps one row per `key`, the latest by `field`. `tie_break` is mandatory in practice: its
absence is `DedupeTieBreakMissing`. The order finishes on `_source_row_id`, so the winner is
unique by construction.

`dedupe:` or `quarantine:` requires the bronze ingestion columns `_load_id`, `_ingested_at`
and `_source_row_id`. They are reserved, so the mapping states they exist by listing them
under `unmapped:`; otherwise `IngestionMetadataMissing`.

## The key audit

A declared `key:` is a `LOCKED` premise: every proof that a mart holds one row per key
rests on it. Because uniqueness is a property of data the compiler cannot see, an entity
with a key and **no** `dedupe:` gets a generated blocking audit, `<entity>_key_unique`, that
stops the run when two rows share a key: among current versions (`valid_to IS NULL`) on an
`scd: type2` entity, among all rows otherwise. With `dedupe:`, duplicates are resolved
instead and the audit is not emitted.

## Relationships

A relationship *is* its join: `name`, `from`, `to`, `via` (a non-empty map from-column →
to-column) and `cardinality` (`many_to_one`, `one_to_one`, `one_to_many`). Marts flatten
through them by name, and a mart flatten through `one_to_many` is refused as `FanoutRisk`.
`imported_from:` is written by `bloomery import`, never by hand: it grades the relationship
`ASSUMED`.

## Published pages

- [Spec schemas: EntityModel](https://morzecrew.github.io/bloomery/latest/reference/spec-schemas/)
- [Specs and the catalog](https://morzecrew.github.io/bloomery/latest/concepts/specs-and-catalog/)
