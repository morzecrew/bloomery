<!-- torve:managed src/bloomery/emit/cube — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/emit/cube/`

### S-0025/D-3 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Capability mismatch behavior is fail-loud: `UnsupportedByTarget` naming entity + feature. Silent degradation is forbidden.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/spec/quality.py` `src/bloomery/transforms/_builtins.py` `tests/property/test_compile_properties.py` `tests/unit/test_emit/test_base.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_quality/test_text_rules.py` `tests/unit/test_transforms/test_builtins.py`

### S-0027/D-4 — `ASSUMED` (Marts and role-playing dimensions)

Date roles expand to exactly `{day, week, month, quarter, year}` bucket columns named `<role>_<bucket>`; `hour` is deliberately not expanded.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/lower/marts.py` `src/bloomery/marts/flatten.py` `src/bloomery/planner/coverage.py` `src/bloomery/planner/request.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `tests/golden/schema/marts.json`

### S-0034/D-52 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-10)* **D31's blanket refusal was one sentence covering two different targets, and it is right about neither in full.** D31 refused steps on dbt and Cube because "their output relations would simply be missing" — checked per target, that argument splits. **Cube builds nothing.** It emits cubes and views over marts, and no silver model, no reject table, no replay statement and no audit for *anything*: the `dirty_corpus` fixture — twelve quality-carrying entities, twelve reject models, a conservation audit apiece — compiles to two files on Cube and always has, refusing none of it. So "the relation would be missing" was never a reason to refuse a step *here*; it is equally true of every silver entity, and singling steps out made this emitter refuse one build-side declaration among the many it already leaves to whoever maintains the tables. The refusal is removed, and its docstring now says what the contract actually is: Cube consumes tables SQLMesh maintains, and is deliberately silent about how. (The mart-assertion refusal added the day before, S-0033/D-89, is removed from Cube for the same reason and stays on dbt.) **dbt builds**, so a step must emit or refuse, and the answer is per tier. Tier 1 needs nothing: the splice happens at lowering, so a macro is already inside its consuming model on every target — which means Tier 1 worked on dbt throughout and D31 never claimed otherwise only because a macro is referenced inline rather than wired in `steps:`. Tier 2 **emits**: the body is already canonicalized and parameter-substituted on `StepIR`, so dbt wraps the same SELECT SQLMesh does in its own envelope — asserted as byte equality between the two targets rather than as a claim, since one SELECT meaning two things is exactly the drift the shared lowering exists to prevent. Tier 3 stays refused, on a concrete reason rather than a blanket one: dbt *has* Python models, but only on Snowflake, BigQuery and Databricks, and none of bloomery's three dialects is one of them, so the wrapper would have no adapter to execute it. **Step audits are refused on dbt** — a consistency audit (D40) is a join between sibling outputs and an `on_fail: fail` body (D39) is a whole query, while dbt's schema tests are per-column or per-model predicates; `_entity_tests` already refuses an audit kind on exactly this ground. The refusal is decided by *building* the audits rather than by the presence of a step, so a single-output Tier 2 step with no `fail` rules keeps the tier instead of losing it to a reason that does not apply to it. **One trap, found and closed:** a step output is an entity in the DAG (D36) whose lowered `expr` is the column referring to itself, so removing the refusal without skipping `produced_by` entities would have had dbt emit an ordinary entity model beside the step's — a model selecting from the relation it defines, and two models writing one relation. SQLMesh already skipped them; dbt now does too. **Not verified, stated:** that dbt *parses* the emitted model is S-0026's outstanding `dbt parse` tier, not something this row claims. What is verified is that the SELECT is byte-identical to SQLMesh's and that the envelope is the one the dbt goldens already lock.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/steps.py` `tests/e2e/test_dbt_parse.py` `tests/golden/test_cube.py` `tests/unit/test_marts/test_asserts.py` `tests/unit/test_steps/test_dbt_and_cube_emission.py`

### S-0050/D-4 — `ASSUMED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A derived metric need not be named in any mart's `measures:`.** It has no measure to place. It is emitted where every input's measure is emitted — the rule the ratio already uses — and the planner's coverage precheck resolves it to the mart carrying those measures. Naming it in `measures:` stays legal and inert, as it is for a ratio.

- Paths: `src/bloomery/emit/cube/__init__.py` `tests/fixtures/period_over_period/marts.yaml` `tests/unit/test_emit/test_period_over_period.py`

### S-0062/D-5 — `LOCKED` (Ownership, classification and grants)

`grants` is refused for Cube. Cube reads relations it does not own, so emitting grants there would be a claim with no mechanism — the silent degradation S-0025/D-3 exists to prevent.

- Paths: `src/bloomery/emit/cube/__init__.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0062/D-12 — `ASSUMED` (Ownership, classification and grants)

A rollup declares its own `grants:` and does not inherit its parent mart's — D2's rule, applied to the one authored node that had no audience of its own. A rollup declaring none is the advisory of row 11 rather than a hole.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/spec/marts.py`

<!-- /torve:managed -->
