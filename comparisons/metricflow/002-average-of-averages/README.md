# MetricFlow × 002-average-of-averages

- **System:** MetricFlow `0.212.0`, driven from Python against DuckDB `1.5.5`.
- **Checked:** 2026-09-15.
- **Feature set:** semantic models with `measures`, a `simple` metric, and a `ratio` metric
  (`metricflow_semantic_interfaces/parsing/schemas.py`). No project-authored SQL.
- **Hosted features:** none. Everything here runs from the installed package against a local
  DuckDB; no dbt Cloud or dbt Semantic Layer service is involved.
- **Case:** [`tests/fixtures/semantic_corpus/002-average-of-averages`](../../../tests/fixtures/semantic_corpus/002-average-of-averages) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

An upstream system publishes a per-order rollup, `average_item_price`, and it is a correct
average of each order's lines. **Using MetricFlow's documented feature set, is a metric that
re-aggregates that stored average prevented before it returns a number?**

Two metrics are declared in one manifest, because the pair is what the question is about:

| Metric | How it is modelled | What it should return |
|---|---|---|
| `average_item_price_naive` | `agg: average` over the published `average_item_price` column | the wrong answer, `55.00` |
| `average_item_price_decomposed` | `type: ratio` of summed `unit_price` over counted lines | the right one, `32.50` |

## What was observed

MetricFlow's own `SemanticManifestValidator` reports **0 errors, 0 warnings** for the manifest
containing both.
`average_item_price_naive` plans and returns `55.0`; `average_item_price_decomposed` plans
and returns `32.5`. Full transcript in `observed.txt`.

Both numbers are the corpus's own: `expected/result.json` pins `55.00000000` for the naive
reading and `32.50000000` for the correct one, so MetricFlow reproduces the trap and the
repair exactly.

## What that supports, and what it does not

It supports two cells, and they point in opposite directions. The decomposition has a
**native** representation — a `ratio` metric is a documented first-class type, and the number
it returns is correct without any project-authored SQL. The failure has **no** representation
within this feature set that prevents it: the wrong model is not merely accepted, it passes
MetricFlow's own validator with nothing to say.

It does **not** support any statement about MetricFlow beyond this configuration and this
version. In particular it says nothing about whether a reviewer, a dbt test, or a
`saved_query` could catch the naive metric — only that the semantic layer itself does not.
