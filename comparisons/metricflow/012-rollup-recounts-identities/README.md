# MetricFlow × 012-rollup-recounts-identities

- **System:** MetricFlow `0.213.0`, driven from Python against DuckDB `1.5.5`.
- **Checked:** 2026-09-29.
- **Feature set:** semantic models with `measures` including `agg: count_distinct`, a
  month-grain time dimension, and `simple` metrics asked for two at a time, with and without
  a `metric_time` group-by (`metricflow_semantic_interfaces/parsing/schemas.py`). The
  monthly pre-aggregate is project-authored SQL in `config/setup.sql` — see below.
- **Hosted features:** none. Everything here runs from the installed package against a local
  DuckDB; no dbt Cloud or dbt Semantic Layer service is involved.
- **Case:** [`tests/fixtures/semantic_corpus/012-rollup-recounts-identities`](../../../tests/fixtures/semantic_corpus/012-rollup-recounts-identities) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

A monthly table is built from daily counts, and `revenue` survives that while `buyers` does
not. **Using MetricFlow's documented feature set, is reading `buyers` from the monthly
rollup prevented before it returns a number, and does the detail answer plan correctly?**

| Request | How it is modelled | What it should return |
|---|---|---|
| `buyers,revenue` | `count_distinct` over `customer_id` and `sum` over `amount`, on `orders` | `detail`: `3` and `110.00` |
| `buyers,revenue/metric_time__month` | the same, by month | January, `3` and `110.00` |
| `buyers_rolled,revenue_rolled` | `agg: sum` over both columns of `orders_monthly`, the rollup in `config/setup.sql` | `rolled`: `4`, wrong, and `110.00`, right |
| `buyers_rolled,revenue_rolled/metric_time__month` | the same, by month | the rollup's one row |

The case's rollup is a table that "does not exist yet": the one somebody builds when the
dashboard gets slow. `config/setup.sql` builds it from the case's orders exactly as
`naive.sql` does — daily counts, then the month adds them up — and the bundle declares a
semantic model over it the way any materialized table is declared.

## What was observed

MetricFlow's own `SemanticManifestValidator` reports **0 errors, 0 warnings** for the
manifest containing both models. Full transcript in `observed.txt`.

- From the detail model: `3` and `Decimal('110.00')`, ungrouped and by month — `3` is the
  corpus's `correct` number.
- From the rollup model: `4` and `Decimal('110.00')`, ungrouped and by month — `4` is the
  corpus's `naive` number.

## What that supports, and what it does not

**The detail answer is native and right.** A `count_distinct` measure is computed from the
orders at the requested grain; the manifest does not route it through the rollup, because
nothing in the manifest relates the two models.

**The rollup is accepted, with both columns treated alike.** To `0.213.0`'s validator the
monthly table is a semantic model at month grain with two summable columns, which it is.
Nothing states that the table was built by aggregating `orders`, or that `buyers` in it is a
distinct count over an identity the rollup no longer holds (`sources.md`), so the column
that survived the rollup and the column that did not are indistinguishable, and a request for
`buyers_rolled` answers `4`.

Neither half is a statement about MetricFlow beyond `0.213.0` and this configuration. It
says nothing about whether a dbt test, a review convention or a caching layer outside the
semantic manifest would treat the rollup differently — only that the semantic layer itself
did not, here.
