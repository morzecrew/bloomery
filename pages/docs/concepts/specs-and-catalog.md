# Specs and the catalog

This page explains bloomery's domain model: how the Catalog holds domain knowledge for a
whole vertical, how a tenant's EntityModel resolves against it, how a Mapping records —
rather than makes — derivation decisions, and how a MetricSet classifies every measure
by additivity. It is the model everything downstream (resolution, guardrails, marts,
planning) operates on.

The split that makes the model work is vertical-level versus tenant-level:

![The Catalog links canonical fields into the EntityModel; a bronze source reaches it through a Mapping; the MetricSet and the Marts read the entity](../_diagrams/light/specs-and-catalog.svg#only-light){ data-src="../_diagrams/light/specs-and-catalog.svg#only-light" }
![The Catalog links canonical fields into the EntityModel; a bronze source reaches it through a Mapping; the MetricSet and the Marts read the entity](../_diagrams/dark/specs-and-catalog.svg#only-dark){ data-src="../_diagrams/dark/specs-and-catalog.svg#only-dark" }

## Catalog: the vertical-level domain graph

The Catalog is the piece most spec-compiler designs miss, and it is what makes the rest
tractable. One Catalog exists per vertical (e-commerce retail, logistics, …), written by
the platform operator — never by tenants. It holds:

- **Canonical fields** — the domain's named quantities, each with a logical type and,
  for monetary fields, a `unit` and `tax_basis`. These two annotations drive the
  [guardrails](guardrails.md): a field without them is `unknown`, and `unknown` in
  additive arithmetic is a compile error.
- **Recipes, ordered by reliability** — alternative derivation paths to a canonical
  field. A recipe is "an alternative path to a node in the graph": if `unit_price`
  isn't present directly, it can come from `line_total / quantity`.
- **Canonical relationships** — the entity graph with cardinalities
  (`order_item → order`, `many_to_one`), which the grain guardrail and mart flattening
  both depend on.
- **Metric templates** — reusable metric definitions with grain and additivity built in.
- **The date dimension** — bloomery owns it, and it is defined here, once. The SQLMesh
  emitter builds the `gold.dim_date` table from this definition, and the MetricFlow
  semantic manifest declares its time spine pointing at that same relation. One
  definition, two emissions, no drift.

```yaml
catalog_version: 3
vertical: ecom_retail

canonical_fields:
  discount:
    entity: order_item
    type: decimal(12,4)
    unit: currency
    recipes:
      - {id: direct,       requires: [discount]}
      - {id: from_prices,  requires: [list_price, sale_price], expr: "list_price - sale_price"}
      - {id: from_pct,     requires: [sale_price, discount_pct],
         expr: "sale_price * discount_pct"}

canonical_relationships:
  - {from: order_item, to: order,    via: order_id,    cardinality: many_to_one}
  - {from: order,      to: customer, via: customer_id, cardinality: many_to_one}

metric_templates:
  gross_revenue:
    requires: [unit_price, quantity]
    grain: order_item
    additivity: additive
    agg: sum
    expr: "unit_price * quantity"
```

The Catalog is deliberately not part of a tenant's project. It is passed separately to
`compile_project` and `resolve`, because it is shared across every tenant in the
vertical and versioned on its own cadence.

## EntityModel: the tenant's resolved subgraph

A tenant's EntityModel is *the subgraph of the Catalog that resolved against their
actual data*, plus tenant-native extensions the Catalog never anticipated. Each entity
declares its grain (as prose — it appears in error messages), its key, SCD kind,
partitioning, and typed fields.

```yaml
spec_version: 7
entities:
  order_item:
    grain: one row per line on an order
    key: [order_id, line_no]
    scd: type1
    partition_by: [days(order_date)]
    fields:
      order_id:   {type: string, required: true}
      line_no:    {type: int,    required: true}
      unit_price: {type: decimal(12,4), canonical: unit_price}
      quantity:   {type: int,    canonical: quantity}
      extensions: {type: variant}            # unmapped tail
relationships:
  - {name: item_of_order, from: order_item, to: order, via: {order_id: order_id},
     cardinality: many_to_one}
```

`canonical: unit_price` is the link back to the Catalog. It does two jobs: it makes the
field count toward metric reachability ("this tenant can have `gross_revenue` because
`unit_price` and `quantity` are available"), and it propagates the Catalog's `unit` and
`tax_basis` metadata onto the column so the guardrails can check arithmetic. A field
without a `canonical:` link is tenant-native: legal, queryable, but invisible to
catalog-derived metrics and metadata-free (`unknown`) in monetary arithmetic.

## Mapping: the recorded decision

A Mapping describes how one bronze source becomes one entity — key extraction, field
extraction via JSONPath-style references, and transform chains drawn from a closed,
versioned whitelist.

```yaml
mapping_version: 3
source: shopify__order_lines
target: order_item
key:
  order_id: {from: "$.order_id", transform: [to_string]}
  line_no:  {from: "$.index",    transform: [to_int]}
fields:
  unit_price:
    recipe: from_total                  # chosen upstream; recorded for reproducibility
    from: {line_total: "$.total", quantity: "$.qty"}
  quantity: {from: "$.qty", transform: [to_int]}
```

The line that matters most is `recipe: from_total`. Recipe *selection* — deciding which
of a canonical field's ordered recipes this tenant's data satisfies — happens upstream,
where an LLM may participate. The compiler is handed a decided spec. It validates the
recorded choice exhaustively: the recipe id must exist on the catalog field, and every
name in the recipe's `requires` must be bound by the mapping's `from` aliases — exactly,
with unbound requires and surplus aliases both errors.

!!! note "The compiler validates recipes; it never chooses them"

    Determinism and auditability both depend on this: the same specs must resolve
    identically forever, and a reviewer must see which recipe was used in the spec
    itself. The consequence is deliberate: when the Catalog evolves and a recorded
    recipe disappears, that is a loud `ResolutionError` the upstream chooser must
    re-decide — never a decision the compiler quietly remakes.

### One entity, several mappings

Nothing above says *one* mapping per entity. Several may name the same `target:`, and the
entity is then the `UNION ALL` of them in lexicographic order of source relation — two
shops on one platform, a region-sharded table, a migration halfway done.

That is what makes the EntityModel an **integration** layer rather than a renaming layer.
Without it, two systems holding orders produce `order_shopify` and `order_woo` and the
model that is supposed to say what a tenant's data *means* stops at the boundary of
whichever system produced it.

The merge is deliberately narrow. It covers one shared key space with disjoint key sets,
and nothing else: overlapping keys are refused, because a key in two sources is either
duplication or an accident, and choosing between two rows that claim one key is a business
rule the compiler cannot check. Sources that need *matching* rather than merging are
[identity resolution](../how-to/resolve-identities.md), which is a step. The full mechanics
are in [Merge sources into one entity](../how-to/merge-sources.md).

## MetricSet: measures and additivity classes

The MetricSet declares the tenant's measures, either inline or by reference to a Catalog
template. Every metric carries a grain and an **additivity class**, which decides how it
may ever be aggregated or stored:

| Class | Meaning | Carries |
|---|---|---|
| `additive` | Sums correctly over every dimension (revenue, quantity) | `agg`, `expr` |
| `semi_additive` | Sums over every dimension *except* one (inventory balance over time) | `SemiAdditivePolicy(over, rule)` with `rule` ∈ `last`/`first`/`avg`/`max`/`min` |
| `non_additive` | Never summable (ratios, averages) | `RatioSpec(numerator, denominator)` over additive components |

```yaml
metrics:
  average_order_value:
    requires_metrics: [net_revenue, order_count]
    additivity: non_additive
    ratio: {numerator: net_revenue, denominator: order_count}
```

Additivity is not documentation — it is enforced. A `non_additive` metric may never be
materialized as a stored number, only recomputed from its additive components at query
time; a `non_additive` metric declared without a `RatioSpec` (or equivalent additive
decomposition) is refused outright, because with nothing to recompute from it could only
ever be answered by storing it. The *policy* — what may be stored, what may be summed —
is bloomery's and is checked at compile time; the *lowering* of these classes into SQL
at query time is delegated to the embedded MetricFlow backend, which can express the
`last` and `first` semi-additive rules (`avg`/`max`/`min` raise `UnsupportedByTarget`
naming the rule). The [guardrails](guardrails.md) page walks the failure modes these
classes prevent.

### Metrics over time

Three of the metric forms describe a metric in terms of something other than its own
aggregation: two of them in terms of *time*, and one in terms of a subset of rows. The
two time-shaped ones are resolved against the catalog's `date_dimension` — the time
spine, which any project with marts already needs.

**A derived metric is computed from other metrics**, by an expression over aliased
inputs. Each input may be read at an `offset:`, which is what makes period-over-period
expressible: the interesting case names one metric twice.

```yaml
metrics:
  revenue_yoy:
    additivity: non_additive
    derived:
      expr: "current - prior"
      inputs:
        current: {metric: revenue}
        prior:   {metric: revenue, offset: {window: "1 year"}}
```

The offset's other form, `offset: {to_grain: month}`, is not a fixed distance back but
the start of the containing period — each day against the first day of its own month.
A derived metric is `non_additive` for the same reason a ratio is: it has no measure to
store, and is recomputed from its inputs at the requested grain.

**A cumulative metric accumulates its own measure** over a trailing `window:` or from
the start of a `grain_to_date:` period. It keeps its `agg`/`expr` and its additivity —
those describe the measure, while `cumulative:` describes how the measure accumulates.

```yaml
  revenue_mtd:
    grain: sale
    additivity: additive
    agg: sum
    expr: "amount"
    cumulative: {grain_to_date: month}
```

**A metric filter restricts the rows a metric aggregates**, as typed clauses rather than
a SQL string. `paid_revenue` is then a metric rather than a convention every caller has
to remember; the filter is reported in the plan's explanation, so a restricted number is
never presented as its unrestricted sibling.

```yaml
  paid_revenue:
    grain: sale
    additivity: additive
    agg: sum
    expr: "amount"
    filter:
      - {dimension: status, op: eq, values: [paid]}
```

Two things are worth knowing before you write one. **A cumulative metric requested at a
grain coarser than it accumulates to has to collapse each period to one value**, and
`period_agg:` says how — `last` by default, so a `grain_to_date: month` metric asked for
by month reports the accumulation at the month's end. That is a deliberate divergence from
MetricFlow, whose default is `first`: on a month totalling 257 it reported 100, the
running total on the first day, which is not month-to-date by any reading. Write
`period_agg: first` (or `average`) to ask for something else. And **`cumulative:` on a
`semi_additive` metric is refused**:
a semi-additive metric may not be summed along its `over:` dimension, which is always a
date role, and a window accumulates along exactly that one — both lower, and the product
is a number with no reading.

What each construct is refused for, and by which error, is in
[spec schemas](../reference/spec-schemas.md#metric). One target boundary is worth
knowing up front: **Cube expresses metric filters and refuses derived and cumulative
metrics** — it compares periods at query time (`compareDateRange`) rather than as a
stored measure definition, and has no equivalent for `grain_to_date`. The MetricFlow
manifest carries all four.

## Marts: the fifth spec kind

A project may also carry a `marts:` document declaring the gold layer: wide, pre-joined
tables at a fixed grain, with dimensions flattened in at build time. Marts are the
serving surface the planner selects from and the emission source for MetricFlow
semantic models — one mart becomes exactly one semantic model. They get their own
page — [The wide-mart gold layer](wide-marts.md).

## How the kinds meet

Resolution builds one dependency graph over all of it: source columns feed entity fields
(through transform chains and recipe bindings), entity fields feed canonical fields
(through `canonical:` links), canonical fields feed metrics (through `requires`), and
metrics feed metrics (through `requires_metrics`). From that single graph come metric
reachability with specific missing leaves ("you can't get margin because `cogs` is
missing" — a product-facing answer, not a diagnostic), cycle detection, and the
deterministic emission order. The [compile pipeline](compile-pipeline.md) page follows
the specs through that graph to emitted artifacts.
