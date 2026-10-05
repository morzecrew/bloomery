# dbt Core × 006-two-grains-one-request

- **System:** dbt Core `1.12.5`, with the `dbt-duckdb` `1.11.0` adapter against DuckDB `1.5.5`.
- **Checked:** 2026-10-05.
- **Feature set:** a dbt project — `sources:`, models, and the `semantic_models:` and
  `metrics:` blocks dbt parses into its manifest (`dbt/contracts/graph/unparsed.py`), here two
  semantic models at their own grains (`order` and `order_line`, joined by a `foreign` entity),
  one `sum` measure on each, and a `simple` metric on each. Commands run: `dbt build`,
  `dbt list`, `dbt compile`.
- **Hosted features:** none, and none reachable. `dbt-metricflow` is not installed and no dbt
  Cloud or dbt Semantic Layer service is involved, so nothing here queries a metric. What dbt
  Core alone does with the definitions is the whole measurement, and the cells say nothing
  about any other configuration.
- **Case:** [`tests/fixtures/semantic_corpus/006-two-grains-one-request`](../../../tests/fixtures/semantic_corpus/006-two-grains-one-request) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

Shipping is a fact about an order and discount a fact about a line, and both are wanted in
one answer. **Using dbt Core's documented feature set, does a request for both metrics get a
plan that aggregates each at its own grain — and what does dbt Core itself produce?**

| Expectation | How it is modelled | The corpus's number |
|---|---|---|
| `branches` | metrics `shipping_total` and `discount_total`, each on the semantic model of its own grain | `16.0000` shipping, `6.0000` discount |

The corpus's naive reading — one join, then both sums — is modelled beside it as
`two_grains_joined`, so the run shows what the tempting SQL returns here too.

## What was observed

`dbt build` finds **2 metrics and 2 semantic models** and completes with `PASS=5 WARN=0
ERROR=0`.

`dbt compile --select metric:shipping_total` and `metric:discount_total` render **no SQL** —
`Nothing to do.` In this configuration dbt Core does not render a query for a metric, so no
dbt-constructed plan for the two-metric request exists to observe.

The numbers in `observed.txt` therefore come from **models this project's author wrote**:
`two_grains_joined` returns `36.0000` shipping and `6.0000` discount, and
`two_grains_composed` (each side aggregated at its own grain, then cross-joined) returns
`16.0000` and `6.0000`. All four are the corpus's own, pinned in `expected/result.json`.

## What that supports, and what it does not

It supports, at this version and in this configuration:

- **The grain of each measure is represented natively**: each is declared on the semantic
  model whose primary entity is its grain, and dbt accepted both.
- **`branches`:** the correct composition was produced **only through project-authored SQL**,
  because no dbt Core command in this configuration renders a metric, let alone two.
- The naive joined model built without comment and returned the multiplied shipping total.

It does **not** support any statement about dbt beyond this configuration and this version.
In particular it says nothing about how an engine that renders metrics — `dbt-metricflow`, or
the dbt Semantic Layer service — plans a request for two metrics from two semantic models:
neither was run here.
