# Spec schemas

Field-by-field reference for the six spec kinds. Parsing is strict: unknown keys,
duplicate YAML keys, and grammar violations are hard `SpecParseError`s, batched per
document with a source path per failure. Parse validates shape and grammar only —
whether references exist is checked at resolution.

Each project document self-identifies by its version key: `spec_version` (EntityModel),
`mapping_version` (Mapping), `metrics_version` (MetricSet), `marts_version` (MartSet),
`steps_version` (StepSet). A project holds exactly one EntityModel, any number of
Mappings, and at most one MetricSet, MartSet and StepSet. The Catalog
(`catalog_version`) is not part of a project — load it with `load_catalog` and pass it
separately.

A version key is required, and it is also how bloomery tells one kind of document from
another. Each is pinned to `1`: a document declaring a version bloomery does not
implement is **refused**, never read as one it does.

## Shared grammars

| Grammar | Rule | Examples |
|---|---|---|
| Type string | `string`, `int`, `bool`, `date`, `timestamp`, `variant`, or `decimal(p, s)` | `decimal(12,4)` |
| Partition spec | A bare column, or `fn(column)` with `fn` ∈ `days`/`months`/`years`/`hours` | `days(order_date)` |
| Source path | JSONPath-lite: `$` followed by dotted identifiers only | `$.customer.id` |
| Currency code | Three uppercase letters (ISO 4217) | `EUR` |
| Member name | Any identifier except the reserved names | — |
| Rule name | `[a-z0-9_]+` — identifier-constrained so no flag lowering ever needs escaping | `discount_not_exceeding_gross` |
| Retention duration | A positive integer (no leading zero, ≤ 5 digits) plus one unit of `h` / `d` / `w` | `90d` |

**Reserved names.** `metric_time` may not be used as a field, dimension, or role name —
the planner owns it as the canonical query-time dimension. The generated data-quality
and ingestion-metadata columns are reserved on the same terms: `_quality_flags`,
`_quality_ok`, `_quality_repairs`, `_load_id`, `_ingested_at`, `_source_row_id`,
`has_quality_flags`. So is `_source`, the union merge's provenance column — reserved
unconditionally rather than only on merged entities, because a name that is legal until a
second mapping arrives is a trap laid for the change that adds one.

**Retention units.** Months and years are deliberately absent — they are not fixed
durations, and a retention window that means something different in February is a legal
problem rather than a convenience. Minutes are absent because `m` would read as either.

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
| `fx_rates` | FxRates | no | The dated exchange-rate relation `convert` reads |

### FxRates

The shape of a rate table the operator supplies; bloomery reads it and never builds it.
See [transforms](transforms.md#the-rate-relation) for what it is for.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `relation` | relation name | yes | Bare name, resolved through the naming policy at the silver layer |
| `from` | column name | yes | The currency a rate converts *from* |
| `to` | column name | yes | The currency a rate converts *to* |
| `rate` | column name | yes | The multiplier |
| `valid_from` | column name | yes | Inclusive start of the rate's validity |
| `valid_to` | column name | yes | Exclusive end, `NULL` for the live rate — required, because one end is not an interval |

No two roles may name the same column: each reads a different column of the rate
relation, and a shared name makes the emitted predicate compare a column against itself.

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

Same shape as a [Metric](#metric) minus `template`, with `additivity` required. A project metric that names it via `template:` merges values with the
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
| `reconcile` | list of Reconcile | no (`[]`) | Cross-entity reconciliation checks — see [Reconcile](#reconcile) |

### Entity

| Field | Type | Required | Meaning |
|---|---|---|---|
| `grain` | string | yes | Prose grain — appears in error messages and explanations |
| `key` | list of field names, ≥ 1 | yes | Entity key, authored order kept |
| `scd` | `type1` \| `type2` | no (`type1`) | Slowly-changing-dimension kind |
| `partition_by` | list of partition specs | no (`[]`) | Physical partitioning |
| `materialization` | `full` \| `incremental_by_key` \| `incremental_by_partition` | no | Explicit wins; default is `incremental_by_partition` when `partition_by` is set, else `full` |
| `fields` | map name → Field | yes | Typed fields (`metric_time` reserved) |
| `quality` | list of entity quality rules | no (`[]`) | Row rules — see [Entity quality rules](#entity-quality-rules) |
| `dedupe` | Dedupe | no | Keep one row per key — see [Dedupe](#dedupe) |
| `quarantine` | Quarantine | no | Reject-table policy — see [Quarantine](#quarantine) |

**`materialization` is derived, never inferred, and that distinction is the rule.** An
entity with a partition key gets `incremental_by_partition` without anyone writing it —
that is a *default*: visible in the compiled output, and overridable by saying otherwise.
What bloomery will not do is *infer* the strategy from grain and partition key in the
ambiguous cases, because an inference is a guess the author cannot see, and a wrong guess
here produces a wrong backfill scope that surfaces as missing rows.

> **bloomery derives defaults; it does not infer intent.**

The same line runs through recipes: the compiler validates the recipe a mapping recorded
and never chooses one itself. If a specific inference is later shown to be both safe *and*
visible in the emitted artifact, it can be argued as a change — a default carries no such
burden, which is why one is cheap and the other is not.

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
| `via` | map from-column → to-column, ≥ 1 | yes | Join columns — a relationship *is* its join, so an empty map is a `SpecParseError` |
| `cardinality` | `many_to_one` \| `one_to_one` \| `one_to_many` | yes | Checked by the fan-out guardrail |

### Entity quality rules

Row rules, discriminated on `rule`. Both read more than one column, which is why they
sit on the entity rather than on a mapping field.

| `rule` | Field | Type | Required | Meaning |
|---|---|---|---|---|
| `expression` | `name` | rule name | yes | Reaches `_quality_flags` and the quality mart, so it is authored, never generated. Refused if it collides with a name generated from the mapping |
| `expression` | `expr` | string | yes | Boolean predicate over the entity's own columns |
| `expression` | `on_fail` | `flag` \| `quarantine` \| `fail` | yes | Disposition |
| `referential` | `via` | relationship name | yes | The declared relationship to probe |
| `referential` | `on_missing` | `unknown_member` \| `quarantine` \| `flag` | yes | Disposition for a non-null fk with no matching row |

`referential` carries `on_missing`, not `on_fail`: `unknown_member` is a disposition no
other rule has (the row passes with its fk rewritten to the reserved `'__unknown__'`
member), and `fail` is deliberately unavailable — a pipeline-stopping orphan gate is a
`reconcile` check instead. `unknown_member` requires a string-typed fk; the relationship's
`to` side may not be the declaring entity.

### Dedupe

| Field | Type | Required | Meaning |
|---|---|---|---|
| `keep` | `latest_by` | yes | Closed vocabulary, one value today |
| `field` | column name | yes | The recency column, ordered descending |
| `tie_break` | list of column names | no (`[]`) | Further sort keys, authored order kept |

Partitions by the entity's `key`. `tie_break` is optional in the grammar and **mandatory
in a model**: its absence under `keep: latest_by` is the compile error
`DedupeTieBreakMissing`. The order finishes with `_source_row_id`, with `NULLS LAST`
pinned on every sort key, so the winner is unique by construction.

### Quarantine

| Field | Type | Required | Meaning |
|---|---|---|---|
| `retention` | retention duration | yes | How long reject rows live; the only deleter |
| `redact` | list of source paths | no (`[]`) | JSONPaths stripped from `raw` and `key_values` at write time |

The block is required whenever any rule can quarantine — `QuarantineRetentionMissing`
otherwise, never a default, because reject rows hold raw source payloads. A `redact:`
path may not intersect a path the mapping reads (`RedactionConflict`): replay re-runs the
mapping against `raw`, and a redacted path is gone by then.

### Reconcile

Document-level, a sibling of `entities:` — a check relates two entities and belongs to
neither.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `name` | rule name | yes | Unique per project; each check emits its own model and audit |
| `left` / `right` | reconcile side | yes | The two sides, keyed on the same columns |
| `tolerance` | quoted decimal ≥ 0 | yes | Absolute tolerance; an unquoted YAML number is a float and refused |
| `on_fail` | `flag` \| `quarantine` \| `fail` | yes | Disposition |

A side is one of two closed shapes:

```yaml
left:  "sum(order_item.line_total) by order_id"   # <agg>(<entity>.<column>) by <columns>
right: "order.total_amount"                       # <entity>.<column>, keyed by that entity's key
```

Both sides must key on the same columns, since they join on their keys. Anything outside
the grammar is a `GuardrailError` — a reconcile side is a declared shape, not SQL.

**A NULL key is a group, not an absence.** The comparison is null-safe throughout,
because the aggregate side's `GROUP BY` already collects every NULL key into one group
and everything below it has to read that column by the same rule. The emitted model is a
`_keys` CTE — both sides' key columns, `UNION`ed — with each side attached by
`LEFT JOIN ... IS NOT DISTINCT FROM`. A key present on *one side only* still fails, which
is what the outer join is for, but a NULL group that agrees on both sides passes, as one
row. Neither the entity key nor an aggregate's `by` columns are forced non-nullable, so
this is reachable from an ordinary project; if a NULL key is itself a data-quality problem
for you, say so with a `not_null` rule.

The long spelling is not a stylistic choice. `FULL OUTER JOIN ... ON a IS NOT DISTINCT
FROM b` says the same thing in one line and renders identically on all three dialects,
and PostgreSQL then refuses to run it — its full join is planned as a merge or hash join,
and a null-safe condition is neither. One shape is emitted everywhere rather than a check
that compares NULL keys on two engines out of three.

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

An entity that uses `quarantine:` or `dedupe:` requires the bronze ingestion-metadata
columns `_load_id`, `_ingested_at`, and `_source_row_id`. They are reserved names, so a
mapping states they exist by listing them in `unmapped:`; their absence is
`IngestionMetadataMissing`. Their *values* are checked at run time by a generated
blocking audit: none of the three may be null, `_source_row_id` must be unique per
source row, and `_ingested_at` must cast to timestamp. The audit is emitted only for
dialects with `TRY_CAST`; on the others the entity is `UnsupportedByTarget`.

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
| simple | `quality` | list of field quality rules | no (`[]`) | See [Field quality rules](#field-quality-rules) |
| recipe | `recipe` | string | yes | Catalog recipe id, chosen upstream and recorded here |
| recipe | `from` | map alias → source path | yes | Bindings for every name in the recipe's `requires` — exactly, no more, no fewer |
| recipe | `direct` | source path | no | The source *also* carries the field directly — emits a `<name>__direct` shadow column and a reconciliation audit |
| recipe | `quality` | list of field quality rules | no (`[]`) | See [Field quality rules](#field-quality-rules) |

### Transform steps

A step is a bare name or a single-key mapping; args normalize to a tuple:

```yaml
transform: [trim, to_string]              # zero-arg steps
transform: [{parse_ts: ISO8601}]          # one arg
transform: [{to_decimal: [12, 4]}]        # multiple args
```

The available names are the closed whitelist in the
[transforms reference](transforms.md); existence is checked at typecheck, not parse.

### Field quality rules

A closed catalogue, discriminated on `rule`. New rules are RFC amendments, never config.
Every rule requires `on_fail` ∈ `flag` \| `quarantine` \| `fail` — there is no
project-wide default, and there is deliberately no `drop` and no `repair` in v1.

| `rule` | Parameters | Fires when |
|---|---|---|
| `coercible` | — | The transform chain produced a coercion-failure marker |
| `not_null` | — | The value is NULL |
| `range` | `min` and/or `max` (int, decimal, or an exact string bound; ≥ 1 of the two) | The value falls outside a declared bound |
| `length` | `min` and/or `max` (int ≥ 0; ≥ 1 of the two) | The character count falls outside a declared bound |
| `pattern` | `regex` (portable subset) | The value does not match |
| `in_enum` | — | The value survived its `enum_map` chain unmapped |
| `in_set` | `values` (list of strings/ints, ≥ 1) | The value is outside the literal set |
| `unique` | — | The value repeats within the partition slice |

Notes that change how you write them:

- **`coercible` is implicit and opt-in per entity.** An entity joins the quality system
  by declaring `quality:`, `quarantine:`, or any field-level `quality:` — `dedupe:`
  alone does not. Every mapped field of a quality-carrying entity then gets a `coercible`
  rule at `quarantine` unless you declare one explicitly to override the disposition.
  It is forced to `fail` on any field named by `dedupe.field`/`tie_break`
  (`DedupeDispositionConflict` otherwise).
- **Bounds are separate rules.** `range`/`length` take one or both bounds, and two bounds
  needing different dispositions are simply two rules.
- **`range` bounds are exact.** Write an int, or quote the value: a quoted bound must be
  an exact decimal (`"10000000000"`, `"0.01"` — sign and fraction allowed, no exponent)
  or an ISO date/timestamp. `"nan"`, `"inf"`, and `"1e10"` are refused at parse: the
  first two make a comparison that is never true on one engine and always true on
  another, and the third renders as a float literal, which no emission path may carry.
- **`in_enum` takes no values.** The admissible set *is* the chain's `enum_map` targets;
  restating it here would let the two drift.
- **`unique` is per partition slice**, in both full and incremental runs — for an
  unpartitioned entity the slice is the whole table. Cross-partition duplicates are
  key-based `dedupe`'s job, in every mode.
- **Nulls belong to `not_null` and `coercible` only.** Every other rule's violation
  predicate must be definitively TRUE to fire; a NULL-involved comparison evaluates to
  SQL `UNKNOWN` and stays silent.

`assert:` on an entity field and `quality:` on a mapping field are different tools:
`assert:` is "alert me" (an audit that observes), `quality:` is "act on the row" (the
disposition system that routes). A field may carry both.

#### The portable regex subset

`pattern` regexes are restricted to what the shipped dialect ports agree on — DuckDB and
Trino run RE2, Postgres runs POSIX ARE. The subset is an **allowlist**: a pattern is
scanned left to right and anything the list below does not name is refused at parse,
with the construct named in the error.

| Accepted | Refused (a selection — the list is closed, so anything unnamed is refused too) |
|---|---|
| Literals and escaped literals (`\.`, `\(`, `\\`, `\t`, `\n`, `\r`) | Backreferences `\1`, property classes `\p{L}`, character-code escapes `\x41` |
| `.` | `\A`, `\Z`, `\z`, `\b`, `\B`, `\G` |
| Character classes `[a-z]`, `[^a-z]`, with ranges and negation | POSIX classes `[[:alpha:]]`, collating elements `[[.x.]]`, equivalence classes `[[=x=]]` |
| `\d` `\w` `\s` and `\D` `\W` `\S` | `\D` `\W` `\S` *inside* a class — an error on Postgres, legal on RE2 |
| Anchors `^` `$` | Anchors inside a group, or mid-alternative |
| Quantifiers `*` `+` `?` `{n}` `{n,}` `{n,m}` | Lazy `a*?`, possessive `a*+`, doubled `a**` |
| Alternation `\|` | — |
| Non-capturing groups `(?:…)` | Capturing groups `(…)`, lookaround `(?=` `(?!` `(?<=` `(?<!`, named groups `(?P<` `(?<`, atomic groups `(?>`, inline flags `(?i)`, comments `(?#`, conditionals `(?(` |

Escapes and character classes are scanned, not substring-matched, so `\(?=` and `[(?=]`
are literals rather than lookahead.

**Patterns must be anchored, and you write the anchors.** `[0-9]{5}` is refused;
`^[0-9]{5}$` is accepted. A SQL regex predicate matches a substring, so the unanchored
form would accept `abc12345xyz`. Each top-level alternative carries its own pair:
`^a$|^b$`, not `^a|b$`.

Capturing groups are refused in favour of `(?:…)`: a rule is a boolean match and
captures nothing, and numbered groups are what backreferences read.

Two divergences are accepted and documented rather than refused: `.` excludes newline on
RE2 and includes it on Postgres ARE, and `\d`/`\w`/`\s` are ASCII on RE2 but
locale-defined on ARE.

At the guardrail stage each pattern is additionally checked against the shipped dialect
ports (`duckdb`, `postgres`, `trino`) for a *regex surface* — a dialect that declares no
regex support, or through which the pattern literal cannot be rendered, is a
`GuardrailError`. That check is deliberately narrow: bloomery never executes SQL, so
nothing at compile time can prove an engine's regex engine accepts a pattern. The subset
above is what carries the portability claim.

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
| `cumulative` | CumulativeSpec | no | Accumulate this metric's own measure over time |
| `derived` | DerivedSpec | with `non_additive` | Compute the metric from other metrics, optionally read at an offset |
| `filter` | list of MetricFilter | no (`[]`) | Restrict the rows the metric aggregates; clauses are ANDed |

### RatioSpec

| Field | Type | Required | Meaning |
|---|---|---|---|
| `numerator` / `denominator` | metric name | yes | The additive components |

### DerivedSpec

A metric with no measure of its own, computed by an expression over others. The
alias is the mapping key rather than a field, because the expression references it.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `expr` | string | yes | Expression over the input aliases |
| `inputs` | map alias → MetricInputSpec | yes (≥ 1) | What each alias reads |

The expression must reference exactly the declared aliases — an unknown one and an
unread one are both refused (`InvalidMetricShape`). The inputs are also the metric's
dependency edges; they need not be repeated in `requires_metrics`.

### MetricInputSpec

| Field | Type | Required | Meaning |
|---|---|---|---|
| `metric` | metric name | yes | The metric this alias reads |
| `offset` | MetricOffset | no | How far back it is read |

### MetricOffset

Exactly one of the two.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `window` | `"<count> <grain>"` | one of | A fixed distance back — `"1 year"`, `"7 days"` |
| `to_grain` | `day` \| `week` \| `month` \| `quarter` \| `year` | one of | The start of the containing period |

### CumulativeSpec

Exactly one of the two. The metric keeps its own `agg`/`expr` and its own
`additivity` — those describe the measure, this describes how it accumulates.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `window` | `"<count> <grain>"` | one of | A trailing window — `"7 days"` |
| `grain_to_date` | `day` \| `week` \| `month` \| `quarter` \| `year` | one of | Accumulate from the start of each period |

### MetricFilter

A typed predicate, never a SQL string: values are validated against the flattened
column's declared logical type and are never cast.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `dimension` | column name | yes | A **categorical** dimension of the mart carrying the metric |
| `op` | `eq` \| `ne` \| `in` \| `not_in` \| `gt` \| `gte` \| `lt` \| `lte` \| `is_null` | yes | Comparison |
| `values` | list of scalars | per operator | One for the comparisons, one bool for `is_null`, one or more for `in`/`not_in` |

Deliberately narrower than the [query vocabulary](../how-to/plan-a-metric-request.md)
a *request* may use: no `like`/`ilike`, whose escape language and case-folding
portability buy nothing where the author already knows the values. A date-role
dimension is refused — a metric pinned to one period is a constant, and the time
relation belongs in `cumulative:` or an `offset:`.

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
  - {via: order_of_customer, prefix: customer_, as_of: order_date}  # ... as of a date
  - {date: order_date, role: ordered}       # declare a date role
```

| Form | Field | Type | Required | Meaning |
|---|---|---|---|---|
| via | `via` | relationship name | yes | Relationship to flatten; `one_to_many` is refused (fan-out) |
| via | `prefix` | string, non-empty | yes | Prefix on every flattened column — mandatory, collisions are errors |
| via | `as_of` | base date/timestamp column | on `scd: type2` | The anchor: the instant the joined entity is read as of. Required to flatten a historical dimension, refused on any other |
| date | `date` | field name | yes | A date/timestamp column of the base entity |
| date | `role` | member name | yes | Expands to `<role>_day` … `<role>_year` bucket columns (`metric_time` reserved) |

## StepSet (`steps_version`)

At most one per project, and optional — most projects wire no steps. A step is a
*referenced implementation*: the document names platform-owned code by `ref@version` and
binds it into the pipeline. It cannot carry a body and cannot name a file to load, which
is what keeps an authored spec from becoming an arbitrary-code-execution surface — the
property comes from the absence of a field, not from validating one.

The manifest describing what a step *is* — its tier, its declared inputs, outputs and
parameter bounds — is not a spec document. It reaches the compiler as a `StepRegistry`
passed to `compile_project(..., steps=…)`, so bloomery reads no step files at all. See
[Steps: referenced implementations](../concepts/step-registry.md) for the manifest side
and the three tiers.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `steps_version` | `1` | yes | Document version key |
| `steps` | list of StepWiring | no (`[]`) | One wiring per step |

### StepWiring

| Field | Type | Required | Meaning |
|---|---|---|---|
| `use` | `ref@version` | yes | `^[a-z][a-z0-9_]*@[1-9][0-9]*$`. One wiring per `ref` — a version bump is that step changing, not a second step |
| `outputs` | map name → relation | yes, ≥ 1 | Binds each declared output to a relation it writes |
| `inputs` | map name → relation | no (`{}`) | Binds each declared input to a relation it reads |
| `parameters` | map name → string / int / bool / decimal | no (`{}`) | Tunables the manifest declares, within the bounds it declares |
| `seed` | int | no | Required for a `seeded` step, refused for the other two tiers |
| `quality` | list of expression rules | no (`[]`) | `expression` rules only; see [Entity quality rules](#entity-quality-rules) for the shape |
| `applies_to` | map rule name → output | no (`{}`) | Which output each rule applies to. Required for every declared rule — a step has several outputs, so "on this step" cannot be lowered |
| `canonical` | map output → {column: canonical field} | no (`{}`) | Which canonical field a produced column *is*. Never inferred from a matching name; without it, metrics over a step output are unreachable |

A bound relation is an optionally-namespaced identifier and nothing else
(`^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$`) — these strings reach generated
source, so the grammar is the second of two locks.

```yaml
steps_version: 1
steps:
  - use: resolve_customers@2
    inputs: {shopify: bronze.shopify_customers, stripe: bronze.stripe_customers}
    outputs: {customer: silver.customer, links: silver.customer_link}
    parameters: {threshold: 0.92}
    canonical:
      customer: {customer_id: customer_id}
    quality:
      - {name: confidence_is_sane, rule: expression, expr: "confidence BETWEEN 0 AND 1", on_fail: fail}
    applies_to: {confidence_is_sane: links}
```

**Shape versus resolution.** Parse checks that `canonical` and `applies_to` name outputs
this wiring binds and that every declared rule says which output it applies to. Whether
the manifest actually declares that output, that column or that parameter is a resolution
question — the spec layer has never seen a manifest.
