# Merge sources into one entity

Point several mappings at one entity when the sources share one key space with disjoint
keys: two shops on one platform, a region-sharded table, a migration halfway done.

## Merge or match?

Ask whether the two systems could ever issue the **same identifier for different things**.

- They could not (keys are comparable and do not overlap): **merge**, on this page.
- The CRM says `C-1001` and billing says `AC-77` for one person: **match**. No union can
  help; that is identity resolution, a Tier 3 step, with its own reference.

## What a project writes

Nothing new. The entity is declared once, and each mapping names it as its `target:`.

```yaml spec=entity_model
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

```yaml spec=mapping
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

```yaml spec=mapping
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

The two read entirely different paths: the entity is what the data means, the mappings are
how each system spells it.

## What comes out

One silver model, one `UNION ALL` branch per source, ordered by **source relation name**
(not by filename), plus a `_source` column naming the relation each row came from.

- Row order is not claimed: `UNION ALL` is a bag.
- `_source` exists only on merged entities, but the name is reserved everywhere.
- A field only one source maps (`gift_note` above) is `CAST(NULL AS …)` on the other
  branches. That needs no acknowledgement.

## What the compiler refuses

All at once, so one round trip fixes the spec:

| Refusal | Why |
|---|---|
| A mapping missing part of the entity's `key:` | a union on a partial key means nothing |
| A mapping missing a `required: true` field | the column would be NULL for that source's rows |
| Two mappings reading the **same** relation | branch order ties; write one mapping instead |
| `scd: type2` on the merged entity | the collision audit cannot tell versions from collisions |
| Two mappings declaring **different** quality rules for a column both produce | rules run once over the union; one set would silently drop the other |
| Some but not all mappings recording `direct:` for a column | the shadow would be NULL for one source, hiding or inventing disagreements |

Types need no separate check: each chain is already checked against the entity's declaration.

## The collision audit

Compilation has no data, so it cannot prove the key sets are disjoint. A generated audit
does, for merged entities only: it groups by **every** key column and fails when a key has
rows from more than one distinct `_source`. It is **blocking**, with no setting to weaken
it, because a key in two sources is either duplication or an accidental shared key space,
and both double-count.

A key duplicated *within* one source is ordinary duplication, which `dedupe:` owns. If the
audit fires, the fix is usually a match, not silencing the merge.

> A project can pass every compile-time check and fail on its first run. Disjointness is a
> run-time guarantee.

On dbt the audit is a singular test, `tests/<entity>_source_collision.sql`, with
`severity='error'`. It runs under `dbt build`, **not** `dbt run`:

```bash
dbt build --select order_line+
```

## A direct path on a merged entity

Each source names its own `direct:` path for a recipe field. You get one
`<field>__direct` column and one reconciliation audit; each branch projects its own path.

```yaml fragment
# mapping_shopify.yaml
fields:
  net_price:
    recipe: from_total
    from: {line_total: "$.total", quantity: "$.quantity"}
    direct: "$.price"
# mapping_woo.yaml: same recipe, a different path
fields:
  net_price:
    recipe: from_total
    from: {line_total: "$.line_gross", quantity: "$.qty"}
    direct: "$.unit_amount"
```

Every mapping producing the column records a path, or none does. A source that does not map
the field at all is outside the rule.

## Cleaning a merged entity

A merged entity takes the whole quality system: entity `quality:`, field rules, `dedupe:`,
`quarantine:` with reject table and replay, on SQLMesh and dbt alike. Underneath:

- rules are one set evaluated once over the merged relation, with per-source inputs; so
  every mapping must declare the **same** rules for a column they both produce;
- `dedupe:` sorts by `_source` before the row identity, so two rows from different shops on
  one key do not tie;
- the collision audit reads the union, before `dedupe:` could collapse a collision;
- each reject row records the mapping that produced it, so replay re-runs that mapping.

`required:` proves every mapping declares a field. For a per-row guarantee on a merged
entity add `assert: {not_null: true}` on the entity field.

## How it shows up in `plan()`

| Change | Class |
|---|---|
| A mapping added to an entity that had one | `ADDITIVE`; `_source` appears |
| A mapping added to an already-merged entity | `ADDITIVE` |
| A mapping removed, two or more remaining | `RESTATING` |
| A mapping removed, leaving one | `RESTATING`; `_source` is dropped |
| A mapping's key expression changed | `BREAKING` |

Adding a source needs no backfill but moves every metric over the entity, and `plan()` lists
those metrics under downstream impact.

```bash
bloomery plan deployed/ proposed/
```

## Published pages

- [Merge sources into one entity](https://morzecrew.github.io/bloomery/latest/how-to/merge-sources/)
