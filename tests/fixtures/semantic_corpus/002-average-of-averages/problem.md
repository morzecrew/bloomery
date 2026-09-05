# 002 — Average of averages

- **Origin:** `industry-pattern`. Every BI tool offers `AVG` on a pre-aggregated table, and
  the number it produces is right only when every group is the same size.
- **Tier:** execution (DuckDB).

## The business question

> What is the average price of an item we sell?

## Declared semantic facts

- `unit_price` is a fact about a **line**.
- `average_item_price` is meant to be that price averaged over items.

## The tempting naive query

```sql
SELECT AVG(average_item_price) AS average_item_price
FROM bronze.corpus__order_summaries;
```

**Why that SQL is valid.** The upstream system publishes a per-order rollup, and every row
of it is a correct average of that order's lines. The aggregate is legal, nothing is null,
nothing is duplicated, and the column is exactly what its name says.

The failure is that averaging weights each group equally. Averaging the two order averages
weights a one-line order the same as a three-line order — and the stored column is what
makes it available to do.

**The stored rollup is load-bearing here, and finding that out changed the case.** Written
first against line-grain rows, the naive spec planned to `32.50` — the *right* answer,
because `AVG(unit_price)` over lines is the right answer. The average-of-averages bug needs
an average that has already been taken. That is why this fixture carries a summaries table
and not only line items.

## The results

Two orders: one line at `100.00`, three lines at `10.00`.

| | average_item_price |
| --- | --- |
| naive | `55.00000000` — the mean of `100` and `10` |
| correct | `32.50000000` — `130 / 4` |

They coincide only when every order has the same number of lines, which is why this
survives testing on tidy sample data and fails in production.

## The semantic failure mode

**A ratio treated as additive.** An average is a quotient of two additive quantities, and it
is not itself additive over anything. Re-aggregating a stored quotient — by `AVG`, `SUM`, or
any other function — cannot recover the quotient of the sums.

## Expected bloomery behaviour

| Expectation | Spec | Outcome | Owner |
| --- | --- | --- | --- |
| **naive** | a stored per-order average, `additivity: additive`, `agg: avg` | **refused** — `FalseAdditivityClaim` | RFC 0038 D2 |
| **decomposed** | a `ratio:` over two additive operands, from the lines | accepted | RFC 0006 D6 |

The **decomposed** row is asserted by planning the metric and running the SQL bloomery
renders, which returns `32.50000000`. The **naive** row is asserted by its refusal.

**This row was `unguarded` until RFC 0038 landed, and the change is the case earning its
keep.** `check_additivity` inspected only metrics declared `non_additive` or
`semi_additive`, so nothing verified that a metric declared `additive` actually was: the
naive spec compiled clean, every cast succeeded, and the planner returned `55.00000000` —
the average of two per-order averages, weighting a one-line order equally with a three-line
one. That is this corpus's inclusion rule exactly, and it is what the fixture recorded
while no rule owned it.

RFC 0038 D2 stores a ratio as its operands rather than as a materialized quotient, and the
guardrail now refuses the declaration that hides one. The wrong number is still in
`expected/result.json` and `naive.sql` still returns it: what changed is that bloomery no
longer will (RFC 0042 §8).
