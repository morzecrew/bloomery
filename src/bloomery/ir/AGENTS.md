<!-- torve:managed src/bloomery/ir — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/ir/`

### S-0002/D-3 — `LOCKED` (Multi-project composition) — implementation: partial

The downstream fingerprint includes the upstream fingerprint whole, never only the exports the downstream touched

- Paths: `src/bloomery/ir/fingerprint.py` `tests/unit/test_ir/test_fingerprint.py`
- Consequence: An upstream change that touches nothing the downstream reads still moves the downstream fingerprint, and artifact headers change on projects nothing about which changed; the docs have to meet that head on rather than the rule being softened
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0002/D-10 — `ASSUMED` (Multi-project composition) — implementation: partial

An upstream's dbt project name is part of what it exports: `exports.yaml` carries an optional `name`, `ExportsIR` carries it across, and the downstream's dbt target spells the two-argument `ref()` and the `dependencies.yml` entry with that name while the downstream's own `dbt_project.yml` is named after its own export name when it has one. The local alias stays what keys the compile input and the IR resolution (D-2); dbt is the one target whose cross-project reference needs the producer's own name, so the name lives on the producer's side of the boundary and nowhere else.

- Paths: `src/bloomery/spec/exports.py` `src/bloomery/ir/nodes.py` `src/bloomery/emit/dbt/__init__.py` `tests/unit/test_emit/test_cross_project.py`
- Consequence: A downstream compiled against an upstream that exports no name keeps emitting `ref('<alias>', ...)` and a `dependencies.yml` naming the alias — resolvable only when the upstream's dbt project happens to be named so — and the refusal for that case is a documented gap until the row is graded. An exported SCD2 entity is a snapshot on dbt, which no project can reference across the boundary; the export is legal and the dbt target has nothing public to give for it.

### S-0007/D-5 — `ASSUMED` (Dimension algebra)

`role_of:` generalizes `DateRoleStep` rather than replacing it. A date's roles expand into buckets, which is a date-specific elaboration, so the two coexist

- Paths: `src/bloomery/spec/marts.py` `src/bloomery/ir/nodes.py`
- Consequence: Existing projects with `flatten: [{date: …, role: …}]` compile unchanged and the general role is additive beside them; departing means absorbing dates into the general vocabulary, which touches every existing project

### S-0017/D-9 — `LOCKED` (Semantic grain model and functional dependencies)

The grain model is derived from the project IR, never stored in it: a grain is computed on demand from an entity's declared key and adds no field to any IR node

- Paths: `src/bloomery/semantic/closure.py` `src/bloomery/ir/nodes.py`
- Consequence: The IR version does not move, no project fingerprint moves and no golden moves, which is what turns preserve-observable-behaviour from an argument into a diff; verified by compiling every fixture, target and dialect on both sides of the branch — 251 cells, byte-identical
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0017/D-15 — `ASSUMED` (Semantic grain model and functional dependencies)

`many_to_many` names a cardinality this tree does not have — the cardinality enum is `many_to_one`, `one_to_one` and `one_to_many` — so the prose and D-3 describe a member no spec can declare and no IR can carry

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/semantic/closure.py`
- Consequence: Nothing was built for it and their text stands as written: this row is the correction, not an edit to them

### S-0019/D-7 — `ASSUMED` (Spec layer and error model)

`materialization` is explicit-with-derived-default (settles original open question #4); the resolved value is IR-recorded and diffable.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/ir/nodes.py` `src/bloomery/marts/flatten.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/entity.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_entity.py`

### S-0020/D-1 — `ASSUMED` (Intermediate representation and determinism contract)

IR is frozen stdlib dataclasses (slots), not Pydantic — validation happens at build, value semantics matter after.

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/plan/model.py` `tests/unit/test_resolve/test_build.py`

### S-0020/D-2 — `ASSUMED` (Intermediate representation and determinism contract)

SQL is stored in the IR as canonical dialect-neutral SQLGlot text (`SqlExpr`), re-parsed at emit. Consequence: SQLGlot version changes can change fingerprints; the exact pin (D4 §5.5) makes that a deliberate event.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/emit/lower/marts.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `src/bloomery/transforms/_builtins.py` `tests/support/type_conformance.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_postgres.py` `tests/unit/test_transforms/test_builtins.py` `tests/unit/test_transforms/test_type_conformance_corpus.py`

### S-0020/D-3 — `ASSUMED` (Intermediate representation and determinism contract)

`project_fingerprint` = `"blm1:" + sha256(canonical bytes)`; includes `bloomery_ir_version`; stable within a bloomery version, explicitly not across versions.

- Paths: `src/bloomery/ir/fingerprint.py` `tests/unit/test_ir/test_fingerprint.py` `tests/unit/test_ir/test_nodes.py`

### S-0020/D-4 — `ASSUMED` (Intermediate representation and determinism contract)

All IR collections are tuples with explicit lexicographic sort, except authored-order fields (`key`, transform chains, recipe aliases, `partition_by`).

- Paths: `src/bloomery/ir/lower.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/dedupe.py` `src/bloomery/quality/lower.py` `src/bloomery/resolve/build.py` `tests/unit/test_quality/test_dedupe_and_reject.py` `tests/unit/test_resolve/test_build.py`

### S-0020/D-5 — `ASSUMED` (Intermediate representation and determinism contract)

Floats are banned in IR and emission; `Decimal`/int only.

- Paths: `src/bloomery/cli/serialize.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/steps.py` `src/bloomery/ir/fingerprint.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/request.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/common.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `src/bloomery/steps/manifest.py` `src/bloomery/steps/splice.py` `src/bloomery/transforms/_builtins.py` `src/bloomery/typing/types.py` `tests/execution/test_as_of_join.py` `tests/execution/test_currency_convert.py` `tests/execution/test_fanout_trap.py` `tests/execution/test_marts.py` `tests/execution/test_period_over_period.py` `tests/execution/test_rollup.py` `tests/fixtures/semantic_corpus/002-average-of-averages/naive.sql` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/golden/schema/marts.json` `tests/support/planning.py` `tests/support/semantic_corpus.py` `tests/unit/test_cli.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_planner/test_request.py` `tests/unit/test_quality/test_edges.py` `tests/unit/test_spec/test_metrics.py` `tests/unit/test_spec/test_quality.py` `tests/unit/test_steps/test_lowering.py` `tests/unit/test_steps/test_manifest_and_registry.py` `tests/unit/test_typing/test_types.py`

### S-0020/D-6 — `ASSUMED` (Intermediate representation and determinism contract)

Unreachable metrics are IR members (`unreachable` tuple with missing leaves), not log lines — they are product-facing output.

- Paths: `src/bloomery/ir/nodes.py`

### S-0022/D-3 — `ASSUMED` (Resolution: dependency DAG, recipes, reachability)

A canonical field is available iff some mapped field links to it via `canonical:` with a direct mapping or validated recipe. A metric is reachable iff every leaf of its `requires`/`requires_metrics` closure is available; unreachable metrics report the specific missing leaves and are stored in the IR (S-0020/D-6) as product-facing output.

- Paths: `src/bloomery/evidence.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/reach.py` `tests/unit/test_evidence.py` `tests/unit/test_unresolved.py`

### S-0023/D-7 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Path conflict does not raise (`PathConflict` is not an error class): the compiler emits the derived column, a `<name>__direct` shadow, and a `RECONCILE` `AuditIR`. The forbidden thing is the silent choice; both paths are valid, so the refusal targets the silence, not the spec.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/quality.py` `src/bloomery/ir/lower.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/mapping.py` `tests/fixtures/path_conflict/entity_model.yaml` `tests/fixtures/path_conflict/mapping.yaml` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_ir/test_lower.py` `tests/unit/test_spec/test_mapping.py`

### S-0025/D-11 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

(Amended, S-0027) The SQLMesh emitter also builds marts: one gold-layer model per `MartIR`, the only join-emitting path for marts.

- Paths: `src/bloomery/emit/lower/marts.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py` `tests/unit/test_emit/test_sqlmesh.py`

### S-0025/D-13 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

(Reverses D6) Bloomery owns the date dimension: one catalog definition emits both the SQLMesh `gold.dim_date` model and the MetricFlow time-spine declaration (S-0030 R1). D6's demand-gate is satisfied — MetricFlow is the demand.

- Paths: `src/bloomery/emit/lower/marts.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/metrics.py` `tests/execution/test_marts.py` `tests/fixtures/ecom_basic/catalog.yaml` `tests/golden/schema/catalog.json` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_fixtures.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_metrics.py`

### S-0027/D-1 — `ASSUMED` (Marts and role-playing dimensions)

Gold is wide pre-joined marts declared in a fifth spec kind (`marts_version: 1`); no query-time joins on the common path. One `MartIR` is read by both the mart builder (SQLMesh, joins at build) and the planner (no joins) — they cannot disagree.

- Paths: `src/bloomery/ir/nodes.py`

### S-0028/D-5 — `ASSUMED` (Native planner: MetricRequest → QueryPlan)

Additivity lowering per D4 exactly: additive → SUM at requested grain; semi-additive (`SemiAdditivePolicy(over, rule ∈ last/first/avg/max/min)`) → sum across every dimension except `over`, rule along `over` (coarser requested grain: rule within each bucket, then sum); non-additive → never stored/summed, recomputed from additive components (`RatioSpec` → `SUM(num)/NULLIF(SUM(den),0)`); missing components = `NonAdditiveWithoutComponents` at resolution/guardrail stage (S-0023 defense-in-depth).

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/coverage.py` `src/bloomery/planner/explain.py` `src/bloomery/planner/result.py` `src/bloomery/spec/common.py` `tests/fixtures/non_additive_aov/marts.yaml` `tests/fixtures/non_additive_aov/metrics.yaml` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_planner/test_coverage.py`

### S-0033/D-2 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

`OnFail = flag | quarantine | fail` (v1 — `repair` deferred, decision 17; landed in D87), explicit per rule, never a global default. Deliberately no `drop`: quarantine is drop plus recoverability; deletion happens via retention policy, with a paper trail.

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/spec/quality.py` `tests/unit/test_ir/test_nodes.py` `tests/unit/test_plan/test_quality_changes.py` `tests/unit/test_spec/test_quality.py`

### S-0033/D-10 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

One `<entity>__reject` table per entity with the §5.6 schema (stable sha256 `reject_id` for idempotent replay). Retention is **required** whenever any quarantine disposition exists — missing retention is a compile error; retention deletes **all** reject rows on expiry (unresolved measured from `last_seen`, resolved from `resolved_at`) and is the only deleter — replay never deletes. `redact:` paths apply at write time and must not intersect any path the entity's mappings read (`from` paths, recipe aliases included) — an intersecting redact is the compile error `RedactionConflict`. Bloomery emits the reject/replay artifacts and never executes them.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/errors.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `tests/engines/test_merged_cleaning_engines.py` `tests/fixtures/multi_source_quality/entity_model.yaml` `tests/unit/test_guardrails/test_quality.py`

### S-0033/D-19 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Three-valued logic: each rule defines a violation predicate and fires only when it is definitively TRUE — NULL-involved comparisons evaluating to SQL `UNKNOWN` do **not** fire (`not_null`/`coercible` own nulls; declare them if nulls are invalid). Applies to `range`/`length`/`pattern`/`in_enum`/`in_set`/`expression`/`referential` — a NULL fk is not an orphan. Corrects Document 5's referential lowering: the bare `COALESCE(fk, '__unknown__')` sketch was wrong (it maps a NULL fk to the unknown member); the lowering is `CASE WHEN ref.<pk> IS NULL AND fk IS NOT NULL THEN '__unknown__' ELSE fk END`.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/predicates.py` `tests/fixtures/quality_precedence/mapping_dups.yaml` `tests/unit/test_ir/test_nodes.py` `tests/unit/test_quality/test_predicates.py`

### S-0033/D-20 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Dedupe is a total order: after `field` DESC and the `tie_break` columns, the final sort key is the stable source-row identity `_source_row_id` — the winner is unique by construction *given the metadata contract* (D21): `_source_row_id` is declared **NOT NULL and unique per source row**, an ingestion-layer obligation enforced at run time by a generated blocking audit on the metadata columns (a data property, not compile-checkable). Null ordering pinned: `NULLS LAST` on **every** sort key including `_source_row_id` (defense in depth — DESC defaults to NULLS FIRST on several engines, so an illegally-null identity must still lose, never win).

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/quality/dedupe.py` `tests/execution/test_dedupe_and_audits.py` `tests/execution/test_quality_precedence.py` `tests/fixtures/quality_precedence/entity_model.yaml` `tests/support/precedence.py` `tests/unit/test_quality/test_dedupe_and_reject.py`

### S-0033/D-50 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **Generated rule names are collision-free and independent of authored order.** Two facts had to be *made* true. Suffixing appended `_{n}` without checking the result was free, so two `a_range_min` rules and an authored `expression` rule legally named `a_range_min_2` produced two rules under one name — one unreadable `failed_rules` entry and one quality-mart row computing the union of both rules' failures; the suffix now counts up until the candidate is actually unused. And `quality_sort_key` omitted `on_fail`, so two rules differing only in disposition sorted equal, the stable sort fell through to authored order, and swapping two YAML lines compiled the same spec to two different IRs (S-0020). `on_fail` joins the key as its last component, breaking only ties nothing else could break.

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/quality/lower.py`

### S-0033/D-87 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **`repair` lands, its recipe is a registered `sql_macro`, and its marker is its own column. D17 is closed.** D17 gated the disposition on a repair-recipe contract and left §10 asking *inline vs catalog-referenced*. S-0034's step registry answers both at once: a recipe is `ref@version` into the registry — declared signature, `runtime_lock`, determinism tier, trust-then-verify — and D1 already holds that specs reference implementations and never contain them, so an inline recipe would have been a second, weaker copy of all of it reachable only from here. **The lowering.** The recipe is spliced at IR build, where the registry lives, and travels as SQL in the rule's params the way an `expression` rule's body does — so emission needs no registry, and a version or `runtime_lock` bump lands in the IR where the fingerprint and `plan()` see it (measured: a body change classifies RESTATING and puts the entity in `replay_scope`, because the kind's params define neither an ordered interval nor a membership set and D52's undecidable-means-replay applies). The rewrite happens at the **extract** level, inside the column's own projection: `CASE WHEN <violation over the raw expression> THEN <recipe> ELSE <raw> END`. That placement is what makes every other rule see the repaired value with no extra nesting, and it forces both halves to be rewritten to read the column's expression rather than its name, since the column is being defined in the same `SELECT`. **The marker.** `_quality_repairs` is a separate column, which was cubic's condition in review and is the right one: a rule is recorded there when its recipe *ran and worked* — it fired over the value as delivered and no longer fires over the value that replaced it. `_quality_flags` stays empty for a repaired row, so `has_quality_flags` keeps meaning **currently suspect** and no mart already asking that question changes its answer. Unlike the two universal columns it is emitted only where a repair rule exists: §12 budgeted the silver-schema churn once, and a third column empty for every project not using the feature is not worth re-opening every golden and fingerprint for. **`fallback` is required**, for the same reason `on_fail` is (D2): a recipe that ran and failed leaves the rule violated and the row is disposed of exactly as if no repair had been declared — the alternative, a still-broken value landing in silver marked as fixed, is the `drop` this RFC refuses wearing a friendlier name. **Refusals**, each a property of the declaration alone: `repair` on `coercible` (it fires *because* the projection is already NULL, so the recipe would be handed the NULL rather than the text that failed to cast — fixing a value before coercion is a Tier 1 macro in the mapping, and the message says so), on `unique` (a property of a population; no rewrite of one row makes a duplicate unique), on a row rule (no column to rewrite), two repair rules on one column (both rewrite the same projection, so which value survives would depend on authoring order and the second recipe would judge a value the first had changed), a recipe accepting more than one column (a rule has no `from:` map, and inventing one would make a rule a second mapping surface), and a column the dedupe order reads (dedupe runs *before* the field rules per D7, so the winner would be chosen on the value as delivered and then have that value rewritten underneath it — D6's reasoning exactly). Verified by executing the emitted pipeline over three rows — one the recipe fixes, one it cannot, one it must not touch — and by sabotage: disabling the recipe, and dropping the "did it run" conjunct from the marker, each fail the assertion that names them. **Not built:** `gold.mart_data_quality` gains no `rows_repaired`, so repairs are observable in silver and not in the quality mart. Recorded rather than implied — adding a measure changes the mart schema, and no demand has asked for it.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/lower.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/spec/quality.py` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/golden/schema/steps.json` `tests/unit/test_spec/test_quality.py`

### S-0033/D-89 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **Mart-level checks are assertions, not quality rules. §10's open question is settled by the disposition model.** §8 deferred them as "blurs into reconciliation" and §10 asked "reconcile-shaped or new surface?" — the answer is neither, and what decides it is not taste. §5.9 draws the boundary at what a verdict *does*: a quality rule disposes of a **row**. A mart row is derived — no `_source_row_id`, no bronze payload, no reject table, no replay — so there is nothing to quarantine, nothing to repair, and nothing to bring back; and a `reconcile` compares *two sides*, which "no month has zero revenue" is not. What is left is D4's other half, "alert me", so `assert:` on a mart declares `{measure, agg, by, min/max, on_fail}` and lowers to an audit the mart model names. `quarantine` and `repair` are absent from its `on_fail` rather than lowered to something weaker, so an author who wanted routing learns it at the surface instead of from a mart that silently only alerts; `fail`/`flag` map to blocking/non-blocking exactly as `reconcile.on_fail` does (D38). The aggregate vocabulary is deliberately the *same tuple* the reconcile grammar uses — both compute one number over a column so a human can be told it is wrong, and two lists that mean the same thing drift. Bounds ride in `params` as text through the D57 carrier, for the same reason. **Resolution is against the flattened column set**, not the base entity's: `ordered_month` exists only because a `date:` step made it, and it is precisely the column §10's example groups by. **The body** is `SELECT <by…>, <agg>(<measure>) FROM @this_model [GROUP BY <by…>] HAVING <bound comparison>` — the value beside the group, because a failure a human must open the warehouse to understand gets ignored. A bare `HAVING` with no `GROUP BY` is the whole-mart form; both shapes were executed on DuckDB, postgres 16 and `trinodb/trino:483` rather than read out of three manuals, and all three agree. **What it cannot see, stated rather than implied:** D19 reaches the mart, so every aggregate but `count` is NULL over an empty group and the assertion stays silent — which is also why an assertion cannot notice a month that is *entirely missing*: no row means no group at all. `count` is the exception and is the one shape that catches an empty mart. Closing the missing-period case needs a join against the date spine, a coverage check with its own dependency, and it is named here rather than half-built. **dbt refuses a project carrying one**, sharing `refuse_steps`' message shape (**amended by D94**: this row said "dbt and Cube", and the Cube half was already obsolete when it was written — S-0034/D-52 had split the blanket Cube refusal on the argument that Cube builds no relation for anything, and Cube compiles the *entire* quality surface, quarantine and reject tables included, without a murmur; refusing this one check would single it out): neither has the audit form, and compiling clean while the declared gate does not exist is the failure D83 caught in the dialect ports. **Cost recorded:** `MartIR` gains a field, and the canonical encoder covers each node's field *names and count*, so every fingerprint in the corpus moves — the churn §12 budgets, spent deliberately. The fixture carrying the demonstration is `quality_precedence` rather than `ecom_basic`, because an assertion makes a project uncompilable for two targets and `ecom_basic` is the fixture those targets' goldens are built on.

- Paths: `src/bloomery/emit/base.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/marts/flatten.py` `src/bloomery/spec/marts.py` `tests/execution/test_quality_precedence.py` `tests/fixtures/quality_precedence/marts.yaml` `tests/golden/schema/marts.json`

### S-0033/D-90 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **Cross-entity checks are `coverage:` on a relationship, and the audit hangs off the *dependent* side. §10's last open question is settled.** §10 guessed "probably reconcile-style"; it is not, and the reason is structural rather than stylistic. A `reconcile` compares two **values** and alerts beyond a tolerance — there is no right-hand value on the referenced entity to compare against, and `right: 1` is neither a shape the closed grammar admits nor one it should grow. This asserts **existence**: every row of a relationship's referenced entity has at least `min` rows referencing it. That makes it the mirror of `referential`, which asks whether every *dependent* row has a parent, and both read the same two relations through the same `via` pairs — which is why it is declared on the **relationship** rather than on either entity. **Why an audit, when a disposition would have been meaningful.** Unlike a mart row (D89), a childless customer is a real silver row with a source identity, a reject table and a replay path, so routing it is not nonsense. It is still an audit, for a reason that only shows up in the DAG: routing would need the *referenced* entity's model to read the *dependent* one, while the dependent one already reads the referenced one through this very relationship — so the pair that most wants this check (an FK one way, a coverage check the other) is exactly the pair whose models would form a cycle. Attaching the audit to the dependent side instead adds **no edge the relationship did not already imply**. `on_fail` is `fail`/`flag` only; `quarantine` and `repair` are absent from the surface rather than lowered to something weaker. **Two emission details that are each a trap closed.** The body counts a *dependent* column, never `COUNT(*)`: a `LEFT JOIN` still produces one output row for an unmatched left row, so `COUNT(*)` answers 1 for a customer with no orders at all and the check would pass on precisely the rows it exists to find. And the dependent side is `@this_model` rather than a named relation — the macro is the one reference SQLMesh rewrites inside an AUDIT body (D29), so naming the relation resolved to the virtual layer *and* put the model into its own `depends_on`, which is how the first cut emitted it. The referenced side is a sibling and is declared in `depends_on`, the trap D40 closed for step audits. Verified by a real SQLMesh plan on a fixture added to the e2e tier for it: the comment above `step_resolution` there argues that nothing else loads SQLMesh and that the gap hid three defects in a row, and this is the same shape — an audit body joining a sibling, with a `depends_on` that exists only because of the audit. dbt refuses the project (its tests are predicates, with no grouped cross-relation form); Cube is not asked, because it builds nothing (S-0034/D-52). **Cost:** `ProjectIR` gains a field, so every fingerprint moves. **Not closed:** the check counts rows that *reached* silver, so a referenced row quarantined by its own rules reads as absent — right for "has an order", wrong for a check somebody phrases as "exists", and named here rather than discovered.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/guardrails/quality.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/lower.py` `src/bloomery/spec/entity.py` `tests/e2e/test_sqlmesh_replan.py` `tests/fixtures/coverage_check/entity_model.yaml` `tests/fixtures/dirty_corpus/entity_model.yaml` `tests/unit/test_fixtures.py`

### S-0034/D-1 — `ASSUMED` (The step registry: referenced implementations)

Four-tier ladder — DSL transform → `sql_macro` (parsed + typechecked, spliced into the SELECT, lineage-transparent) → `sql_model` (parsed, schema inferred) → `python_model` (trust + verify) — with the rule: **lowest tier that works**. Tier 3's costs (data leaves the engine, memory-bound, coarse lineage) are named, not hidden.

- Paths: `src/bloomery/ir/nodes.py`

### S-0034/D-5 — `ASSUMED` (The step registry: referenced implementations)

Determinism tiers: `pure` (freely backfillable) | `seeded` (seed required in the spec, recorded) | `nondeterministic` (**compile error**). Restatement is the organizing capability of the architecture; refusing nondeterminism is the load-bearing constraint, not conservatism.

- Paths: `src/bloomery/errors.py` `src/bloomery/ir/nodes.py` `tests/support/identity.py` `tests/unit/test_steps/test_identity_demo.py`

### S-0034/D-11 — `ASSUMED` (The step registry: referenced implementations)

Steps are IR and DAG citizens: `StepIR` nodes (ref, version, kind, determinism, `runtime_lock`, typed inputs/outputs) in a new `ProjectIR.steps` tuple (S-0020 amendment) and first-class `step.<ref>` DAG nodes (S-0022 amendment). Fingerprint coverage is the whole mechanism: any manifest change — `runtime_lock` included — shifts `project_fingerprint`; `plan()` sees an ordinary structural IR diff (no special-casing); the S-0031 hydration cache self-invalidates via `HydrationKey.spec_fingerprint`, no new key component.

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/resolve/graph.py` `tests/unit/test_plan/test_step_changes.py` `tests/unit/test_resolve/test_graph.py`

### S-0034/D-15 — `ASSUMED` (The step registry: referenced implementations)

`StepIR` additionally carries the resolved parameters (canonically sorted `(name, value)` pairs, `Decimal`-as-str per canon-bytes), the recorded seed for seeded steps, and the input/output wiring (sorted pairs) — all fingerprint-covered, so a parameter or seed change is a `RESTATING` diff exactly like a `runtime_lock` change.

- Paths: `src/bloomery/ir/nodes.py`

### S-0035/D-1 — `ASSUMED` (Public surface and stability policy)

**Signature closure** is the root-namespace rule: any type appearing in a public signature, return, generic argument, or returned-dataclass field is itself exported from `bloomery`. **Fourteen** types are added under it (§5.1), the walk stopping at handle types (decision 9). Enforced by a unit test walking `get_type_hints`, not by review — a walk that decision 10 has to make runnable first.

- Paths: `src/bloomery/__init__.py` `src/bloomery/evidence.py` `src/bloomery/ir/nodes.py` `tests/unit/test_advisories.py` `tests/unit/test_ir/test_nodes.py` `tests/unit/test_package.py` `tests/unit/test_signature_closure.py`

### S-0040/D-7 — `ASSUMED` (Temporal joins: SCD2 flattening and currency conversion)

A `type2` entity's validity-interval column names belong on `EntityIR`. Today each target names them privately, which is the mechanical reason no predicate can be emitted; naming them in the IR is what makes the two targets agree.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/ir/nodes.py` `tests/e2e/test_dbt_parse.py` `tests/unit/test_emit/test_dbt.py`

### S-0041/D-1 — `LOCKED` (Deterministic union merge)

Several mappings may target one entity; they are merged with `UNION ALL`. This replaces the refusal at `resolve/build.py:849` and keeps the promise its message makes. Consequence: `EntityIR` gains a set of source mappings where it had one, and every consumer reading "the mapping" of an entity must be revisited.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `tests/unit/test_resolve/test_build.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-3 — `LOCKED` (Deterministic union merge)

Mappings are unioned in **lexicographic order of source name**, so the emitted artifact is byte-identical across processes. Row order is explicitly **not** claimed — `UNION ALL` is a bag, and nothing downstream may depend on source order.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/ir/nodes.py` `tests/unit/test_determinism_guard.py` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_resolve/test_build.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-7 — `ASSUMED` (Deterministic union merge)

A `_source` system column carries provenance. It is load-bearing rather than diagnostic: the collision audit reports which sources collided, and without it the report is unactionable on a multi-source entity.

- Paths: `pages/docs/reference/stability.md` `src/bloomery/emit/lower/silver.py` `src/bloomery/ir/nodes.py` `src/bloomery/spec/common.py` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_steps/test_lowering.py`

### S-0041/D-17 — `ASSUMED` (Deterministic union merge)

**`bloomery_ir_version` 5 → 6.** `EntityIR` gains its source tuple, and the canonical encoder writes each dataclass's field names and count, so every fingerprint moves whether or not a project merges anything. Stated because it is exactly what went unstated at v4, where the bump was missed and only the encoder's own strictness kept it honest. `plan()` refuses to diff a v5 IR against a v6 one.

- Paths: `src/bloomery/ir/nodes.py`

### S-0041/D-26 — `ASSUMED` (Deterministic union merge)

**Answers D25 (`OPEN`) — option (a), and D25's blast-radius figure was wrong by an order of magnitude.** The lowered expression moves to a new column-grained `SourceColumnIR` on `SourceIR`; `ColumnIR` keeps the schema (§5.7). D25 said "37 `.columns` read sites" and estimated the cost from that; measured, **exactly 8 sites read a `ColumnIR` lowering field, in 3 files** — `plan/diff.py` (`renamed_from` ×4, `recipe_id`, `expr.sql`) and `emit/lower/silver.py` (`expr.ast()` ×2). Four of those eight are `renamed_from`, which D25 mis-assigned to the lowering half and which is declared on the EntityModel `Field`, so it does not move at all. The 37 was a count of `.columns` readers, and `.columns` readers are overwhelmingly *schema* readers — they survive untouched, which is the whole point of the split. **Real cost: two constructors where there was one, and four call sites.** The golden churn stands regardless — the IR shape moves and D17 bumps the version.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/operands.py` `src/bloomery/guardrails/stage.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/resolve/build.py` `src/bloomery/resolve/facets.py` `src/bloomery/resolve/steps.py` `src/bloomery/resolve/timeline.py` `tests/bench/test_hydration.py` `tests/support/ir_factory.py` `tests/support/plan_ir.py` `tests/unit/test_emit/test_cube.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_facets.py` `tests/unit/test_unresolved.py`

### S-0041/D-32 — `LOCKED` (Deterministic union merge)

**A rule's per-mapping dependency is projected as a branch-local column; the rule stays entity-grained (P2a).** The mechanism is not invented here — `coercible` already reads projected `_src_<rule>_<n>` aliases (`quality/predicates.py:source_alias`) rather than inline JSONPaths, because the raw paths live one level down in the extract SELECT, and P1 turned that projection site into `_branch_select`. So a fact only one branch knows already has a way to reach a rule the merged relation evaluates once. **D6 is not violated, and the reading that says it is — that projecting a verdict per branch just *is* "a rule evaluated per source" — mistakes what D6 argues.** D6 argues from the *row population* — "a rule evaluated per source would judge rows the merged relation does not contain" — and the union is `ALL`, so a branch-projected **scalar** verdict judges exactly the rows the union contains. Dedupe runs after the union and may drop a row; that row's flag is then unused, which is not a wrong answer. **The boundary is `WINDOWED_KINDS`** (`quality/predicates.py`, currently `{unique}`): a windowed verdict depends on the population and so may not be computed per branch — and it does not need to be, since its inputs are the produced column values, which D26's split already makes mapping-invariant. Consequence: `coercible` sheds its per-source alias set for one branch-computed boolean ("every source path *this branch* read was non-null"), which collapses the arity problem at the level where arity is known; `in_enum` takes the same shape rather than a second mechanism, its admissible set being the branch's own `enum_map` chain. **The tempting wrong fix is recorded so it is not re-proposed:** NULL-filling a missing `_src_` alias to make the arities agree renders `is_not_null` false, the conjunction never fires, and the rule silently stops checking on that branch — the failure D28 refuses by name, a check that quietly stops checking being worse than one that is absent.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/guardrails/quality.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/quality/lower.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/build.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_merged_cleaning.py` `tests/fixtures/multi_source_quality/mapping_legacy.yaml` `tests/support/quality_rules.py` `tests/unit/test_quality/test_lower.py` `tests/unit/test_quality/test_predicates.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0044/D-1 — `LOCKED` (ISO 8601 timestamps across dialects)

`{parse_ts: ISO8601}` must accept the `T` separator on every shipping dialect. The argument names a standard; a whitelisted transform that implements it on two ports of three is a defect in the transform, not a caveat for the docs.

- Paths: `examples/lakehouse/**` `src/bloomery/dialects/postgres.py` `src/bloomery/dialects/trino.py` `src/bloomery/ir/nodes.py` `src/bloomery/transforms/_builtins.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0044/D-2 — `LOCKED` (ISO 8601 timestamps across dialects)

The fix may **not** be a blanket render-time rewrite of `CAST(… AS TIMESTAMP)` on Trino. Emitted artifacts already cast operands that are timestamps and NULLs, and `REPLACE` over either is a type error, not a no-op (§2).

- Paths: `examples/lakehouse/**` `src/bloomery/dialects/postgres.py` `src/bloomery/dialects/trino.py` `src/bloomery/ir/nodes.py` `src/bloomery/transforms/_builtins.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0044/D-3 — `LOCKED` (ISO 8601 timestamps across dialects)

The fix lives in the **neutral spelling**, not at the port, because provenance does not survive the canonical-text round-trip (§3). Any option that needs the dialect to know a cast came from `parse_ts` is out.

- Paths: `examples/lakehouse/**` `src/bloomery/dialects/postgres.py` `src/bloomery/dialects/trino.py` `src/bloomery/ir/nodes.py` `src/bloomery/transforms/_builtins.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0044/D-7 — `LOCKED` (ISO 8601 timestamps across dialects)

Until this lands, the divergence is **documented, not refused**. (d) is the S-0025/D-3-pure answer and it breaks working projects to punish a bug they already routed around; the projects that hit it hit it loudly, through the `coercible` rule, not silently.

- Paths: `examples/lakehouse/**` `src/bloomery/dialects/postgres.py` `src/bloomery/dialects/trino.py` `src/bloomery/ir/nodes.py` `src/bloomery/transforms/_builtins.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-1 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A derived metric is `expr` over aliased inputs, each input a metric.** `inputs` is a mapping keyed by alias, not a list: the alias is the input's identity because `expr` references it, and a dict makes a duplicate alias unrepresentable rather than a validation. Consequence: `MetricIR` gains a `derived` field and the additivity guard must accept it as a decomposition.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/resolve/build.py` `src/bloomery/semantic/plan.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-2 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**An offset is `{window: "<count> <grain>"}` or `{to_grain: <grain>}`, exactly one.** The grain vocabulary is `day`, `week`, `month`, `quarter`, `year` — the mart's own date buckets (S-0027/D-4). `hour` is refused despite MetricFlow accepting it: the emitted time spine is day-grain, so an hourly offset would resolve against a spine that cannot express it.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-5 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**`cumulative:` is lowered, and the blanket `UnsupportedCumulative` refusal is deleted rather than narrowed.** The class goes with it: a reserved-surface error whose surface is no longer reserved is a class that can only mislead. Combinations that still cannot be lowered are refused by their own named guardrails (D7).

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/planner/semantic_plan.py` `tests/execution/test_period_over_period.py` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_planner/test_metricflow_planner.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-8 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A metric filter is a typed predicate list — `{dimension, op, values}` — and never a SQL string.** A string would be dialect-bound, unvalidatable against the column's declared type, and an injection surface in a compiler whose input may be untrusted. The list is ANDed; a disjunction is expressed as `in`.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/semantic/additivity.py` `src/bloomery/spec/common.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_semantic/test_ratio_rows.py` `tests/unit/test_spec/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-14 — `ASSUMED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**`bloomery_ir_version` 8 → 9.** `MetricIR` gains fields; the canonical encoder writes each dataclass's field names and count, so every project carrying a metric re-fingerprints whether or not it uses any of this. `plan()` refuses to diff a v8 IR against a v9 one.

- Paths: `src/bloomery/ir/nodes.py`

### S-0053/D-1 — `LOCKED` (Measure semantic types and additivity algebra)

**The aggregation vocabulary is a closed typed set, never a target-interpreted string.** `Additive`, `SemiAdditive`, `NonAdditive`, `Ratio`, `DistinctCount`, `Snapshot`. Locked because the planner, the proof rules and every emitter branch on it: an open string set makes each target the authority for what a measure means, which is the arrangement this whole sequence exists to end. Staging the *implementation* across releases is fine; encoding a future class as a string is not.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/ir/nodes.py` `src/bloomery/spec/common.py` `tests/fixtures/semantic_corpus/005-semi-additive-balance/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/005-semi-additive-balance/problem.md` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/problem.md` `tests/unit/test_guardrails/test_additivity.py` `tests/unit/test_semantic/test_rollup.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0053/D-2 — `LOCKED` (Measure semantic types and additivity algebra)

**A ratio is stored as its operands, not as a materialized quotient.** `SUM(num)/SUM(den)` and `AVG(ratio)` differ, the second is what a numeric-looking column invites, and the difference is a plausible wrong number. This is also S-0055's precondition — a derived metric spanning two branches cannot be reconstructed after the operands are gone — so reversing it later strands that document.

- Paths: `src/bloomery/emit/lower/rollups.py` `src/bloomery/errors.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/mart.py` `tests/fixtures/semantic_corpus/002-average-of-averages/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/002-average-of-averages/problem.md` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/problem.md` `tests/fixtures/semantic_corpus/008-ratio-rollup/bloomery/declared/metrics.yaml` `tests/fixtures/semantic_corpus/008-ratio-rollup/bloomery/naive/metrics.yaml` `tests/fixtures/semantic_corpus/008-ratio-rollup/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/008-ratio-rollup/problem.md` `tests/fixtures/semantic_corpus/012-rollup-recounts-identities/problem.md` `tests/unit/test_emit/test_rollups.py` `tests/unit/test_guardrails/test_additivity.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_steps/test_step_canonicals.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0053/D-8 — `LOCKED` (Measure semantic types and additivity algebra)

**A site branching on additivity tests the property it means, never the member it happened to observe.** Fifteen sites across the emitters, the planner and the guardrails read `NON_ADDITIVE`, and twelve of them meant something else — nine "never emits a measure", three "a ratio specifically" — so minting `RATIO` narrowed twelve branches at once and no test in the tree could see it. `bloomery.ir.COMPUTED` is that property under its own name, and is already complete for all six members. Locked because it is what the `RESOLVABLE` canary's promise rests on: minting `DistinctCount` or `Snapshot` is an enum edit and a lowering, not a second sweep of fifteen judgement calls (see `logs/T-0023.md` (`logs/T-0023.md`), D146).

- Paths: `src/bloomery/errors.py` `src/bloomery/ir/nodes.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0055/D-8 — `OPEN` (Multi-grain aggregate-then-join query planning)

**Whether `DistinctCount`, `Snapshot` and `SemiAdditive` enter branch planning at all in P1.** §8 gates them on their proof rules being independently sound. Decide per class, with the corpus case each one converts, rather than as a group.

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/semantic/rollup.py` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/problem.md` `tests/fixtures/semantic_corpus/012-rollup-recounts-identities/problem.md` `tests/unit/test_planner/test_coverage.py`

### S-0059/D-11 — `ASSUMED` (Loose ends inside shipped subsystems)

A `sql_model` output with no `flag` rule stays byte-identical — the flags columns are conditional on the rule, not on the tier. Accepts an asymmetry with mapped entities in exchange for leaving every existing step golden alone.

- Paths: `src/bloomery/ir/nodes.py` `tests/unit/test_steps/test_lowering.py`

### S-0059/D-12 — `LOCKED` (Loose ends inside shipped subsystems)

`EntityIR` gains no field. `carries_quality_flags` is derived from `produced_by` and the rule dispositions, because a new IR field moves every fingerprint in the corpus — including projects that wire no steps.

- Paths: `src/bloomery/ir/nodes.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0061/D-1 — `LOCKED` (The SQLMesh project file)

bloomery emits `config.yaml` with `model_defaults` and **never** a `gateways:` block. The dbt precedent is not an analogy but the same rule: `dbt_project.yml` is emitted, `profiles.yml` is not, because a connection carries hosts and credentials and the compiler reads no environment. M2 measures that SQLMesh accepts the split.

- Paths: `examples/targets/run.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0061/D-3 — `LOCKED` (The SQLMesh project file)

`start` is **derived**, never a new spec key. The catalog's date dimension already states the project's temporal extent; a second declaration of one fact is two declarations that will disagree.

- Paths: `examples/targets/run.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0062/D-12 — `ASSUMED` (Ownership, classification and grants)

A rollup declares its own `grants:` and does not inherit its parent mart's — D2's rule, applied to the one authored node that had no audience of its own. A rollup declaring none is the advisory of row 11 rather than a hole.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/spec/marts.py`

### S-0063/D-1 — `LOCKED` (Exposures and downstream consumers)

Exposures are **declared**, never discovered. Discovery needs a network and credentials; S-0020 forbids both, and a compiler that reads a BI tool is a different program.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/guardrails/lineage.py` `src/bloomery/ir/nodes.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0063/D-3 — `ASSUMED` (Exposures and downstream consumers)

`kind` uses dbt's **vocabulary** verbatim — `dashboard`, `notebook`, `analysis`, `ml`, `application`, measured against dbt's own schema. It does not follow that the *document* is dbt's: the emitted form spells `type`, takes an owner object and a flat `depends_on`, and §5.1 states both shapes so the emitter phase is not deciding it.

- Paths: `src/bloomery/ir/nodes.py`

### S-0063/D-6 — `ASSUMED` (Exposures and downstream consumers)

`url:` is text. It is never fetched, never validated beyond being a string, and its correctness is the author's.

- Paths: `src/bloomery/ir/nodes.py`

### S-0067/D-1 — `LOCKED` (Stable node identity across renames)

Identity is declared, never inferred. No similarity heuristic over names, SQL or column sets decides that two nodes are the same node; a wrong guess here rewrites history rather than raising an error.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/guardrails/lineage.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/model.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0069/D-1 — `LOCKED` (Definition supersession and change attribution)

The delta is stated in spec vocabulary, never as a text diff of emitted SQL. A reader who has to decide which textual differences are semantic is doing the compiler's job.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/guardrails/lineage.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/model.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0069/D-2 — `LOCKED` (Definition supersession and change attribution)

Superseded versions are related, never overwritten. History that replaces cannot answer the question the feature exists for.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/guardrails/lineage.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/model.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0069/D-3 — `LOCKED` (Definition supersession and change attribution)

The compiler never attributes a change to data. "No definition change" is the complete and correct answer when the definition did not change.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/guardrails/lineage.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/model.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0072/D-3 — `LOCKED` (Marts in the lineage graph)

Follows from row 2, and stated separately because it is the thing an executor will be tempted to add: **no per-column `entity_field → mart` edge**. The consequence is stated in §9 and not mitigated: a mart dimension no metric reads is not reached by a downstream walk.

- Paths: `src/bloomery/guardrails/lineage.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/graph.py` `src/bloomery/resolve/resolution.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0072/D-4 — `LOCKED` (Marts in the lineage graph)

`mart` joins `NODE_ID_PREFIXES` and the entity-name reservation, with a `_MINTS` row. A rule that held for five prefixes of six would be learned as a list of exceptions, which is S-0059/D-7's argument unchanged.

- Paths: `src/bloomery/guardrails/lineage.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/graph.py` `src/bloomery/resolve/resolution.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0077/D-1 — `LOCKED` (A ratio over one row set)

**bloomery does not choose which rows a ratio is about.** Both readings — per unit over units that exist, and total over units with overheads included — are metrics somebody wants, and the defect is that they are spelled identically. The rule refuses until the author says; it never picks. Locked because every cheaper design is a compiler making a decision about somebody's business, and the wrong one is invisible in the output.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/semantic/additivity.py` `src/bloomery/spec/quality.py` `tests/fixtures/semantic_corpus/008-ratio-rollup/**` `tests/fixtures/semantic_corpus/009-null-denominator/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0077/D-2 — `LOCKED` (A ratio over one row set)

**The inclusive reading stays reachable and is spelled out loud.** Without it the rule reduces to "exclude zero rows", which is D1 reversed with extra steps: an author who means `4.00` must be able to say so, and be seen to have said so.

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/spec/common.py` `tests/fixtures/semantic_corpus/009-null-denominator/bloomery/inclusive/metrics.yaml`
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

### S-0079/D-1 — `LOCKED` (Determinations reach the IR and the rollup lowering)

A determination is a **stored** fact. `ColumnIR` gains `determines: tuple[str, ...]`, filled by `_column_ir` from the entity model's `Field.determines` and carried unchanged, the way `classification` is. It is authored, it appears in no other IR field, and no compile can recover it without re-reading the spec

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py`
- Consequence: S-0017/D-9 keeps the grain model out of the IR because a grain is computed from `EntityIR.key`, which the IR holds; that reasoning does not reach a determination and may not be cited to keep one out. The IR stores what an author wrote and derives what follows from it, which is the line D-4 stands on the other side of
- Check: `uv run pytest tests/unit/test_resolve/test_build.py -q` (shadow; runs as `decision:S-0079/D-1`, no log entry owed)

### S-0079/D-2 — `LOCKED` (Determinations reach the IR and the rollup lowering)

`bloomery_ir_version` moves 19 → 20 with the field, and `ProjectIR`'s docstring gains the sentence saying why. The default of `()` is not a reason to skip it: the canonical encoder writes each dataclass's field count and names per instance, so every project with an entity column re-fingerprints whether or not it declares anything

- Paths: `src/bloomery/ir/nodes.py` `tests/unit/test_ir/**`
- Consequence: Every project's fingerprint moves and `plan()` refuses to diff a version 19 IR against a version 20 one, which is the refusal that makes the change loud. The version is declared once, on the dataclass — `test_the_compiler_emits_the_declared_ir_version` is what stops it being bumped in one of two places
- Check: `uv run pytest tests/unit/test_ir/test_nodes.py tests/unit/test_determinism_guard.py -q` (shadow; runs as `decision:S-0079/D-2`, no log entry owed)

### S-0079/D-9 — `ASSUMED` (Determinations reach the IR and the rollup lowering)

`determines` is appended to `ColumnIR` with a default of `()`, and the two other construction sites — `_shadow_column` in `src/bloomery/guardrails/conflict.py` and the step-output loop in `src/bloomery/resolve/steps.py` — are left untouched

- Paths: `src/bloomery/ir/nodes.py`
- Consequence: A merge shadow and a step output carry no determination, and that is the answer rather than an omission: a shadow is a second projection of a column that already carries the declaration, and a step output has no entity-model field to read one from. Neither file is in either phase's scope, and neither needs to be

### S-0079/D-10 — `OPEN` (Determinations reach the IR and the rollup lowering)

Whether the mart-namespace determination is also worth carrying onto `MartColumnIR` for the spec differ's impact report. This document stores it only on `ColumnIR` and derives the rest; the impact report S-0007 names has not been designed, and the shape it wants is not knowable yet. The executor adds nothing for it here and logs the decision if building proves otherwise

- Paths: `src/bloomery/ir/nodes.py`
- Consequence: Answering it later is additive and costs another version bump; answering it now would store a derived fact against D-4 on the strength of a consumer nobody has written

## Invariants holding over `src/bloomery/ir/`

- **S-0079/I-1**: The IR version is declared once, on the dataclass, and every project's fingerprint is stable across processes and `PYTHONHASHSEED` values
  - Paths: `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py`
  - Check: `uv run pytest tests/unit/test_ir tests/unit/test_determinism_guard.py -q`
- **S-0079/I-2**: No IR node carries a mapping; the canonical encoder writes `None`, `bool`, `Enum`, `int`, `str`, `Decimal`, tuples and frozen dataclasses, and raises on anything else
  - Paths: `src/bloomery/ir/nodes.py` `src/bloomery/marts/rollup.py`
  - Check: `uv run pytest tests/unit/test_ir/test_fingerprint.py -q`

<!-- /torve:managed -->
