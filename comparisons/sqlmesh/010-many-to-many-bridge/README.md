# SQLMesh × 010-many-to-many-bridge

- **System:** SQLMesh `0.236.2`, against DuckDB `1.5.5` through its `duckdb` gateway.
- **Checked:** 2026-09-29.
- **Feature set:** a SQLMesh project — `config.yaml` with one gateway, four `MODEL (...)`
  blocks with `grain` and `references`, and two `METRIC (...)` blocks. Commands run: `sqlmesh
  info`, `sqlmesh plan --auto-apply`, `sqlmesh audit`, `sqlmesh rewrite`, the last for each
  metric alone and for revenue grouped by promotion label.
- **Hosted features:** none, and none involved. Open-source SQLMesh with a local DuckDB
  gateway; no Tobiko Cloud and no scheduler.
- **Case:** [`tests/fixtures/semantic_corpus/010-many-to-many-bridge`](../../../tests/fixtures/semantic_corpus/010-many-to-many-bridge) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

`o1` used two promotions and `o2` used one. **Using SQLMesh's documented feature set, is a
revenue sum reached through the order–promotion bridge prevented before it returns a
number — and what does SQLMesh produce for revenue at the order's own grain, or broken down
by promotion?**

| Request | How it is modelled | The corpus's number |
|---|---|---|
| `revenue` | `SUM(silver.orders.revenue)` | the right answer, `150.00` |
| `revenue_through_bridge` | `SUM(silver.promoted_orders.revenue)`, over a model the author wrote that joins orders through the bridge | the wrong one, `250.00` |
| `revenue_by_label` | `revenue` grouped by `label`, a column of `silver.promos`, with the join left to SQLMesh | — |

The bridge, `silver.order_promos`, declares `references (order_id, promo_id)`. `silver.orders`
and `silver.promos` declare their grains.

## What was observed

`sqlmesh info` finds **4 models**, the plan applies them, and `sqlmesh audit` finds **0
audits**. `revenue` returns `150.00` and `revenue_through_bridge` returns `250.00`, the
corpus's two numbers. Nothing in the load, the plan or the audit distinguishes them.

For the grouped request SQLMesh finds a path from `silver.orders` through the bridge to
`silver.promos` and renders it. The first `ON` clause pairs the order's key with the
bridge's **promotion** reference:

```sql
LEFT JOIN silver.order_promos AS silver__order_promos
  ON silver__orders.order_id = silver__order_promos.promo_id
```

No order id equals a promotion id, so every order falls through the left join. The result is
one row, `(None, 150.00)`: the correct total under a null label, with no breakdown. The
request runs, returns, and reports nothing.

## What that supports, and what it does not

For the **per_order** reading it supports `NATIVE-PLAN`: revenue over the model that stores
it returns `150.00`, from SQL that is SQLMesh's own.

For the **bridged** reading it supports `NOT-REPRESENTED`. The fan-out is in a model this
project's author wrote, and the metric over it returns `250.00`. Nothing in `MODEL` or
`METRIC` records that `revenue` originates at the order and may not be summed over bridge
rows.

The grouped request shows that, in this configuration, SQLMesh's own traversal of the
bridge renders a join on the wrong pair of columns and returns an unlabelled total. That is
neither a prevention nor the naive fan-out, and the cell should not read it as either.

It does **not** support any statement about SQLMesh beyond this configuration and this
version. A bridge that declared its references in the other order, or one reference per
model, is a different project, and it was not run.
