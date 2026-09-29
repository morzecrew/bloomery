# dbt Core × 003-scd2-unqualified-join

- **System:** dbt Core `1.12.3`, with the `dbt-duckdb` `1.11.0` adapter against DuckDB `1.5.5`.
- **Checked:** 2026-09-29.
- **Feature set:** a dbt project — `sources:`, models, and the `semantic_models:` and
  `metrics:` blocks dbt parses into its manifest (`dbt/contracts/graph/unparsed.py`), here an
  orders semantic model with a `foreign` `customer` entity and a `sum` measure, and a type-2
  tier semantic model declared with a `natural` entity, a `primary_entity` key and
  `validity_params` on two time dimensions. Commands run: `dbt build`, `dbt list`,
  `dbt compile`.
- **Hosted features:** none, and none reachable. `dbt-metricflow` is not installed and no dbt
  Cloud or dbt Semantic Layer service is involved, so nothing here queries a metric. What dbt
  Core alone does with the definitions is the whole measurement, and the cells say nothing
  about any other configuration. dbt's own `snapshots` feature is not used: the case supplies
  `silver.customer_tier` already versioned, and the bundle reads it as a source.
- **Case:** [`tests/fixtures/semantic_corpus/003-scd2-unqualified-join`](../../../tests/fixtures/semantic_corpus/003-scd2-unqualified-join) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

`customer_tier` holds one row per customer per version, and joining orders to it on the
business key alone counts every order once per version. **Using dbt Core's documented feature
set, is the unanchored join prevented before it returns a number — and what does dbt Core
itself produce for the anchored one?**

| Expectation | How it is modelled | The corpus's number |
|---|---|---|
| `unanchored` | model `revenue_unanchored`: equality on `customer_id` | the wrong answer, `600.0000` |
| `anchored` | model `revenue_anchored`: the same join restricted to `valid_from <= created_at < valid_to` | the right one, `300.0000` |

The type-2 fact itself is declared to dbt on the `customer_tier` semantic model: `customer` as
a `natural` entity, `valid_from` with `validity_params: {is_start: true}` and `valid_to` with
`is_end: true`.

## What was observed

`dbt build` finds **1 metric and 2 semantic models** and completes with `PASS=5 WARN=0
ERROR=0`: the validity window is accepted as declared.

The first configuration tried had no `primary_entity` on `customer_tier`; `dbt parse`
refused it with `Semantic Manifest validation failed.`, preceded by *"The semantic model
customer_tier contains dimensions, but it does not define a primary entity."* The committed
configuration adds `primary_entity: customer_tier_version`, which is what that message asks
for, and `observed.txt` is the run of the committed configuration only.

`dbt compile --select metric:revenue` renders **no SQL** — `Nothing to do.` In this
configuration dbt Core parses metrics and writes them to the manifest; it does not render a
query for one, so no dbt-rendered join exists whose anchoring could be observed.

The two numbers in `observed.txt` therefore come from **models this project's author wrote**:
`revenue_unanchored` returns `600.0000` and `revenue_anchored` returns `300.0000`. Both are
the corpus's own, pinned in `expected/result.json`.

## What that supports, and what it does not

It supports, at this version and in this configuration:

- **The type-2 fact has a native representation.** `validity_params` and the `natural` entity
  type are part of the vocabulary dbt validates, and `dbt build` accepted them.
- **`unanchored`:** the model joining on the business key alone built and returned `600.0000`.
  The semantic declaration of the validity window did not bear on it: models are SQL, and
  nothing in the run related the model's join to the semantic model's window.
- **`anchored`:** the correct number was produced **only through project-authored SQL**,
  because no dbt Core command in this configuration renders a metric.

It does **not** support any statement about dbt beyond this configuration and this version.
In particular it says nothing about how an engine that renders metrics — `dbt-metricflow`, or
the dbt Semantic Layer service — joins against a semantic model carrying `validity_params`:
neither was run here.
