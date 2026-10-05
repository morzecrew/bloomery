# Marts

Declare the wide-mart gold layer: base entity, flatten steps, date roles, measures,
historical dimensions (`as_of:` and `reading: current`), role-playing dimensions,
rollups, and the evidence a mart requires.

## The doctrine

Gold is one wide, pre-joined mart per (grain × subject area), with every dimension
flattened in **at build time**. The query path is `SELECT dims, AGG(measures) FROM mart
GROUP BY dims`, with no join before an aggregate, so fan-out is refused where a join would
be *built* rather than discovered where it would be *summed*. One mart becomes one gold
model on SQL targets and exactly one semantic model in the MetricFlow manifest; the planner
selects from built marts and never joins raw entities.

## The MartSet document

At most one per project, keyed by `marts_version: 1`. A project without marts compiles
silver only.

```yaml spec=marts
marts_version: 1
marts:
  order_items:
    grain: order_item
    base: order_item
    flatten:
      - {via: item_of_order, prefix: order_}
      - {via: order_of_customer, prefix: customer_, as_of: order_date}
      - {date: order_date, role: ordered}
      - {date: ship_date, role: shipped}
    measures: [gross_revenue, net_revenue, quantity]
    partition_by: [days(ordered_day)]
    cost_hint: 3
    owner: analytics@example.com
  orders:
    grain: order
    base: order
    flatten:
      - {date: order_date, role: ordered}
    measures: [order_count, shipping_cost]
rollups:
  order_items_monthly:
    of: order_items
    keep: [order_customer_id, ordered_month]
    measures: [gross_revenue]
```

## Mart keys

| Key | Required | Meaning |
|---|---|---|
| `grain` | yes | must equal the base entity's grain; every measure's grain must match it |
| `base` | yes | the fact entity the mart is built from |
| `flatten` | no | steps applied in authored order; chains flatten transitively |
| `measures` | no | metric names served; a mart with measures needs a date role |
| `partition_by` | no | partition specs over mart columns |
| `materialization` | no | as on an entity |
| `cost_hint` | no | integer ≥ 1; when several marts can serve a metric, the cheapest wins, ties broken by name |
| `reading` | on a `type2` base | `current` |
| `requires_evidence` | no | `assumed` (default) or `locked` |
| `owner`, `grants` | no | annotations |

## Flatten steps

**`via`** flattens a declared relationship. `prefix` is mandatory and prefixes every
flattened column (`order_` + `customer_id` = `order_customer_id`); a collision after
prefixing is an error, never an auto-rename. Only `many_to_one` and `one_to_one`
relationships flatten; `one_to_many` is `FanoutRisk`.

**`date`** declares a date role: `{date: order_date, role: ordered}` expands to
`ordered_day`, `ordered_week`, `ordered_month`, `ordered_quarter`, `ordered_year`. These
bucket columns are what requests group by. `metric_time` is reserved.

| Refusal | When |
|---|---|
| `GrainViolation` | a measure's grain differs from the mart's |
| `FanoutRisk` | a flatten through `one_to_many` |
| `MartMissingTimeDimension` | measures with no date role |
| `HistoricalFanout` | a `type2` dimension flattened with neither `as_of` nor `reading: current` |

## Role-playing dimensions

One date dimension plays several roles (ordered, shipped), each a distinct set of bucket
columns, so `ordered_month` and `shipped_month` give two correct, different answers with no
aliasing. An unqualified reference to a multi-role dimension is refused as
`AmbiguousDimension`, naming the roles.

For a non-date dimension reached twice, declare which dimension each family is a role of:

```yaml fragment
flatten:
  - {via: order_billing_address, prefix: billing_, role_of: address}
  - {via: order_shipping_address, prefix: shipping_, role_of: address}
```

`role_of:` is what admits a metric filter comparing `billing_region` with `shipping_region`.

## Historical dimensions

An `scd: type2` entity holds one row per version per key. Flattening it needs an answer
to "as of when":

- `as_of: order_date` reads the version current at the base entity's own date
  (point-in-time attribution). The join gains a half-open validity predicate on
  `valid_from` / `valid_to`.
- `reading: current` reads only the current version (`valid_to IS NULL`, in the join's `ON`
  clause, so rows without a current version keep NULL columns).

Both are declarations, never defaults. Each is refused on a non-historical entity, and they
are refused together on one step.

A mart **based** on a `type2` entity must declare `reading: current`, which filters the base
to one row per key:

```yaml spec=marts
marts_version: 1
marts:
  customer_current:
    grain: customer
    base: customer
    reading: current
    materialization: full
    flatten:
      - {date: signup_date, role: signed_up}
```

Any mart that reads current versions, on its base or any flatten step, must be
`materialization: full`. A partitioned one has to say so explicitly, because partitioning
defaults to incremental.

## Rollups

A rollup is a coarser aggregate of one mart, built once: it names what it **keeps**, and
drops every other parent column. Keys: `of` (a mart in this document, never a rollup),
`keep` (non-empty, not every parent column), `measures` (non-empty, each stored by the
parent), and optional `partition_by` / `materialization`. There is no `grain`, `base` or
`cost_hint`.

A rollup is **never chosen for you**: no request is redirected to it. An unprovable rollup
is refused (`UnprovableRollup`): a `distinct_count`, `semi_additive` or `non_additive`
measure, one the parent does not store, one whose `filter:` or `cumulative:` would be
dropped, or a rollup that drops nothing. A `ratio` is carried as its operands.

## Requiring declared evidence

`requires_evidence: locked` says the mart will not rest on anything the compiler worked out
for itself. A premise weaker than that is refused, naming the measure and column: for
example a column carried through a relationship with `imported_from:`, or an entity imported
from an upstream project. The default `assumed` is byte-identical to omitting the key; there
is no `open`.

```yaml fragment
statutory_revenue:
  grain: order
  base: order
  flatten:
    - {date: order_date, role: ordered}
  measures: [net_revenue]
  requires_evidence: locked
```

## Cross-grain requests

Metrics on different marts can be requested together: each is aggregated on its own mart
and the results joined on a shared dimension, when every requested dimension is the *same
source column* on every branch. Otherwise the request is refused as `UnreachableAtGrain`;
the fix is usually to flatten the dimension onto every mart involved.

## Published pages

- [The wide-mart gold layer](https://morzecrew.github.io/bloomery/latest/concepts/wide-marts/)
- [Spec schemas: MartSet](https://morzecrew.github.io/bloomery/latest/reference/spec-schemas/)
