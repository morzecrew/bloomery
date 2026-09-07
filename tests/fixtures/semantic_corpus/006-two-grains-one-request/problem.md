# 006 — Two grains asked for in one question

- **Origin:** `industry-pattern`. The moment a dashboard puts a shipping tile next to a
  discount tile, somebody writes one query for both.
- **Tier:** execution (DuckDB). Nothing here needs an engine the default suite excludes.

## The business question

> What did we spend on shipping, and what did we give away in discounts?

## Declared semantic facts

- `shipping` is a fact about an **order**. One order, one shipping charge.
- `discount` is a fact about an **order line**. One line, one discount.
- `item_of_order` is `many_to_one` from `order_item` onto `order`.

Both facts are wanted in one answer, and no single relation holds them at their own
grains. This is case 001's trap with a second measure standing beside it — and the second
measure is what makes it a different case, because it is the reason somebody joins.

## The tempting naive query

```sql
SELECT SUM(o.shipping) AS shipping_total, SUM(i.discount) AS discount_total
FROM bronze.corpus__order_items AS i
JOIN bronze.corpus__orders AS o USING (order_id);
```

**Why that SQL is valid.** One join, correct on its declared cardinality, and it is the
only join that puts both columns in one place. Every type checks, no row is dropped, no
null appears. `discount_total` is even right — which is what makes the query convincing:
half the answer is correct, and nothing marks which half.

`shipping` is multiplied once per line of its order, exactly as in case 001. Adding a
second measure did not add a second bug; it added a **reason** to write the join, and the
first bug came with it.

## The correct answer

Each measure is aggregated at the grain it originates at, and the two results are joined
only afterwards — aggregate-then-join, never join-then-hope (RFC 0041 D1). With no
grouping the two aggregates are one row each and the join is their cross product; with a
grouping it is a null-safe join on the shared key (D13).

## What bloomery does

| expectation | outcome | rule |
| --- | --- | --- |
| `branches` | accepted | R010 |

Answers it. The coverage precheck partitions the two measures by owning mart (RFC 0041
D11), plans each branch as the single-mart request it is, and composes the results
itself (D9). The plan carries **R010**: each branch holds one row per key because of the
aggregate beneath it, structurally, rather than because the data happened to look that
way (D2).
