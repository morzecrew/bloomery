# MetricFlow × 006-two-grains-one-request

- **System:** MetricFlow `0.213.0`, driven from Python against DuckDB `1.5.5`.
- **Checked:** 2026-09-29.
- **Feature set:** semantic models with `primary` and `foreign` entities, `measures`, and
  two `simple` metrics asked for in one request, with and without a group-by
  (`metricflow_semantic_interfaces/parsing/schemas.py`). No project-authored SQL.
- **Hosted features:** none. Everything here runs from the installed package against a local
  DuckDB; no dbt Cloud or dbt Semantic Layer service is involved.
- **Case:** [`tests/fixtures/semantic_corpus/006-two-grains-one-request`](../../../tests/fixtures/semantic_corpus/006-two-grains-one-request) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

`shipping` is a fact about an order and `discount` a fact about a line. **Using
MetricFlow's documented feature set, does one request for both return each at its own grain?**

| Request | What it should return |
|---|---|
| `shipping_total,discount_total` | `branches`: `16.0000` and `6.0000` |
| `shipping_total,discount_total/sales_order` | per order, shipping once and the order's discounts summed |
| `shipping_total,discount_total/metric_time__day` | the same totals, grouped by the one day the rows share |

`shipping` is on the `orders` model and `discount` on `order_items`; the two share the
`sales_order` entity. It is `sales_order` rather than `order` for a rendering reason, not a
semantic one: grouping by an entity named `order` rendered `ORDER BY order`, which DuckDB
refused to parse. That was seen while authoring and is not in `observed.txt`.

## What was observed

MetricFlow's own `SemanticManifestValidator` reports **0 errors, 0 warnings**. Full
transcript in `observed.txt`.

- Ungrouped, the request returns `Decimal('16.0000')` and `Decimal('6.0000')` — the
  corpus's `correct` pair.
- By `sales_order`: `o1` `9.0000` / `3.0000`, `o2` `5.0000` / `2.0000`, `o3`
  `2.0000` / `1.0000`.
- By `metric_time__day`: `2025-03-01`, `16.0000` / `6.0000`.

## What that supports, and what it does not

**The two-grain request is planned natively and correctly.** Each metric's measure is
aggregated in the semantic model it is declared on and the results are joined afterwards,
so asking for both does not put `shipping` on a line row. No author-written SQL is involved,
and the multi-metric request needed nothing but the two metric names.

It does **not** support any statement about MetricFlow beyond `0.213.0` and this
configuration, and nothing about a request over a relation that already carries both
columns — which is `001`'s `representation` question, measured in that bundle.
