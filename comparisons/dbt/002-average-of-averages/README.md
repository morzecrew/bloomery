# dbt Core × 002-average-of-averages

- **System:** dbt Core `1.12.3`, with the `dbt-duckdb` `1.11.0` adapter against DuckDB `1.5.5`.
- **Checked:** 2026-09-18.
- **Feature set:** a dbt project — `sources:`, models, and the `semantic_models:` and
  `metrics:` blocks dbt parses into its manifest (`dbt/contracts/graph/unparsed.py`), here
  measures, a `simple` metric and a `ratio` metric. Commands run: `dbt build`, `dbt list`,
  `dbt compile`, `dbt parse`.
- **Hosted features:** none, and none reachable. `dbt-metricflow` is not installed and no dbt
  Cloud or dbt Semantic Layer service is involved, so nothing here queries a metric. What dbt
  Core alone does with the definitions is the whole measurement, and the cells say nothing
  about any other configuration.
- **Case:** [`tests/fixtures/semantic_corpus/002-average-of-averages`](../../../tests/fixtures/semantic_corpus/002-average-of-averages) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

An upstream system publishes a per-order rollup, `average_item_price`, and it is a correct
average of each order's lines. **Using dbt Core's documented feature set, is a metric that
re-aggregates that stored average prevented before it returns a number — and what does dbt
Core itself produce for either metric?**

Both metrics are declared in one project, because the pair is what the question is about:

| Metric | How it is modelled | The corpus's number |
|---|---|---|
| `average_item_price_naive` | `agg: average` over the published `average_item_price` column | the wrong answer, `55.00` |
| `average_item_price_decomposed` | `type: ratio` of summed `unit_price` over counted lines | the right one, `32.50` |

## What was observed

`dbt build` finds **4 metrics and 2 semantic models** and completes with `PASS=5 WARN=0
ERROR=0`. dbt validates the semantic manifest while parsing
(`dbt/contracts/graph/semantic_manifest.py`) and reports nothing about either metric: the
naive definition and the decomposed one are equally acceptable to it.

`dbt compile --select metric:average_item_price_naive` and the same for the other three
metrics render **no SQL** — `Nothing to do.` dbt Core parses metrics, lists them and writes
them to the manifest; the engine that turns one into a query ships separately.

The two numbers in `observed.txt` therefore come from **models this project's author wrote**:
`average_item_price_naive` returns `55.00000000` and `average_item_price_decomposed` returns
`32.50000000`. Both are the corpus's own: `expected/result.json` pins `55.00000000` for the
naive reading and `32.50000000` for the correct one.

The probe is the last line. Adding `already_aggregated: true` to the measure — the fact that
would make the naive model refusable — is rejected by dbt's own parser:

```text
Parsing Error: at path ['measures'][0]: Additional properties are not allowed
('already_aggregated' was unexpected)
```

so the measure's key set is closed rather than a list of keys somebody happened to try.

## What that supports, and what it does not

It supports two cells. The fact that a stored column is already an aggregate has **no
representation** in this feature set: `UnparsedMeasure`'s keys are `name`, `agg`,
`description`, `label`, `expr`, `agg_params`, `non_additive_dimension`, `agg_time_dimension`,
`create_metric`, `config`, and the probe shows an eleventh is refused. And the correct answer
was reached here **only through project-authored SQL** — a model — because in this
configuration no dbt Core command renders a metric.

It does **not** support any statement about dbt beyond this configuration and this version.
In particular it says nothing about dbt Core with `dbt-metricflow` installed, or about the
dbt Semantic Layer service: neither was run here. The engine those paths use is MetricFlow,
which this matrix measures in its own column at `0.212.0`, and a reader comparing the two
columns is comparing two configurations rather than two products.
