<!-- torve:managed src/bloomery/resolve — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/resolve/`

### S-0004/D-2 — `LOCKED` (Observability: logging and a warnings channel)

A log record never carries nondeterminism of bloomery's making — no timestamp, id or counter the compiler invented — and is built only from values the pipeline already holds: stage names, counts, fingerprints and source paths

- Paths: `src/bloomery/spec/project.py` `src/bloomery/resolve/build.py` `src/bloomery/compile.py` `src/bloomery/runtime/hydration.py` `src/bloomery/planner/metricflow_planner.py`
- Consequence: A record's timestamp exists only if the caller's handler adds one, on the caller's side of the I/O boundary; the pre-commit bans on the clock and the id generator get no exemption for a logging call site
- Check: `uv run pytest tests/unit/test_determinism_guard.py -q` (shadow; runs as `decision:S-0004/D-2`, no log entry owed)

### S-0004/D-4 — `ASSUMED` (Observability: logging and a warnings channel)

Two levels only, to start — `INFO` for one bounded record per stage per compile and `DEBUG` for per-entity and per-artifact detail — and no record at `WARNING` or above anywhere, because that severity belongs to the advisory channel

- Paths: `src/bloomery/spec/project.py` `src/bloomery/resolve/build.py` `src/bloomery/compile.py` `src/bloomery/runtime/hydration.py` `src/bloomery/planner/metricflow_planner.py`
- Consequence: The INFO budget is pinned not to grow with the project, which is what "safe to leave on in production" has to mean to be worth saying; a third level costs a log line rather than a contract, which is why this is not `LOCKED`
- Check: `uv run pytest tests/unit/test_logging_posture.py -q` (shadow; runs as `decision:S-0004/D-4`, no log entry owed)

### S-0004/D-13 — `ASSUMED` (Observability: logging and a warnings channel)

Modules obtain their stage logger by the documented name literally — `bloomery.spec`, `bloomery.resolve`, `bloomery.guardrails`, `bloomery.emit`, `bloomery.runtime`, `bloomery.planner` — and never through `getLogger(__name__)`

- Paths: `src/bloomery/spec/project.py` `src/bloomery/resolve/build.py` `src/bloomery/compile.py` `src/bloomery/runtime/hydration.py` `src/bloomery/planner/metricflow_planner.py`
- Consequence: The two idioms ship different stable sets, and `__name__` would make the documented names a strict subset of the real ones; tuning works either way through the hierarchy, so what differs is only which names are the promise
- Check: `uv run pytest tests/unit/test_logging_posture.py -q` (shadow; runs as `decision:S-0004/D-13`, no log entry owed)

### S-0008/D-7 — `OPEN` (Fuzzing the compile boundary)

Whether each of the two narrow-handler sites gains `RecursionError` or a depth limit raising a named error — decided per site from its reproduction, and logged either way

- Paths: `src/bloomery/evidence.py` `src/bloomery/resolve/steps.py`
- Consequence: A depth limit raising a named error adds a class to `src/bloomery/errors.py` and an entry to `pages/docs/reference/errors.md`; widening the catch adds neither, and the two sites may legitimately get different answers

### S-0019/D-4 — `ASSUMED` (Spec layer and error model)

Parse validates shape and grammar only; reference existence (entities, transforms, canonical fields) is deferred to resolve/typecheck. Consequence: a shape-valid spec with dangling references parses fine — callers must run `resolve` to trust it.

- Paths: `src/bloomery/marts/flatten.py` `src/bloomery/resolve/refs.py` `src/bloomery/spec/__init__.py` `src/bloomery/spec/entity.py` `src/bloomery/spec/mapping.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `tests/golden/schema/metrics.json` `tests/property/test_schema_agreement.py` `tests/unit/test_spec/test_entity.py`

### S-0019/D-6 — `ASSUMED` (Spec layer and error model)

Parse-stage errors are batched per document (all failures reported at once).

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/errors.py` `src/bloomery/evidence.py` `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/build.py` `src/bloomery/resolve/refs.py` `src/bloomery/spec/common.py` `src/bloomery/spec/project.py` `src/bloomery/typing/check.py` `tests/unit/test_cli.py` `tests/unit/test_evidence.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_refs.py` `tests/unit/test_spec/test_mapping.py` `tests/unit/test_spec/test_project.py` `tests/unit/test_spec/test_sql_text.py`

### S-0019/D-7 — `ASSUMED` (Spec layer and error model)

`materialization` is explicit-with-derived-default (settles original open question #4); the resolved value is IR-recorded and diffable.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/ir/nodes.py` `src/bloomery/marts/flatten.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/entity.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_entity.py`

### S-0020/D-2 — `ASSUMED` (Intermediate representation and determinism contract)

SQL is stored in the IR as canonical dialect-neutral SQLGlot text (`SqlExpr`), re-parsed at emit. Consequence: SQLGlot version changes can change fingerprints; the exact pin (D4 §5.5) makes that a deliberate event.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/emit/lower/marts.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `src/bloomery/transforms/_builtins.py` `tests/support/type_conformance.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_postgres.py` `tests/unit/test_transforms/test_builtins.py` `tests/unit/test_transforms/test_type_conformance_corpus.py`

### S-0020/D-4 — `ASSUMED` (Intermediate representation and determinism contract)

All IR collections are tuples with explicit lexicographic sort, except authored-order fields (`key`, transform chains, recipe aliases, `partition_by`).

- Paths: `src/bloomery/ir/lower.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/dedupe.py` `src/bloomery/quality/lower.py` `src/bloomery/resolve/build.py` `tests/unit/test_quality/test_dedupe_and_reject.py` `tests/unit/test_resolve/test_build.py`

### S-0020/D-5 — `ASSUMED` (Intermediate representation and determinism contract)

Floats are banned in IR and emission; `Decimal`/int only.

- Paths: `src/bloomery/cli/serialize.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/steps.py` `src/bloomery/ir/fingerprint.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/request.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/common.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `src/bloomery/steps/manifest.py` `src/bloomery/steps/splice.py` `src/bloomery/transforms/_builtins.py` `src/bloomery/typing/types.py` `tests/execution/test_as_of_join.py` `tests/execution/test_currency_convert.py` `tests/execution/test_fanout_trap.py` `tests/execution/test_marts.py` `tests/execution/test_period_over_period.py` `tests/execution/test_rollup.py` `tests/fixtures/semantic_corpus/002-average-of-averages/naive.sql` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/golden/schema/marts.json` `tests/support/planning.py` `tests/support/semantic_corpus.py` `tests/unit/test_cli.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_planner/test_request.py` `tests/unit/test_quality/test_edges.py` `tests/unit/test_spec/test_metrics.py` `tests/unit/test_spec/test_quality.py` `tests/unit/test_steps/test_lowering.py` `tests/unit/test_steps/test_manifest_and_registry.py` `tests/unit/test_typing/test_types.py`

### S-0022/D-1 — `ASSUMED` (Resolution: dependency DAG, recipes, reachability)

Resolution builds a single dependency DAG over source columns (JSONPath refs), mapped entity fields, catalog canonical fields + recipes, and metrics including `requires_metrics` metric-on-metric edges. One graph feeds reachability, cycles, topo order, and the guardrails (S-0023) — no parallel structures that can disagree.

- Paths: `src/bloomery/resolve/graph.py` `src/bloomery/resolve/reach.py`

### S-0022/D-2 — `ASSUMED` (Resolution: dependency DAG, recipes, reachability)

The compiler never chooses a recipe. The mapping's recorded `recipe:` id is validated — id exists on the catalog field, every `requires` name bound by the mapping's `from` aliases (exactly) — else `ResolutionError`. Choice happens upstream; the compiler reproduces it (determinism + auditability, spec §3.4). Consequence: catalog evolution can invalidate recorded choices, and that is a loud error, not a silent re-choice.

- Paths: `src/bloomery/evidence.py` `src/bloomery/guardrails/operands.py` `src/bloomery/resolve/recipes.py` `src/bloomery/resolve/resolution.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/mapping.py` `tests/golden/schema/catalog.json` `tests/golden/schema/mapping.json` `tests/unit/test_resolve/test_edge_shapes_offcorpus.py` `tests/unit/test_resolve/test_recipes.py`

### S-0022/D-3 — `ASSUMED` (Resolution: dependency DAG, recipes, reachability)

A canonical field is available iff some mapped field links to it via `canonical:` with a direct mapping or validated recipe. A metric is reachable iff every leaf of its `requires`/`requires_metrics` closure is available; unreachable metrics report the specific missing leaves and are stored in the IR (S-0020/D-6) as product-facing output.

- Paths: `src/bloomery/evidence.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/reach.py` `tests/unit/test_evidence.py` `tests/unit/test_unresolved.py`

### S-0022/D-4 — `ASSUMED` (Resolution: dependency DAG, recipes, reachability)

Any cycle in the DAG raises `CircularDerivation` (a `ResolutionError` subclass) naming the full cycle path, rotated to the lexicographically smallest node for stable messages.

- Paths: `src/bloomery/errors.py` `src/bloomery/resolve/order.py` `tests/unit/test_resolve/test_order.py`

### S-0022/D-5 — `ASSUMED` (Resolution: dependency DAG, recipes, reachability)

Emission order is a topological sort with ties broken lexicographically by node name — implemented once in resolve; all consumers take the order from `Resolution`. This is the package's main determinism hazard, contained here.

- Paths: `src/bloomery/resolve/order.py` `tests/unit/test_resolve/test_resolution.py`

### S-0022/D-6 — `ASSUMED` (Resolution: dependency DAG, recipes, reachability)

`Resolution` = reachable metrics, unreachable metrics + reasons, per-field provenance (`direct` | `recipe:<id>` | `tenant-native`), topo order — all tuples, explicitly sorted. `resolve(project, catalog)` is a pure function, no I/O, and public API.

- Paths: `src/bloomery/resolve/resolution.py` `tests/unit/test_resolve/test_resolution.py`

### S-0022/D-7 — `ASSUMED` (Resolution: dependency DAG, recipes, reachability)

All cross-spec reference validation lives here, not parse (S-0019/D-4): mapping targets, `canonical:` links, relationship endpoints, metric template refs. All failures are `ResolutionError`s with source paths, batched per stage; later checks run only on a reference-clean graph.

- Paths: `src/bloomery/errors.py` `src/bloomery/resolve/refs.py` `tests/unit/test_resolve/test_refs.py`

### S-0023/D-2 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Violations are batched project-wide: leaf errors (`UnitMismatch`, `TaxBasisMismatch`, `CurrencyMismatch`, `GrainMismatch`, `AdditivityViolation`, `AssertLoweringError`) are collected and raised as one `GuardrailError` aggregate, sorted by `(source_path, type)`. Matches S-0019/D-6.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/arithmetic.py` `src/bloomery/guardrails/quality.py` `src/bloomery/guardrails/stage.py` `src/bloomery/quality/reconcile.py` `src/bloomery/resolve/build.py` `src/bloomery/resolve/steps.py` `tests/fixtures/fanout_trap/metrics.yaml` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_guardrails/test_stage.py` `tests/unit/test_steps/test_lowering.py`

### S-0023/D-4 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Currency codes are checked only when both operands declare one; distinct declared codes require an explicit `convert` transform. Absent codes are compatible — opt-in, unlike tax basis, so single-currency tenants aren't trained to paste constants.

- Paths: `src/bloomery/guardrails/arithmetic.py` `src/bloomery/resolve/build.py` `tests/fixtures/semantic_corpus/004-currency-mix/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/004-currency-mix/problem.md` `tests/golden/refusals/example-mixed-currency.txt` `tests/unit/test_guardrails/test_arithmetic.py`

### S-0023/D-7 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Path conflict does not raise (`PathConflict` is not an error class): the compiler emits the derived column, a `<name>__direct` shadow, and a `RECONCILE` `AuditIR`. The forbidden thing is the silent choice; both paths are valid, so the refusal targets the silence, not the spec.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/quality.py` `src/bloomery/ir/lower.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/mapping.py` `tests/fixtures/path_conflict/entity_model.yaml` `tests/fixtures/path_conflict/mapping.yaml` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_ir/test_lower.py` `tests/unit/test_spec/test_mapping.py`

### S-0023/D-9 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

`check_guardrails(draft: ProjectIR) -> ProjectIR` is pure; its only amendment is path-conflict handling (shadow column + audit). All other guardrails are read-only checks.

- Paths: `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/build.py` `tests/property/test_guardrail_properties.py` `tests/unit/test_guardrails/test_stage.py`

### S-0023/D-10 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Mart-level fan-out guard runs at compile time (_bloomery-changes.md D2, S-0027): `GrainViolation` (a measure whose grain is coarser than the mart's grain listed in a finer-grain mart's `measures`) and `FanoutRisk` (a `flatten:` step whose `via:` relationship is not `many_to_one`/`one_to_one`) are `GuardrailError` leaves, batched like the rest. `fanout_trap` now fails at compile time; its execution assertion is kept because it documents why the compile error exists.

- Paths: `src/bloomery/guardrails/grain.py` `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/build.py` `tests/execution/test_as_of_join.py` `tests/execution/test_fanout_trap.py` `tests/fixtures/fanout_trap/marts.yaml` `tests/unit/test_guardrails/test_stage.py`

### S-0025/D-13 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

(Reverses D6) Bloomery owns the date dimension: one catalog definition emits both the SQLMesh `gold.dim_date` model and the MetricFlow time-spine declaration (S-0030 R1). D6's demand-gate is satisfied — MetricFlow is the demand.

- Paths: `src/bloomery/emit/lower/marts.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/metrics.py` `tests/execution/test_marts.py` `tests/fixtures/ecom_basic/catalog.yaml` `tests/golden/schema/catalog.json` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_fixtures.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_metrics.py`

### S-0027/D-6 — `ASSUMED` (Marts and role-playing dimensions)

Mart flattening is resolved at IR build (`bloomery/marts/`, pure): consumers see the wide schema, never the recipe. `ProjectIR.marts` is fingerprint-covered.

- Paths: `src/bloomery/marts/flatten.py` `src/bloomery/resolve/build.py` `tests/unit/test_evidence.py` `tests/unit/test_resolve/test_build.py`

### S-0027/D-9 — `ASSUMED` (Marts and role-playing dimensions)

(Amended for `_bloomery-metricflow-pivot.md`) Marts are the emission source for MetricFlow semantic models — one mart = exactly one semantic model (S-0030 R1); a measure-carrying mart must declare a date role (`MartMissingTimeDimension` otherwise). Marts and role-playing are *more* load-bearing after the pivot, not less.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/marts/flatten.py` `src/bloomery/quality/mart.py` `src/bloomery/resolve/graph.py` `tests/fixtures/ecom_basic/marts.yaml` `tests/fixtures/quality_precedence/entity_model.yaml` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_fixtures.py` `tests/unit/test_quality/test_mart.py` `tests/unit/test_resolve/test_graph.py`

### S-0033/D-6 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Entity-level `dedupe` requires `tie_break` under `keep: latest_by` (nondeterministic winners violate the core invariant); dedupe-referenced fields' `coercible` is forced to `fail`. Row rules `expression` and `referential` (`on_missing ∈ {unknown_member, quarantine, flag}` — `fail` deliberately excluded: orphans are an expected, recoverable data condition; a pipeline-stopping orphan gate is a `reconcile` check; `unknown_member` keeps aggregates correct via a reserved member row and requires a string-typed fk in v1 — the reserved member is the string `'__unknown__'`; a non-string fk with `unknown_member` is a compile-time `GuardrailError` naming the alternatives, typed per-key sentinels rejected); `reconcile` blocks emit model + non-blocking audit.

- Paths: `src/bloomery/errors.py` `src/bloomery/quality/catalogue.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/quality.py` `tests/unit/test_spec/test_quality.py`

### S-0033/D-10 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

One `<entity>__reject` table per entity with the §5.6 schema (stable sha256 `reject_id` for idempotent replay). Retention is **required** whenever any quarantine disposition exists — missing retention is a compile error; retention deletes **all** reject rows on expiry (unresolved measured from `last_seen`, resolved from `resolved_at`) and is the only deleter — replay never deletes. `redact:` paths apply at write time and must not intersect any path the entity's mappings read (`from` paths, recipe aliases included) — an intersecting redact is the compile error `RedactionConflict`. Bloomery emits the reject/replay artifacts and never executes them.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/errors.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `tests/engines/test_merged_cleaning_engines.py` `tests/fixtures/multi_source_quality/entity_model.yaml` `tests/unit/test_guardrails/test_quality.py`

### S-0033/D-21 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Ingestion metadata contract: entities using `quarantine` or `dedupe` require bronze `_load_id`, `_ingested_at`, `_source_row_id` (a stable per-source-row identity supplied by the ingestion layer, **NOT NULL and unique per source row** — data properties no compiler can check, so the lowering emits a generated **blocking audit** on the metadata columns: a null or duplicated `_source_row_id` stops the run); column absence is the new compile error `IngestionMetadataMissing` (`GuardrailError` leaf, `errors.py` per S-0019/D-3). `reject_id` = sha256 over the length-prefixed utf-8 **pair** (`source_relation`, `_source_row_id`) — canonical serialization per the S-0020 canon-bytes doctrine. This supersedes the triple this row first carried (this round's own earlier decision): `_load_id` is removed from the identity and becomes an attribute (the latest observing load) — re-deliveries of the same source row across loads must land on the **same** reject row (that is what `first_seen`/`last_seen` track); a per-load identity would mint a new row per retry and violate replay idempotence. A re-delivery updates `last_seen`/`_load_id`/`failed_rules` on the existing row.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/quality.py` `src/bloomery/quality/catalogue.py` `src/bloomery/quality/dedupe.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/transforms/_builtins.py` `tests/e2e/test_dbt_parse.py` `tests/e2e/test_sqlmesh_project.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_dedupe_and_audits.py` `tests/execution/test_merged_cleaning.py` `tests/execution/test_zoneless_utc.py` `tests/fixtures/dirty/README.md` `tests/fixtures/semi_additive_inventory/mapping.yaml` `tests/support/execution.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_trino.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_entity.py`

### S-0033/D-23 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

`_quality_flags` **and** `failed_rules` share one physical contract: rule names identifier-constrained at parse (no escaping in any lowering); the column is never NULL (empty array / empty delimited string per `DialectFeature.ARRAY`); delimited fallback joins with `,` in lexicographic rule-name order; `_quality_ok` generated per shape; flag-set equality across lowerings asserted in the dialect-matrix tier. The reject table's `failed_rules` lowers by exactly this contract — array where `DialectFeature.ARRAY`, else the lexicographic comma-delimited string.

- Paths: `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/spec/quality.py` `tests/engines/test_merged_cleaning_engines.py` `tests/unit/test_quality/test_flags.py` `tests/unit/test_spec/test_quality.py`

### S-0033/D-87 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **`repair` lands, its recipe is a registered `sql_macro`, and its marker is its own column. D17 is closed.** D17 gated the disposition on a repair-recipe contract and left §10 asking *inline vs catalog-referenced*. S-0034's step registry answers both at once: a recipe is `ref@version` into the registry — declared signature, `runtime_lock`, determinism tier, trust-then-verify — and D1 already holds that specs reference implementations and never contain them, so an inline recipe would have been a second, weaker copy of all of it reachable only from here. **The lowering.** The recipe is spliced at IR build, where the registry lives, and travels as SQL in the rule's params the way an `expression` rule's body does — so emission needs no registry, and a version or `runtime_lock` bump lands in the IR where the fingerprint and `plan()` see it (measured: a body change classifies RESTATING and puts the entity in `replay_scope`, because the kind's params define neither an ordered interval nor a membership set and D52's undecidable-means-replay applies). The rewrite happens at the **extract** level, inside the column's own projection: `CASE WHEN <violation over the raw expression> THEN <recipe> ELSE <raw> END`. That placement is what makes every other rule see the repaired value with no extra nesting, and it forces both halves to be rewritten to read the column's expression rather than its name, since the column is being defined in the same `SELECT`. **The marker.** `_quality_repairs` is a separate column, which was cubic's condition in review and is the right one: a rule is recorded there when its recipe *ran and worked* — it fired over the value as delivered and no longer fires over the value that replaced it. `_quality_flags` stays empty for a repaired row, so `has_quality_flags` keeps meaning **currently suspect** and no mart already asking that question changes its answer. Unlike the two universal columns it is emitted only where a repair rule exists: §12 budgeted the silver-schema churn once, and a third column empty for every project not using the feature is not worth re-opening every golden and fingerprint for. **`fallback` is required**, for the same reason `on_fail` is (D2): a recipe that ran and failed leaves the rule violated and the row is disposed of exactly as if no repair had been declared — the alternative, a still-broken value landing in silver marked as fixed, is the `drop` this RFC refuses wearing a friendlier name. **Refusals**, each a property of the declaration alone: `repair` on `coercible` (it fires *because* the projection is already NULL, so the recipe would be handed the NULL rather than the text that failed to cast — fixing a value before coercion is a Tier 1 macro in the mapping, and the message says so), on `unique` (a property of a population; no rewrite of one row makes a duplicate unique), on a row rule (no column to rewrite), two repair rules on one column (both rewrite the same projection, so which value survives would depend on authoring order and the second recipe would judge a value the first had changed), a recipe accepting more than one column (a rule has no `from:` map, and inventing one would make a rule a second mapping surface), and a column the dedupe order reads (dedupe runs *before* the field rules per D7, so the winner would be chosen on the value as delivered and then have that value rewritten underneath it — D6's reasoning exactly). Verified by executing the emitted pipeline over three rows — one the recipe fixes, one it cannot, one it must not touch — and by sabotage: disabling the recipe, and dropping the "did it run" conjunct from the marker, each fail the assertion that names them. **Not built:** `gold.mart_data_quality` gains no `rows_repaired`, so repairs are observable in silver and not in the quality mart. Recorded rather than implied — adding a measure changes the mart schema, and no demand has asked for it.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/lower.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/spec/quality.py` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/golden/schema/steps.json` `tests/unit/test_spec/test_quality.py`

### S-0033/D-95 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-12)* **An `expression` rule is a predicate over the entity's own columns — enforced, not merely documented.** `ExpressionRule.expr` was a bare string, parsed and spliced into the silver model with nothing checking it: the one authored-SQL surface in the framework with no resolution step, while every neighbour has one (`dedupe` columns D47, `reconcile` sides against a closed grammar, mart `assert` measures, recipe aliases exactly, `coverage` endpoints D91). Three refusals, each closing something **measured** rather than imagined. **A subquery**, and the reason is corruption at least as much as access: the qualifier pass that binds a bare column to the extract descends *into* a subquery, so `amt > (SELECT amt FROM other)` was emitted as `_extract.amt > (SELECT _extract.amt FROM other)` — correlated to the outer row, reading nothing from `other`. Executed on DuckDB with `amt` 10 against 1: the author's predicate is true so the rule must not fire, and it fired, flagging a good row — under `quarantine` that diverts it out of silver, which is data loss from a rule that reads correctly in the spec. A row predicate needs no subquery, and one that did could not be trusted to mean what it says; a comparison against another relation is what `reconcile:` is for. **A column the entity does not declare** — D47's own words, "a run-time binder failure on a model that compiled clean". **A qualified reference**, because the extract supplies the qualifier and a written one either names a relation the rule cannot read or shadows bloomery's. **Left open, deliberately:** the function vocabulary. `amt > pg_sleep(10)` still compiles, and narrowing that means giving expression rules a closed function list the way S-0021 gives transform chains one — a design decision about the surface, not a defect anything here demonstrated. Recorded rather than quietly widened, because the difference between "measured and fixed" and "seemed unsafe so I restricted it" is the difference this corpus is written to preserve.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `tests/unit/test_spec/test_sql_text.py`

### S-0034/D-8 — `ASSUMED` (The step registry: referenced implementations)

Emission: `sql_macro` splices into the entity SELECT (one query); `sql_model` emits an ordinary model artifact from the registry body; `python_model` emits a generated SQLMesh Python-model `.py` artifact (S-0025/D-2 file-shaped) wrapping the impl + contract assertion. Step outputs are DAG entities with manifest grain; two steps writing one output is a compile error (settles Document 5 §11.5).

- Paths: `src/bloomery/emit/steps.py` `src/bloomery/resolve/steps.py` `tests/unit/test_steps/test_emission.py` `tests/unit/test_steps/test_lowering.py`

### S-0034/D-11 — `ASSUMED` (The step registry: referenced implementations)

Steps are IR and DAG citizens: `StepIR` nodes (ref, version, kind, determinism, `runtime_lock`, typed inputs/outputs) in a new `ProjectIR.steps` tuple (S-0020 amendment) and first-class `step.<ref>` DAG nodes (S-0022 amendment). Fingerprint coverage is the whole mechanism: any manifest change — `runtime_lock` included — shifts `project_fingerprint`; `plan()` sees an ordinary structural IR diff (no special-casing); the S-0031 hydration cache self-invalidates via `HydrationKey.spec_fingerprint`, no new key component.

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/resolve/graph.py` `tests/unit/test_plan/test_step_changes.py` `tests/unit/test_resolve/test_graph.py`

### S-0034/D-16 — `ASSUMED` (The step registry: referenced implementations)

Multi-output emission resolved — **supersedes the draft §10 entry and its execute-exactly-once constraint** (recorded honestly: that constraint is dropped, not satisfied): each declared output gets its own generated wrapper model, each executing the step and returning its own output; safe **for correctly declared steps** — nondeterministic steps are compile-refused and seeded steps re-execute with the same recorded seed (pure/seeded ⇒ identical results); residual risk recorded: a *misdeclared* step slips the compile check and, under N executions, can produce disagreeing sibling outputs within one run (behavioral gates catch run-to-run, not intra-run, divergence) — accepted for v1, with a cross-output consistency audit named as the demand-gated mitigation. `assert_step_contract` runs in every wrapper against **all** declared outputs, catching partial-output lies wherever the run starts. The N-executions-for-N-outputs cost is documented; a single-execution staging optimization is a demand-gated, named escape hatch — not built.

- Paths: `src/bloomery/emit/steps.py` `src/bloomery/resolve/steps.py` `src/bloomery/steps/manifest.py` `tests/execution/test_step_consistency.py` `tests/golden/test_sqlmesh_duckdb.py` `tests/unit/test_steps/test_emission.py`

### S-0034/D-49 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-09)* **D41 is built: metrics and `reconcile` reach step outputs, through a declared canonical link.** What was missing was a *surface*, not a mechanism. A metric is reachable iff every leaf of its `requires` closure is **available**, and a canonical field is available iff something draws a `canonical` edge to it — which only mapped entity fields could. So a step's columns were never available and any metric over one was unreachable, for a reason narrower than D41's own wording ("metric resolution keys on mappings") suggested. `StepWiring` gains `canonical: {<output>: {<column>: <canonical_field>}}`. On the **wiring**, not in the manifest: canonical names are the authored spec's vocabulary, and a manifest naming them could not be reused by a second project spelling them differently — the fork §5.7 exists to refuse. Never inferred from a matching column name, which is D43's argument about references applied to the same temptation. Nothing about metric resolution changed: the link draws the ordinary `canonical` edge and reachability follows. `reconcile` needed a second, unrelated repair — it resolved sides against *declared and mapped* entities, and a step output is neither, so a check naming one was refused as "declared but no mapping targets it", which is true and useless since the step writes the relation. Both kinds now answer through one `_SideEntity` view (field names and key), so the check asks what it needs rather than branching on provenance; declared-but-unmapped stays refused, which was always the real point. The refusal's wording now names both ways a relation can exist.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/resolve/graph.py` `src/bloomery/resolve/refs.py` `src/bloomery/spec/steps.py` `tests/fixtures/identity_resolution/catalog.yaml` `tests/fixtures/identity_resolution/steps.yaml` `tests/unit/test_quality/test_reconcile.py` `tests/unit/test_steps/test_step_canonicals.py` `tests/unit/test_unresolved.py`

### S-0034/D-50 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-09)* **Tier 1 has a spec surface: a mapping references a macro, in two shapes.** D26 refused a wired `sql_macro` because none existed, so the docs described a splice that could not happen. A field mapping gains a third shape beside `from:` and `recipe:` — `step: ref@version` with `from:` binding the columns it consumes — and a transform chain gains a `{step: ref@version}` link, so Tier 0 and Tier 1 compose on one field (the field shape binds a *raw* source path, so without the link no whitelist transform can run before the macro). A macro is referenced **inline**, never wired in `steps:`: it writes no relation, so it has no output to bind there, and one wiring per ref (D13) would make a macro usable in exactly one mapping with one parameter set — the pressure that produces `fuzzy_score_strict`, which is the fork §5.7 exists to refuse. Parameters are therefore supplied at the call site. The splice happens at **lowering**, so the macro is part of `ColumnIR.expr`, the model stays one query, and lineage sees through it — which moved `macro_expression` from `emit.steps` down to `bloomery.steps.splice` (emit sits *above* resolve, so the emitter could not own a splice the lowering needs), taking `parameter_literal` with it now both SQL tiers need the same typed literal. Consequence found by the type gate rather than by reading: the field-mapping union grew a third member, and five sites assumed two — a macro binds aliases like a recipe and has no chain, so they test an `ALIAS_BOUND` pair.

- Paths: `src/bloomery/resolve/build.py` `src/bloomery/resolve/graph.py` `src/bloomery/resolve/resolution.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/mapping.py` `src/bloomery/spec/quality.py` `src/bloomery/steps/splice.py` `tests/unit/test_resolve/test_edge_shapes_offcorpus.py` `tests/unit/test_steps/test_splice.py`

### S-0034/D-51 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-09)* **A macro declares its signature; it is never read off its body.** The first cut inferred the signature from the body's `:name` placeholders. That is the third appearance of one temptation, and it is refused for the third time — D43 refused fabricating references from matching key columns, D49 refused auto-linking canonical fields by name. The deciding argument is the ladder itself: Tier 0's `TransformSpec` declares `input_domain` **and** `output_type`, so a macro declaring neither would be the one tier whose inputs nothing checks, while §5.1's table claims Tier 1 can *parse and typecheck*. `StepManifest` gains `accepts: {column: type}` — a separate key from `inputs:`, which is relation-shaped for table steps, because one key meaning two things by kind reads fine only to whoever wrote it. The output type needs no new field: a macro has exactly one output of exactly one column (D18b). This buys three things. The **body** is checked against the declaration once, at the registry, where a disagreement is the platform's bug rather than a puzzle handed to every call site. The **call site** is checked against the declaration, so the message names what the macro expects instead of only which placeholder was unfilled. And a **chain** is typechecked *around* the link: the run before it against what it accepts, the run after it from what it produces — implemented as segments queued into the ordinary batch stage, so S-0023/D-2's one-aggregate property survives for chains containing a macro. Named cost, recorded rather than discovered: a genuinely polymorphic macro (`COALESCE(:a, :b)` over any type) must now pick a concrete type. Tier 0 carries the identical constraint through `input_domain`, so it is consistent rather than a new tax — but it is a real limit. A chain link must accept exactly one column, since a chain carries one running value; a two-column macro is refused there and pointed at the field shape.

- Paths: `src/bloomery/resolve/build.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/mapping.py` `tests/golden/schema/mapping.json` `tests/property/test_schema_agreement.py` `tests/unit/test_resolve/test_declared_zone.py` `tests/unit/test_schema.py`

### S-0034/D-54 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-11)* **A chain link whose macro declares an undefaulted parameter is refused.** The `{step: ref@v}` chain form is a bare reference with nowhere to pass values, unlike the `step:`/`from:` field shape and its `parameters:` map — so `_splice_link` passes `{}`, `_macro_parameters` omits every parameter without a default, and `splice` leaves those `:name` placeholders alone. The result reached emitted SQL as a live placeholder (`CAST(nm AS TEXT)

- Paths: `src/bloomery/resolve/build.py` `tests/unit/test_steps/test_macro_fields.py`

### S-0035/D-10 — `ASSUMED` (Public surface and stability policy)

**The `TYPE_CHECKING` guard is lifted on public signatures before the closure test lands.** `typing.get_type_hints` currently raises `NameError` on 7 of the 29 exports, including `compile_project`, because `from __future__ import annotations` plus a `TYPE_CHECKING`-only import leaves the annotation naming something absent at run time. Decision 1's enforcement is unimplementable until those names are importable at run time — a prerequisite the design did not see, found by running the proposed walk rather than by reading it. Guards on internal signatures are untouched.

- Paths: `src/bloomery/evidence.py` `src/bloomery/resolve/facets.py` `src/bloomery/resolve/lineage.py` `src/bloomery/resolve/timeline.py` `src/bloomery/schema.py` `tests/unit/test_signature_closure.py`

### S-0039/D-3 — `ASSUMED` (`SpecEvidence`: spec analysis as a first-class output)

**Partial analysis is the point**: the pipeline runs to the first refusing stage and reports the prefix. "Seven metrics reachable, two blocked on `cogs`, one refusal at `mappings/crm.yaml`" is unavailable today at any price, and is the most useful sentence bloomery can produce about a spec it will not compile. This is the only new behaviour in the RFC, and the pipeline already supports it — stages are already sequential and already batch.

- Paths: `src/bloomery/evidence.py` `src/bloomery/resolve/build.py` `tests/unit/test_evidence.py` `tests/unit/test_semantic/test_ratio_rows.py`

### S-0039/D-5 — `ASSUMED` (`SpecEvidence`: spec analysis as a first-class output)

**`stage_reached` is mandatory to read**, stated first in the docstring and tested on the ambiguous case: an empty `unreachable` means "nothing unreachable" only at `COMPLETE`, and means "never computed" at `PARSE`. Without it the empty tuple is ambiguous in exactly the way that produces a wrong conclusion.

- Paths: `src/bloomery/cli/render.py` `src/bloomery/resolve/build.py` `tests/unit/test_cli.py` `tests/unit/test_resolve/test_lineage.py`

### S-0040/D-4 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

`convert` raises `UnsupportedByTarget` at **emit**, on all three dialects. It stays a registered transform with an unchanged typecheck, so the spec surface does not move and a future dialect clears the refusal by declaring a `Feature` — the mechanism S-0025 already provides.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/evidence.py` `src/bloomery/resolve/build.py` `src/bloomery/transforms/_builtins.py` `tests/fixtures/currency_convert_refusal/entity_model.yaml` `tests/support/type_conformance.py` `tests/unit/test_emit/test_currency_convert.py` `tests/unit/test_evidence.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-1 — `LOCKED` (Deterministic union merge)

Several mappings may target one entity; they are merged with `UNION ALL`. This replaces the refusal at `resolve/build.py:849` and keeps the promise its message makes. Consequence: `EntityIR` gains a set of source mappings where it had one, and every consumer reading "the mapping" of an entity must be revisited.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `tests/unit/test_resolve/test_build.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-4 — `LOCKED` (Deterministic union merge)

Every mapping must produce the entity's **full declared key** and **every required field**. A partial key makes the union meaningless; a NULL-filled required field is a broken contract silently created by the merge.

- Paths: `src/bloomery/resolve/build.py` `tests/unit/test_resolve/test_build.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-12 — `LOCKED` (Deterministic union merge)

`(target, source)` is **unique**: two mappings for one entity may not read the same source relation. Lexicographic ordering needs a total order and two branches on one relation tie, which would leave branch order undefined, `_source` ambiguous, and the collision audit unable to name a branch. Consequence: reading one relation twice is expressed as one mapping with a filter, not two mappings.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/resolve/build.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_resolve/test_build.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-18 — `LOCKED` (Deterministic union merge)

**`_source` joins `RESERVED_MEMBER_NAMES`.** Every other generated column is reserved — `_quality_flags`, `_quality_ok`, `_load_id`, `_ingested_at`, `_source_row_id`, `has_quality_flags` — and a generated column that is not is one an author can collide with. Reserved unconditionally, not only on merged entities: a name that is legal until a second mapping arrives is a trap laid for the change that adds one.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/common.py` `tests/unit/test_spec/test_entity.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-21 — `LOCKED` (Deterministic union merge)

**A merged entity may not mix a mapped source with a step-produced output**, refused explicitly rather than left to fail somewhere downstream. §8 already puts it out of scope; this is the refusal that makes the scope real, since a step output entity carries `produced_by` and no mapping at all, and the union has nothing to order it by.

- Paths: `src/bloomery/resolve/steps.py` `tests/unit/test_steps/test_lowering.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-23 — `ASSUMED` (Deterministic union merge)

**Answers D10 (`OPEN`) — `scd: type2` plus multi-source is refused.** The expected answer, and D14 makes it cheap: the collision audit would fire on every key holding versions from two sources, and distinguishing a version from a collision needs the validity columns S-0040/phase-2-the-as-of-join proposes and does not build. Refused with a message naming that dependency, so the refusal routes rather than merely blocks.

- Paths: `src/bloomery/resolve/build.py` `tests/unit/test_resolve/test_build.py`

### S-0041/D-26 — `ASSUMED` (Deterministic union merge)

**Answers D25 (`OPEN`) — option (a), and D25's blast-radius figure was wrong by an order of magnitude.** The lowered expression moves to a new column-grained `SourceColumnIR` on `SourceIR`; `ColumnIR` keeps the schema (§5.7). D25 said "37 `.columns` read sites" and estimated the cost from that; measured, **exactly 8 sites read a `ColumnIR` lowering field, in 3 files** — `plan/diff.py` (`renamed_from` ×4, `recipe_id`, `expr.sql`) and `emit/lower/silver.py` (`expr.ast()` ×2). Four of those eight are `renamed_from`, which D25 mis-assigned to the lowering half and which is declared on the EntityModel `Field`, so it does not move at all. The 37 was a count of `.columns` readers, and `.columns` readers are overwhelmingly *schema* readers — they survive untouched, which is the whole point of the split. **Real cost: two constructors where there was one, and four call sites.** The golden churn stands regardless — the IR shape moves and D17 bumps the version.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/operands.py` `src/bloomery/guardrails/stage.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/resolve/build.py` `src/bloomery/resolve/facets.py` `src/bloomery/resolve/steps.py` `src/bloomery/resolve/timeline.py` `tests/bench/test_hydration.py` `tests/support/ir_factory.py` `tests/support/plan_ir.py` `tests/unit/test_emit/test_cube.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_facets.py` `tests/unit/test_unresolved.py`

### S-0041/D-32 — `LOCKED` (Deterministic union merge)

**A rule's per-mapping dependency is projected as a branch-local column; the rule stays entity-grained (P2a).** The mechanism is not invented here — `coercible` already reads projected `_src_<rule>_<n>` aliases (`quality/predicates.py:source_alias`) rather than inline JSONPaths, because the raw paths live one level down in the extract SELECT, and P1 turned that projection site into `_branch_select`. So a fact only one branch knows already has a way to reach a rule the merged relation evaluates once. **D6 is not violated, and the reading that says it is — that projecting a verdict per branch just *is* "a rule evaluated per source" — mistakes what D6 argues.** D6 argues from the *row population* — "a rule evaluated per source would judge rows the merged relation does not contain" — and the union is `ALL`, so a branch-projected **scalar** verdict judges exactly the rows the union contains. Dedupe runs after the union and may drop a row; that row's flag is then unused, which is not a wrong answer. **The boundary is `WINDOWED_KINDS`** (`quality/predicates.py`, currently `{unique}`): a windowed verdict depends on the population and so may not be computed per branch — and it does not need to be, since its inputs are the produced column values, which D26's split already makes mapping-invariant. Consequence: `coercible` sheds its per-source alias set for one branch-computed boolean ("every source path *this branch* read was non-null"), which collapses the arity problem at the level where arity is known; `in_enum` takes the same shape rather than a second mechanism, its admissible set being the branch's own `enum_map` chain. **The tempting wrong fix is recorded so it is not re-proposed:** NULL-filling a missing `_src_` alias to make the arities agree renders `is_not_null` false, the conjunction never fires, and the rule silently stops checking on that branch — the failure D28 refuses by name, a check that quietly stops checking being worse than one that is absent.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/guardrails/quality.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/quality/lower.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/build.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_merged_cleaning.py` `tests/fixtures/multi_source_quality/mapping_legacy.yaml` `tests/support/quality_rules.py` `tests/unit/test_quality/test_lower.py` `tests/unit/test_quality/test_predicates.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-33 — `LOCKED` (Deterministic union merge)

**Every mapping of an entity opts into the quality system, or none does; disagreement is refused (P2a).** `opts_in(entity, mapping)` is a disjunction over one mapping's field-level `quality:` blocks, so two mappings can disagree about whether the entity joined the system at all — and the same predicate selects `_try_cast_shape`, so the disagreement reaches column lowering and not only rule generation. This is not the "where is it computed" question D32 answers; it is two contradictory statements by an author, and the honest response to those is a refusal naming both source paths. It also settles a **fourth** per-mapping coupling D29 did not enumerate: `_repair_bodies` (`resolve/build.py`) reads `mapping.fields[<column>].quality[].repair`, so two mappings may name different repair recipes for one column. Under agreement that is the same refusal rather than a fifth case — and the spliced body itself is invariant, since it reads the *produced* column, not a source path. Consequence: `lower_quality` may go on taking one `Mapping`. Agreement is what makes any of them the same answer, and the refusal — not a merge rule — is what makes that safe.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/resolve/build.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_resolve/test_build.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-36 — `ASSUMED` (Deterministic union merge)

**Answers D28 — `direct:` is allowed on a merged entity when *every* mapping records one for the column, and refused when they disagree.** D28 refused the combination outright and handed P2 a choice between "one shadow projection per source with a null-safe audit" and "a coverage rule in D4's shape". Measured with the refusal disabled against two mappings that *agree*, the null-safe audit is answering the wrong question: the shadow column is duplicated on the entity **and on every branch**, the reconcile audit is emitted twice, and each branch carries the other's extraction — `shop__items` projecting `$.unit_price` off a relation that does not have it. That is not a NULL-shadow problem, it is `Derivation` being built per mapping while `_shadow` returns one projection: the same per-mapping-fact-on-a-shared-node shape D26 split for `expr` and D32 for the rule inputs. So the coverage rule is the answer and the null-safe audit is unnecessary under it — under agreement no branch's shadow is NULL for want of a path, and the reconcile check keeps the meaning it has on one source: the recipe-derived value against the direct value *that row's own mapping* extracted, which is D32's principle applied to a second reader. Consequence: `Derivation` carries its source relation, `path_conflict_amendments` fans out per source like every other lowering, and disagreement is refused by D33's pattern rather than tolerated. D28's row stands unamended — its refusal is correct until this one is executed, and what it predicted is the thing this has to be read against. *Added by execution 2026-09-03 — see logs/T-0012.md (F-8), which carries the probe output.*

- Paths: `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/build.py` `tests/execution/test_path_conflict.py` `tests/fixtures/path_conflict_merged/entity_model.yaml` `tests/fixtures/path_conflict_merged/mapping_legacy.yaml` `tests/golden/test_sqlmesh_duckdb.py` `tests/unit/test_fixtures.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_resolution.py`

### S-0046/D-1 — `ASSUMED` (Transform types the engine agrees with)

A builder is told its **input logical type**. `Builder` becomes `(input type, column AST, *args) -> AST` or gains it by keyword; the declaration and the construction then read the same fact. This is the enabling change for §2.1 and §2.2.

- Paths: `src/bloomery/resolve/build.py` `src/bloomery/transforms/registry.py` `tests/support/type_conformance.py` `tests/unit/test_transforms/test_registry.py`

### S-0048/D-2 — `LOCKED` (Lineage)

**`Graph`, `Edge`, `Lineage` and `Direction` join `bloomery.__all__`, and `Resolution` gains `graph` with no default.** A traversal returning a sub-DAG is unusable if its return type is private, and `Node`/`NodeKind` are already public — the surface is being completed. No default on the field because a `Resolution` without its graph is not a state this design wants representable. Consequence: both types are bound by `stability.md`'s SemVer rule from this point, and hand-constructed `Resolution`s in tests break loudly rather than silently carrying an empty graph.

- Paths: `src/bloomery/resolve/resolution.py` `tests/unit/test_resolve/test_graph.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0048/D-6 — `ASSUMED` (Lineage)

**The edge-label vocabulary is closed at eight labels and nine `(label, src kind, dst kind)` triples, read off the builders and pinned by a test keyed on the triple.** The first draft of §5.3 was compiled from the 22 fixtures, and that method cost two entries: `_step_edges` emits `step_input` at three sites and the corpus reaches one, so both `step → step` forms were missing; and `_mapping_edges` labels a Tier 1 `sql_macro` field `step:<ref@version>`, which no fixture declares, so the label itself was missing. Consequence: the corpus is a witness to this table, never its source, and a guard keyed on the label alone is specifically the one that cannot catch a new shape of a label it already knows. Depart if a label turns out to be constructed dynamically anywhere, which would make the closed set a lie rather than a contract.

- Paths: `src/bloomery/resolve/graph.py` `tests/unit/test_resolve/test_edge_vocabulary.py` `tests/unit/test_resolve/test_lineage.py`

### S-0049/D-1 — `LOCKED` (Mapping identity)

**The identity is the document name.** It is unique by construction (a key of the `sources` mapping), already computed, already the ordering key for `Project.mappings`, and already the user-facing coordinate for refusals (S-0019/source-paths). Consequence: identity is a filename, so a rename changes it — accepted under D4's boundary.

- Paths: `src/bloomery/evidence.py` `src/bloomery/resolve/resolution.py` `src/bloomery/spec/common.py` `src/bloomery/spec/mapping.py` `tests/property/test_schema_agreement.py` `tests/unit/test_resolve/test_resolution.py` `tests/unit/test_spec/test_mapping.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0049/D-7 — `OPEN` (Mapping identity)

**Whether `FieldProvenance` sorts by `(entity, field, mapping)` or `(entity, mapping, field)`.** §5.4 argues the first — a field's answers stay adjacent — but the second groups a reader's attention by document, which is what they will edit. Execution decides against the corpus, and logs it: whichever reads better on `multi_source`'s four collapsed facts is the answer, and that is a thing to look at rather than reason about.

- Paths: `src/bloomery/resolve/resolution.py` `tests/unit/test_resolve/test_resolution.py`

### S-0049/D-11 — `LOCKED` (Mapping identity)

**`FieldProvenance.mapping` is keyword-only, and D5's rationale for placing it third was wrong.** D5 argued that a positional caller would fail on arity; `recipe_id` carries a default, so the old four-argument call `FieldProvenance(entity, field, provenance, recipe_id)` still satisfies arity and binds `provenance` into `mapping` — the silent rebinding the placement was chosen to prevent, reproduced rather than reasoned about. `kw_only=True` restores the loud failure and keeps the reading order D5 wanted. Consequence: the field's *position* is now a reading convenience only, and nothing rests on it. *Added by execution 2026-08-31 — see logs/T-0008.md (R-1).*

- Paths: `src/bloomery/resolve/resolution.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-1 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A derived metric is `expr` over aliased inputs, each input a metric.** `inputs` is a mapping keyed by alias, not a list: the alias is the input's identity because `expr` references it, and a dict makes a duplicate alias unrepresentable rather than a validation. Consequence: `MetricIR` gains a `derived` field and the additivity guard must accept it as a decomposition.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/resolve/build.py` `src/bloomery/semantic/plan.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-3 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**Derived inputs are unioned into `requires_metrics` by the template merge, never written twice by the author.** The DAG, reachability, cycle detection and `depends_on` then need no change at all. The reference checker reads the spec model before the merge and validates the inputs there; both callers use one helper on the spec model, so the set of metrics a derived metric depends on has exactly one definition.

- Paths: `src/bloomery/resolve/metrics.py` `src/bloomery/resolve/refs.py` `src/bloomery/spec/metrics.py` `tests/unit/test_resolve/test_metrics.py` `tests/unit/test_resolve/test_refs.py` `tests/unit/test_spec/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0059/D-6 — `LOCKED` (Loose ends inside shipped subsystems)

The node-id collision is **refused**, not re-spelled. `Node.name` and the `lineage --node` argument are published surface, and the resolve API is not covered by the emitted-artifact stability caveat. Locks the bare `<entity>.<field>` spelling in: changing it later is a breaking change to every stored lineage id, which is exactly what this row buys.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/lineage.py` `src/bloomery/resolve/graph.py` `src/bloomery/resolve/timeline.py` `tests/unit/test_guardrails/test_lineage.py` `tests/unit/test_resolve/test_graph.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0059/D-9 — `LOCKED` (Loose ends inside shipped subsystems)

`on_fail: flag` lowers for `sql_model` outputs only, through `_quality_pipeline` — the same function the silver lowering calls, never a second copy of the projection.

- Paths: `src/bloomery/resolve/steps.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0059/D-10 — `LOCKED` (Loose ends inside shipped subsystems)

`on_fail: quarantine` on a step output is **refused permanently**, and the message names both blockers: no ingestion-metadata key for the reject table, and no `quarantine:` retention surface in a `steps:` wiring. Not "pending".

- Paths: `src/bloomery/resolve/steps.py` `tests/unit/test_steps/test_lowering.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0063/D-2 — `LOCKED` (Exposures and downstream consumers)

An exposure naming an undeclared metric or mart is refused. An exposure pointing at nothing reports clean, which is the failure mode the feature exists to remove.

- Paths: `pages/docs/how-to/declare-an-exposure.md` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/exposures.py` `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/graph.py` `tests/unit/test_guardrails/test_exposures.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0065/D-10 — `ASSUMED` (Rollup marts and pre-aggregations)

**Rollups do not chain**: `rollup_of:` names a mart that is not itself a rollup, and a chain is refused — §10's second question. The obligation composes; its *premise* does not. Row 12 rests the grain half on R008, a measure embedded in a mart at that mart's grain, and a rollup's measures do not originate at the rollup's grain — they arrive there. Restating that premise is a phase of its own, and one refusal is cheaper than a wrong composition.

- Paths: `src/bloomery/resolve/graph.py` `src/bloomery/resolve/timeline.py` `src/bloomery/spec/marts.py`

### S-0066/D-1 — `LOCKED` (Declared input currency for conversion)

**A conversion's input currency must be a declared or derived fact; an unknown input is refused.** This is the whole document: an assertion that nothing can check is indistinguishable from a fact, and the difference is a wrong number that passes every existing guard. Locked because relaxing it — accepting `from` as its own evidence — restores exactly the situation S-0053/D-3 was written against, and because the refusal is what makes R009 mean anything.

- Paths: `src/bloomery/resolve/build.py` `src/bloomery/semantic/denomination.py` `src/bloomery/spec/mapping.py` `tests/unit/test_resolve/test_currency_convert.py` `tests/unit/test_semantic/test_denomination.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0066/D-3 — `LOCKED` (Declared input currency for conversion)

**The column's currency is what the chain's *last* conversion produces.** The existing per-marker check refuses a correct two-hop chain (§3), and bridging through a major currency is how minor pairs convert in practice. Locked because the guarantee the check buys is a property of where the chain ends, and any rule reading an intermediate step is reading a currency the column is never in.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/resolve/build.py` `tests/unit/test_resolve/test_currency_convert.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0066/D-6 — `ASSUMED` (Declared input currency for conversion)

**The declaration lives on the mapping's field, not on the entity or canonical field.** The mapping is where a source path and a transform chain meet, and a canonical field is shared across mappings — one field fed by a euro feed and a dollar feed would need two input currencies for one declaration. Not `LOCKED` because a project that never maps the same canonical field twice would not notice the difference.

- Paths: `src/bloomery/resolve/build.py`

### S-0067/D-6 — `OPEN` (Stable node identity across renames)

Whether node identity is a write-once `id:` or a one-shot `renamed_from:` in S-0024/D-3's shape (§10). Recorded rather than assumed: the codebase already chose the second answer for fields, and a document that does not say why nodes differ is one that looks like it did not know.

- Paths: `src/bloomery/resolve/timeline.py` `tests/unit/test_resolve/test_timeline.py`

### S-0069/D-4 — `LOCKED` (Definition supersession and change attribution)

Attribution runs over the dependency closure, not the named node. The single-node answer is the one `git log` already gives badly.

- Paths: `src/bloomery/resolve/timeline.py` `tests/unit/test_resolve/test_timeline.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0072/D-1 — `LOCKED` (Marts in the lineage graph)

The edge is `metric → mart`, labelled `measure` — dependency → dependent, like every other edge in this graph. A change to a metric restates the mart column that embeds it; a change to a mart moves no metric's definition. Reversing this inverts every downstream walk that reads the gold layer.

- Paths: `src/bloomery/resolve/graph.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0072/D-2 — `LOCKED` (Marts in the lineage graph)

The graph stays a **RESOLVE**-stage product, built from authored documents. No mart edge may require the flattener's output. This is what keeps `bloomery lineage` able to answer on a project that does not compile — which is when the question is most worth asking — and reversing it moves the graph out of `Resolution`, whose reachability report is computed from it.

- Paths: `src/bloomery/resolve/graph.py` `tests/unit/test_resolve/test_graph.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0073/D-1 — `LOCKED` (Caller-assembled spec history)

bloomery does not read spec history. The caller hands it spec text; where that text came from is outside the library and outside the CLI. Reversing this re-opens S-0020's boundary, which every document in this corpus is written on top of.

- Paths: `src/bloomery/resolve/timeline.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
