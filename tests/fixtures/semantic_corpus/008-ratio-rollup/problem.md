# 008 — Ratio rollup

- **Origin:** `industry-pattern`. Every warehouse that stores a per-row rate invites the
  next reader to aggregate it, and the aggregate is right only when every row carries the
  same denominator.
- **Tier:** execution (DuckDB).

## The business question

> What did we earn per item sold?

## Declared semantic facts

- `revenue` is a fact about an **order**, and is additive across orders.
- `item_count` is a fact about an **order**, and is additive across orders.
- `revenue_per_item` is meant to be the first divided by the second, at whatever grain the
  question is asked at.

## The tempting naive query

```sql
SELECT ROUND(AVG(revenue / item_count), 2) AS revenue_per_item
FROM bronze.corpus__orders;
```

**Why that SQL is valid.** Each order's revenue per item is a correct number about that
order. Averaging a column of correct numbers is a legal aggregate over non-null values, and
nothing is duplicated or missing.

The failure is that the average weights each *order* equally when the question weights each
*item* equally. A 30-line order at 3.00 and a 10-line order at 4.00 average to 3.50, which
is a number no item ever earned.

## The wrong result and the correct one

| | `revenue_per_item` |
|---|---|
| naive | `3.50` |
| correct | `3.25` |

130.00 of revenue over 40 items is 3.25, and a reader can check both by hand from the four
values in `data/rows.sql`.

## The semantic failure mode

A ratio is not a measure that can be rolled up; it is a **construction** that must be
rebuilt from its operands at the requested grain. Storing the quotient makes the wrong
aggregate available, and the wrong aggregate is the one every BI tool offers first.

## How this differs from 002

`002-average-of-averages` is about a stored average arriving from **upstream** — a column
some other system already aggregated, which bloomery can only refuse to re-aggregate. This
case is about bloomery's own metric vocabulary: the same quotient, declared here, and the
difference between declaring it `additive` and declaring it a `ratio`.

## Expected bloomery behaviour

- **naive** — `revenue_per_item` declared `additivity: additive` with `agg: avg` is refused
  as `FalseAdditivityClaim` (RFC 0038 D2). Averaging an average re-aggregates an aggregate.
- **declared** — the same quotient declared `additivity: ratio` over its two operands is
  accepted, and the planner returns 3.25. **R012** is the rule that owns it: a ratio is
  recomputed from operands that each roll up, never summed like one.
