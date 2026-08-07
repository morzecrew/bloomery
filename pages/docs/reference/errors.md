# Errors

Every failure bloomery raises derives from `BloomeryError` — one `except BloomeryError`
catches everything — and every class lives in `bloomery.errors`, importable without
pulling in any pipeline stage.

## The hierarchy

```text
BloomeryError
├── SpecParseError
├── UnknownTransformError
├── TypeCheckError
├── TransformRegistrationError
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
│   ├── NonAdditiveWithoutComponents
│   └── MartMissingTimeDimension
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
    └── FilterTypeMismatch
```

## Per class

| Class | Stage | Raised when |
|---|---|---|
| `BloomeryError` | — | Base class; carries `message`, `source_path`, and `collected` |
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
| `CurrencyMismatch` | guardrails | Two distinct declared currencies with no explicit `convert` step in the chain |
| `GrainMismatch` | guardrails | An expression combining columns of different grains without explicit aggregation |
| `AdditivityViolation` | guardrails | An aggregation contradicting the metric's declared additivity |
| `AssertLoweringError` | guardrails | An `assert:` clause ill-typed against the field's logical type |
| `GrainViolation` | guardrails | A mart measure whose grain does not strictly equal the mart grain |
| `FanoutRisk` | guardrails | A mart `via:` flatten step over a `one_to_many` relationship |
| `NonAdditiveWithoutComponents` | guardrails | A non-additive metric with no ratio/additive decomposition to recompute from |
| `MartMissingTimeDimension` | guardrails | A measure-carrying mart that declares no date role |
| `PlanError` | plan | A spec diff that cannot produce a safe migration plan (including IR-version mismatch) |
| `ContractViolation` | plan | Dropping or narrowing a field still referenced by a reachable metric — expand/contract enforced |
| `RenameTargetMissing` | plan | A `renamed_from` annotation whose old name is absent from the old IR |
| `EmitError` | emit | The IR cannot be lowered to a target artifact; also unknown target/dialect names and emitter-registration collisions |
| `UnsupportedByTarget` | emit | An IR construct the selected target or dialect cannot express — fail loud, never approximate |
| `PlannerError` | planner | A malformed or unanswerable request; also the fallback for untranslated backend failures |
| `UnknownMember` | planner | A request names a metric or dimension that does not exist; message carries a did-you-mean |
| `UnreachableAtGrain` | planner | No single mart can answer the request at the requested grain — refused, never joined at plan time |
| `AmbiguousDimension` | planner | An unqualified reference to a dimension with multiple roles; message names the roles |
| `InvalidRequest` | planner | Bad filter/order/limit shapes, duplicates, floats as filter values |
| `FilterTypeMismatch` | planner | A filter value whose type contradicts the dimension's logical type — refused before any SQL renders |

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
