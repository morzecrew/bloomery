# 001 — Order shipping counted once per line

- **Origin:** `industry-pattern`. The denormalized order export is the most common shape a
  warehouse receives, and this is what happens the first time somebody sums a column on it.
- **Tier:** execution (DuckDB). Nothing here needs an engine the default suite excludes.

## The business question

> What did we spend on shipping?

## Declared semantic facts

- `shipping` is a fact about an **order**. One order, one shipping charge.
- `order_item` is one row per line; `item_of_order` is `many_to_one` onto `order`.
- The bronze export carries `shipping` on every line, because that is how the source
  system flattens it.

## The tempting naive query

```sql
SELECT SUM(o.shipping) AS shipping_total
FROM corpus.order_items AS i
JOIN corpus.orders AS o USING (order_id);
```

**Why that SQL is valid.** The join is correct. The declared cardinality is correct — it is
`many_to_one`, so it does not multiply *orders*. Every type checks, no row is dropped, no
null appears, and nothing about the data is wrong. A schema test, a null test and a
uniqueness test all pass.

What multiplies is the **value**: the join produces one row per line, each carrying a copy
of the same `9.00`, and `SUM` cannot tell a copy from a second charge.

## The results

| | shipping_total |
| --- | --- |
| naive | `27.0000` |
| correct | `9.0000` |

Three lines, one order. Hand-checkable, which is the point (D2).

## The semantic failure mode

**Fan-out of a coarser-grained measure.** A value originating at one grain was aggregated at
a finer one. The failure is not in the SQL, the schema, the data, or the declared
cardinality — every one of those is right. It is that nothing in the query records *where
the value originates*, so nothing can notice that the aggregation is happening somewhere
else.

## Expected bloomery behaviour

Three expectations, one fixture (D4), because this case has to survive the evolution from
validator to planner rather than being rewritten at each step:

| Expectation | Spec | Outcome | Owner |
| --- | --- | --- | --- |
| **representation** | a wide mart at line grain listing an order-grain measure | refused | `GrainViolation`, RFC 0010 D2 |
| **rollup** | shipping aggregated at order grain | accepted | RFC 0010 D2 |
| **refinement** | shipping pulled into a line-grain derivation | refused | `GrainMismatch`, RFC 0006 D5 |

The middle row is what makes the other two mean something: a compiler that refused all
three would be safe and useless.

## What this case is waiting for

`accepted` is today's word for the rollup, not `proven` — bloomery compiles it and no proof
value exists yet to record. When RFC 0039 lands, this row gains a `proof.json` and the
outcome becomes `proven`; when RFC 0040 lands, the refinement refusal should carry a
refutation naming the missing functional dependency rather than a grain-string comparison.
Neither changes the fixture, which is the property D4 is about.

**The refinement expectation needs the catalog.** `check_grain` reads an operand's home
entity from `canonical_fields`, so a project with no catalog does not get this refusal at
all — the fan-out compiles clean. That is a property of the current tree worth knowing
while reading this case, not a defect this corpus asserts.
