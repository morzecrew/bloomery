# SQLMesh × 006-two-grains-one-request

- **System:** SQLMesh `0.236.2`, against DuckDB `1.5.5` through its `duckdb` gateway.
- **Checked:** 2026-09-29.
- **Feature set:** a SQLMesh project — `config.yaml` with one gateway, two `MODEL (...)`
  blocks with `grain` and `references`, and two `METRIC (...)` blocks. Commands run: `sqlmesh
  info`, `sqlmesh plan --auto-apply`, `sqlmesh audit`, `sqlmesh rewrite`, the last for each
  metric alone, for both in one request, and for both grouped by `order_id`.
- **Hosted features:** none, and none involved. Open-source SQLMesh with a local DuckDB
  gateway; no Tobiko Cloud and no scheduler.
- **Case:** [`tests/fixtures/semantic_corpus/006-two-grains-one-request`](../../../tests/fixtures/semantic_corpus/006-two-grains-one-request) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

Shipping is stored once per order and discount once per line. **Using SQLMesh's documented
feature set, what does one request for both return — each at its own grain, or both over the
join that puts them in one relation?**

| Request | How it is modelled | The corpus's number |
|---|---|---|
| `shipping_and_discount` | `SELECT METRIC(shipping_total), METRIC(discount_total)`, no grouping | `16.0000` and `6.0000` |
| `shipping_and_discount_by_order` | the same two metrics grouped by `order_id` | — |

`shipping_total` is `SUM(silver.orders.shipping)` and `discount_total` is
`SUM(silver.order_items.discount)`. Each metric names the model its column is stored in, and
neither expression names the other model.

## What was observed

`sqlmesh info` finds **2 models**, the plan applies them, and `sqlmesh audit` finds **0
audits**. Alone, the two metrics return `16.0000` and `6.0000`.

Asked for together, the rewriter builds one subquery per model, aggregates each, and joins
the results:

```sql
FROM (SELECT SUM(silver__orders.shipping) AS shipping_total
      FROM silver.orders AS silver__orders) AS __table
FULL JOIN (SELECT SUM(silver__order_items.discount) AS discount_total
           FROM silver.order_items AS silver__order_items) AS silver__order_items
  ON TRUE
```

and returns `(16.0000, 6.0000)`, the corpus's correct answer. Grouped by `order_id`, the
same shape joins the two aggregates on the key and returns `o1` `9.0000`/`3.0000`, `o2`
`5.0000`/`2.0000`, `o3` `2.0000`/`1.0000`. The two columns add up to the ungrouped numbers.

## What that supports, and what it does not

It supports `NATIVE-PLAN` for the **branches** reading. The rewriter aggregates each metric
over the model its expression names and joins only afterwards, and no SQL beyond the two
column aggregates was written by this project's author.

That result depends on each metric naming the model that stores its column. A project that
first joins lines to orders in a model and declares both metrics over it gets the fan-out of
`001`'s `shipping_total_on_lines`. The rewriter would see one model, and nothing would tell
the two apart. That variant is measured in `001`'s bundle and was not repeated here.

It does **not** support any statement about SQLMesh beyond this configuration and this
version, and nothing here was run against Tobiko Cloud, another engine, or the linter.
