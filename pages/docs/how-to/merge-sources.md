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
| `scd: type2` | The collision check below would fire on every key holding versions from two sources. Telling a version from a collision means reading the validity interval, and the union's lowering does not — the interval is modelled now (see [as-of joins](../concepts/wide-marts.md#historical-dimensions-need-an-anchor)), but the merge audit does not consult it |
| Two mappings declaring **different** rules for a column they both produce | The rules run once over the merged relation, so a set taken from one mapping would silently drop what the others wrote. See [cleaning a merged entity](#cleaning-a-merged-entity) |
| Some but not all of the mappings producing a column recording a `direct:` path | The `__direct` shadow would be NULL for the other source's rows, which is indistinguishable from a genuinely NULL direct value — so the reconciliation audit either reports a disagreement that is not there or quietly stops checking. See [a direct path on a merged entity](#a-direct-path-on-a-merged-entity) |

Types need no separate check: each mapping's transform chain is already checked against the
entity's *declaration*, so two mappings cannot disagree about a column's type without both
failing first.

## A direct path on a merged entity

[`direct:`](../concepts/guardrails.md#path-conflict-the-guardrail-that-does-not-raise) records that a source carries a field
directly *as well as* through a recipe, and the compiler emits both plus a reconciliation
audit rather than picking one. On a merged entity each source names its own path:

```yaml
# mapping_shopify.yaml
fields:
  net_price:
    recipe: from_total
    from: {line_total: "$.total", quantity: "$.quantity"}
    direct: "$.price"

# mapping_woo.yaml — same recipe, same conflict, a different path
fields:
  net_price:
    recipe: from_total
    from: {line_total: "$.line_gross", quantity: "$.qty"}
    direct: "$.unit_amount"
```

You get **one** `net_price__direct` column and **one** reconciliation audit, and each
branch of the union projects its own extraction — `$.price` is read off the Shopify
relation only, which is the only relation that has it.

What both mappings have to agree on is *whether* the conflict exists. Every mapping that
produces the column records a path, or none does.

A source that does not map the field at all is outside that: it already gets a typed NULL
for the derived column, it gets one for the shadow too, and the audit compares NULL with
NULL and reports nothing. There is no path to require there — `direct:` is part of a
field mapping, and that source has none.

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

## Cleaning a merged entity

A merged entity takes the whole [data-quality system](add-quality-rules.md): `quality:`
rules on the entity and on its mappings' fields, `dedupe:`, and `quarantine:` with its
reject table and replay. Nothing about declaring them differs from a single-source entity.

What differs is underneath, and it is worth knowing because it decides what the compiler
asks of you. **The rules are one set, evaluated once over the merged relation. Their inputs
are per source.** A coercion rule compares the produced column against the raw paths it
reads, and the two shops read different paths; an `in_enum` rule admits what the chain's
`enum_map` maps, and the two shops map different spellings. Each branch computes its own
verdict below the union and the rule reads the result, so one rule can judge rows from
sources that share no column name at all.

That is why **every mapping of a merged entity must declare the same rules for a column
they both produce**. A rule is written on a mapping's field, and two mappings writing
different ones is not a merge rule to invent — it is two contradictory statements, refused
with both documents named. A column only *one* mapping produces is a different case and is
not refused: its rules join the entity's set, and on the branch that maps nothing the
coercion marker reads "no sources, no evidence" rather than reporting every one of that
source's rows as a failed cast.

Two more things happen on their own:

- **`dedupe:` sorts by `_source`** immediately before the row identity. That identity is
  unique within *one* source relation, so without the extra term two rows from different
  shops on one key compare equal and the survivor is undefined.
- **The collision audit reads the union**, not the finished model. With `dedupe:` in
  between, a key held by both shops is collapsed to one row before the model exists — an
  audit reading the model would find one source per key and pass, on exactly the data it
  is there to refuse.

`assert:`, `references:` and `coverage:` were never affected: they are declared on the
entity model and never read a mapping. For a required field on a merged entity,
`assert: {not_null: true}` is the runtime check you want — `required:` proves every mapping
*declares* the field, and says nothing about what its source path returns per row.

!!! note "One target"

    `quarantine:` needs a reject model, which the dbt emitter does not lower — merged or
    not. A merged entity that quarantines compiles for SQLMesh; one that only flags
    compiles for both.

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

Both SQL targets. The `UNION ALL` needs nothing dbt lacks — it is the same shared SELECT,
and the dbt emitter declares one `source()` per mapping — and the collision audit that
makes the merge correct is emitted as a
[singular test](emit-dbt.md#singular-tests-and-when-they-run), `tests/<entity>_source_collision.sql`,
carrying `severity='error'` because that audit is blocking and not configurable to
anything weaker.

One thing to know if you build with dbt: a dbt test is a separate node, so the collision
audit runs under `dbt build` and **not** under `dbt run`. Running the project with
`dbt run` materializes the union with its correctness condition unevaluated. The
[operator contract](emit-dbt.md#the-operator-contract) states this for every check
bloomery emits to dbt, not only this one.

## See also

- [The `lakehouse/` example](../get-started/examples.md) — this merge, built into Iceberg
  tables and queried; `just break-it` gives both shops the same key and shows the
  collision audit stopping the plan
- [Resolve identities across systems](resolve-identities.md) — different key spaces, which
  needs matching rather than merging
- [Add quality rules](add-quality-rules.md) — the system a merged entity joins the same
  way any other entity does
- [Evolve a spec](evolve-a-spec.md) — how `plan()` classifies the changes above
