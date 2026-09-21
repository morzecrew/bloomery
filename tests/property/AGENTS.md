<!-- torve:managed tests/property — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/property/`

### S-0010/D-1 — `LOCKED` (Generating from the spec schema) — implementation: none

Schema-directed generation lands in the property tier under `tests/property/`, never as a fuzz target: it produces valid input by construction, which is the property tier's territory by the seam the corpus already states

- Paths: `tests/property/**`
- Consequence: The check runs in the default test tiers on every pull request and shrinks a failing spec to structure a person can read, at the cost of coverage-guided feedback; a contract that proposes a fuzz target for this work is proposing to reopen the seam, which halts under this grade
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0010/D-2 — `LOCKED` (Generating from the spec schema) — implementation: none

The generated-document strategy and its assertions extend `tests/property/test_schema_agreement.py`, never a sibling module asserting drift of its own

- Paths: `tests/property/test_schema_agreement.py`
- Consequence: The existing corpus strategy stays beside the generated one in the same module, because a corpus of real documentation examples asserts something a generator does not — that the spelling the docs teach is accepted; shared generator helpers may live elsewhere under `tests/`, but nothing that asserts agreement may
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0010/D-3 — `OPEN` (Generating from the spec schema) — implementation: none

Whether the generator is `hypothesis-jsonschema`'s `from_schema()` or a hand-written strategy over the subset of JSON Schema bloomery emits is decided by execution, with the tiebreak being the fraction of generated documents that reach the resolver — never the dependency's release date

- Paths: `tests/property/**` `tests/support/**` `pyproject.toml`
- Consequence: Adopting the dependency adds a `dev`-group entry to `pyproject.toml` carrying the same explanatory comment style `jsonschema` already has; declining it puts a maintained strategy in this repository instead. Either way the measured fraction is logged, so the choice is re-decidable on evidence rather than re-argued.

### S-0010/D-4 — `ASSUMED` (Generating from the spec schema) — implementation: none

Only one direction of agreement is asserted — what the parser refuses, the schema should refuse too, for the mutation classes JSON Schema can express — and a document the schema accepts and the parser refuses is a named divergence, not a failure

- Paths: `tests/property/test_schema_agreement.py`
- Consequence: The float `tolerance` and the free-string metric `agg` stay asserted as expected divergences at the bottom of that module, so closing one turns the suite red and forces the note to be removed rather than left lying; a new divergence is named in the same place rather than fixed under this document

### S-0010/D-5 — `OPEN` (Generating from the spec schema) — implementation: none

What would move this work to a fuzz target after all is stated by execution, the candidate signal being guardrail branches reached materially faster under coverage feedback than under generation

- Paths: `tests/property/**`
- Consequence: The row is discharged with whatever was measured — including "no evidence either way" — rather than left implicitly open, so D-1's seam is reopened on a number instead of on an impression

### S-0010/D-6 — `ASSUMED` (Generating from the spec schema) — implementation: none

Cross-document consistency is produced by generating a pool of names the documents then draw from, rather than generating each document independently and hoping its references resolve

- Paths: `tests/property/**` `tests/support/**`
- Consequence: The generator is stateful across a project's documents, so the reach fraction for a set is not the fraction for a single kind and the two are reported separately; a pool that constrains the generated space more than it buys is a departure to log against this row, not a bug

### S-0019/D-4 — `ASSUMED` (Spec layer and error model)

Parse validates shape and grammar only; reference existence (entities, transforms, canonical fields) is deferred to resolve/typecheck. Consequence: a shape-valid spec with dangling references parses fine — callers must run `resolve` to trust it.

- Paths: `src/bloomery/marts/flatten.py` `src/bloomery/resolve/refs.py` `src/bloomery/spec/__init__.py` `src/bloomery/spec/entity.py` `src/bloomery/spec/mapping.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `tests/golden/schema/metrics.json` `tests/property/test_schema_agreement.py` `tests/unit/test_spec/test_entity.py`

### S-0019/D-8 — `ASSUMED` (Spec layer and error model)

Catalog is passed separately from `Project` (vertical-level vs tenant-level), matching spec §8's `compile_project(..., catalog=...)`.

- Paths: `src/bloomery/cli/io.py` `src/bloomery/schema.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/project.py` `tests/property/test_schema_agreement.py`

### S-0023/D-9 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

`check_guardrails(draft: ProjectIR) -> ProjectIR` is pure; its only amendment is path-conflict handling (shadow column + audit). All other guardrails are read-only checks.

- Paths: `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/build.py` `tests/property/test_guardrail_properties.py` `tests/unit/test_guardrails/test_stage.py`

### S-0024/D-3 — `ASSUMED` (Plan: spec diff and change classification)

Renames are explicit only: `renamed_from: <old>` in the spec (carried as `ColumnIR.renamed_from`, an S-0020 amendment). No heuristic inference — determinism and auditability beat convenience. A stale annotation (old name absent from `old`, including `old is None`) raises `RenameTargetMissing` (`PlanError`), which forces the annotation to be dropped after one applied plan.

- Paths: `src/bloomery/errors.py` `src/bloomery/plan/diff.py` `src/bloomery/plan/model.py` `src/bloomery/spec/entity.py` `tests/fixtures/evolution_v3/entity_model.yaml` `tests/golden/schema/entity_model.json` `tests/property/test_plan_properties.py` `tests/unit/test_plan/test_diff.py` `tests/unit/test_plan/test_evolution.py`

### S-0025/D-3 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Capability mismatch behavior is fail-loud: `UnsupportedByTarget` naming entity + feature. Silent degradation is forbidden.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/spec/quality.py` `src/bloomery/transforms/_builtins.py` `tests/property/test_compile_properties.py` `tests/unit/test_emit/test_base.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_quality/test_text_rules.py` `tests/unit/test_transforms/test_builtins.py`

### S-0025/D-4 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

SQL rendering: SQLGlot AST → `DialectPort.render`; Jinja only ever sees pre-rendered strings (envelope templating).

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/emit/steps.py` `tests/property/test_compile_properties.py` `tests/unit/test_steps/test_dbt_and_cube_emission.py`

### S-0025/D-18 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

*(2026-08-11)* **The dbt target defines the generic test it declares; the emitted project depends on no package.** D16's dbt half had to name *some* vehicle for `min`/`max`/`regex`/`reconcile`, and the only one dbt offers is `dbt_utils.expression_is_true` — which D16 itself noted "is a package, not core" without following the consequence. The consequence is that bloomery emitted a project **declaring a test it did not define**: `dbt compile` stops at ``'dbt_utils' is undefined. … install package dependencies with "dbt deps"``, for every project carrying one of those four clauses. Two fixes were available — emit a `packages.yml` pinning `dbt-labs/dbt_utils`, or define the test — and the second wins on the thing this compiler is for: artifacts are a pure function of the specs (S-0020), and a `packages.yml` makes the output complete only after a *network fetch* the compiler is forbidden from performing and the consumer may not be able to perform at all. So `macros/bloomery_expression_is_true.sql` is emitted, iff `schema.yml` declares the test. Three things follow. **It is `ArtifactKind.AUDIT`, not `CONFIG`** — it is the custom audit *body* for this target, the exact counterpart of the `audits/<name>.sql` file SQLMesh gets for the same kinds and from the same `audit_predicate`, which makes D16's "one function, two forms" symmetry structural rather than incidental. **The body is `dbt_utils`' `default__test_expression_is_true` minus the `column_name` branch bloomery never takes**, so the replaced semantics are preserved exactly — including that a NULL expression *passes*, `NOT NULL` being NULL and selecting no row, which is S-0033/D-19's Kleene discipline arrived at from dbt's side. **The emission condition reads the emitted schema rather than re-deriving the entity filter**, so the project can neither declare the test without the macro nor carry it unused, and a test pins both directions.

- Paths: `src/bloomery/emit/dbt/__init__.py` `tests/e2e/test_dbt_parse.py` `tests/property/test_compile_properties.py` `tests/unit/test_emit/test_dbt.py`

### S-0025/D-20 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

*(2026-08-11)* **The dbt target emits a real DAG, and keeps the naming policy owning namespaces. S-0026/D-22 is closed — with both of its candidates, not one.** D22 found `dbt build` could not pass: models named their inputs literally (`FROM silver.order_item`), so dbt had no edges to order them by *and* materialized each into the profile's target schema while the `FROM` clause said `silver`. It offered two fixes with an "or" between them, and the "or" was the mistake — **neither is sufficient alone, and each repairs the other's cost.** `+schema` config alone places the relations and leaves ordering absent, so a gold model still races its silver input. `ref()`/`source()` alone orders the DAG but resolves names through dbt's schema config, which is the objection D22 raised: the naming port stops owning the namespace. Together: `ref()` for every relation bloomery emits and `source()` for bronze, `+schema: <ns>` per model directory, and a `generate_schema_name` override returning the configured schema **verbatim** — because dbt's default returns `<target.schema>_<custom>`, which would put models in `main_silver` while `sources.yml` (which never passes through that macro) still said `bronze`, honouring the policy in half the project. **How it is emitted.** Shared lowering is untouched: both targets build inputs as `exp.table_(relation, db=namespace)`, and the dbt emitter rewrites *table nodes only*, mapping `(namespace, relation)` to a reference. A namespace-less table is never rewritten, which is what keeps a CTE reference from being mistaken for a model; a table the map does not know is left literal rather than guessed at, because inventing a `ref()` for a relation bloomery did not write would name a model dbt cannot find. An SCD2 entity resolves to its **snapshot**, the only thing this target builds for it. **The cost, stated.** D5's port-abstraction proof compared the two targets' SELECTs byte for byte and can no longer: the `FROM` clauses differ by construction. It is restated, not weakened — resolve the references, drop namespaces, and the SQL is identical on every projection, join, cast and dialect quirk, so the entire difference between the targets is one documented substitution. The namespaces the comparison erases are asserted separately, against the `+schema` config and the override.

- Paths: `src/bloomery/emit/dbt/__init__.py` `tests/e2e/test_dbt_parse.py` `tests/property/test_compile_properties.py` `tests/support/compiling.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_quality_mart.py`

### S-0030/D-7 — `ASSUMED` (MetricFlow backend: manifest emitter and planner adapter)

`planner/names.py` owns the bidirectional bloomery↔dunder mapping (`{entity}__{dim}`, `{entity}__{time_dim}__{grain}`, `metric_time__{grain}`, `-metric` for desc), keyed on the **primary entity** name (not the semantic model name). Callers never see dunder names. `metric_time` is reserved, rejected at spec validation. Property test: every emitter-produced dimension round-trips through `names.py`.

- Paths: `src/bloomery/planner/names.py` `src/bloomery/planner/result.py` `tests/property/test_metricflow_properties.py` `tests/property/test_planner_properties.py` `tests/unit/test_planner/test_names.py`

### S-0030/D-8 — `ASSUMED` (MetricFlow backend: manifest emitter and planner adapter)

Filters (Jinja `where_constraints`) are the highest-risk surface: values never interpolated raw — typed per-dialect literal renderer or bind parameters; dimension names only from validated `DimensionRef`s via `names.py`; values type-checked against the dimension (`FilterTypeMismatch`); `contains`/`like` escape wildcards. Adversarial fuzz property test (injection strings, template syntax, unicode quotes, newlines) asserts parsed-SQL predicate structure unchanged and scanned relations exactly the expected mart — **merge-blocking**. *(Superseded by D16 — see §5.6 note.)*

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/planner/filters.py` `src/bloomery/planner/request.py` `tests/property/test_planner_properties.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_planner/test_filters.py`

### S-0032/D-5 — `ASSUMED` (Query vocabulary: filters, sort, pagination)

**D-Q5:** string-carrier scalars — `str` operands on ordering operators are parsed and validated against the resolved dimension's `LogicalType` at request-validation time, before any rendering: invalid → `FilterTypeMismatch`, non-finite → `InvalidLiteral`; **no SQL cast is ever emitted** (rendered literals are already in the dimension's type). `NaN`/`Infinity`/`-Infinity` refused even though they parse as `Decimal` — `lt "NaN"` fails open on Postgres and matches every row. `UUID` renders as a string literal against string-typed dimensions; no UUID `LogicalType` is added.

- Paths: `src/bloomery/errors.py` `src/bloomery/planner/filters.py` `src/bloomery/planner/parse.py` `src/bloomery/planner/request.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `tests/execution/test_period_over_period.py` `tests/property/test_planner_properties.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_planner/test_filters.py` `tests/unit/test_planner/test_request.py` `tests/unit/test_spec/test_metrics.py` `tests/unit/test_spec/test_quality.py`

### S-0033/D-67 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **A `fail` rule's audit covers two populations, not one.** D32 moved the body off `@this_model` and onto the pre-route staged extract, which fixed the precedence inversion and, in the same move, stopped covering the rows *already in the entity*. That population is not empty and is not reachable from bronze: a **replayed** row is merged in from the reject table, and its bronze source has aged out of the incremental window by construction — that is the entire premise of `replay_scope` (§5.7). Reproduced end to end: after a widening plus a replay, a row sat in silver whose own `_quality_flags` recorded the blocking rule firing while that rule's audit reported **zero** violating rows — a model contradicting its own data, which is worse than an unchecked population because it reads as coverage. The body is now `pre-route extract UNION @this_model`, exactly two relations, inside D29's limit (`referential` cannot carry `fail`, D6). `UNION` rather than `UNION ALL`: the ordinary violator is in both populations and reporting it twice says nothing extra. The entity leg reads the **recorded** verdict — `_quality_flags` carries FAIL names since D32 — rather than re-deriving the predicate over model columns, which is forced: over the model the coercion marker's source conjuncts are gone and `coercible` would silently re-define itself as `not_null`, the very special case D32 retired. Recorded price: the leg covers rows evaluated under the *current* spec, and a rule added or renamed classifies RESTATING (D11), whose backfill is what re-derives the flags. Replay deliberately does **not** filter `fail` rules out of its MERGE — refusing to merge them would be quarantine outranking fail again, the inversion D32 exists to prevent; the row lands, and the audit is what stops the next run.

- Paths: `src/bloomery/emit/dbt/__init__.py` `tests/execution/test_quarantine_replay.py` `tests/property/test_compile_properties.py` `tests/unit/test_emit/test_dbt.py`

### S-0034/D-51 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-09)* **A macro declares its signature; it is never read off its body.** The first cut inferred the signature from the body's `:name` placeholders. That is the third appearance of one temptation, and it is refused for the third time — D43 refused fabricating references from matching key columns, D49 refused auto-linking canonical fields by name. The deciding argument is the ladder itself: Tier 0's `TransformSpec` declares `input_domain` **and** `output_type`, so a macro declaring neither would be the one tier whose inputs nothing checks, while §5.1's table claims Tier 1 can *parse and typecheck*. `StepManifest` gains `accepts: {column: type}` — a separate key from `inputs:`, which is relation-shaped for table steps, because one key meaning two things by kind reads fine only to whoever wrote it. The output type needs no new field: a macro has exactly one output of exactly one column (D18b). This buys three things. The **body** is checked against the declaration once, at the registry, where a disagreement is the platform's bug rather than a puzzle handed to every call site. The **call site** is checked against the declaration, so the message names what the macro expects instead of only which placeholder was unfilled. And a **chain** is typechecked *around* the link: the run before it against what it accepts, the run after it from what it produces — implemented as segments queued into the ordinary batch stage, so S-0023/D-2's one-aggregate property survives for chains containing a macro. Named cost, recorded rather than discovered: a genuinely polymorphic macro (`COALESCE(:a, :b)` over any type) must now pick a concrete type. Tier 0 carries the identical constraint through `input_domain`, so it is consistent rather than a new tax — but it is a real limit. A chain link must accept exactly one column, since a chain carries one running value; a two-column macro is refused there and pointed at the field shape.

- Paths: `src/bloomery/resolve/build.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/mapping.py` `tests/golden/schema/mapping.json` `tests/property/test_schema_agreement.py` `tests/unit/test_resolve/test_declared_zone.py` `tests/unit/test_schema.py`

### S-0037/D-2 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**Every closed set appears in the schema as an `enum`**, never a free string: transforms, quality rules, `Op`, `LogicalType`, `OnFail`, `Additivity`, document versions. This is the property constrained generation depends on — a proposer choosing from an enum cannot invent a transform, so the refusal that would catch the invention never fires. Unit-tested per set.

- Paths: `src/bloomery/schema.py` `tests/golden/test_spec_schemas.py` `tests/property/test_schema_agreement.py` `tests/unit/test_schema.py`

### S-0037/D-10 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**A property test measures schema/parser agreement** rather than assuming it: every fixture validates against its schema, and mutations the parser rejects are checked against the schema too, with divergences recorded as amendments. The schema is a pre-filter, never the authority — two validators over one grammar drift, and undetected drift reads to a user as arbitrariness.

- Paths: `src/bloomery/spec/exports.py` `src/bloomery/spec/imports.py` `tests/property/test_schema_agreement.py` `tests/unit/test_spec/test_exports.py` `tests/unit/test_spec/test_imports.py`

### S-0049/D-1 — `LOCKED` (Mapping identity)

**The identity is the document name.** It is unique by construction (a key of the `sources` mapping), already computed, already the ordering key for `Project.mappings`, and already the user-facing coordinate for refusals (S-0019/source-paths). Consequence: identity is a filename, so a rename changes it — accepted under D4's boundary.

- Paths: `src/bloomery/evidence.py` `src/bloomery/resolve/resolution.py` `src/bloomery/spec/common.py` `src/bloomery/spec/mapping.py` `tests/property/test_schema_agreement.py` `tests/unit/test_resolve/test_resolution.py` `tests/unit/test_spec/test_mapping.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0049/D-3 — `LOCKED` (Mapping identity)

**`document` is set by the loader and is not part of the YAML vocabulary.** A document declaring its own name is a second source of truth that can disagree with the first. Consequence: `Mapping` cannot be constructed from YAML alone in a test without the loader — which is already how every test builds one.

- Paths: `src/bloomery/spec/common.py` `src/bloomery/spec/mapping.py` `tests/property/test_schema_agreement.py` `tests/unit/test_guardrails/test_operands.py` `tests/unit/test_spec/test_mapping.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0060/D-2 — `LOCKED` (dbt as a complete quality target)

The incremental and first-run bodies are **two pre-rendered SELECTs** chosen by `{% if is_incremental() %}` in the envelope. Never one SELECT with Jinja spliced into it: S-0025/D-4's rule is that envelopes interpolate rendered strings, and a conditional inside a rendered string is a template no dialect port ever saw.

- Paths: `src/bloomery/emit/dbt/__init__.py` `tests/e2e/test_dbt_parse.py` `tests/property/test_compile_properties.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
