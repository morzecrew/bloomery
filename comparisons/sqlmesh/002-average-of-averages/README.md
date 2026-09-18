# SQLMesh × 002-average-of-averages

- **System:** SQLMesh `0.236.1`, against DuckDB `1.5.5` through its `duckdb` gateway.
- **Checked:** 2026-09-18.
- **Feature set:** a SQLMesh project — `config.yaml` with one gateway, `MODEL (...)` DDL with
  `grain` and `references`, and `METRIC (...)` DDL, including a derived metric written over
  two other metrics. Commands run: `sqlmesh info`, `sqlmesh plan --auto-apply`, `sqlmesh
  audit`, `sqlmesh rewrite`.
- **Hosted features:** none, and none involved. This is open-source SQLMesh with a local
  DuckDB gateway; no Tobiko Cloud, no scheduler, no state beyond the scratch directory the
  run creates. What SQLMesh alone does with these definitions is the whole measurement, and
  the cells say nothing about any other configuration.
- **Case:** [`tests/fixtures/semantic_corpus/002-average-of-averages`](../../../tests/fixtures/semantic_corpus/002-average-of-averages) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

An upstream system publishes a per-order rollup, `average_item_price`, and it is a correct
average of each order's lines. **Using SQLMesh's documented feature set, is a metric that
re-aggregates that stored average prevented before it returns a number — and what does
SQLMesh itself produce for either metric?**

Both metrics are declared in one project, because the pair is what the question is about:

| Metric | How it is modelled | The corpus's number |
|---|---|---|
| `average_item_price_naive` | `AVG(silver.order_summaries.average_item_price)` | the wrong answer, `55.00` |
| `average_item_price_decomposed` | a derived metric, `unit_price_total / line_count` | the right one, `32.50` |

## What was observed

`sqlmesh info` finds **2 models** and `sqlmesh plan --auto-apply --no-prompts` applies them
and finishes with `Virtual layer updated`. Nothing in the load, the plan or `sqlmesh audit`
distinguishes the two metrics: the naive definition and the decomposed one are equally
acceptable to SQLMesh.

`sqlmesh rewrite` renders SQL for both, and the SQL is SQLMesh's own. For the naive metric it
is `AVG(silver__order_summaries.average_item_price)` over the summaries model; for the
decomposed one it builds `COUNT(...)` and `SUM(...)` in a subquery and divides them in the
outer select. The numbers in `observed.txt` are what that rendered SQL returns against the
case's rows: `55.0` and `32.5`, which are the corpus's own `55.00000000` for the naive
reading and `32.50000000` for the correct one.

The probe is the last line. Adding `already_aggregated true` to the metric — the fact that
would make the naive metric refusable — is rejected by SQLMesh's own loader:

```text
Error: 1 validation error for MetricMeta: already_aggregated Extra inputs are not permitted
```

so `METRIC`'s key set is closed rather than a list of keys somebody happened to try.

## What that supports, and what it does not

It supports two cells. The fact that a stored column is already an aggregate has **no
representation** in this feature set: `MetricMeta`'s keys are `name`, `dialect`, `expression`,
`description` and `owner`, and the probe shows a sixth is refused. And the correct answer was
reached **natively**: `average_item_price_decomposed` is a derived metric, SQLMesh
re-aggregates its operands itself, and no SQL beyond the two column aggregates was written by
this project's author.

It does **not** support any statement about SQLMesh beyond this configuration and this
version. In particular nothing here was run against Tobiko Cloud, against another engine, or
with SQLMesh's linter rules enabled, and the cells claim nothing about them.
