# dbt Core × 012-rollup-recounts-identities

- **System:** dbt Core `1.12.5`, with the `dbt-duckdb` `1.11.0` adapter against DuckDB `1.5.5`.
- **Checked:** 2026-10-05.
- **Feature set:** a dbt project — `sources:`, models (one materialized as a `table` through
  `config(materialized='table')`), and the `semantic_models:` and `metrics:` blocks dbt parses
  into its manifest (`dbt/contracts/graph/unparsed.py`), here a detail semantic model with a
  `sum` and a `count_distinct` measure, a semantic model over the monthly rollup with two `sum`
  measures, and a `simple` metric on each of the four. Commands run: `dbt build`, `dbt list`,
  `dbt compile`.
- **Hosted features:** none, and none reachable. `dbt-metricflow` is not installed and no dbt
  Cloud or dbt Semantic Layer service is involved, so nothing here queries a metric. What dbt
  Core alone does with the definitions is the whole measurement, and the cells say nothing
  about any other configuration.
- **Case:** [`tests/fixtures/semantic_corpus/012-rollup-recounts-identities`](../../../tests/fixtures/semantic_corpus/012-rollup-recounts-identities) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

The dashboard reads a monthly table built by adding up a daily pre-aggregate. Revenue
survives that; the distinct-customer count does not. **Using dbt Core's documented feature
set, is the rollup that re-adds a distinct count prevented before it is built — and what does
dbt Core itself produce from the detail?**

| Expectation | How it is modelled | The corpus's number |
|---|---|---|
| `rolled` | model `orders_monthly`, a materialized table summing `orders_daily`'s `buyers` and `revenue`; semantic model `orders_monthly` with both as `agg: sum`; model `january_from_rollup` | the wrong answer, `4` buyers |
| `detail` | semantic model `orders` with `buyers` as `agg: count_distinct` over `customer_id`; model `january_from_detail` | the right one, `3` buyers |

## What was observed

`dbt build` finds **4 metrics and 2 semantic models** and completes with `PASS=6 WARN=0
ERROR=0`: the monthly table was materialized with its re-added `buyers` column, and the
semantic model declaring that column summable was accepted beside the `count_distinct`
measure over the same customers.

`dbt compile --select metric:<name>` for all four metrics renders **no SQL** — `Nothing to
do.` In this configuration dbt Core does not render a query for a metric, so whether a metric
would be answered from the rollup or from the detail is not observable here.

The numbers in `observed.txt` therefore come from **models this project's author wrote**:
`january_from_rollup` returns `4` buyers and `110.00` revenue, and `january_from_detail`
returns `3` buyers and `110.00` revenue. The buyer counts are the corpus's own, pinned in
`expected/result.json`; the matching revenue is the half of the rollup that is right.

## What that supports, and what it does not

It supports, at this version and in this configuration:

- **`rolled`:** a model built by aggregating another is SQL like any other model, and nothing
  in the run related `orders_monthly.buyers` to the distinct count it was summed from. The
  wrong rollup was built, materialized and read without comment.
- **`detail`:** the distinct count is a native aggregation and was accepted; the correct
  number was produced **only through project-authored SQL**, because no dbt Core command in
  this configuration renders a metric.

It does **not** support any statement about dbt beyond this configuration and this version.
In particular it says nothing about `dbt-metricflow`, the dbt Semantic Layer service, or any
caching or pre-aggregation feature they offer: none was run here.
