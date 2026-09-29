# SQLMesh × 012-rollup-recounts-identities

- **System:** SQLMesh `0.236.2`, against DuckDB `1.5.5` through its `duckdb` gateway.
- **Checked:** 2026-09-29.
- **Feature set:** a SQLMesh project — `config.yaml` with one gateway, two `MODEL (...)`
  blocks with `grain` and `references`, and four `METRIC (...)` blocks. Commands run: `sqlmesh
  info`, `sqlmesh plan --auto-apply`, `sqlmesh audit`, `sqlmesh rewrite`, the last for the
  buyer metrics alone and for buyers and revenue together, over the rollup and over the
  orders.
- **Hosted features:** none, and none involved. Open-source SQLMesh with a local DuckDB
  gateway; no Tobiko Cloud and no scheduler.
- **Case:** [`tests/fixtures/semantic_corpus/012-rollup-recounts-identities`](../../../tests/fixtures/semantic_corpus/012-rollup-recounts-identities) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

Three customers over two days of January, and `c1` buys on both. The dashboard reads a daily
pre-aggregate because reading every order is slow. **Using SQLMesh's documented feature set,
is a buyer count re-added from that rollup prevented before it returns a number — and what
does SQLMesh produce reading the orders instead?**

| Request | How it is modelled | The corpus's number |
|---|---|---|
| `rolled` | `buyers_rolled` and `revenue_rolled`: `SUM` over `silver.daily_sales`'s `daily_buyers` and `daily_revenue` | buyers, the wrong answer, `4` |
| `detail` | `buyers` and `revenue`: `COUNT(DISTINCT customer_id)` and `SUM(amount)` over `silver.orders` | buyers, the right one, `3` |

## What was observed

`sqlmesh info` finds **2 models**, the plan applies both, and `sqlmesh audit` finds **0
audits**. Over the rollup the request returns `(4, 110.00)`, and over the orders it returns
`(3, 110.00)`. Revenue survives the re-addition and the buyer count does not. Nothing in the
load, the plan or the audit distinguishes the two requests.

A metric in this project names the model it reads, so the rollup is read only when a metric
names it. SQLMesh did not substitute `silver.daily_sales` for `silver.orders` in any rendering
here, and nothing in this run shows it choosing between a rollup and its detail.

The probe is the last line. An `additive` key on the rollup model is rejected by SQLMesh's
own loader:

```text
Error: Failed to load model from file '<scratch>/probe/models/daily_sales.sql':: Invalid
field name present in the MODEL block: 'additive'
```

## What that supports, and what it does not

For the **rolled** reading it supports `NOT-REPRESENTED`. `daily_buyers` and `daily_revenue`
are two numeric columns of one model, and nothing states that one may be re-added
across days and the other may not. Both `SUM`s load, plan, audit and return.

For the **detail** reading it supports `NATIVE-PLAN`. `COUNT(DISTINCT ...)` over the orders is
a bare aggregate of a model column, rendered by SQLMesh and returning `3`.

It does **not** support any statement about SQLMesh beyond this configuration and this
version. Nothing here was run against Tobiko Cloud, against another engine, or with any
feature that routes a request to a pre-aggregate on SQLMesh's own initiative.
