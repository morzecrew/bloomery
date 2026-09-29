# dbt Core × 007-distinct-users-fanout

- **System:** dbt Core `1.12.3`, with the `dbt-duckdb` `1.11.0` adapter against DuckDB `1.5.5`.
- **Checked:** 2026-09-29.
- **Feature set:** a dbt project — `sources:`, models, and the `semantic_models:` and
  `metrics:` blocks dbt parses into its manifest (`dbt/contracts/graph/unparsed.py`), here a
  `count_distinct` measure on the sessions semantic model, a `sum` measure over a per-day
  distinct count on a second semantic model, and a `simple` metric on each. Commands run:
  `dbt build`, `dbt list`, `dbt compile`.
- **Hosted features:** none, and none reachable. `dbt-metricflow` is not installed and no dbt
  Cloud or dbt Semantic Layer service is involved, so nothing here queries a metric. What dbt
  Core alone does with the definitions is the whole measurement, and the cells say nothing
  about any other configuration.
- **Case:** [`tests/fixtures/semantic_corpus/007-distinct-users-fanout`](../../../tests/fixtures/semantic_corpus/007-distinct-users-fanout) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

A distinct count has no rollup: two days' distinct users do not add up to the period's.
**Using dbt Core's documented feature set, is summing a per-day distinct count prevented
before it returns a number — and what does dbt Core itself produce for the distinct count?**

| Expectation | How it is modelled | The corpus's number |
|---|---|---|
| `naive` | semantic model `daily_active_users` with `daily_users_summed` as `agg: sum` over the per-day `count(distinct user_id)`; model `active_users_summed` | the wrong answer, `4` |
| `declared` | measure `active_users`, `agg: count_distinct`, `expr: user_id`, on the sessions semantic model; model `active_users_distinct` | the right one, `3` |

## What was observed

`dbt build` finds **2 metrics and 2 semantic models** and completes with `PASS=5 WARN=0
ERROR=0`. The `sum` over a column that is itself a distinct count was accepted beside the
`count_distinct` measure; nothing in the run related the two.

`dbt compile --select metric:active_users` and `metric:active_users_summed` render **no SQL**
— `Nothing to do.` In this configuration dbt Core does not render a query for a metric.

The two numbers in `observed.txt` therefore come from **models this project's author wrote**:
`active_users_summed` returns `4` and `active_users_distinct` returns `3`. Both are the
corpus's own, pinned in `expected/result.json`.

## What that supports, and what it does not

It supports, at this version and in this configuration:

- **`declared`:** a distinct count is a native aggregation, `count_distinct`, and dbt accepted
  it; the correct number was produced **only through project-authored SQL**, because no dbt
  Core command in this configuration renders a metric.
- **`naive`:** the column a per-day distinct count lands in is, to the measure declared over
  it, a number like any other. The `sum` measure built without comment; no key in
  `UnparsedMeasure` states that a column is already a distinct count.

It does **not** support any statement about dbt beyond this configuration and this version.
In particular it says nothing about how `dbt-metricflow` or the dbt Semantic Layer service
aggregates a `count_distinct` measure across a time grain: neither was run here.
