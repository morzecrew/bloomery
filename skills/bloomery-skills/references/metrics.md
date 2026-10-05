# Metrics

Declare measures and metrics in the MetricSet: grain, additivity, templates, ratios,
derived and period-over-period metrics, cumulative metrics, semi-additive metrics and
metric filters.

## The MetricSet document

At most one per project, keyed by `metrics_version: 1`. A metric is a catalog template
instantiation (`template:` plus overrides, the metric's own keys winning) or fully inline.

```yaml spec=metrics
metrics_version: 1
metrics:
  gross_revenue:
    template: gross_revenue
  order_count:
    grain: order
    additivity: additive
    agg: count
    expr: "order_id"
    owner: finance@example.com
  net_revenue:
    requires: [unit_price, quantity, discount]
    grain: order_item
    additivity: additive
    agg: sum
    expr: "unit_price * quantity - discount"
    description: Revenue after line discounts
  average_order_value:
    requires_metrics: [net_revenue, order_count]
    additivity: ratio
    ratio: {numerator: net_revenue, denominator: order_count}
  active_customers:
    grain: order
    additivity: distinct_count
    agg: count_distinct
    expr: "customer_id"
```

| Key | Meaning |
|---|---|
| `template` | a catalog metric template to instantiate |
| `requires` | canonical field names the metric reads (its leaves) |
| `requires_metrics` | metrics it reads |
| `grain` | the entity grain it aggregates from |
| `additivity` | the aggregation class; required inline or via template |
| `agg`, `expr` | aggregation and the expression over required names |
| `ratio`, `semi_additive`, `derived`, `cumulative`, `filter` | the shapes below |
| `description`, `owner` | carried into emissions |

## Reachability

`requires` names **canonical** fields, not entity columns. A metric is reachable when every
leaf is linked by some entity field's `canonical:`; otherwise it is unreachable with the
missing leaf named, and `via` names the metrics in between when it is blocked through
another metric. Check with `resolve`:

```bash
bloomery resolve specs/
```

## Additivity classes

Additivity decides how a metric may ever be aggregated or stored, and the guardrails enforce
it.

| Class | Meaning | Carries |
|---|---|---|
| `additive` | sums over every dimension | `agg`, `expr` |
| `semi_additive` | sums over every dimension but one (a balance over time) | `semi_additive: {over, rule}` |
| `ratio` | a quotient kept as its operands | `ratio: {numerator, denominator}` |
| `non_additive` | never summable, not a fixed ratio | `derived:`, or `expr` over additive dependencies |
| `distinct_count` | distinct identities, never rolled up | `agg: count_distinct` and `expr` naming the identity |

- A `ratio` or `non_additive` metric is never stored as a number; it is recomputed from its
  components at query time. `non_additive` with nothing to recompute from is refused.
- `ratio:` under any other additivity, and `additivity: ratio` without `ratio:`, are both
  refused.
- The metric's grain must equal the grain of every mart that serves it (`GrainViolation`).

## Semi-additive

```yaml fragment
inventory_on_hand:
  grain: inventory_snapshot
  additivity: semi_additive
  agg: sum
  expr: "units"
  semi_additive: {over: snapshot_day, rule: last}
```

`rule` is `last`, `first`, `avg`, `min` or `max`. The planner's MetricFlow backend lowers
`last` and `first`; `avg`, `min` and `max` raise `UnsupportedByTarget` naming the rule.

## Metrics over time

These resolve against the catalog's `date_dimension`.

**Derived** metrics compute from other metrics through aliased inputs. An input read at an
`offset:` gives period-over-period. The expression must use exactly the declared aliases
(`InvalidMetricShape` otherwise), and inputs need not be repeated in `requires_metrics`.

```yaml spec=metrics
metrics_version: 1
metrics:
  revenue:
    grain: sale
    additivity: additive
    agg: sum
    expr: "amount"
  revenue_yoy:
    additivity: non_additive
    derived:
      expr: "current - prior"
      inputs:
        current: {metric: revenue}
        prior: {metric: revenue, offset: {window: "1 year"}}
  revenue_vs_month_start:
    additivity: non_additive
    derived:
      expr: "current - start"
      inputs:
        current: {metric: revenue}
        start: {metric: revenue, offset: {to_grain: month}}
  revenue_mtd:
    grain: sale
    additivity: additive
    agg: sum
    expr: "amount"
    cumulative: {grain_to_date: month}
  revenue_7d:
    grain: sale
    additivity: additive
    agg: sum
    expr: "amount"
    cumulative: {window: "7 days", period_agg: last}
```

- An offset is exactly one of `window: "<count> <grain>"` or `to_grain:` (`day`, `week`,
  `month`, `quarter`, `year`; the start of the containing period).
- **Cumulative** keeps the metric's own `agg` / `expr` / `additivity` and takes exactly one
  of `window:` or `grain_to_date:`. `period_agg` (`last` by default; `first`, `average`)
  says how a coarser request collapses each period. `cumulative:` on `semi_additive` is
  refused.

## Metric filters

A filter restricts the rows a metric aggregates, as typed clauses (ANDed), never a SQL
string. The restriction is reported in every plan's explanation.

```yaml fragment
paid_revenue:
  grain: sale
  additivity: additive
  agg: sum
  expr: "amount"
  filter:
    - {dimension: status, op: eq, values: [paid]}
    - {dimension: channel, op: not_in, values: [internal, test]}
```

- `dimension` is a **categorical** column of the mart carrying the metric, matching
  `^[a-z][a-z0-9_]*$`. A date-role dimension is refused: use `cumulative:` or `offset:`.
- `op`: `eq`, `ne`, `in`, `not_in`, `gt`, `gte`, `lt`, `lte`, `is_null`. Values are checked
  against the column's type and never cast.
- `column:` instead of `values:` compares two dimensions (`eq` / `ne` only); both flatten
  steps must declare `role_of:` the same dimension, or `MetricFilterInvalid`.
- No `like`; that belongs to request filters.

## Target boundaries

The MetricFlow manifest carries every shape above. Cube expresses filters but refuses
derived and cumulative metrics. A metric reaches a SQL target only as a mart measure.

## Published pages

- [Specs and the catalog: MetricSet](https://morzecrew.github.io/bloomery/latest/concepts/specs-and-catalog/)
- [Spec schemas: Metric](https://morzecrew.github.io/bloomery/latest/reference/spec-schemas/)
