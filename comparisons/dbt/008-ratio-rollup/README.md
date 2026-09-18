# dbt Core × 008-ratio-rollup

- **System:** dbt Core `1.12.3`, with the `dbt-duckdb` `1.11.0` adapter against DuckDB `1.5.5`.
- **Checked:** 2026-09-18.
- **Feature set:** a dbt project — `sources:`, models, and the `semantic_models:` and
  `metrics:` blocks dbt parses into its manifest (`dbt/contracts/graph/unparsed.py`), here
  measures, `simple` metrics and a `ratio` metric. Commands run: `dbt build`, `dbt list`,
  `dbt compile`, `dbt parse`.
- **Hosted features:** none, and none reachable. `dbt-metricflow` is not installed and no dbt
  Cloud or dbt Semantic Layer service is involved, so nothing here queries a metric. What dbt
  Core alone does with the definitions is the whole measurement.
- **Case:** [`tests/fixtures/semantic_corpus/008-ratio-rollup`](../../../tests/fixtures/semantic_corpus/008-ratio-rollup) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

Each order carries its revenue and its item count, so each order's revenue per item is right;
averaging those per-order rates weights a thirty-line order the same as a ten-line one.
**Using dbt Core's documented feature set, is the averaged-rate model prevented before it
returns a number — and what does dbt Core itself produce for either metric?**

| Metric | How it is modelled | The corpus's number |
|---|---|---|
| `revenue_per_item_naive` | `agg: average` over `revenue / item_count` | the wrong answer, `3.50` |
| `revenue_per_item_ratio` | `type: ratio` of summed revenue over summed items | the right one, `3.25` |

## What was observed

`dbt build` finds **4 metrics and 1 semantic model** and completes with `PASS=4 WARN=0
ERROR=0`. dbt's parse-time semantic validation (`dbt/contracts/graph/semantic_manifest.py`)
reports nothing about either metric.

`dbt compile --select metric:revenue_per_item_ratio` and the same for the other three metrics
render **no SQL** — `Nothing to do.` dbt Core parses metrics, lists them and writes them to
the manifest; the engine that turns one into a query ships separately.

The two numbers in `observed.txt` therefore come from **models this project's author wrote**:
`3.5` for the averaged-rate reading and `3.25` for the rebuilt quotient. Both are the
corpus's own.

The probe is the last line. Adding `already_a_rate: true` to the `stored_rate` measure — the
fact that would make the naive model refusable — is rejected by dbt's own parser:

```text
Parsing Error: at path ['measures'][2]: Additional properties are not allowed
('already_a_rate' was unexpected)
```

so the measure's key set is closed rather than a list of keys somebody happened to try.

## What that supports, and what it does not

It supports two cells. That a stored column is itself a rate — a quotient that must be
rebuilt rather than averaged — has **no representation** in this feature set, and the probe
shows the key set is closed against the attempt. And the correct answer was reached here
**only through project-authored SQL**, because in this configuration no dbt Core command
renders a metric, so the declared row is `CUSTOM` rather than `NATIVE-PLAN`.

It does **not** support any statement about dbt beyond this configuration and this version.
It says nothing about dbt Core with `dbt-metricflow` installed, or about the dbt Semantic
Layer service: neither was run here. The engine those paths use is MetricFlow, measured in
its own column at `0.212.0`, where this case's declared row is `NATIVE-PLAN`.
