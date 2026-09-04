# Errors

Every failure bloomery raises derives from `BloomeryError` — one `except BloomeryError`
catches everything — and every class lives in `bloomery.errors`, importable without
pulling in any pipeline stage.

## The hierarchy

```text
BloomeryError
├── InvariantViolated
├── SpecParseError
├── UnknownTransformError
├── TypeCheckError
├── TransformRegistrationError
├── StepError
│   ├── StepDeterminismError
│   └── StepContractViolation
├── ResolutionError
│   ├── CircularDerivation
│   └── MissingReference
├── GuardrailError
│   ├── UnitMismatch
│   ├── TaxBasisMismatch
│   ├── CurrencyMismatch
│   ├── GrainMismatch
│   ├── AdditivityViolation
│   ├── AssertLoweringError
│   ├── GrainViolation
│   ├── FanoutRisk
│   ├── HistoricalFanout
│   ├── NonAdditiveWithoutComponents
│   ├── InvalidMetricShape
│   ├── MetricFilterInvalid
│   ├── MartMissingTimeDimension
│   ├── ReservedEntityName
│   ├── QuarantineRetentionMissing
│   ├── DedupeTieBreakMissing
│   ├── DedupeDispositionConflict
│   ├── IngestionMetadataMissing
│   └── RedactionConflict
├── PlanError
│   ├── ContractViolation
│   └── RenameTargetMissing
├── EmitError
│   └── UnsupportedByTarget
└── PlannerError
    ├── UnknownMember
    ├── UnreachableAtGrain
    ├── AmbiguousDimension
    ├── InvalidRequest
    ├── FilterTypeMismatch
    └── UnsupportedFilter
        ├── UnsupportedSetRelation
        ├── UnsupportedHierarchy
        ├── UnsupportedTextOperator
        ├── FilterTooComplex
        ├── UnsupportedNegation
        ├── InvalidLiteral
        ├── UnsupportedSortNulls
        ├── UnsupportedPagination
        ├── UnsupportedFieldCompare   (adapter-owned)
        └── UnsupportedQuantifier     (adapter-owned)
```

## Per class

| Class | Stage | Raised when |
|---|---|---|
| `BloomeryError` | — | Base class; carries `message`, `source_path`, and `collected` |
| `InvariantViolated` | any | A guarantee an earlier stage was supposed to have established did not hold — never an authored spec's fault, and never spec feedback. Every total lookup that raises it is total *because* a guardrail already refused the case, so seeing one is a bug report |
| `StepError` | steps | Base of the referenced-implementation family (RFC 0017) |
| `StepDeterminismError` | steps (compile) | A step declaring `determinism: nondeterministic`, or a `seeded` step wired without a seed — a nondeterministic step makes a backfill disagree with the run it replaces |
| `StepContractViolation` | steps (**run time**) | Raised by the wrapper bloomery generates *into your warehouse*: the step's actual output contradicts its manifest — a missing or undeclared output, a differing column set, an unassignable type, or a NULL in a required column. The one error here a reader meets outside a compile |
| `SpecParseError` | parse | YAML failures, duplicate keys, unknown keys, shape/grammar violations — batched per document |
| `UnknownTransformError` | typecheck | A transform chain names a transform absent from the registry; message names the closest match |
| `TypeCheckError` | typecheck | Unparsable type strings; a chain's terminal type not assignable to the declared type; precision-cap overflows |
| `TransformRegistrationError` | registration | `register_transform` given an invalid spec or a colliding name |
| `ResolutionError` | resolve | Cross-spec reference and recipe failures over the dependency DAG — batched per stage |
| `CircularDerivation` | resolve | Any cycle in the dependency DAG; message names the full cycle path |
| `MissingReference` | resolve | A spec references a nonexistent entity, field, canonical field, template, or relationship end |
| `GuardrailError` | guardrails | The batched aggregate of guardrail violations, sorted by `(source_path, type name)` |
| `UnitMismatch` | guardrails | `+`/`-` operands with differing declared `unit` (currency + count) |
| `TaxBasisMismatch` | guardrails | `net` and `gross` — or an unknown basis beside a monetary operand — meeting in additive arithmetic |
| `CurrencyMismatch` | guardrails | Two distinct declared currencies meeting in one expression; no token waives it — `convert` answers it by producing a column declared in the target currency |
| `GrainMismatch` | guardrails | An expression combining columns of different grains without explicit aggregation |
| `AdditivityViolation` | guardrails | An aggregation contradicting the metric's declared additivity |
| `AssertLoweringError` | guardrails | An `assert:` clause ill-typed against the field's logical type |
| `GrainViolation` | guardrails | A mart measure whose grain does not strictly equal the mart grain |
| `FanoutRisk` | guardrails | A mart `via:` flatten step over a `one_to_many` relationship |
| `HistoricalFanout` | guardrails | A mart that flattens an `scd: type2` entity without an `as_of:` anchor, declares one on a non-historical entity, or is based on a historical one |
| `NonAdditiveWithoutComponents` | guardrails | A non-additive metric with no ratio/additive decomposition to recompute from |
| `InvalidMetricShape` | guardrails | A metric whose declaration contradicts itself — `derived:` beside `cumulative:`, a derived metric declared additive, a cumulative one with no measure to accumulate, or a derived expression referencing an alias its `inputs:` do not declare |
| `MetricFilterInvalid` | guardrails | A metric `filter:` naming a dimension the carrying mart does not flatten, a date-role dimension, or a value that does not fit the column's declared type |
| `MartMissingTimeDimension` | guardrails | A measure-carrying mart that declares no date role |
| `ReservedEntityName` | guardrails | An entity named `canonical`, `metric`, `source` or `step` — every lineage node id but an entity field's is `<prefix>.<rest>`, so such an entity mints ids in another kind's namespace |
| `QuarantineRetentionMissing` | guardrails | An entity with a `quarantine` disposition and no `quarantine:` block — reject rows hold raw payloads, so retention is required and never defaulted |
| `DedupeTieBreakMissing` | guardrails | `dedupe: {keep: latest_by}` without `tie_break` — rows sharing a timestamp would make the winner arbitrary |
| `DedupeDispositionConflict` | guardrails | A `coercible` rule weaker than `fail` on a field named by `dedupe.field`/`tie_break`, where an uncastable value leaves the dedupe order undefined |
| `IngestionMetadataMissing` | guardrails | An entity using `quarantine:`/`dedupe:` whose mapping neither maps nor acknowledges `_load_id`, `_ingested_at`, `_source_row_id` |
| `RedactionConflict` | guardrails | A `quarantine.redact` path intersecting a path the mapping reads — replay re-runs the mapping against `raw`, which the redaction has already destroyed |
| `PlanError` | plan | A spec diff that cannot produce a safe migration plan (including IR-version mismatch) |
| `ContractViolation` | plan | Dropping or narrowing a field still referenced by a reachable metric — expand/contract enforced |
| `RenameTargetMissing` | plan | A `renamed_from` annotation whose old name is absent from the old IR |
| `EmitError` | emit | The IR cannot be lowered to a target artifact; also unknown target/dialect names and emitter-registration collisions |
| `UnsupportedByTarget` | emit | An IR construct the selected target or dialect cannot express — fail loud, never approximate |
| `PlannerError` | planner | A malformed or unanswerable request; also the fallback for untranslated backend failures |
| `UnknownMember` | planner | A request names a metric or dimension that does not exist; message carries a did-you-mean |
| `UnreachableAtGrain` | planner | No single mart can answer the request at the requested grain — refused, never joined at plan time |
| `AmbiguousDimension` | planner | An unqualified reference to a dimension with multiple roles; message names the roles |
| `InvalidRequest` | planner | Bad filter/order/limit shapes, duplicates, malformed filter documents |
| `FilterTypeMismatch` | planner | A filter value whose type contradicts the dimension's logical type — refused before any SQL renders |
| `UnsupportedFilter` | planner | Base of the closed query-vocabulary refusal family (RFC 0015): every leaf carries a stable `.reason` code and, where the refusal happens after normalization, `.normalized` — the post-normalization form |
| `UnsupportedSetRelation` | planner | `$superset`/`$subset`/`$disjoint`/`$overlaps` — marts are flattened and scalar; no array columns exist to relate |
| `UnsupportedHierarchy` | planner | `$descendant_of`/`$ancestor_of` — model hierarchy as flattened level columns on the mart |
| `UnsupportedTextOperator` | planner | `$regex` (dialect-divergent, unbounded cost) and `$empty` (ambiguous across types) — use `like`/`ilike`, `eq ""`, or `is_null true` |
| `FilterTooComplex` | planner | CNF expansion exceeded the clause cap (default 64), refused *during* distribution |
| `UnsupportedNegation` | planner | A negated leaf with no complement operator (e.g. `$not $like`) |
| `InvalidLiteral` | planner | A non-finite numeric operand (`NaN`/`Infinity`, float or string form — fails open if permitted) or an invalid `like` pattern (unpaired trailing `\`, NUL) |
| `UnsupportedSortNulls` | planner | A `nulls` placement other than the canonical default (`first` for asc, `last` for desc) |
| `UnsupportedPagination` | planner | A non-zero `offset` or cursor pagination — paging aggregates belongs to the serving layer |
| `UnsupportedFieldCompare` | adapter | `$fields` field-to-field compare — declared here so app adapters can raise it; never raised by bloomery, and not part of `KNOWN_UNSUPPORTED` |
| `UnsupportedQuantifier` | adapter | `$any`/`$all`/`$none` element quantifiers — declared here so app adapters can raise it; never raised by bloomery, and not part of `KNOWN_UNSUPPORTED` |

## Data-quality refusals without their own class

Five data-quality guardrails have named leaves (above). The rest raise a bare
`GuardrailError` — the design authority names five, and minting further classes would
put names in `bloomery.errors` no RFC has decided on. Each is still a distinct,
addressed message inside the same batched aggregate:

| Refusal | Raised when |
|---|---|
| Pattern portability | A `pattern` rule one of the shipped dialect ports (DuckDB, Postgres, Trino) declares no regex surface for, or whose text SQLGlot will not carry into that dialect's SQL unchanged. The subset the pattern must speak is enforced earlier, at parse, as a `SpecParseError` |
| `dedupe` naming an unknown column | `dedupe.field` or a `tie_break` entry the entity does not declare — it lowers straight into `ORDER BY <column> DESC NULLS LAST`, so a typo would fail in the engine's binder on a model that compiled clean |
| `via` naming no relationship | A `referential` rule whose `via` matches nothing in the entity model's `relationships:` — a referential rule probes a *declared* relationship; there is nothing to join on otherwise |
| `via` declared from another entity | A `referential` rule naming a relationship whose `from` side is a sibling — the join reads that relationship's columns off *this* entity's extract, which never projects them |
| Self-referencing `referential` | A `referential` rule whose relationship's `to` side is the declaring entity — the rule lowers to a `LEFT JOIN` inside that entity's own model, and a model cannot join the table it is being built from |
| `unknown_member` on a non-string fk | `referential: {on_missing: unknown_member}` where the foreign key is not string-typed; the reserved member is the *string* `'__unknown__'`, and typed sentinels like `-1` could collide with a legal key |
| `unknown_member` on a composite key | The same disposition on a relationship joining through more than one column — the rewrite is one `CASE` over one column, so a composite fk would get a half-sentinel key matching no reserved row |
| Entity rule name a generated rule owns | An entity-level `quality:` rule named the same as a rule generated from the mapping (a field rule, an implicit `coercible`, a `referential` named after its relationship) — that name is the key of a quality-mart time series and an entry in `failed_rules`, so one of the two would have to be silently renamed |
| Reconcile grammar and resolution | A side outside the closed shape, an undeclared entity, an unknown column, sides keyed on different columns, or a duplicate check name |
| Reserved metric name | A project metric colliding with one the quality mart owns (`quality_rows_evaluated`, `quality_rows_failed`, `quality_rows_quarantined`, `quality_rows_deduped`, `quality_quarantine_rate`) — one flat namespace, and two definitions of one name is a silent winner, not a merge |

Data-quality refusals also happen at emit time rather than compile time, and those are
`UnsupportedByTarget`. Two are about the *dialect*, both on an absent NULL-on-failure
cast: an entity with `coercible` rules (RFC 0016 D30), and — because the
ingestion-metadata audit asserts `_ingested_at` casts to timestamp, which is a
`TRY_CAST` of its own — a **dedupe-only** entity too, even though it carries no quality
rules at all (D31). A third is about an absent Unicode normalization (D86). **None of
the three can fire on a shipped dialect**: DuckDB and Trino have `TRY_CAST`, Postgres
gets a guard around its own input parser (D84), and all three normalize. They are what a
fourth dialect would meet if it arrived without the capability, and they are provoked in
the test suite against exactly such a dialect.

None is about a *target's* artifact families any more. A `quarantine:` block and a
`reconcile:` check were refused for dbt until it grew the reject table, the replay macro
and the comparison model; what dbt still refuses is a Tier 3 `python_model` step, which
is about the adapters dbt's Python models run on rather than about anything bloomery
lowers. All of them name the target or dialect that does support the construct.

## The closed refusal list

The `UnsupportedFilter` family is a **closed, reviewed list** (RFC 0015), not drift:
every construct the query vocabulary cannot express was refused deliberately, with a
named error and a rationale. The stable `.reason` codes raisable by bloomery's three
parse functions (`parse_filter_json`, `parse_sort_json`, `parse_page_json`) are
exported as `bloomery.planner.KNOWN_UNSUPPORTED` and drift-guarded by test — adapters
key their refusal handling (HTTP problem responses, UI messages) on `.reason`, and
assert their own refusal sets against the export. Anything not on the list must
translate; growing the list is a reviewed decision, never an accident.

A refusal is not the same thing as malformed input. The parse functions raise
`UnsupportedFilter` only for constructs the vocabulary reviewed and declined (some during
tree construction, some after the rewrite — see the API reference) — a document that is simply ill-formed (a non-mapping payload, a
field map of the wrong shape, an unknown `$op`, an operand of the wrong type, a `nulls`
value that is neither `"first"` nor `"last"`, a non-int `limit`) raises `InvalidRequest`
and never carries a `.reason` from the closed list. Handle the two separately: a
`.reason` is a product decision to surface, an `InvalidRequest` is a caller bug to fix.

## Fix suggestions

Five refusals carry a structured next action beside the prose, because a human reads a
message and a program reads a *structure*. Each field exposes a value bloomery already
computed on its way to writing the message:

| Class | Field | Carries |
|---|---|---|
| `UnknownMember` | `did_you_mean: str \| None` | The closest known metric or dimension name |
| `UnreachableAtGrain` | `covering_marts: tuple[MartCoverage, ...]` | One entry per required measure: the mart that *does* serve it, and the grain it serves it at |
| `GrainViolation` | `offending_measures: tuple[MeasureRef, ...]` | The measure at odds with the mart grain, and its own grain |
| `UnknownStep` | `available_versions: tuple[int, ...]` | The versions of that `ref` the registry holds, ascending |
| `UnsupportedFilter` | `nearest_supported: str \| None` | The operator that would have worked (`$regex` → `"like"`) |

`MartCoverage(mart, metric, grain)` and `MeasureRef(measure, grain)` are frozen public
dataclasses, exported from the package root. They are typed values rather than encoded
strings on purpose: a `tuple[str, ...]` could name the marts but not say which metric
each covers at which grain, and that pairing is the whole content of the conflict.

```python
from bloomery.errors import UnreachableAtGrain

try:
    planner.plan(ir, request, dialect="duckdb")
except UnreachableAtGrain as refusal:
    for entry in refusal.covering_marts:
        print(f"{entry.metric} lives on {entry.mart} at grain {entry.grain}")
```

**Absence has one representation, and "the attribute is missing" is not it.** Every field
is always present: a collection field is `()` and a scalar is `None` when there is
nothing to suggest, so no caller needs `getattr`. An empty suggestion is a *fact* rather
than a search that was skipped, and the two emptinesses mean different repairs —
`covering_marts == ()` means no mart lists the metric at all (define one), while a
populated tuple means the metrics are split across grains (request them separately).

Nothing is fabricated. `$empty` is refused *because* `eq ""` and `is_null true` are
different questions, so `nearest_supported` is `None` there and the message names both;
a set relation has no scalar counterpart at all. And nothing is discoverable *only*
through a suggestion — the primary contract stays the message and, for
`UnsupportedFilter`, the `.reason` code.

`nearest_supported` is the `Op` *value* rather than the member, because `bloomery.errors`
imports nothing. `Op` is a `StrEnum`, so `refusal.nearest_supported == Op.LIKE` holds and
`Op(refusal.nearest_supported)` round-trips.

## `source_path`

Every error carries an optional `source_path` — a dotted/bracketed address into the
authored document, prefixed with the document's name (the key you passed to
`load_project`, or a deterministic label like `mapping[shop__orders->order]` where
parsed models no longer know their file):

```text
mappings/shopify.yaml: fields.unit_price.from
```

The parse stage always sets it; later stages set it best-effort.

## Batching

The parse, resolution, and guardrail stages **batch**: they collect every individual
failure in the stage and raise one aggregate whose message lists every path, so a spec
is fixed in one round-trip rather than one error at a time. On an aggregate,
`exc.collected` holds the individual errors as a tuple for machine consumption;
`BloomeryError.from_collected(errors)` is the constructor that builds one. A stage with
a single failure raises that failure directly, uncollected.

Planner errors are deliberately **not** batched — a request fails on its first problem,
because request-time callers want one actionable refusal, not a report.
