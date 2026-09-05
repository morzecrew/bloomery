# 005 — Daily balances summed across time

- **Origin:** `industry-pattern`. Every finance warehouse holds a daily snapshot table, and
  `SUM` is the first thing anyone does to a column of money.
- **Tier:** execution (DuckDB).

## The business question

> How much money do we hold across all accounts?

## Declared semantic facts

- `balance` is a **snapshot**: one row per account per day, carrying the state of the
  account on that day.
- It is additive across **accounts** — two accounts' balances add up.
- It is not additive across **time** — Monday's balance and Tuesday's balance are the same
  money observed twice, not two amounts.

## The tempting naive query

```sql
SELECT SUM(balance) AS total_balance FROM corpus.balances;
```

**Why that SQL is valid.** Every row is a real observation, no row is duplicated, the grain
is honest, the join count is zero. There is no fan-out here at all — which is what makes
this case different from 001 and worth having beside it. The table is exactly what it says
it is, and summing a numeric column of it is still meaningless.

## The results

Two accounts over two days; one moves, one does not.

| | total_balance |
| --- | --- |
| naive | `320.0000` — `100 + 120 + 50 + 50` |
| correct | `170.0000` — the latest day, `120 + 50` |

The gap grows with the length of the history, not with the size of the business, so a table
that is right on day one drifts further from the truth every day it is retained.

## The semantic failure mode

**Aggregating over a non-additive axis.** The measure has an axis along which addition is
not defined, and nothing in the type of the column records that. `SUM` is willing over any
numeric column, and the axis it is being summed over is not visible in the query.

## Expected bloomery behaviour

| Expectation | Spec | Outcome | Owner |
| --- | --- | --- | --- |
| **naive** | `additivity: additive` on a snapshot | **refused** — `FalseAdditivityClaim` | RFC 0038 D1 |
| **declared** | `semi_additive: {over: as_of_day, rule: last}` | accepted | RFC 0006 D6 |

Bloomery already enforced the *shape* of a semi-additive declaration: declare
`semi_additive` without a policy and `AdditivityViolation` refuses it. What nothing checked
was the claim in the other direction — that a measure declared `additive` really is. So the
naive spec compiled, the planner returned `320.00000000`, and the only guard that existed
was the one an author had to opt into.

RFC 0038 D1 closes the aggregation vocabulary into a typed set with `Snapshot` as a member,
and this row converted `unguarded → refused` when it landed (RFC 0042 §8). The refusal
reads the origin grain rather than the word: `balance` is keyed on `account_id, as_of_day`,
`as_of_day` is a date, so each row is a point-in-time snapshot and the fix it names is the
**declared** row beside it.
