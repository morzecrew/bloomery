# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-08-15

First release. Everything bloomery does is new here, so this section is one `Added` —
`Changed`, `Deprecated`, `Removed`, `Fixed` and `Security` describe movement away from a
version somebody could have installed, and there is not one yet. They begin at 0.2.0.

From this tag the [stability promises](https://morzecrew.github.io/bloomery/reference/stability/)
bind: SemVer over the Python API, per-kind versioning over spec YAML, and emitted
artifacts explicitly **not** stable across bloomery versions.

### Added

**The compiler**

- `compile_project(project, *, target, dialect, naming=None, catalog=None, steps=EMPTY_REGISTRY)`
  — declarative specs to target artifacts as one pure function. No filesystem, no
  network, no clock, no randomness: the same specs produce byte-identical artifacts
  across machines, processes and `PYTHONHASHSEED` values.
- **Six spec document kinds**, each strict YAML that self-identifies by its version key:
  Catalog (`catalog_version`), EntityModel (`spec_version`), Mapping (`mapping_version`),
  MetricSet (`metrics_version`), MartSet (`marts_version`) and StepSet (`steps_version`).
  Unknown keys, duplicate YAML keys and grammar violations are refused, batched per
  document with a source path each. A version bloomery does not implement is refused
  rather than read as one it does.
- Deterministic intermediate representation with a `blm1:` content fingerprint
  (`build_project_ir`, `project_fingerprint`), stamped into every artifact header.
  `bloomery_ir_version` is **5**; it covers each node's field names and count, so an IR
  shape change moves every fingerprint by construction.
- A closed whitelist of 24 typed mapping transforms with a compile-time typecheck of
  every chain, decimal precision and scale tracked through arithmetic, and
  `register_transform` for vetted extensions.
- Resolution (`resolve`): cross-spec reference validation, recorded-recipe validation,
  cycle detection, and metric reachability naming the specific missing leaf.
  `UnreachableMetric.via` names the chain when a metric is blocked *through* another one.

**Guardrails**

- Fail-closed unit, tax-basis, currency, grain and additivity checks; mart fan-out and
  grain protection; `assert:` clauses lowered to target-native audits. Every violation is
  a typed error with a source path, and stages batch so a spec is fixed in one round trip.
- Two constructs that used to compile clean and could not be right are refused:
  `HistoricalFanout` for a mart flattening an `scd: type2` dimension with no validity
  predicate (each base row multiplied by that key's version count, with every declared
  cardinality still honest), and `UnsupportedByTarget` for the `convert` transform, which
  lowered to a `CONVERT_CURRENCY` call no engine defines. `convert` stays registered and
  typechecked; currency conversion needs a dated rate relation bloomery does not model.

**Data quality**

- Cleansing as spec surface: a closed rule catalogue (`coercible`, `not_null`, `range`,
  `length`, `pattern`, `in_enum`, `in_set`, `unique`, `normalize`, `charset`), entity row
  rules (`expression`, `referential`), `dedupe:`, `quarantine:`, document-level
  `reconcile:`, and cross-entity `coverage:` checks. Every rule carries an explicit
  `on_fail` — `flag`, `quarantine`, `fail` or `repair` — and rules evaluate under a
  strict three-valued discipline, so a NULL-involved comparison never fires.
- `pattern` speaks a portable regex allowlist, refused at parse with the construct named;
  `range` bounds are exact (int, decimal, or a string carrying an exact decimal or ISO
  date/timestamp); `charset` declares admissible characters as `U+` codepoints.
- One replayable `<entity>__reject` table per entity with a `reject_id` recomputable from
  the row, a replay artifact that re-runs the current mapping under the pipeline's own
  dedupe order, `retention:` and `redact:`. bloomery emits the artifact and never runs it.
- `gold.mart_data_quality` — an ordinary mart with one row per rule evaluation plus an
  accounting row per entity, so quarantine rate is a plain `MetricRequest`. Five reserved
  metrics come with it.
- Every silver model projects `_quality_flags` and `_quality_ok`; a mart over a
  rule-carrying base flattens them into a `has_quality_flags` dimension.

**Steps: referenced implementations**

- A project may wire platform-owned steps through a `steps_version: 1` document —
  `use: ref@version`, input/output bindings, parameters within the manifest's declared
  bounds, `expression` quality rules on outputs, and `canonical:` links so metrics and
  `reconcile` can read a step output. Manifests reach the compiler as a frozen
  `StepRegistry` passed to `compile_project(..., steps=…)`: bloomery reads no step files
  and has no dynamic loading path, so a spec can never name code to load.
- Three tiers emit — `sql_macro` splices into the consuming SELECT, `sql_model` emits an
  ordinary model, and `python_model` emits one generated wrapper per declared output,
  each carrying a non-optional `assert_step_contract` call. Step outputs are entities:
  a mart may reference one exactly as it would any silver entity, and `plan()` diffs them.
- `bloomery.steps.assert_step_contract` — the run-time contract, and the only bloomery
  name intended for import outside compilation. It imports nothing but `bloomery.errors`.

**The gold layer and the emitters**

- Wide marts: relationship flattening with mandatory prefixes, role-playing date
  dimensions (`ordered_month`, `shipped_month`, …), a generated `dim_date` owned by the
  catalog, and aggregate `assert:` clauses lowering to target-native audits.
- Emit targets for **SQLMesh** (models, audits, native SCD2, reject/replay, quality
  audits), **dbt** (models through `ref()`/`source()`, sources, snapshots, schema tests,
  a self-contained expression-test macro) and **Cube** (cubes and views with additivity
  metadata, ratios as calculated measures), rendering over **DuckDB**, **Trino** and
  **PostgreSQL**. `register_emitter` adds extension targets. Where a target cannot express
  a declaration it raises `UnsupportedByTarget` rather than dropping it silently.

**Request-time planning**

- `MetricFlowPlanner`: a structured `MetricRequest` becomes SQL over a wide mart plus
  typed columns, warnings, a deterministic explanation and a fingerprint — refusing
  unknown members, cross-grain requests and ambiguous dimensions instead of guessing.
  MetricFlow is embedded and render-only, never connected to a database. Bind result rows
  by `ColumnDescriptor.sql_alias`; display `name`.
- Filters are typed CNF clauses (`Predicate` / `AnyOf` — implicit AND, one level of OR),
  with `RowPolicy` for row-level scoping and `parse_filter_json` / `parse_sort_json` /
  `parse_page_json` as the Mongo-flavoured JSON front door. Unsupported constructs raise
  `UnsupportedFilter` with a stable reason code from the closed, drift-guarded set
  exported as `bloomery.planner.KNOWN_UNSUPPORTED`.
- `LruManifestHydrator` / `HydrationKey`: in-process manifest hydration keyed by spec
  fingerprint and library versions, with an optional caller-owned byte store.

**Assessing and evolving a spec**

- `evaluate(project) -> SpecEvidence` — everything knowable about a spec without touching
  data, as one value: reachable metrics, unreachable ones with the missing leaf, batched
  refusals with source paths, mart shapes, entities, fingerprint. **Refusals are the
  return value**, and analysis that completed before the refusal comes back with them.
  `InvariantViolated` and every programming error still propagate.
- `plan()` — every change between two compiled versions classified as additive, widening,
  rename, restating or breaking, with backfill scope, replay scope for the reject tables a
  change invalidates, downstream metric impact and an enforced expand/contract workflow.
- Structured fix suggestions on five refusals: `UnknownMember.did_you_mean`,
  `UnreachableAtGrain.covering_marts`, `GrainViolation.offending_measures`,
  `UnknownStep.available_versions`, `UnsupportedFilter.nearest_supported`. Always present
  — `()` or `None` when there is nothing to suggest, never absent and never fabricated.

**Surfaces**

- A total error hierarchy rooted at `BloomeryError`: every failure is typed, carries a
  source path into the offending spec node, and is documented in the errors reference.
- **A command line** — `bloomery compile|plan|resolve|explain|schema|fingerprint`, plus
  `bloomery --version`. Each command is a thin argument shell over one public function;
  `--format json` emits the same values the Python API returns. A refusal exits `1` and a
  usage error `2`, so a pipeline can tell "your spec is wrong" from "your command is
  wrong". Nothing is executed: `bloomery run` does not exist.
- **JSON Schema per spec kind** — `spec_json_schema(kind)`, `all_spec_schemas()`, and
  `bloomery schema --out DIR`. Generated from the Pydantic models so they cannot drift
  from the parser, with every closed set enumerated. Also published at
  `https://morzecrew.github.io/bloomery/schemas/v1/<kind>.json`.
- `bloomery.__all__` is **closed over its own signatures**: every type named in a public
  signature is importable from the root, enforced by a test that walks the whole surface.
  `bloomery.__version__` reports the installed release.
- Documentation: get-started, concepts, how-to guides for every target and the planner,
  full spec/transform/error/API/stability references, and a runnable `examples/quickstart/`.

[Unreleased]: https://github.com/morzecrew/bloomery/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/morzecrew/bloomery/releases/tag/v0.1.0
