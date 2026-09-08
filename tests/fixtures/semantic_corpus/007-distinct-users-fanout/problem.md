# 007 — Distinct users summed across days

- **Origin:** `industry-pattern`. Daily active users is the first chart on every product
  dashboard, and "users this week" is the second — computed, more often than not, by adding
  the first one up.
- **Tier:** execution (DuckDB).

## The business question

> How many distinct users were active?

## Declared semantic facts

- `active_users` is a **distinct count**: the number of different `user_id`s in the rows
  being asked about.
- It is not additive across **any** partition. Two days' distinct users do not add up to
  the period's distinct users unless no user appears on both days, and nothing in the data
  says that.

## The tempting naive query

```sql
SELECT SUM(daily_users) AS active_users
FROM (
    SELECT session_day, COUNT(DISTINCT user_id) AS daily_users
    FROM bronze.corpus__sessions
    GROUP BY session_day
) AS by_day;
```

**Why that SQL is valid.** Every row is a real session, no row is duplicated, the grain is
honest and there is no join. Each daily number is *correct* — two users on Monday, two on
Tuesday. Only the addition is wrong, and `SUM` is willing over any numeric column.

## The results

Three users over two days; one of them is active on both.

| | active_users |
| --- | --- |
| naive | `4` — `2 + 2` |
| correct | `3` — `u1`, `u2`, `u3` |

The gap is the number of users who were active in more than one partition, which grows
with engagement: the more a product succeeds, the more this number lies about it.

## The semantic failure mode

**Rolling up a measure that has no rollup.** A distinct count has no operator that
combines two partitions' results into the whole's — `SUM` needs the partitions to be
disjoint in the counted identity, and a stored per-day count carries no record of who was
in it. The only sound computation is over the rows themselves, at the grain being asked.

## Expected bloomery behaviour

| Expectation | Spec | Outcome | Owner |
| --- | --- | --- | --- |
| **naive** | `additivity: additive` with `agg: count_distinct` | **refused** — `FalseAdditivityClaim` | RFC 0038 D2 |
| **declared** | `additivity: distinct_count` | accepted | RFC 0038 D1 |

The **naive** spec was refused before this case existed: RFC 0038 D2's allowlist accepts an
`additive` claim only over an aggregation that re-aggregates, and `count_distinct` does
not. What the refusal could not do until now was name a fix — a plain distinct count has no
decomposition to declare, so `non_additive` was closed to it too, and the measure had no
word at all.

The **declared** spec is that word. `distinct_count` is `count_distinct` over the identity
it counts and nothing else (either half without the other is refused), the emitters lower
it as the aggregation they already knew, and the planner computes it from the mart's rows
at whatever grain a request asks — never from a coarser result, which is why it stays out
of the aggregate-then-join path (RFC 0041 D8). This case is the one the member converts
(RFC 0042 D5), and the number it plans to is the correct one.
