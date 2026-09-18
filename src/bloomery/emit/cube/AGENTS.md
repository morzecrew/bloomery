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

### S-0062/D-5 — `LOCKED` (Ownership, classification and grants)

`grants` is refused for Cube. Cube reads relations it does not own, so emitting grants there would be a claim with no mechanism — the silent degradation S-0025/D-3 exists to prevent.

- Paths: `src/bloomery/emit/cube/__init__.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0062/D-12 — `ASSUMED` (Ownership, classification and grants)

A rollup declares its own `grants:` and does not inherit its parent mart's — D2's rule, applied to the one authored node that had no audience of its own. A rollup declaring none is the advisory of row 11 rather than a hole.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/spec/marts.py`

### S-0065/D-1 — `LOCKED` (Rollup marts and pre-aggregations)

"Aggregate marts" and Cube `pre_aggregations` are **one feature**, scheduled once. The ceiling review named it twice, and building it twice is the failure this row exists to prevent.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/marts/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0065/D-2 — `LOCKED` (Rollup marts and pre-aggregations)

Blocked on S-0017 and S-0054. A rollup's safety is a functional-dependency question over an aggregation class, and both are those RFCs' vocabulary. Building first means inventing it worse and then owning two.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/marts/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0065/D-7 — `LOCKED` (Rollup marts and pre-aggregations)

Cube-to-cube `joins` stay out of this RFC. They reintroduce the query-time joins the wide-mart design removes — the position S-0030/D-3 states for MetricFlow semantic models, reached independently for Cube rather than inherited from it. Cube's own refusal is unwritten, and writing it belongs with whatever RFC takes Cube's surface.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/marts/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0065/D-8 — `LOCKED` (Rollup marts and pre-aggregations)

**No plan transformation may merge two aggregate branches before aggregation without proving the merge preserves every measure's grain.** Inherited from S-0055/cost-is-secondary-to-soundness and §10, readable at `654d93e`: that document stated the rule and asked for a property test constructing such a partition and asserting the merge is refused. Neither was built, because the optimization pass §9 deferred it to does not exist. Parked here rather than dropped at S-0055's retirement, because this is the live document holding a preservation obligation (§5.2) and the two are one shape — a transformation is legal only when it can show the aggregate it produces is the one the detail would have produced. It is **not** a rollup-mart decision and does not gate this feature: it transfers to whatever document builds a `SemanticPlan` optimization pass, which owes §6's inherited test with it. `LOCKED` because a merge without the proof is silent double counting, which this sequence refuses rather than approximates. Recorded at S-0055's retirement — see `81df8cc`.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/marts/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0065/D-14 — `LOCKED` (Rollup marts and pre-aggregations)

**A rollup mart is never a measure owner and never a covering mart.** §4 makes query-time rollup selection S-0054's job and nothing in the code knows it: `measure_owners` picks the cheapest mart serving a measure, a rollup is by construction the cheapest, and so the first rollup declared would take detail-grain requests silently and answer them from monthly totals — quickly, plausibly and wrongly, which is the class §2 gives as the reason this feature is the one where being wrong is worst. `LOCKED` because reversing it is not a scheduling call: it is the planner learning to choose, and that is a different document's work.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/marts/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0077/D-1 — `LOCKED` (A ratio over one row set)

**bloomery does not choose which rows a ratio is about.** Both readings — per unit over units that exist, and total over units with overheads included — are metrics somebody wants, and the defect is that they are spelled identically. The rule refuses until the author says; it never picks. Locked because every cheaper design is a compiler making a decision about somebody's business, and the wrong one is invisible in the output.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/semantic/additivity.py` `src/bloomery/spec/quality.py` `tests/fixtures/semantic_corpus/008-ratio-rollup/**` `tests/fixtures/semantic_corpus/009-null-denominator/**`
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
