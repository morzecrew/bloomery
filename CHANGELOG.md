# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Planner filter vocabulary is now CNF (breaking, pre-0.1): `FilterExpr` becomes `Predicate`, filters accept one level of OR via `AnyOf` groups, `between` and `contains` are removed (compose `gte`+`lte`; write `like`/`ilike` patterns with your own wildcards), `is_null` takes exactly one bool, and `RowPolicy.as_filter()` is renamed `as_clause()`.

- Float filter values are now accepted and normalized to exact decimals at the request boundary instead of being refused; non-finite values (`NaN`/`Infinity`, in float or string form) are rejected with a typed `InvalidLiteral`.

- `Mapping.on_unmapped_enum` is retired (breaking, pre-0.1): a spec still carrying the key is now refused as an unknown key. Unmapped enum values become a data-quality concern — they fail the `in_enum` rule and take that rule's disposition (RFC 0016, superseding RFC 0008 D7's never-implemented emitter convention).

- `bloomery_ir_version` is now `2` — the IR gained the data-quality shape, so every artifact's `fingerprint:` header changes and `plan()` refuses to diff a v1 IR against a v2 one. No emitted SQL changed.

- Reserved field/dimension/role names now cover the generated data-quality and ingestion-metadata columns (`_quality_flags`, `_quality_ok`, `_load_id`, `_ingested_at`, `_source_row_id`, `has_quality_flags`) alongside `metric_time`; the refusal message names the RFC that owns each.

### Fixed

- Docs site root no longer 404s before the first release: the dev docs deploy
  now sets the gh-pages root redirect while no released version exists.

### Added

- Initial project scaffold: packaging, quality gate, CI, docs infrastructure (RFC 0001).

- Spec layer: strict YAML loaders (`load_project`, `load_catalog`) for the five spec kinds — Catalog, EntityModel, Mapping, MetricSet, MartSet — with unknown keys, duplicate keys, and grammar violations refused, and all parse failures batched with source paths.

- Total error hierarchy rooted at `BloomeryError`: every failure is typed, carries a source path into the offending spec, and batching stages report every problem in one round-trip.

- Deterministic intermediate representation with a `blm1:` content fingerprint (`build_project_ir`, `project_fingerprint`): same specs in, byte-identical artifacts out, across machines and hash seeds.

- Closed whitelist of 24 typed mapping transforms with a compile-time typecheck of every chain, decimal precision/scale tracking through arithmetic, and `register_transform` for vetted extensions.

- Resolution stage (`resolve`): cross-spec reference validation, recorded-recipe validation, cycle detection, and metric reachability with specific missing leaves.

- Fail-closed guardrails: unit, tax-basis, currency, grain, and additivity checks; mart fan-out and grain protection; `assert:` clauses lowered to target-native audits.

- Wide-mart gold layer: relationship flattening with mandatory prefixes, role-playing date dimensions (`ordered_month`, `shipped_month`, …), and a generated `dim_date` calendar owned by the catalog.

- Emit targets for SQLMesh (models, audits, native SCD2), dbt (models, sources, snapshots, schema tests), and Cube (cubes and views with additivity metadata, ratios as calculated measures), rendering over DuckDB, Trino, and Postgres dialects; `register_emitter` adds extension targets.

- Request-time metric planner (`MetricFlowPlanner`): a structured `MetricRequest` becomes SQL plus typed columns, warnings, a deterministic explanation, and a fingerprint — refusing unknown members, cross-grain requests, and ambiguous dimensions instead of guessing. Row-level scoping via `RowPolicy`.

- Manifest hydration for the planner (`LruManifestHydrator`, `HydrationKey`): an in-process LRU keyed by spec fingerprint and library versions, with an optional caller-owned byte store.

- Spec-diff planning (`plan`): every change between two compiled versions classified as additive, widening, rename, restating, or breaking, with backfill scope, downstream metric impact, and an enforced expand/contract workflow.

- Documentation site: get-started, concepts, how-to guides for every target and the planner, full spec/transform/error/API references, and a runnable `examples/quickstart/` project.

- JSON filter front door: `bloomery.planner.parse_filter_json` parses Mongo-flavoured filter documents into typed clauses, normalizing (De Morgan, complement inversion, capped CNF distribution) before refusing, with `parse_sort_json` and `parse_page_json` alongside.

- Closed refusal list for the query vocabulary: unsupported constructs raise a typed `UnsupportedFilter` with a stable reason code, and the complete set of raisable codes is exported as `bloomery.planner.KNOWN_UNSUPPORTED`.
