# RFC 0002 — Spec layer and error model

- **Status:** ✅ Complete — shipped 2026-08-07 (M1): the four spec kinds + `Project`,
  pure text-in loaders, and the total batched `BloomeryError` hierarchy landed as
  designed (`bloomery/spec/`, `bloomery/errors.py`).
- **Scope:** The input boundary of the compiler: the four Pydantic spec kinds
  (`Catalog`, `EntityModel`, `Mapping`, `MetricSet`), the `Project` container, the pure
  loaders (`load_catalog`, `load_project`), and the total `BloomeryError` hierarchy with
  source paths. Covers parsing and structural validation only — no cross-spec resolution
  (RFC 0005), no type checking (RFC 0004), no semantics of what the specs *mean* downstream.
  New modules: `bloomery/spec/`, `bloomery/errors.py`.
- **Related:** [`rfcs/_original-smelter-spec.md`](_original-smelter-spec.md) §3, §5.1, §8;
  RFC 0003 (IR these specs compile into), RFC 0005 (resolution over parsed specs).
- **Origin:** Original `smelter` spec v0.1, renamed `bloomery`.

---

## 1. Summary

Four spec kinds parsed from YAML text into strict Pydantic v2 models, wrapped in a
`Project` container. Loading is pure — callers pass strings, never paths. Every parse or
validation failure surfaces as a typed `BloomeryError` subclass carrying a dotted
`source_path` into the offending spec node. Unknown keys are rejected loudly
(`extra="forbid"` everywhere).

## 2. Motivation

The compiler is a pure function embedded in a control plane; its inputs arrive as text
produced by humans and by upstream (possibly LLM-assisted) proposal systems. A typo'd key
silently ignored is the worst failure mode in a config-driven system, and a bare `KeyError`
three stages later is nearly as bad — it points at compiler internals instead of the spec
line the author must fix. The spec layer exists so that every downstream stage can assume
structurally valid input and every failure names its origin.

## 3. Current state

Greenfield. The repository contains only scaffolding (empty `src/`, `tests/`). The original
spec (§3) fixes the YAML shapes; this RFC pins the Python model surface.

## 4. Goals / Non-goals

**Goals**

- Strict, versioned Pydantic models for all four spec kinds plus `Project`.
- Pure loaders: `load_catalog(text: str) -> Catalog`,
  `load_project(sources: Mapping[str, str]) -> Project`.
- A closed `BloomeryError` hierarchy; every failure the package can raise derives from it
  and carries `source_path` and a human message.
- Deterministic parse: same text → identical model instances (field order preserved as
  authored where meaningful, normalized where not).

**Non-goals**

- Cross-spec checks (does `mapping.target` name a real entity?) — that is resolution
  (RFC 0005). Parse validates *shape*, not *references*. This keeps the parse stage a
  per-document pure function.
- Reading files or URLs — the control plane owns I/O (hard invariant #1).
- Spec migrations between `spec_version`s — out of scope for v0.1; versions are carried and
  checked for supported range only.

## 5. Design

### 5.1 Module layout

```
src/bloomery/
  errors.py          # full error hierarchy — single module, no subpackage
  spec/
    __init__.py      # re-exports the public models
    common.py        # SpecModel base, source-path plumbing, shared enums
    catalog.py       # Catalog, CanonicalField, Recipe, CanonicalRelationship, MetricTemplate
    entity.py        # EntityModel, Entity, Field, Relationship
    mapping.py       # Mapping, KeyField, FieldMapping, TransformStep
    metrics.py       # MetricSet, Metric
    project.py       # Project container + load_catalog / load_project
```

### 5.2 The base model

```python
class SpecModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
```

All spec models are frozen — a parsed spec is immutable, which makes it safe to hash, cache,
and hand to the IR builder without defensive copies. Pydantic's own `ValidationError` never
escapes the package: loaders catch it and re-raise `SpecParseError` with the Pydantic error
locations converted to bloomery source paths.

### 5.3 Source paths

A `source_path` is a dotted/bracketed string addressing a node in the *authored document*,
e.g. `entities.shipment.fields.weight_kg.transform[1]`. It is built from Pydantic's
`loc` tuple plus the document name supplied to the loader (`sources` mapping key). Rules:

- dict keys join with `.`; list indices render as `[n]`.
- The document name prefixes the path: `mappings/shopify_order_lines: fields.unit_price.from`.
- Every `BloomeryError` has `source_path: str | None`; parse-stage errors always set it.

### 5.4 Error hierarchy

```python
class BloomeryError(Exception):
    source_path: str | None
    # message is the str(exc); subclasses add structured fields

class SpecParseError(BloomeryError): ...          # YAML/shape/unknown-key failures
class UnknownTransformError(BloomeryError): ...   # names closest match (RFC 0004)
class TypeCheckError(BloomeryError): ...          # RFC 0004
class ResolutionError(BloomeryError): ...         # RFC 0005 (CircularDerivation, MissingReference…)
class GuardrailError(BloomeryError): ...          # RFC 0006 (UnitMismatch, GrainMismatch…)
class PlanError(BloomeryError): ...               # RFC 0007 (ContractViolation)
class EmitError(BloomeryError): ...               # RFC 0008 (UnsupportedByTarget, UnknownDialect)
```

Leaf classes live with their stage's RFC but are all *declared* in `errors.py` — one module,
importable without pulling in any stage, so callers can write one `except BloomeryError`.
Multiple independent failures in one document are collected and raised as a single
`SpecParseError` whose message lists every path — authors fix a spec in one round-trip, not
one error at a time. (Later stages raise on first failure per stage but the guardrail stage
also batches; see RFC 0006.)

### 5.5 Spec model surface

Shapes follow the original spec §3.2–§3.4 exactly; the deltas and clarifications:

- **Types are strings at parse time** (`decimal(12,4)`, `string`, `int`, `variant`).
  Parsing them into `LogicalType` happens in the typing layer (RFC 0004); the spec layer
  only validates the *grammar* via a regex, so parse errors still point at the field.
- **`TransformStep`** is either a bare name (`to_int`) or a single-key mapping
  (`{parse_ts: "ISO8601"}`); normalized at parse into `TransformStep(name, args: tuple)`.
  Whether the name exists in the registry is checked at typecheck, not parse (parse has no
  registry dependency).
- **`Mapping.fields`** values are either a simple form (`{from, transform}`) or a recipe
  form (`{recipe, from: {alias: jsonpath}}`) — a discriminated union on the presence of
  `recipe`. `from` paths are JSONPath-lite strings (`$.a.b`); grammar-validated only.
- **`Entity.scd`** ∈ `{type1, type2}`; **`Entity.partition_by`** entries are either bare
  column names or `fn(column)` with `fn` ∈ `{days, months, years, hours}` (Iceberg-style),
  grammar-validated at parse.
- **`Entity.materialization`** (new, optional): `full | incremental_by_key |
  incremental_by_partition`. When absent, a deterministic default is derived later (IR
  build): `incremental_by_partition` if `partition_by` present, else `full`. This settles
  original-spec open question #4: *declared wins, inference is only the default*, and the
  resolved value is recorded in the IR so `plan()` sees materialization changes.
- **`MetricSet`** metrics mirror `metric_templates` but are tenant-authored; a metric may
  reference a template by `template:` or be fully inline. `additivity` ∈
  `{additive, semi_additive, non_additive}`; `semi_additive` carries a typed policy
  `{over: <dimension-ref>, rule: last|first|avg|max|min}` (`SemiAdditivePolicy`,
  RFC 0011 D5); `non_additive` requires a `ratio: {numerator, denominator}` (`RatioSpec`)
  or equivalent additive decomposition — absence is `NonAdditiveWithoutComponents`
  (RFC 0006).
- **`marts:`** — a fifth spec kind (`marts_version: 1`, at most one per project,
  optional), defining the wide-mart gold layer. Shape and validation: RFC 0010.
- **`Project`** = `entity_model` + ordered `mappings` + optional `metric_set` + optional
  `marts`; the catalog is deliberately *not* part of `Project` (it is vertical-level,
  passed separately to `compile_project` / `resolve`, per spec §8).

`load_project` keys the `sources` mapping by document name; each document self-identifies
its kind via its version key (`spec_version` / `mapping_version` / `metrics_version`).
Exactly one EntityModel and at most one MetricSet per project; violations are
`SpecParseError`s naming the duplicate documents.

### 5.6 YAML parsing

`yaml.safe_load` via PyYAML — one new runtime dependency beyond the original spec's list
(pydantic has no YAML support; every alternative — ruamel, strictyaml — is heavier).
Duplicate-key detection is enforced with a custom loader that raises `SpecParseError`
(PyYAML's default silently keeps the last value — exactly the silent failure this layer
exists to prevent). Only `safe_load`; YAML tags/anchors resolving to non-plain types are
rejected.

## 6. Tests

- Unit: every model's happy path; every rejection (unknown key, missing required, bad type
  grammar, bad enum, duplicate YAML key, duplicate document kind) asserting both error type
  and `source_path`.
- Property (Hypothesis): round-trip — `model → yaml → load → model` is identity for
  generated valid specs.
- The `minimal` and `ecom_basic` fixture projects (RFC 0009) parse clean.

## 7. Docs

`pages/reference/spec-catalog.md`, `spec-entity-model.md`, `spec-mapping.md`,
`spec-metrics.md` — one reference page per spec kind, generated-adjacent (hand-written but
mirroring the model fields exactly). An explanation page on the error model and source paths.

## 8. Out of scope

- **Spec-version migration tooling** — v0.1 supports exactly one version per kind; a
  version outside the supported range is a `SpecParseError`. Migrations arrive when a
  second version exists to migrate from.
- **JSON/TOML input** — YAML only; loaders take text, so a caller can pre-convert.

## 9. Risks

- *Pydantic v2 error-loc mapping is fiddly* (unions produce branched locs). Mitigation: a
  single `loc → source_path` function with exhaustive unit tests; discriminated unions
  everywhere a union exists, so locs stay linear.
- *Frozen models with tuple fields* deviate from YAML's list-shaped mental model; docs show
  YAML, not Python, so authors never see it.

## 10. Unresolved questions

- None blocking. Implementation is free to settle exact Pydantic idioms (discriminators,
  `BeforeValidator` vs `model_validator`) as long as error paths stay precise.

## 11. Decisions

| # | Decision |
| --- | --- |
| 1 | All spec models are Pydantic v2, `extra="forbid"`, `frozen=True`. Unknown keys are hard errors at parse. |
| 2 | Loaders are pure text-in: `load_catalog(text)`, `load_project(sources: Mapping[str, str])`. No path/file API will be added to the core package — I/O belongs to callers. |
| 3 | Every raisable failure derives from `BloomeryError` and carries `source_path`; all error classes are declared in `bloomery/errors.py` so `except BloomeryError` needs one import. Pydantic/yaml exceptions never escape. |
| 4 | Parse validates shape and grammar only; reference existence (entities, transforms, canonical fields) is deferred to resolve/typecheck. Consequence: a shape-valid spec with dangling references parses fine — callers must run `resolve` to trust it. |
| 5 | PyYAML (`safe_load` + duplicate-key rejection) is added as a runtime dependency. |
| 6 | Parse-stage errors are batched per document (all failures reported at once). |
| 7 | `materialization` is explicit-with-derived-default (settles original open question #4); the resolved value is IR-recorded and diffable. |
| 8 | Catalog is passed separately from `Project` (vertical-level vs tenant-level), matching spec §8's `compile_project(..., catalog=...)`. |
| 9 | (Amended for `_bloomery-changes.md`) A fifth spec kind `marts:` joins the four (RFC 0010); `semi_additive` metrics carry a typed `SemiAdditivePolicy` and `non_additive` metrics a `RatioSpec` (RFC 0011 D5). Spec-layer scope is still shape/grammar only. |
| 10 | (Amended for `_bloomery-metricflow-pivot.md`) `metric_time` is a reserved dimension/field name, rejected at spec validation with a clear message (RFC 0013 R4). The `Metric` model reserves optional `cumulative:` (window / grain_to_date) and derived-expression forms lowered per RFC 0013's mapping table; both are additive spec surface, parse-validated only. |

## 12. Phasing

Ships in M1 together with RFC 0003 (IR); the loaders and error hierarchy are the first
merged code in the package.
