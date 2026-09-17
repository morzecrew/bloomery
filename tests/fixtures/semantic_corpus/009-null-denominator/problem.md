# 009 — Null denominator

- **Origin:** `industry-pattern`. Every per-unit rate has rows where the unit count is
  zero, and the cost those rows carry has to go somewhere.
- **Why a zero and not a null**, under a name RFC 0042 §3 wrote as `null-denominator`:
  `SUM` skips a null, so both spellings return the same 4.00 — but a null lets the wrong
  answer be read as an aggregation artefact, while a zero is a count the source asserts.
  The bug is which rows the ratio is about, and a zero says that with nothing missing.
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
  **refused**, with `UndeclaredRatioRows`. **R019** is the rule: a ratio is over one row
  set, and every row in it has a non-zero denominator. This one satisfies R012 exactly —
  additive operands, each rolling up — and R012 is about *how* a ratio is rebuilt rather
  than which rows belong in it, which is why a second rule was needed rather than a
  stronger reading of the first.

  The refusal names both fixes and picks neither. That is the point: the two readings below
  are both metrics somebody wants, and until this rule existed they were spelled
  identically and bloomery answered one of them without being asked.

  This arm was `unguarded` until then, and the corpus asserted the wrong number rather than
  pretending a guard existed — RFC 0042 D5 named the decision the converting rule would
  answer to.
- **restricted** — the same ratio whose operands declare the rows they are about is
  **accepted** and returns 3.00, on **R012**. The restriction is a spec fact, which is what
  makes the correct answer reachable without a new rule; R019 reads it and discharges.
- **inclusive** — the same ratio declaring `includes_zero_denominator: true` is
  **accepted** and returns **4.00**, on **R019**. It is the other reading — "total carrier
  spend per parcel moved, overheads included" — and the number is the one this case pins as
  `naive`, which is the whole point of the arm: 4.00 is a wrong answer to "what does it cost
  to move a parcel" and a right one to a question an author has now written down.
