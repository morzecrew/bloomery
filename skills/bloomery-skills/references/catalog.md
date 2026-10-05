# Catalog

Declare a vertical's domain graph: canonical fields with units and tax bases, recipes,
canonical relationships, metric templates, the date dimension and exchange rates.

## What the catalog is for

One catalog exists per vertical (e-commerce retail, logistics, …). It is written by the
platform operator, never by a tenant, and it is **not part of a project**: it is loaded on
its own (`load_catalog`, or `catalog.yaml` / `--catalog` on the CLI) and passed beside the
project, because many tenant projects share it and it is versioned on its own cadence.

It holds what is true of the domain regardless of any tenant's data. A tenant's entity
model links its fields to the catalog with `canonical:`, and that link is what gives a
field its unit, tax basis and currency, and what makes catalog metric templates reachable.

## A complete catalog

```yaml spec=catalog
catalog_version: 1
vertical: ecom_retail

canonical_fields:
  unit_price:
    entity: order_item
    type: decimal(12,4)
    unit: currency
    tax_basis: net
    description: Price of one unit, before tax
    recipes:
      - {id: direct, requires: [unit_price]}
      - {id: from_total, requires: [line_total, quantity], expr: "line_total / quantity"}
  quantity:
    entity: order_item
    type: int
    unit: count
    recipes:
      - {id: direct, requires: [quantity]}
  amount_usd:
    entity: payment
    type: decimal(12,4)
    unit: currency
    currency: USD

canonical_relationships:
  - {from: order_item, to: order, via: order_id, cardinality: many_to_one}
  - {from: order, to: customer, via: customer_id, cardinality: many_to_one}

metric_templates:
  gross_revenue:
    requires: [unit_price, quantity]
    grain: order_item
    additivity: additive
    agg: sum
    expr: "unit_price * quantity"

date_dimension:
  name: dim_date
  grain: day
  start_year: 2020
  end_year: 2030

fx_rates:
  relation: fx_rate
  from: from_ccy
  to: to_ccy
  rate: rate
  valid_from: valid_from
  valid_to: valid_to
```

## Top-level keys

| Key | Required | Holds |
|---|---|---|
| `catalog_version` | yes | `1` |
| `vertical` | yes | the vertical's name |
| `canonical_fields` | no | map name → canonical field |
| `canonical_relationships` | no | the canonical entity graph |
| `metric_templates` | no | reusable metric definitions |
| `date_dimension` | no | the calendar bloomery emits |
| `fx_rates` | no | the shape of the operator's exchange-rate table |

## Canonical fields

| Key | Required | Meaning |
|---|---|---|
| `entity` | yes | the field's home entity |
| `type` | yes | `string`, `int`, `bool`, `date`, `timestamp`, `variant`, `decimal(p,s)` |
| `unit` | no | `currency` or `count`; drives the unit guardrail |
| `tax_basis` | no | `net`, `gross` or `unknown`; drives the tax-basis guardrail |
| `currency` | no | an ISO 4217 code; drives the currency guardrail |
| `description` | no | carried into semantic-layer emissions |
| `recipes` | no | alternative derivation paths, ordered by reliability |

**Annotate every monetary field.** A field without `unit` is `unknown`, and `unknown` in
additive arithmetic is a compile error. Net and gross may not meet in one expression, and
two different currencies may not either (`CurrencyMismatch`): declare a converted field in
the target currency instead and convert in the mapping.

## Recipes

A recipe is an alternative path to a canonical field: if `unit_price` is not present
directly, it can come from `line_total / quantity`. Each recipe has an `id`, the names it
`requires`, and an optional `expr` over those names.

Recipes are ordered by reliability, but **the compiler never picks one**. Which recipe a
tenant's data satisfies is decided upstream and recorded in the mapping as
`recipe: from_total`; the compiler checks that the id exists and that the mapping binds
every required name exactly. When a catalog change removes a recipe a mapping recorded,
that mapping is refused with a `ResolutionError` until someone re-decides it.

```yaml fragment
fields:
  unit_price:
    recipe: from_total
    from: {line_total: "$.total", quantity: "$.qty"}
```

## Canonical relationships

The canonical graph, with cardinalities `many_to_one`, `one_to_one` or `one_to_many`.
`via` is a single join column. Projects declare their own join relationships in the entity
model; the catalog's graph is the domain's.

## Metric templates

A template has a metric's shape, with `additivity` required and no `owner`. A project
instantiates it by name, and the project metric's own keys win:

```yaml spec=metrics
metrics_version: 1
metrics:
  gross_revenue:
    template: gross_revenue
    description: Revenue before discounts
```

A template is reachable for a project only when every name in its `requires` is linked by
some entity field's `canonical:`.

## The date dimension

bloomery owns the calendar, and defines it here once. `start_year` and `end_year` are
required and inclusive; `name` defaults to `dim_date` and `grain` to `day` (the only grain).
One definition emits both the `gold.dim_date` model and the MetricFlow time spine pointing
at it. Any project with marts needs one: marts declare date roles, and metrics over time
(`offset:`, `cumulative:`) resolve against it. A SQLMesh compile also takes its
`model_defaults.start` from `start_year`.

## Exchange rates

`fx_rates` describes a table the operator supplies and bloomery never builds: the relation
name and the columns for `from`, `to`, `rate`, `valid_from` and `valid_to`. Both interval
ends are required, and no two roles may name the same column. Without `fx_rates`, a
`convert` transform in a mapping is refused at emit with `UnsupportedByTarget`. The
operator guarantees that intervals for one currency pair do not overlap and that a rate
exists for every pair and date converted; a miss converts to `NULL`.

## Loading it from Python

```python
from pathlib import Path

from bloomery import compile_project, load_catalog, load_project, Target

catalog = load_catalog(Path("specs/catalog.yaml").read_text())
project = load_project({p.name: p.read_text() for p in Path("specs").glob("*.yaml") if p.name != "catalog.yaml"})
artifacts = compile_project(project, target=Target.SQLMESH, dialect="duckdb", catalog=catalog)
```

## Published pages

- [Specs and the catalog](https://morzecrew.github.io/bloomery/latest/concepts/specs-and-catalog/)
- [Spec schemas](https://morzecrew.github.io/bloomery/latest/reference/spec-schemas/)
