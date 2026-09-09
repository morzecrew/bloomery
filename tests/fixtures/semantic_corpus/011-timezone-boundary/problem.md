# 011 — Timezone boundary

- **Origin:** `industry-pattern`. A source system publishing local wall-clock times with no
  zone on them is the common case, not the exotic one, and the zone is written in its
  documentation rather than in its data.
- **Tier:** execution (DuckDB). RFC 0042 D7 left this case's tier open when 003's was
  decided; a named-zone conversion and a truncation are ordinary SQL and DuckDB has both,
  so it runs in the default suite with the rest (logs/T-0029.md).

## The business question

> What did we take in February?

## Declared semantic facts

- `revenue` is a fact about an **order**, and is additive across orders.
- `placed_at` is a `timestamp`, and bloomery's `timestamp` is **always UTC**
  (RFC 0004 §5.1).
- The source system's clock is `America/New_York`. That is a fact about the system.

## The tempting naive query

```sql
WHERE CAST(placed_at AS TIMESTAMP) >= TIMESTAMP '2025-02-01 00:00:00'
```

**Why that SQL is valid.** The string parses, the cast succeeds, the comparison is
well-typed and the range is right. Nothing is null, nothing is duplicated, and no row is
lost to a join.

The failure is five hours wide. `o1` was placed at 21:30 on 31 January in New York, which
is 02:30 on 1 February UTC. Read as a bare wall clock it is a January order, and February
reports 40.00 for a month that took 140.00.

## The wrong result and the correct one

| | `february_revenue` |
|---|---|
| naive | `40.00` |
| correct | `140.00` |

Two rows, one of them within five hours of a month boundary — which is where every one of
these lives.

## The semantic failure mode

A zoneless local timestamp read as UTC is an **undeclared denomination**, exactly as a
number without a currency is. `parse_ts` reads a wall clock; it cannot know which clock.
The assertion "this wall clock is UTC" is made by the *absence* of a zone step, which is
the one place an assertion cannot be checked — and it is the same shape RFC 0061 gave
`currency_in:` a declaration for, one type over.

## Expected bloomery behaviour

The period is part of the measure's expression rather than a restriction on a bucket:
bloomery refuses a metric filtered to a fixed period — *a metric restricted to a fixed
period is a constant, not a metric* (RFC 0034) — and the expression is identical in both
arms, so the only difference between them is which instant `placed_at` holds.

- **zoneless** — `parse_ts` alone compiles, plans, and returns 40.00. It is **`unguarded`**:
  nothing today asks a timestamp to say which clock it came off, so bloomery produces the
  wrong month without complaint. The corpus says so rather than pretending a guard exists
  (RFC 0042 §8). **RFC 0042 D5** is the decision a future rule converting this case
  answers to.
- **anchored** — `to_utc: America/New_York` names the zone the wall clock was written in,
  and the same expression is **accepted** and returns 140.00. **R011** is what authorizes
  the sum once the instant is right; nothing about the sum was ever wrong.

## A note for anyone running this elsewhere

`to_utc` is known to invert on Trino, so this case's `anchored` arm is a DuckDB claim
rather than a cross-dialect one. Which dialects agree on a named-zone conversion is
RFC 0043's matrix to answer, not this corpus's.
