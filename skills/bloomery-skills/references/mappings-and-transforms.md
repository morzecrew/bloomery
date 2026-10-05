# Mappings and transforms

Map a bronze source onto an entity: key and field extraction, transform chains from the
closed whitelist, recorded recipes, casts and parses, time zones, currency conversion, and
custom transforms.

## The Mapping document

One per (source relation, target entity) pair, keyed by `mapping_version: 1`.

```yaml spec=mapping
mapping_version: 1
source: shopify__order_lines
target: order_item
key:
  order_id: {from: "$.order_id", transform: [to_string]}
  line_no: {from: "$.index", transform: [to_int]}
fields:
  unit_price:
    recipe: from_total
    from: {line_total: "$.total", quantity: "$.qty"}
  quantity: {from: "$.qty", transform: [to_int]}
unmapped: ["$.extensions", "$.variant", "$.created_at"]
```

| Key | Required | Meaning |
|---|---|---|
| `mapping_version` | yes | `1` |
| `source` | yes | the bronze relation name |
| `target` | yes | an entity of the EntityModel |
| `key` | yes | every key column of the entity |
| `fields` | no | field name → field mapping |
| `unmapped` | no | source paths deliberately not mapped; also how a mapping states the ingestion columns `_load_id`, `_ingested_at`, `_source_row_id` exist |
| `freshness` | no | `warn_after` / `error_after` durations for the source (dbt only emits them; the target entity must declare `quarantine:` or `dedupe:`) |

Source paths are JSONPath-lite: `$` followed by dotted identifiers (`$.customer.id`).
A mapping must supply every `required: true` field of its entity; a misspelled field name is
a compile error against the entity model.

## The three field shapes

**Simple**: one path and a transform chain.

```yaml fragment
quantity: {from: "$.qty", transform: [to_int]}
```

**Recipe**: a catalog recipe id chosen upstream and recorded here, with an alias → path
binding for every name in the recipe's `requires`, exactly: an unbound name and a surplus
alias are both errors. `direct:` records that the source also carries the field directly;
bloomery emits a `<name>__direct` shadow column and a reconciliation audit rather than
choosing.

```yaml fragment
unit_price:
  recipe: from_total
  from: {line_total: "$.total", quantity: "$.qty"}
  direct: "$.price"
```

**Macro**: a Tier 1 step called as a field (see the steps-and-macros reference).

```yaml fragment
email_domain:
  step: extract_domain@1
  from: {email: "$.email"}
```

## Transform chains

A chain starts at `string` (extraction yields text) and each step's output feeds the next.
The terminal type must be assignable to the field's declared type, or `TypeCheckError`. A
step is a bare name, a one-argument mapping, or a list of arguments:

```yaml fragment
transform: [trim, {split_part: ["-", 2]}, {to_decimal: [12, 4]}]
```

The whitelist is closed. A name outside it is `UnknownTransformError`, naming the closest
match.

| Group | Transforms |
|---|---|
| String | `trim`, `upper`, `lower`, `split_part`, `regex_extract`, `strip_prefix`, `strip_suffix`, `concat`, `enum_map` |
| Casts and parses | `to_string`, `to_int`, `to_decimal`, `to_bool`, `parse_ts`, `parse_date`, `to_utc` |
| Nulls and JSON | `coalesce`, `nullif`, `json_path` |
| Arithmetic | `multiply`, `divide`, `round`, `abs` |
| Currency | `convert` |

- `enum_map: [F, female, M, male]` maps pairs; unmapped values pass through.
- Decimal precision is tracked: `multiply` / `divide` widen; crossing 38 digits is an error
  telling you to narrow with `to_decimal`.
- `divide` is inexact on DuckDB; prefer `{multiply: "0.01"}` to `{divide: 100}`.
- `nullif: "N/A"` turns a sentinel into NULL; `coalesce: 0` does the reverse.

## Timestamps and zones

`timestamp` always means a UTC instant. `parse_ts: ISO8601` reads a **local wall clock**,
and text carrying a numeric offset becomes NULL rather than a value an hour off. There are
three correct spellings, one per kind of source:

```yaml fragment
# a feed writing local times in a known zone
placed_at:
  from: "$.placed_at"
  transform: [{parse_ts: ISO8601}, {to_utc: America/New_York}]
# a feed whose wall clocks already are UTC
shipped_at:
  from: "$.shipped_at"
  zone_in: UTC
  transform: [{parse_ts: ISO8601}]
# a feed that stamps every value with Z or an offset
event_at:
  from: "$.event_at"
  transform: [{parse_ts: ISO8601_INSTANT}]
```

A parsed wall clock whose *position* decides an answer (a mart date role, an as-of anchor,
a literal comparison) needs `to_utc` or `zone_in:`, or it is refused as `UndeclaredZone`.
`zone_in:` lives on the mapping, never the canonical field, because two feeds can run on two
clocks. `to_utc` after `ISO8601_INSTANT` is refused; `zone_in:` beside it may only be `UTC`.
A `parse_ts` format with `%z` or `%Z` is refused. `parse_date` needs no zone.

## Currency conversion

`convert: [from, to, anchor]` converts at the rate valid on the anchor's date, reading the
catalog's `fx_rates` relation. `currency_in:` states what the source holds, and the chain is
checked against it; the last conversion's output must match the canonical field's
`currency:`.

```yaml spec=mapping
mapping_version: 1
source: stripe__payments
target: payment
key:
  payment_id: {from: "$.id", transform: [to_string]}
fields:
  paid_at: {from: "$.paid_at", transform: [{parse_date: ISO8601}]}
  currency_code: {from: "$.currency"}
  amount_usd_bridged:
    currency_in: EUR
    from: "$.amount"
    transform: [{to_decimal: [12, 4]}, {convert: [EUR, CHF, paid_at]}, {convert: [CHF, USD, paid_at]}]
  amount_usd:
    currency_in: {column: currency_code}
    from: "$.amount"
    transform: [{to_decimal: [12, 4]}, {convert: [currency_code, USD, paid_at]}]
```

The anchor and a currency column are fields of the same entity mapped by a direct `from:`
path. Codes are three uppercase letters. A code or date with no rate converts to `NULL`; add
`quality: [{rule: not_null, on_fail: quarantine}]` on the field to reject instead. Without
`fx_rates` in the catalog, `convert` is refused at emit.

## Custom transforms

A deployment can add a transform at import time with `register_transform`. The
`TransformSpec` declares the name, arguments, input domain, output type and a builder that
returns a dialect-neutral SQLGlot AST, never SQL text. A name colliding with any existing
transform raises `TransformRegistrationError`: nothing shadows a vetted transform.

```python
from bloomery import TransformSpec, register_transform

register_transform(my_transform_spec)  # a TransformSpec built by your adapter package
```

## Field quality rules

A simple or recipe field mapping also carries `quality:` rules (`not_null`, `range`,
`pattern`, `in_set`, …), each with a required `on_fail`. Declaring them makes the entity a
quality-carrying entity; that system has its own reference.

## Published pages

- [Spec schemas: Mapping](https://morzecrew.github.io/bloomery/latest/reference/spec-schemas/)
- [Transforms](https://morzecrew.github.io/bloomery/latest/reference/transforms/)
