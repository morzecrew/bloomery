# Close an open decision

A metric is unreachable because some canonical field is unavailable, and closing that gap
is a decision bloomery will not make for you. `SpecEvidence.unresolved` states each one
you have left: which field, which edit closes it, what the catalog offers, and which
metrics are waiting on it.

```python
from bloomery import Gap, Stage, evaluate, load_catalog, load_project

evidence = evaluate(load_project(sources), catalog=load_catalog(catalog_text))

for decision in evidence.unresolved:
    where = f"{decision.entity}.{decision.field}" if decision.field else decision.entity
    print(f"{decision.canonical}: {decision.gap.value} at {where}")
    print(f"  blocks {', '.join(decision.blocks)}")
    print(f"  the catalog declares {[option.id for option in decision.options]}")
```

Read `stage_reached` first, as with every tuple on `SpecEvidence` — see
[Assess a spec](evaluate-a-spec.md). An empty `unresolved` means "nothing open" only where
the resolve stage got far enough to say so.

## The loop

Recording a choice is one edit to one document, and the next report is computed from the
result. That is the whole cycle:

1. Read the report.
2. Make the one edit its first entry names.
3. Recompile, and read the report again.

It ends. Each entry names a canonical field some metric requires, and the set of those is
fixed by your catalog and your metrics — neither of which this loop edits. A recipe binds
**alias slots to source paths**, never to other canonical fields, so no choice you record
can add work.

## The two gaps need two different edits

`gap` is the field that tells them apart, and it is the reason this report exists: without
it both arrive as the same unreachable metric.

`Gap.UNLINKED` — nothing in your entity model carries `canonical: <name>`. The edit is an
entity-model one:

```console
$ bloomery resolve specs/
Open decisions (1)
  cogs  unlinked  order_item  direct  blocks: margin
```

`entity` is where the field belongs, from the catalog. Declare it and link it:

```yaml
    fields:
      cogs: {type: "decimal(12,4)", canonical: cogs}
```

That edit **does not close the decision** — it moves it. There was no field to record a
recipe on, and now there is:

```console
$ bloomery resolve specs/
Open decisions (1)
  cogs  unmapped  order_item.cogs  direct  blocks: margin
```

`Gap.UNMAPPED` — a field carries the link and no mapping produces it. This is the entry a
choice closes. `field` names what to map, and the edit is a mapping field:

```yaml
fields:
  cogs:
    recipe: direct
    from: {cogs: "$.unit_cost"}
```

The keys under `from:` are the recipe's `requires` — its alias slots — and the values are
the source paths that fill them. Bind every slot and no others, or the resolve stage
refuses with the list of what it expected.

```console
$ bloomery resolve specs/
Reachable (4)
  average_order_value
  gross_revenue
  margin
  order_count

Unreachable (0)
```

### When a step produces the relation

`gap` is read off your entity model, and a step wiring is the third place a canonical link
can live. Where the relation comes from a step (RFC 0017's `canonical:` block), an
`UNLINKED` entry names the entity the catalog declares the field for — which is still where
it belongs — but the edit goes in `steps.yaml`, beside the output that produces the column:

```yaml
    canonical:
      customer: {canonical_id: customer_ref}
```

The report cannot tell you that, because which relation a step produces is a fact about the
registry you assembled rather than about your specs. Where an entry names an entity no
mapping builds, look at the wiring.

An entry with no `options` is one the catalog declares no derivation for. That is a fact
about the catalog and never about your data: bloomery reads no data, so whether the source
paths exist is a question only you can answer.

## `options` are what the catalog declares, not what bloomery suggests

The recipes come back in **catalog order**, which is authored — a catalog orders them by
reliability — and bloomery neither ranks nor scores nor picks, including where there is
exactly one. Taking `options[0]` every round is a choice your code made, and the spec will
record it under your name.

Sorting the list yourself destroys the only ordering information in it. The CLI prints the
ids and leaves each recipe's `requires` to `--format json`, which carries the whole value:

```console
$ bloomery resolve specs/ --format json
```

```json
{
  "unresolved": [
    {
      "blocks": ["margin"],
      "canonical": "cogs",
      "entity": "order_item",
      "field": null,
      "gap": "unlinked",
      "options": [{"expr": null, "id": "direct", "requires": ["cogs"]}]
    }
  ]
}
```

## What you already decided

`SpecEvidence.provenance` is the other half of a loop's memory: one entry per mapped field,
saying whether it comes straight from a source column, through a recipe — with the id you
recorded — or from no canonical link at all. `mapping` names the document it was read
from, which is the document you would edit.

```json
{"entity": "order_item", "field": "unit_price", "mapping": "mapping_order_items", "provenance": "recipe", "recipe_id": "from_total"}
```

Use it to avoid re-deriving your own history from the mapping documents you wrote.

Where several mappings build one entity, a field they both produce gets **one entry per
mapping**, so two documents implementing one column differently are two rows rather than
one — the answers for a field stay next to each other, sorted by document name.

## When the report is empty and something is still blocked

Three cases, and they are worth telling apart.

**A refusal in the resolve stage.** A recipe id that does not exist, or one whose
`requires` are not bound, is refused before reachability is computed — so there is no
report that round. The refusal names the fix and lists the ids the catalog does have; fix
it and recompile.

**A merged entity.** Where several mappings build one entity, any one of them might be the
document that closes the gap, and the report does not guess between them: those decisions
are left out rather than reported un-actionably, and the metric blocked on one is still in
`unreachable`. `provenance` does name mappings, so it will tell you which documents build
the entity — start from the one whose source carries the field.

**Nothing requires it.** A canonical field no metric needs is not work, and never appears.
