# SQLMesh × 001-order-shipping-fanout

- **System:** SQLMesh `0.236.2`, against DuckDB `1.5.5` through its `duckdb` gateway.
- **Checked:** 2026-09-29.
- **Feature set:** a SQLMesh project — `config.yaml` with one gateway, three `MODEL (...)`
  blocks with `grain` and `references`, and two `METRIC (...)` blocks. Commands run: `sqlmesh
  info`, `sqlmesh plan --auto-apply`, `sqlmesh audit`, `sqlmesh rewrite`, the last for two
  single-metric requests and one request grouped by a line-grain column.
- **Hosted features:** none, and none involved. Open-source SQLMesh with a local DuckDB
  gateway; no Tobiko Cloud and no scheduler.
- **Case:** [`tests/fixtures/semantic_corpus/001-order-shipping-fanout`](../../../tests/fixtures/semantic_corpus/001-order-shipping-fanout) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

Shipping is stored once per order; an order has three lines. **Using SQLMesh's documented
feature set, is a sum of shipping over line-grain rows prevented before it returns a number —
and what does SQLMesh produce when shipping is asked for at its own grain, or broken down by
a line?**

| Request | How it is modelled | The corpus's number |
|---|---|---|
| `shipping_total` | `SUM(silver.orders.shipping)`, over the model that stores it once per order | the right answer, `9.0000` |
| `shipping_total_on_lines` | `SUM(silver.order_lines.shipping)`, over a model the author wrote that joins lines to orders | the wrong one, `27.0000` |
| `shipping_by_line` | `shipping_total` grouped by `line_no`, a column of `silver.order_items` | — |

## What was observed

`sqlmesh info` finds **3 models**, the plan applies them, and `sqlmesh audit` finds **0
audits**. Both metrics load and render, and they return the corpus's two numbers:
`9.0000` and `27.0000`. Nothing in the load, the plan or the audit tells them apart.
`silver.order_lines` declares an honest grain, `(order_id, line_no)`, and nothing in its
`MODEL` block, or in any other key, says that its `shipping` column belongs to an order.

The grouped request is where SQLMesh builds the join itself. Asked for `shipping_total` by
`line_no`, the rewriter finds `line_no` on `silver.order_items` and joins it to
`silver.orders` along the references. The `ON` clause it renders compares the order's key
with the line model's composite grain:

```sql
LEFT JOIN silver.order_items AS silver__order_items
  ON silver__orders.order_id = (order_id, line_no)
```

and DuckDB refuses it:

```text
refused: BinderException: Binder Error: Ambiguous reference to column name "order_id"
```

So in this configuration the breakdown returns no number at all, right or wrong. The run
does not show what the rewriter would do with a line model whose grain is a single column.
That is a different project, and it was not run.

## What that supports, and what it does not

For the **rollup** reading it supports `NATIVE-PLAN`: shipping asked for over the model that
stores it returns `9.0000`, and the SQL is SQLMesh's own.

For the **representation** reading — a line-grain relation carrying an order-grain measure —
it supports `NOT-REPRESENTED`. The fan-out is in a model this project's author wrote. The
metric over it returns `27.0000`, and no key in `MODEL` or `METRIC` records that a column
originates at a coarser grain than the model it sits in.

For the **refinement** reading the run shows something narrower. SQLMesh's own join to a
line-grain column renders SQL the engine refuses. That is a failure of this version to
render the request, not a check on shipping's grain. Nothing in `observed.txt` rests on a
grain rule, and the cell should say so rather than read the refusal as a prevention.

It does **not** support any statement about SQLMesh beyond this configuration and this
version. Nothing here was run against Tobiko Cloud, against another engine, or with
SQLMesh's linter enabled.
