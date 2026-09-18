<!-- torve:managed src/bloomery/steps — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/steps/`

### S-0020/D-5 — `ASSUMED` (Intermediate representation and determinism contract)

Floats are banned in IR and emission; `Decimal`/int only.

- Paths: `src/bloomery/cli/serialize.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/steps.py` `src/bloomery/ir/fingerprint.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/request.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/common.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `src/bloomery/steps/manifest.py` `src/bloomery/steps/splice.py` `src/bloomery/transforms/_builtins.py` `src/bloomery/typing/types.py` `tests/execution/test_as_of_join.py` `tests/execution/test_currency_convert.py` `tests/execution/test_fanout_trap.py` `tests/execution/test_marts.py` `tests/execution/test_period_over_period.py` `tests/execution/test_rollup.py` `tests/fixtures/semantic_corpus/002-average-of-averages/naive.sql` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/golden/schema/marts.json` `tests/support/planning.py` `tests/support/semantic_corpus.py` `tests/unit/test_cli.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_planner/test_request.py` `tests/unit/test_quality/test_edges.py` `tests/unit/test_spec/test_metrics.py` `tests/unit/test_spec/test_quality.py` `tests/unit/test_steps/test_lowering.py` `tests/unit/test_steps/test_manifest_and_registry.py` `tests/unit/test_typing/test_types.py`

### S-0021/D-6 — `ASSUMED` (Logical types and the transform registry)

`register_transform(spec)` is public API; the default registry is a module-level immutable mapping built at import, extensions live in a process-global overlay, name collisions are errors, and all registry iteration is sorted by name. Consequence: determinism is scoped to a fixed installed extension set.

- Paths: `src/bloomery/steps/registry.py` `src/bloomery/transforms/__init__.py` `src/bloomery/transforms/registry.py`

### S-0021/D-7 — `ASSUMED` (Logical types and the transform registry)

Transform builders produce SQLGlot AST only — never string formatting. Dialect rendering happens at emit (S-0025); dialect incapability is an emit-time `DialectPort` feature failure, never a typing concern.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/steps/splice.py` `src/bloomery/transforms/_builtins.py` `tests/unit/test_steps/test_splice.py`

### S-0034/D-3 — `ASSUMED` (The step registry: referenced implementations)

`StepRegistry` is a frozen compile **input** (steps mapping + macro bodies), assembled by the caller; `compile_project(..., steps: StepRegistry = EMPTY_REGISTRY)`. Unknown ref or version → `UnknownStep` naming available versions. **No dynamic loading path exists** — tenant specs can never become an arbitrary-code-execution surface.

- Paths: `src/bloomery/errors.py` `src/bloomery/spec/steps.py` `src/bloomery/steps/registry.py` `tests/unit/test_schema.py`

### S-0034/D-4 — `ASSUMED` (The step registry: referenced implementations)

Trust-then-verify: compile time trusts `produces` (DAG complete, downstream typechecked, `plan()` computes backfills across the step); the generated wrapper carries a non-optional, non-configurable `assert_step_contract` (outputs present, none undeclared, exact column set, assignable types, required-null check, grain uniqueness over the output's declared `key`). A claim that is checked is a commitment; a claim that isn't is a comment. New errors: `UnknownStep`, `StepDeterminismError` (compile), `StepContractViolation` (runtime, raised by generated code).

- Paths: `src/bloomery/steps/contract.py`

### S-0034/D-13 — `ASSUMED` (The step registry: referenced implementations)

Implementation binding: `StepRegistry` gains `sql_bodies: Mapping[tuple[str, int], str]` (`sql_model` bodies, parsed at compile like `macro_bodies`); `StepManifest` gains `entrypoint: str` (`"package.module:function"`) for `python_model`, and the generated wrapper imports it at **run time**. The no-dynamic-loading rule is scoped to compile time — bloomery never imports or executes step code while compiling (manifests and SQL text only); runtime import of platform-owned code by the generated model is the normal SQLMesh execution path, and registry build (caller-side) verifies the entrypoint resolves.

- Paths: `src/bloomery/spec/mapping.py` `src/bloomery/steps/manifest.py` `tests/e2e/test_sqlmesh_replan.py` `tests/golden/schema/mapping.json`

### S-0034/D-16 — `ASSUMED` (The step registry: referenced implementations)

Multi-output emission resolved — **supersedes the draft §10 entry and its execute-exactly-once constraint** (recorded honestly: that constraint is dropped, not satisfied): each declared output gets its own generated wrapper model, each executing the step and returning its own output; safe **for correctly declared steps** — nondeterministic steps are compile-refused and seeded steps re-execute with the same recorded seed (pure/seeded ⇒ identical results); residual risk recorded: a *misdeclared* step slips the compile check and, under N executions, can produce disagreeing sibling outputs within one run (behavioral gates catch run-to-run, not intra-run, divergence) — accepted for v1, with a cross-output consistency audit named as the demand-gated mitigation. `assert_step_contract` runs in every wrapper against **all** declared outputs, catching partial-output lies wherever the run starts. The N-executions-for-N-outputs cost is documented; a single-execution staging optimization is a demand-gated, named escape hatch — not built.

- Paths: `src/bloomery/emit/steps.py` `src/bloomery/resolve/steps.py` `src/bloomery/steps/manifest.py` `tests/execution/test_step_consistency.py` `tests/golden/test_sqlmesh_duckdb.py` `tests/unit/test_steps/test_emission.py`

### S-0034/D-22 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-08, M13)* **§9's "dependency-light by construction" was untrue as laid out, and is partly repaired.** Measured: `import bloomery.steps.contract` cost ~400 ms and 1011 modules, pulling in metricflow, jinja2, sqlglot, pydantic and yaml — because importing a submodule executes its parent packages' `__init__` first, and bloomery's top-level one imports the whole compile surface. A package-wide lazy `__getattr__` (PEP 562) fixed it completely — 6.5 ms, 55 modules, no heavy dependencies — and was **reverted**: `plan` and `resolve` are both public functions *and* submodule names, so once the submodule is imported the module attribute shadows the function and `from bloomery import plan` returns a module. Import-order-dependent silent breakage is worse than a slow import. Kept: the collision-free half, a lazy `bloomery.steps`. The remaining cost is §8's named escape hatch (extract `contract.py` into a micro-package), still not built; recorded here so the claim in §9 is not read as satisfied.

- Paths: `src/bloomery/steps/__init__.py` `tests/unit/test_steps/test_emission.py`

### S-0034/D-50 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-09)* **Tier 1 has a spec surface: a mapping references a macro, in two shapes.** D26 refused a wired `sql_macro` because none existed, so the docs described a splice that could not happen. A field mapping gains a third shape beside `from:` and `recipe:` — `step: ref@version` with `from:` binding the columns it consumes — and a transform chain gains a `{step: ref@version}` link, so Tier 0 and Tier 1 compose on one field (the field shape binds a *raw* source path, so without the link no whitelist transform can run before the macro). A macro is referenced **inline**, never wired in `steps:`: it writes no relation, so it has no output to bind there, and one wiring per ref (D13) would make a macro usable in exactly one mapping with one parameter set — the pressure that produces `fuzzy_score_strict`, which is the fork §5.7 exists to refuse. Parameters are therefore supplied at the call site. The splice happens at **lowering**, so the macro is part of `ColumnIR.expr`, the model stays one query, and lineage sees through it — which moved `macro_expression` from `emit.steps` down to `bloomery.steps.splice` (emit sits *above* resolve, so the emitter could not own a splice the lowering needs), taking `parameter_literal` with it now both SQL tiers need the same typed literal. Consequence found by the type gate rather than by reading: the field-mapping union grew a third member, and five sites assumed two — a macro binds aliases like a recipe and has no chain, so they test an `ALIAS_BOUND` pair.

- Paths: `src/bloomery/resolve/build.py` `src/bloomery/resolve/graph.py` `src/bloomery/resolve/resolution.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/mapping.py` `src/bloomery/spec/quality.py` `src/bloomery/steps/splice.py` `tests/unit/test_resolve/test_edge_shapes_offcorpus.py` `tests/unit/test_steps/test_splice.py`

### S-0034/D-53 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-11)* **`parameter_literal` validates its numeric branch, because that branch renders unquoted.** The function's own docstring calls itself the injection boundary — "what makes ``x' OR 1=1 --`` a string containing an apostrophe rather than a predicate" — and that was true of the *string* branch, which quotes, and false of `int`/`decimal`, which do not. A Tier 1 call site spelling `parameters: {factor: "1 OR 1=1"}` emitted `CAST(amt * 1 OR 1 = 1 AS DECIMAL(12, 4))`: a predicate spliced into a projection. Tier 2 validated its parameters at the registry and Tier 1 never did, and the fix is deliberately **not** the missing call at the second call site — the check moves below both tiers, to where the rendering happens, so a third caller cannot reintroduce it.

- Paths: `src/bloomery/steps/splice.py` `tests/unit/test_steps/test_macro_fields.py`

### S-0034/D-55 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-11)* **A `StepRegistry` key must be the identity its manifest declares.** The registry is keyed by `(ref, version)` and the manifest carries the same pair, so the two could disagree — silently, which is what makes it worth a row: `lower_steps` builds `StepIR` from the *manifest* identity while the wiring's canonical links and `on_fail: fail` rules are keyed by the *wiring* identity, so a mismatch drops those without a word. Checked at construction, the one moment a frozen compile input can be checked once for every later reader — the same argument that makes collision an error in the transform registry (S-0021/D-6). The check found an existing disagreement in the test corpus on its first run.

- Paths: `src/bloomery/steps/registry.py` `tests/unit/test_steps/test_manifest_and_registry.py`

### S-0034/D-56 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-11)* **D53's numeric guard is a syntax check, not a parse — because Python's numeric parsers accept strings SQL does not.** The first fix validated with `Decimal(value)`, which is the wrong tool for a question about what may be *emitted*: the literal that reaches the SQL is the original text, and `Decimal("1_0")` is 10 while `1_0` in a projection is not a number at all. `Decimal` also accepts `Infinity` and `NaN`, which render as bare identifiers rather than numbers, and `1e400`, which no column can hold. Separately, `int` was validated as merely numeric, so a parameter declared `int` and given `"1.5"` emitted `1.5` — a different type reaching the SQL than the manifest promised. Now a per-type pattern matching SQL numeric-literal syntax, with no exponent form: a spec author writes `0.85` rather than `8.5e-1`, and admitting `1e400` would mean deciding what an unrepresentable bound means. Recorded rather than folded into D53 because the failure is instructive — a guard can be in the right *place* and still ask the wrong question.

- Paths: `src/bloomery/steps/splice.py`

<!-- /torve:managed -->
