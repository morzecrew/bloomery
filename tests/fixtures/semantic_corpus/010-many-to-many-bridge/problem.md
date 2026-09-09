# 010 — Many-to-many bridge

- **Origin:** `industry-pattern`. A bridge table is the standard modelling of a
  many-to-many, and both of its edges point at exactly one row — which is what makes the
  duplication invisible at the point a reader checks for it.
- **Tier:** execution (DuckDB).

## The business question

> What was our revenue?

## Declared semantic facts

- `revenue` is a fact about an **order**, and is additive across orders.
- `order_promo` is one row per promotion applied to an order.
- Both of its relationships are `many_to_one`: a bridge row names one order and one
  promotion.

## The tempting naive query

```sql
SELECT ROUND(SUM(o.revenue), 2) AS revenue
FROM bronze.corpus__orders o
JOIN bronze.corpus__order_promos b ON b.order_id = o.order_id
JOIN bronze.corpus__promos p ON p.promo_id = b.promo_id;
```

**Why that SQL is valid.** Two inner joins, each on a declared key, each `many_to_one` in
the direction it is written. There is no `one_to_many` edge anywhere in the query and no
aggregate inside a join. Checked hop by hop, nothing is wrong.

The fan-out is a property of the **path**, not of either edge. Reading
`order → order_promo → promo` traverses the first edge backwards, and an order with two
promotions arrives at the join twice.

## The wrong result and the correct one

| | `revenue` |
|---|---|
| naive | `250.00` |
| correct | `150.00` |

Three bridge rows over two orders; o1's 100.00 is counted once per promotion.

## The semantic failure mode

Grain is a property of a **path**, and a path of safe edges is not a safe path. This is why
the grain model is directional (RFC 0037 D5): an edge says which way values may travel, and
a bridge is two edges pointing away from a grain that neither of them is.

## How this differs from 001

`001-order-shipping-fanout` fans out through one declared `one_to_many` — the danger is
written on the edge, and a reader who checks cardinalities finds it. Here **every edge is
`many_to_one`** and the duplication appears only when two of them are composed. A guard
that inspected relationships one at a time would pass this case.

## Expected bloomery behaviour

- **bridged** — a mart at `order_promo` grain listing `revenue`, which originates at
  `order`, is refused as `GrainViolation` (RFC 0010 D2). The mart contract is what catches
  it: a measure may be embedded only at its own grain, whatever path reached it.
- **per_order** — revenue on a mart at its own grain is accepted and returns 150.00.
  **R011** owns it: an additive measure summed across a rollup its grain proof permits, and
  here the rollup is the identity one.
