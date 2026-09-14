# Adopt a project that already has a semantic layer

If your team already runs MetricFlow, the relationships between your tables are written
down. You should not have to type them again to get bloomery's proofs — and if you do type
them again, the two copies will disagree eventually.

`bloomery import` reads them out. It prints a `relationships:` block; you paste it into your
entity model and commit it.

```bash
bloomery import metricflow target/semantic_manifest.json specs/ \
    --entity order_items=order_item \
    --entity customers=customer
```

The relationships it produces carry `imported_from:`, which is how everything downstream
knows a human here did not read them.

## 1. What it takes and what it refuses

An importer is only worth having if it is exact. This one reads **one** thing — a pair of
entity elements, one `foreign` and one `primary` or `unique`, in two different semantic
models — and turns it into one `many_to_one`:

```yaml
semantic_models:
  - name: order_items
    entities:
      - {name: customer, type: foreign, expr: customer_id}
  - name: customers
    entities:
      - {name: customer, type: primary, expr: customer_id}
```

Both halves are stated in the artifact, so nothing is inferred. Where either half is
missing, the import refuses rather than emitting a weaker edge — there is no weaker edge to
emit:

| The artifact says | What happens |
| --- | --- |
| a `foreign` element no other model declares `primary` or `unique` | refused: the target is not unique, so the edge determines nothing |
| two models declaring one element `primary` | refused: the target is ambiguous |
| an element with no `expr` | refused: no column to join on |
| an `expr` like `lower(customer_id)` | refused: a relationship joins columns, not expressions |
| a `natural` element | ignored — it is a key that is *not* unique, so no cardinality follows |

!!! note "Why not dbt"

    A dbt `relationships` test says every value of a column appears in a target column. It
    says nothing about that target being *unique*, and reading it as `many_to_one` would
    invent the fact that makes the edge worth having. A dbt importer becomes exact the
    moment it requires a `unique` or `primary_key` test on the named target too.

## 2. Name the entities

Two things in a MetricFlow manifest are called entities and they are not the same thing. A
**semantic model** is the relation — that is what a bloomery entity corresponds to. An
**entity element**, under `entities:`, is a join identity that several models share, and it
corresponds to nothing in bloomery.

So the endpoints come from `semantic_models[].name`, and those are named for your warehouse
tables while your bloomery entities are named for your business. `--entity` says which is
which:

```bash
--entity order_items=order_item --entity customers=customer
```

Without it the two must be spelled identically. Nothing guesses the pairing — not by
comparing key columns, not by singularising a name — because a wrong guess here is a
relationship between the wrong two things, and it would be wrong silently.

Every refusal names the model it is about, so running it once with no flags is a reasonable
way to find out what to map.

## 3. Paste it in

The output is a fragment, not a document. A project holds exactly one entity model, so
append the block to the one you have:

```yaml
relationships:
  - name: item_of_order          # yours
    from: order_item
    to: order
    via: {order_id: order_id}
    cardinality: many_to_one

  - name: order_item__customer   # pasted
    from: order_item
    to: customer
    via:
      customer_id: customer_id
    cardinality: many_to_one
    imported_from: metricflow:target/semantic_manifest.json
```

The name is generated, and it is a name your marts can refer to like any other — a
`flatten:` step naming a relationship names this one by the name above. Rename it if you
prefer; nothing downstream depends on the generated spelling.

A relationship your project already declares with the same `from`, `to` and `via` is **not**
printed — two statements that agree are not a contradiction. One that disagrees about
cardinality *is*, and the import refuses naming both, because neither side wins by default.

## 4. Overlay the rest, then check

Import gives you structure. Grain, additivity, units and currency are yours to write, and
that is the point — they are the facts nobody else's artifact states precisely enough to
close a proof with.

```bash
bloomery check specs/
```

## What `imported_from:` costs you

A relationship read out of an artifact is graded weaker than one you wrote, and a consumer
can say it wants the stronger kind:

```yaml
marts:
  finance_ledger:
    requires_evidence: locked
```

That mart is now refused if any of its measures rests on a column reached through an
imported relationship, and the refusal names the artifact so you can go and read it:

> mart `finance_ledger` requires 'locked'; its measures (`net_revenue`) rest on column
> `customer_region`, carried by `order_item__customer` — read out of
> `metricflow:target/semantic_manifest.json` rather than written here.

The fix is in the message: author the relationship here and drop its `imported_from:`, or
let the mart accept `assumed`. Both are real answers — the first says a person checked it,
the second says the artifact is trusted. What bloomery will not do is let the difference go
unrecorded.

!!! warning "`imported_from:` is a claim, not a check"

    It says the *mapping rule* was exact, not that the artifact was honest. Nothing here
    verifies that the manifest matches the warehouse, and nothing re-checks a committed
    block against a manifest that has since changed.

    It is also load-bearing in a direction that is easy to miss. Written by hand on a
    relationship you authored, it lowers that relationship's grade — and any strict consumer
    above it is then refused with `InsufficientEvidence`, naming an artifact nobody read it
    out of. That is the safe direction, and still a wrong fact.

## Next

- [Assess a spec before it compiles](evaluate-a-spec.md) — what `check` is built on
- [Annotate a spec](annotate-a-spec.md) — owners, classifications and the other things
  bloomery records but does not verify
