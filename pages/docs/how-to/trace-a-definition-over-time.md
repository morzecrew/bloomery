# Trace a definition over time

[Lineage](trace-lineage.md) tells you what a metric is built from. It cannot tell you that
its filter moved three weeks ago — and that is the other half of "why is this number
different", asked about as often.

`timeline()` answers it. You hand it the spec sets as they stood, oldest first, and it
reports which versions carried the node, which pairs of versions something moved between,
and what moved — named in the vocabulary your specs are written in.

```python
timeline(history, "metric.gross_revenue")
```

Like `lineage()`, it reads no data, opens no connection and touches no warehouse. This is
history of the **spec** — what your documents said, when.

## 1. Assemble the history

This step is yours, for the reason it is yours in
[reproduce a past artifact set](reproduce-a-past-artifact-set.md): only you know where your
specs live. Fetch the text for each version you care about — a git revision, a row per
release in a table, a directory per quarter — and keep them in the order you want reported.

**bloomery never sorts your history.** Order is positional: the sequence you supply is the
sequence you get back, and nothing checks that the first entry is the oldest. That is
deliberate — sorting would mean owning time zones, resolution, clock skew and the
difference between a commit date and an effective date, over data bloomery did not produce
and cannot see.

So a reversed history produces a reversed timeline and no complaint. Order the sequence
before you hand it over.

## 2. Walk one node

```python title="timeline.py"
from bloomery import SpecVersion, load_catalog, load_project, timeline

# whatever step 1 returned: (label, sources, catalog_text) per version, oldest first
history = [
    SpecVersion(
        label=label,
        project=load_project(sources),
        catalog=load_catalog(catalog_text) if catalog_text else None,
    )
    for label, sources, catalog_text in versions
]

walk = timeline(history, "metric.gross_revenue")

for entry in walk.entries:
    print(entry.label, "present" if entry.present else "absent")

for change in walk.changes:
    print(f"{change.before} -> {change.after}  {change.node}")
    for delta in change.facets:
        print(f"    {delta.facet}: {delta.field}  {delta.old} -> {delta.new}")
```

which prints, in full, over the five-version project this documentation is built from:

```text title="what it prints"
v1 present
v2 present
v3 present
v4 present
v5 present
v1 -> v2  order_item.unit_price
    body: expr  shop__order_lines: CAST(price AS DECIMAL(10, 2)) -> shop__order_lines: CAST(price AS DECIMAL(12, 4))
    unit: type  decimal(10,2) -> decimal(12,4)
v3 -> v4  order_item.qty
    metadata: renamed_from  quantity -> None
v3 -> v4  order_item.unit_price
    body: expr  shop__order_lines: CAST(price AS DECIMAL(12, 4)) -> shop__order_lines: CAST(total / qty AS DECIMAL(12, 4))
    body: recipe_id  shop__order_lines: direct -> shop__order_lines: from_total
```

`gross_revenue` is what was asked for and it appears nowhere: its own definition is
identical in all five versions, and every line above is a node beneath it.

Every version is compiled, so a quarter of daily history is ninety compiles. The cost is
yours and so is the choice: start coarse — one entry a month — and narrow only around the
boundary you find.

If a version's project wires steps, hand over the registry that was in force with it:
`SpecVersion(label=..., project=..., catalog=..., steps=registry)`. Without it that version
is refused rather than guessed at, exactly as an ordinary compile is.

## Reading the answer

**`entries` has one row per version you supplied**, present or absent. An absence keeps its
place in the sequence, so you can see *which* version the node was missing from rather than
only that it went missing somewhere.

**`changes` holds one row per pair of adjacent versions whose definition differs.** A node
that never moved gets an empty `changes` and a full `entries` — "this has not changed since
March" is the answer, not a miss. A gap produces no change across it: the node was deleted
and then added, and calling that a change would claim a definition moved across a version it
was not in.

**Every change names the node it is about**, and it is often not the one you asked for —
see [What moved, and where](#what-moved-and-where) below.

## What moved, and where

### The answer covers what the node is built from

A metric whose own definition never moved still reports a different number when a dimension
beneath it is redefined. So the walk covers the node's **upstream closure** — everything
`lineage(..., direction="upstream")` reaches from it — and each change names the node it is
about:

```text
v3 -> v4  order_item.unit_price
    body: expr       shop__order_lines: CAST(price AS ...) -> shop__order_lines: CAST(total / qty AS ...)
    body: recipe_id  shop__order_lines: direct -> shop__order_lines: from_total
```

`metric.gross_revenue` is what was asked for and its own record is identical in every
version; the answer is two hops beneath it. Reporting only the node you named would be the
narrow answer `git log` already gives.

Upstream only, never downstream. A mart that carries your metric as a measure is not part of
what the metric *is*, so a change to it is not an answer to why the metric moved — ask about
the mart.

### The facets

`facets` is never empty: a change with nothing to report is not a change. Each entry names
the facet, the field, and both values where a value has a short spelling.

| Facet | What moved |
| --- | --- |
| `grain` | which rows the definition describes — the grain, the key, the dimensions a rollup keeps |
| `filter` | a metric's declared filter |
| `unit` | what a value is expressed in — its type, unit, tax basis, currency |
| `inputs` | what it is wired to — the fields it reads, a mart's measures, a step's relations |
| `body` | an expression or a recipe changed |
| `additivity` | how values combine — the aggregate, the additivity class, the window, the ratio |
| `quality` | which rows survive a rule — quality, dedupe, quarantine, asserts, `required` |
| `storage` | materialization, partitioning |
| `runtime` | what runs a step — its version, determinism, runtime lock, seed |
| `metadata` | something a reader reads and no number depends on |

`old` and `new` are `None` where the value has no short spelling — a mart's whole column
list, say. The field name is the answer there; rendering a record list into a string would
be the text diff this deliberately is not.

**A rename is not a definition change.** A node whose only difference is what it is called
crosses its boundary with nothing reported, because identity belongs to no facet. Renaming a
metric *another* metric reads does move that other metric's `inputs`, though — what it reads
is now spelled differently, and the walk reports what it sees rather than guessing that the
two spellings are one thing.

## Renames, and why an `id:` pays here

The node id is the name unless the node has adopted an [`id:`](trace-lineage.md#identity-when-the-name-is-not-it).
Across a history that difference is the whole feature:

| The project | A rename reads as |
| --- | --- |
| No `id:` | a delete and an add — two nodes, one timeline each |
| `id:` on both sides | one node across the boundary, `matched_by` is `id` |

Nothing guesses. Matching two definitions by their *shape* would sometimes reconnect a
rename and sometimes weld together two unrelated metrics, and a confidently wrong history is
worse than an honest gap. If you want renames to survive, the remedy is a row in the spec.

`matched_by` is recorded **per pair**, not per timeline, because adoption is something that
happens partway through: mint an id in April and the March boundary is matched by name while
every boundary after it is matched by id. A pair matches by id only when *both* sides carry
one, so adopting an id without renaming stays continuous — and adopting one *and* renaming in
the same version reads as a delete and an add, because nothing connects the two definitions
at all.

### Ask by the spelling your oldest entry uses

The node is found at the **first entry that carries the spelling you asked for**, and
tracked forward from there. That is not symmetric, and the asymmetry is worth knowing before
you read an answer:

| You ask for | Across an adoption partway through |
| --- | --- |
| the **name** | spans it — the name is carried forward and each version translates it to whatever id it has |
| the **id** | the versions *before* that id existed report `absent` |

The walk reads your history once and in order, so it cannot attribute backwards: it has no
way to know, at the first entry, that a spelling appearing three entries later belongs to
the node it is looking at. The earliest entry it can answer about is the one where your
spelling first appears.

The same rule explains the other end. If your project adopted an `id:` *before* the window
you are walking, `metric.gross_revenue` names no node in any of those versions and the whole
timeline reads absent — ask `metric.mtr_7f3a9c` instead, which is also what `bloomery
lineage` calls it.

## Naming your versions

The labels are yours. bloomery carries them into the result, renders them, and compares them
for nothing — there is no format to satisfy, and `"before"` and `"after"` is a legitimate
history of two entries.

When you keep enough of them to want an order, use exactly one spelling:

```text
2026-03-01T00:00:00Z
```

UTC, no offset, no fractional part. **That form and only that form sorts lexicographically
into chronological order**, which is what lets whatever renders your timeline sort it without
parsing anything. "ISO-8601" at large does not: `2026-03-01T00:00:00-01:00` sorts *before*
`2026-03-01T00:00:00Z` and is an hour *later*, and a fractional part reorders against a whole
second. Pick the narrow form once, in whatever writes your labels, and the sort is free
forever.

## What it does not do

**It does not fetch anything.** There is deliberately no `--as-of` and no history adapter —
see [reproduce a past artifact set](reproduce-a-past-artifact-set.md) for why the caller
owns the store.

**It does not interpolate.** Supply March and June and the answer is "it changed between
these two", never "it changed in April". If you need the day, supply the days.

**It does not attribute a change to the data.** A definition that moved is a definition that
moved; whether the number moved *because* of it is a question about rows, and this reads no
rows.

**It is one node's closure, not a query over the graph.** "Every metric that changed in Q1"
is a different question with a different cost. A loop over this function is the honest way to
ask it today.

**It does not say what a change means.** `additivity: additive -> semi_additive` says a
property the compiler tracks moved. Whether that made a number wrong is a judgement about
your business, and the facet is deliberately not worded as a verdict.
