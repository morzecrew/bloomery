<!-- torve:managed src/bloomery — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/`

### S-0004/D-1 — `LOCKED` (Observability: logging and a warnings channel)

No handler, ever: the library's only logging configuration act is attaching a `NullHandler` to the `bloomery` logger at package import, and it never adds, removes or configures a handler, a format or a level on a logger it does not own

- Paths: `src/bloomery/__init__.py` `pyproject.toml`
- Consequence: A library that installs a handler fights its embedder, and reversing this reaches every caller in the process; the level stays at `NOTSET` deliberately, which is the only way a caller's own `setLevel` on the `bloomery` logger can work from outside
- Check: `uv run pytest tests/unit/test_logging_posture.py -q` (shadow; runs as `decision:S-0004/D-1`, no log entry owed)

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

### S-0004/D-5 — `LOCKED` (Observability: logging and a warnings channel)

Nothing important is ever only logged: anything a caller must act on is a value they receive — a refusal or an advisory — and a log record is a second copy at most

- Paths: `src/bloomery/evidence.py`
- Consequence: It is the whole argument for the advisory channel existing; without it the channel is decoration, and it is also why there is no log record for an advisory at all
- Check: `uv run pytest tests/unit/test_advisories.py -q` (shadow; runs as `decision:S-0004/D-5`, no log entry owed)

### S-0004/D-6 — `OPEN` (Observability: logging and a warnings channel)

Whether `compile_project` grows a report carrying artifacts plus advisories, or stays artifacts-only with callers who want advisories calling `evaluate`, is deliberately undecided and needs a consumer rather than a guess

- Paths: `src/bloomery/compile.py`
- Consequence: Until a consumer asks, `compile_project` returns artifacts and nothing else; the field on `SpecEvidence` is useful under either answer and ships first, so neither answer is foreclosed

### S-0004/D-7 — `LOCKED` (Observability: logging and a warnings channel)

An advisory is not a refusal that lost its nerve: the bar is that the spec is legal, the compiled artifacts are correct, and there is still something the author would want to know, and anything where the numbers could be wrong stays a refusal

- Paths: `src/bloomery/evidence.py`
- Consequence: A review that finds an advisory where a refusal belongs should treat it as a defect; this does not soften "refuse rather than answer wrongly" and nothing may be moved from the refusal side to the advisory side under it
- Check: `uv run pytest tests/unit/test_advisories.py -q` (shadow; runs as `decision:S-0004/D-7`, no log entry owed)

### S-0004/D-8 — `ASSUMED` (Observability: logging and a warnings channel)

Deprecation is `warnings.warn(..., BloomeryDeprecationWarning)` at the old call site, naming the replacement and the removal release, best-effort once per process per spelling by an explicit module-level guard that records after emitting — and it is the only use of the `warnings` module under `src/bloomery/`

- Paths: `src/bloomery/errors.py`
- Consequence: The guard bounds how often bloomery emits and cannot show a warning a caller's `ignore` filter hides; two threads hitting a spelling's first use concurrently may emit twice, and a caller needing a hard once gets it from their own filter configuration
- Check: `uv run pytest tests/unit/test_deprecation.py -q` (shadow; runs as `decision:S-0004/D-8`, no log entry owed)

### S-0004/D-10 — `ASSUMED` (Observability: logging and a warnings channel)

The advisory vocabulary is a closed enum with no free-text constructor, and every member has a row in the reference's advisory table while every documented code is constructible — checked in both directions

- Paths: `src/bloomery/evidence.py` `pages/docs/reference/errors.md` `tests/unit/test_docs_floor.py`
- Consequence: Adding an advisory is a reviewed change that lands its documentation row with it; a documented code no path can construct fails the census, which is what blocks the deprecated-spelling advisory until a spelling is actually deprecated
- Check: `uv run pytest tests/unit/test_docs_floor.py -q` (shadow; runs as `decision:S-0004/D-10`, no log entry owed)

### S-0004/D-11 — `ASSUMED` (Observability: logging and a warnings channel)

Advisories are a sorted, deduplicated tuple under the declared key `(code.value, source_path or "", message)`, applied in exactly one place, and the `Advisory` dataclass is deliberately not orderable

- Paths: `src/bloomery/evidence.py`
- Consequence: A missing source path normalizes to the empty string for ordering while staying `None` on the value; the dataclass's own field order disagrees with the key, so making the type orderable reintroduces both a silent disagreement and a `TypeError` on a legal pair
- Check: `uv run pytest tests/unit/test_advisories.py -q` (shadow; runs as `decision:S-0004/D-11`, no log entry owed)

### S-0004/D-12 — `ASSUMED` (Observability: logging and a warnings channel)

Advisories are computed by a pure function of the same values every other evidence field is derived from, called by `evaluate`, with no accumulator threaded through the pipeline and no ordering dependence on when a stage ran, and are reported at every partial width

- Paths: `src/bloomery/evidence.py`
- Consequence: An advisory derived from an input is computed and correct whether or not a stage refused, so withholding it from a refused project makes `advisories` the one field that is empty for a reason the stage reached cannot explain
- Check: `uv run pytest tests/unit/test_advisories.py -q` (shadow; runs as `decision:S-0004/D-12`, no log entry owed)

### S-0004/D-13 — `ASSUMED` (Observability: logging and a warnings channel)

Modules obtain their stage logger by the documented name literally — `bloomery.spec`, `bloomery.resolve`, `bloomery.guardrails`, `bloomery.emit`, `bloomery.runtime`, `bloomery.planner` — and never through `getLogger(__name__)`

- Paths: `src/bloomery/spec/project.py` `src/bloomery/resolve/build.py` `src/bloomery/compile.py` `src/bloomery/runtime/hydration.py` `src/bloomery/planner/metricflow_planner.py`
- Consequence: The two idioms ship different stable sets, and `__name__` would make the documented names a strict subset of the real ones; tuning works either way through the hierarchy, so what differs is only which names are the promise
- Check: `uv run pytest tests/unit/test_logging_posture.py -q` (shadow; runs as `decision:S-0004/D-13`, no log entry owed)

### S-0004/D-15 — `ASSUMED` (Observability: logging and a warnings channel)

A new field on `SpecEvidence` is appended after whatever field is last at the time, and a positional-construction test that supplies every pre-existing field by position lands with it, alongside a test pinning the field count

- Paths: `src/bloomery/evidence.py`
- Consequence: "Additive" holds positionally only for an appended field, and a field inserted earlier silently rebinds positional construction; a test that stops short of the insertion point passes in both worlds and pins nothing
- Check: `uv run pytest tests/unit/test_advisories.py -q` (shadow; runs as `decision:S-0004/D-15`, no log entry owed)

### S-0004/D-16 — `OPEN` (Observability: logging and a warnings channel)

What makes a quality rule "unstrengthened" — the vocabulary the second advisory candidate names and this codebase does not have — is decided at implementation against the `QualityRule` subclasses in `src/bloomery/spec/quality.py`, and the decision is logged

- Paths: `src/bloomery/evidence.py`
- Consequence: The advisory cannot be built before the term means something checkable, and the definition chosen fixes both what the code reports and what its documentation row can say; getting it wrong produces an advisory that fires on correct specs, which D-7 forbids

### S-0008/D-7 — `OPEN` (Fuzzing the compile boundary)

Whether each of the two narrow-handler sites gains `RecursionError` or a depth limit raising a named error — decided per site from its reproduction, and logged either way

- Paths: `src/bloomery/evidence.py` `src/bloomery/resolve/steps.py`
- Consequence: A depth limit raising a named error adds a class to `src/bloomery/errors.py` and an entry to `pages/docs/reference/errors.md`; widening the catch adds neither, and the two sites may legitimately get different answers

### S-0012/D-4 — `LOCKED` (Validating a dialect port against an engine we cannot run)

No engine driver, cloud SDK or Spark session enters `src/bloomery`; live harnesses live in `tests/support/` and their drivers are test-only dependency groups, never installed for `uv add bloomery`

- Paths: `src/bloomery/**` `tests/support/**` `pyproject.toml`
- Consequence: A cloud port adds a port module and a test harness and nothing else to the install path, so the package stays a pure compiler and its dependency closure stays free of a JVM and four vendor SDKs
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0019/D-3 — `ASSUMED` (Spec layer and error model)

Every raisable failure derives from `BloomeryError` and carries `source_path`; all error classes are declared in `bloomery/errors.py` so `except BloomeryError` needs one import. Pydantic/yaml exceptions never escape.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/quality.py` `src/bloomery/spec/common.py`

### S-0019/D-6 — `ASSUMED` (Spec layer and error model)

Parse-stage errors are batched per document (all failures reported at once).

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/errors.py` `src/bloomery/evidence.py` `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/build.py` `src/bloomery/resolve/refs.py` `src/bloomery/spec/common.py` `src/bloomery/spec/project.py` `src/bloomery/typing/check.py` `tests/unit/test_cli.py` `tests/unit/test_evidence.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_refs.py` `tests/unit/test_spec/test_mapping.py` `tests/unit/test_spec/test_project.py` `tests/unit/test_spec/test_sql_text.py`

### S-0019/D-8 — `ASSUMED` (Spec layer and error model)

Catalog is passed separately from `Project` (vertical-level vs tenant-level), matching spec §8's `compile_project(..., catalog=...)`.

- Paths: `src/bloomery/cli/io.py` `src/bloomery/schema.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/project.py` `tests/property/test_schema_agreement.py`

### S-0019/D-10 — `ASSUMED` (Spec layer and error model)

(Amended for `_bloomery-metricflow-pivot.md`) `metric_time` is a reserved dimension/field name, rejected at spec validation with a clear message (S-0030 R4). The `Metric` model reserves optional `cumulative:` (window / grain_to_date) and derived-expression forms lowered per S-0030's mapping table; both are additive spec surface, parse-validated only.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/spec/common.py` `src/bloomery/spec/entity.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `tests/golden/schema/catalog.json` `tests/golden/schema/entity_model.json` `tests/golden/schema/marts.json` `tests/golden/schema/metrics.json` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_spec/test_metrics.py`

### S-0020/D-11 — `ASSUMED` (Intermediate representation and determinism contract)

*(2026-08-12)* **A lookup that an earlier stage makes total says which stage, and no lookup may fail as a bare `StopIteration`.** `next(x for x in xs if …)` over a validated set is correct and fails terribly: no message, no source path, no hint about which stage was supposed to prevent it. One escaped from a `coverage` check naming an unmapped entity and read as a crash rather than as a missing refusal — the guardrail that would have caught it did not exist yet (S-0033/D-91). The invariant "every such lookup is total because a guardrail refused the case that would break it" was real and held everywhere but there; what it never had was somewhere to be *stated*, so drift was invisible. Two parts. `guaranteed(candidates, *, expected, by)` raises `InvariantViolated` naming its guarantor, so each call site carries the name of the check it depends on — the point is the `by=` argument, not the error. And an AST scan over `src/` fails on any bare `next(...)`, which is what keeps the form from returning. **The scan immediately paid for itself:** a `grep` had found six sites and the AST found **twelve** — `next(iter(xs))` and `next(generator_variable)` are the same hazard in spellings a regex written around one idiom does not see. That gap between what a scan sees and what a reader assumes it sees is the reason this is enforced rather than documented.

- Paths: `src/bloomery/errors.py` `tests/unit/test_errors.py` `tests/unit/test_signature_closure.py` `tests/unit/test_total_lookups.py`

### S-0022/D-2 — `ASSUMED` (Resolution: dependency DAG, recipes, reachability)

The compiler never chooses a recipe. The mapping's recorded `recipe:` id is validated — id exists on the catalog field, every `requires` name bound by the mapping's `from` aliases (exactly) — else `ResolutionError`. Choice happens upstream; the compiler reproduces it (determinism + auditability, spec §3.4). Consequence: catalog evolution can invalidate recorded choices, and that is a loud error, not a silent re-choice.

- Paths: `src/bloomery/evidence.py` `src/bloomery/guardrails/operands.py` `src/bloomery/resolve/recipes.py` `src/bloomery/resolve/resolution.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/mapping.py` `tests/golden/schema/catalog.json` `tests/golden/schema/mapping.json` `tests/unit/test_resolve/test_edge_shapes_offcorpus.py` `tests/unit/test_resolve/test_recipes.py`

### S-0022/D-3 — `ASSUMED` (Resolution: dependency DAG, recipes, reachability)

A canonical field is available iff some mapped field links to it via `canonical:` with a direct mapping or validated recipe. A metric is reachable iff every leaf of its `requires`/`requires_metrics` closure is available; unreachable metrics report the specific missing leaves and are stored in the IR (S-0020/D-6) as product-facing output.

- Paths: `src/bloomery/evidence.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/reach.py` `tests/unit/test_evidence.py` `tests/unit/test_unresolved.py`

### S-0022/D-4 — `ASSUMED` (Resolution: dependency DAG, recipes, reachability)

Any cycle in the DAG raises `CircularDerivation` (a `ResolutionError` subclass) naming the full cycle path, rotated to the lexicographically smallest node for stable messages.

- Paths: `src/bloomery/errors.py` `src/bloomery/resolve/order.py` `tests/unit/test_resolve/test_order.py`

### S-0022/D-7 — `ASSUMED` (Resolution: dependency DAG, recipes, reachability)

All cross-spec reference validation lives here, not parse (S-0019/D-4): mapping targets, `canonical:` links, relationship endpoints, metric template refs. All failures are `ResolutionError`s with source paths, batched per stage; later checks run only on a reference-clean graph.

- Paths: `src/bloomery/errors.py` `src/bloomery/resolve/refs.py` `tests/unit/test_resolve/test_refs.py`

### S-0023/D-2 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Violations are batched project-wide: leaf errors (`UnitMismatch`, `TaxBasisMismatch`, `CurrencyMismatch`, `GrainMismatch`, `AdditivityViolation`, `AssertLoweringError`) are collected and raised as one `GuardrailError` aggregate, sorted by `(source_path, type)`. Matches S-0019/D-6.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/arithmetic.py` `src/bloomery/guardrails/quality.py` `src/bloomery/guardrails/stage.py` `src/bloomery/quality/reconcile.py` `src/bloomery/resolve/build.py` `src/bloomery/resolve/steps.py` `tests/fixtures/fanout_trap/metrics.yaml` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_guardrails/test_stage.py` `tests/unit/test_steps/test_lowering.py`

### S-0023/D-8 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Range sanity: the guardrail stage validates `assert:` clauses for well-typedness against the field's `LogicalType` only (`AssertLoweringError`); lowering to target-native audits happens via `AuditIR` at emit (S-0020, S-0025).

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/asserts.py` `src/bloomery/guardrails/stage.py` `src/bloomery/quality/predicates.py` `src/bloomery/spec/entity.py` `src/bloomery/spec/quality.py` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/unit/test_guardrails/test_asserts.py` `tests/unit/test_guardrails/test_quality.py`

### S-0024/D-3 — `ASSUMED` (Plan: spec diff and change classification)

Renames are explicit only: `renamed_from: <old>` in the spec (carried as `ColumnIR.renamed_from`, an S-0020 amendment). No heuristic inference — determinism and auditability beat convenience. A stale annotation (old name absent from `old`, including `old is None`) raises `RenameTargetMissing` (`PlanError`), which forces the annotation to be dropped after one applied plan.

- Paths: `src/bloomery/errors.py` `src/bloomery/plan/diff.py` `src/bloomery/plan/model.py` `src/bloomery/spec/entity.py` `tests/fixtures/evolution_v3/entity_model.yaml` `tests/golden/schema/entity_model.json` `tests/property/test_plan_properties.py` `tests/unit/test_plan/test_diff.py` `tests/unit/test_plan/test_evolution.py`

### S-0024/D-5 — `ASSUMED` (Plan: spec diff and change classification)

Expand/contract is enforced in this stage: dropping/narrowing a field referenced by a metric reachable in `new`, or by an old-reachable metric that vanished in the same plan, raises `ContractViolation` (`PlanError`). Deprecation must land in a prior version. This is the stage's only refusal — BREAKING changes are classified and returned, not raised.

- Paths: `pages/docs/how-to/evolve-a-spec.md` `src/bloomery/errors.py` `src/bloomery/plan/diff.py`

### S-0025/D-1 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Three independent ports (`TargetEmitter`, `DialectPort`, `NamingPolicy`), all `Protocol`s. Target and dialect never collapse into one adapter.

- Paths: `src/bloomery/dialects/__init__.py` `src/bloomery/dialects/base.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/naming.py` `src/bloomery/quality/flags.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_postgres.py`

### S-0025/D-3 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Capability mismatch behavior is fail-loud: `UnsupportedByTarget` naming entity + feature. Silent degradation is forbidden.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/spec/quality.py` `src/bloomery/transforms/_builtins.py` `tests/property/test_compile_properties.py` `tests/unit/test_emit/test_base.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_quality/test_text_rules.py` `tests/unit/test_transforms/test_builtins.py`

### S-0025/D-5 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

v0.1 adapter set: SQLMesh + Cube + dbt targets; DuckDB + Postgres + Trino dialects. dbt is a port-abstraction proof, documented as such.

- Paths: `src/bloomery/compile.py` `src/bloomery/dialects/duckdb.py` `src/bloomery/dialects/postgres.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/runtime/sql_client.py` `tests/unit/test_dialects/test_duckdb.py` `tests/unit/test_dialects/test_postgres.py` `tests/unit/test_dialects/test_trino.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_runtime/test_sql_client.py`

### S-0027/D-2 — `ASSUMED` (Marts and role-playing dimensions)

Measure grain must strictly equal mart grain; coarser or finer is `GrainViolation`. Resolves D2's prose/example contradiction to the strict reading; relaxation is a future additive change.

- Paths: `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/semantic/proof.py` `src/bloomery/semantic/rollup.py` `tests/fixtures/fanout_trap/marts.yaml` `tests/fixtures/fanout_trap/metrics.yaml` `tests/fixtures/semantic_corpus/001-order-shipping-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/001-order-shipping-fanout/problem.md` `tests/fixtures/semantic_corpus/010-many-to-many-bridge/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/010-many-to-many-bridge/problem.md` `tests/golden/refusals/example-wrong-grain.txt` `tests/golden/refusals/fanout_trap.txt` `tests/support/semantic_corpus.py` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_semantic_corpus_guard.py`

### S-0027/D-3 — `ASSUMED` (Marts and role-playing dimensions)

`flatten` via-steps require declared `many_to_one`/`one_to_one` relationships (else `FanoutRisk`); chains flatten transitively in authored order; prefixes mandatory; collisions are errors, never auto-renames.

- Paths: `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `src/bloomery/spec/marts.py` `tests/golden/schema/marts.json` `tests/unit/test_marts/test_flatten.py` `tests/unit/test_spec/test_marts.py`

### S-0028/D-3 — `ASSUMED` (Native planner: MetricRequest → QueryPlan)

Six-step algorithm: validate (`UnknownMember` with `did_you_mean` via difflib, S-0021/D-4) → mart selection (0 → `UnreachableAtGrain` naming the per-metric grain/mart conflict; 1 → use; N → lowest `cost_hint`, ties lexicographic by mart name) → additivity lowering → SQLGlot AST build → `dialect.render` → `Explanation`.

- Paths: `src/bloomery/errors.py` `tests/unit/test_planner/test_coverage.py`

### S-0028/D-5 — `ASSUMED` (Native planner: MetricRequest → QueryPlan)

Additivity lowering per D4 exactly: additive → SUM at requested grain; semi-additive (`SemiAdditivePolicy(over, rule ∈ last/first/avg/max/min)`) → sum across every dimension except `over`, rule along `over` (coarser requested grain: rule within each bucket, then sum); non-additive → never stored/summed, recomputed from additive components (`RatioSpec` → `SUM(num)/NULLIF(SUM(den),0)`); missing components = `NonAdditiveWithoutComponents` at resolution/guardrail stage (S-0023 defense-in-depth).

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/coverage.py` `src/bloomery/planner/explain.py` `src/bloomery/planner/result.py` `src/bloomery/spec/common.py` `tests/fixtures/non_additive_aov/marts.yaml` `tests/fixtures/non_additive_aov/metrics.yaml` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_planner/test_coverage.py`

### S-0028/D-6 — `ASSUMED` (Native planner: MetricRequest → QueryPlan)

Every dimension reference in `MetricRequest`/`FilterExpr`/`OrderSpec` parses into a `DimensionRef` (S-0027); unqualified reference to a multi-role dimension → `AmbiguousDimension` naming the roles. The planner reads flattened mart columns — no joins, so role-playing needs no planner logic.

- Paths: `src/bloomery/errors.py` `src/bloomery/planner/coverage.py` `src/bloomery/planner/request.py` `tests/execution/test_planner_numbers.py`

### S-0028/D-9 — `ASSUMED` (Native planner: MetricRequest → QueryPlan)

Errors: `PlannerError(BloomeryError)` with leaves `UnknownMember`, `UnreachableAtGrain`, `AmbiguousDimension`, `InvalidRequest`, all declared in `bloomery/errors.py` (S-0019/D-3). Planner errors are **not batched** — deviation from compile-time batching, justified: the interactive caller fixes one request, and validation-first means failures are mostly singular.

- Paths: `src/bloomery/errors.py` `src/bloomery/planner/request.py` `tests/unit/test_planner/test_request.py`

### S-0030/D-8 — `ASSUMED` (MetricFlow backend: manifest emitter and planner adapter)

Filters (Jinja `where_constraints`) are the highest-risk surface: values never interpolated raw — typed per-dialect literal renderer or bind parameters; dimension names only from validated `DimensionRef`s via `names.py`; values type-checked against the dimension (`FilterTypeMismatch`); `contains`/`like` escape wildcards. Adversarial fuzz property test (injection strings, template syntax, unicode quotes, newlines) asserts parsed-SQL predicate structure unchanged and scanned relations exactly the expected mart — **merge-blocking**. *(Superseded by D16 — see §5.6 note.)*

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/planner/filters.py` `src/bloomery/planner/request.py` `tests/property/test_planner_properties.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_planner/test_filters.py`

### S-0032/D-5 — `ASSUMED` (Query vocabulary: filters, sort, pagination)

**D-Q5:** string-carrier scalars — `str` operands on ordering operators are parsed and validated against the resolved dimension's `LogicalType` at request-validation time, before any rendering: invalid → `FilterTypeMismatch`, non-finite → `InvalidLiteral`; **no SQL cast is ever emitted** (rendered literals are already in the dimension's type). `NaN`/`Infinity`/`-Infinity` refused even though they parse as `Decimal` — `lt "NaN"` fails open on Postgres and matches every row. `UUID` renders as a string literal against string-typed dimensions; no UUID `LogicalType` is added.

- Paths: `src/bloomery/errors.py` `src/bloomery/planner/filters.py` `src/bloomery/planner/parse.py` `src/bloomery/planner/request.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `tests/execution/test_period_over_period.py` `tests/property/test_planner_properties.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_planner/test_filters.py` `tests/unit/test_planner/test_request.py` `tests/unit/test_spec/test_metrics.py` `tests/unit/test_spec/test_quality.py`

### S-0033/D-6 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Entity-level `dedupe` requires `tie_break` under `keep: latest_by` (nondeterministic winners violate the core invariant); dedupe-referenced fields' `coercible` is forced to `fail`. Row rules `expression` and `referential` (`on_missing ∈ {unknown_member, quarantine, flag}` — `fail` deliberately excluded: orphans are an expected, recoverable data condition; a pipeline-stopping orphan gate is a `reconcile` check; `unknown_member` keeps aggregates correct via a reserved member row and requires a string-typed fk in v1 — the reserved member is the string `'__unknown__'`; a non-string fk with `unknown_member` is a compile-time `GuardrailError` naming the alternatives, typed per-key sentinels rejected); `reconcile` blocks emit model + non-blocking audit.

- Paths: `src/bloomery/errors.py` `src/bloomery/quality/catalogue.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/quality.py` `tests/unit/test_spec/test_quality.py`

### S-0033/D-10 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

One `<entity>__reject` table per entity with the §5.6 schema (stable sha256 `reject_id` for idempotent replay). Retention is **required** whenever any quarantine disposition exists — missing retention is a compile error; retention deletes **all** reject rows on expiry (unresolved measured from `last_seen`, resolved from `resolved_at`) and is the only deleter — replay never deletes. `redact:` paths apply at write time and must not intersect any path the entity's mappings read (`from` paths, recipe aliases included) — an intersecting redact is the compile error `RedactionConflict`. Bloomery emits the reject/replay artifacts and never executes them.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/errors.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `tests/engines/test_merged_cleaning_engines.py` `tests/fixtures/multi_source_quality/entity_model.yaml` `tests/unit/test_guardrails/test_quality.py`

### S-0033/D-21 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Ingestion metadata contract: entities using `quarantine` or `dedupe` require bronze `_load_id`, `_ingested_at`, `_source_row_id` (a stable per-source-row identity supplied by the ingestion layer, **NOT NULL and unique per source row** — data properties no compiler can check, so the lowering emits a generated **blocking audit** on the metadata columns: a null or duplicated `_source_row_id` stops the run); column absence is the new compile error `IngestionMetadataMissing` (`GuardrailError` leaf, `errors.py` per S-0019/D-3). `reject_id` = sha256 over the length-prefixed utf-8 **pair** (`source_relation`, `_source_row_id`) — canonical serialization per the S-0020 canon-bytes doctrine. This supersedes the triple this row first carried (this round's own earlier decision): `_load_id` is removed from the identity and becomes an attribute (the latest observing load) — re-deliveries of the same source row across loads must land on the **same** reject row (that is what `first_seen`/`last_seen` track); a per-load identity would mint a new row per retry and violate replay idempotence. A re-delivery updates `last_seen`/`_load_id`/`failed_rules` on the existing row.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/quality.py` `src/bloomery/quality/catalogue.py` `src/bloomery/quality/dedupe.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/transforms/_builtins.py` `tests/e2e/test_dbt_parse.py` `tests/e2e/test_sqlmesh_project.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_dedupe_and_audits.py` `tests/execution/test_merged_cleaning.py` `tests/execution/test_zoneless_utc.py` `tests/fixtures/dirty/README.md` `tests/fixtures/semi_additive_inventory/mapping.yaml` `tests/support/execution.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_trino.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_entity.py`

### S-0033/D-56 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **The dialects a `pattern` is checked against are the shipped ports, never the registry.** `registered_dialects()` is process-global and mutable, so an extension dialect registered by an unrelated import could decide whether an existing project compiles — the ambient dependency S-0020 exists to forbid, and one no golden would catch. The checked set is the constant `PATTERN_TARGET_DIALECTS = (duckdb, postgres, trino)`, overridable by an explicit argument the caller supplies. Recorded consequence: an extension dialect is no longer checked at compile time. Checking it would mean plumbing a dialect set into `build_project_ir`, which is dialect-free by construction and right to be — a project is portable or it is not, and the guardrail stage has no target. Named as the escape hatch, not built.

- Paths: `pages/docs/how-to/add-quality-rules.md` `src/bloomery/compile.py` `src/bloomery/dialects/__init__.py` `src/bloomery/quality/pattern.py` `tests/unit/test_compile.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_quality/test_edges.py`

### S-0034/D-3 — `ASSUMED` (The step registry: referenced implementations)

`StepRegistry` is a frozen compile **input** (steps mapping + macro bodies), assembled by the caller; `compile_project(..., steps: StepRegistry = EMPTY_REGISTRY)`. Unknown ref or version → `UnknownStep` naming available versions. **No dynamic loading path exists** — tenant specs can never become an arbitrary-code-execution surface.

- Paths: `src/bloomery/errors.py` `src/bloomery/spec/steps.py` `src/bloomery/steps/registry.py` `tests/unit/test_schema.py`

### S-0034/D-5 — `ASSUMED` (The step registry: referenced implementations)

Determinism tiers: `pure` (freely backfillable) | `seeded` (seed required in the spec, recorded) | `nondeterministic` (**compile error**). Restatement is the organizing capability of the architecture; refusing nondeterminism is the load-bearing constraint, not conservatism.

- Paths: `src/bloomery/errors.py` `src/bloomery/ir/nodes.py` `tests/support/identity.py` `tests/unit/test_steps/test_identity_demo.py`

### S-0035/D-1 — `ASSUMED` (Public surface and stability policy)

**Signature closure** is the root-namespace rule: any type appearing in a public signature, return, generic argument, or returned-dataclass field is itself exported from `bloomery`. **Fourteen** types are added under it (§5.1), the walk stopping at handle types (decision 9). Enforced by a unit test walking `get_type_hints`, not by review — a walk that decision 10 has to make runnable first.

- Paths: `src/bloomery/__init__.py` `src/bloomery/evidence.py` `src/bloomery/ir/nodes.py` `tests/unit/test_advisories.py` `tests/unit/test_ir/test_nodes.py` `tests/unit/test_package.py` `tests/unit/test_signature_closure.py`

### S-0035/D-7 — `ASSUMED` (Public surface and stability policy)

**The four permissive version keys are pinned to `Literal[1]`**, matching `steps_version`. The draft proposed *adding* keys on the belief that four kinds lacked them; every kind already has one, and the key is the document-kind **discriminator** — a document without it cannot be identified at all, so "missing means 1" would break loading rather than preserve it. The real defect is that `spec_version: 99` and `mapping_version: 42` are accepted and silently read as v1, so a spec written for a future bloomery is misread rather than refused. `spec_version` keeps its irregular name: renaming is a breaking change for consistency alone.

- Paths: `src/bloomery/schema.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/entity.py` `src/bloomery/spec/exports.py` `src/bloomery/spec/exposures.py` `src/bloomery/spec/imports.py` `src/bloomery/spec/mapping.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `tests/unit/test_schema.py` `tests/unit/test_spec/test_document_versions.py` `tests/unit/test_spec/test_exports.py` `tests/unit/test_spec/test_exposures.py`

### S-0035/D-10 — `ASSUMED` (Public surface and stability policy)

**The `TYPE_CHECKING` guard is lifted on public signatures before the closure test lands.** `typing.get_type_hints` currently raises `NameError` on 7 of the 29 exports, including `compile_project`, because `from __future__ import annotations` plus a `TYPE_CHECKING`-only import leaves the annotation naming something absent at run time. Decision 1's enforcement is unimplementable until those names are importable at run time — a prerequisite the design did not see, found by running the proposed walk rather than by reading it. Guards on internal signatures are untouched.

- Paths: `src/bloomery/evidence.py` `src/bloomery/resolve/facets.py` `src/bloomery/resolve/lineage.py` `src/bloomery/resolve/timeline.py` `src/bloomery/schema.py` `tests/unit/test_signature_closure.py`

### S-0037/D-1 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**The JSON Schema export ships first and is the highest-leverage item.** It is a day's work over `model_json_schema()` and serves four consumers at once — editor completion, control-plane form validation, drift-free reference docs, and constrained generation for machine-authored specs. The last is the one that changes a proposal loop's safety argument from a prompt instruction into a structural constraint.

- Paths: `src/bloomery/schema.py` `tests/unit/test_schema.py`

### S-0037/D-2 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**Every closed set appears in the schema as an `enum`**, never a free string: transforms, quality rules, `Op`, `LogicalType`, `OnFail`, `Additivity`, document versions. This is the property constrained generation depends on — a proposer choosing from an enum cannot invent a transform, so the refusal that would catch the invention never fires. Unit-tested per set.

- Paths: `src/bloomery/schema.py` `tests/golden/test_spec_schemas.py` `tests/property/test_schema_agreement.py` `tests/unit/test_schema.py`

### S-0037/D-3 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**Schema export is deterministic and golden-tested**, on the same discipline as every other bloomery output: sorted keys, stable `$defs` order, no addresses in descriptions. A nondeterministic golden is noise, and these goldens are how schema changes become reviewable.

- Paths: `src/bloomery/schema.py` `tests/golden/test_spec_schemas.py` `tests/unit/test_determinism_guard.py` `tests/unit/test_schema.py`

### S-0037/D-5 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**`bloomery/cli/io.py` is the only module in the package permitted to touch the filesystem**, added to S-0036's purity allowlist as a named carve-out with a stated reason, and enforced one-directional by import-linter: the CLI may import the library, no library module may import the CLI. The shell reads paths; the library still only ever sees strings, so the no-I/O invariant is preserved *and made structurally obvious* rather than merely asserted.

- Paths: `src/bloomery/__init__.py` `src/bloomery/cli/io.py` `tests/unit/test_import_contracts.py`

### S-0037/D-7 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**Five refusals gain optional structured suggestion fields** (§5.4), additive. The draft cited two existing precedents; only one is real. `UnsupportedFilter.reason` is an attribute; **`UnknownMember.did_you_mean` is not** — its docstring has promised the field since S-0028 while the closest match is computed and thrown into prose. So `UnknownMember` joins the list as a fifth entry rather than serving as the model for it, and the field is what finally makes its own docstring true. Each field exposes a value bloomery **already computes and currently discards**. Absence is `()` or `None` in Python and `[]` or `null` in the CLI JSON — always present, never fabricated, and never silently dropped from a structure §5.2 promises matches the API (§5.4).

- Paths: `src/bloomery/errors.py` `tests/unit/test_error_suggestions.py` `tests/unit/test_marts/test_flatten.py`

### S-0037/D-11 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**Suggestion payloads are typed values, not encoded strings.** `covering_marts` carries `MartCoverage(mart, metric, grain)` rather than `tuple[str, ...]`: the field promises per-metric grain, and a tuple of strings can only deliver it through a format the caller has to parse and nobody has documented. That is the failure this section exists to remove, so shipping it inside the fix would be self-defeating. Cost: two new public types (`MartCoverage`, `MeasureRef`) that S-0035's closure then reaches and root-exports.

- Paths: `src/bloomery/__init__.py` `src/bloomery/errors.py` `tests/unit/test_error_suggestions.py`

### S-0039/D-1 — `ASSUMED` (`SpecEvidence`: spec analysis as a first-class output)

**`evaluate(project) -> SpecEvidence` is added**, composing `build_project_ir` → `resolve` and the batched refusal stages under one call and one frozen return type. It adds no analysis bloomery does not already perform; the contribution is naming the concept and stopping its discard at the exception boundary.

- Paths: `src/bloomery/evidence.py`

### S-0039/D-3 — `ASSUMED` (`SpecEvidence`: spec analysis as a first-class output)

**Partial analysis is the point**: the pipeline runs to the first refusing stage and reports the prefix. "Seven metrics reachable, two blocked on `cogs`, one refusal at `mappings/crm.yaml`" is unavailable today at any price, and is the most useful sentence bloomery can produce about a spec it will not compile. This is the only new behaviour in the RFC, and the pipeline already supports it — stages are already sequential and already batch.

- Paths: `src/bloomery/evidence.py` `src/bloomery/resolve/build.py` `tests/unit/test_evidence.py` `tests/unit/test_semantic/test_ratio_rows.py`

### S-0039/D-6 — `ASSUMED` (`SpecEvidence`: spec analysis as a first-class output)

**Data-dependent evidence stays out, permanently.** Coercion rates, null deltas and sample rows require execution; the platform composes `evaluate()` with its own dry-run into one review payload. `evaluate()` is the natural-looking home for "and also run it against a sample," and taking that step would put an engine connection inside the compiler and end the infrastructure-free test suite in the same commit.

- Paths: `src/bloomery/evidence.py`

### S-0039/D-9 — `ASSUMED` (`SpecEvidence`: spec analysis as a first-class output)

**`SpecEvidence` carries facts, never judgement** — no score, no confidence, no approve/reject. The reviewer decides; bloomery reports. This mirrors S-0022's rule that the compiler validates a recorded recipe but never chooses one.

- Paths: `src/bloomery/evidence.py`

### S-0040/D-1 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

Flattening an entity with `scd: type2` into a mart is **refused** at compile time, not silently emitted and not silently filtered to the current version. The join has no validity predicate and the relation has one row per version, so the emitted mart multiplies the base grain while every guardrail passes. Consequence: the only shipped way to use a historical dimension in a mart is a `type1` current-view entity built from it, until §5.3 exists.

- Paths: `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `tests/fixtures/scd2_mart_refusal/entity_model.yaml` `tests/fixtures/semantic_corpus/003-scd2-unqualified-join/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/003-scd2-unqualified-join/problem.md` `tests/golden/refusals/example-scd2-flatten.txt` `tests/golden/refusals/scd2_mart_refusal.txt` `tests/unit/test_fixtures.py` `tests/unit/test_guardrails/test_stage.py` `tests/unit/test_marts/test_flatten.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0040/D-2 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

A mart whose **`base`** is `scd: type2` is refused on the same account. There is no fan-out, but the declared `grain:` claims one row per entity while the relation holds one per version, so every measure counts revisions. Refusing both sides keeps "a mart's grain is what it says" true without exception.

- Paths: `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `tests/fixtures/scd2_as_of/marts.yaml` `tests/fixtures/scd2_mart_refusal/entity_model.yaml` `tests/fixtures/scd2_replay/marts.yaml` `tests/golden/refusals/scd2_mart_refusal.txt` `tests/unit/test_fixtures.py` `tests/unit/test_guardrails/test_stage.py` `tests/unit/test_marts/test_flatten.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0040/D-4 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

`convert` raises `UnsupportedByTarget` at **emit**, on all three dialects. It stays a registered transform with an unchanged typecheck, so the spec surface does not move and a future dialect clears the refusal by declaring a `Feature` — the mechanism S-0025 already provides.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/evidence.py` `src/bloomery/resolve/build.py` `src/bloomery/transforms/_builtins.py` `tests/fixtures/currency_convert_refusal/entity_model.yaml` `tests/support/type_conformance.py` `tests/unit/test_emit/test_currency_convert.py` `tests/unit/test_evidence.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0040/D-5 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

`_CONVERT_MARKER` is removed from the currency guardrail with D4. It is the token that permits mixed-currency arithmetic; leaving it would keep a compile-time "yes" whose only outcome is a run-time failure. Consequence: `CurrencyMismatch` becomes unconditional until §5.4 ships.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/arithmetic.py` `tests/unit/test_guardrails/test_arithmetic.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0047/D-2 — `LOCKED` (The unresolved-work report)

**`options` is enumerated in catalog order and never sorted, ranked or scored.** Enumerating what the catalog declares is a projection; ordering is where a preference would hide. `Recipe`'s docstring makes catalog order *authored* ("ordered by reliability"), so re-sorting — alphabetically included — destroys information rather than normalizing it. Consequence: this is a deliberate exception to the sort-every-collection habit, and it needs the §6 test with a non-alphabetical catalog or the exception is untested.

- Paths: `src/bloomery/cli/render.py` `src/bloomery/evidence.py` `tests/unit/test_unresolved.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0047/D-3 — `LOCKED` (The unresolved-work report)

**The two gaps are distinguished, and that is the RFC's reason to exist.** `UNLINKED` and `UNMAPPED` are reported identically today and need different edits (§3). Consequence: the report reads the entity model, not only the DAG, which is why it lives in `evidence.py` and not in `resolve/`.

- Paths: `src/bloomery/evidence.py` `tests/unit/test_unresolved.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0047/D-4 — `LOCKED` (The unresolved-work report)

**A single available option is still not chosen.** The tempting erosion of S-0022/D-2, refused explicitly so it is not re-proposed as an optimization: "exactly one qualifies" requires the compiler to have an opinion about qualification, the arity is a fact about the catalog on one day, and a spec that silently acquires a derivation is one whose author cannot account for their own numbers.

- Paths: `src/bloomery/evidence.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0047/D-5 — `ASSUMED` (The unresolved-work report)

**The report is a `COMPLETE`-stage product; a refusal empties it.** Recipe validation is in the pipeline's first stage, so a malformed choice costs the round's worklist (§3, cases (d)/(e)). Accepted because the refusal messages already name the fix precisely and the loop still terminates — fix the error, recompile, read the report. Graded `ASSUMED` rather than `LOCKED` because it is a claim about how an agent behaves, and whoever builds this may find the loop needs the partial report; the alternative is computing the options half before validation, which is possible since it needs no DAG.

- Paths: `src/bloomery/evidence.py` `tests/unit/test_unresolved.py`

### S-0047/D-6 — `LOCKED` (The unresolved-work report)

**Termination rests on `Recipe.requires` naming alias slots, never canonical fields.** Verified in `resolve_recipe`, which matches `requires` against the mapping's `from:` keys. Consequence: recipe *composition* would break the argument in §5.4, not merely complicate it, and would need a cycle check over recipes. Recorded here so the coupling is visible from the feature that would break it.

- Paths: `src/bloomery/evidence.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0047/D-8 — `ASSUMED` (The unresolved-work report)

**`provenance` returns to `SpecEvidence`.** It is computed on every `resolve()` and discarded, and has been off the CLI since S-0039/D-8. A loop needs its own memory, and the alternative is a chooser re-deriving its history from the mapping documents it wrote. Graded `ASSUMED` because it is additive and reversible: if it turns out no caller reads it, dropping the field costs nothing but a changelog line. Its order is `(entity, field)`, stated in §5.1 rather than left as the current implementation's habit.

- Paths: `src/bloomery/evidence.py`

### S-0047/D-9 — `LOCKED` (The unresolved-work report)

**Every entry names one edit; an entry that cannot is omitted.** The promise is not "here is a gap" but "here is the edit that would close it", and an entry a caller cannot act on is a worklist item that never clears. Consequence, and the only shape affected today: a canonical whose entity is built by more than one mapping is **not reported**, because its columns are per mapping (S-0041/D-26) and an entry keyed on `canonical` cannot say which document to edit. Nothing is hidden — the blocked metric is still `unreachable` — and the omission lifts when the report can carry a mapping identity, which is S-0041/phasing (P-2)'s question rather than this one's.

- Paths: `src/bloomery/evidence.py` `tests/unit/test_unresolved.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0047/D-10 — `LOCKED` (The unresolved-work report)

**`UNLINKED` and `UNMAPPED` close by different edits, and termination is measured accordingly.** An `UNLINKED` entry has no field to record a recipe on, so an entity-model edit turns it into `UNMAPPED` — progress without removal. The decreasing measure is therefore the pair (open canonicals, `UNLINKED` among them) under lexicographic order, and the bound is twice the number of open canonicals rather than that number (§5.4 carries the notation, which does not survive a table cell). Consequence: a chooser that writes only mappings terminates on the `UNMAPPED` subset and correctly leaves `UNLINKED` entries standing, which is the honest answer to half of §10's third question. An earlier draft of §5.4 claimed every accepted choice removes an entry; it does not, and the two-gap distinction D3 draws is what makes the error visible.

- Paths: `src/bloomery/evidence.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0049/D-1 — `LOCKED` (Mapping identity)

**The identity is the document name.** It is unique by construction (a key of the `sources` mapping), already computed, already the ordering key for `Project.mappings`, and already the user-facing coordinate for refusals (S-0019/source-paths). Consequence: identity is a filename, so a rename changes it — accepted under D4's boundary.

- Paths: `src/bloomery/evidence.py` `src/bloomery/resolve/resolution.py` `src/bloomery/spec/common.py` `src/bloomery/spec/mapping.py` `tests/property/test_schema_agreement.py` `tests/unit/test_resolve/test_resolution.py` `tests/unit/test_spec/test_mapping.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0049/D-6 — `LOCKED` (Mapping identity)

**S-0047/D-9's omission is not lifted here.** D9 gave two reasons and this RFC removes one; the other — what a worklist entry means when N documents could each close a gap — is a decision about the report's promise. Consequence: `_unresolved` keeps its `continue`, and the change is a comment saying what is now true. Answering both at once would decide S-0047's contract inside a document about nouns.

- Paths: `src/bloomery/evidence.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-5 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**`cumulative:` is lowered, and the blanket `UnsupportedCumulative` refusal is deleted rather than narrowed.** The class goes with it: a reserved-surface error whose surface is no longer reserved is a class that can only mislead. Combinations that still cannot be lowered are refused by their own named guardrails (D7).

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/planner/semantic_plan.py` `tests/execution/test_period_over_period.py` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_planner/test_metricflow_planner.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-7 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**`derived:` and `cumulative:` on one metric is refused.** A derived metric has no measure and a cumulative window accumulates one; the combination names two mutually exclusive shapes, and MetricFlow has no type for it. Refused by name at the guardrail stage rather than left to produce an invalid manifest.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/metrics.py` `tests/unit/test_guardrails/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-9 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A filter's dimension is checked against every mart listing the metric, at the guardrail stage.** Not at emit: a filter naming a column no mart flattens is a *model* error, decidable from the spec, and it should fail with the batched aggregate every other model error joins. Checking every listing mart rather than the owning one avoids reaching for the ownership rule from a layer below the module that defines it, and is a superset of what correctness needs.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/errors.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/semantic/additivity.py` `tests/fixtures/period_over_period/entity_model.yaml` `tests/unit/test_guardrails/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0053/D-1 — `LOCKED` (Measure semantic types and additivity algebra)

**The aggregation vocabulary is a closed typed set, never a target-interpreted string.** `Additive`, `SemiAdditive`, `NonAdditive`, `Ratio`, `DistinctCount`, `Snapshot`. Locked because the planner, the proof rules and every emitter branch on it: an open string set makes each target the authority for what a measure means, which is the arrangement this whole sequence exists to end. Staging the *implementation* across releases is fine; encoding a future class as a string is not.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/ir/nodes.py` `src/bloomery/spec/common.py` `tests/fixtures/semantic_corpus/005-semi-additive-balance/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/005-semi-additive-balance/problem.md` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/problem.md` `tests/unit/test_guardrails/test_additivity.py` `tests/unit/test_semantic/test_rollup.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0053/D-2 — `LOCKED` (Measure semantic types and additivity algebra)

**A ratio is stored as its operands, not as a materialized quotient.** `SUM(num)/SUM(den)` and `AVG(ratio)` differ, the second is what a numeric-looking column invites, and the difference is a plausible wrong number. This is also S-0055's precondition — a derived metric spanning two branches cannot be reconstructed after the operands are gone — so reversing it later strands that document.

- Paths: `src/bloomery/emit/lower/rollups.py` `src/bloomery/errors.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/mart.py` `tests/fixtures/semantic_corpus/002-average-of-averages/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/002-average-of-averages/problem.md` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/problem.md` `tests/fixtures/semantic_corpus/008-ratio-rollup/bloomery/declared/metrics.yaml` `tests/fixtures/semantic_corpus/008-ratio-rollup/bloomery/naive/metrics.yaml` `tests/fixtures/semantic_corpus/008-ratio-rollup/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/008-ratio-rollup/problem.md` `tests/fixtures/semantic_corpus/012-rollup-recounts-identities/problem.md` `tests/unit/test_emit/test_rollups.py` `tests/unit/test_guardrails/test_additivity.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_steps/test_step_canonicals.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0057/D-1 — `LOCKED` (`bloomery check` and imported semantic provenance)

**P1 requires no dbt, no SQLMesh, no credentials, no network and no emission.** It is what makes the command usable in pre-commit and on an untrusted CI runner, and every one of those dependencies is easy to acquire accidentally and hard to remove afterwards. The compiler is already pure under S-0020; this keeps the command honest to that.

- Paths: `src/bloomery/evidence.py` `src/bloomery/semantic/rollup.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0057/D-3 — `LOCKED` (`bloomery check` and imported semantic provenance)

**No importer converts absence into a guessed default that strengthens semantics.** The dangerous direction is specific: a missing additivity becoming `Additive`, a missing grain becoming the entity's. Silence in a foreign artifact means unknown, and unknown is not safe.

- Paths: `src/bloomery/errors.py` `src/bloomery/imports.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0057/D-5 — `ASSUMED` (`bloomery check` and imported semantic provenance)

**Counts report surfaces actually checked, never totals that imply unproven coverage.** A green `check` must not read as "every future query is safe", which is precisely what a large round number invites. Not `LOCKED` because the right *set* of categories is a presentation question execution may adjust.

- Paths: `src/bloomery/evidence.py` `tests/unit/test_cli.py` `tests/unit/test_evidence.py`

### S-0059/D-1 — `LOCKED` (Loose ends inside shipped subsystems)

MetricFlow ships as a fourth **core** target (`Target.METRICFLOW`), not an extension registered through `register_emitter`. It is built in-tree, golden-tested and hydrated by the planner already; leaving it out of `Target` would make the enum a claim about maturity it does not otherwise make.

- Paths: `src/bloomery/compile.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0059/D-6 — `LOCKED` (Loose ends inside shipped subsystems)

The node-id collision is **refused**, not re-spelled. `Node.name` and the `lineage --node` argument are published surface, and the resolve API is not covered by the emitted-artifact stability caveat. Locks the bare `<entity>.<field>` spelling in: changing it later is a breaking change to every stored lineage id, which is exactly what this row buys.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/lineage.py` `src/bloomery/resolve/graph.py` `src/bloomery/resolve/timeline.py` `tests/unit/test_guardrails/test_lineage.py` `tests/unit/test_resolve/test_graph.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0059/D-7 — `LOCKED` (Loose ends inside shipped subsystems)

`metric`, `canonical`, `source` and `step` are reserved as entity names **unconditionally** — not only when a real collision exists. A conditional refusal makes a spec's validity depend on a metric added later in another file.

- Paths: `src/bloomery/errors.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0062/D-10 — `LOCKED` (Ownership, classification and grants)

`secret` on a column a **published relation** carries is a refusal — a mart or a rollup, unconditionally. A published relation is the thing `secret` says this column is not part of, so the two statements cannot both hold. Independent of redaction, and of whether anything is granted.

- Paths: `pages/docs/how-to/annotate-a-spec.md` `src/bloomery/errors.py` `src/bloomery/evidence.py` `src/bloomery/guardrails/classification.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0062/D-11 — `LOCKED` (Ownership, classification and grants)

A `pii`/`secret` column reaching a relation that **admits a role its source entity does not** is a refusal — a set difference, not a superset test, so disjoint grant sets are refused too: a role that can read the mart and not the entity is the leak whether or not the mart also admits the entity's roles; an **undeclared** audience on either side is an advisory, not a refusal. Refusing the unknown case would refuse every project managing gold grants outside bloomery, and the compiler can only call a contradiction where it holds both statements.

- Paths: `pages/docs/how-to/annotate-a-spec.md` `src/bloomery/errors.py` `src/bloomery/evidence.py` `src/bloomery/guardrails/classification.py` `src/bloomery/guardrails/stage.py` `tests/unit/test_classification_guard.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0063/D-2 — `LOCKED` (Exposures and downstream consumers)

An exposure naming an undeclared metric or mart is refused. An exposure pointing at nothing reports clean, which is the failure mode the feature exists to remove.

- Paths: `pages/docs/how-to/declare-an-exposure.md` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/exposures.py` `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/graph.py` `tests/unit/test_guardrails/test_exposures.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0065/D-5 — `LOCKED` (Rollup marts and pre-aggregations)

An unprovable rollup is **refused**, never warned about. A rollup is read instead of the detail table, so a wrong one answers quickly and plausibly — the class this project refuses rather than approximates.

- Paths: `src/bloomery/cli/render.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/evidence.py` `src/bloomery/guardrails/stage.py` `src/bloomery/marts/rollup.py` `src/bloomery/semantic/rollup.py` `tests/fixtures/semantic_corpus/012-rollup-recounts-identities/problem.md` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0066/D-7 — `OPEN` (Declared input currency for conversion)

**Whether `currency_in:` extends to `RecipeFieldMapping` and `MacroFieldMapping`.** This row assumed a recipe's chain can hold a conversion, and it cannot: a `Recipe` is `{id, requires, expr}` — a SQL expression over aliases, with no transform chain — and a macro's body is opaque SQL. Neither can carry a `convert` step, so neither can hold a conversion whose input would need declaring, and neither reaches the code that would ask. Answered "no" for both, and "yes" for `KeyField`, which this row did not think to ask about (see `logs/T-0025.md` (`logs/T-0025.md`), D158).

- Paths: `src/bloomery/evidence.py` `tests/unit/test_evidence.py`

### S-0070/D-4 — `LOCKED` (Consumer-declared evidence strictness)

The refusal names how the fact was obtained and what to write instead. A message that only says "insufficient evidence" gets worked around by deleting the requirement.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/evidence.py` `src/bloomery/guardrails/stage.py` `src/bloomery/semantic/proof.py` `tests/unit/test_guardrails/test_evidence.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0075/D-4 — `LOCKED` (Mechanical imports and per-relationship provenance)

**Two relationships are the same relationship when `(from, to, via)` match, and a cardinality disagreement between an imported and a declared one refuses naming both.** S-0057/D-4 mandates the refusal and leaves the predicate undefined, which makes it unimplementable. Not `name`: an importer generates names and an author picks them, so name equality reports every import as a conflict and every renamed import as none. Agreement on the same triple is not a contradiction and is accepted silently.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/imports.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

## Invariants holding over `src/bloomery/`

- **S-0004/I-1**: Compiling the corpus with a capturing handler at DEBUG on the `bloomery` logger and with no handler at all produces byte-identical artifacts, and the listening run demonstrably captured records
  - Paths: `src/bloomery/**`
  - Check: `uv run pytest tests/unit/test_determinism_guard.py -q`
- **S-0004/I-2**: The package installs exactly one `NullHandler`, sets no level, leaves propagation alone, survives a reload without accumulating a second handler, and emits no record at `WARNING` or above over a real compile
  - Paths: `src/bloomery/**`
  - Check: `uv run pytest tests/unit/test_logging_posture.py -q`

<!-- /torve:managed -->
