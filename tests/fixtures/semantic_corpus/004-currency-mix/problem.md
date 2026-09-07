# 004 — Money in two currencies, added

- **Origin:** `industry-pattern`. A processor settles in the currency the customer paid in
  and charges its fee in one currency; both land in the same table as `decimal`.
- **Tier:** execution (DuckDB).

## The business question

> What did we take in, in dollars?

## Declared semantic facts

- `amount_eur` is money, **EUR**.
- `fee_usd` is money, **USD**.
- A rate is a dated fact: the EUR→USD rate on the day of the payment is the one that
  applies, and it is supplied by an operator-owned relation.

## The tempting naive query

```sql
SELECT SUM(amount_eur + fee_usd) AS total_usd FROM corpus.payments;
```

**Why that SQL is valid.** Both columns are `DECIMAL(12,4)`. The addition type-checks in
every engine there is. Both values are money, both are net of tax, neither is null. Nothing
in the *type system of SQL* records a denomination, so there is nothing for the engine to
object to.

The result is a number with no unit — not dollars, not euros, and not convertible into
either after the fact, because the two have already been added.

## The results

Two payments, one rate period, EUR→USD at `1.10`.

| | total_usd |
| --- | --- |
| naive | `157.5000` — euros and dollars added as though they were the same thing |
| correct | `172.5000` — the EUR side converted at the payment's own date, then added |

The gap is not a rounding difference and it is not stable: it moves with the rate, so the
same query re-run next month is wrong by a different amount.

## The semantic failure mode

**Unit erasure.** The unit is metadata the warehouse dropped, so a check that only reads
types cannot see the mismatch. This is the case that makes RFC 0038 D3's point: units have
to participate in type checking, or the only place a currency exists is the column name.

## Expected bloomery behaviour

| Expectation | Spec | Outcome | Owner |
| --- | --- | --- | --- |
| **mixed** | `amount_eur + fee_usd`, no rate relation | refused | `CurrencyMismatch`, RFC 0006 D4 |
| **converted** | `currency_in: EUR` with `convert: [EUR, USD, paid_at]`, `fx_rates:` declared | accepted | R009 |
| **mislabelled** | `currency_in: EUR` with `convert: [JPY, USD, paid_at]` | refused | `ResolutionError`, R009 |

The refusal is **unconditional** — declaring `fx_rates:` does not make mixed currencies
addable. What the rate relation changes is the *fix* bloomery can offer: with one, it points
at the convert transform; without one, it says so and names the three remaining options.

That distinction is why this case is `refused` today rather than `unguarded`.

**The third arm is the one the conversion itself can get wrong.** `mislabelled` converts the
same euros with the yen rate: every cast succeeds, the rate relation has the row asked for,
and the answer is wrong by whatever JPY→USD and EUR→USD differ by. It is the same failure
this case is about — a denomination nothing checked — moved from the arithmetic to the
conversion, and until RFC 0061 it compiled clean. What admits `converted` and refuses
`mislabelled` is one rule, R009: a conversion's input currency is declared, or produced by
the step before it.
