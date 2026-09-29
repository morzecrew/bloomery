# MetricFlow × 004-currency-mix

- **System:** MetricFlow `0.213.0`, driven from Python against DuckDB `1.5.5`.
- **Checked:** 2026-09-29.
- **Feature set:** semantic models with `measures` whose `expr` is SQL over the model's
  own columns, and `simple` metrics (`metricflow_semantic_interfaces/parsing/schemas.py`).
  The conversion is project-authored SQL in `config/setup.sql`, because nothing else was
  found to carry it — see `sources.md`.
- **Hosted features:** none. Everything here runs from the installed package against a local
  DuckDB; no dbt Cloud or dbt Semantic Layer service is involved.
- **Case:** [`tests/fixtures/semantic_corpus/004-currency-mix`](../../../tests/fixtures/semantic_corpus/004-currency-mix) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

`amount_eur` is euros and `fee_usd` is dollars, in the same table and the same decimal
type. **Using MetricFlow's documented feature set, is a total that adds them unconverted
prevented before it returns a number, and what does reaching the converted total cost?**

| Metric | How it is modelled | What it should return |
|---|---|---|
| `total_usd_mixed` | `agg: sum` over `amount_eur + fee_usd` | `mixed`: the wrong answer, `157.5000` |
| `total_usd_converted` | `agg: sum` over `amount_usd + fee_usd` on `payments_converted`, a view joining the case's EUR→USD rate at the payment date | `converted`: `172.5000` |
| `total_usd_mislabelled` | the same, on `payments_converted_as_jpy`, a view identical but for asking the rate relation for `JPY` | `mislabelled`: anything but a refusal is unguarded |

A measure's `expr` reads only its own model's columns and a rate is a row of another
relation, so a conversion has to happen before MetricFlow sees the rows: both views are the
case's `correct.sql` join, in `config/setup.sql`.

## What was observed

MetricFlow's own `SemanticManifestValidator` reports **0 errors, 0 warnings** for the
manifest containing all three. Full transcript in `observed.txt`.

- `total_usd_mixed` returns `Decimal('157.5000')` — the corpus's `naive` number.
- `total_usd_converted` returns `Decimal('172.5000')` — the corpus's `correct` number.
- `total_usd_mislabelled` returns `None`. The case's rate relation has no `JPY` row, so
  the view's inner join keeps no payment and the sum is SQL `NULL`. That is the data's
  doing, not a check: with a `JPY` row present the same view would return a number.

## What that supports, and what it does not

**The unconverted sum is accepted.** No key in the manifest vocabulary names a currency or a
unit — `currency` does not appear anywhere in `metricflow_semantic_interfaces` at
`0.213.0` (`sources.md`) — so two money columns are two numbers, and adding them is as
valid as adding any two numbers. The manifest answers `157.5000`.

**The converted total is reachable, and only as SQL.** What makes `total_usd_converted`
right is a join the author wrote, outside the manifest; MetricFlow reads its output as a
table like any other. The mislabelled view is equally valid to the validator, because the
currency it converts from is a string literal inside that SQL, and the manifest has no
declaration for it to disagree with.

None of this is a statement about MetricFlow beyond `0.213.0` and this configuration. It
says nothing about whether a dbt test or a review convention would catch the mixed sum or the
wrong rate — only that the semantic layer itself did not, here.
