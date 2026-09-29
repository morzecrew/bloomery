# MetricFlow × 003-scd2-unqualified-join

- **System:** MetricFlow `0.213.0`, driven from Python against DuckDB `1.5.5`.
- **Checked:** 2026-09-29.
- **Feature set:** semantic models with `primary`, `foreign` and `natural` entities,
  `primary_entity`, time dimensions with `validity_params`, and a `simple` metric requested
  with a group-by (`metricflow_semantic_interfaces/parsing/schemas.py`). No project-authored
  SQL.
- **Hosted features:** none. Everything here runs from the installed package against a local
  DuckDB; no dbt Cloud or dbt Semantic Layer service is involved.
- **Case:** [`tests/fixtures/semantic_corpus/003-scd2-unqualified-join`](../../../tests/fixtures/semantic_corpus/003-scd2-unqualified-join) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

`silver.customer_tier` is a type-2 history — one row per customer per version — and
`customer_id` is not unique in it. **Using MetricFlow's documented feature set, is revenue by
tier over a join on the business key alone prevented before it returns a number, and can the
as-of join be stated?**

The case's relation is modelled twice, over the same table:

| Model | How it is declared | Request | What it should return |
|---|---|---|---|
| `customer_tier_by_key` | entity `customer`, `type: primary` | `revenue/customer__tier` | `unanchored`: the wrong total, `600.0000` |
| `customer_tier_versions` | entity `versioned_customer`, `type: natural`, `valid_from` / `valid_to` with `validity_params` | `revenue/versioned_customer__tier` | `anchored`: `300.0000` in total |

`orders` carries both as `foreign` entities over the same `customer_id`, so the two
requests differ only in which declaration of the dimension they reach. `revenue` with no
group-by is requested too, as the baseline no join touches.

## What was observed

MetricFlow's own `SemanticManifestValidator` reports **0 errors, 0 warnings** for the
manifest containing both. Full transcript in `observed.txt`.

- `revenue` returns `Decimal('300.0000')`.
- `revenue/customer__tier` returns `bronze` `300.0000` and `gold` `300.0000`: every order
  against both versions, summing to `600.0000` — the corpus's `naive` number.
- `revenue/versioned_customer__tier` returns `bronze` `100.0000` and `gold` `200.0000`:
  each order against the version in force at its own date, summing to `300.0000` — the
  corpus's `correct` number.

Building the `natural` model needed one addition: a model whose only entity is `natural`
fails to load with *"contains dimensions, but it does not define a primary entity"*, so it
declares `primary_entity: customer_version`. That failure was seen while authoring and is
not in `observed.txt`.

## What that supports, and what it does not

**The as-of join is native.** A `natural` entity with a start and an end `validity_params`
dimension is joined to the order at the order's time, with no project-authored SQL, and the
breakdown is right. A `natural` entity on a model *without* validity dimensions is not
joinable at all (`metricflow_semantics/model/semantics/semantic_model_join_evaluator.py`).

**Nothing requires it.** The same relation declared with a `primary` entity is a claim that
`customer_id` is unique in it, and `0.213.0`'s validator does not read the data to check
that — it cannot know the relation is versioned unless the author says so. The manifest
plans a `foreign` → `primary` join, which it counts as valid, and answers every order once
per version. The fact that would make the key-only join refusable — *this relation holds
more than one row per key* — is stated only by choosing the `natural` declaration; choosing
`primary` states the opposite, and is accepted.

Neither half is a statement about MetricFlow beyond `0.213.0` and this configuration. It
says nothing about whether a dbt uniqueness test on `customer_id` would catch the `primary`
declaration — only that the semantic layer itself did not, here.
