<!-- torve:managed tests/unit/test_steps — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/unit/test_steps/`

### S-0020/D-5 — `ASSUMED` (Intermediate representation and determinism contract)

Floats are banned in IR and emission; `Decimal`/int only.

- Paths: `src/bloomery/cli/serialize.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/steps.py` `src/bloomery/ir/fingerprint.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/request.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/common.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `src/bloomery/steps/manifest.py` `src/bloomery/steps/splice.py` `src/bloomery/transforms/_builtins.py` `src/bloomery/typing/types.py` `tests/execution/test_as_of_join.py` `tests/execution/test_currency_convert.py` `tests/execution/test_fanout_trap.py` `tests/execution/test_marts.py` `tests/execution/test_period_over_period.py` `tests/execution/test_rollup.py` `tests/fixtures/semantic_corpus/002-average-of-averages/naive.sql` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/golden/schema/marts.json` `tests/support/planning.py` `tests/support/semantic_corpus.py` `tests/unit/test_cli.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_planner/test_request.py` `tests/unit/test_quality/test_edges.py` `tests/unit/test_spec/test_metrics.py` `tests/unit/test_spec/test_quality.py` `tests/unit/test_steps/test_lowering.py` `tests/unit/test_steps/test_manifest_and_registry.py` `tests/unit/test_typing/test_types.py`

### S-0021/D-7 — `ASSUMED` (Logical types and the transform registry)

Transform builders produce SQLGlot AST only — never string formatting. Dialect rendering happens at emit (S-0025); dialect incapability is an emit-time `DialectPort` feature failure, never a typing concern.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/steps/splice.py` `src/bloomery/transforms/_builtins.py` `tests/unit/test_steps/test_splice.py`

### S-0023/D-2 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Violations are batched project-wide: leaf errors (`UnitMismatch`, `TaxBasisMismatch`, `CurrencyMismatch`, `GrainMismatch`, `AdditivityViolation`, `AssertLoweringError`) are collected and raised as one `GuardrailError` aggregate, sorted by `(source_path, type)`. Matches S-0019/D-6.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/arithmetic.py` `src/bloomery/guardrails/quality.py` `src/bloomery/guardrails/stage.py` `src/bloomery/quality/reconcile.py` `src/bloomery/resolve/build.py` `src/bloomery/resolve/steps.py` `tests/fixtures/fanout_trap/metrics.yaml` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_guardrails/test_stage.py` `tests/unit/test_steps/test_lowering.py`

### S-0024/D-2 — `ASSUMED` (Plan: spec diff and change classification)

`plan(old_ir | None, new_ir)` is a pure structural diff of two `ProjectIR`s — no external lineage, no I/O. `plan(None, ir)` = all ADDITIVE (initial deploy); `plan(ir, ir)` = empty, property-tested (S-0026).

- Paths: `src/bloomery/plan/diff.py` `src/bloomery/plan/model.py` `tests/unit/test_cli.py` `tests/unit/test_plan/test_diff.py` `tests/unit/test_plan/test_exposures.py` `tests/unit/test_plan/test_quality_changes.py` `tests/unit/test_plan/test_step_changes.py` `tests/unit/test_steps/test_step_entities.py`

### S-0025/D-4 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

SQL rendering: SQLGlot AST → `DialectPort.render`; Jinja only ever sees pre-rendered strings (envelope templating).

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/emit/steps.py` `tests/property/test_compile_properties.py` `tests/unit/test_steps/test_dbt_and_cube_emission.py`

### S-0033/D-9 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Silver gains `_quality_flags`/`_quality_ok`; marts gain `has_quality_flags` (S-0027 amendment). Array capability is `DialectFeature.ARRAY` — an engine property, deliberately diverging from Document 5's `TargetCapabilities` placement; dialects without it lower to a delimited string.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/marts/flatten.py` `src/bloomery/spec/common.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_steps/test_lowering.py`

### S-0034/D-5 — `ASSUMED` (The step registry: referenced implementations)

Determinism tiers: `pure` (freely backfillable) | `seeded` (seed required in the spec, recorded) | `nondeterministic` (**compile error**). Restatement is the organizing capability of the architecture; refusing nondeterminism is the load-bearing constraint, not conservatism.

- Paths: `src/bloomery/errors.py` `src/bloomery/ir/nodes.py` `tests/support/identity.py` `tests/unit/test_steps/test_identity_demo.py`

### S-0034/D-8 — `ASSUMED` (The step registry: referenced implementations)

Emission: `sql_macro` splices into the entity SELECT (one query); `sql_model` emits an ordinary model artifact from the registry body; `python_model` emits a generated SQLMesh Python-model `.py` artifact (S-0025/D-2 file-shaped) wrapping the impl + contract assertion. Step outputs are DAG entities with manifest grain; two steps writing one output is a compile error (settles Document 5 §11.5).

- Paths: `src/bloomery/emit/steps.py` `src/bloomery/resolve/steps.py` `tests/unit/test_steps/test_emission.py` `tests/unit/test_steps/test_lowering.py`

### S-0034/D-16 — `ASSUMED` (The step registry: referenced implementations)

Multi-output emission resolved — **supersedes the draft §10 entry and its execute-exactly-once constraint** (recorded honestly: that constraint is dropped, not satisfied): each declared output gets its own generated wrapper model, each executing the step and returning its own output; safe **for correctly declared steps** — nondeterministic steps are compile-refused and seeded steps re-execute with the same recorded seed (pure/seeded ⇒ identical results); residual risk recorded: a *misdeclared* step slips the compile check and, under N executions, can produce disagreeing sibling outputs within one run (behavioral gates catch run-to-run, not intra-run, divergence) — accepted for v1, with a cross-output consistency audit named as the demand-gated mitigation. `assert_step_contract` runs in every wrapper against **all** declared outputs, catching partial-output lies wherever the run starts. The N-executions-for-N-outputs cost is documented; a single-execution staging optimization is a demand-gated, named escape hatch — not built.

- Paths: `src/bloomery/emit/steps.py` `src/bloomery/resolve/steps.py` `src/bloomery/steps/manifest.py` `tests/execution/test_step_consistency.py` `tests/golden/test_sqlmesh_duckdb.py` `tests/unit/test_steps/test_emission.py`

### S-0034/D-22 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-08, M13)* **§9's "dependency-light by construction" was untrue as laid out, and is partly repaired.** Measured: `import bloomery.steps.contract` cost ~400 ms and 1011 modules, pulling in metricflow, jinja2, sqlglot, pydantic and yaml — because importing a submodule executes its parent packages' `__init__` first, and bloomery's top-level one imports the whole compile surface. A package-wide lazy `__getattr__` (PEP 562) fixed it completely — 6.5 ms, 55 modules, no heavy dependencies — and was **reverted**: `plan` and `resolve` are both public functions *and* submodule names, so once the submodule is imported the module attribute shadows the function and `from bloomery import plan` returns a module. Import-order-dependent silent breakage is worse than a slow import. Kept: the collision-free half, a lazy `bloomery.steps`. The remaining cost is §8's named escape hatch (extract `contract.py` into a micro-package), still not built; recorded here so the claim in §9 is not read as satisfied.

- Paths: `src/bloomery/steps/__init__.py` `tests/unit/test_steps/test_emission.py`

### S-0034/D-31 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-08, M13 self-audit; narrowed by D52)* **Steps are refused on dbt and Cube rather than dropped, and the DAG edges were fiction.** `step_artifacts` is wired into the SQLMesh emitter only; the other two targets emitted no step artifacts and no error, silently withholding relations downstream models were typechecked against — now `UnsupportedByTarget` (S-0025/D-3: fail loud, never approximate). Separately, step edges hung off a synthetic `<entity>.*` node that no other producer or consumer ever creates, so the "upstream reaches it in topological order" claim was false and the node only detected self-loops. Input edges now come from every field of the named entity, output edges from the step's produced columns.

- Paths: `tests/unit/test_steps/test_dbt_and_cube_emission.py`

### S-0034/D-41 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-08, M13 re-audit; built by D49)* **D36 claimed more than shipped: metrics and `reconcile` still cannot reference a step output.** §5.8 names "downstream mappings, marts, and metrics"; marts work and metrics do not — metric resolution keys on *mappings*, and a step entity has none, so a measure over a step column is `unreachable metric … no mapped derivation path`. `reconcile` refuses them too, for the same reason. Both fail loud rather than silently, so this is a documentation defect and not a correctness one — but the RFC row is the authority (CLAUDE.md), and a row claiming more than the code does is the kind of drift the corpus exists to prevent. D36 is narrowed to marts and downstream models; metrics and reconcile over step outputs are the next increment, named like D39 names quality rules.

- Paths: `src/bloomery/guardrails/quality.py` `tests/unit/test_steps/test_step_canonicals.py`

### S-0034/D-49 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-09)* **D41 is built: metrics and `reconcile` reach step outputs, through a declared canonical link.** What was missing was a *surface*, not a mechanism. A metric is reachable iff every leaf of its `requires` closure is **available**, and a canonical field is available iff something draws a `canonical` edge to it — which only mapped entity fields could. So a step's columns were never available and any metric over one was unreachable, for a reason narrower than D41's own wording ("metric resolution keys on mappings") suggested. `StepWiring` gains `canonical: {<output>: {<column>: <canonical_field>}}`. On the **wiring**, not in the manifest: canonical names are the authored spec's vocabulary, and a manifest naming them could not be reused by a second project spelling them differently — the fork §5.7 exists to refuse. Never inferred from a matching column name, which is D43's argument about references applied to the same temptation. Nothing about metric resolution changed: the link draws the ordinary `canonical` edge and reachability follows. `reconcile` needed a second, unrelated repair — it resolved sides against *declared and mapped* entities, and a step output is neither, so a check naming one was refused as "declared but no mapping targets it", which is true and useless since the step writes the relation. Both kinds now answer through one `_SideEntity` view (field names and key), so the check asks what it needs rather than branching on provenance; declared-but-unmapped stays refused, which was always the real point. The refusal's wording now names both ways a relation can exist.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/resolve/graph.py` `src/bloomery/resolve/refs.py` `src/bloomery/spec/steps.py` `tests/fixtures/identity_resolution/catalog.yaml` `tests/fixtures/identity_resolution/steps.yaml` `tests/unit/test_quality/test_reconcile.py` `tests/unit/test_steps/test_step_canonicals.py` `tests/unit/test_unresolved.py`

### S-0034/D-50 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-09)* **Tier 1 has a spec surface: a mapping references a macro, in two shapes.** D26 refused a wired `sql_macro` because none existed, so the docs described a splice that could not happen. A field mapping gains a third shape beside `from:` and `recipe:` — `step: ref@version` with `from:` binding the columns it consumes — and a transform chain gains a `{step: ref@version}` link, so Tier 0 and Tier 1 compose on one field (the field shape binds a *raw* source path, so without the link no whitelist transform can run before the macro). A macro is referenced **inline**, never wired in `steps:`: it writes no relation, so it has no output to bind there, and one wiring per ref (D13) would make a macro usable in exactly one mapping with one parameter set — the pressure that produces `fuzzy_score_strict`, which is the fork §5.7 exists to refuse. Parameters are therefore supplied at the call site. The splice happens at **lowering**, so the macro is part of `ColumnIR.expr`, the model stays one query, and lineage sees through it — which moved `macro_expression` from `emit.steps` down to `bloomery.steps.splice` (emit sits *above* resolve, so the emitter could not own a splice the lowering needs), taking `parameter_literal` with it now both SQL tiers need the same typed literal. Consequence found by the type gate rather than by reading: the field-mapping union grew a third member, and five sites assumed two — a macro binds aliases like a recipe and has no chain, so they test an `ALIAS_BOUND` pair.

- Paths: `src/bloomery/resolve/build.py` `src/bloomery/resolve/graph.py` `src/bloomery/resolve/resolution.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/mapping.py` `src/bloomery/spec/quality.py` `src/bloomery/steps/splice.py` `tests/unit/test_resolve/test_edge_shapes_offcorpus.py` `tests/unit/test_steps/test_splice.py`

### S-0034/D-52 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-10)* **D31's blanket refusal was one sentence covering two different targets, and it is right about neither in full.** D31 refused steps on dbt and Cube because "their output relations would simply be missing" — checked per target, that argument splits. **Cube builds nothing.** It emits cubes and views over marts, and no silver model, no reject table, no replay statement and no audit for *anything*: the `dirty_corpus` fixture — twelve quality-carrying entities, twelve reject models, a conservation audit apiece — compiles to two files on Cube and always has, refusing none of it. So "the relation would be missing" was never a reason to refuse a step *here*; it is equally true of every silver entity, and singling steps out made this emitter refuse one build-side declaration among the many it already leaves to whoever maintains the tables. The refusal is removed, and its docstring now says what the contract actually is: Cube consumes tables SQLMesh maintains, and is deliberately silent about how. (The mart-assertion refusal added the day before, S-0033/D-89, is removed from Cube for the same reason and stays on dbt.) **dbt builds**, so a step must emit or refuse, and the answer is per tier. Tier 1 needs nothing: the splice happens at lowering, so a macro is already inside its consuming model on every target — which means Tier 1 worked on dbt throughout and D31 never claimed otherwise only because a macro is referenced inline rather than wired in `steps:`. Tier 2 **emits**: the body is already canonicalized and parameter-substituted on `StepIR`, so dbt wraps the same SELECT SQLMesh does in its own envelope — asserted as byte equality between the two targets rather than as a claim, since one SELECT meaning two things is exactly the drift the shared lowering exists to prevent. Tier 3 stays refused, on a concrete reason rather than a blanket one: dbt *has* Python models, but only on Snowflake, BigQuery and Databricks, and none of bloomery's three dialects is one of them, so the wrapper would have no adapter to execute it. **Step audits are refused on dbt** — a consistency audit (D40) is a join between sibling outputs and an `on_fail: fail` body (D39) is a whole query, while dbt's schema tests are per-column or per-model predicates; `_entity_tests` already refuses an audit kind on exactly this ground. The refusal is decided by *building* the audits rather than by the presence of a step, so a single-output Tier 2 step with no `fail` rules keeps the tier instead of losing it to a reason that does not apply to it. **One trap, found and closed:** a step output is an entity in the DAG (D36) whose lowered `expr` is the column referring to itself, so removing the refusal without skipping `produced_by` entities would have had dbt emit an ordinary entity model beside the step's — a model selecting from the relation it defines, and two models writing one relation. SQLMesh already skipped them; dbt now does too. **Not verified, stated:** that dbt *parses* the emitted model is S-0026's outstanding `dbt parse` tier, not something this row claims. What is verified is that the SELECT is byte-identical to SQLMesh's and that the envelope is the one the dbt goldens already lock.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/steps.py` `tests/e2e/test_dbt_parse.py` `tests/golden/test_cube.py` `tests/unit/test_marts/test_asserts.py` `tests/unit/test_steps/test_dbt_and_cube_emission.py`

### S-0034/D-53 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-11)* **`parameter_literal` validates its numeric branch, because that branch renders unquoted.** The function's own docstring calls itself the injection boundary — "what makes ``x' OR 1=1 --`` a string containing an apostrophe rather than a predicate" — and that was true of the *string* branch, which quotes, and false of `int`/`decimal`, which do not. A Tier 1 call site spelling `parameters: {factor: "1 OR 1=1"}` emitted `CAST(amt * 1 OR 1 = 1 AS DECIMAL(12, 4))`: a predicate spliced into a projection. Tier 2 validated its parameters at the registry and Tier 1 never did, and the fix is deliberately **not** the missing call at the second call site — the check moves below both tiers, to where the rendering happens, so a third caller cannot reintroduce it.

- Paths: `src/bloomery/steps/splice.py` `tests/unit/test_steps/test_macro_fields.py`

### S-0034/D-54 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-11)* **A chain link whose macro declares an undefaulted parameter is refused.** The `{step: ref@v}` chain form is a bare reference with nowhere to pass values, unlike the `step:`/`from:` field shape and its `parameters:` map — so `_splice_link` passes `{}`, `_macro_parameters` omits every parameter without a default, and `splice` leaves those `:name` placeholders alone. The result reached emitted SQL as a live placeholder (`CAST(nm AS TEXT)

- Paths: `src/bloomery/resolve/build.py` `tests/unit/test_steps/test_macro_fields.py`

### S-0034/D-55 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-11)* **A `StepRegistry` key must be the identity its manifest declares.** The registry is keyed by `(ref, version)` and the manifest carries the same pair, so the two could disagree — silently, which is what makes it worth a row: `lower_steps` builds `StepIR` from the *manifest* identity while the wiring's canonical links and `on_fail: fail` rules are keyed by the *wiring* identity, so a mismatch drops those without a word. Checked at construction, the one moment a frozen compile input can be checked once for every later reader — the same argument that makes collision an error in the transform registry (S-0021/D-6). The check found an existing disagreement in the test corpus on its first run.

- Paths: `src/bloomery/steps/registry.py` `tests/unit/test_steps/test_manifest_and_registry.py`

### S-0035/D-3 — `ASSUMED` (Public surface and stability policy)

**`assert_step_contract` is promoted to `bloomery.steps.__all__`** and the generated wrapper's import rewritten to the shallow path. The module path was de-facto public API — imported by bloomery's own artifacts shipped into consumer repositories — with no declaration and no test protecting it. `bloomery.steps.contract` keeps working; this adds a supported path rather than removing an unsupported one. A golden assertion pins the emitted import line.

- Paths: `tests/unit/test_steps/test_emission.py`

### S-0041/D-7 — `ASSUMED` (Deterministic union merge)

A `_source` system column carries provenance. It is load-bearing rather than diagnostic: the collision audit reports which sources collided, and without it the report is unactionable on a multi-source entity.

- Paths: `pages/docs/reference/stability.md` `src/bloomery/emit/lower/silver.py` `src/bloomery/ir/nodes.py` `src/bloomery/spec/common.py` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_steps/test_lowering.py`

### S-0041/D-21 — `LOCKED` (Deterministic union merge)

**A merged entity may not mix a mapped source with a step-produced output**, refused explicitly rather than left to fail somewhere downstream. §8 already puts it out of scope; this is the refusal that makes the scope real, since a step output entity carries `produced_by` and no mapping at all, and the union has nothing to order it by.

- Paths: `src/bloomery/resolve/steps.py` `tests/unit/test_steps/test_lowering.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0043/D-10 — `LOCKED` (The dbt singular-test surface)

**The audit envelope separates from the audit body** (§5.3). `emit/steps.py` is target-neutral by position and not by content: its `_AUDIT` template bakes SQLMesh's `AUDIT (name …);` header in, so `quality_audits` and `consistency_audits` hand shared callers a SQLMesh artifact. A producer instead returns a *named body* — rendered SELECT, name, disposition — and each target wraps it. The alternative, a second template beside the first, gives one audit body two spellings maintained in parallel, which is the divergence the shared lowering exists to prevent. Consequence: this is the only structural change here, and it is what makes the remaining work a template and a path rather than five separate liftings. It also carries the relation in as a parameter, so `@this_model` stops being a literal the dbt side would rewrite by substitution.

- Paths: `src/bloomery/emit/base.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/steps.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_steps/test_dbt_and_cube_emission.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0053/D-2 — `LOCKED` (Measure semantic types and additivity algebra)

**A ratio is stored as its operands, not as a materialized quotient.** `SUM(num)/SUM(den)` and `AVG(ratio)` differ, the second is what a numeric-looking column invites, and the difference is a plausible wrong number. This is also S-0055's precondition — a derived metric spanning two branches cannot be reconstructed after the operands are gone — so reversing it later strands that document.

- Paths: `src/bloomery/emit/lower/rollups.py` `src/bloomery/errors.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/mart.py` `tests/fixtures/semantic_corpus/002-average-of-averages/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/002-average-of-averages/problem.md` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/problem.md` `tests/fixtures/semantic_corpus/008-ratio-rollup/bloomery/declared/metrics.yaml` `tests/fixtures/semantic_corpus/008-ratio-rollup/bloomery/naive/metrics.yaml` `tests/fixtures/semantic_corpus/008-ratio-rollup/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/008-ratio-rollup/problem.md` `tests/fixtures/semantic_corpus/012-rollup-recounts-identities/problem.md` `tests/unit/test_emit/test_rollups.py` `tests/unit/test_guardrails/test_additivity.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_steps/test_step_canonicals.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0059/D-10 — `LOCKED` (Loose ends inside shipped subsystems)

`on_fail: quarantine` on a step output is **refused permanently**, and the message names both blockers: no ingestion-metadata key for the reject table, and no `quarantine:` retention surface in a `steps:` wiring. Not "pending".

- Paths: `src/bloomery/resolve/steps.py` `tests/unit/test_steps/test_lowering.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0059/D-11 — `ASSUMED` (Loose ends inside shipped subsystems)

A `sql_model` output with no `flag` rule stays byte-identical — the flags columns are conditional on the rule, not on the tier. Accepts an asymmetry with mapped entities in exchange for leaving every existing step golden alone.

- Paths: `src/bloomery/ir/nodes.py` `tests/unit/test_steps/test_lowering.py`

<!-- /torve:managed -->
