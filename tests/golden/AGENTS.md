<!-- torve:managed tests/golden — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/golden/`

### S-0025/D-2 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Emitters produce file-shaped text artifacts as data (settles open question #1). No filesystem writes, no live-context registration in core — callers build that on top.

- Paths: `src/bloomery/emit/base.py` `src/bloomery/emit/steps.py` `tests/golden/test_sqlmesh_duckdb.py` `tests/support/execution.py`

### S-0033/D-83 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **The reject table's two constructions are spelled by the dialect port, and Trino hosts it. D75 is closed — and Postgres turned out to be wrong in the same place, silently.** D75 recorded the two gaps and refused Trino at emit; the fix it named — a per-dialect hook rather than a shared AST — is built. `DialectPort` gains `text_sha256` and `json_object`, because a construction that differs per engine belongs to the port that knows the engine (S-0025/D-1), not to a lowering that is supposed to be dialect-neutral. Trino: `LOWER(TO_HEX(SHA256(TO_UTF8(…))))` and the standard keyword `JSON_OBJECT`. **The finding that was not in D75:** Postgres declared support for *both* features and has neither. Its `sha256` takes and returns `bytea`, so the plain spelling did not fail — it silently yielded bytes where every other engine yields a hex string, which would have made `reject_id` disagree across engines while looking like it worked; and it has no positional `json_object` at all (`function pg_catalog.json_object(unknown, integer, …) does not exist` — the SQL/JSON one arrived in 16 taking `KEY … VALUE` only, and the positional builder has always been `json_build_object`). D75's own sentence — "the one construction SQLGlot renders verbatim on every shipped dialect… holds for DuckDB and Postgres but not Trino" — was therefore half wrong, and it read as verified because the *other* half had been. It held only because Postgres never reached emission: D30 refuses a quality-carrying entity there for the unrelated `TRY_CAST` reason, so the reject table was never built for it. Postgres now has correct spellings that stay unreachable until D30 lifts, asserted at the port rather than through a compile so they cannot rot in the meantime. Verified by **executing the emitted model**, not the expressions: the full `__reject` SELECT runs on `trinodb/trino:483` and returns a `reject_id` byte-identical to the Python canon-bytes digest — cross-engine *agreement* being the property `reject_id` actually needs. The feature flags stay in the vocabulary: a fourth dialect may still lack either, and the refusal they drive is still the right answer for one that does.

- Paths: `src/bloomery/dialects/postgres.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/quality/reject.py` `tests/engines/test_merged_cleaning_engines.py` `tests/golden/test_sqlmesh_dialects.py` `tests/unit/test_emit/test_quality_artifacts.py`

### S-0034/D-16 — `ASSUMED` (The step registry: referenced implementations)

Multi-output emission resolved — **supersedes the draft §10 entry and its execute-exactly-once constraint** (recorded honestly: that constraint is dropped, not satisfied): each declared output gets its own generated wrapper model, each executing the step and returning its own output; safe **for correctly declared steps** — nondeterministic steps are compile-refused and seeded steps re-execute with the same recorded seed (pure/seeded ⇒ identical results); residual risk recorded: a *misdeclared* step slips the compile check and, under N executions, can produce disagreeing sibling outputs within one run (behavioral gates catch run-to-run, not intra-run, divergence) — accepted for v1, with a cross-output consistency audit named as the demand-gated mitigation. `assert_step_contract` runs in every wrapper against **all** declared outputs, catching partial-output lies wherever the run starts. The N-executions-for-N-outputs cost is documented; a single-execution staging optimization is a demand-gated, named escape hatch — not built.

- Paths: `src/bloomery/emit/steps.py` `src/bloomery/resolve/steps.py` `src/bloomery/steps/manifest.py` `tests/execution/test_step_consistency.py` `tests/golden/test_sqlmesh_duckdb.py` `tests/unit/test_steps/test_emission.py`

### S-0034/D-52 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-10)* **D31's blanket refusal was one sentence covering two different targets, and it is right about neither in full.** D31 refused steps on dbt and Cube because "their output relations would simply be missing" — checked per target, that argument splits. **Cube builds nothing.** It emits cubes and views over marts, and no silver model, no reject table, no replay statement and no audit for *anything*: the `dirty_corpus` fixture — twelve quality-carrying entities, twelve reject models, a conservation audit apiece — compiles to two files on Cube and always has, refusing none of it. So "the relation would be missing" was never a reason to refuse a step *here*; it is equally true of every silver entity, and singling steps out made this emitter refuse one build-side declaration among the many it already leaves to whoever maintains the tables. The refusal is removed, and its docstring now says what the contract actually is: Cube consumes tables SQLMesh maintains, and is deliberately silent about how. (The mart-assertion refusal added the day before, S-0033/D-89, is removed from Cube for the same reason and stays on dbt.) **dbt builds**, so a step must emit or refuse, and the answer is per tier. Tier 1 needs nothing: the splice happens at lowering, so a macro is already inside its consuming model on every target — which means Tier 1 worked on dbt throughout and D31 never claimed otherwise only because a macro is referenced inline rather than wired in `steps:`. Tier 2 **emits**: the body is already canonicalized and parameter-substituted on `StepIR`, so dbt wraps the same SELECT SQLMesh does in its own envelope — asserted as byte equality between the two targets rather than as a claim, since one SELECT meaning two things is exactly the drift the shared lowering exists to prevent. Tier 3 stays refused, on a concrete reason rather than a blanket one: dbt *has* Python models, but only on Snowflake, BigQuery and Databricks, and none of bloomery's three dialects is one of them, so the wrapper would have no adapter to execute it. **Step audits are refused on dbt** — a consistency audit (D40) is a join between sibling outputs and an `on_fail: fail` body (D39) is a whole query, while dbt's schema tests are per-column or per-model predicates; `_entity_tests` already refuses an audit kind on exactly this ground. The refusal is decided by *building* the audits rather than by the presence of a step, so a single-output Tier 2 step with no `fail` rules keeps the tier instead of losing it to a reason that does not apply to it. **One trap, found and closed:** a step output is an entity in the DAG (D36) whose lowered `expr` is the column referring to itself, so removing the refusal without skipping `produced_by` entities would have had dbt emit an ordinary entity model beside the step's — a model selecting from the relation it defines, and two models writing one relation. SQLMesh already skipped them; dbt now does too. **Not verified, stated:** that dbt *parses* the emitted model is S-0026's outstanding `dbt parse` tier, not something this row claims. What is verified is that the SELECT is byte-identical to SQLMesh's and that the envelope is the one the dbt goldens already lock.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/steps.py` `tests/e2e/test_dbt_parse.py` `tests/golden/test_cube.py` `tests/unit/test_marts/test_asserts.py` `tests/unit/test_steps/test_dbt_and_cube_emission.py`

### S-0037/D-2 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**Every closed set appears in the schema as an `enum`**, never a free string: transforms, quality rules, `Op`, `LogicalType`, `OnFail`, `Additivity`, document versions. This is the property constrained generation depends on — a proposer choosing from an enum cannot invent a transform, so the refusal that would catch the invention never fires. Unit-tested per set.

- Paths: `src/bloomery/schema.py` `tests/golden/test_spec_schemas.py` `tests/property/test_schema_agreement.py` `tests/unit/test_schema.py`

### S-0037/D-3 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**Schema export is deterministic and golden-tested**, on the same discipline as every other bloomery output: sorted keys, stable `$defs` order, no addresses in descriptions. A nondeterministic golden is noise, and these goldens are how schema changes become reviewable.

- Paths: `src/bloomery/schema.py` `tests/golden/test_spec_schemas.py` `tests/unit/test_determinism_guard.py` `tests/unit/test_schema.py`

### S-0041/D-5 — `LOCKED` (Deterministic union merge)

A key appearing in more than one source is refused by a generated **blocking** audit (`on_fail: fail`), not configurable to `flag` or `quarantine`. Overlap is either duplication or a shared key space by accident, and both are refusals. The message names the identity-resolution step as the escape hatch. Consequence: bloomery's union is for disjoint key sets, permanently — matching stays a step, and S-0038 is not reopened.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `tests/e2e/test_dbt_parse.py` `tests/e2e/test_sqlmesh_replan.py` `tests/execution/test_merged_cleaning.py` `tests/golden/test_sqlmesh_duckdb.py` `tests/unit/test_examples.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-34 — `LOCKED` (Deterministic union merge)

**Artifact shape varies with mapping count; `_source` stays merged-only (P2b).** The question D7 and D15 both defer, answered once for the provenance column, the metadata audit body and the collision audit together. The metadata audit becomes `PARTITION BY _source, _source_row_id` on a merged entity and stays `PARTITION BY _source_row_id` elsewhere. **The cost is a new precedent, stated here rather than discovered later:** until now the *set* of emitted artifacts varied with a spec, never a generated **body**. The alternative — `_source` on every entity, one uniform audit body, mapping count invisible in the artifacts — buys a reader the property that a merged entity looks like any other, and costs a corpus-wide golden re-stamp plus a constant column on every single-source silver model, which is precisely what D9 declined to pay on measured grounds. Continuing that decision is cheaper than reversing it, and reversing it buys nothing but uniformity. **A third option is named only to close it:** making `_source_row_id` globally unique in bronze would dissolve the question, and it does so by relocating the problem into S-0033/D-21's ingestion contract and breaking every table already landed under it.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_merged_cleaning.py` `tests/golden/test_sqlmesh_dialects.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-36 — `ASSUMED` (Deterministic union merge)

**Answers D28 — `direct:` is allowed on a merged entity when *every* mapping records one for the column, and refused when they disagree.** D28 refused the combination outright and handed P2 a choice between "one shadow projection per source with a null-safe audit" and "a coverage rule in D4's shape". Measured with the refusal disabled against two mappings that *agree*, the null-safe audit is answering the wrong question: the shadow column is duplicated on the entity **and on every branch**, the reconcile audit is emitted twice, and each branch carries the other's extraction — `shop__items` projecting `$.unit_price` off a relation that does not have it. That is not a NULL-shadow problem, it is `Derivation` being built per mapping while `_shadow` returns one projection: the same per-mapping-fact-on-a-shared-node shape D26 split for `expr` and D32 for the rule inputs. So the coverage rule is the answer and the null-safe audit is unnecessary under it — under agreement no branch's shadow is NULL for want of a path, and the reconcile check keeps the meaning it has on one source: the recipe-derived value against the direct value *that row's own mapping* extracted, which is D32's principle applied to a second reader. Consequence: `Derivation` carries its source relation, `path_conflict_amendments` fans out per source like every other lowering, and disagreement is refused by D33's pattern rather than tolerated. D28's row stands unamended — its refusal is correct until this one is executed, and what it predicted is the thing this has to be read against. *Added by execution 2026-09-03 — see logs/T-0012.md (F-8), which carries the probe output.*

- Paths: `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/build.py` `tests/execution/test_path_conflict.py` `tests/fixtures/path_conflict_merged/entity_model.yaml` `tests/fixtures/path_conflict_merged/mapping_legacy.yaml` `tests/golden/test_sqlmesh_duckdb.py` `tests/unit/test_fixtures.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_resolution.py`

### S-0050/D-11 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**Cube refuses derived and cumulative metrics per construct with `UnsupportedByTarget`, and emits metric filters.** Period-over-period is a query-time concern in Cube, and `grain_to_date` has no `rolling_window` equivalent. Refusing the offset-free derived case too — which `{member}` templating could express — keeps one rule where support-that-depends-on-an-offset would need two, and the ratio form still covers division.

- Paths: `tests/golden/test_metricflow_manifest.py` `tests/unit/test_emit/test_period_over_period.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0051/D-3 — `LOCKED` (The reject table on a merged entity)

**Replay filters each branch to `source_relation = '<branch>'`.** Without it a mapping's extraction runs over another mapping's payload and returns NULLs rather than raising — a silent wrong answer, which is the failure class this project refuses. The filter is sound because `(target, source)` is unique (S-0041/D-12), so the literal names exactly one branch.

- Paths: `src/bloomery/emit/lower/silver.py` `tests/execution/test_merged_cleaning.py` `tests/golden/test_sqlmesh_dialects.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0079/D-8 — `ASSUMED` (Determinations reach the IR and the rollup lowering) — implementation: none

The end-to-end proof is one **new** golden fixture, `coarsening_rollup`, registered in the three golden drivers' `EXPECTED_PATHS` tables — not an extension of `rollup_mart`

- Paths: `tests/fixtures/coarsening_rollup/**` `tests/golden/coarsening_rollup/**` `tests/golden/test_cube.py` `tests/golden/test_dbt_postgres.py` `tests/golden/test_sqlmesh_duckdb.py`
- Consequence: `rollup_mart` keeps answering the measure question alone, so a future diff in either fixture says which question moved. It also keeps the two phases' golden directories disjoint — the first phase's regeneration and the second phase's new artifacts are never the same file

<!-- /torve:managed -->
