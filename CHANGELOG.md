# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Planner filter vocabulary is now CNF (breaking, pre-0.1): `FilterExpr` becomes `Predicate`, filters accept one level of OR via `AnyOf` groups, `between` and `contains` are removed (compose `gte`+`lte`; write `like`/`ilike` patterns with your own wildcards), `is_null` takes exactly one bool, and `RowPolicy.as_filter()` is renamed `as_clause()`.

- Float filter values are now accepted and normalized to exact decimals at the request boundary instead of being refused; non-finite values (`NaN`/`Infinity`, in float or string form) are rejected with a typed `InvalidLiteral`.

- `bloomery_ir_version` is now `2` — the IR gained the data-quality shape, so every artifact's `fingerprint:` header changes and `plan()` refuses to diff a v1 IR against a v2 one. No emitted SQL changed.

- Every silver model now projects `_quality_flags` and `_quality_ok`. An entity with no quality rules carries the empty collection and `TRUE`, so the change is two projections rather than a behaviour change — but it moves every silver golden, every dbt model, and every fingerprint. A mart whose base entity carries rules flattens the pair into a `has_quality_flags` dimension, so "revenue excluding flagged rows" is an ordinary `MetricRequest` filter.

- An entity that declares any `quality:`/`quarantine:` surface lowers its transform chains `TRY_CAST`-shaped: a failed coercion produces a marker the implicit `coercible` rule disposes of, instead of aborting the run. Entities with no quality surface keep the shipped produce-or-raise lowering, and the implicit `coercible` rule does not exist for them — joining the quality system is per entity and explicit (`dedupe:` alone does not opt in).

- Changing a quality rule, a disposition (in either direction, `referential`'s `on_missing` included, where `unknown_member` and `flag` are distinct changes although both keep the row), or a `dedupe` block classifies as `RESTATING`. `replay_scope` is reported rather than only a backfill where quarantined rows can actually come back — the rule removed, its disposition now `flag`, or its parameters relaxed (a widened bound, a widened `in_enum`/`in_set` membership, including an `enum_map` widened only by a new spelling for an existing target). A tightening — a narrowed bound, or `quarantine → fail` — backfills and does not replay: those rows sit in the reject table and still fail the rule.

- Reserved field/dimension/role names now cover the generated data-quality and ingestion-metadata columns (`_quality_flags`, `_quality_ok`, `_load_id`, `_ingested_at`, `_source_row_id`, `has_quality_flags`) alongside `metric_time`; the refusal message names the RFC that owns each. The quality mart's five metric names are reserved in the same way.

### Removed

- `Mapping.on_unmapped_enum` (breaking, pre-0.1): a spec still carrying the key is now refused as an unknown key. Unmapped enum values become a data-quality concern — they fail the `in_enum` rule and take that rule's disposition, superseding RFC 0008 D7's never-implemented emitter convention.

### Fixed

- The emitted quarantine-replay `MERGE` assigned to *qualified* target columns (`_target.col = …`), which DuckDB, Postgres and Trino all reject — the artifact could not run on any shipped dialect. The `SET` target is now the bare column standard SQL requires.

- The replay `MERGE` for an entity that declares `quarantine:` without `dedupe:` rendered an empty row comparison (`WHEN MATCHED AND () > ()`), i.e. invalid SQL. Without a dedupe block the total order degenerates to its final sort key, the stable `_source_row_id`, and the comparison stays total.

- Docs site root no longer 404s before the first release: the dev docs deploy
  now sets the gh-pages root redirect while no released version exists.

### Added

- Declarative data quality (RFC 0016): cleansing becomes spec surface. Mapping fields take a `quality:` list from a closed catalogue (`coercible`, `not_null`, `range`, `length`, `pattern`, `in_enum`, `in_set`, `unique`); entities take row rules (`expression`, `referential`), a `dedupe:` block, and a `quarantine:` policy; the entity model takes a document-level `reconcile:` list. Every rule carries an explicit `on_fail` — `flag`, `quarantine`, or `fail`, with deliberately no `drop` and no `repair` in v1 — and the pipeline order is fixed: extract → transform → dedupe → field rules → row rules → route.

- `pattern` rules speak a **portable regex subset** defined as an allowlist: literals, `.`, character classes, `\d`/`\w`/`\s` and their negations, the anchors `^`/`$`, the quantifiers `* + ? {n} {n,} {n,m}`, alternation, and non-capturing groups `(?:…)`. Everything else is refused at parse with the construct named — capturing groups, backreferences, atomic groups, possessive and lazy quantifiers, lookaround, named groups, inline flags, POSIX classes, `\A`/`\Z`/`\b`, and anything unrecognized. Patterns must be anchored by the author (`^[0-9]{5}$`, not `[0-9]{5}`, which would accept `abc12345xyz`), one pair per top-level alternative.

- `range` bounds are exact: an int, a decimal, or a string carrying one exactly — an exact decimal literal or an ISO date/timestamp. `"nan"`, `"inf"` and `"1e10"` are refused at parse; the first two compare open on some engines and closed on others, and the third renders as a float literal.

- Rules evaluate under a strict three-valued discipline: a rule fires only when its violation predicate is definitively TRUE, so a NULL-involved comparison never fires and a NULL foreign key is not an orphan. `not_null` and `coercible` are the only rules that own nulls.

- One replayable `<entity>__reject` table per entity, with a `reject_id` recomputable from the row itself, plus a replay artifact that re-runs the current mapping against the quarantined payload under the pipeline's own dedupe order — applied to the candidates against each other as well as against the incumbent, so two rejects resolving to one key produce one entity row — and re-stamps `failed_rules`/`last_seen` on the rows that still fail. A re-delivery lands on the same reject row and keeps its original `first_seen` while `last_seen` advances. bloomery emits the artifact and never executes it. `retention:` is required whenever anything can quarantine, and `redact:` strips JSONPaths at write time.

- SQLMesh emits the full set: the dedupe `QUALIFY` (rendered natively on DuckDB, as a `ROW_NUMBER` subquery elsewhere), the two-way entity/reject split, the reject model, a blocking audit on the bronze ingestion-metadata contract, a blocking audit per `on_fail: fail` rule — read over the rows the pipeline evaluated, so a row that quarantines *and* trips a blocking rule still stops the run — and the replay merge. dbt raises `UnsupportedByTarget` for the reject/replay artifacts and for `reconcile` — the honest port-proof scope. Cube consumes the quality mart like any other mart.

- `reconcile.on_fail` decides whether the check's audit blocks: `fail` stops the run — the pipeline-stopping gate RFC 0016 §5.3 nominates reconcile for — while `flag` reports and carries on so a disagreement never withholds the comparison table.

- A blocking `<entity>_conservation` audit per entity with a reject table: every bronze row lands in exactly one of the entity, an unresolved reject, or the deduped count, checked on every production run rather than only in the test suite. Skipped for the one shape an audit body cannot express — a routing predicate that reads a sibling entity (`referential` with `on_missing: quarantine`).

- `gold.mart_data_quality`, an ordinary mart carrying one row per rule evaluation plus one accounting row per entity (`rule = '(entity)'`), so every count is additive and quarantine rate is a plain `MetricRequest` groupable by entity or run month. `rows_failed` is the per-rule count; `rows_evaluated`, `rows_quarantined` and `rows_deduped` describe the entity's population and ride on its accounting row. Five reserved metrics come with it: `quality_rows_evaluated`, `quality_rows_failed`, `quality_rows_quarantined`, `quality_rows_deduped`, and the `quality_quarantine_rate` ratio. `run_id` is emitted declared-but-NULL — the pinned SQLMesh exposes no run-identifier macro — with a comment naming what the caller supplies.

- `Plan.replay_scope` (`ReplayScope`) alongside `backfill_scope`: the entities whose reject tables a spec change invalidates.

- Compile-time data-quality guardrails, batched into the same aggregate as everything else: `DedupeTieBreakMissing`, `DedupeDispositionConflict`, `QuarantineRetentionMissing`, `IngestionMetadataMissing` and `RedactionConflict`, plus bare refusals for a `pattern` regex the shipped dialect ports cannot express, `unknown_member` on a non-string or composite foreign key, a `referential` rule whose `via` names no relationship or names one declared from another entity (pointing back at its own entity included), a `dedupe` clause ordering by a column the entity does not declare, a malformed `reconcile` side, and a project metric colliding with a reserved quality-mart name.

- `DialectFeature.ARRAY` and `DialectFeature.TRY_CAST`. Dialects without arrays lower `_quality_flags` to a lexicographic comma-delimited string; Postgres has no NULL-on-failure cast, so compiling a `coercible`-carrying entity for it refuses loudly instead of silently degrading quarantine into an aborted run.

- Documentation: a "Data quality" concept page and an "Add quality rules" how-to guide, plus the full rule/dedupe/quarantine/reconcile schemas and the new refusals in the spec-schema, error, and API references.

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
