<!-- torve:managed tests/unit/test_emit — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/unit/test_emit/`

### S-0002/D-10 — `LOCKED` (Multi-project composition) — implementation: partial

An upstream's dbt project name is part of what it exports: `exports.yaml` carries an optional `name`, `ExportsIR` carries it across, and the downstream's dbt target spells the two-argument `ref()` and the `dependencies.yml` entry with that name while the downstream's own `dbt_project.yml` is named after its own export name when it has one. The local alias stays what keys the compile input and the IR resolution (D-2); dbt is the one target whose cross-project reference needs the producer's own name, so the name lives on the producer's side of the boundary and nowhere else.

- Paths: `src/bloomery/spec/exports.py` `src/bloomery/ir/nodes.py` `src/bloomery/emit/dbt/__init__.py` `tests/unit/test_emit/test_cross_project.py`
- Consequence: A downstream compiled against an upstream that exports no name keeps emitting `ref('<alias>', ...)` and a `dependencies.yml` naming the alias — resolvable only when the upstream's dbt project happens to be named so — and the refusal for that case is a documented gap until the row is graded. An exported SCD2 entity is a snapshot on dbt, which no project can reference across the boundary; the export is legal and the dbt target has nothing public to give for it.
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0019/D-7 — `ASSUMED` (Spec layer and error model)

`materialization` is explicit-with-derived-default (settles original open question #4); the resolved value is IR-recorded and diffable.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/ir/nodes.py` `src/bloomery/marts/flatten.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/entity.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_entity.py`

### S-0020/D-5 — `ASSUMED` (Intermediate representation and determinism contract)

Floats are banned in IR and emission; `Decimal`/int only.

- Paths: `src/bloomery/cli/serialize.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/steps.py` `src/bloomery/ir/fingerprint.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/request.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/common.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `src/bloomery/steps/manifest.py` `src/bloomery/steps/splice.py` `src/bloomery/transforms/_builtins.py` `src/bloomery/typing/types.py` `tests/execution/test_as_of_join.py` `tests/execution/test_currency_convert.py` `tests/execution/test_fanout_trap.py` `tests/execution/test_marts.py` `tests/execution/test_period_over_period.py` `tests/execution/test_rollup.py` `tests/fixtures/semantic_corpus/002-average-of-averages/naive.sql` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/golden/schema/marts.json` `tests/support/planning.py` `tests/support/semantic_corpus.py` `tests/unit/test_cli.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_planner/test_request.py` `tests/unit/test_quality/test_edges.py` `tests/unit/test_spec/test_metrics.py` `tests/unit/test_spec/test_quality.py` `tests/unit/test_steps/test_lowering.py` `tests/unit/test_steps/test_manifest_and_registry.py` `tests/unit/test_typing/test_types.py`

### S-0023/D-7 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Path conflict does not raise (`PathConflict` is not an error class): the compiler emits the derived column, a `<name>__direct` shadow, and a `RECONCILE` `AuditIR`. The forbidden thing is the silent choice; both paths are valid, so the refusal targets the silence, not the spec.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/quality.py` `src/bloomery/ir/lower.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/mapping.py` `tests/fixtures/path_conflict/entity_model.yaml` `tests/fixtures/path_conflict/mapping.yaml` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_ir/test_lower.py` `tests/unit/test_spec/test_mapping.py`

### S-0025/D-3 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Capability mismatch behavior is fail-loud: `UnsupportedByTarget` naming entity + feature. Silent degradation is forbidden.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/spec/quality.py` `src/bloomery/transforms/_builtins.py` `tests/property/test_compile_properties.py` `tests/unit/test_emit/test_base.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_quality/test_text_rules.py` `tests/unit/test_transforms/test_builtins.py`

### S-0025/D-5 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

v0.1 adapter set: SQLMesh + Cube + dbt targets; DuckDB + Postgres + Trino dialects. dbt is a port-abstraction proof, documented as such.

- Paths: `src/bloomery/compile.py` `src/bloomery/dialects/duckdb.py` `src/bloomery/dialects/postgres.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/runtime/sql_client.py` `tests/unit/test_dialects/test_duckdb.py` `tests/unit/test_dialects/test_postgres.py` `tests/unit/test_dialects/test_trino.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_runtime/test_sql_client.py`

### S-0025/D-8 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Emitter/dialect registries mirror the transform registry: immutable defaults + explicit overlay, collision is an error, iteration sorted (S-0021/D-6).

- Paths: `src/bloomery/dialects/__init__.py` `src/bloomery/emit/__init__.py` `src/bloomery/runtime/sql_client.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_emit/test_base.py`

### S-0025/D-11 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

(Amended, S-0027) The SQLMesh emitter also builds marts: one gold-layer model per `MartIR`, the only join-emitting path for marts.

- Paths: `src/bloomery/emit/lower/marts.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py` `tests/unit/test_emit/test_sqlmesh.py`

### S-0025/D-13 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

(Reverses D6) Bloomery owns the date dimension: one catalog definition emits both the SQLMesh `gold.dim_date` model and the MetricFlow time-spine declaration (S-0030 R1). D6's demand-gate is satisfied — MetricFlow is the demand.

- Paths: `src/bloomery/emit/lower/marts.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/metrics.py` `tests/execution/test_marts.py` `tests/fixtures/ecom_basic/catalog.yaml` `tests/golden/schema/catalog.json` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_fixtures.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_metrics.py`

### S-0025/D-18 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

*(2026-08-11)* **The dbt target defines the generic test it declares; the emitted project depends on no package.** D16's dbt half had to name *some* vehicle for `min`/`max`/`regex`/`reconcile`, and the only one dbt offers is `dbt_utils.expression_is_true` — which D16 itself noted "is a package, not core" without following the consequence. The consequence is that bloomery emitted a project **declaring a test it did not define**: `dbt compile` stops at ``'dbt_utils' is undefined. … install package dependencies with "dbt deps"``, for every project carrying one of those four clauses. Two fixes were available — emit a `packages.yml` pinning `dbt-labs/dbt_utils`, or define the test — and the second wins on the thing this compiler is for: artifacts are a pure function of the specs (S-0020), and a `packages.yml` makes the output complete only after a *network fetch* the compiler is forbidden from performing and the consumer may not be able to perform at all. So `macros/bloomery_expression_is_true.sql` is emitted, iff `schema.yml` declares the test. Three things follow. **It is `ArtifactKind.AUDIT`, not `CONFIG`** — it is the custom audit *body* for this target, the exact counterpart of the `audits/<name>.sql` file SQLMesh gets for the same kinds and from the same `audit_predicate`, which makes D16's "one function, two forms" symmetry structural rather than incidental. **The body is `dbt_utils`' `default__test_expression_is_true` minus the `column_name` branch bloomery never takes**, so the replaced semantics are preserved exactly — including that a NULL expression *passes*, `NOT NULL` being NULL and selecting no row, which is S-0033/D-19's Kleene discipline arrived at from dbt's side. **The emission condition reads the emitted schema rather than re-deriving the entity filter**, so the project can neither declare the test without the macro nor carry it unused, and a test pins both directions.

- Paths: `src/bloomery/emit/dbt/__init__.py` `tests/e2e/test_dbt_parse.py` `tests/property/test_compile_properties.py` `tests/unit/test_emit/test_dbt.py`

### S-0025/D-20 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

*(2026-08-11)* **The dbt target emits a real DAG, and keeps the naming policy owning namespaces. S-0026/D-22 is closed — with both of its candidates, not one.** D22 found `dbt build` could not pass: models named their inputs literally (`FROM silver.order_item`), so dbt had no edges to order them by *and* materialized each into the profile's target schema while the `FROM` clause said `silver`. It offered two fixes with an "or" between them, and the "or" was the mistake — **neither is sufficient alone, and each repairs the other's cost.** `+schema` config alone places the relations and leaves ordering absent, so a gold model still races its silver input. `ref()`/`source()` alone orders the DAG but resolves names through dbt's schema config, which is the objection D22 raised: the naming port stops owning the namespace. Together: `ref()` for every relation bloomery emits and `source()` for bronze, `+schema: <ns>` per model directory, and a `generate_schema_name` override returning the configured schema **verbatim** — because dbt's default returns `<target.schema>_<custom>`, which would put models in `main_silver` while `sources.yml` (which never passes through that macro) still said `bronze`, honouring the policy in half the project. **How it is emitted.** Shared lowering is untouched: both targets build inputs as `exp.table_(relation, db=namespace)`, and the dbt emitter rewrites *table nodes only*, mapping `(namespace, relation)` to a reference. A namespace-less table is never rewritten, which is what keeps a CTE reference from being mistaken for a model; a table the map does not know is left literal rather than guessed at, because inventing a `ref()` for a relation bloomery did not write would name a model dbt cannot find. An SCD2 entity resolves to its **snapshot**, the only thing this target builds for it. **The cost, stated.** D5's port-abstraction proof compared the two targets' SELECTs byte for byte and can no longer: the `FROM` clauses differ by construction. It is restated, not weakened — resolve the references, drop namespaces, and the SQL is identical on every projection, join, cast and dialect quirk, so the entire difference between the targets is one documented substitution. The namespaces the comparison erases are asserted separately, against the `+schema` config and the override.

- Paths: `src/bloomery/emit/dbt/__init__.py` `tests/e2e/test_dbt_parse.py` `tests/property/test_compile_properties.py` `tests/support/compiling.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_quality_mart.py`

### S-0025/D-22 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

*(2026-08-11)* **The emitted `schema.yml` targets dbt `>=1.10,<2`, and the generic-test form is what sets that floor.** Found by a deprecation warning in D21's new build pass — "arguments to generic tests should be nested under the `arguments` property" — which looked like housekeeping and was not. **The two spellings are mutually exclusive**, measured on four real installs by compiling this repo's own emitted project rather than inferred from a changelog: flat compiles on 1.9.10, 1.10.22, 1.11.12 and 1.12.0 (warning from 1.10 on); nested is a **compilation error** on 1.9 and clean on all three later ones. So the choice is a compatibility range, not a style, and the only version that discriminates is 1.9 — which is what makes the nested form worth taking. Adopting it at a floor of 1.12 (the version that happened to be installed) would have cost three further minor versions for nothing; the floor is the version the feature actually arrived in. **What this exposed is bigger than the warning.** Which dbt versions the *emitted artifact* works on had never been written down anywhere. `dbt-core>=1.9` was a **dev** dependency — the test environment, not the product — unbounded, so CI silently tested against whatever resolved that day, while the artifact's own compatibility was a matter of nobody having asked. S-0025/dbt-emitter-compatibility calls dbt "the compatibility target" without ever saying compatible with *what*. It now says: the dependency is bounded `>=1.10,<2` (as sqlmesh and metricflow already were — dbt was the one framework left floating), the range is stated in the emitter's docstring, and a test pins the emitted form with the measured matrix in its docstring, so the bound and the form can only move together. `not_null` is unaffected: it takes no arguments and stays a bare name on every version.

- Paths: `src/bloomery/emit/dbt/__init__.py` `tests/unit/test_emit/test_dbt.py`

### S-0027/D-2 — `ASSUMED` (Marts and role-playing dimensions)

Measure grain must strictly equal mart grain; coarser or finer is `GrainViolation`. Resolves D2's prose/example contradiction to the strict reading; relaxation is a future additive change.

- Paths: `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/semantic/proof.py` `src/bloomery/semantic/rollup.py` `tests/fixtures/fanout_trap/marts.yaml` `tests/fixtures/fanout_trap/metrics.yaml` `tests/fixtures/semantic_corpus/001-order-shipping-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/001-order-shipping-fanout/problem.md` `tests/fixtures/semantic_corpus/010-many-to-many-bridge/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/010-many-to-many-bridge/problem.md` `tests/golden/refusals/example-wrong-grain.txt` `tests/golden/refusals/fanout_trap.txt` `tests/support/semantic_corpus.py` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_semantic_corpus_guard.py`

### S-0027/D-8 — `ASSUMED` (Marts and role-playing dimensions)

`cost_hint` (int, default 1) is a tie-breaking scan-cost hint only; selection ties break lexicographically (S-0020 determinism).

- Paths: `src/bloomery/emit/lower/marts.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/spec/marts.py` `tests/golden/schema/marts.json` `tests/unit/test_emit/test_metricflow.py` `tests/unit/test_planner/test_coverage.py`

### S-0027/D-9 — `ASSUMED` (Marts and role-playing dimensions)

(Amended for `_bloomery-metricflow-pivot.md`) Marts are the emission source for MetricFlow semantic models — one mart = exactly one semantic model (S-0030 R1); a measure-carrying mart must declare a date role (`MartMissingTimeDimension` otherwise). Marts and role-playing are *more* load-bearing after the pivot, not less.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/marts/flatten.py` `src/bloomery/quality/mart.py` `src/bloomery/resolve/graph.py` `tests/fixtures/ecom_basic/marts.yaml` `tests/fixtures/quality_precedence/entity_model.yaml` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_fixtures.py` `tests/unit/test_quality/test_mart.py` `tests/unit/test_resolve/test_graph.py`

### S-0030/D-3 — `ASSUMED` (MetricFlow backend: manifest emitter and planner adapter)

`emit_manifest(ir, *, naming) -> PydanticSemanticManifest` is a pure deterministic emitter. One mart = exactly one semantic model; never a semantic model for a non-materialized entity (would reintroduce query-time joins). Every measure carries `agg_time_dimension`; a martless time dimension is `MartMissingTimeDimension` (new `GuardrailError` leaf). All collections sorted lexicographically before construction — the manifest is hashed/cached. Full IR→MetricFlow mapping and enum tables per §5.2.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `tests/fixtures/non_additive_aov/marts.yaml` `tests/unit/test_emit/test_metricflow.py`

### S-0030/D-4 — `ASSUMED` (MetricFlow backend: manifest emitter and planner adapter)

`SemiAdditivePolicy.rule` maps `last → MAX`, `first → MIN`; `avg`/`max`/`min` are not expressible via `non_additive_dimension` → `UnsupportedByTarget` naming the rule.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `tests/fixtures/non_additive_aov/marts.yaml` `tests/unit/test_emit/test_metricflow.py`

### S-0030/D-6 — `ASSUMED` (MetricFlow backend: manifest emitter and planner adapter)

Mart-coverage precheck runs **before** delegation and preserves the refusal policy: all measures on one mart (else `UnreachableAtGrain` with S-0028's exact per-metric grain/mart message), all dimensions flattened onto it, multi-candidate → `cost_hint` then lexicographic. MetricFlow could plan multi-hop joins; we refuse first — refuse-don't-guess enforced twice (coverage, then MetricFlow's resolver). Belt and braces.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/planner/coverage.py` `src/bloomery/planner/metricflow_planner.py` `tests/fixtures/multi_mart_refusal/marts.yaml` `tests/unit/test_emit/test_cube.py`

### S-0033/D-21 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Ingestion metadata contract: entities using `quarantine` or `dedupe` require bronze `_load_id`, `_ingested_at`, `_source_row_id` (a stable per-source-row identity supplied by the ingestion layer, **NOT NULL and unique per source row** — data properties no compiler can check, so the lowering emits a generated **blocking audit** on the metadata columns: a null or duplicated `_source_row_id` stops the run); column absence is the new compile error `IngestionMetadataMissing` (`GuardrailError` leaf, `errors.py` per S-0019/D-3). `reject_id` = sha256 over the length-prefixed utf-8 **pair** (`source_relation`, `_source_row_id`) — canonical serialization per the S-0020 canon-bytes doctrine. This supersedes the triple this row first carried (this round's own earlier decision): `_load_id` is removed from the identity and becomes an attribute (the latest observing load) — re-deliveries of the same source row across loads must land on the **same** reject row (that is what `first_seen`/`last_seen` track); a per-load identity would mint a new row per retry and violate replay idempotence. A re-delivery updates `last_seen`/`_load_id`/`failed_rules` on the existing row.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/quality.py` `src/bloomery/quality/catalogue.py` `src/bloomery/quality/dedupe.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/transforms/_builtins.py` `tests/e2e/test_dbt_parse.py` `tests/e2e/test_sqlmesh_project.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_dedupe_and_audits.py` `tests/execution/test_merged_cleaning.py` `tests/execution/test_zoneless_utc.py` `tests/fixtures/dirty/README.md` `tests/fixtures/semi_additive_inventory/mapping.yaml` `tests/support/execution.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_trino.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_entity.py`

### S-0033/D-32 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **A `fail` rule's audit reads the pre-route population.** Routing is stage 6 and an audit runs after the model is built, so an audit over `@this_model` sees only the rows the split kept — a row failing a `fail` rule *and* a `quarantine` rule was diverted and the run carried on, inverting D18's severity order. The body is a query over the staged extract (the same rows the routing predicate is evaluated over), which stays inside D29's two-relation scope limit because `referential` cannot carry `fail` (D6). Consequences: every kind lowers through the same `violation` predicate (retiring a `coercible`-at-`fail` special case that had silently redefined the rule as `not_null`), and FAIL-disposition rule names are recorded in **both** `failed_rules` and `_quality_flags`, so the quality mart's `rows_failed` is no longer structurally zero for the rules whose firing matters most.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `tests/execution/test_quarantine_replay.py` `tests/unit/test_emit/test_dbt.py`

### S-0033/D-58 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **dbt's refusal of `reconcile:` is authorized scope, not a widened one.** §5.4's target-coverage sentence granted the dbt emitter one refusal — "the reject/replay artifacts" — and `_refuse_reconcile` shipped a second one under it, which is code contradicting an accepted RFC. The refusal is right and is granted here rather than removed: a reconcile check lowers to a model **and** a *non-blocking* audit (§5.3); dbt lowers neither in this wave, and the test surface it does emit (`schema.yml` data tests) blocks the build on failure, so approximating the audit with one would turn "report the disagreement" into "fail the build" — S-0025/D-3's silent degradation, in the direction that halts a pipeline over a tolerance the author declared non-fatal. §5.4 carries the matching amendment and the `UnsupportedByTarget` message cites this row, so the scope a compile refuses on is checkable against the decision that grants it. The price, stated: dbt is a strictly smaller target in one more named way, and a project with a `reconcile:` block compiles for `sqlmesh` only.

- Paths: `src/bloomery/emit/dbt/__init__.py` `tests/unit/test_emit/test_dbt.py`

### S-0033/D-67 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **A `fail` rule's audit covers two populations, not one.** D32 moved the body off `@this_model` and onto the pre-route staged extract, which fixed the precedence inversion and, in the same move, stopped covering the rows *already in the entity*. That population is not empty and is not reachable from bronze: a **replayed** row is merged in from the reject table, and its bronze source has aged out of the incremental window by construction — that is the entire premise of `replay_scope` (§5.7). Reproduced end to end: after a widening plus a replay, a row sat in silver whose own `_quality_flags` recorded the blocking rule firing while that rule's audit reported **zero** violating rows — a model contradicting its own data, which is worse than an unchecked population because it reads as coverage. The body is now `pre-route extract UNION @this_model`, exactly two relations, inside D29's limit (`referential` cannot carry `fail`, D6). `UNION` rather than `UNION ALL`: the ordinary violator is in both populations and reporting it twice says nothing extra. The entity leg reads the **recorded** verdict — `_quality_flags` carries FAIL names since D32 — rather than re-deriving the predicate over model columns, which is forced: over the model the coercion marker's source conjuncts are gone and `coercible` would silently re-define itself as `not_null`, the very special case D32 retired. Recorded price: the leg covers rows evaluated under the *current* spec, and a rule added or renamed classifies RESTATING (D11), whose backfill is what re-derives the flags. Replay deliberately does **not** filter `fail` rules out of its MERGE — refusing to merge them would be quarantine outranking fail again, the inversion D32 exists to prevent; the row lands, and the audit is what stops the next run.

- Paths: `src/bloomery/emit/dbt/__init__.py` `tests/execution/test_quarantine_replay.py` `tests/property/test_compile_properties.py` `tests/unit/test_emit/test_dbt.py`

### S-0033/D-83 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **The reject table's two constructions are spelled by the dialect port, and Trino hosts it. D75 is closed — and Postgres turned out to be wrong in the same place, silently.** D75 recorded the two gaps and refused Trino at emit; the fix it named — a per-dialect hook rather than a shared AST — is built. `DialectPort` gains `text_sha256` and `json_object`, because a construction that differs per engine belongs to the port that knows the engine (S-0025/D-1), not to a lowering that is supposed to be dialect-neutral. Trino: `LOWER(TO_HEX(SHA256(TO_UTF8(…))))` and the standard keyword `JSON_OBJECT`. **The finding that was not in D75:** Postgres declared support for *both* features and has neither. Its `sha256` takes and returns `bytea`, so the plain spelling did not fail — it silently yielded bytes where every other engine yields a hex string, which would have made `reject_id` disagree across engines while looking like it worked; and it has no positional `json_object` at all (`function pg_catalog.json_object(unknown, integer, …) does not exist` — the SQL/JSON one arrived in 16 taking `KEY … VALUE` only, and the positional builder has always been `json_build_object`). D75's own sentence — "the one construction SQLGlot renders verbatim on every shipped dialect… holds for DuckDB and Postgres but not Trino" — was therefore half wrong, and it read as verified because the *other* half had been. It held only because Postgres never reached emission: D30 refuses a quality-carrying entity there for the unrelated `TRY_CAST` reason, so the reject table was never built for it. Postgres now has correct spellings that stay unreachable until D30 lifts, asserted at the port rather than through a compile so they cannot rot in the meantime. Verified by **executing the emitted model**, not the expressions: the full `__reject` SELECT runs on `trinodb/trino:483` and returns a `reject_id` byte-identical to the Python canon-bytes digest — cross-engine *agreement* being the property `reject_id` actually needs. The feature flags stay in the vocabulary: a fourth dialect may still lack either, and the refusal they drive is still the right answer for one that does.

- Paths: `src/bloomery/dialects/postgres.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/quality/reject.py` `tests/engines/test_merged_cleaning_engines.py` `tests/golden/test_sqlmesh_dialects.py` `tests/unit/test_emit/test_quality_artifacts.py`

### S-0040/D-4 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

`convert` raises `UnsupportedByTarget` at **emit**, on all three dialects. It stays a registered transform with an unchanged typecheck, so the spec surface does not move and a future dialect clears the refusal by declaring a `Feature` — the mechanism S-0025 already provides.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/evidence.py` `src/bloomery/resolve/build.py` `src/bloomery/transforms/_builtins.py` `tests/fixtures/currency_convert_refusal/entity_model.yaml` `tests/support/type_conformance.py` `tests/unit/test_emit/test_currency_convert.py` `tests/unit/test_evidence.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0040/D-7 — `ASSUMED` (Temporal joins: SCD2 flattening and currency conversion)

A `type2` entity's validity-interval column names belong on `EntityIR`. Today each target names them privately, which is the mechanical reason no predicate can be emitted; naming them in the IR is what makes the two targets agree.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/ir/nodes.py` `tests/e2e/test_dbt_parse.py` `tests/unit/test_emit/test_dbt.py`

### S-0040/D-11 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

The FX rate relation declares **both** interval ends (`valid_from` and `valid_to`), never `valid_from` alone. One end is not an interval: a fact row would match every rate at or before its anchor and the conversion would fan out. Deriving the upper bound with `LEAD(valid_from)` is rejected — it makes every conversion a window function over the whole rate table, and it extends the newest rate to infinity, so a stale feed converts at last week's rate instead of failing. Consequence: a gap in the rate table is a *miss*, taking D9's `unknown_member` disposition, rather than silently resolving to a neighbour.

- Paths: `src/bloomery/transforms/_builtins.py` `tests/execution/test_currency_convert.py` `tests/fixtures/currency_convert/catalog.yaml` `tests/unit/test_emit/test_currency_convert.py` `tests/unit/test_quality/test_lower.py` `tests/unit/test_spec/test_catalog.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-3 — `LOCKED` (Deterministic union merge)

Mappings are unioned in **lexicographic order of source name**, so the emitted artifact is byte-identical across processes. Row order is explicitly **not** claimed — `UNION ALL` is a bag, and nothing downstream may depend on source order.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/ir/nodes.py` `tests/unit/test_determinism_guard.py` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_resolve/test_build.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-7 — `ASSUMED` (Deterministic union merge)

A `_source` system column carries provenance. It is load-bearing rather than diagnostic: the collision audit reports which sources collided, and without it the report is unactionable on a multi-source entity.

- Paths: `pages/docs/reference/stability.md` `src/bloomery/emit/lower/silver.py` `src/bloomery/ir/nodes.py` `src/bloomery/spec/common.py` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_steps/test_lowering.py`

### S-0041/D-13 — `LOCKED` (Deterministic union merge)

The collision audit reads the **union output, before dedupe**, and groups by **every** declared key column. Reading `silver.order` would let dedupe collapse the colliding rows before the audit counts them — the audit would be checking the one relation guaranteed not to contain what it looks for. Grouping by a partial key would merge distinct composite keys and block valid data, which on a blocking audit is the worst failure available.

- Paths: `src/bloomery/emit/lower/silver.py` `tests/execution/test_merged_cleaning.py` `tests/unit/test_emit/test_quality_artifacts.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-20 — `ASSUMED` (Deterministic union merge)

**dbt emits one `source()` per mapping**, and the model body unions them. Nothing about the union needs a dbt capability it lacks, so refusing it there — as dbt is refused for `python_model` steps, mart assertions and reject tables — would be a limitation invented rather than found.

- Paths: `src/bloomery/emit/dbt/__init__.py` `tests/unit/test_emit/test_dbt.py`

### S-0041/D-26 — `ASSUMED` (Deterministic union merge)

**Answers D25 (`OPEN`) — option (a), and D25's blast-radius figure was wrong by an order of magnitude.** The lowered expression moves to a new column-grained `SourceColumnIR` on `SourceIR`; `ColumnIR` keeps the schema (§5.7). D25 said "37 `.columns` read sites" and estimated the cost from that; measured, **exactly 8 sites read a `ColumnIR` lowering field, in 3 files** — `plan/diff.py` (`renamed_from` ×4, `recipe_id`, `expr.sql`) and `emit/lower/silver.py` (`expr.ast()` ×2). Four of those eight are `renamed_from`, which D25 mis-assigned to the lowering half and which is declared on the EntityModel `Field`, so it does not move at all. The 37 was a count of `.columns` readers, and `.columns` readers are overwhelmingly *schema* readers — they survive untouched, which is the whole point of the split. **Real cost: two constructors where there was one, and four call sites.** The golden churn stands regardless — the IR shape moves and D17 bumps the version.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/operands.py` `src/bloomery/guardrails/stage.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/resolve/build.py` `src/bloomery/resolve/facets.py` `src/bloomery/resolve/steps.py` `src/bloomery/resolve/timeline.py` `tests/bench/test_hydration.py` `tests/support/ir_factory.py` `tests/support/plan_ir.py` `tests/unit/test_emit/test_cube.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_facets.py` `tests/unit/test_unresolved.py`

### S-0041/D-30 — `ASSUMED` (Deterministic union merge)

**Departs from D20 — the dbt target refuses a merged entity in P1**. D20's claim about the *union* holds and shipped: the `UNION ALL` is the same shared SELECT both targets render, and the dbt emitter does emit one `source()` per mapping. What D20 did not account for is that the merge's correctness condition is a **blocking audit** (D5), and this emitter has no artifact for one: its whole test surface is `schema.yml` entries covering `not_null`, `accepted_values` and a single expression test, and it emits no singular-test path at all. A generated `GROUP BY <key> HAVING COUNT(DISTINCT _source) > 1` is none of those. Emitting the union without it produces a model that compiles here, runs anywhere, and double-counts an entity in silence — the degradation S-0025/D-3 refuses. **S-0033/fixed-pipeline-order-and-lowering's target-coverage sentence deliberately was not stretched to cover this**: it authorizes dbt's partiality for the *quality* artifacts, and a rule an author chose to make blocking is not the same thing as the one check a feature cannot be correct without. Consequence: merged entities are SQLMesh-only until the dbt emitter grows a singular-test surface, which is its own change and not P2's. D20's row is left standing — what it predicted is the thing this has to be read against. *Added by execution 2026-08-16 — see logs/T-0004.md (V-002, attempt 1).*

- Paths: `tests/e2e/test_dbt_parse.py` `tests/unit/test_emit/test_dbt.py`

### S-0043/D-4 — `ASSUMED` (The dbt singular-test surface)

**Native schema tests stay preferred where dbt has an equivalent.** `not_null` and `enum` keep their builtin lowering; the singular test is the fallback, not the replacement. Rationale is reader-facing: a native test names its column in `dbt test` output and appears in `dbt docs`, and a hand-rolled query does neither. Graded `ASSUMED` because it is a readability claim, and D10 asks whoever builds this to check it against real output.

- Paths: `src/bloomery/emit/dbt/__init__.py` `tests/e2e/test_dbt_parse.py` `tests/unit/test_emit/test_quality_artifacts.py`

### S-0043/D-9 — `ASSUMED` (The dbt singular-test surface)

**S-0041/D-30 is lifted, not superseded.** D30's argument was correct when written — the emitter genuinely had no artifact for the audit. What changes is the emitter, not the reasoning, and D30's row stays as the record of why merged entities were SQLMesh-only for one release.

- Paths: `tests/unit/test_emit/test_dbt.py`

### S-0043/D-10 — `LOCKED` (The dbt singular-test surface)

**The audit envelope separates from the audit body** (§5.3). `emit/steps.py` is target-neutral by position and not by content: its `_AUDIT` template bakes SQLMesh's `AUDIT (name …);` header in, so `quality_audits` and `consistency_audits` hand shared callers a SQLMesh artifact. A producer instead returns a *named body* — rendered SELECT, name, disposition — and each target wraps it. The alternative, a second template beside the first, gives one audit body two spellings maintained in parallel, which is the divergence the shared lowering exists to prevent. Consequence: this is the only structural change here, and it is what makes the remaining work a template and a path rather than five separate liftings. It also carries the relation in as a parameter, so `@this_model` stops being a literal the dbt side would rewrite by substitution.

- Paths: `src/bloomery/emit/base.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/steps.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_steps/test_dbt_and_cube_emission.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-1 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A derived metric is `expr` over aliased inputs, each input a metric.** `inputs` is a mapping keyed by alias, not a list: the alias is the input's identity because `expr` references it, and a dict makes a duplicate alias unrepresentable rather than a validation. Consequence: `MetricIR` gains a `derived` field and the additivity guard must accept it as a decomposition.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/resolve/build.py` `src/bloomery/semantic/plan.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-2 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**An offset is `{window: "<count> <grain>"}` or `{to_grain: <grain>}`, exactly one.** The grain vocabulary is `day`, `week`, `month`, `quarter`, `year` — the mart's own date buckets (S-0027/D-4). `hour` is refused despite MetricFlow accepting it: the emitted time spine is day-grain, so an hourly offset would resolve against a spine that cannot express it.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-4 — `ASSUMED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A derived metric need not be named in any mart's `measures:`.** It has no measure to place. It is emitted where every input's measure is emitted — the rule the ratio already uses — and the planner's coverage precheck resolves it to the mart carrying those measures. Naming it in `measures:` stays legal and inert, as it is for a ratio.

- Paths: `src/bloomery/emit/cube/__init__.py` `tests/fixtures/period_over_period/marts.yaml` `tests/unit/test_emit/test_period_over_period.py`

### S-0050/D-5 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**`cumulative:` is lowered, and the blanket `UnsupportedCumulative` refusal is deleted rather than narrowed.** The class goes with it: a reserved-surface error whose surface is no longer reserved is a class that can only mislead. Combinations that still cannot be lowered are refused by their own named guardrails (D7).

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/planner/semantic_plan.py` `tests/execution/test_period_over_period.py` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_planner/test_metricflow_planner.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-8 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A metric filter is a typed predicate list — `{dimension, op, values}` — and never a SQL string.** A string would be dialect-bound, unvalidatable against the column's declared type, and an injection surface in a compiler whose input may be untrusted. The list is ANDed; a disjunction is expressed as `in`.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/semantic/additivity.py` `src/bloomery/spec/common.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_semantic/test_ratio_rows.py` `tests/unit/test_spec/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-11 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**Cube refuses derived and cumulative metrics per construct with `UnsupportedByTarget`, and emits metric filters.** Period-over-period is a query-time concern in Cube, and `grain_to_date` has no `rolling_window` equivalent. Refusing the offset-free derived case too — which `{member}` templating could express — keeps one rule where support-that-depends-on-an-offset would need two, and the ratio form still covers division.

- Paths: `tests/golden/test_metricflow_manifest.py` `tests/unit/test_emit/test_period_over_period.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-15 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**The filter renderer lives once, in `emit/lower/predicates.py`, parameterized by the target's column spelling.** Each target supplies how it names a column — `{{ Dimension('e__c') }}` for MetricFlow, `{CUBE}.c` for Cube — and the comparison syntax, list rendering and literal escaping are shared. Two renderers would be the same injection-safety rules spelled twice, which is the defect class this project keeps finding in itself.

- Paths: `src/bloomery/emit/lower/predicates.py` `tests/unit/test_emit/test_period_over_period.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0053/D-2 — `LOCKED` (Measure semantic types and additivity algebra)

**A ratio is stored as its operands, not as a materialized quotient.** `SUM(num)/SUM(den)` and `AVG(ratio)` differ, the second is what a numeric-looking column invites, and the difference is a plausible wrong number. This is also S-0055's precondition — a derived metric spanning two branches cannot be reconstructed after the operands are gone — so reversing it later strands that document.

- Paths: `src/bloomery/emit/lower/rollups.py` `src/bloomery/errors.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/mart.py` `tests/fixtures/semantic_corpus/002-average-of-averages/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/002-average-of-averages/problem.md` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/problem.md` `tests/fixtures/semantic_corpus/008-ratio-rollup/bloomery/declared/metrics.yaml` `tests/fixtures/semantic_corpus/008-ratio-rollup/bloomery/naive/metrics.yaml` `tests/fixtures/semantic_corpus/008-ratio-rollup/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/008-ratio-rollup/problem.md` `tests/fixtures/semantic_corpus/012-rollup-recounts-identities/problem.md` `tests/unit/test_emit/test_rollups.py` `tests/unit/test_guardrails/test_additivity.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_steps/test_step_canonicals.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0060/D-14 — `LOCKED` (dbt as a complete quality target)

The replay macro wraps its three statements in an explicit `BEGIN`/`COMMIT`. `run_query` opens no transaction, and a failure between the entity `MERGE` and the reject stamps leaves a row both admitted and unresolved — double-counted in the quality mart and re-admitted on the next replay. SQLMesh's replay file states the same requirement in prose to a human; the macro has to state it to the engine.

- Paths: `src/bloomery/emit/dbt/__init__.py` `tests/e2e/test_dbt_quality.py` `tests/unit/test_emit/test_quality_artifacts.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0063/D-4 — `LOCKED` (Exposures and downstream consumers)

Cube and SQLMesh emit nothing for an exposure, and this is **not** a refusal. Neither framework has the concept, so there is nothing to degrade; refusing a Cube compile because the project declares a dashboard would turn an annotation into a target restriction.

- Paths: `src/bloomery/emit/dbt/__init__.py` `tests/unit/test_emit/test_sqlmesh.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0064/D-6 — `LOCKED` (Declared source freshness)

SQLMesh and Cube emit nothing, and it is not a refusal — neither models a source as an object, so there is no artifact being approximated (the S-0063/D-4 rule).

- Paths: `tests/unit/test_emit/test_cube.py` `tests/unit/test_emit/test_sqlmesh.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
