# MetricFlow × 008-ratio-rollup

- **System:** MetricFlow `0.212.0`, driven from Python against DuckDB `1.5.5`.
- **Checked:** 2026-09-15.
- **Feature set:** semantic models with `measures`, a `simple` metric, and a `ratio` metric
  over two `simple` metrics (`metricflow_semantic_interfaces/parsing/schemas.py`). No
  project-authored SQL.
- **Hosted features:** none. Everything here runs from the installed package against a local
  DuckDB; no dbt Cloud or dbt Semantic Layer service is involved.
- **Case:** [`tests/fixtures/semantic_corpus/008-ratio-rollup`](../../../tests/fixtures/semantic_corpus/008-ratio-rollup) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

`revenue` and `item_count` are both additive facts about an order; `revenue / item_count` is
not additive over anything. **Using MetricFlow's documented feature set, is a metric that
averages the stored quotient prevented before it returns a number?**

| Metric | How it is modelled | What it should return |
|---|---|---|
| `revenue_per_item_naive` | a measure with `agg: average` and `expr: revenue / item_count` | the wrong answer, `3.50` |
| `revenue_per_item_ratio` | `type: ratio`, numerator `revenue`, denominator `item_count` | the right one, `3.25` |

## What was observed

MetricFlow's own `SemanticManifestValidator` reports **0 errors, 0 warnings**.
`revenue_per_item_naive` returns
`3.5`; `revenue_per_item_ratio` returns `3.25`. Full transcript in `observed.txt`. Both
match the corpus's `expected/result.json`.

## A detail the reproduction forced, worth recording

A `ratio` metric's `numerator` and `denominator` name **metrics**, not measures:
declaring them against the measure names fails to build with `Metric 'revenue' is not
configured as a metric in the model`. The bundle therefore declares two `simple` metrics
whose only purpose is to be composed. This is a modelling cost, not a semantic one, and it
is the reason the manifest carries four metrics for two questions.

## What that supports, and what it does not

The correct construction is **native**: the quotient is rebuilt from its operands at the
requested grain, by a documented metric type, and the number is right.

The failure is **not represented** in this feature set. A measure whose `expr` is already a
quotient and whose `agg` is `average` is exactly as valid, to `0.212.0`'s validator, as the
ratio metric beside it. Nothing in the manifest records that `revenue / item_count` is a
constructed rate rather than a stored quantity, so nothing can notice that averaging it is
meaningless.

Neither half is a statement about MetricFlow beyond `0.212.0` and this configuration. In
particular it says nothing about whether a dbt test or a review convention would catch the
stored rate — only that the semantic layer itself does not.
