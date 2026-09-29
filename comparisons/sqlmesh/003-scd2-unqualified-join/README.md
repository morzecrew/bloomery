# SQLMesh × 003-scd2-unqualified-join

- **System:** SQLMesh `0.236.2`, against DuckDB `1.5.5` through its `duckdb` gateway.
- **Checked:** 2026-09-29.
- **Feature set:** a SQLMesh project — `config.yaml` with one gateway, four `MODEL (...)`
  blocks with `grain` and `references`, and two `METRIC (...)` blocks. Commands run: `sqlmesh
  info`, `sqlmesh plan --auto-apply`, `sqlmesh audit`, `sqlmesh rewrite`, the last for one
  ungrouped request and three grouped by a tier column.
- **Hosted features:** none, and none involved. Open-source SQLMesh with a local DuckDB
  gateway; no Tobiko Cloud and no scheduler.
- **Case:** [`tests/fixtures/semantic_corpus/003-scd2-unqualified-join`](../../../tests/fixtures/semantic_corpus/003-scd2-unqualified-join) —
  its schema and rows are read directly, so the two cannot drift. The case supplies the
  type-2 history as `silver.customer_tier`. The models here read it under other names
  (`silver.tier_versions`, `silver.tier_history`), so the views SQLMesh publishes do not
  collide with the supplied relation.

## The exact question

One customer was upgraded once, and there are two orders, one on each side of the change.
**Using SQLMesh's documented feature set, is revenue broken down by tier joined to the tier
in force when each order was placed — and is the join that reads every version prevented?**

| Request | How it is modelled | The corpus's number |
|---|---|---|
| `revenue` | `SUM(silver.orders.amount)`, no breakdown | `300.0000` |
| `revenue_by_tier` | `revenue` by `tier`, with the history declared at its real grain, `(customer_id, valid_from)` | — |
| `revenue_by_history_tier` | `revenue` by `history_tier`, with the history declared by its business key alone, as a reference | the wrong answer, `600.0000` across the groups |
| `revenue_by_tier_as_of` | `revenue_as_of` by `tier_at_order`, over a model the author wrote with the as-of predicate | the right one, `300.0000` |

## What was observed

`sqlmesh info` finds **4 models**, the plan applies them, and `sqlmesh audit` finds **0
audits**. Ungrouped, `revenue` is `300.0000`: the rewriter reads `silver.orders` alone.

With the history at its real grain, the grouped request renders an `ON` clause that compares
the order's `customer_id` with the history's composite grain,
`silver__orders.customer_id = (customer_id, valid_from)`, and DuckDB refuses it with
`Ambiguous reference to column name "customer_id"`. There is no number, right or wrong.

With the history declared by `references (customer_id)` and no grain, SQLMesh joins on the
business key, `silver__orders.customer_id = silver__tier_history.customer_id`, and returns
`('bronze', 300.0000), ('gold', 300.0000)`. Each order is counted once per version, and the
groups add to `600.0000`, the corpus's naive number. The plan and the audit are clean, and
nothing is reported.

The as-of model returns `('bronze', 100.0000), ('gold', 200.0000)`, the corpus's number. The
predicate that makes it right is in a model this project's author wrote:

```sql
ON o.customer_id = t.customer_id
AND o.ordered_at >= t.valid_from
AND o.ordered_at < t.valid_to
```

## What was not run, and why

SQLMesh has `SCD_TYPE_2_BY_TIME` and `SCD_TYPE_2_BY_COLUMN` model kinds, and they were read
rather than run. Those kinds **build** a type-2 history: across successive plans, they
compare each run's source rows with the last. This case **supplies** the history already
versioned, as the operator's snapshot, and there is no sequence of runs in the case's data to
build it from. A project that let SQLMesh build the versions would be measuring a different
case. So this bundle claims nothing about those kinds, and the cells rest only on the models
above.

## What that supports, and what it does not

For the **unanchored** reading it supports `NOT-REPRESENTED`. Declared by its business key,
the history is joined on that key alone and every version is counted. Declared at its real
grain, the rendered join cannot run. Neither declaration has a slot for the fact that a row
is valid over an interval, or for the column an order would be read as of.

For the **anchored** reading it supports `CUSTOM`. The right breakdown is reached only
through the as-of predicate in `silver.orders_as_of`, which SQLMesh plans and materialises
without knowing that it selects one version per order.

It does **not** support any statement about SQLMesh beyond this configuration and this
version. Nothing here was run against Tobiko Cloud, against another engine, or with the
SCD type-2 kinds.
