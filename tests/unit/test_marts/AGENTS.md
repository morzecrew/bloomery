<!-- torve:managed tests/unit/test_marts — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/unit/test_marts/`

### S-0027/D-3 — `ASSUMED` (Marts and role-playing dimensions)

`flatten` via-steps require declared `many_to_one`/`one_to_one` relationships (else `FanoutRisk`); chains flatten transitively in authored order; prefixes mandatory; collisions are errors, never auto-renames.

- Paths: `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `src/bloomery/spec/marts.py` `tests/golden/schema/marts.json` `tests/unit/test_marts/test_flatten.py` `tests/unit/test_spec/test_marts.py`

### S-0033/D-15 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

A mart's `base` must be a silver entity, never a reject table — a mart over `<entity>__reject` is a compile error. Mart rowcounts legitimately differ from bronze (quarantined rows never reach marts); the conservation audit is what makes the difference explainable.

- Paths: `src/bloomery/marts/flatten.py` `src/bloomery/quality/mart.py` `tests/unit/test_marts/test_flatten.py`

### S-0034/D-52 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-10)* **D31's blanket refusal was one sentence covering two different targets, and it is right about neither in full.** D31 refused steps on dbt and Cube because "their output relations would simply be missing" — checked per target, that argument splits. **Cube builds nothing.** It emits cubes and views over marts, and no silver model, no reject table, no replay statement and no audit for *anything*: the `dirty_corpus` fixture — twelve quality-carrying entities, twelve reject models, a conservation audit apiece — compiles to two files on Cube and always has, refusing none of it. So "the relation would be missing" was never a reason to refuse a step *here*; it is equally true of every silver entity, and singling steps out made this emitter refuse one build-side declaration among the many it already leaves to whoever maintains the tables. The refusal is removed, and its docstring now says what the contract actually is: Cube consumes tables SQLMesh maintains, and is deliberately silent about how. (The mart-assertion refusal added the day before, S-0033/D-89, is removed from Cube for the same reason and stays on dbt.) **dbt builds**, so a step must emit or refuse, and the answer is per tier. Tier 1 needs nothing: the splice happens at lowering, so a macro is already inside its consuming model on every target — which means Tier 1 worked on dbt throughout and D31 never claimed otherwise only because a macro is referenced inline rather than wired in `steps:`. Tier 2 **emits**: the body is already canonicalized and parameter-substituted on `StepIR`, so dbt wraps the same SELECT SQLMesh does in its own envelope — asserted as byte equality between the two targets rather than as a claim, since one SELECT meaning two things is exactly the drift the shared lowering exists to prevent. Tier 3 stays refused, on a concrete reason rather than a blanket one: dbt *has* Python models, but only on Snowflake, BigQuery and Databricks, and none of bloomery's three dialects is one of them, so the wrapper would have no adapter to execute it. **Step audits are refused on dbt** — a consistency audit (D40) is a join between sibling outputs and an `on_fail: fail` body (D39) is a whole query, while dbt's schema tests are per-column or per-model predicates; `_entity_tests` already refuses an audit kind on exactly this ground. The refusal is decided by *building* the audits rather than by the presence of a step, so a single-output Tier 2 step with no `fail` rules keeps the tier instead of losing it to a reason that does not apply to it. **One trap, found and closed:** a step output is an entity in the DAG (D36) whose lowered `expr` is the column referring to itself, so removing the refusal without skipping `produced_by` entities would have had dbt emit an ordinary entity model beside the step's — a model selecting from the relation it defines, and two models writing one relation. SQLMesh already skipped them; dbt now does too. **Not verified, stated:** that dbt *parses* the emitted model is S-0026's outstanding `dbt parse` tier, not something this row claims. What is verified is that the SELECT is byte-identical to SQLMesh's and that the envelope is the one the dbt goldens already lock.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/steps.py` `tests/e2e/test_dbt_parse.py` `tests/golden/test_cube.py` `tests/unit/test_marts/test_asserts.py` `tests/unit/test_steps/test_dbt_and_cube_emission.py`

### S-0037/D-7 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**Five refusals gain optional structured suggestion fields** (§5.4), additive. The draft cited two existing precedents; only one is real. `UnsupportedFilter.reason` is an attribute; **`UnknownMember.did_you_mean` is not** — its docstring has promised the field since S-0028 while the closest match is computed and thrown into prose. So `UnknownMember` joins the list as a fifth entry rather than serving as the model for it, and the field is what finally makes its own docstring true. Each field exposes a value bloomery **already computes and currently discards**. Absence is `()` or `None` in Python and `[]` or `null` in the CLI JSON — always present, never fabricated, and never silently dropped from a structure §5.2 promises matches the API (§5.4).

- Paths: `src/bloomery/errors.py` `tests/unit/test_error_suggestions.py` `tests/unit/test_marts/test_flatten.py`

### S-0040/D-1 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

Flattening an entity with `scd: type2` into a mart is **refused** at compile time, not silently emitted and not silently filtered to the current version. The join has no validity predicate and the relation has one row per version, so the emitted mart multiplies the base grain while every guardrail passes. Consequence: the only shipped way to use a historical dimension in a mart is a `type1` current-view entity built from it, until §5.3 exists.

- Paths: `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `tests/fixtures/scd2_mart_refusal/entity_model.yaml` `tests/fixtures/semantic_corpus/003-scd2-unqualified-join/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/003-scd2-unqualified-join/problem.md` `tests/golden/refusals/example-scd2-flatten.txt` `tests/golden/refusals/scd2_mart_refusal.txt` `tests/unit/test_fixtures.py` `tests/unit/test_guardrails/test_stage.py` `tests/unit/test_marts/test_flatten.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0040/D-2 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

A mart whose **`base`** is `scd: type2` is refused on the same account. There is no fan-out, but the declared `grain:` claims one row per entity while the relation holds one per version, so every measure counts revisions. Refusing both sides keeps "a mart's grain is what it says" true without exception.

- Paths: `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `tests/fixtures/scd2_as_of/marts.yaml` `tests/fixtures/scd2_mart_refusal/entity_model.yaml` `tests/fixtures/scd2_replay/marts.yaml` `tests/golden/refusals/scd2_mart_refusal.txt` `tests/unit/test_fixtures.py` `tests/unit/test_guardrails/test_stage.py` `tests/unit/test_marts/test_flatten.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0040/D-8 — `OPEN` (Temporal joins: SCD2 flattening and currency conversion)

The as-of anchor's spelling and location. §5.3 proposes `as_of:` on the `flatten` entry; a mart-level default and a relationship-level declaration are both defensible. Whoever builds Phase 2 decides and logs it. It must be **declared** either way — inference is closed by S-0038.

- Paths: `tests/fixtures/semantic_corpus/003-scd2-unqualified-join/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/003-scd2-unqualified-join/problem.md` `tests/unit/test_marts/test_flatten.py`

<!-- /torve:managed -->
