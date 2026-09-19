<!-- torve:managed src/bloomery/spec — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/spec/`

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

### S-0007/D-1 — `LOCKED` (Dimension algebra)

Every relation is declared, never inferred — not from column names, not from cardinality, not from the data. One `GROUP BY` would answer `determines:` exactly, and from a single load of a source that has no counterexample yet; an inference cannot be told from a declaration once written down

- Paths: `src/bloomery/spec/entity.py` `src/bloomery/spec/catalog.py` `src/bloomery/semantic/closure.py`
- Consequence: A relation has exactly the standing of a declared `many_to_one`: the compiler reads what an author wrote and never looks at a row, so nothing in the closure or the spec models may consult data or guess from a name
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0007/D-3 — `LOCKED` (Dimension algebra)

A dimension is not an entity. Modelling `city` and `state` as entities with a declared `many_to_one` would reuse R002 exactly and is rejected: it taxes a two-column fact with a grain, a key and a mapping, and it puts every hierarchy level into the lineage graph as a node nobody builds

- Paths: `src/bloomery/spec/entity.py` `src/bloomery/semantic/closure.py`
- Consequence: The column-to-column determination needs its own fact and its own closure; the entity-keyed machinery is not extended to carry it, and a project with a five-level geography gains no entities
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0007/D-4 — `ASSUMED` (Dimension algebra)

Determination is a lattice, not a list. A column may determine several others independently, and `postcode` determining both `state` and `delivery_zone` is the ordinary case rather than the exotic one

- Paths: `src/bloomery/spec/entity.py` `src/bloomery/spec/catalog.py`
- Consequence: `determines:` is a set of names on the determinant and is transitively closed by the compiler; departing means an ordered-levels spelling, which is smaller, cannot express a lattice, and restates the same fact on every mart that carries the columns

### S-0007/D-5 — `ASSUMED` (Dimension algebra)

`role_of:` generalizes `DateRoleStep` rather than replacing it. A date's roles expand into buckets, which is a date-specific elaboration, so the two coexist

- Paths: `src/bloomery/spec/marts.py` `src/bloomery/ir/nodes.py`
- Consequence: Existing projects with `flatten: [{date: …, role: …}]` compile unchanged and the general role is additive beside them; departing means absorbing dates into the general vocabulary, which touches every existing project

### S-0007/D-6 — `OPEN` (Dimension algebra)

Whether `determines:` lives on the entity model or on the catalog's canonical field. A determination is a property of values rather than of a feed, which argues for the catalog; the entity model is where fields are otherwise described. The executor decides against the shape of both and logs it

- Paths: `src/bloomery/spec/entity.py` `src/bloomery/spec/catalog.py`
- Consequence: The placement decides where the parse, the cycle refusal and the transitive closure live, and whether a determination is stated once per catalog field or once per entity that maps it

### S-0007/D-8 — `OPEN` (Dimension algebra)

Whether `same_as:` is needed at all. The in-project case is derivable from `role_of:` and the cross-project case has no consumer until multi-project composition reaches its emitted-reference phase. If both hold, this relation is not built

- Paths: `src/bloomery/spec/marts.py`
- Consequence: Phase 3 exists only if this resolves that the relation is needed; resolving it the other way retires the relation and the document can complete on the first two phases

### S-0019/D-2 — `ASSUMED` (Spec layer and error model)

Loaders are pure text-in: `load_catalog(text)`, `load_project(sources: Mapping[str, str])`. No path/file API will be added to the core package — I/O belongs to callers.

- Paths: `src/bloomery/spec/project.py`

### S-0019/D-3 — `ASSUMED` (Spec layer and error model)

Every raisable failure derives from `BloomeryError` and carries `source_path`; all error classes are declared in `bloomery/errors.py` so `except BloomeryError` needs one import. Pydantic/yaml exceptions never escape.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/quality.py` `src/bloomery/spec/common.py`

### S-0019/D-4 — `ASSUMED` (Spec layer and error model)

Parse validates shape and grammar only; reference existence (entities, transforms, canonical fields) is deferred to resolve/typecheck. Consequence: a shape-valid spec with dangling references parses fine — callers must run `resolve` to trust it.

- Paths: `src/bloomery/marts/flatten.py` `src/bloomery/resolve/refs.py` `src/bloomery/spec/__init__.py` `src/bloomery/spec/entity.py` `src/bloomery/spec/mapping.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `tests/golden/schema/metrics.json` `tests/property/test_schema_agreement.py` `tests/unit/test_spec/test_entity.py`

### S-0019/D-5 — `ASSUMED` (Spec layer and error model)

PyYAML (`safe_load` + duplicate-key rejection) is added as a runtime dependency.

- Paths: `src/bloomery/spec/common.py`

### S-0019/D-6 — `ASSUMED` (Spec layer and error model)

Parse-stage errors are batched per document (all failures reported at once).

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/errors.py` `src/bloomery/evidence.py` `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/build.py` `src/bloomery/resolve/refs.py` `src/bloomery/spec/common.py` `src/bloomery/spec/project.py` `src/bloomery/typing/check.py` `tests/unit/test_cli.py` `tests/unit/test_evidence.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_refs.py` `tests/unit/test_spec/test_mapping.py` `tests/unit/test_spec/test_project.py` `tests/unit/test_spec/test_sql_text.py`

### S-0019/D-7 — `ASSUMED` (Spec layer and error model)

`materialization` is explicit-with-derived-default (settles original open question #4); the resolved value is IR-recorded and diffable.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/ir/nodes.py` `src/bloomery/marts/flatten.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/entity.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_entity.py`

### S-0019/D-8 — `ASSUMED` (Spec layer and error model)

Catalog is passed separately from `Project` (vertical-level vs tenant-level), matching spec §8's `compile_project(..., catalog=...)`.

- Paths: `src/bloomery/cli/io.py` `src/bloomery/schema.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/project.py` `tests/property/test_schema_agreement.py`

### S-0019/D-9 — `ASSUMED` (Spec layer and error model)

(Amended for `_bloomery-changes.md`) A fifth spec kind `marts:` joins the four (S-0027); `semi_additive` metrics carry a typed `SemiAdditivePolicy` and `non_additive` metrics a `RatioSpec` (S-0028/D-5). Spec-layer scope is still shape/grammar only.

- Paths: `src/bloomery/spec/common.py` `src/bloomery/spec/marts.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_spec/test_metrics.py`

### S-0019/D-10 — `ASSUMED` (Spec layer and error model)

(Amended for `_bloomery-metricflow-pivot.md`) `metric_time` is a reserved dimension/field name, rejected at spec validation with a clear message (S-0030 R4). The `Metric` model reserves optional `cumulative:` (window / grain_to_date) and derived-expression forms lowered per S-0030's mapping table; both are additive spec surface, parse-validated only.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/spec/common.py` `src/bloomery/spec/entity.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `tests/golden/schema/catalog.json` `tests/golden/schema/entity_model.json` `tests/golden/schema/marts.json` `tests/golden/schema/metrics.json` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_spec/test_metrics.py`

### S-0019/D-14 — `ASSUMED` (Spec layer and error model)

*(2026-08-12)* **An entity or mart name is an identifier, because it reaches the model envelope and nothing there quotes it.** Both were unconstrained — `entities: dict[str, Entity]`, and marts under `MemberName`, which only rejects reserved words. Field names travel a *different* path and were always safe: they reach SQL through SQLGlot, which quotes them and doubles an inner quote, verified by compiling a field named `amt") OR 1=1 --` and reading the escaped identifier back out. A **relation** name also reaches the SQLMesh `MODEL (...)` block, which is Jinja over pre-rendered strings (D4) and quotes nothing, so an entity named `t"; DROP TABLE x --` emitted `name silver.t"; DROP TABLE x --,` into the model definition verbatim. Fixed at the spec layer with `^[a-z][a-z0-9_]*$` rather than by escaping at the envelope, on the same reasoning that pins `StepRef`: a relation name has no business carrying anything but identifier characters, and a pattern refuses at the source path where the author can act on it instead of silently mangling the artifact. Step output bindings were already covered by `RELATION_PATTERN`; metric names do not become relations. Every name in the fixture corpus already matched, so the constraint documents existing practice rather than narrowing it.

- Paths: `src/bloomery/spec/common.py` `tests/unit/test_spec/test_relation_names.py`

### S-0020/D-5 — `ASSUMED` (Intermediate representation and determinism contract)

Floats are banned in IR and emission; `Decimal`/int only.

- Paths: `src/bloomery/cli/serialize.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/steps.py` `src/bloomery/ir/fingerprint.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/request.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/common.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `src/bloomery/steps/manifest.py` `src/bloomery/steps/splice.py` `src/bloomery/transforms/_builtins.py` `src/bloomery/typing/types.py` `tests/execution/test_as_of_join.py` `tests/execution/test_currency_convert.py` `tests/execution/test_fanout_trap.py` `tests/execution/test_marts.py` `tests/execution/test_period_over_period.py` `tests/execution/test_rollup.py` `tests/fixtures/semantic_corpus/002-average-of-averages/naive.sql` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/golden/schema/marts.json` `tests/support/planning.py` `tests/support/semantic_corpus.py` `tests/unit/test_cli.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_planner/test_request.py` `tests/unit/test_quality/test_edges.py` `tests/unit/test_spec/test_metrics.py` `tests/unit/test_spec/test_quality.py` `tests/unit/test_steps/test_lowering.py` `tests/unit/test_steps/test_manifest_and_registry.py` `tests/unit/test_typing/test_types.py`

### S-0022/D-2 — `ASSUMED` (Resolution: dependency DAG, recipes, reachability)

The compiler never chooses a recipe. The mapping's recorded `recipe:` id is validated — id exists on the catalog field, every `requires` name bound by the mapping's `from` aliases (exactly) — else `ResolutionError`. Choice happens upstream; the compiler reproduces it (determinism + auditability, spec §3.4). Consequence: catalog evolution can invalidate recorded choices, and that is a loud error, not a silent re-choice.

- Paths: `src/bloomery/evidence.py` `src/bloomery/guardrails/operands.py` `src/bloomery/resolve/recipes.py` `src/bloomery/resolve/resolution.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/mapping.py` `tests/golden/schema/catalog.json` `tests/golden/schema/mapping.json` `tests/unit/test_resolve/test_edge_shapes_offcorpus.py` `tests/unit/test_resolve/test_recipes.py`

### S-0023/D-7 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Path conflict does not raise (`PathConflict` is not an error class): the compiler emits the derived column, a `<name>__direct` shadow, and a `RECONCILE` `AuditIR`. The forbidden thing is the silent choice; both paths are valid, so the refusal targets the silence, not the spec.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/quality.py` `src/bloomery/ir/lower.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/mapping.py` `tests/fixtures/path_conflict/entity_model.yaml` `tests/fixtures/path_conflict/mapping.yaml` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_ir/test_lower.py` `tests/unit/test_spec/test_mapping.py`

### S-0023/D-8 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Range sanity: the guardrail stage validates `assert:` clauses for well-typedness against the field's `LogicalType` only (`AssertLoweringError`); lowering to target-native audits happens via `AuditIR` at emit (S-0020, S-0025).

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/asserts.py` `src/bloomery/guardrails/stage.py` `src/bloomery/quality/predicates.py` `src/bloomery/spec/entity.py` `src/bloomery/spec/quality.py` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/unit/test_guardrails/test_asserts.py` `tests/unit/test_guardrails/test_quality.py`

### S-0024/D-3 — `ASSUMED` (Plan: spec diff and change classification)

Renames are explicit only: `renamed_from: <old>` in the spec (carried as `ColumnIR.renamed_from`, an S-0020 amendment). No heuristic inference — determinism and auditability beat convenience. A stale annotation (old name absent from `old`, including `old is None`) raises `RenameTargetMissing` (`PlanError`), which forces the annotation to be dropped after one applied plan.

- Paths: `src/bloomery/errors.py` `src/bloomery/plan/diff.py` `src/bloomery/plan/model.py` `src/bloomery/spec/entity.py` `tests/fixtures/evolution_v3/entity_model.yaml` `tests/golden/schema/entity_model.json` `tests/property/test_plan_properties.py` `tests/unit/test_plan/test_diff.py` `tests/unit/test_plan/test_evolution.py`

### S-0025/D-3 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Capability mismatch behavior is fail-loud: `UnsupportedByTarget` naming entity + feature. Silent degradation is forbidden.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/spec/quality.py` `src/bloomery/transforms/_builtins.py` `tests/property/test_compile_properties.py` `tests/unit/test_emit/test_base.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_quality/test_text_rules.py` `tests/unit/test_transforms/test_builtins.py`

### S-0025/D-7 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Quarantine is an emitter convention (`<entity>__quarantine` artifact), not IR surface (settles #5; revisit on a second policy consumer).

- Paths: `src/bloomery/spec/mapping.py` `src/bloomery/transforms/_builtins.py`

### S-0025/D-13 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

(Reverses D6) Bloomery owns the date dimension: one catalog definition emits both the SQLMesh `gold.dim_date` model and the MetricFlow time-spine declaration (S-0030 R1). D6's demand-gate is satisfied — MetricFlow is the demand.

- Paths: `src/bloomery/emit/lower/marts.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/metrics.py` `tests/execution/test_marts.py` `tests/fixtures/ecom_basic/catalog.yaml` `tests/golden/schema/catalog.json` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_fixtures.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_metrics.py`

### S-0027/D-3 — `ASSUMED` (Marts and role-playing dimensions)

`flatten` via-steps require declared `many_to_one`/`one_to_one` relationships (else `FanoutRisk`); chains flatten transitively in authored order; prefixes mandatory; collisions are errors, never auto-renames.

- Paths: `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `src/bloomery/spec/marts.py` `tests/golden/schema/marts.json` `tests/unit/test_marts/test_flatten.py` `tests/unit/test_spec/test_marts.py`

### S-0027/D-4 — `ASSUMED` (Marts and role-playing dimensions)

Date roles expand to exactly `{day, week, month, quarter, year}` bucket columns named `<role>_<bucket>`; `hour` is deliberately not expanded.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/lower/marts.py` `src/bloomery/marts/flatten.py` `src/bloomery/planner/coverage.py` `src/bloomery/planner/request.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `tests/golden/schema/marts.json`

### S-0027/D-7 — `ASSUMED` (Marts and role-playing dimensions)

Marts are optional: a project without a `marts:` document compiles silver only; the planner then refuses everything with `UnreachableAtGrain` (no marts, no serving surface).

- Paths: `src/bloomery/marts/flatten.py` `src/bloomery/spec/marts.py` `tests/golden/schema/marts.json`

### S-0027/D-8 — `ASSUMED` (Marts and role-playing dimensions)

`cost_hint` (int, default 1) is a tie-breaking scan-cost hint only; selection ties break lexicographically (S-0020 determinism).

- Paths: `src/bloomery/emit/lower/marts.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/spec/marts.py` `tests/golden/schema/marts.json` `tests/unit/test_emit/test_metricflow.py` `tests/unit/test_planner/test_coverage.py`

### S-0028/D-5 — `ASSUMED` (Native planner: MetricRequest → QueryPlan)

Additivity lowering per D4 exactly: additive → SUM at requested grain; semi-additive (`SemiAdditivePolicy(over, rule ∈ last/first/avg/max/min)`) → sum across every dimension except `over`, rule along `over` (coarser requested grain: rule within each bucket, then sum); non-additive → never stored/summed, recomputed from additive components (`RatioSpec` → `SUM(num)/NULLIF(SUM(den),0)`); missing components = `NonAdditiveWithoutComponents` at resolution/guardrail stage (S-0023 defense-in-depth).

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/coverage.py` `src/bloomery/planner/explain.py` `src/bloomery/planner/result.py` `src/bloomery/spec/common.py` `tests/fixtures/non_additive_aov/marts.yaml` `tests/fixtures/non_additive_aov/metrics.yaml` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_planner/test_coverage.py`

### S-0032/D-5 — `ASSUMED` (Query vocabulary: filters, sort, pagination)

**D-Q5:** string-carrier scalars — `str` operands on ordering operators are parsed and validated against the resolved dimension's `LogicalType` at request-validation time, before any rendering: invalid → `FilterTypeMismatch`, non-finite → `InvalidLiteral`; **no SQL cast is ever emitted** (rendered literals are already in the dimension's type). `NaN`/`Infinity`/`-Infinity` refused even though they parse as `Decimal` — `lt "NaN"` fails open on Postgres and matches every row. `UUID` renders as a string literal against string-typed dimensions; no UUID `LogicalType` is added.

- Paths: `src/bloomery/errors.py` `src/bloomery/planner/filters.py` `src/bloomery/planner/parse.py` `src/bloomery/planner/request.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `tests/execution/test_period_over_period.py` `tests/property/test_planner_properties.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_planner/test_filters.py` `tests/unit/test_planner/test_request.py` `tests/unit/test_spec/test_metrics.py` `tests/unit/test_spec/test_quality.py`

### S-0033/D-1 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

The governing principle: **specs describe, specs reference implementations, specs never contain implementations.** Bronze gets no cleansing (replay source); gold gets none (rebuildable).

- Paths: `src/bloomery/spec/quality.py` `tests/fixtures/dirty/README.md` `tests/golden/schema/mapping.json`

### S-0033/D-2 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

`OnFail = flag | quarantine | fail` (v1 — `repair` deferred, decision 17; landed in D87), explicit per rule, never a global default. Deliberately no `drop`: quarantine is drop plus recoverability; deletion happens via retention policy, with a paper trail.

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/spec/quality.py` `tests/unit/test_ir/test_nodes.py` `tests/unit/test_plan/test_quality_changes.py` `tests/unit/test_spec/test_quality.py`

### S-0033/D-3 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Coercion failure is a rule: transform chains lower to failure-marker form (`TRY_CAST`-style per dialect); the implicit, overridable `coercible` rule (default `quarantine`) disposes of it. Retires `Mapping.on_unmapped_enum` (S-0019 amendment — absorbed into `in_enum`/`coercible`) and supersedes S-0025/D-7's never-implemented emitter convention with the modeled reject table.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/guardrails/operands.py` `src/bloomery/quality/predicates.py` `src/bloomery/spec/mapping.py` `src/bloomery/spec/quality.py` `src/bloomery/transforms/_builtins.py` `tests/execution/test_path_conflict.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_spec/test_mapping.py`

### S-0033/D-5 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Closed field-rule catalogue: `coercible`, `not_null`, `range`, `length`, `pattern` (portable regex subset, compile-time validated per target dialect via sqlglot), `in_enum`, `in_set`, `normalize` and `charset` (added by D86, which closed D26), `unique` (evaluated per partition slice in both full and incremental modes — the partition is the scope unit either way; cross-partition duplicates out of scope in every mode, dedupe's job; sampling rejected per Document 5 §11.3). New rules are RFC amendments, not config.

- Paths: `src/bloomery/quality/catalogue.py` `src/bloomery/quality/pattern.py` `src/bloomery/quality/predicates.py` `src/bloomery/quality/reconcile.py` `src/bloomery/spec/quality.py` `src/bloomery/spec/steps.py` `tests/golden/schema/mapping.json`

### S-0033/D-6 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Entity-level `dedupe` requires `tie_break` under `keep: latest_by` (nondeterministic winners violate the core invariant); dedupe-referenced fields' `coercible` is forced to `fail`. Row rules `expression` and `referential` (`on_missing ∈ {unknown_member, quarantine, flag}` — `fail` deliberately excluded: orphans are an expected, recoverable data condition; a pipeline-stopping orphan gate is a `reconcile` check; `unknown_member` keeps aggregates correct via a reserved member row and requires a string-typed fk in v1 — the reserved member is the string `'__unknown__'`; a non-string fk with `unknown_member` is a compile-time `GuardrailError` naming the alternatives, typed per-key sentinels rejected); `reconcile` blocks emit model + non-blocking audit.

- Paths: `src/bloomery/errors.py` `src/bloomery/quality/catalogue.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/quality.py` `tests/unit/test_spec/test_quality.py`

### S-0033/D-9 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Silver gains `_quality_flags`/`_quality_ok`; marts gain `has_quality_flags` (S-0027 amendment). Array capability is `DialectFeature.ARRAY` — an engine property, deliberately diverging from Document 5's `TargetCapabilities` placement; dialects without it lower to a delimited string.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/marts/flatten.py` `src/bloomery/spec/common.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_steps/test_lowering.py`

### S-0033/D-13 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

The guardrail boundary (§5.9) is normative: guardrail = the model is wrong, compile time; quality rule = the data is wrong, run time. Nothing decidable from the spec alone enters `quality/`.

- Paths: `src/bloomery/guardrails/metrics.py` `src/bloomery/quality/__init__.py` `src/bloomery/spec/quality.py`

### S-0033/D-21 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Ingestion metadata contract: entities using `quarantine` or `dedupe` require bronze `_load_id`, `_ingested_at`, `_source_row_id` (a stable per-source-row identity supplied by the ingestion layer, **NOT NULL and unique per source row** — data properties no compiler can check, so the lowering emits a generated **blocking audit** on the metadata columns: a null or duplicated `_source_row_id` stops the run); column absence is the new compile error `IngestionMetadataMissing` (`GuardrailError` leaf, `errors.py` per S-0019/D-3). `reject_id` = sha256 over the length-prefixed utf-8 **pair** (`source_relation`, `_source_row_id`) — canonical serialization per the S-0020 canon-bytes doctrine. This supersedes the triple this row first carried (this round's own earlier decision): `_load_id` is removed from the identity and becomes an attribute (the latest observing load) — re-deliveries of the same source row across loads must land on the **same** reject row (that is what `first_seen`/`last_seen` track); a per-load identity would mint a new row per retry and violate replay idempotence. A re-delivery updates `last_seen`/`_load_id`/`failed_rules` on the existing row.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/quality.py` `src/bloomery/quality/catalogue.py` `src/bloomery/quality/dedupe.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/transforms/_builtins.py` `tests/e2e/test_dbt_parse.py` `tests/e2e/test_sqlmesh_project.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_dedupe_and_audits.py` `tests/execution/test_merged_cleaning.py` `tests/execution/test_zoneless_utc.py` `tests/fixtures/dirty/README.md` `tests/fixtures/semi_additive_inventory/mapping.yaml` `tests/support/execution.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_trino.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_entity.py`

### S-0033/D-23 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

`_quality_flags` **and** `failed_rules` share one physical contract: rule names identifier-constrained at parse (no escaping in any lowering); the column is never NULL (empty array / empty delimited string per `DialectFeature.ARRAY`); delimited fallback joins with `,` in lexicographic rule-name order; `_quality_ok` generated per shape; flag-set equality across lowerings asserted in the dialect-matrix tier. The reject table's `failed_rules` lowers by exactly this contract — array where `DialectFeature.ARRAY`, else the lexicographic comma-delimited string.

- Paths: `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/spec/quality.py` `tests/engines/test_merged_cleaning_engines.py` `tests/unit/test_quality/test_flags.py` `tests/unit/test_spec/test_quality.py`

### S-0033/D-38 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **`reconcile.on_fail` is not a label.** All three values emitted the same non-blocking audit while the quality mart reported `disposition = 'fail'`. `fail` now emits a **blocking** audit — §5.3 nominates reconcile as the pipeline-stopping gate, and that sentence is only true if the value blocks; `flag` stays non-blocking so a disagreement does not withhold the comparison table; `quarantine` lowers non-blocking because a reconcile routes no row, and refusing the value belongs to the spec surface where `on_fail` is typed.

- Paths: `src/bloomery/spec/marts.py`

### S-0033/D-86 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **The catalogue gains `normalize` and `charset`, and the confusables table is deliberately not among them. D26 is closed.** D26 offered "a Unicode normal form **and/or** a confusables table"; only the first half is built as offered. `normalize` is `NORMALIZE(col, NFC) <> col` — the dialect-neutral node, rewritten to `NFC_NORMALIZE` inside DuckDB's `render` because DuckDB has that function and no `NORMALIZE`, while SQLGlot's duckdb generator renders one verbatim (the D83 shape: renders everywhere, defined in two places out of three). One form only: Postgres and Trino spell all four, DuckDB spells one, and a rule that compiles everywhere and runs on two engines out of three is what S-0025/D-3 exists to refuse. It is a **rule and never a transform** — normalizing silently would rewrite what a source delivered, which D1 forbids. **The table is refused on determinism grounds:** UTS#39 confusables is versioned Unicode data, so embedding it would make a row's disposition depend on which Unicode revision the compiler shipped — an ambient input by another name (S-0020), and one that would move dispositions under a dependency bump nobody read as a semantic change. `charset` declares the admissible characters instead, as `U+` codepoints and inclusive ranges, exactly one of `allow:`/`forbid:`, lowering through a single `TRANSLATE(col, members, '')` read two ways. Codepoints rather than characters because every character the rule exists to catch is invisible: a literal one in YAML is unreadable in review and indistinguishable from a space in a diff. The `allow` reading turns out to be *stronger* than the table would have been for the case that motivated it — an allow-list of the script a column is written in catches a Cyrillic homoglyph, a fullwidth digit and an Arabic-Indic digit alike, none of which any denylist enumerates completely. Three declaration refusals, all decidable from the spec alone and so `GuardrailError`s: a backwards range, a range crossing the surrogate block (checked on the *span*, not the endpoints — the block is 2048 wide, so an endpoint-only check would leave the real refusal to arrive from `MAX_CHARSET_SIZE`, a constant that has nothing to do with surrogates and could grow), and a set past that cap, which exists because the members become a string literal in every row's predicate and in the IR fingerprint. `TRANSLATE` carries **no** `DialectFeature`: all three engines spell it identically and its delete-when-shorter behaviour was executed on each rather than assumed; a feature flag earns its place where the *port* has to differ, which is why `normalize` has one and this does not. Verified by execution on postgres 16 as a permanent engine tier and on `trinodb/trino:483` by hand (no Trino client dependency yet — S-0026's outstanding work), both agreeing with DuckDB on every specimen including the null. **Found on the way:** the §6 matrix rendered through `node.sql(dialect="duckdb")` rather than through the port, so it executed SQL the emitter never emits. Here that surfaced as a failure — DuckDB has no `NORMALIZE` at all — but the failure is incidental to the direction of this particular rewrite. A port rewrite that produces something the *direct* render also accepts would have diverged silently, with the matrix green on SQL no artifact contains. It is routed through the port now.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/duckdb.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/quality/charset.py` `src/bloomery/quality/predicates.py` `src/bloomery/spec/quality.py` `tests/engines/test_postgres_text_rules.py` `tests/golden/schema/mapping.json`

### S-0033/D-87 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **`repair` lands, its recipe is a registered `sql_macro`, and its marker is its own column. D17 is closed.** D17 gated the disposition on a repair-recipe contract and left §10 asking *inline vs catalog-referenced*. S-0034's step registry answers both at once: a recipe is `ref@version` into the registry — declared signature, `runtime_lock`, determinism tier, trust-then-verify — and D1 already holds that specs reference implementations and never contain them, so an inline recipe would have been a second, weaker copy of all of it reachable only from here. **The lowering.** The recipe is spliced at IR build, where the registry lives, and travels as SQL in the rule's params the way an `expression` rule's body does — so emission needs no registry, and a version or `runtime_lock` bump lands in the IR where the fingerprint and `plan()` see it (measured: a body change classifies RESTATING and puts the entity in `replay_scope`, because the kind's params define neither an ordered interval nor a membership set and D52's undecidable-means-replay applies). The rewrite happens at the **extract** level, inside the column's own projection: `CASE WHEN <violation over the raw expression> THEN <recipe> ELSE <raw> END`. That placement is what makes every other rule see the repaired value with no extra nesting, and it forces both halves to be rewritten to read the column's expression rather than its name, since the column is being defined in the same `SELECT`. **The marker.** `_quality_repairs` is a separate column, which was cubic's condition in review and is the right one: a rule is recorded there when its recipe *ran and worked* — it fired over the value as delivered and no longer fires over the value that replaced it. `_quality_flags` stays empty for a repaired row, so `has_quality_flags` keeps meaning **currently suspect** and no mart already asking that question changes its answer. Unlike the two universal columns it is emitted only where a repair rule exists: §12 budgeted the silver-schema churn once, and a third column empty for every project not using the feature is not worth re-opening every golden and fingerprint for. **`fallback` is required**, for the same reason `on_fail` is (D2): a recipe that ran and failed leaves the rule violated and the row is disposed of exactly as if no repair had been declared — the alternative, a still-broken value landing in silver marked as fixed, is the `drop` this RFC refuses wearing a friendlier name. **Refusals**, each a property of the declaration alone: `repair` on `coercible` (it fires *because* the projection is already NULL, so the recipe would be handed the NULL rather than the text that failed to cast — fixing a value before coercion is a Tier 1 macro in the mapping, and the message says so), on `unique` (a property of a population; no rewrite of one row makes a duplicate unique), on a row rule (no column to rewrite), two repair rules on one column (both rewrite the same projection, so which value survives would depend on authoring order and the second recipe would judge a value the first had changed), a recipe accepting more than one column (a rule has no `from:` map, and inventing one would make a rule a second mapping surface), and a column the dedupe order reads (dedupe runs *before* the field rules per D7, so the winner would be chosen on the value as delivered and then have that value rewritten underneath it — D6's reasoning exactly). Verified by executing the emitted pipeline over three rows — one the recipe fixes, one it cannot, one it must not touch — and by sabotage: disabling the recipe, and dropping the "did it run" conjunct from the marker, each fail the assertion that names them. **Not built:** `gold.mart_data_quality` gains no `rows_repaired`, so repairs are observable in silver and not in the quality mart. Recorded rather than implied — adding a measure changes the mart schema, and no demand has asked for it.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/lower.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/spec/quality.py` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/golden/schema/steps.json` `tests/unit/test_spec/test_quality.py`

### S-0033/D-89 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **Mart-level checks are assertions, not quality rules. §10's open question is settled by the disposition model.** §8 deferred them as "blurs into reconciliation" and §10 asked "reconcile-shaped or new surface?" — the answer is neither, and what decides it is not taste. §5.9 draws the boundary at what a verdict *does*: a quality rule disposes of a **row**. A mart row is derived — no `_source_row_id`, no bronze payload, no reject table, no replay — so there is nothing to quarantine, nothing to repair, and nothing to bring back; and a `reconcile` compares *two sides*, which "no month has zero revenue" is not. What is left is D4's other half, "alert me", so `assert:` on a mart declares `{measure, agg, by, min/max, on_fail}` and lowers to an audit the mart model names. `quarantine` and `repair` are absent from its `on_fail` rather than lowered to something weaker, so an author who wanted routing learns it at the surface instead of from a mart that silently only alerts; `fail`/`flag` map to blocking/non-blocking exactly as `reconcile.on_fail` does (D38). The aggregate vocabulary is deliberately the *same tuple* the reconcile grammar uses — both compute one number over a column so a human can be told it is wrong, and two lists that mean the same thing drift. Bounds ride in `params` as text through the D57 carrier, for the same reason. **Resolution is against the flattened column set**, not the base entity's: `ordered_month` exists only because a `date:` step made it, and it is precisely the column §10's example groups by. **The body** is `SELECT <by…>, <agg>(<measure>) FROM @this_model [GROUP BY <by…>] HAVING <bound comparison>` — the value beside the group, because a failure a human must open the warehouse to understand gets ignored. A bare `HAVING` with no `GROUP BY` is the whole-mart form; both shapes were executed on DuckDB, postgres 16 and `trinodb/trino:483` rather than read out of three manuals, and all three agree. **What it cannot see, stated rather than implied:** D19 reaches the mart, so every aggregate but `count` is NULL over an empty group and the assertion stays silent — which is also why an assertion cannot notice a month that is *entirely missing*: no row means no group at all. `count` is the exception and is the one shape that catches an empty mart. Closing the missing-period case needs a join against the date spine, a coverage check with its own dependency, and it is named here rather than half-built. **dbt refuses a project carrying one**, sharing `refuse_steps`' message shape (**amended by D94**: this row said "dbt and Cube", and the Cube half was already obsolete when it was written — S-0034/D-52 had split the blanket Cube refusal on the argument that Cube builds no relation for anything, and Cube compiles the *entire* quality surface, quarantine and reject tables included, without a murmur; refusing this one check would single it out): neither has the audit form, and compiling clean while the declared gate does not exist is the failure D83 caught in the dialect ports. **Cost recorded:** `MartIR` gains a field, and the canonical encoder covers each node's field *names and count*, so every fingerprint in the corpus moves — the churn §12 budgets, spent deliberately. The fixture carrying the demonstration is `quality_precedence` rather than `ecom_basic`, because an assertion makes a project uncompilable for two targets and `ecom_basic` is the fixture those targets' goldens are built on.

- Paths: `src/bloomery/emit/base.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/marts/flatten.py` `src/bloomery/spec/marts.py` `tests/execution/test_quality_precedence.py` `tests/fixtures/quality_precedence/marts.yaml` `tests/golden/schema/marts.json`

### S-0033/D-90 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **Cross-entity checks are `coverage:` on a relationship, and the audit hangs off the *dependent* side. §10's last open question is settled.** §10 guessed "probably reconcile-style"; it is not, and the reason is structural rather than stylistic. A `reconcile` compares two **values** and alerts beyond a tolerance — there is no right-hand value on the referenced entity to compare against, and `right: 1` is neither a shape the closed grammar admits nor one it should grow. This asserts **existence**: every row of a relationship's referenced entity has at least `min` rows referencing it. That makes it the mirror of `referential`, which asks whether every *dependent* row has a parent, and both read the same two relations through the same `via` pairs — which is why it is declared on the **relationship** rather than on either entity. **Why an audit, when a disposition would have been meaningful.** Unlike a mart row (D89), a childless customer is a real silver row with a source identity, a reject table and a replay path, so routing it is not nonsense. It is still an audit, for a reason that only shows up in the DAG: routing would need the *referenced* entity's model to read the *dependent* one, while the dependent one already reads the referenced one through this very relationship — so the pair that most wants this check (an FK one way, a coverage check the other) is exactly the pair whose models would form a cycle. Attaching the audit to the dependent side instead adds **no edge the relationship did not already imply**. `on_fail` is `fail`/`flag` only; `quarantine` and `repair` are absent from the surface rather than lowered to something weaker. **Two emission details that are each a trap closed.** The body counts a *dependent* column, never `COUNT(*)`: a `LEFT JOIN` still produces one output row for an unmatched left row, so `COUNT(*)` answers 1 for a customer with no orders at all and the check would pass on precisely the rows it exists to find. And the dependent side is `@this_model` rather than a named relation — the macro is the one reference SQLMesh rewrites inside an AUDIT body (D29), so naming the relation resolved to the virtual layer *and* put the model into its own `depends_on`, which is how the first cut emitted it. The referenced side is a sibling and is declared in `depends_on`, the trap D40 closed for step audits. Verified by a real SQLMesh plan on a fixture added to the e2e tier for it: the comment above `step_resolution` there argues that nothing else loads SQLMesh and that the gap hid three defects in a row, and this is the same shape — an audit body joining a sibling, with a `depends_on` that exists only because of the audit. dbt refuses the project (its tests are predicates, with no grouped cross-relation form); Cube is not asked, because it builds nothing (S-0034/D-52). **Cost:** `ProjectIR` gains a field, so every fingerprint moves. **Not closed:** the check counts rows that *reached* silver, so a referenced row quarantined by its own rules reads as absent — right for "has an order", wrong for a check somebody phrases as "exists", and named here rather than discovered.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/guardrails/quality.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/lower.py` `src/bloomery/spec/entity.py` `tests/e2e/test_sqlmesh_replan.py` `tests/fixtures/coverage_check/entity_model.yaml` `tests/fixtures/dirty_corpus/entity_model.yaml` `tests/unit/test_fixtures.py`

### S-0033/D-92 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-11)* **`Reconcile.on_fail` is `flag | fail`, not the full disposition vocabulary.** It was typed `OnFailName`, so `quarantine` and `repair` parsed. Neither means anything here: a reconcile compares two *aggregates*, so there is no row to divert and no recipe surface to carry a repair. `repair` lowered to `OnFail.REPAIR` with no recipe and no fallback, went non-blocking, and wrote "repair" into the quality mart's disposition column as though it were a disposition something had applied. Narrowed at the spec surface, where the other row-routing refusals live.

- Paths: `src/bloomery/emit/lower/reconcile.py` `src/bloomery/spec/quality.py`

### S-0033/D-95 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-12)* **An `expression` rule is a predicate over the entity's own columns — enforced, not merely documented.** `ExpressionRule.expr` was a bare string, parsed and spliced into the silver model with nothing checking it: the one authored-SQL surface in the framework with no resolution step, while every neighbour has one (`dedupe` columns D47, `reconcile` sides against a closed grammar, mart `assert` measures, recipe aliases exactly, `coverage` endpoints D91). Three refusals, each closing something **measured** rather than imagined. **A subquery**, and the reason is corruption at least as much as access: the qualifier pass that binds a bare column to the extract descends *into* a subquery, so `amt > (SELECT amt FROM other)` was emitted as `_extract.amt > (SELECT _extract.amt FROM other)` — correlated to the outer row, reading nothing from `other`. Executed on DuckDB with `amt` 10 against 1: the author's predicate is true so the rule must not fire, and it fired, flagging a good row — under `quarantine` that diverts it out of silver, which is data loss from a rule that reads correctly in the spec. A row predicate needs no subquery, and one that did could not be trusted to mean what it says; a comparison against another relation is what `reconcile:` is for. **A column the entity does not declare** — D47's own words, "a run-time binder failure on a model that compiled clean". **A qualified reference**, because the extract supplies the qualifier and a written one either names a relation the rule cannot read or shadows bloomery's. **Left open, deliberately:** the function vocabulary. `amt > pg_sleep(10)` still compiles, and narrowing that means giving expression rules a closed function list the way S-0021 gives transform chains one — a design decision about the surface, not a defect anything here demonstrated. Recorded rather than quietly widened, because the difference between "measured and fixed" and "seemed unsafe so I restricted it" is the difference this corpus is written to preserve.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `tests/unit/test_spec/test_sql_text.py`

### S-0033/D-96 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-12)* **A `pattern` rule may not nest unbounded repetition, because the cost is invisible from the spec and lands on one engine only.** The portable-subset scanner asked whether a regex *means* the same thing on every dialect (D5) and never what it *costs*. `^(?:a+)+$` passed — capturing groups are already refused, so the audit's first example was wrong, but `(?:…)` is accepted and reaches the engine. That is the textbook catastrophic-backtracking shape: two quantifiers can split one input exponentially many ways, and a non-matching subject makes the matcher try all of them. **Why the spec layer and not the engine.** DuckDB (RE2) and Trino (RE2J) match in linear time and would shrug; **Postgres** backtracks. So the rule passes review on the dialect a developer runs locally and hangs the one production uses — the same "silently means something else on another dialect" failure D5 exists to prevent, with the argument applied to cost rather than meaning. The check is one flag per open group in the existing single-pass scanner: an **unbounded** quantifier (`*`, `+`, `{n,}`) applied to a group whose body matches a **varying** length. The two halves are deliberately different tests, and the first cut got it wrong by using "unbounded" for both — review caught that `^(?:a{1,2})+b$` was still accepted, and measurement confirmed it: matching 26 `a`s takes 0.008s, 24 takes 0.003s, doubling every two characters. A bounded-but-ambiguous body partitions the input exponentially just as an unbounded one does; only a *fixed*-length body (`{n}`, or no quantifier at all) can be split exactly one way. So `?` now marks a body ambiguous without making an outer repetition unbounded. Bounding **either** side still makes it linear: `(?:a+){1,8}` and `(?:[0-9]{3}-)*` both pass. This conservatively refuses `(?:ab?)+`, which is unambiguous in practice — stated rather than hidden, because the alternative is the overlap analysis rejected below. **The gap, recorded rather than papered over:** alternation overlap. `^(?:a

- Paths: `src/bloomery/spec/quality.py` `tests/unit/test_spec/test_quality.py`

### S-0034/D-2 — `ASSUMED` (The step registry: referenced implementations)

`StepManifest` per §5.2: `ref`, `version`, `kind`, `determinism`, `runtime_lock`, typed `inputs`/`outputs` with grain + `key` (the grain's uniqueness columns) + `produces`, bounded `parameters`, `lineage: coarse|column`. Step bodies live in the platform repo — never in bloomery, never in tenant specs; tenant specs wire `use: ref@version` + bindings + parameters + optional S-0033 quality rules on outputs.

- Paths: `src/bloomery/spec/steps.py`

### S-0034/D-3 — `ASSUMED` (The step registry: referenced implementations)

`StepRegistry` is a frozen compile **input** (steps mapping + macro bodies), assembled by the caller; `compile_project(..., steps: StepRegistry = EMPTY_REGISTRY)`. Unknown ref or version → `UnknownStep` naming available versions. **No dynamic loading path exists** — tenant specs can never become an arbitrary-code-execution surface.

- Paths: `src/bloomery/errors.py` `src/bloomery/spec/steps.py` `src/bloomery/steps/registry.py` `tests/unit/test_schema.py`

### S-0034/D-13 — `ASSUMED` (The step registry: referenced implementations)

Implementation binding: `StepRegistry` gains `sql_bodies: Mapping[tuple[str, int], str]` (`sql_model` bodies, parsed at compile like `macro_bodies`); `StepManifest` gains `entrypoint: str` (`"package.module:function"`) for `python_model`, and the generated wrapper imports it at **run time**. The no-dynamic-loading rule is scoped to compile time — bloomery never imports or executes step code while compiling (manifests and SQL text only); runtime import of platform-owned code by the generated model is the normal SQLMesh execution path, and registry build (caller-side) verifies the entrypoint resolves.

- Paths: `src/bloomery/spec/mapping.py` `src/bloomery/steps/manifest.py` `tests/e2e/test_sqlmesh_replan.py` `tests/golden/schema/mapping.json`

### S-0034/D-49 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-09)* **D41 is built: metrics and `reconcile` reach step outputs, through a declared canonical link.** What was missing was a *surface*, not a mechanism. A metric is reachable iff every leaf of its `requires` closure is **available**, and a canonical field is available iff something draws a `canonical` edge to it — which only mapped entity fields could. So a step's columns were never available and any metric over one was unreachable, for a reason narrower than D41's own wording ("metric resolution keys on mappings") suggested. `StepWiring` gains `canonical: {<output>: {<column>: <canonical_field>}}`. On the **wiring**, not in the manifest: canonical names are the authored spec's vocabulary, and a manifest naming them could not be reused by a second project spelling them differently — the fork §5.7 exists to refuse. Never inferred from a matching column name, which is D43's argument about references applied to the same temptation. Nothing about metric resolution changed: the link draws the ordinary `canonical` edge and reachability follows. `reconcile` needed a second, unrelated repair — it resolved sides against *declared and mapped* entities, and a step output is neither, so a check naming one was refused as "declared but no mapping targets it", which is true and useless since the step writes the relation. Both kinds now answer through one `_SideEntity` view (field names and key), so the check asks what it needs rather than branching on provenance; declared-but-unmapped stays refused, which was always the real point. The refusal's wording now names both ways a relation can exist.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/resolve/graph.py` `src/bloomery/resolve/refs.py` `src/bloomery/spec/steps.py` `tests/fixtures/identity_resolution/catalog.yaml` `tests/fixtures/identity_resolution/steps.yaml` `tests/unit/test_quality/test_reconcile.py` `tests/unit/test_steps/test_step_canonicals.py` `tests/unit/test_unresolved.py`

### S-0034/D-50 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-09)* **Tier 1 has a spec surface: a mapping references a macro, in two shapes.** D26 refused a wired `sql_macro` because none existed, so the docs described a splice that could not happen. A field mapping gains a third shape beside `from:` and `recipe:` — `step: ref@version` with `from:` binding the columns it consumes — and a transform chain gains a `{step: ref@version}` link, so Tier 0 and Tier 1 compose on one field (the field shape binds a *raw* source path, so without the link no whitelist transform can run before the macro). A macro is referenced **inline**, never wired in `steps:`: it writes no relation, so it has no output to bind there, and one wiring per ref (D13) would make a macro usable in exactly one mapping with one parameter set — the pressure that produces `fuzzy_score_strict`, which is the fork §5.7 exists to refuse. Parameters are therefore supplied at the call site. The splice happens at **lowering**, so the macro is part of `ColumnIR.expr`, the model stays one query, and lineage sees through it — which moved `macro_expression` from `emit.steps` down to `bloomery.steps.splice` (emit sits *above* resolve, so the emitter could not own a splice the lowering needs), taking `parameter_literal` with it now both SQL tiers need the same typed literal. Consequence found by the type gate rather than by reading: the field-mapping union grew a third member, and five sites assumed two — a macro binds aliases like a recipe and has no chain, so they test an `ALIAS_BOUND` pair.

- Paths: `src/bloomery/resolve/build.py` `src/bloomery/resolve/graph.py` `src/bloomery/resolve/resolution.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/mapping.py` `src/bloomery/spec/quality.py` `src/bloomery/steps/splice.py` `tests/unit/test_resolve/test_edge_shapes_offcorpus.py` `tests/unit/test_steps/test_splice.py`

### S-0034/D-51 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-09)* **A macro declares its signature; it is never read off its body.** The first cut inferred the signature from the body's `:name` placeholders. That is the third appearance of one temptation, and it is refused for the third time — D43 refused fabricating references from matching key columns, D49 refused auto-linking canonical fields by name. The deciding argument is the ladder itself: Tier 0's `TransformSpec` declares `input_domain` **and** `output_type`, so a macro declaring neither would be the one tier whose inputs nothing checks, while §5.1's table claims Tier 1 can *parse and typecheck*. `StepManifest` gains `accepts: {column: type}` — a separate key from `inputs:`, which is relation-shaped for table steps, because one key meaning two things by kind reads fine only to whoever wrote it. The output type needs no new field: a macro has exactly one output of exactly one column (D18b). This buys three things. The **body** is checked against the declaration once, at the registry, where a disagreement is the platform's bug rather than a puzzle handed to every call site. The **call site** is checked against the declaration, so the message names what the macro expects instead of only which placeholder was unfilled. And a **chain** is typechecked *around* the link: the run before it against what it accepts, the run after it from what it produces — implemented as segments queued into the ordinary batch stage, so S-0023/D-2's one-aggregate property survives for chains containing a macro. Named cost, recorded rather than discovered: a genuinely polymorphic macro (`COALESCE(:a, :b)` over any type) must now pick a concrete type. Tier 0 carries the identical constraint through `input_domain`, so it is consistent rather than a new tax — but it is a real limit. A chain link must accept exactly one column, since a chain carries one running value; a two-column macro is refused there and pointed at the field shape.

- Paths: `src/bloomery/resolve/build.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/mapping.py` `tests/golden/schema/mapping.json` `tests/property/test_schema_agreement.py` `tests/unit/test_resolve/test_declared_zone.py` `tests/unit/test_schema.py`

### S-0035/D-7 — `ASSUMED` (Public surface and stability policy)

**The four permissive version keys are pinned to `Literal[1]`**, matching `steps_version`. The draft proposed *adding* keys on the belief that four kinds lacked them; every kind already has one, and the key is the document-kind **discriminator** — a document without it cannot be identified at all, so "missing means 1" would break loading rather than preserve it. The real defect is that `spec_version: 99` and `mapping_version: 42` are accepted and silently read as v1, so a spec written for a future bloomery is misread rather than refused. `spec_version` keeps its irregular name: renaming is a breaking change for consistency alone.

- Paths: `src/bloomery/schema.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/entity.py` `src/bloomery/spec/exports.py` `src/bloomery/spec/exposures.py` `src/bloomery/spec/imports.py` `src/bloomery/spec/mapping.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `tests/unit/test_schema.py` `tests/unit/test_spec/test_document_versions.py` `tests/unit/test_spec/test_exports.py` `tests/unit/test_spec/test_exposures.py`

### S-0037/D-10 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**A property test measures schema/parser agreement** rather than assuming it: every fixture validates against its schema, and mutations the parser rejects are checked against the schema too, with divergences recorded as amendments. The schema is a pre-filter, never the authority — two validators over one grammar drift, and undetected drift reads to a user as arbitrariness.

- Paths: `src/bloomery/spec/exports.py` `src/bloomery/spec/imports.py` `tests/property/test_schema_agreement.py` `tests/unit/test_spec/test_exports.py` `tests/unit/test_spec/test_imports.py`

### S-0041/D-7 — `ASSUMED` (Deterministic union merge)

A `_source` system column carries provenance. It is load-bearing rather than diagnostic: the collision audit reports which sources collided, and without it the report is unactionable on a multi-source entity.

- Paths: `pages/docs/reference/stability.md` `src/bloomery/emit/lower/silver.py` `src/bloomery/ir/nodes.py` `src/bloomery/spec/common.py` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_steps/test_lowering.py`

### S-0041/D-18 — `LOCKED` (Deterministic union merge)

**`_source` joins `RESERVED_MEMBER_NAMES`.** Every other generated column is reserved — `_quality_flags`, `_quality_ok`, `_load_id`, `_ingested_at`, `_source_row_id`, `has_quality_flags` — and a generated column that is not is one an author can collide with. Reserved unconditionally, not only on merged entities: a name that is legal until a second mapping arrives is a trap laid for the change that adds one.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/common.py` `tests/unit/test_spec/test_entity.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0047/D-1 — `LOCKED` (The unresolved-work report)

**The report is derived; no spec surface changes.** §3 measured that a `canonical:`-linked field with no mapping is a legal, complete spec whose metric is reported unreachable — including when the field is `required:`. "Undecided" is therefore already expressible, and a marker would be a second spelling of it. Consequence: this RFC touches no document kind, no `spec_version`, and no parser.

- Paths: `src/bloomery/cli/render.py` `src/bloomery/evidence.py` `src/bloomery/resolve/reach.py` `src/bloomery/resolve/recipes.py` `src/bloomery/resolve/resolution.py` `src/bloomery/spec/catalog.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0049/D-1 — `LOCKED` (Mapping identity)

**The identity is the document name.** It is unique by construction (a key of the `sources` mapping), already computed, already the ordering key for `Project.mappings`, and already the user-facing coordinate for refusals (S-0019/source-paths). Consequence: identity is a filename, so a rename changes it — accepted under D4's boundary.

- Paths: `src/bloomery/evidence.py` `src/bloomery/resolve/resolution.py` `src/bloomery/spec/common.py` `src/bloomery/spec/mapping.py` `tests/property/test_schema_agreement.py` `tests/unit/test_resolve/test_resolution.py` `tests/unit/test_spec/test_mapping.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0049/D-2 — `LOCKED` (Mapping identity)

**`(source, target)` is refused as the identity**, against S-0041/D-19's key shape looking like a candidate. Demonstrated non-unique: two documents may declare the same pair and the loader accepts them. Consequence: D19's quality-mart key is left alone — it is an accounting key for a per-entity mart, not an identity, and this decision does not reopen it.

- Paths: `src/bloomery/evidence.py` `src/bloomery/resolve/resolution.py` `src/bloomery/spec/mapping.py` `src/bloomery/spec/project.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0049/D-3 — `LOCKED` (Mapping identity)

**`document` is set by the loader and is not part of the YAML vocabulary.** A document declaring its own name is a second source of truth that can disagree with the first. Consequence: `Mapping` cannot be constructed from YAML alone in a test without the loader — which is already how every test builds one.

- Paths: `src/bloomery/spec/common.py` `src/bloomery/spec/mapping.py` `tests/property/test_schema_agreement.py` `tests/unit/test_guardrails/test_operands.py` `tests/unit/test_spec/test_mapping.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0049/D-9 — `LOCKED` (Mapping identity)

**`document` is `SkipJsonSchema` — absent from the schema `bloomery schema` exports.** That schema's audience is a spec author and D3 says this field is not theirs to write; a required `document` there would have an editor demand the one key the loader refuses, the exported contract contradicting the compiler on the surface whose whole job is to agree with it. Consequence: the model and the exported schema deliberately disagree about one field, recorded by `test_document_is_in_the_model_and_not_the_schema` where the other measured divergences live. *Added by execution 2026-08-30 — see logs/T-0008.md (D036, attempt 1).*

- Paths: `src/bloomery/evidence.py` `src/bloomery/resolve/resolution.py` `src/bloomery/spec/mapping.py` `src/bloomery/spec/project.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-1 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A derived metric is `expr` over aliased inputs, each input a metric.** `inputs` is a mapping keyed by alias, not a list: the alias is the input's identity because `expr` references it, and a dict makes a duplicate alias unrepresentable rather than a validation. Consequence: `MetricIR` gains a `derived` field and the additivity guard must accept it as a decomposition.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/resolve/build.py` `src/bloomery/semantic/plan.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-2 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**An offset is `{window: "<count> <grain>"}` or `{to_grain: <grain>}`, exactly one.** The grain vocabulary is `day`, `week`, `month`, `quarter`, `year` — the mart's own date buckets (S-0027/D-4). `hour` is refused despite MetricFlow accepting it: the emitted time spine is day-grain, so an hourly offset would resolve against a spine that cannot express it.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-3 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**Derived inputs are unioned into `requires_metrics` by the template merge, never written twice by the author.** The DAG, reachability, cycle detection and `depends_on` then need no change at all. The reference checker reads the spec model before the merge and validates the inputs there; both callers use one helper on the spec model, so the set of metrics a derived metric depends on has exactly one definition.

- Paths: `src/bloomery/resolve/metrics.py` `src/bloomery/resolve/refs.py` `src/bloomery/spec/metrics.py` `tests/unit/test_resolve/test_metrics.py` `tests/unit/test_resolve/test_refs.py` `tests/unit/test_spec/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-8 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A metric filter is a typed predicate list — `{dimension, op, values}` — and never a SQL string.** A string would be dialect-bound, unvalidatable against the column's declared type, and an injection surface in a compiler whose input may be untrusted. The list is ANDed; a disjunction is expressed as `in`.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/semantic/additivity.py` `src/bloomery/spec/common.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_semantic/test_ratio_rows.py` `tests/unit/test_spec/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-10 — `ASSUMED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**The filter operator set is `eq, ne, in, not_in, gt, gte, lt, lte, is_null` — no `like`/`ilike`.** Patterns need the `\` escape language, an `ESCAPE` clause and a case-folding portability argument, all for a construct rare in a metric definition. Adding them later is additive.

- Paths: `src/bloomery/spec/metrics.py`

### S-0050/D-12 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**The metric-filter operator vocabulary is defined in the spec layer and is *not* shared with `planner.request.Op`.** They are different facts: one is what a request may ask, the other what a definition may pin, and the request set carries `like`/`ilike` this one refuses. Stated as a decision rather than left as an accident, because a future reader will see two enums and reach for the merge.

- Paths: `src/bloomery/spec/metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-13 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**String values in a metric filter refuse `{` and `}`, at parse.** Both semantic targets template with braces — Jinja on MetricFlow, `{member}` on Cube — and a value carrying one would need per-target neutralization. One refusal beats two escaping rules that can disagree; a curly brace in a filtered dimension value has no BI use worth the divergence. At parse rather than at the guardrail because it is a property of the document alone, which is where S-0019/D-4 draws that line — unlike D9's dimension check, which needs the marts. NUL and floats are refused in the same validator, for the reasons they are refused everywhere else.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/spec/metrics.py` `tests/unit/test_spec/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0053/D-1 — `LOCKED` (Measure semantic types and additivity algebra)

**The aggregation vocabulary is a closed typed set, never a target-interpreted string.** `Additive`, `SemiAdditive`, `NonAdditive`, `Ratio`, `DistinctCount`, `Snapshot`. Locked because the planner, the proof rules and every emitter branch on it: an open string set makes each target the authority for what a measure means, which is the arrangement this whole sequence exists to end. Staging the *implementation* across releases is fine; encoding a future class as a string is not.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/ir/nodes.py` `src/bloomery/spec/common.py` `tests/fixtures/semantic_corpus/005-semi-additive-balance/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/005-semi-additive-balance/problem.md` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/problem.md` `tests/unit/test_guardrails/test_additivity.py` `tests/unit/test_semantic/test_rollup.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0062/D-1 — `LOCKED` (Ownership, classification and grants)

The three annotations change no SELECT. They reach metadata slots only, and an existing golden's SQL is byte-identical with them absent — asserted, not assumed.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/spec/entity.py` `src/bloomery/spec/quality.py` `tests/unit/test_tenant_guard.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0062/D-3 — `LOCKED` (Ownership, classification and grants)

`classification` is a **closed** vocabulary. An open string is a tag that cannot be routed, and the routing — the `redact` reconciliation and Cube's `public: false` — is the whole reason this is not a `meta` passthrough.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/spec/entity.py` `src/bloomery/spec/quality.py` `tests/unit/test_tenant_guard.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0062/D-4 — `LOCKED` (Ownership, classification and grants)

**Superseded by rows 9, 10 and 11.** `pii`/`secret` on a mapped field whose path is not redacted is a refusal **when the entity quarantines**, and silent otherwise. Unsatisfiable as written: a mapped field's path cannot be redacted — `_check_redaction` refuses that already — so both branches close and the classification has no legal spelling, which is the gap §2 opened this RFC to fill (see `logs/T-0050.md`, and `logs/T-0051.md` for the replacement).

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/spec/entity.py` `src/bloomery/spec/quality.py` `tests/unit/test_tenant_guard.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0062/D-7 — `ASSUMED` (Ownership, classification and grants)

Seeds are refused permanently, with a message naming S-0020 rather than a wave. A seed is data in the repository, and the only way to emit one is to put rows in a spec.

- Paths: `src/bloomery/spec/common.py` `src/bloomery/spec/entity.py`

### S-0062/D-12 — `ASSUMED` (Ownership, classification and grants)

A rollup declares its own `grants:` and does not inherit its parent mart's — D2's rule, applied to the one authored node that had no audience of its own. A rollup declaring none is the advisory of row 11 rather than a hole.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/spec/marts.py`

### S-0064/D-1 — `LOCKED` (Declared source freshness)

bloomery **declares** freshness and never measures it. The threshold is emitted; the framework runs the query. This is the same line drawn everywhere else — no execution, no clock, no environment.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/quality/reject.py` `src/bloomery/spec/catalog.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0064/D-3 — `ASSUMED` (Declared source freshness)

Durations reuse `quarantine.retention`'s grammar and validator. One spelling of a duration across the spec surface.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/spec/quality.py` `tests/fixtures/quality_precedence/mapping_codes.yaml`

### S-0065/D-10 — `ASSUMED` (Rollup marts and pre-aggregations)

**Rollups do not chain**: `rollup_of:` names a mart that is not itself a rollup, and a chain is refused — §10's second question. The obligation composes; its *premise* does not. Row 12 rests the grain half on R008, a measure embedded in a mart at that mart's grain, and a rollup's measures do not originate at the rollup's grain — they arrive there. Restating that premise is a phase of its own, and one refusal is cheaper than a wrong composition.

- Paths: `src/bloomery/resolve/graph.py` `src/bloomery/resolve/timeline.py` `src/bloomery/spec/marts.py`

### S-0066/D-1 — `LOCKED` (Declared input currency for conversion)

**A conversion's input currency must be a declared or derived fact; an unknown input is refused.** This is the whole document: an assertion that nothing can check is indistinguishable from a fact, and the difference is a wrong number that passes every existing guard. Locked because relaxing it — accepting `from` as its own evidence — restores exactly the situation S-0053/D-3 was written against, and because the refusal is what makes R009 mean anything.

- Paths: `src/bloomery/resolve/build.py` `src/bloomery/semantic/denomination.py` `src/bloomery/spec/mapping.py` `tests/unit/test_resolve/test_currency_convert.py` `tests/unit/test_semantic/test_denomination.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0066/D-2 — `LOCKED` (Declared input currency for conversion)

**A currency is never inferred — not from a column name, a source path, or the data.** S-0038 closed inference for this class and S-0005/D-1 refuses `INFERRED_HEURISTIC` as a way to close an obligation. Locked because a guess here is indistinguishable at the call site from a declaration, which is the property that makes the guess dangerous rather than merely imprecise.

- Paths: `src/bloomery/guardrails/arithmetic.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/catalog.py` `src/bloomery/transforms/_builtins.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0066/D-5 — `ASSUMED` (Declared input currency for conversion)

**Per-row denomination is admitted by the vocabulary from the first commit, and refused as unbuilt until P2.** Adding it later means a second mechanism for "what currency is this in", which is the argument that withdrew S-0054's P3. Not `LOCKED` because if P1 shows the `column:` form distorts the declaration's shape, a separate spelling is a defensible retreat — but it must then be designed, not improvised.

- Paths: `src/bloomery/spec/mapping.py` `tests/golden/schema/mapping.json`

### S-0067/D-2 — `LOCKED` (Stable node identity across renames)

The id is opaque. Compared for equality, never parsed, never used to derive a path, a relation name or an ordering.

- Paths: `src/bloomery/spec/project.py` `tests/unit/test_spec/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0073/D-2 — `LOCKED` (Caller-assembled spec history)

No `--as-of` on any command. The flag would oblige bloomery to know what a history is — which store, which instant-to-version mapping, what to do when it is ambiguous — and none of those is a question about compiling. `--steps` is the same question already answered this way (S-0034/purity-the-registry-is-a-compile-input).

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/cli/io.py` `src/bloomery/spec/project.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0073/D-3 — `LOCKED` (Caller-assembled spec history)

S-0068 is rejected, not deferred. An unscheduled design still shapes the documents that cite it, and two already cite this one.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/cli/io.py` `src/bloomery/spec/project.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0075/D-2 — `LOCKED` (Mechanical imports and per-relationship provenance)

**A dbt `relationships` test alone imports nothing.** It asserts every value exists in a target column and says nothing about the target being unique, so reading it as `many_to_one` invents the cardinality that makes the edge determine anything — S-0057/D-3's failure, by its own example. `many_to_one` from dbt requires the `relationships` test *and* a `unique`/`primary_key` on the named target. Locked because the tempting version of this importer is the one that skips the second test, and it would be indistinguishable in review from the correct one. Proposed by execution — see `logs/T-0053.md` (`logs/T-0053.md`) (D3, attempt 1).

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/guardrails/evidence.py` `src/bloomery/semantic/proof.py` `src/bloomery/spec/entity.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0075/D-7 — `ASSUMED` (Mechanical imports and per-relationship provenance)

**`imported_from:` is a free string naming the artifact, and its presence is the fact.** A boolean would need a second key for the refusal to name the source, and an enum invites an author to write `declared` on something they did not read (§5's alternatives). Not `LOCKED` because a second importer may want structure; a string is the cheapest thing to widen.

- Paths: `src/bloomery/spec/entity.py` `tests/unit/test_guardrails/test_evidence.py`

### S-0075/D-10 — `LOCKED` (Mechanical imports and per-relationship provenance)

**A relationship's name is unique across a project.** Nothing made it so and every consumer treats it as a key, each resolving a collision differently and silently: a mart's `via:` takes the first match, `plan` keeps the last of a `{name: rel}` dict, and D1's lookup marked every same-named authored edge as imported. Refused at resolution rather than fixed per reader — the readers are four and the fact is one. Locked because D1's lookup is keyed by that name, so relaxing it reintroduces a wrong refusal rather than an ambiguity. Added by execution 2026-09-13 — see PR #115 review.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/guardrails/evidence.py` `src/bloomery/semantic/proof.py` `src/bloomery/spec/entity.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0076/D-1 — `LOCKED` (Declared source timezone)

**A zone is declared, never inferred.** Not from the column name, not from a project default, not from the values. An inferred zone is indistinguishable from a declared one once written down, and the failure it produces is a five-hour shift with full compiler blessing. Locked because every cheaper alternative is a way of making the wrong answer easier to reach than today.

- Paths: `src/bloomery/semantic/denomination.py` `src/bloomery/spec/mapping.py` `src/bloomery/transforms/_builtins.py` `src/bloomery/typing/types.py` `tests/fixtures/semantic_corpus/011-timezone-boundary/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0076/D-2 — `LOCKED` (Declared source timezone)

**The declaration lives on the mapping, beside `currency_in:`** — not on the canonical field. A canonical field is shared across mappings and two feeds may run on two clocks, which is exactly the argument S-0066/D-6 made for currency; the shape is identical, so the answer is not re-derived.

- Paths: `src/bloomery/spec/mapping.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0076/D-3 — `LOCKED` (Declared source timezone)

**`zone_in: UTC` is a declaration, not a no-op.** A feed whose wall clocks really are UTC says so. Today that claim is made by silence and silence cannot be checked; the key's only job is to turn an unfalsifiable default into a sentence somebody wrote.

- Paths: `src/bloomery/semantic/denomination.py` `src/bloomery/spec/mapping.py` `src/bloomery/transforms/_builtins.py` `src/bloomery/typing/types.py` `tests/fixtures/semantic_corpus/011-timezone-boundary/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0077/D-1 — `LOCKED` (A ratio over one row set)

**bloomery does not choose which rows a ratio is about.** Both readings — per unit over units that exist, and total over units with overheads included — are metrics somebody wants, and the defect is that they are spelled identically. The rule refuses until the author says; it never picks. Locked because every cheaper design is a compiler making a decision about somebody's business, and the wrong one is invisible in the output.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/semantic/additivity.py` `src/bloomery/spec/quality.py` `tests/fixtures/semantic_corpus/008-ratio-rollup/**` `tests/fixtures/semantic_corpus/009-null-denominator/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0077/D-2 — `LOCKED` (A ratio over one row set)

**The inclusive reading stays reachable and is spelled out loud.** Without it the rule reduces to "exclude zero rows", which is D1 reversed with extra steps: an author who means `4.00` must be able to say so, and be seen to have said so.

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/spec/common.py` `tests/fixtures/semantic_corpus/009-null-denominator/bloomery/inclusive/metrics.yaml`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0077/D-13 — `LOCKED` (A ratio over one row set)

**`repair` does not discharge the positivity premise either.** D3 names only `flag`; this is D3's own sentence applied to the member it did not name. A repaired row stays in the relation carrying a fallback the rule cannot bound, because its recipe is a step and its fallback is whatever the author wrote. Only `quarantine` and `fail` discharge, because only those remove the row. Locked with D3: departing would mean proving a fallback is positive, which needs the step registry's output and is not a compile-time fact — see `logs/T-0063.md` (unlisted, 15:15Z).

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/semantic/additivity.py` `src/bloomery/spec/quality.py` `tests/fixtures/semantic_corpus/008-ratio-rollup/**` `tests/fixtures/semantic_corpus/009-null-denominator/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0077/D-14 — `LOCKED` (A ratio over one row set)

*Superseded by D16.* **A fourth discharge: the denominator counts a column that cannot be NULL.** §5.1's three discharges refuse every ratio in this repository — eight projects, including the two corpus cases §6 calls untouched — and five of the eight are counts, where the premise holds by construction and no declaration could add anything. A count counts the very rows the numerator sums, so a row contributing to the numerator contributes 1. Without this the rule refuses `revenue / order_count`, and §9's claim that a well-declared project is not inconvenienced is false for every project in the tree — see `logs/T-0063.md` (unlisted, 15:40Z).

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/semantic/additivity.py` `src/bloomery/spec/quality.py` `tests/fixtures/semantic_corpus/008-ratio-rollup/**` `tests/fixtures/semantic_corpus/009-null-denominator/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0077/D-16 — `LOCKED` (A ratio over one row set)

**`count` and `count_distinct` over a column that cannot be null both discharge.** Supersedes D14, which excluded the second on the grounds that a distinct count is about the group rather than the row — true, and not the premise. What R019 refuses is a denominator whose *per-row* contribution can be zero while the numerator's is not, and that is a property of a sum over a numeric column; a count of either kind is at least one for any non-empty row set. The exclusion was admitted wrong on the evidence of the message it produced: "nothing restricts … to rows with a non-zero `customer_id`" about a string column, telling the author to filter `customer_id > 0` — see `logs/T-0063.md` (unlisted, 15:55Z, attempt 2).

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/semantic/additivity.py` `src/bloomery/spec/quality.py` `tests/fixtures/semantic_corpus/008-ratio-rollup/**` `tests/fixtures/semantic_corpus/009-null-denominator/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
