# dbt Core × 001-order-shipping-fanout

- **System:** dbt Core `1.12.3`, with the `dbt-duckdb` `1.11.0` adapter against DuckDB `1.5.5`.
- **Checked:** 2026-09-29.
- **Feature set:** a dbt project — `sources:`, models, and the `semantic_models:` and
  `metrics:` blocks dbt parses into its manifest (`dbt/contracts/graph/unparsed.py`), here two
  semantic models with `primary` and `foreign` entities, one `sum` measure on each, and a
  `simple` metric on each measure. Commands run: `dbt build`, `dbt list`, `dbt compile`.
- **Hosted features:** none, and none reachable. `dbt-metricflow` is not installed and no dbt
  Cloud or dbt Semantic Layer service is involved, so nothing here queries a metric. What dbt
  Core alone does with the definitions is the whole measurement, and the cells say nothing
  about any other configuration.
- **Case:** [`tests/fixtures/semantic_corpus/001-order-shipping-fanout`](../../../tests/fixtures/semantic_corpus/001-order-shipping-fanout) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

`shipping` is a fact about an order and is stored once per order; joining orders to their
lines hands every line a copy of it. **Using dbt Core's documented feature set, is a
line-grain mart that lists the order-grain `shipping` measure prevented before it returns a
number — and what does dbt Core itself produce for the order-grain reading?**

Both readings are declared in one project, because the pair is what the question is about:

| Expectation | How it is modelled | The corpus's number |
|---|---|---|
| `representation` | semantic model `order_lines_wide` (primary entity `order_line`) over a model joining lines to orders, with `shipping_on_lines` as `agg: sum` | the wrong answer, `27.0000` |
| `rollup` | semantic model `orders` (primary entity `order`) with `shipping` as `agg: sum` | the right one, `9.0000` |
| `refinement` | not modelled — see below | — |

## What was observed

`dbt build` finds **2 metrics and 2 semantic models** and completes with `PASS=6 WARN=0
ERROR=0`. The semantic manifest validation dbt runs while parsing
(`dbt/contracts/graph/semantic_manifest.py`) reports nothing about the line-grain semantic
model carrying a copy of an order-grain value: both semantic models are equally acceptable
to it.

`dbt compile --select metric:shipping_total` and `metric:shipping_total_wide` render **no
SQL** — `Nothing to do.` In this configuration dbt Core parses metrics, lists them and writes
them to the manifest; it does not render a query for one.

The two numbers in `observed.txt` therefore come from **models this project's author wrote**:
`shipping_total_naive` (sum over the wide mart) returns `27.0000` and `shipping_total_correct`
(sum over `orders`) returns `9.0000`. Both are the corpus's own, pinned in
`expected/result.json`.

## What that supports, and what it does not

It supports, at this version and in this configuration:

- **`representation`:** the wide semantic model is accepted by `dbt build`. Its measure is
  attached to a semantic model whose primary entity is `order_line`, and no key in
  `UnparsedMeasure` or `UnparsedSemanticModel` states that the column's value originates at
  `order`; nothing in the run objected.
- **`rollup`:** the order-grain metric is declared natively and accepted, and the correct
  number was produced **only through project-authored SQL**, because no dbt Core command in
  this configuration renders a metric.
- **`refinement`** — pulling shipping into a line-grain derivation — is a bloomery-specific
  construct with no counterpart declared here; it was **not run**, and this bundle supplies no
  evidence for that row.

It does **not** support any statement about dbt beyond this configuration and this version.
It says nothing about dbt Core with `dbt-metricflow` installed, or about the dbt Semantic
Layer service: neither was run here.
