# dbt Core × 005-semi-additive-balance

- **System:** dbt Core `1.12.3`, with the `dbt-duckdb` `1.11.0` adapter against DuckDB `1.5.5`.
- **Checked:** 2026-09-18.
- **Feature set:** a dbt project — `sources:`, models, and the `semantic_models:` and
  `metrics:` blocks dbt parses into its manifest (`dbt/contracts/graph/unparsed.py`), here two
  measures over one column, one of them carrying a `non_additive_dimension` block, and a
  `simple` metric on each. Commands run: `dbt build`, `dbt list`, `dbt compile`.
- **Hosted features:** none, and none reachable. `dbt-metricflow` is not installed and no dbt
  Cloud or dbt Semantic Layer service is involved, so nothing here queries a metric. What dbt
  Core alone does with the definitions is the whole measurement.
- **Case:** [`tests/fixtures/semantic_corpus/005-semi-additive-balance`](../../../tests/fixtures/semantic_corpus/005-semi-additive-balance) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

`corpus__balances` is a daily snapshot: one row per account per day, carrying the state of
the account on that day. Summing it across days adds Monday's money to Tuesday's copy of the
same money. **Using dbt Core's documented feature set, is the summing model prevented before
it returns a number — and what does dbt Core itself produce for either metric?**

| Metric | How it is modelled | The corpus's number |
|---|---|---|
| `total_balance_naive` | `agg: sum` over `balance` | the wrong answer, `320.0000` |
| `total_balance_semi_additive` | the same `agg: sum`, plus `non_additive_dimension: {name: as_of_day, window_choice: max}` | the right one, `170.0000` |

## What was observed

`dbt build` finds **2 metrics and 1 semantic model** and completes with `PASS=4 WARN=0
ERROR=0`. The two measures sit in one semantic model, over one column, and differ by a single
block; dbt's parse-time semantic validation
(`dbt/contracts/graph/semantic_manifest.py`) has nothing to say about either.

`dbt compile --select metric:total_balance_naive` and the same for the semi-additive metric
render **no SQL** — `Nothing to do.` dbt Core parses metrics, lists them and writes them to
the manifest; the engine that turns one into a query ships separately.

The two numbers in `observed.txt` therefore come from **models this project's author wrote**:
`320.0000` for the summing reading and `170.0000` for the one that selects the last snapshot
day before summing. Both are the corpus's own.

## What that supports, and what it does not

It supports two cells, and the asymmetry between them is the point. The semi-additive fact
**is** in this vocabulary — `non_additive_dimension` is a documented measure key and dbt
accepts it — but stating it is optional, so the naive measure is not a claim dbt's validator
declines to check: it is not a claim at all. Nothing in the feature set distinguishes the two
measures as right and wrong, which is what `NOT-REPRESENTED` names for the naive row.

And the correct number was reached here **only through project-authored SQL**, because in
this configuration no dbt Core command renders a metric — so the declared row is `CUSTOM`
rather than `NATIVE-PLAN`, as a fact about this configuration and not about the declaration.

It does **not** support any statement about dbt beyond this configuration and this version.
It says nothing about dbt Core with `dbt-metricflow` installed, or about the dbt Semantic
Layer service: neither was run here. The engine those paths use is MetricFlow, measured in
its own column at `0.212.0`, where this case's declared row is `NATIVE-PLAN`.
