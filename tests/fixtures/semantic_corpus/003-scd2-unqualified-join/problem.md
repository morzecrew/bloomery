# 003 — Revenue joined to every version of a slowly-changing dimension

- **Origin:** `industry-pattern`. Type-2 history is the standard way to keep a dimension's
  past, and the business key stays the obvious thing to join on.
- **Tier:** execution (DuckDB). RFC 0042 §9 guessed this might need the Docker-gated engine
  tier; an as-of join over a validity interval is ordinary SQL and DuckDB runs it, so the
  case stays in the default suite.
- **`silver.customer_tier` is supplied, not derived.** Type-2 versions come from the
  operator's snapshotting, not from anything bloomery builds out of bronze — so the case
  creates that relation itself and the harness leaves bloomery's model for it unrun. A
  harness that insisted on rebuilding it would be asserting a pipeline nobody runs.

## The business question

> What revenue did we book, with each order attributed to its customer's tier?

The tier is why the dimension is joined at all, and the total is where the damage shows:
the breakdown is wrong per group *and* the groups no longer sum to the revenue actually
booked, so a single number is enough to prove it and small enough to check by hand
(RFC 0042 D2).

## Declared semantic facts

- `customer_tier` is `scd: type2` — one row per customer **per version**, with
  `valid_from` / `valid_to`.
- `customer_id` is the business key. It is **not** unique in that relation.
- `tier_of_customer` is `many_to_one` from `order`, and that is correct: an order has one
  customer.

## The tempting naive query

```sql
SELECT SUM(o.amount) AS revenue
FROM corpus.orders AS o
JOIN corpus.customer_tier AS t ON o.customer_id = t.customer_id;
```

**Why that SQL is valid.** It is the join the ERD draws. The declared cardinality is right —
`many_to_one` is a claim about the *domain*, and in the domain an order does have one
customer. Every row is real, every key resolves, nothing is null.

What is wrong is that the cardinality describes the domain and the relation describes the
domain **over time**. One customer with two tier versions is two rows, so every order meets
both, and revenue is counted once per version.

## The results

One customer upgraded once; two orders, one on each side of the change.

| | revenue |
| --- | --- |
| naive | `600.0000` — every order against both versions |
| correct | `300.0000` |

The multiplier is the version count, so this gets worse the longer the history runs — and
it is invisible on a dimension nobody has changed yet.

## The semantic failure mode

**An unqualified historical join.** Joining on identity alone asks "which customer", when
the question that has an answer is "which customer *as of when*". No amount of correct
cardinality supplies the missing instant.

## Expected bloomery behaviour

| Expectation | Spec | Outcome | Owner |
| --- | --- | --- | --- |
| **unanchored** | flatten `tier_of_customer` with no `as_of:` | refused | `HistoricalFanout`, RFC 0023 D1 |
| **anchored** | the same flatten, `as_of: ordered_at` | accepted | RFC 0023 D8 |

`HistoricalFanout` is kept apart from `FanoutRisk` for the reason this case shows: the
`cardinality:` here is *already right*, and an error pointing at it would send the author to
correct the one thing that is not wrong.
