# dbt Core × 010-many-to-many-bridge

- **System:** dbt Core `1.12.3`, with the `dbt-duckdb` `1.11.0` adapter against DuckDB `1.5.5`.
- **Checked:** 2026-09-29.
- **Feature set:** a dbt project — `sources:`, models, and the `semantic_models:` and
  `metrics:` blocks dbt parses into its manifest (`dbt/contracts/graph/unparsed.py`), here
  four semantic models: `orders` and `promos` at their own grains, the `order_promos` bridge
  with two `foreign` entities, and a bridged mart listing revenue; a `sum` measure and a
  `simple` metric on each of the two that carry revenue. Commands run: `dbt build`, `dbt list`,
  `dbt compile`.
- **Hosted features:** none, and none reachable. `dbt-metricflow` is not installed and no dbt
  Cloud or dbt Semantic Layer service is involved, so nothing here queries a metric. What dbt
  Core alone does with the definitions is the whole measurement, and the cells say nothing
  about any other configuration.
- **Case:** [`tests/fixtures/semantic_corpus/010-many-to-many-bridge`](../../../tests/fixtures/semantic_corpus/010-many-to-many-bridge) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

Revenue is a fact about an order; a bridge row names one order and one promotion, so an
order with two promotions reaches the bridge twice. **Using dbt Core's documented feature
set, is a mart at bridge grain that lists revenue prevented before it returns a number — and
what does dbt Core itself produce for revenue at its own grain?**

| Expectation | How it is modelled | The corpus's number |
|---|---|---|
| `bridged` | semantic model `order_promos_wide` (primary entity `order_promo_row`) over a model joining the bridge to orders and promos, with `revenue_on_promos` as `agg: sum` | the wrong answer, `250.00` |
| `per_order` | semantic model `orders` (primary entity `order`) with `revenue` as `agg: sum` | the right one, `150.00` |

## What was observed

`dbt build` finds **2 metrics and 4 semantic models** and completes with `PASS=7 WARN=0
ERROR=0`. The bridged semantic model, carrying an order-grain value at bridge grain, was
accepted beside the bridge declared with its two `foreign` entities.

`dbt compile --select metric:revenue` and `metric:revenue_bridged` render **no SQL** —
`Nothing to do.` In this configuration dbt Core does not render a query for a metric, so no
dbt-constructed join path through the bridge exists to observe.

The two numbers in `observed.txt` therefore come from **models this project's author wrote**:
`revenue_bridged` returns `250.00` and `revenue_per_order` returns `150.00`. Both are the
corpus's own, pinned in `expected/result.json`.

## What that supports, and what it does not

It supports, at this version and in this configuration:

- **`bridged`:** the bridge-grain semantic model listing revenue is accepted by `dbt build`.
  No key in `UnparsedMeasure` or `UnparsedSemanticModel` states that the column's value
  originates at `order`, and nothing in the run objected.
- **`per_order`:** revenue at its own grain is declared natively and accepted, and the
  correct number was produced **only through project-authored SQL**, because no dbt Core
  command in this configuration renders a metric.

It does **not** support any statement about dbt beyond this configuration and this version.
In particular it says nothing about which join paths `dbt-metricflow` or the dbt Semantic
Layer service would take through the `order_promos` semantic model: neither was run here.
