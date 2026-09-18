# SQLMesh × 008-ratio-rollup

- **System:** SQLMesh `0.236.1`, against DuckDB `1.5.5` through its `duckdb` gateway.
- **Checked:** 2026-09-18.
- **Feature set:** a SQLMesh project — `config.yaml` with one gateway, one `MODEL (...)` block
  with `grain` and `references`, and four `METRIC (...)` blocks, one of them derived from two
  others. Commands run: `sqlmesh info`, `sqlmesh plan --auto-apply`, `sqlmesh audit`, `sqlmesh
  rewrite`.
- **Hosted features:** none, and none involved. Open-source SQLMesh with a local DuckDB
  gateway; no Tobiko Cloud and no scheduler.
- **Case:** [`tests/fixtures/semantic_corpus/008-ratio-rollup`](../../../tests/fixtures/semantic_corpus/008-ratio-rollup) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

Each order's revenue per item is a correct rate for that order. Averaging the rates weights a
thirty-line order the same as a ten-line one. **Using SQLMesh's documented feature set, is a
metric that averages a stored rate prevented before it returns a number — and what does
SQLMesh produce for the rate rebuilt from its operands?**

| Metric | How it is modelled | The corpus's number |
|---|---|---|
| `revenue_per_item_naive` | `AVG(silver.orders.revenue / silver.orders.item_count)` | the wrong answer, `3.50` |
| `revenue_per_item_declared` | a derived metric, `revenue_total / item_total` | the right one, `3.25` |

## What was observed

`sqlmesh info` finds **1 model**, the plan applies it, and `sqlmesh audit` finds **0 audits**.
Both metrics load, and nothing distinguishes them: one averages a quotient, the other divides
two sums, and SQLMesh has no opinion about which of those the question wanted.

`sqlmesh rewrite` renders both, and both renderings are SQLMesh's own. The declared metric's
is the whole point of the cell:

```sql
SELECT revenue_total / item_total AS revenue_per_item_declared
FROM (
  SELECT SUM(silver__orders.item_count) AS item_total,
         SUM(silver__orders.revenue) AS revenue_total
  FROM silver.orders AS silver__orders
) AS __table
```

The operands are re-aggregated and divided at the grain asked for, with no SQL from this
project beyond the two column aggregates. The numbers are the corpus's own: `3.5` and `3.25`.

The probe is the last line. Adding `already_a_rate true` to the naive metric — the fact that
would make it refusable — is rejected by SQLMesh's own loader:

```text
Error: 1 validation error for MetricMeta: already_a_rate Extra inputs are not permitted
```

## What that supports, and what it does not

It supports two cells. The fact that a stored column is **already a rate** has no
representation in this feature set, by the same closed key set `002` probed. And the correct
rate is reached **natively**: SQLMesh's derived metrics are exactly the mechanism that rebuilds
a ratio at the requested grain, and this is the cell where that mechanism is doing the work
rather than the author.

It does **not** support any statement about SQLMesh beyond this configuration and this
version, and nothing here was run against Tobiko Cloud, another engine, or the linter.
