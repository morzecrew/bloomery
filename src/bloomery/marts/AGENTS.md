<!-- torve:managed src/bloomery/marts — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/marts/`

### S-0017/D-4 — `ASSUMED` (Semantic grain model and functional dependencies)

The as-of qualification reuses the historical-fanout guardrail's semantic fact rather than restating it

- Paths: `src/bloomery/semantic/historical.py` `src/bloomery/marts/flatten.py`
- Consequence: Two readings of SCD2 validity in one compiler is the divergence this project has paid for before — one body, two callers

### S-0017/D-10 — `ASSUMED` (Semantic grain model and functional dependencies)

The as-of fact lives in one function in the semantic package, and the mart guard reads it from there

- Paths: `src/bloomery/semantic/historical.py` `src/bloomery/marts/flatten.py`
- Consequence: Anything in this sequence that needs to know whether a historical hop is qualified calls that function; the anchor states it distinguishes are finer than the two sentences the mart needed, which is what a blocked edge carries

### S-0017/D-13 — `ASSUMED` (Semantic grain model and functional dependencies)

The mart's grain refusal stays on grain-string equality until a planner has exercised this substrate

- Paths: `src/bloomery/marts/flatten.py`
- Consequence: The only thing the mart path takes from this document is the as-of fact; its grain comparison is untouched, and the unit tier pins the decision as well as the behaviour so a later silent migration is visible

### S-0019/D-4 — `ASSUMED` (Spec layer and error model)

Parse validates shape and grammar only; reference existence (entities, transforms, canonical fields) is deferred to resolve/typecheck. Consequence: a shape-valid spec with dangling references parses fine — callers must run `resolve` to trust it.

- Paths: `src/bloomery/marts/flatten.py` `src/bloomery/resolve/refs.py` `src/bloomery/spec/__init__.py` `src/bloomery/spec/entity.py` `src/bloomery/spec/mapping.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `tests/golden/schema/metrics.json` `tests/property/test_schema_agreement.py` `tests/unit/test_spec/test_entity.py`

### S-0019/D-7 — `ASSUMED` (Spec layer and error model)

`materialization` is explicit-with-derived-default (settles original open question #4); the resolved value is IR-recorded and diffable.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/ir/nodes.py` `src/bloomery/marts/flatten.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/entity.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_entity.py`

### S-0027/D-2 — `ASSUMED` (Marts and role-playing dimensions)

Measure grain must strictly equal mart grain; coarser or finer is `GrainViolation`. Resolves D2's prose/example contradiction to the strict reading; relaxation is a future additive change.

- Paths: `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/semantic/proof.py` `src/bloomery/semantic/rollup.py` `tests/fixtures/fanout_trap/marts.yaml` `tests/fixtures/fanout_trap/metrics.yaml` `tests/fixtures/semantic_corpus/001-order-shipping-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/001-order-shipping-fanout/problem.md` `tests/fixtures/semantic_corpus/010-many-to-many-bridge/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/010-many-to-many-bridge/problem.md` `tests/golden/refusals/example-wrong-grain.txt` `tests/golden/refusals/fanout_trap.txt` `tests/support/semantic_corpus.py` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_semantic_corpus_guard.py`

### S-0027/D-3 — `ASSUMED` (Marts and role-playing dimensions)

`flatten` via-steps require declared `many_to_one`/`one_to_one` relationships (else `FanoutRisk`); chains flatten transitively in authored order; prefixes mandatory; collisions are errors, never auto-renames.

- Paths: `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `src/bloomery/spec/marts.py` `tests/golden/schema/marts.json` `tests/unit/test_marts/test_flatten.py` `tests/unit/test_spec/test_marts.py`

### S-0027/D-4 — `ASSUMED` (Marts and role-playing dimensions)

Date roles expand to exactly `{day, week, month, quarter, year}` bucket columns named `<role>_<bucket>`; `hour` is deliberately not expanded.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/lower/marts.py` `src/bloomery/marts/flatten.py` `src/bloomery/planner/coverage.py` `src/bloomery/planner/request.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `tests/golden/schema/marts.json`

### S-0027/D-6 — `ASSUMED` (Marts and role-playing dimensions)

Mart flattening is resolved at IR build (`bloomery/marts/`, pure): consumers see the wide schema, never the recipe. `ProjectIR.marts` is fingerprint-covered.

- Paths: `src/bloomery/marts/flatten.py` `src/bloomery/resolve/build.py` `tests/unit/test_evidence.py` `tests/unit/test_resolve/test_build.py`

### S-0027/D-7 — `ASSUMED` (Marts and role-playing dimensions)

Marts are optional: a project without a `marts:` document compiles silver only; the planner then refuses everything with `UnreachableAtGrain` (no marts, no serving surface).

- Paths: `src/bloomery/marts/flatten.py` `src/bloomery/spec/marts.py` `tests/golden/schema/marts.json`

### S-0027/D-9 — `ASSUMED` (Marts and role-playing dimensions)

(Amended for `_bloomery-metricflow-pivot.md`) Marts are the emission source for MetricFlow semantic models — one mart = exactly one semantic model (S-0030 R1); a measure-carrying mart must declare a date role (`MartMissingTimeDimension` otherwise). Marts and role-playing are *more* load-bearing after the pivot, not less.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/marts/flatten.py` `src/bloomery/quality/mart.py` `src/bloomery/resolve/graph.py` `tests/fixtures/ecom_basic/marts.yaml` `tests/fixtures/quality_precedence/entity_model.yaml` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_fixtures.py` `tests/unit/test_quality/test_mart.py` `tests/unit/test_resolve/test_graph.py`

### S-0033/D-9 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Silver gains `_quality_flags`/`_quality_ok`; marts gain `has_quality_flags` (S-0027 amendment). Array capability is `DialectFeature.ARRAY` — an engine property, deliberately diverging from Document 5's `TargetCapabilities` placement; dialects without it lower to a delimited string.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/marts/flatten.py` `src/bloomery/spec/common.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_steps/test_lowering.py`

### S-0033/D-15 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

A mart's `base` must be a silver entity, never a reject table — a mart over `<entity>__reject` is a compile error. Mart rowcounts legitimately differ from bronze (quarantined rows never reach marts); the conservation audit is what makes the difference explainable.

- Paths: `src/bloomery/marts/flatten.py` `src/bloomery/quality/mart.py` `tests/unit/test_marts/test_flatten.py`

### S-0033/D-57 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **`range` bounds are exact or refused.** `min`/`max` typed `int

- Paths: `src/bloomery/marts/flatten.py` `tests/unit/test_plan/test_quality_changes.py`

### S-0033/D-89 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **Mart-level checks are assertions, not quality rules. §10's open question is settled by the disposition model.** §8 deferred them as "blurs into reconciliation" and §10 asked "reconcile-shaped or new surface?" — the answer is neither, and what decides it is not taste. §5.9 draws the boundary at what a verdict *does*: a quality rule disposes of a **row**. A mart row is derived — no `_source_row_id`, no bronze payload, no reject table, no replay — so there is nothing to quarantine, nothing to repair, and nothing to bring back; and a `reconcile` compares *two sides*, which "no month has zero revenue" is not. What is left is D4's other half, "alert me", so `assert:` on a mart declares `{measure, agg, by, min/max, on_fail}` and lowers to an audit the mart model names. `quarantine` and `repair` are absent from its `on_fail` rather than lowered to something weaker, so an author who wanted routing learns it at the surface instead of from a mart that silently only alerts; `fail`/`flag` map to blocking/non-blocking exactly as `reconcile.on_fail` does (D38). The aggregate vocabulary is deliberately the *same tuple* the reconcile grammar uses — both compute one number over a column so a human can be told it is wrong, and two lists that mean the same thing drift. Bounds ride in `params` as text through the D57 carrier, for the same reason. **Resolution is against the flattened column set**, not the base entity's: `ordered_month` exists only because a `date:` step made it, and it is precisely the column §10's example groups by. **The body** is `SELECT <by…>, <agg>(<measure>) FROM @this_model [GROUP BY <by…>] HAVING <bound comparison>` — the value beside the group, because a failure a human must open the warehouse to understand gets ignored. A bare `HAVING` with no `GROUP BY` is the whole-mart form; both shapes were executed on DuckDB, postgres 16 and `trinodb/trino:483` rather than read out of three manuals, and all three agree. **What it cannot see, stated rather than implied:** D19 reaches the mart, so every aggregate but `count` is NULL over an empty group and the assertion stays silent — which is also why an assertion cannot notice a month that is *entirely missing*: no row means no group at all. `count` is the exception and is the one shape that catches an empty mart. Closing the missing-period case needs a join against the date spine, a coverage check with its own dependency, and it is named here rather than half-built. **dbt refuses a project carrying one**, sharing `refuse_steps`' message shape (**amended by D94**: this row said "dbt and Cube", and the Cube half was already obsolete when it was written — S-0034/D-52 had split the blanket Cube refusal on the argument that Cube builds no relation for anything, and Cube compiles the *entire* quality surface, quarantine and reject tables included, without a murmur; refusing this one check would single it out): neither has the audit form, and compiling clean while the declared gate does not exist is the failure D83 caught in the dialect ports. **Cost recorded:** `MartIR` gains a field, and the canonical encoder covers each node's field *names and count*, so every fingerprint in the corpus moves — the churn §12 budgets, spent deliberately. The fixture carrying the demonstration is `quality_precedence` rather than `ecom_basic`, because an assertion makes a project uncompilable for two targets and `ecom_basic` is the fixture those targets' goldens are built on.

- Paths: `src/bloomery/emit/base.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/marts/flatten.py` `src/bloomery/spec/marts.py` `tests/execution/test_quality_precedence.py` `tests/fixtures/quality_precedence/marts.yaml` `tests/golden/schema/marts.json`

### S-0040/D-1 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

Flattening an entity with `scd: type2` into a mart is **refused** at compile time, not silently emitted and not silently filtered to the current version. The join has no validity predicate and the relation has one row per version, so the emitted mart multiplies the base grain while every guardrail passes. Consequence: the only shipped way to use a historical dimension in a mart is a `type1` current-view entity built from it, until §5.3 exists.

- Paths: `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `tests/fixtures/scd2_mart_refusal/entity_model.yaml` `tests/fixtures/semantic_corpus/003-scd2-unqualified-join/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/003-scd2-unqualified-join/problem.md` `tests/golden/refusals/example-scd2-flatten.txt` `tests/golden/refusals/scd2_mart_refusal.txt` `tests/unit/test_fixtures.py` `tests/unit/test_guardrails/test_stage.py` `tests/unit/test_marts/test_flatten.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0040/D-2 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

A mart whose **`base`** is `scd: type2` is refused on the same account. There is no fan-out, but the declared `grain:` claims one row per entity while the relation holds one per version, so every measure counts revisions. Refusing both sides keeps "a mart's grain is what it says" true without exception.

- Paths: `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `tests/fixtures/scd2_as_of/marts.yaml` `tests/fixtures/scd2_mart_refusal/entity_model.yaml` `tests/fixtures/scd2_replay/marts.yaml` `tests/golden/refusals/scd2_mart_refusal.txt` `tests/unit/test_fixtures.py` `tests/unit/test_guardrails/test_stage.py` `tests/unit/test_marts/test_flatten.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0065/D-1 — `LOCKED` (Rollup marts and pre-aggregations)

"Aggregate marts" and Cube `pre_aggregations` are **one feature**, scheduled once. The ceiling review named it twice, and building it twice is the failure this row exists to prevent.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/marts/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0065/D-2 — `LOCKED` (Rollup marts and pre-aggregations)

Blocked on S-0017 and S-0054. A rollup's safety is a functional-dependency question over an aggregation class, and both are those RFCs' vocabulary. Building first means inventing it worse and then owning two.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/marts/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0065/D-5 — `LOCKED` (Rollup marts and pre-aggregations)

An unprovable rollup is **refused**, never warned about. A rollup is read instead of the detail table, so a wrong one answers quickly and plausibly — the class this project refuses rather than approximates.

- Paths: `src/bloomery/cli/render.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/evidence.py` `src/bloomery/guardrails/stage.py` `src/bloomery/marts/rollup.py` `src/bloomery/semantic/rollup.py` `tests/fixtures/semantic_corpus/012-rollup-recounts-identities/problem.md` `tests/unit/test_semantic/test_plan.py`
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

<!-- /torve:managed -->
