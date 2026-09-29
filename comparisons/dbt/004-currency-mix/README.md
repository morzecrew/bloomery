# dbt Core × 004-currency-mix

- **System:** dbt Core `1.12.3`, with the `dbt-duckdb` `1.11.0` adapter against DuckDB `1.5.5`.
- **Checked:** 2026-09-29.
- **Feature set:** a dbt project — `sources:`, models, and the `semantic_models:` and
  `metrics:` blocks dbt parses into its manifest (`dbt/contracts/graph/unparsed.py`), here one
  semantic model with three `sum` measures, two of them carrying a free-form
  `config: meta: {currency: ...}`, and a `simple` metric on the mixed sum. Commands run:
  `dbt build`, `dbt list`, `dbt compile`, `dbt parse`.
- **Hosted features:** none, and none reachable. `dbt-metricflow` is not installed and no dbt
  Cloud or dbt Semantic Layer service is involved, so nothing here queries a metric. What dbt
  Core alone does with the definitions is the whole measurement, and the cells say nothing
  about any other configuration.
- **Case:** [`tests/fixtures/semantic_corpus/004-currency-mix`](../../../tests/fixtures/semantic_corpus/004-currency-mix) —
  its schema and rows, including the operator's `silver.fx_rate`, are read directly, so the
  two cannot drift.

## The exact question

`amount_eur` is euros and `fee_usd` is dollars, both `DECIMAL(12,4)`. **Using dbt Core's
documented feature set, is a measure that adds the two prevented before it returns a
number — and what does dbt Core itself produce for the converted total?**

| Expectation | How it is modelled | The corpus's number |
|---|---|---|
| `mixed` | measure `total_mixed`, `agg: sum`, `expr: amount_eur + fee_usd`; model `total_usd_mixed` | the wrong answer, `157.5000` |
| `converted` | model `total_usd_converted`: EUR converted through `silver.fx_rate` at the payment's date, then added | the right one, `172.5000` |
| `mislabelled` | not modelled — see below | — |

## What was observed

`dbt build` finds **1 metric and 1 semantic model** and completes with `PASS=4 WARN=0
ERROR=0`. The `meta` currency labels on `amount_eur` and `fee_usd` were accepted, and nothing
in the run reported anything about `total_mixed` adding the two columns they label.

`dbt compile --select metric:total_usd_naive` renders **no SQL** — `Nothing to do.` In this
configuration dbt Core does not render a query for a metric.

The two numbers in `observed.txt` therefore come from **models this project's author wrote**:
`total_usd_mixed` returns `157.5000` and `total_usd_converted` returns `172.5000`. Both are
the corpus's own, pinned in `expected/result.json`.

The probe is the last line. Adding `currency: EUR` to the measure itself, rather than under
free-form `meta`, is rejected by dbt's own parser:

```text
Parsing Error: at path ['measures'][0]: Additional properties are not allowed
('currency' was unexpected)
```

## What that supports, and what it does not

It supports, at this version and in this configuration:

- **`mixed`:** a denomination has **no typed slot** on a measure — the probe shows the key set
  refuses one — and the only place it could be written, `meta`, was accepted and did not
  bear on the build: the measure adding EUR to USD built without comment.
- **`converted`:** the correct number was produced **only through project-authored SQL**, a
  join to the rate relation written in `config/models/total_usd_converted.sql`.
- **`mislabelled`** — a conversion declared with the wrong source currency — depends on a
  declared conversion, which this configuration has no native construct for; it was **not
  run**, and this bundle supplies no evidence for that row.

It does **not** support any statement about dbt beyond this configuration and this version:
it says nothing about dbt Core with `dbt-metricflow` installed, the dbt Semantic Layer
service, or any package from the dbt package hub, none of which was run here.
