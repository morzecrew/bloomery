# MetricFlow × 005-semi-additive-balance

- **System:** MetricFlow `0.212.0`, driven from Python against DuckDB `1.5.5`.
- **Checked:** 2026-09-15.
- **Feature set:** semantic models with `measures`, and `non_additive_dimension` with
  `window_choice: max` (`metricflow_semantic_interfaces/parsing/schemas.py`,
  `metricflow_semantic_interfaces/protocols/measure.py`). No project-authored SQL.
- **Hosted features:** none. Everything here runs from the installed package against a local
  DuckDB; no dbt Cloud or dbt Semantic Layer service is involved.
- **Case:** [`tests/fixtures/semantic_corpus/005-semi-additive-balance`](../../../tests/fixtures/semantic_corpus/005-semi-additive-balance) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

`balance` is a daily snapshot: additive across accounts, not additive across time. **Using
MetricFlow's documented feature set, is a metric that sums it across time prevented before
it returns a number?**

| Metric | How it is modelled | What it should return |
|---|---|---|
| `total_balance_naive` | `agg: sum` over `balance` | the wrong answer, `320.0000` |
| `total_balance_semi_additive` | the same `agg: sum`, plus `non_additive_dimension: {name: as_of_day, window_choice: max}` | the right one, `170.0000` |

The two measures sit in the **same semantic model** over the same column and differ only by
that block, which is what makes the comparison about the feature rather than about the SQL.

## What was observed

MetricFlow's own `SemanticManifestValidator` reports **0 errors, 0 warnings**.
`total_balance_naive` returns
`Decimal('320.0000')`; `total_balance_semi_additive` returns `Decimal('170.0000')`. Full
transcript in `observed.txt`. Both match the corpus's `expected/result.json`.

## What that supports, and what it does not

Semi-additivity is **represented natively and correctly**: one declarative block over an
otherwise identical measure produces the last-value-per-day reduction, and the number is
right. This is the strongest native result in the three bundles — the semantics are not
approximated, they are declared.

What is not represented is the *obligation*. Nothing requires a snapshot measure to carry
the block, and a measure over the same column without it validates clean and answers
`320.0000`. The two measures are indistinguishable to the validator; only the author knows
which one is a lie.

Neither half is a statement about MetricFlow beyond `0.212.0` and this configuration. In
particular it says nothing about whether a dbt test, a review convention or a
`saved_query` would catch the measure without the block — only that the semantic layer
itself does not.
