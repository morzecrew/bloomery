# SQLMesh × 004-currency-mix

- **System:** SQLMesh `0.236.2`, against DuckDB `1.5.5` through its `duckdb` gateway.
- **Checked:** 2026-09-29.
- **Feature set:** a SQLMesh project — `config.yaml` with one gateway, four `MODEL (...)`
  blocks with `grain`, and three `METRIC (...)` blocks. Commands run: `sqlmesh info`,
  `sqlmesh plan --auto-apply`, `sqlmesh audit`, `sqlmesh rewrite`.
- **Hosted features:** none, and none involved. Open-source SQLMesh with a local DuckDB
  gateway; no Tobiko Cloud and no scheduler.
- **Case:** [`tests/fixtures/semantic_corpus/004-currency-mix`](../../../tests/fixtures/semantic_corpus/004-currency-mix) —
  its schema and rows are read directly, so the two cannot drift. The case supplies the
  rate relation as `silver.fx_rate`. The model here reads it as `silver.fx_rates`, so the
  view SQLMesh publishes does not collide with the supplied relation.

## The exact question

Each payment carries a settled amount in euros and a fee in dollars. **Using SQLMesh's
documented feature set, is a metric that adds the two prevented before it returns a number —
and what does it take to get dollars?**

| Metric | How it is modelled | The corpus's number |
|---|---|---|
| `total_usd_mixed` | `SUM(amount_eur + fee_usd)` over `silver.payments` | the wrong answer, `157.5000` |
| `total_usd_converted` | the same sum over `silver.payments_usd`, a model that converts at the dated EUR→USD rate | the right one, `172.5000` |
| `total_usd_mislabelled` | the same sum over a model that converts the euros with a JPY→USD rate | — |

## What was observed

`sqlmesh info` finds **4 models**, the plan applies them, and `sqlmesh audit` finds **0
audits**. All three metrics load and render.

`total_usd_mixed` returns `157.5000` and `total_usd_converted` returns `172.5000`, the
corpus's two numbers. Nothing in the load, the plan or the audit distinguishes them: both
add two `DECIMAL(12, 4)` columns.

`total_usd_mislabelled` returns `None`. The rate relation has no JPY row, so the inner join
in the author's model keeps no payments and the sum is over nothing. The plan is clean, and
the null is the only sign. With a JPY row present, the same model would return a wrong number
rather than none. That variant needs rows the case does not carry, and it was not run.

The two probes are the last lines. A `unit` key on the metric and a `currency` key on the
payments model are both rejected by SQLMesh's own loader:

```text
Error: 1 validation error for MetricMeta: unit Extra inputs are not permitted
Error: Failed to load model from file '<scratch>/probe/models/payments.sql':: Invalid field
name present in the MODEL block: 'currency'
```

## What that supports, and what it does not

For the **mixed** reading it supports `NOT-REPRESENTED`. The denomination of a column has no
slot in `MetricMeta` or `ModelMeta`, and the probes show that an invented key is refused on
both.

For the **converted** reading it supports `CUSTOM`. The right total comes from a model this
project's author wrote: the currency pair, the dated join and the multiplication are SQL that
SQLMesh carries through without knowing it is a conversion.

For the **mislabelled** reading it supports `NOT-REPRESENTED`. A conversion that names the
wrong input currency plans and runs clean, because nothing records which currency the input
was in.

It does **not** support any statement about SQLMesh beyond this configuration and this
version. A project could convert inside the metric's expression or upstream of SQLMesh
instead. Both are the same kind of author-written SQL, and neither was run here.
