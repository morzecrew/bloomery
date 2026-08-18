# Merge sources into one entity

Two shops on one platform. A region-sharded table. A migration halfway done. In each case
several source relations describe the same kind of thing, in **one shared key space**, and
you want one entity rather than `order_shopify` and `order_woo`.

Point two mappings at the same `target:` and bloomery emits a `UNION ALL`. There is no new
syntax, because there is nothing new to say.

!!! info "Different key spaces? You want the other page."

    This page is for sources whose keys are already comparable and **do not overlap**. If
    the CRM issues `C-1001` and billing issues `AC-77` for the same person, no union can
    help you — that is matching, and it lives in
    [Resolve identities across systems](resolve-identities.md).

## What a project writes

Nothing new. The entity is declared once:

```yaml title="entity_model.yaml"
spec_version: 1
entities:
  order_line:
    grain: one row per line on an order, across both shops
    key: [order_id, line_no]
    fields:
      order_id: {type: string, required: true}
      line_no: {type: int, required: true}
      sku: {type: string, required: true}
      quantity: {type: int}
      gift_note: {type: string}
```

and two mappings name it as their `target:`:

```yaml title="mapping_platform.yaml"
mapping_version: 1
source: shopify__order_lines
target: order_line
key:
  order_id: {from: "$.order.id", transform: [to_string]}
  line_no: {from: "$.position", transform: [to_int]}
fields:
  sku: {from: "$.variant.sku", transform: [to_string]}
  quantity: {from: "$.quantity", transform: [to_int]}
  gift_note: {from: "$.properties.gift_note", transform: [to_string]}
```

```yaml title="mapping_legacy.yaml"
mapping_version: 1
source: woo__order_lines
target: order_line
key:
  order_id: {from: "$.order_number", transform: [to_string]}
  line_no: {from: "$.item_index", transform: [to_int]}
fields:
  sku: {from: "$.product_sku", transform: [to_string]}
  quantity: {from: "$.qty", transform: [to_int]}
```

The two read entirely different paths. That is the point: the entity model is what the data
*means*, and the mappings are how each system happens to spell it.

## What comes out

One silver model, one branch per source, in **lexicographic order of source relation**:

```sql
SELECT
  CAST(properties ->> '$.gift_note' AS TEXT) AS gift_note,
  ...,
  'shopify__order_lines' AS _source
FROM bronze.shopify__order_lines
UNION ALL
SELECT
  CAST(NULL AS TEXT) AS gift_note,
  ...,
  'woo__order_lines' AS _source
FROM bronze.woo__order_lines
```

Three things in that output are worth naming.

**Branch order is the source relation's, not the document's.** It has to be fixed for the
same specs to produce the same bytes, and a filename is not a stable thing to sort on.

**Row order is not claimed.** `UNION ALL` is a bag. Nothing downstream may assume one
shop's rows come first; where an order matters, it comes from declared ordering columns.

**`_source` is a real column.** It carries which relation a row came from, and it exists
only on merged entities. It is reserved everywhere, though — you cannot name a field
`_source` even in a project that merges nothing, because a name that is legal until a
second mapping arrives is a trap laid for the change that adds one.

## The one field only one shop has

`gift_note` above is mapped by the platform and not by the legacy shop, and it lowers to
`CAST(NULL AS TEXT)` for the legacy shop's rows. That is legitimate and needs no
acknowledgement — a *misspelled* field name is already a compile error against the entity
model, so silence here can only mean the honest case.

What it does not need is a narrower branch. Every branch projects every column of the
entity, because a `UNION ALL` whose arms disagree on arity is not a narrower branch; it is
invalid SQL.

## What the compiler refuses

All of it at once, so you fix a spec in one round trip rather than one error per compile.

| Refusal | Why |
|---|---|
| A mapping missing part of the entity's `key:` | A union on a partial key has no meaning |
| A mapping missing a `required: true` field | The merge would NULL-fill a required column for that one source's rows, and the entity would look internally inconsistent rather than externally broken |
| Two mappings reading the **same** relation | Branch order needs a total order, and two branches on one relation tie. Express two disjoint row sets of one table as one mapping with a filter |
| `scd: type2` | The collision check below would fire on every key holding versions from two sources, and telling a version from a collision needs validity columns nothing models yet |
| Any quality rule, `dedupe:` or `quarantine:` | See [the limits](#what-a-merged-entity-cannot-do-yet) |

Types need no separate check: each mapping's transform chain is already checked against the
entity's *declaration*, so two mappings cannot disagree about a column's type without both
failing first.

## The one thing only the warehouse can check

Compilation has no data, so it cannot know the key sets are disjoint. A generated audit
does, and it is emitted for merged entities only:

```sql title="audits/order_line_source_collision.sql"
SELECT order_id, line_no, COUNT(DISTINCT _source) AS sources
FROM @this_model
GROUP BY order_id, line_no
HAVING COUNT(DISTINCT _source) > 1
```

It is **blocking**, and there is no setting that makes it otherwise. A key in two sources
means one of two things — the sources genuinely duplicate a row, or they share a key space
by accident — and both are refusals. Flagging it would let a double-counted entity into the
warehouse marked merely suspect.

Two details it is easy to get wrong, and this does not:

- It groups by **every** key column. Grouping a composite key by its first component alone
  would merge distinct keys and block correct data.
- It counts **distinct sources**. A key duplicated *within* one source is ordinary
  duplication, which `dedupe:` owns, and this audit stays out of it.

If it fires, the answer is usually not to make it stop. Overlapping keys need a match, not a
merge — go to [Resolve identities across systems](resolve-identities.md).

!!! note "Disjointness is a run-time guarantee, not a compile-time one"

    A project can pass every compile-time check and fail on its first run. That is the
    correct split — it is the same one `dedupe` and `referential` live with — but do not
    read a successful compile as proof the sources are disjoint.

## What a merged entity cannot do yet

A merged entity is outside the data-quality system for now: no `quality:` rules on the
entity or on its mappings' fields, no `dedupe:`, no `quarantine:`. Each is refused at
compile time with a message saying why.

The reason is not squeamishness. Quality rules are lowered **per mapping** — a generated
coercion rule carries one mapping's source paths into a rule the merged relation evaluates
once, and the other source's bronze relation need not have the column it names. Shipping
that would emit a check that is wrong rather than absent.

`assert:`, `references:` and `coverage:` are unaffected: they are declared on the entity
model and never read a mapping. For a required field on a merged entity, `assert: {not_null:
true}` is the runtime check you want — `required:` proves every mapping *declares* the
field, and says nothing about what its source path returns per row.

## How it shows up in `plan()`

No new change class:

| Change | Class |
|---|---|
| A mapping added to an entity that had one | `ADDITIVE` — new rows, and the `_source` column appears |
| A mapping added to an already-merged entity | `ADDITIVE` — new rows only |
| A mapping removed, two or more remaining | `RESTATING` — same columns, fewer rows |
| A mapping removed, leaving one | `RESTATING`, and `_source` is dropped |
| A mapping's key expression changed | `BREAKING` — it redefines what a row *is* |

Adding a source is not a silent schema move: `plan()` names the relation and says the
`_source` column is arriving, which is exactly the kind of change an operator should see
before it lands.

It also reports the affected metrics. A source addition is `ADDITIVE` and needs no
backfill, but it is the one additive change that moves numbers already on a dashboard — the
entity's row population grew, so every metric over it reports differently the day the
second shop lands. Those names show up in `downstream_impact`, in both directions: adding a
source and removing one each report the metrics whose values move.

## Target support

SQLMesh only, for now. The `UNION ALL` itself needs nothing dbt lacks — and the dbt emitter
does declare one `source()` per mapping — but the collision audit has no honest dbt
equivalent, and the merge is not correct without it. Compiling a merged entity for dbt
refuses, naming the audit and pointing at the target that emits it, rather than quietly
shipping an unguarded union.

## See also

- [The `lakehouse/` example](../get-started/examples.md) — this merge, built into Iceberg
  tables and queried; `just break-it` gives both shops the same key and shows the
  collision audit stopping the plan
- [Resolve identities across systems](resolve-identities.md) — different key spaces, which
  needs matching rather than merging
- [Add quality rules](add-quality-rules.md) — the system a merged entity is currently
  outside of
- [Evolve a spec](evolve-a-spec.md) — how `plan()` classifies the changes above
