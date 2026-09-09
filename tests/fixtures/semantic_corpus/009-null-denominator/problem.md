# 009 — Null denominator

- **Origin:** `industry-pattern`. Every per-unit rate has rows where the unit count is
  zero, and the cost those rows carry has to go somewhere.
- **Tier:** execution (DuckDB).

## The business question

> What did it cost us to ship a parcel?

## Declared semantic facts

- `carrier_cost` is a fact about a **shipment**, and is additive across shipments.
- `parcels` is a fact about a **shipment**, and is additive across shipments.
- `cost_per_parcel` is the first divided by the second, at the grain asked for.

## The tempting naive query

```sql
SELECT ROUND(SUM(carrier_cost) / SUM(parcels), 2) AS cost_per_parcel
FROM bronze.corpus__shipments;
```

**Why that SQL is valid.** Sum over sum is the *right shape* for a ratio — it is what
008 exists to argue for, and what bloomery emits. Every value is present, `parcels` is `0`
rather than null because the count is known and it is none, and nothing divides by zero:
the total denominator is 40.

The failure is in the rows, not the arithmetic. `s3` was cancelled after the carrier had
charged for it, so its 40.00 has no parcels of its own — and sum-over-sum charges it to the
40 parcels the other two shipments moved. The answer is 4.00 for a fleet whose parcels cost
3.00 each.

## The wrong result and the correct one

| | `cost_per_parcel` |
|---|---|
| naive | `4.00` |
| correct | `3.00` |

160.00 over 40 against 120.00 over 40, from three rows.

## The semantic failure mode

A ratio's operands must be about the **same rows**. A row with a zero denominator is not a
row this question is about, and including it moves cost onto units that did not incur it.
The bug survives every check a ratio normally gets: the shape is right, the operands are
additive, the denominator is non-zero, and no value is null.

## How this differs from 008

`008-ratio-rollup` is about *how* a ratio is rebuilt — average the quotients and you weight
the groups wrongly. This case grants all of that and still gets the wrong number, because
the rule that governs reconstruction says nothing about which rows belong in it. The two
together are the reason **R012 is not enough on its own**.

## Expected bloomery behaviour

- **declared** — the ratio declared correctly over correctly declared operands is
  **`unguarded`**: it satisfies R012, compiles, plans, and returns 4.00. Nothing bloomery
  checks today looks at whether a zero-denominator row belongs in the numerator, and the
  corpus says so rather than pretending otherwise (RFC 0042 §8's gate). **RFC 0042 D5** is
  the decision a future rule converting this case would answer to.
- **restricted** — the same ratio whose operands declare the rows they are about is
  **accepted** and returns 3.00, on **R012**. The restriction is a spec fact, which is what makes the
  correct answer reachable without a new rule.
