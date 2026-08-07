# Spec schemas

Field-by-field reference for the five spec kinds. Parsing is strict: unknown keys,
duplicate YAML keys, and grammar violations are hard `SpecParseError`s, batched per
document with a source path per failure. Parse validates shape and grammar only —
whether references exist is checked at resolution.

Each project document self-identifies by its version key: `spec_version` (EntityModel),
`mapping_version` (Mapping), `metrics_version` (MetricSet), `marts_version` (MartSet).
A project holds exactly one EntityModel, any number of Mappings, and at most one
MetricSet and one MartSet. The Catalog (`catalog_version`) is not part of a project —
load it with `load_catalog` and pass it separately.

## Shared grammars

| Grammar | Rule | Examples |
|---|---|---|
| Type string | `string`, `int`, `bool`, `date`, `timestamp`, `variant`, or `decimal(p, s)` | `decimal(12,4)` |
| Partition spec | A bare column, or `fn(column)` with `fn` ∈ `days`/`months`/`years`/`hours` | `days(order_date)` |
| Source path | JSONPath-lite: `$` followed by dotted identifiers only | `$.customer.id` |
| Currency code | Three uppercase letters (ISO 4217) | `EUR` |
| Member name | Any identifier except the reserved names | — |

**Reserved:** `metric_time` may not be used as a field, dimension, or role name — the
planner owns it as the canonical query-time dimension.

## Catalog (`catalog_version`)

One per vertical, loaded via `load_catalog(text)`.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `catalog_version` | int ≥ 1 | yes | Document version key |
| `vertical` | string | yes | The vertical this catalog describes |
| `canonical_fields` | map name → CanonicalField | no (`{}`) | The domain's named quantities |
| `canonical_relationships` | list of CanonicalRelationship | no (`[]`) | The canonical entity graph |
| `metric_templates` | map name → MetricTemplate | no (`{}`) | Reusable metric definitions |
| `date_dimension` | DateDimension | no | The vertical-owned calendar |

### CanonicalField

| Field | Type | Required | Meaning |
|---|---|---|---|
| `entity` | string | yes | Home entity of the field |
| `type` | type string | yes | Logical type |
| `description` | string | no | Carried into semantic-layer emissions |
| `unit` | `currency` \| `count` | no | Drives the unit guardrail; absent = unknown |
| `tax_basis` | `net` \| `gross` \| `unknown` | no | Drives the tax-basis guardrail |
| `currency` | ISO 4217 code | no | Drives the currency guardrail |
| `recipes` | list of Recipe | no (`[]`) | Alternative derivation paths, ordered by reliability |

### Recipe

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | string | yes | The id a mapping records with `recipe:` |
| `requires` | list of strings | yes | Names the recipe consumes |
| `expr` | string | no | Derivation expression over the required names |

### CanonicalRelationship

| Field | Type | Required | Meaning |
|---|---|---|---|
| `from` | string | yes | From-entity |
| `to` | string | yes | To-entity |
| `via` | string | yes | Join column |
| `cardinality` | `many_to_one` \| `one_to_one` \| `one_to_many` | yes | Relationship cardinality |

### MetricTemplate

Same shape as a [Metric](#metric) minus `template`/`cumulative`, with `additivity`
required. A project metric that names it via `template:` merges values with the
metric's own winning.

### DateDimension

| Field | Type | Required | Meaning |
|---|---|---|---|
| `name` | string | no (`dim_date`) | Emitted gold relation name |
| `grain` | `day` | no (`day`) | Calendar grain (only `day` today) |
| `start_year` | int 1–9999 | yes | First calendar year, inclusive |
| `end_year` | int 1–9999, ≥ `start_year` | yes | Last calendar year, inclusive |

One definition emits both the `gold.dim_date` model and the MetricFlow time-spine
declaration — bounds are calendar years, never a clock.

## EntityModel (`spec_version`)

Exactly one per project.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `spec_version` | int ≥ 1 | yes | Document version key |
| `entities` | map name → Entity | yes | The project's entities |
| `relationships` | list of Relationship | no (`[]`) | Declared relationships |

### Entity

| Field | Type | Required | Meaning |
|---|---|---|---|
| `grain` | string | yes | Prose grain — appears in error messages and explanations |
| `key` | list of field names, ≥ 1 | yes | Entity key, authored order kept |
| `scd` | `type1` \| `type2` | no (`type1`) | Slowly-changing-dimension kind |
| `partition_by` | list of partition specs | no (`[]`) | Physical partitioning |
| `materialization` | `full` \| `incremental_by_key` \| `incremental_by_partition` | no | Explicit wins; default is `incremental_by_partition` when `partition_by` is set, else `full` |
| `fields` | map name → Field | yes | Typed fields (`metric_time` reserved) |

### Field

| Field | Type | Required | Meaning |
|---|---|---|---|
| `type` | type string | yes | Logical type |
| `required` | bool | no (`false`) | Whether the mapping must supply it |
| `canonical` | string | no | Link to a catalog canonical field |
| `renamed_from` | string | no | One-shot rename annotation for `plan()` |
| `assert` | AssertClause | no | Range-sanity assertions, lowered to audits |

### AssertClause

All members optional; at least one should be present for the clause to do anything.

| Field | Type | Meaning |
|---|---|---|
| `min` / `max` | int, decimal, or string | Inclusive bounds; well-typedness against the field's type is checked at the guardrail stage |
| `not_null` | bool | Column must not be null |
| `enum` | list of strings/ints | Closed value set |
| `regex` | string | Value pattern |

`not_null` and `enum` lower to builtin audits/tests; `min`, `max`, and `regex` lower to
custom audit artifacts.

### Relationship

| Field | Type | Required | Meaning |
|---|---|---|---|
| `name` | string | yes | Referenced by mart `via:` flatten steps |
| `from` / `to` | string | yes | The two entities |
| `via` | map from-column → to-column | yes | Join columns |
| `cardinality` | `many_to_one` \| `one_to_one` \| `one_to_many` | yes | Checked by the fan-out guardrail |

## Mapping (`mapping_version`)

One document per (source, target entity) pair.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `mapping_version` | int ≥ 1 | yes | Document version key |
| `source` | string | yes | Bronze relation name |
| `target` | string | yes | Target entity |
| `key` | map key-column → KeyField | yes | Key lowering |
| `fields` | map field → FieldMapping | no (`{}`) | Field lowering |
| `unmapped` | list of source paths | no (`[]`) | The explicitly unmapped tail |
| `on_unmapped_enum` | `quarantine` | no (`quarantine`) | Policy for unmapped enum values (closed vocabulary, one value today) |

### KeyField

| Field | Type | Required | Meaning |
|---|---|---|---|
| `from` | source path | yes | Where the key column comes from |
| `transform` | transform chain | no (`[]`) | Steps applied in order |

### FieldMapping — two forms

A field mapping is **simple** or **recipe**, discriminated on the presence of `recipe`:

```yaml
# simple: one source path plus a transform chain
quantity: {from: "$.qty", transform: [to_int]}

# recipe: a recorded catalog recipe id plus alias → path bindings
unit_price:
  recipe: from_total
  from: {line_total: "$.total", quantity: "$.qty"}
```

| Form | Field | Type | Required | Meaning |
|---|---|---|---|---|
| simple | `from` | source path | yes | Source column path |
| simple | `transform` | transform chain | no (`[]`) | Steps applied in order |
| recipe | `recipe` | string | yes | Catalog recipe id, chosen upstream and recorded here |
| recipe | `from` | map alias → source path | yes | Bindings for every name in the recipe's `requires` — exactly, no more, no fewer |
| recipe | `direct` | source path | no | The source *also* carries the field directly — emits a `<name>__direct` shadow column and a reconciliation audit |

### Transform steps

A step is a bare name or a single-key mapping; args normalize to a tuple:

```yaml
transform: [trim, to_string]              # zero-arg steps
transform: [{parse_ts: ISO8601}]          # one arg
transform: [{to_decimal: [12, 4]}]        # multiple args
```

The available names are the closed whitelist in the
[transforms reference](transforms.md); existence is checked at typecheck, not parse.

## MetricSet (`metrics_version`)

At most one per project.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `metrics_version` | int ≥ 1 | yes | Document version key |
| `metrics` | map name → Metric | yes | The project's metrics |

### Metric

A metric is a template instantiation (`template:` plus overrides) or fully inline.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `template` | string | no | Catalog template to instantiate; own values win over the template's |
| `description` | string | no | Carried into semantic-layer emissions |
| `requires` | list of canonical field names | no (`[]`) | Leaves the metric reads |
| `requires_metrics` | list of metric names | no (`[]`) | Metrics a derived metric reads |
| `grain` | string | no | Entity grain the metric aggregates from |
| `additivity` | `additive` \| `semi_additive` \| `non_additive` | effectively yes (inline or via template) | Aggregation class, enforced by guardrails |
| `agg` | string | no | Aggregation function (`sum`, `count`, …) |
| `expr` | string | no | Expression over the required names |
| `ratio` | RatioSpec | with `non_additive` | Additive decomposition to recompute from |
| `semi_additive` | SemiAdditivePolicy | with `semi_additive` | The dimension and rule |
| `cumulative` | CumulativeSpec | no | Reserved surface: exactly one of `window` / `grain_to_date`; parse-validated only |

### RatioSpec

| Field | Type | Required | Meaning |
|---|---|---|---|
| `numerator` / `denominator` | metric name | yes | The additive components |

### SemiAdditivePolicy

| Field | Type | Required | Meaning |
|---|---|---|---|
| `over` | dimension name | yes | The dimension the metric is not additive over |
| `rule` | `last` \| `first` \| `avg` \| `min` \| `max` | yes | Rule applied along `over` |

## MartSet (`marts_version`)

At most one per project; a project without marts compiles silver only.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `marts_version` | int ≥ 1 | yes | Document version key |
| `marts` | map name → Mart | yes | The gold layer |

### Mart

| Field | Type | Required | Meaning |
|---|---|---|---|
| `grain` | string | yes | Must equal the base entity's grain; every measure's grain must match it strictly |
| `base` | entity name | yes | The fact the mart is built from |
| `flatten` | list of flatten steps | no (`[]`) | Applied in authored order; chains flatten transitively |
| `measures` | list of metric names | no (`[]`) | Metrics this mart serves; a mart with measures must declare a date role |
| `partition_by` | list of partition specs | no (`[]`) | Physical partitioning |
| `materialization` | as Entity | no | Materialization override |
| `cost_hint` | int ≥ 1 | no (`1`) | Tie-breaker when several marts can serve a metric — cheapest wins |

### Flatten steps — two forms

Discriminated on `via` vs `date`:

```yaml
flatten:
  - {via: item_of_order, prefix: order_}    # flatten a relationship
  - {date: order_date, role: ordered}       # declare a date role
```

| Form | Field | Type | Required | Meaning |
|---|---|---|---|---|
| via | `via` | relationship name | yes | Relationship to flatten; `one_to_many` is refused (fan-out) |
| via | `prefix` | string, non-empty | yes | Prefix on every flattened column — mandatory, collisions are errors |
| date | `date` | field name | yes | A date/timestamp column of the base entity |
| date | `role` | member name | yes | Expands to `<role>_day` … `<role>_year` bucket columns (`metric_time` reserved) |
