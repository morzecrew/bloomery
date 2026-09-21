<!-- torve:managed tests/e2e — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/e2e/`

### S-0003/D-3 — `LOCKED` (Replay on a historical entity) — implementation: partial

The acceptance for this design is an as-of join finding the recovered row, never a row being present in the entity relation

- Paths: `tests/e2e/test_dbt_parse.py` `tests/execution/test_replay_to_bronze.py`
- Consequence: Present-and-invisible is the exact failure this design exists to remove, and a row-count assertion cannot tell the two apart — it passes against the defect
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0025/D-18 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

*(2026-08-11)* **The dbt target defines the generic test it declares; the emitted project depends on no package.** D16's dbt half had to name *some* vehicle for `min`/`max`/`regex`/`reconcile`, and the only one dbt offers is `dbt_utils.expression_is_true` — which D16 itself noted "is a package, not core" without following the consequence. The consequence is that bloomery emitted a project **declaring a test it did not define**: `dbt compile` stops at ``'dbt_utils' is undefined. … install package dependencies with "dbt deps"``, for every project carrying one of those four clauses. Two fixes were available — emit a `packages.yml` pinning `dbt-labs/dbt_utils`, or define the test — and the second wins on the thing this compiler is for: artifacts are a pure function of the specs (S-0020), and a `packages.yml` makes the output complete only after a *network fetch* the compiler is forbidden from performing and the consumer may not be able to perform at all. So `macros/bloomery_expression_is_true.sql` is emitted, iff `schema.yml` declares the test. Three things follow. **It is `ArtifactKind.AUDIT`, not `CONFIG`** — it is the custom audit *body* for this target, the exact counterpart of the `audits/<name>.sql` file SQLMesh gets for the same kinds and from the same `audit_predicate`, which makes D16's "one function, two forms" symmetry structural rather than incidental. **The body is `dbt_utils`' `default__test_expression_is_true` minus the `column_name` branch bloomery never takes**, so the replaced semantics are preserved exactly — including that a NULL expression *passes*, `NOT NULL` being NULL and selecting no row, which is S-0033/D-19's Kleene discipline arrived at from dbt's side. **The emission condition reads the emitted schema rather than re-deriving the entity filter**, so the project can neither declare the test without the macro nor carry it unused, and a test pins both directions.

- Paths: `src/bloomery/emit/dbt/__init__.py` `tests/e2e/test_dbt_parse.py` `tests/property/test_compile_properties.py` `tests/unit/test_emit/test_dbt.py`

### S-0025/D-20 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

*(2026-08-11)* **The dbt target emits a real DAG, and keeps the naming policy owning namespaces. S-0026/D-22 is closed — with both of its candidates, not one.** D22 found `dbt build` could not pass: models named their inputs literally (`FROM silver.order_item`), so dbt had no edges to order them by *and* materialized each into the profile's target schema while the `FROM` clause said `silver`. It offered two fixes with an "or" between them, and the "or" was the mistake — **neither is sufficient alone, and each repairs the other's cost.** `+schema` config alone places the relations and leaves ordering absent, so a gold model still races its silver input. `ref()`/`source()` alone orders the DAG but resolves names through dbt's schema config, which is the objection D22 raised: the naming port stops owning the namespace. Together: `ref()` for every relation bloomery emits and `source()` for bronze, `+schema: <ns>` per model directory, and a `generate_schema_name` override returning the configured schema **verbatim** — because dbt's default returns `<target.schema>_<custom>`, which would put models in `main_silver` while `sources.yml` (which never passes through that macro) still said `bronze`, honouring the policy in half the project. **How it is emitted.** Shared lowering is untouched: both targets build inputs as `exp.table_(relation, db=namespace)`, and the dbt emitter rewrites *table nodes only*, mapping `(namespace, relation)` to a reference. A namespace-less table is never rewritten, which is what keeps a CTE reference from being mistaken for a model; a table the map does not know is left literal rather than guessed at, because inventing a `ref()` for a relation bloomery did not write would name a model dbt cannot find. An SCD2 entity resolves to its **snapshot**, the only thing this target builds for it. **The cost, stated.** D5's port-abstraction proof compared the two targets' SELECTs byte for byte and can no longer: the `FROM` clauses differ by construction. It is restated, not weakened — resolve the references, drop namespaces, and the SQL is identical on every projection, join, cast and dialect quirk, so the entire difference between the targets is one documented substitution. The namespaces the comparison erases are asserted separately, against the `+schema` config and the override.

- Paths: `src/bloomery/emit/dbt/__init__.py` `tests/e2e/test_dbt_parse.py` `tests/property/test_compile_properties.py` `tests/support/compiling.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_quality_mart.py`

### S-0026/D-22 — `ASSUMED` (Testing strategy and fixture corpus)

*(2026-08-10)* **`dbt parse` is built, and building it found that `dbt build` cannot pass.** §5.2 names dbt's tier-6 cell in three words, and the tier now runs `dbt parse` over every fixture the dbt target compiles plus a Tier 2 step project — closing the claim S-0034/D-52 explicitly left open, that the emitted step model is a file dbt accepts. It carries its own control: one model's `config()` is deliberately malformed and dbt must refuse it, so the nine passes above it are not a parser that accepts anything. **The finding.** `dbt build` on the same project fails, and not because of the tier: bloomery's dbt models reference their inputs by **literal relation name** (`FROM silver.order_item`) rather than through `{{ ref(...) }}` or `{{ source(...) }}`. So dbt has no dependency edges between bloomery's models — it cannot order them — and it materializes each into the profile's target schema while the `FROM` clause names `silver`. Both halves have to be true for a build to work, and neither is. Two candidate fixes, **neither built**, because this is S-0025's decision about how deep the dbt target goes rather than a testing-tier patch: rewrite silver/gold references to `ref()` and bronze to `source()` (a real DAG, but `ref()` resolves through dbt's own schema config, so the naming policy stops owning the namespace); or emit per-directory `+schema` config in `dbt_project.yml` (relations line up, ordering still absent). Recorded here because the limitation was **unwritten anywhere** until this tier was built — S-0025 calls dbt "the compatibility target, minimal but honest", and this is the part that was not written down.

- Paths: `src/bloomery/emit/dbt/__init__.py` `tests/e2e/test_dbt_parse.py`

### S-0033/D-18 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Disposition precedence for a row failing multiple rules — severity order `fail > quarantine > flag`: any failing `fail` rule stops the run (blocking audit); else any failing `quarantine` rule diverts the row, with **all** failed rule names recorded in the reject's `failed_rules` (flag-level failures included); else flags accumulate in `_quality_flags`. Deterministic for every combination — no compile-time rejection of rule/disposition combinations needed.

- Paths: `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/quality/catalogue.py` `src/bloomery/quality/predicates.py` `tests/e2e/test_sqlmesh_replan.py` `tests/execution/test_quality_precedence.py` `tests/fixtures/quality_precedence/entity_model.yaml` `tests/support/precedence.py` `tests/unit/test_quality/test_predicates.py`

### S-0033/D-21 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Ingestion metadata contract: entities using `quarantine` or `dedupe` require bronze `_load_id`, `_ingested_at`, `_source_row_id` (a stable per-source-row identity supplied by the ingestion layer, **NOT NULL and unique per source row** — data properties no compiler can check, so the lowering emits a generated **blocking audit** on the metadata columns: a null or duplicated `_source_row_id` stops the run); column absence is the new compile error `IngestionMetadataMissing` (`GuardrailError` leaf, `errors.py` per S-0019/D-3). `reject_id` = sha256 over the length-prefixed utf-8 **pair** (`source_relation`, `_source_row_id`) — canonical serialization per the S-0020 canon-bytes doctrine. This supersedes the triple this row first carried (this round's own earlier decision): `_load_id` is removed from the identity and becomes an attribute (the latest observing load) — re-deliveries of the same source row across loads must land on the **same** reject row (that is what `first_seen`/`last_seen` track); a per-load identity would mint a new row per retry and violate replay idempotence. A re-delivery updates `last_seen`/`_load_id`/`failed_rules` on the existing row.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/quality.py` `src/bloomery/quality/catalogue.py` `src/bloomery/quality/dedupe.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/transforms/_builtins.py` `tests/e2e/test_dbt_parse.py` `tests/e2e/test_sqlmesh_project.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_dedupe_and_audits.py` `tests/execution/test_merged_cleaning.py` `tests/execution/test_zoneless_utc.py` `tests/fixtures/dirty/README.md` `tests/fixtures/semi_additive_inventory/mapping.yaml` `tests/support/execution.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_trino.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_entity.py`

### S-0033/D-90 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **Cross-entity checks are `coverage:` on a relationship, and the audit hangs off the *dependent* side. §10's last open question is settled.** §10 guessed "probably reconcile-style"; it is not, and the reason is structural rather than stylistic. A `reconcile` compares two **values** and alerts beyond a tolerance — there is no right-hand value on the referenced entity to compare against, and `right: 1` is neither a shape the closed grammar admits nor one it should grow. This asserts **existence**: every row of a relationship's referenced entity has at least `min` rows referencing it. That makes it the mirror of `referential`, which asks whether every *dependent* row has a parent, and both read the same two relations through the same `via` pairs — which is why it is declared on the **relationship** rather than on either entity. **Why an audit, when a disposition would have been meaningful.** Unlike a mart row (D89), a childless customer is a real silver row with a source identity, a reject table and a replay path, so routing it is not nonsense. It is still an audit, for a reason that only shows up in the DAG: routing would need the *referenced* entity's model to read the *dependent* one, while the dependent one already reads the referenced one through this very relationship — so the pair that most wants this check (an FK one way, a coverage check the other) is exactly the pair whose models would form a cycle. Attaching the audit to the dependent side instead adds **no edge the relationship did not already imply**. `on_fail` is `fail`/`flag` only; `quarantine` and `repair` are absent from the surface rather than lowered to something weaker. **Two emission details that are each a trap closed.** The body counts a *dependent* column, never `COUNT(*)`: a `LEFT JOIN` still produces one output row for an unmatched left row, so `COUNT(*)` answers 1 for a customer with no orders at all and the check would pass on precisely the rows it exists to find. And the dependent side is `@this_model` rather than a named relation — the macro is the one reference SQLMesh rewrites inside an AUDIT body (D29), so naming the relation resolved to the virtual layer *and* put the model into its own `depends_on`, which is how the first cut emitted it. The referenced side is a sibling and is declared in `depends_on`, the trap D40 closed for step audits. Verified by a real SQLMesh plan on a fixture added to the e2e tier for it: the comment above `step_resolution` there argues that nothing else loads SQLMesh and that the gap hid three defects in a row, and this is the same shape — an audit body joining a sibling, with a `depends_on` that exists only because of the audit. dbt refuses the project (its tests are predicates, with no grouped cross-relation form); Cube is not asked, because it builds nothing (S-0034/D-52). **Cost:** `ProjectIR` gains a field, so every fingerprint moves. **Not closed:** the check counts rows that *reached* silver, so a referenced row quarantined by its own rules reads as absent — right for "has an order", wrong for a check somebody phrases as "exists", and named here rather than discovered.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/guardrails/quality.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/lower.py` `src/bloomery/spec/entity.py` `tests/e2e/test_sqlmesh_replan.py` `tests/fixtures/coverage_check/entity_model.yaml` `tests/fixtures/dirty_corpus/entity_model.yaml` `tests/unit/test_fixtures.py`

### S-0034/D-13 — `ASSUMED` (The step registry: referenced implementations)

Implementation binding: `StepRegistry` gains `sql_bodies: Mapping[tuple[str, int], str]` (`sql_model` bodies, parsed at compile like `macro_bodies`); `StepManifest` gains `entrypoint: str` (`"package.module:function"`) for `python_model`, and the generated wrapper imports it at **run time**. The no-dynamic-loading rule is scoped to compile time — bloomery never imports or executes step code while compiling (manifests and SQL text only); runtime import of platform-owned code by the generated model is the normal SQLMesh execution path, and registry build (caller-side) verifies the entrypoint resolves.

- Paths: `src/bloomery/spec/mapping.py` `src/bloomery/steps/manifest.py` `tests/e2e/test_sqlmesh_replan.py` `tests/golden/schema/mapping.json`

### S-0034/D-42 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-08, M13 re-audit)* **The consistency audit was emitted and never ran, and the wrapper never loaded at all.** Two defects in one blind spot, both invisible to every test written for them. (a) SQLMesh loads a bare `AUDIT` as a **model** audit, executed only where a model's `audits` list names it — and nothing named it, so D40's blocking check was inert. The test that "proved" it extracted the SELECT and ran it straight against DuckDB, so SQLMesh was never in the loop. (b) Loading the project properly then showed the `python_model` wrapper does not load *at all*: SQLMesh serializes the module globals a model function references into a fresh environment, and a global holding a `Decimal` parameter fails to reconstruct there — `name 'Decimal' is not defined`, before anything runs. The wrapper had only ever been `ast.parse`d. Audits are now attached to the child output's model, and the wrapper binds every name inside its function so there is nothing to serialize. The lesson is the general one: a generated artifact is only verified by the tool that will consume it, and parsing it yourself proves the grammar, not the contract.

- Paths: `tests/e2e/test_sqlmesh_replan.py`

### S-0034/D-44 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-09, M13 fourth audit)* **The consistency audit read its sibling through the naming policy, which this codebase had already learned not to do.** D43 routed both sides of the audit through `ctx.naming` to fix a real bug — and reintroduced the failure `lowering.py` states as doctrine (*"the audited entity is addressed through THIS_MODEL, never through the naming policy"*) and S-0033/D-61 redesigned the conservation audit to avoid. SQLMesh substitutes physical snapshot tables only for relations in the audited model's `depends_on`, and sibling wrappers had no edge between them, so the audit resolved `silver.customer` to a virtual-layer view: **the plan failed on correct data** on a first deploy, gave a **false positive** on a staged one (comparing this plan's child against the *promoted* parent), and a **false negative** on the orphan it exists to catch. Fixed by declaring the referenced siblings — and the model's own reads, since `depends_on` replaces inference rather than extending it. Because that makes a reference a real DAG edge, mutual references are now refused at the manifest as a cycle.

- Paths: `tests/e2e/test_sqlmesh_replan.py`

### S-0034/D-52 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-10)* **D31's blanket refusal was one sentence covering two different targets, and it is right about neither in full.** D31 refused steps on dbt and Cube because "their output relations would simply be missing" — checked per target, that argument splits. **Cube builds nothing.** It emits cubes and views over marts, and no silver model, no reject table, no replay statement and no audit for *anything*: the `dirty_corpus` fixture — twelve quality-carrying entities, twelve reject models, a conservation audit apiece — compiles to two files on Cube and always has, refusing none of it. So "the relation would be missing" was never a reason to refuse a step *here*; it is equally true of every silver entity, and singling steps out made this emitter refuse one build-side declaration among the many it already leaves to whoever maintains the tables. The refusal is removed, and its docstring now says what the contract actually is: Cube consumes tables SQLMesh maintains, and is deliberately silent about how. (The mart-assertion refusal added the day before, S-0033/D-89, is removed from Cube for the same reason and stays on dbt.) **dbt builds**, so a step must emit or refuse, and the answer is per tier. Tier 1 needs nothing: the splice happens at lowering, so a macro is already inside its consuming model on every target — which means Tier 1 worked on dbt throughout and D31 never claimed otherwise only because a macro is referenced inline rather than wired in `steps:`. Tier 2 **emits**: the body is already canonicalized and parameter-substituted on `StepIR`, so dbt wraps the same SELECT SQLMesh does in its own envelope — asserted as byte equality between the two targets rather than as a claim, since one SELECT meaning two things is exactly the drift the shared lowering exists to prevent. Tier 3 stays refused, on a concrete reason rather than a blanket one: dbt *has* Python models, but only on Snowflake, BigQuery and Databricks, and none of bloomery's three dialects is one of them, so the wrapper would have no adapter to execute it. **Step audits are refused on dbt** — a consistency audit (D40) is a join between sibling outputs and an `on_fail: fail` body (D39) is a whole query, while dbt's schema tests are per-column or per-model predicates; `_entity_tests` already refuses an audit kind on exactly this ground. The refusal is decided by *building* the audits rather than by the presence of a step, so a single-output Tier 2 step with no `fail` rules keeps the tier instead of losing it to a reason that does not apply to it. **One trap, found and closed:** a step output is an entity in the DAG (D36) whose lowered `expr` is the column referring to itself, so removing the refusal without skipping `produced_by` entities would have had dbt emit an ordinary entity model beside the step's — a model selecting from the relation it defines, and two models writing one relation. SQLMesh already skipped them; dbt now does too. **Not verified, stated:** that dbt *parses* the emitted model is S-0026's outstanding `dbt parse` tier, not something this row claims. What is verified is that the SELECT is byte-identical to SQLMesh's and that the envelope is the one the dbt goldens already lock.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/steps.py` `tests/e2e/test_dbt_parse.py` `tests/golden/test_cube.py` `tests/unit/test_marts/test_asserts.py` `tests/unit/test_steps/test_dbt_and_cube_emission.py`

### S-0040/D-7 — `ASSUMED` (Temporal joins: SCD2 flattening and currency conversion)

A `type2` entity's validity-interval column names belong on `EntityIR`. Today each target names them privately, which is the mechanical reason no predicate can be emitted; naming them in the IR is what makes the two targets agree.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/ir/nodes.py` `tests/e2e/test_dbt_parse.py` `tests/unit/test_emit/test_dbt.py`

### S-0041/D-5 — `LOCKED` (Deterministic union merge)

A key appearing in more than one source is refused by a generated **blocking** audit (`on_fail: fail`), not configurable to `flag` or `quarantine`. Overlap is either duplication or a shared key space by accident, and both are refusals. The message names the identity-resolution step as the escape hatch. Consequence: bloomery's union is for disjoint key sets, permanently — matching stays a step, and S-0038 is not reopened.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `tests/e2e/test_dbt_parse.py` `tests/e2e/test_sqlmesh_replan.py` `tests/execution/test_merged_cleaning.py` `tests/golden/test_sqlmesh_duckdb.py` `tests/unit/test_examples.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-30 — `ASSUMED` (Deterministic union merge)

**Departs from D20 — the dbt target refuses a merged entity in P1**. D20's claim about the *union* holds and shipped: the `UNION ALL` is the same shared SELECT both targets render, and the dbt emitter does emit one `source()` per mapping. What D20 did not account for is that the merge's correctness condition is a **blocking audit** (D5), and this emitter has no artifact for one: its whole test surface is `schema.yml` entries covering `not_null`, `accepted_values` and a single expression test, and it emits no singular-test path at all. A generated `GROUP BY <key> HAVING COUNT(DISTINCT _source) > 1` is none of those. Emitting the union without it produces a model that compiles here, runs anywhere, and double-counts an entity in silence — the degradation S-0025/D-3 refuses. **S-0033/fixed-pipeline-order-and-lowering's target-coverage sentence deliberately was not stretched to cover this**: it authorizes dbt's partiality for the *quality* artifacts, and a rule an author chose to make blocking is not the same thing as the one check a feature cannot be correct without. Consequence: merged entities are SQLMesh-only until the dbt emitter grows a singular-test surface, which is its own change and not P2's. D20's row is left standing — what it predicted is the thing this has to be read against. *Added by execution 2026-08-16 — see logs/T-0004.md (V-002, attempt 1).*

- Paths: `tests/e2e/test_dbt_parse.py` `tests/unit/test_emit/test_dbt.py`

### S-0043/D-2 — `LOCKED` (The dbt singular-test surface)

**A `dbt build`-conditional block satisfies S-0041/D-5.** A dbt test does not run under `dbt run`, so the collision audit is blocking only under `dbt build`. Accepted because **every schema test this emitter already ships has the same property** — a `not_null` audit does not block `dbt run` either — and refusing the merge for a property shared by every existing dbt check would apply a standard exactly once. Consequence: the emitted project's operator contract states that bloomery's blocking audits on dbt are blocking under `dbt build`; that sentence is this RFC's cost and it is not optional.

- Paths: `tests/e2e/test_dbt_parse.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0043/D-3 — `LOCKED` (The dbt singular-test surface)

**`on_fail` maps to `severity`** — `fail` → `error` written explicitly, `flag` → `warn` — **and the operator contract carries two sentences, not one.** The mapping is exact; the *disposition* is not, because dbt lets the invocation choose the consequence in both directions. `dbt run` skips a `fail` audit (D2) and `--warn-error` promotes a `flag` one, so the contract states both or it misleads: a reader given only D2's sentence will believe `flag` is unconditionally non-blocking. This is the one place bloomery's three-value disposition model does not survive intact to a target — SQLMesh needs neither sentence, since there the artifact carries `blocking false` and no flag overrides it. Graded `LOCKED` with D2 because they are one fact about dbt seen from two sides, and separating them is how half of it gets dropped. Also corrects half of `_refuse_reconcile`'s stated argument (§3), recorded so the correction is not mistaken for a licence to lift D58.

- Paths: `src/bloomery/emit/dbt/__init__.py` `tests/e2e/test_dbt_parse.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0043/D-4 — `ASSUMED` (The dbt singular-test surface)

**Native schema tests stay preferred where dbt has an equivalent.** `not_null` and `enum` keep their builtin lowering; the singular test is the fallback, not the replacement. Rationale is reader-facing: a native test names its column in `dbt test` output and appears in `dbt docs`, and a hand-rolled query does neither. Graded `ASSUMED` because it is a readability claim, and D10 asks whoever builds this to check it against real output.

- Paths: `src/bloomery/emit/dbt/__init__.py` `tests/e2e/test_dbt_parse.py` `tests/unit/test_emit/test_quality_artifacts.py`

### S-0060/D-1 — `LOCKED` (dbt as a complete quality target)

The reject table preserves `first_seen` / `last_evaluated_at` **in its own SELECT**, by `LEFT JOIN` to `{{ this }}` and `COALESCE`, not by dbt's `merge_exclude_columns`. Column exclusion cannot express a `COALESCE`, so it would leave a null unhealed where SQLMesh heals it — a divergence in the column retention reads — and it requires a `merge` strategy dbt-postgres does not have and dbt-duckdb has only above a DuckDB floor. Locks the reject model to one scan of itself per run, in exchange for working on every adapter.

- Paths: `src/bloomery/emit/lower/silver.py` `tests/e2e/test_dbt_quality.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0060/D-2 — `LOCKED` (dbt as a complete quality target)

The incremental and first-run bodies are **two pre-rendered SELECTs** chosen by `{% if is_incremental() %}` in the envelope. Never one SELECT with Jinja spliced into it: S-0025/D-4's rule is that envelopes interpolate rendered strings, and a conditional inside a rendered string is a template no dialect port ever saw.

- Paths: `src/bloomery/emit/dbt/__init__.py` `tests/e2e/test_dbt_parse.py` `tests/property/test_compile_properties.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0060/D-3 — `LOCKED` (dbt as a complete quality target)

Replay is `macros/replay_<entity>.sql`, run by `dbt run-operation`. Not ergonomics: the statements name relations through `ref()`, which resolves only inside dbt's Jinja, so a bare `.sql` file would be runnable by neither dbt nor a SQL client. **The macro form is what is locked; how it names relations is not** — P1 measures `ref()` on the supported range's floor and ceiling, and §9's naming-policy fallback is the body if it is unavailable below the ceiling.

- Paths: `src/bloomery/emit/dbt/__init__.py` `tests/e2e/test_dbt_quality.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0060/D-5 — `LOCKED` (dbt as a complete quality target)

The dbt replay artifact keeps `ArtifactKind.REPLAY` despite living under `macros/`. The kind means "a statement the caller runs, not a relation the framework maintains", and a caller routing the artifact stream must be able to tell those apart without parsing a path.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/quality_mart.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `tests/e2e/test_dbt_parse.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0060/D-7 — `LOCKED` (dbt as a complete quality target)

The quality mart's dbt refusal is **deleted**, not narrowed, once D1 and D6 land: no surface it reads is then missing. Narrowing its predicate is the right change only if this RFC does not ship — the two are alternatives, not a sequence, and pursuing both would leave dead code behind.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/quality_mart.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `tests/e2e/test_dbt_parse.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0060/D-9 — `LOCKED` (dbt as a complete quality target)

`python_model` steps stay refused (S-0034/D-52), untouched by this RFC. Leaving one refusal standing is what keeps "dbt refuses this" a specific statement rather than a historical one.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/quality_mart.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `tests/e2e/test_dbt_parse.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0060/D-11 — `LOCKED` (dbt as a complete quality target)

The reject model names `incremental_strategy='delete+insert'`. Left to the adapter it is per-adapter and project-overridable, and `append` makes `unique_key` inert — every re-delivery becomes a new row, silently, because the `LEFT JOIN` still computes the right values and nothing reads them back. dbt-duckdb's default *is* `delete+insert` (measured), which is why this looked like a free choice and is not. The value is named here rather than delegated: `delete+insert` materializes the SELECT before deleting, so the join against `{{ this }}` reads the incumbent row, and it exists on every adapter — `merge` would be narrower with nothing left to buy once D1 moved the preservation out of the merge clause.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/quality_mart.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `tests/e2e/test_dbt_parse.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0060/D-12 — `ASSUMED` (dbt as a complete quality target)

Parity is proven by an equivalence leg — one spec set built on both targets over one DuckDB, reject tables compared row for row — not by per-artifact goldens alone. The two targets emit different bytes on purpose, so only the rows can carry the claim.

- Paths: `tests/e2e/test_dbt_quality.py`

### S-0060/D-13 — `ASSUMED` (dbt as a complete quality target)

A `--full-refresh` **loses resolved reject history**, and the contract says so rather than preventing it. The `{% else %}` branch sees only currently-quarantined rows; refusing to full-refresh would leave an operator unable to recover a broken relation, and SQLMesh has the same exposure under a restatement. Ships with a regression test that asserts the loss.

- Paths: `tests/e2e/test_dbt_quality.py`

### S-0060/D-14 — `LOCKED` (dbt as a complete quality target)

The replay macro wraps its three statements in an explicit `BEGIN`/`COMMIT`. `run_query` opens no transaction, and a failure between the entity `MERGE` and the reject stamps leaves a row both admitted and unresolved — double-counted in the quality mart and re-admitted on the next replay. SQLMesh's replay file states the same requirement in prose to a human; the macro has to state it to the engine.

- Paths: `src/bloomery/emit/dbt/__init__.py` `tests/e2e/test_dbt_quality.py` `tests/unit/test_emit/test_quality_artifacts.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0061/D-2 — `LOCKED` (The SQLMesh project file)

`model_defaults.start` is emitted, derived from `date_dimension.start_year`. Omitting it makes `sqlmesh plan` backfill every time-range model over a single day and report success (M4) — an artifact bloomery wrote, producing a plausible-but-wrong result. This row is the RFC.

- Paths: `tests/e2e/test_sqlmesh_project.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
