<!-- torve:managed src/bloomery/emit — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/emit/`

### S-0002/D-7 — `ASSUMED` (Multi-project composition) — implementation: partial

Two composing projects must share a naming policy; whether a mismatch is a refusal depends on the upstream IR recording the policy it was compiled under

- Paths: `src/bloomery/naming.py` `src/bloomery/emit/base.py`
- Consequence: Without a shared policy the downstream names relations the upstream never created, and the failure surfaces in the warehouse rather than in the compile — which is the worst place for it

### S-0011/D-6 — `ASSUMED` (Retrieval semantics) — implementation: none

The retrieval manifest is emitted by a target of its own, not alongside another target's artifacts

- Paths: `src/bloomery/compile.py` `src/bloomery/emit/**`
- Consequence: A project's retrieval contract is independent of which analytical framework it compiles for, at the cost of a target enum member that names an artifact rather than a consumer

### S-0011/D-7 — `ASSUMED` (Retrieval semantics) — implementation: none

The manifest inlines each profile's space fully rather than referencing it by name

- Paths: `src/bloomery/emit/**`
- Consequence: The manifest is larger and repeats a space shared by several profiles, and in exchange it is readable by a consumer that has no access to the spec tree

### S-0011/D-10 — `LOCKED` (Retrieval semantics) — implementation: none

A vendor-oriented vector emitter is `register_emitter`, out of tree, and stays there until it has an artifact contract someone has run; no vector-database member of the target enum

- Paths: `src/bloomery/compile.py` `src/bloomery/emit/__init__.py`
- Consequence: The capability is available to anyone who wants it without core carrying a vendor's name or its compatibility promise
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0020/D-5 — `ASSUMED` (Intermediate representation and determinism contract)

Floats are banned in IR and emission; `Decimal`/int only.

- Paths: `src/bloomery/cli/serialize.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/steps.py` `src/bloomery/ir/fingerprint.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/request.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/common.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `src/bloomery/steps/manifest.py` `src/bloomery/steps/splice.py` `src/bloomery/transforms/_builtins.py` `src/bloomery/typing/types.py` `tests/execution/test_as_of_join.py` `tests/execution/test_currency_convert.py` `tests/execution/test_fanout_trap.py` `tests/execution/test_marts.py` `tests/execution/test_period_over_period.py` `tests/execution/test_rollup.py` `tests/fixtures/semantic_corpus/002-average-of-averages/naive.sql` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/golden/schema/marts.json` `tests/support/planning.py` `tests/support/semantic_corpus.py` `tests/unit/test_cli.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_planner/test_request.py` `tests/unit/test_quality/test_edges.py` `tests/unit/test_spec/test_metrics.py` `tests/unit/test_spec/test_quality.py` `tests/unit/test_steps/test_lowering.py` `tests/unit/test_steps/test_manifest_and_registry.py` `tests/unit/test_typing/test_types.py`

### S-0025/D-2 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Emitters produce file-shaped text artifacts as data (settles open question #1). No filesystem writes, no live-context registration in core — callers build that on top.

- Paths: `src/bloomery/emit/base.py` `src/bloomery/emit/steps.py` `tests/golden/test_sqlmesh_duckdb.py` `tests/support/execution.py`

### S-0025/D-4 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

SQL rendering: SQLGlot AST → `DialectPort.render`; Jinja only ever sees pre-rendered strings (envelope templating).

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/emit/steps.py` `tests/property/test_compile_properties.py` `tests/unit/test_steps/test_dbt_and_cube_emission.py`

### S-0025/D-8 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Emitter/dialect registries mirror the transform registry: immutable defaults + explicit overlay, collision is an error, iteration sorted (S-0021/D-6).

- Paths: `src/bloomery/dialects/__init__.py` `src/bloomery/emit/__init__.py` `src/bloomery/runtime/sql_client.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_emit/test_base.py`

### S-0025/D-9 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Every artifact carries a header comment with the project fingerprint — applied-vs-spec drift detection downstream.

- Paths: `src/bloomery/emit/base.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/emit/sqlmesh/__init__.py`

### S-0025/D-10 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

(Amended for `_bloomery-changes.md` D6) `TargetCapabilities` is a `frozenset[Feature]` over a closed `Feature` StrEnum — membership-checked, sorted at any output-reaching iteration. The native planner (S-0028) is a fourth port sharing this vocabulary; its lack of `QUERY_TIME_JOIN`/`MULTI_FACT` is the fan-out-impossibility property, documented as a feature.

- Paths: `src/bloomery/emit/base.py`

### S-0033/D-89 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **Mart-level checks are assertions, not quality rules. §10's open question is settled by the disposition model.** §8 deferred them as "blurs into reconciliation" and §10 asked "reconcile-shaped or new surface?" — the answer is neither, and what decides it is not taste. §5.9 draws the boundary at what a verdict *does*: a quality rule disposes of a **row**. A mart row is derived — no `_source_row_id`, no bronze payload, no reject table, no replay — so there is nothing to quarantine, nothing to repair, and nothing to bring back; and a `reconcile` compares *two sides*, which "no month has zero revenue" is not. What is left is D4's other half, "alert me", so `assert:` on a mart declares `{measure, agg, by, min/max, on_fail}` and lowers to an audit the mart model names. `quarantine` and `repair` are absent from its `on_fail` rather than lowered to something weaker, so an author who wanted routing learns it at the surface instead of from a mart that silently only alerts; `fail`/`flag` map to blocking/non-blocking exactly as `reconcile.on_fail` does (D38). The aggregate vocabulary is deliberately the *same tuple* the reconcile grammar uses — both compute one number over a column so a human can be told it is wrong, and two lists that mean the same thing drift. Bounds ride in `params` as text through the D57 carrier, for the same reason. **Resolution is against the flattened column set**, not the base entity's: `ordered_month` exists only because a `date:` step made it, and it is precisely the column §10's example groups by. **The body** is `SELECT <by…>, <agg>(<measure>) FROM @this_model [GROUP BY <by…>] HAVING <bound comparison>` — the value beside the group, because a failure a human must open the warehouse to understand gets ignored. A bare `HAVING` with no `GROUP BY` is the whole-mart form; both shapes were executed on DuckDB, postgres 16 and `trinodb/trino:483` rather than read out of three manuals, and all three agree. **What it cannot see, stated rather than implied:** D19 reaches the mart, so every aggregate but `count` is NULL over an empty group and the assertion stays silent — which is also why an assertion cannot notice a month that is *entirely missing*: no row means no group at all. `count` is the exception and is the one shape that catches an empty mart. Closing the missing-period case needs a join against the date spine, a coverage check with its own dependency, and it is named here rather than half-built. **dbt refuses a project carrying one**, sharing `refuse_steps`' message shape (**amended by D94**: this row said "dbt and Cube", and the Cube half was already obsolete when it was written — S-0034/D-52 had split the blanket Cube refusal on the argument that Cube builds no relation for anything, and Cube compiles the *entire* quality surface, quarantine and reject tables included, without a murmur; refusing this one check would single it out): neither has the audit form, and compiling clean while the declared gate does not exist is the failure D83 caught in the dialect ports. **Cost recorded:** `MartIR` gains a field, and the canonical encoder covers each node's field *names and count*, so every fingerprint in the corpus moves — the churn §12 budgets, spent deliberately. The fixture carrying the demonstration is `quality_precedence` rather than `ecom_basic`, because an assertion makes a project uncompilable for two targets and `ecom_basic` is the fixture those targets' goldens are built on.

- Paths: `src/bloomery/emit/base.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/marts/flatten.py` `src/bloomery/spec/marts.py` `tests/execution/test_quality_precedence.py` `tests/fixtures/quality_precedence/marts.yaml` `tests/golden/schema/marts.json`

### S-0034/D-8 — `ASSUMED` (The step registry: referenced implementations)

Emission: `sql_macro` splices into the entity SELECT (one query); `sql_model` emits an ordinary model artifact from the registry body; `python_model` emits a generated SQLMesh Python-model `.py` artifact (S-0025/D-2 file-shaped) wrapping the impl + contract assertion. Step outputs are DAG entities with manifest grain; two steps writing one output is a compile error (settles Document 5 §11.5).

- Paths: `src/bloomery/emit/steps.py` `src/bloomery/resolve/steps.py` `tests/unit/test_steps/test_emission.py` `tests/unit/test_steps/test_lowering.py`

### S-0034/D-16 — `ASSUMED` (The step registry: referenced implementations)

Multi-output emission resolved — **supersedes the draft §10 entry and its execute-exactly-once constraint** (recorded honestly: that constraint is dropped, not satisfied): each declared output gets its own generated wrapper model, each executing the step and returning its own output; safe **for correctly declared steps** — nondeterministic steps are compile-refused and seeded steps re-execute with the same recorded seed (pure/seeded ⇒ identical results); residual risk recorded: a *misdeclared* step slips the compile check and, under N executions, can produce disagreeing sibling outputs within one run (behavioral gates catch run-to-run, not intra-run, divergence) — accepted for v1, with a cross-output consistency audit named as the demand-gated mitigation. `assert_step_contract` runs in every wrapper against **all** declared outputs, catching partial-output lies wherever the run starts. The N-executions-for-N-outputs cost is documented; a single-execution staging optimization is a demand-gated, named escape hatch — not built.

- Paths: `src/bloomery/emit/steps.py` `src/bloomery/resolve/steps.py` `src/bloomery/steps/manifest.py` `tests/execution/test_step_consistency.py` `tests/golden/test_sqlmesh_duckdb.py` `tests/unit/test_steps/test_emission.py`

### S-0034/D-52 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-10)* **D31's blanket refusal was one sentence covering two different targets, and it is right about neither in full.** D31 refused steps on dbt and Cube because "their output relations would simply be missing" — checked per target, that argument splits. **Cube builds nothing.** It emits cubes and views over marts, and no silver model, no reject table, no replay statement and no audit for *anything*: the `dirty_corpus` fixture — twelve quality-carrying entities, twelve reject models, a conservation audit apiece — compiles to two files on Cube and always has, refusing none of it. So "the relation would be missing" was never a reason to refuse a step *here*; it is equally true of every silver entity, and singling steps out made this emitter refuse one build-side declaration among the many it already leaves to whoever maintains the tables. The refusal is removed, and its docstring now says what the contract actually is: Cube consumes tables SQLMesh maintains, and is deliberately silent about how. (The mart-assertion refusal added the day before, S-0033/D-89, is removed from Cube for the same reason and stays on dbt.) **dbt builds**, so a step must emit or refuse, and the answer is per tier. Tier 1 needs nothing: the splice happens at lowering, so a macro is already inside its consuming model on every target — which means Tier 1 worked on dbt throughout and D31 never claimed otherwise only because a macro is referenced inline rather than wired in `steps:`. Tier 2 **emits**: the body is already canonicalized and parameter-substituted on `StepIR`, so dbt wraps the same SELECT SQLMesh does in its own envelope — asserted as byte equality between the two targets rather than as a claim, since one SELECT meaning two things is exactly the drift the shared lowering exists to prevent. Tier 3 stays refused, on a concrete reason rather than a blanket one: dbt *has* Python models, but only on Snowflake, BigQuery and Databricks, and none of bloomery's three dialects is one of them, so the wrapper would have no adapter to execute it. **Step audits are refused on dbt** — a consistency audit (D40) is a join between sibling outputs and an `on_fail: fail` body (D39) is a whole query, while dbt's schema tests are per-column or per-model predicates; `_entity_tests` already refuses an audit kind on exactly this ground. The refusal is decided by *building* the audits rather than by the presence of a step, so a single-output Tier 2 step with no `fail` rules keeps the tier instead of losing it to a reason that does not apply to it. **One trap, found and closed:** a step output is an entity in the DAG (D36) whose lowered `expr` is the column referring to itself, so removing the refusal without skipping `produced_by` entities would have had dbt emit an ordinary entity model beside the step's — a model selecting from the relation it defines, and two models writing one relation. SQLMesh already skipped them; dbt now does too. **Not verified, stated:** that dbt *parses* the emitted model is S-0026's outstanding `dbt parse` tier, not something this row claims. What is verified is that the SELECT is byte-identical to SQLMesh's and that the envelope is the one the dbt goldens already lock.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/steps.py` `tests/e2e/test_dbt_parse.py` `tests/golden/test_cube.py` `tests/unit/test_marts/test_asserts.py` `tests/unit/test_steps/test_dbt_and_cube_emission.py`

### S-0043/D-5 — `LOCKED` (The dbt singular-test surface)

**The model reference goes through `_reference_map`, never string formatting.** It is what makes a singular test a DAG participant rather than a query that happens to name a table, and it is already built for exactly this shape. Consequence: a singular test is ordered against its model by dbt, which is what makes "blocking" mean anything at all under D2.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/emit/steps.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0043/D-10 — `LOCKED` (The dbt singular-test surface)

**The audit envelope separates from the audit body** (§5.3). `emit/steps.py` is target-neutral by position and not by content: its `_AUDIT` template bakes SQLMesh's `AUDIT (name …);` header in, so `quality_audits` and `consistency_audits` hand shared callers a SQLMesh artifact. A producer instead returns a *named body* — rendered SELECT, name, disposition — and each target wraps it. The alternative, a second template beside the first, gives one audit body two spellings maintained in parallel, which is the divergence the shared lowering exists to prevent. Consequence: this is the only structural change here, and it is what makes the remaining work a template and a path rather than five separate liftings. It also carries the relation in as a parameter, so `@this_model` stops being a literal the dbt side would rewrite by substitution.

- Paths: `src/bloomery/emit/base.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/steps.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_steps/test_dbt_and_cube_emission.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

## Invariants holding over `src/bloomery/emit/`

- **S-0002/I-1**: A project carrying neither an exports nor an imports document compiles byte-identically to what it compiled before composition existed; the golden corpus is that test, and only a deliberate IR version bump may move a fingerprint in it
  - Paths: `tests/golden/**` `src/bloomery/emit/**`
  - Check: `uv run pytest tests/golden -q`

<!-- /torve:managed -->
