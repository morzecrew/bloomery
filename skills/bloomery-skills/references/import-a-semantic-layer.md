# Import a semantic layer

A team that already runs MetricFlow has its table relationships written down. `bloomery
import` reads them out of the semantic manifest and prints a `relationships:` block to
paste into the entity model, so the two copies cannot drift apart by retyping. Imported
relationships carry `imported_from:` and are graded weaker than ones a person wrote.

## Run it

```console
$ bloomery import metricflow target/semantic_manifest.json specs/ \
    --entity order_items=order_item \
    --entity customers=customer
```

| Argument | Meaning |
|---|---|
| `metricflow` | the artifact kind; MetricFlow is the only one |
| `target/semantic_manifest.json` | the manifest to read |
| `specs/` | the project directory, read to skip relationships already declared |
| `--entity MODEL=ENTITY` | repeatable: which bloomery entity a semantic model names |

It prints the block and writes nothing. Exit `1` is a refusal naming the model at fault.

## What it reads and what it refuses

It reads exactly one shape: a pair of entity elements, one `foreign` and one `primary` or
`unique`, in two different semantic models, which becomes one `many_to_one`:

```yaml fragment
semantic_models:
  - name: order_items
    entities:
      - {name: customer, type: foreign, expr: customer_id}
  - name: customers
    entities:
      - {name: customer, type: primary, expr: customer_id}
```

Both halves are stated in the artifact, so nothing is inferred. Where one is missing it
refuses rather than emit a weaker edge:

| The manifest says | Result |
|---|---|
| a `foreign` element no other model declares `primary` or `unique` | refused: the target is not unique |
| two models declaring one element `primary` | refused: the target is ambiguous |
| an element with no `expr` | refused: no column to join on |
| an `expr` such as `lower(customer_id)` | refused: a relationship joins columns |
| a `natural` element | ignored: a non-unique key implies no cardinality |

There is no dbt importer: a dbt `relationships` test says nothing about the target being
unique, so reading it as `many_to_one` would invent the fact that makes the edge useful.

## Name the entities

A MetricFlow **semantic model** is a relation; it corresponds to a bloomery entity. An
**entity element** under `entities:` is a shared join identity and corresponds to nothing in
bloomery. Endpoints come from `semantic_models[].name`, named for warehouse tables, while
bloomery entities are named for the business. `--entity order_items=order_item` pairs them.
Without it the names must match exactly; nothing guesses by key column or by singularising.

Every refusal names its model, so a first run with no `--entity` flags lists what to map.

## Paste the block

The output is a fragment, not a document. A project has exactly one entity model; append
the block to its `relationships:`:

```yaml fragment
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

- **The name is a key.** A mart's `flatten:` step, an entity's referential rule and the plan
  diff cite a relationship by name. Replacing one you wrote with an imported one means
  repointing everything that named the old; renaming the generated name means renaming it
  everywhere in the same change. A dangling name surfaces only at compile.
- **Agreement is skipped.** A relationship already declared with the same `from`, `to` and
  `via` is not printed.
- **Disagreement refuses.** One that differs in cardinality is refused naming both;
  neither side wins by default.

See [entities](entities.md) for the relationship fields and [marts](marts.md) for
`flatten:`.

## Overlay the rest, then check

Import gives structure only. Grain, additivity, units and currency are yours to write;
they are the facts no other artifact states precisely enough to close a proof.

```console
$ bloomery check specs/
```

## What `imported_from:` costs

A relationship read from an artifact is evidence of grade `ASSUMED`, not `LOCKED`. A
consumer that wants only authored premises says so:

```yaml fragment
marts:
  finance_ledger:
    requires_evidence: locked
```

That mart is refused with `InsufficientEvidence` when any of its measures rests on a column
reached through an imported relationship, and the refusal names the artifact:

```text
mart `finance_ledger` requires 'locked'; its measures (`net_revenue`) rest on column
`customer_region`, carried by `order_item__customer` — read out of
`metricflow:target/semantic_manifest.json` rather than written here.
```

Two real fixes: author the relationship and drop its `imported_from:` (a person checked
it), or let the mart accept `assumed` (the artifact is trusted). See
[guardrails-and-evidence](guardrails-and-evidence.md).

`imported_from:` is a claim, not a check. It says the mapping rule was exact, not that the
manifest matches the warehouse, and nothing re-checks a committed block against a manifest
that later changed. Written by hand on an authored relationship, it lowers that
relationship's grade and refuses strict consumers above it, naming an artifact nobody read.

## Steps

1. `dbt parse` (or your MetricFlow build) so `semantic_manifest.json` is current.
2. `bloomery import metricflow <manifest> specs/` with no flags; read the refusals.
3. Add one `--entity MODEL=ENTITY` per semantic model whose name differs.
4. Append the printed block to the entity model's `relationships:`.
5. Write grain, metrics and marts on top; `bloomery check specs/` until it exits `0`.
6. Decide per strict mart: author the edge, or accept `assumed`.

Documentation: [import a semantic layer](https://morzecrew.github.io/bloomery/latest/how-to/import-a-semantic-layer/).
