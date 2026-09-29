# MetricFlow × 010-many-to-many-bridge

- **System:** MetricFlow `0.213.0`, driven from Python against DuckDB `1.5.5`.
- **Checked:** 2026-09-29.
- **Feature set:** semantic models with `primary` and `foreign` entities, a bridge model
  with two `foreign` entities, `measures`, and `simple` metrics requested with and without
  a group-by (`metricflow_semantic_interfaces/parsing/schemas.py`). The bridge-grain relation
  is project-authored SQL in `config/setup.sql` — see below.
- **Hosted features:** none. Everything here runs from the installed package against a local
  DuckDB; no dbt Cloud or dbt Semantic Layer service is involved.
- **Case:** [`tests/fixtures/semantic_corpus/010-many-to-many-bridge`](../../../tests/fixtures/semantic_corpus/010-many-to-many-bridge) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

`revenue` is a fact about an order; `order_promos` is a bridge whose two edges each point
at one row. **Using MetricFlow's documented feature set, is revenue aggregated across the
bridge prevented before it returns a number, and does revenue at its own grain plan
correctly?**

| Request | How it is modelled | What it should return |
|---|---|---|
| `revenue` | `agg: sum` on `orders` | `per_order`: `150.00` |
| `revenue/promo__label` | the same metric, grouped by a dimension reached through the bridge | revenue across the bridge |
| `revenue_bridged` | `agg: sum` over `revenue` on `order_promos_wide`, a view of the bridge joined to its orders | `bridged`: the wrong answer, `250.00` |
| `revenue_bridged/promo__label` | the same, grouped by promotion label | the bridge-grain breakdown |

`bridged` in the corpus is a relation at bridge grain carrying `revenue`. A measure's
`expr` reads only its own model's columns, so that relation has to exist as a table first;
`config/setup.sql` builds it from the case's tables as the join in `naive.sql`.

## What was observed

MetricFlow's own `SemanticManifestValidator` reports **0 errors, 0 warnings** for the
manifest containing all four semantic models. Full transcript in `observed.txt`.

- `revenue` returns `Decimal('150.00')` — the corpus's `correct` number.
- `revenue/promo__label` is **refused when planning** with `InvalidQueryException`: *"No
  valid join paths exist from the measure to the group-by-item. (fan-out join support is
  pending)"*.
- `revenue_bridged` returns `Decimal('250.00')` — the corpus's `naive` number — and by
  label `loyalty` `100.00`, `spring` `150.00`.

## What that supports, and what it does not

**Revenue at its own grain is native and right**, and **the path through the bridge is
refused**: from `orders`, reaching `promo` starts with `order` `primary` → `foreign` on
the bridge, which `0.213.0` lists among its invalid entity joins
(`metricflow_semantics/model/semantics/semantic_model_join_evaluator.py`,
`_INVALID_ENTITY_JOINS`). That the case's edges are each many-to-one does not help the
path past that check, because the check reads the direction of the first hop.

**Over a relation that already carries the copies, nothing is refused.** The bridge-grain view
is one `CREATE VIEW` of project SQL; a semantic model over it declares its own grain
truthfully, and a `sum` over `revenue` there validates clean and answers `250.00`. No key on
a measure states the grain a value originates at (`sources.md`).

Neither half is a statement about MetricFlow beyond `0.213.0` and this configuration. It
says nothing about whether a dbt test or a review convention would catch the bridge-grain
relation — only that the semantic layer itself did not, here.
