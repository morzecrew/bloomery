# 012 — A rollup recounts identities

- **Origin:** `industry-pattern`. The pre-aggregate is the first thing anyone
  builds when a dashboard gets slow, and the columns that survive it and the
  columns that do not sit side by side in the same table.
- **Tier:** execution (DuckDB).
- **Why this is not case 007.** Case 007 is the same arithmetic at the *query*
  layer, and bloomery already refused it — its naive spec declares the measure
  `additive`, and the additivity guardrail catches the lie. Here the measure is
  declared honestly as `distinct_count` and the lie is in a **materialized**
  monthly table asked for by name. No guardrail before RFC 0058 could see it: a
  mart is a fact table at its base grain and nothing described a relation built
  by aggregating another one. The rule is different (R013 rather than
  RFC 0038 D2), the surface is different, and the number is wrong at build time
  rather than at query time.

## The business question

> How many customers bought from us in January, and what did they spend?

## Declared semantic facts

- `revenue` is a fact about an **order** and is additive across orders.
- `buyers` is the count of **distinct customers**, which is a fact about a set
  of orders rather than about any one of them.
- The dashboard reads a monthly table, because reading every order is slow.

## The tempting naive query

```sql
SELECT SUM(daily_buyers) AS buyers
FROM (
    SELECT ordered_on, COUNT(DISTINCT customer_id) AS daily_buyers
    FROM bronze.corpus__orders
    GROUP BY ordered_on
) AS by_day;
```

**Why that SQL is valid.** Each day's customer count is a correct number about
that day. Summing a column of correct numbers is a legal aggregate over
non-null values, nothing is duplicated, nothing is missing, and the same query
shape over `amount` gives exactly the right revenue. The rollup is right about
one column and wrong about the one beside it.

The failure is that a distinct count is not additive across partitions: a
customer who buys on two days is one customer and two daily counts. Re-adding
them needs a disjointness proof no rule supplies (RFC 0041 D8), and the groups
here are not disjoint — which is the ordinary case, not the edge one.

## The wrong result and the correct one

| | `buyers` |
|---|---|
| naive | `4` |
| correct | `3` |

## What bloomery does

`detail` declares the mart and no rollup, and is **accepted**: `buyers` is
computed from the orders at the grain the question asks about, and the planner
returns `3`. R008 is what authorizes it — the measure is embedded in the mart
at that mart's grain, which is the whole of what the aggregate rests on when
there is no pre-aggregate between the question and the rows.

`rolled` declares the same project plus the monthly rollup, carrying `revenue`
and `buyers` together. It is **refused** with `UnprovableRollup`: R013 discharges
the obligation for `revenue` and not for `buyers`, and RFC 0058 D5 makes an
unprovable rollup a refusal rather than a warning. A rollup is read *instead of*
the detail table, so a wrong one does not fail — it answers, quickly.
