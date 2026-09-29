# MetricFlow × 001-order-shipping-fanout

- **System:** MetricFlow `0.213.0`, driven from Python against DuckDB `1.5.5`.
- **Checked:** 2026-09-29.
- **Feature set:** semantic models with `primary` and `foreign` entities, `measures`,
  `simple` metrics and a `derived` metric, requested with and without a group-by
  (`metricflow_semantic_interfaces/parsing/schemas.py`). The line-grain relation is
  project-authored SQL in `config/setup.sql`, because the case creates only the normalized
  tables — see below.
- **Hosted features:** none. Everything here runs from the installed package against a local
  DuckDB; no dbt Cloud or dbt Semantic Layer service is involved.
- **Case:** [`tests/fixtures/semantic_corpus/001-order-shipping-fanout`](../../../tests/fixtures/semantic_corpus/001-order-shipping-fanout) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

`shipping` is a fact about an order; one order has three lines. **Using MetricFlow's
documented feature set, is shipping aggregated at a line grain — in a line-grain relation, or
pulled into a line-grain derivation — prevented before it returns a number, and does the
order-grain total plan correctly?**

| Request | How it is modelled | What it should return |
|---|---|---|
| `shipping_total` | `agg: sum` on the `orders` model, whose primary entity is `order` | `rollup`: `9.0000` |
| `shipping_total/order_line__line_no` | the same metric, grouped by a dimension of the `order_items` model | a line-grain listing of an order-grain measure |
| `shipping_total_by_line` | `agg: sum` over `shipping` on `order_items_wide`, the line-grain view in `config/setup.sql` | `representation`: the wrong answer, `27.0000` |
| `landed_total_by_line` | `agg: sum` over `unit_price + shipping` on the same view | `refinement`: the wrong answer, `57.0000` |
| `landed_total_derived` | `type: derived`, `unit_price_total + shipping_total` | the landed total, `39.0000` |
| `landed_total_derived/order_line__line_no` | the same, grouped by line | a line-grain derivation over shipping |

A measure's `expr` reads only its own semantic model's columns, so the only way to put
`shipping` on a line row is a relation that already carries it. `config/setup.sql` builds
that relation as a view over the case's two tables — the join in `naive.sql`, not a copy of
its rows.

## What was observed

MetricFlow's own `SemanticManifestValidator` reports **0 errors, 0 warnings** for the
manifest containing all three semantic models. Full transcript in `observed.txt`.

- `shipping_total` returns `Decimal('9.0000')` — the corpus's `correct` number.
- Grouped by `order_line__line_no`, both `shipping_total` and `landed_total_derived` are
  **refused when planning** with `InvalidQueryException`: *"No valid join paths exist from
  the measure to the group-by-item. (fan-out join support is pending)"*, suggesting only
  `order`-reachable items.
- `shipping_total_by_line` returns `Decimal('27.0000')` and `landed_total_by_line` returns
  `Decimal('57.0000')`, validator clean.
- `landed_total_derived` returns `Decimal('39.0000')`: each operand aggregated in its own
  model, then added.

## What that supports, and what it does not

**The rollup is native and right.** A measure is aggregated in the semantic model it is
declared on, so `shipping_total` is summed over orders whatever else is in the manifest.

**Through the normalized models, the fan-out is refused.** Reaching a line dimension from an
order measure means joining `order` onto `order_items` along a `primary` → `foreign`
edge, which `0.213.0` lists among its invalid entity joins
(`metricflow_semantics/model/semantics/semantic_model_join_evaluator.py`,
`_INVALID_ENTITY_JOINS`). The refusal is structural — it reads the entity types, not the
measure — and it happens before any SQL is rendered.

**Over a relation that already carries the copy, nothing is refused.** The line-grain view is
one `CREATE VIEW` of project SQL, and a semantic model over it with a `primary` line entity
is exactly as valid as the normalized pair. No key on a measure states the grain a value
originates at (`sources.md`), so a `sum` over a copied order value is indistinguishable
from a `sum` over a line value, and the manifest answers `27.0000` and `57.0000`.

Neither half is a statement about MetricFlow beyond `0.213.0` and this configuration. It
says nothing about whether a dbt test or a review convention would catch the wide
relation — only that the semantic layer itself did not, here.
