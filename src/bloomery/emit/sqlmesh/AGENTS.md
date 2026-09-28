<!-- torve:managed src/bloomery/emit/sqlmesh — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/emit/sqlmesh/`

### S-0003/D-1 — `LOCKED` (Replay on a historical entity)

bloomery computes no framework's SCD bookkeeping: no snapshot identity, no validity interval and no strategy hash is written or guessed anywhere on the replay path

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/sqlmesh/__init__.py`
- Consequence: dbt's `dbt_scd_id` is a hash over its own unique key and check columns, computed in its own macros; a guess that is wrong produces duplicate versions rather than an error, and a guess that is right makes this compiler an implementation of another framework's internals — which is the coupling the lowering layer exists to prevent
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0003/D-9 — `ASSUMED` (Replay on a historical entity)

The two targets fail the old merge differently: on dbt it lands silently with a NULL interval, and on SQLMesh it does not land at all — the entity is a view over a physical snapshot table and the write is refused outright by the engine

- Paths: `src/bloomery/emit/sqlmesh/__init__.py` `tools/spikes/rfc0060_sqlmesh.py`
- Consequence: Nothing about the refusal changes — the pair was refused either way, for a reason that holds on both — but a claim that both targets fail silently is not true, and a reader's sense of how urgent this is should follow the loud failure rather than the quiet one

### S-0023/D-7 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Path conflict does not raise (`PathConflict` is not an error class): the compiler emits the derived column, a `<name>__direct` shadow, and a `RECONCILE` `AuditIR`. The forbidden thing is the silent choice; both paths are valid, so the refusal targets the silence, not the spec.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/quality.py` `src/bloomery/ir/lower.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/mapping.py` `tests/fixtures/path_conflict/entity_model.yaml` `tests/fixtures/path_conflict/mapping.yaml` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_ir/test_lower.py` `tests/unit/test_spec/test_mapping.py`

### S-0025/D-3 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Capability mismatch behavior is fail-loud: `UnsupportedByTarget` naming entity + feature. Silent degradation is forbidden.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/spec/quality.py` `src/bloomery/transforms/_builtins.py` `tests/property/test_compile_properties.py` `tests/unit/test_emit/test_base.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_quality/test_text_rules.py` `tests/unit/test_transforms/test_builtins.py`

### S-0025/D-4 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

SQL rendering: SQLGlot AST → `DialectPort.render`; Jinja only ever sees pre-rendered strings (envelope templating).

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/emit/steps.py` `tests/property/test_compile_properties.py` `tests/unit/test_steps/test_dbt_and_cube_emission.py`

### S-0025/D-9 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Every artifact carries a header comment with the project fingerprint — applied-vs-spec drift detection downstream.

- Paths: `src/bloomery/emit/base.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/emit/sqlmesh/__init__.py`

### S-0025/D-11 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

(Amended, S-0027) The SQLMesh emitter also builds marts: one gold-layer model per `MartIR`, the only join-emitting path for marts.

- Paths: `src/bloomery/emit/lower/marts.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py` `tests/unit/test_emit/test_sqlmesh.py`

### S-0025/D-13 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

(Reverses D6) Bloomery owns the date dimension: one catalog definition emits both the SQLMesh `gold.dim_date` model and the MetricFlow time-spine declaration (S-0030 R1). D6's demand-gate is satisfied — MetricFlow is the demand.

- Paths: `src/bloomery/emit/lower/marts.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/metrics.py` `tests/execution/test_marts.py` `tests/fixtures/ecom_basic/catalog.yaml` `tests/golden/schema/catalog.json` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_fixtures.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_metrics.py`

### S-0027/D-2 — `ASSUMED` (Marts and role-playing dimensions)

Measure grain must strictly equal mart grain; coarser or finer is `GrainViolation`. Resolves D2's prose/example contradiction to the strict reading; relaxation is a future additive change.

- Paths: `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/semantic/proof.py` `src/bloomery/semantic/rollup.py` `tests/fixtures/fanout_trap/marts.yaml` `tests/fixtures/fanout_trap/metrics.yaml` `tests/fixtures/semantic_corpus/001-order-shipping-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/001-order-shipping-fanout/problem.md` `tests/fixtures/semantic_corpus/010-many-to-many-bridge/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/010-many-to-many-bridge/problem.md` `tests/golden/refusals/example-wrong-grain.txt` `tests/golden/refusals/fanout_trap.txt` `tests/support/semantic_corpus.py` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_semantic_corpus_guard.py`

### S-0033/D-18 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Disposition precedence for a row failing multiple rules — severity order `fail > quarantine > flag`: any failing `fail` rule stops the run (blocking audit); else any failing `quarantine` rule diverts the row, with **all** failed rule names recorded in the reject's `failed_rules` (flag-level failures included); else flags accumulate in `_quality_flags`. Deterministic for every combination — no compile-time rejection of rule/disposition combinations needed.

- Paths: `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/quality/catalogue.py` `src/bloomery/quality/predicates.py` `tests/e2e/test_sqlmesh_replan.py` `tests/execution/test_quality_precedence.py` `tests/fixtures/quality_precedence/entity_model.yaml` `tests/support/precedence.py` `tests/unit/test_quality/test_predicates.py`

### S-0033/D-21 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Ingestion metadata contract: entities using `quarantine` or `dedupe` require bronze `_load_id`, `_ingested_at`, `_source_row_id` (a stable per-source-row identity supplied by the ingestion layer, **NOT NULL and unique per source row** — data properties no compiler can check, so the lowering emits a generated **blocking audit** on the metadata columns: a null or duplicated `_source_row_id` stops the run); column absence is the new compile error `IngestionMetadataMissing` (`GuardrailError` leaf, `errors.py` per S-0019/D-3). `reject_id` = sha256 over the length-prefixed utf-8 **pair** (`source_relation`, `_source_row_id`) — canonical serialization per the S-0020 canon-bytes doctrine. This supersedes the triple this row first carried (this round's own earlier decision): `_load_id` is removed from the identity and becomes an attribute (the latest observing load) — re-deliveries of the same source row across loads must land on the **same** reject row (that is what `first_seen`/`last_seen` track); a per-load identity would mint a new row per retry and violate replay idempotence. A re-delivery updates `last_seen`/`_load_id`/`failed_rules` on the existing row.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/quality.py` `src/bloomery/quality/catalogue.py` `src/bloomery/quality/dedupe.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/transforms/_builtins.py` `tests/e2e/test_dbt_parse.py` `tests/e2e/test_sqlmesh_project.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_dedupe_and_audits.py` `tests/execution/test_merged_cleaning.py` `tests/execution/test_zoneless_utc.py` `tests/fixtures/dirty/README.md` `tests/fixtures/semi_additive_inventory/mapping.yaml` `tests/support/execution.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_trino.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_entity.py`

### S-0033/D-89 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **Mart-level checks are assertions, not quality rules. §10's open question is settled by the disposition model.** §8 deferred them as "blurs into reconciliation" and §10 asked "reconcile-shaped or new surface?" — the answer is neither, and what decides it is not taste. §5.9 draws the boundary at what a verdict *does*: a quality rule disposes of a **row**. A mart row is derived — no `_source_row_id`, no bronze payload, no reject table, no replay — so there is nothing to quarantine, nothing to repair, and nothing to bring back; and a `reconcile` compares *two sides*, which "no month has zero revenue" is not. What is left is D4's other half, "alert me", so `assert:` on a mart declares `{measure, agg, by, min/max, on_fail}` and lowers to an audit the mart model names. `quarantine` and `repair` are absent from its `on_fail` rather than lowered to something weaker, so an author who wanted routing learns it at the surface instead of from a mart that silently only alerts; `fail`/`flag` map to blocking/non-blocking exactly as `reconcile.on_fail` does (D38). The aggregate vocabulary is deliberately the *same tuple* the reconcile grammar uses — both compute one number over a column so a human can be told it is wrong, and two lists that mean the same thing drift. Bounds ride in `params` as text through the D57 carrier, for the same reason. **Resolution is against the flattened column set**, not the base entity's: `ordered_month` exists only because a `date:` step made it, and it is precisely the column §10's example groups by. **The body** is `SELECT <by…>, <agg>(<measure>) FROM @this_model [GROUP BY <by…>] HAVING <bound comparison>` — the value beside the group, because a failure a human must open the warehouse to understand gets ignored. A bare `HAVING` with no `GROUP BY` is the whole-mart form; both shapes were executed on DuckDB, postgres 16 and `trinodb/trino:483` rather than read out of three manuals, and all three agree. **What it cannot see, stated rather than implied:** D19 reaches the mart, so every aggregate but `count` is NULL over an empty group and the assertion stays silent — which is also why an assertion cannot notice a month that is *entirely missing*: no row means no group at all. `count` is the exception and is the one shape that catches an empty mart. Closing the missing-period case needs a join against the date spine, a coverage check with its own dependency, and it is named here rather than half-built. **dbt refuses a project carrying one**, sharing `refuse_steps`' message shape (**amended by D94**: this row said "dbt and Cube", and the Cube half was already obsolete when it was written — S-0034/D-52 had split the blanket Cube refusal on the argument that Cube builds no relation for anything, and Cube compiles the *entire* quality surface, quarantine and reject tables included, without a murmur; refusing this one check would single it out): neither has the audit form, and compiling clean while the declared gate does not exist is the failure D83 caught in the dialect ports. **Cost recorded:** `MartIR` gains a field, and the canonical encoder covers each node's field *names and count*, so every fingerprint in the corpus moves — the churn §12 budgets, spent deliberately. The fixture carrying the demonstration is `quality_precedence` rather than `ecom_basic`, because an assertion makes a project uncompilable for two targets and `ecom_basic` is the fixture those targets' goldens are built on.

- Paths: `src/bloomery/emit/base.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/marts/flatten.py` `src/bloomery/spec/marts.py` `tests/execution/test_quality_precedence.py` `tests/fixtures/quality_precedence/marts.yaml` `tests/golden/schema/marts.json`

### S-0033/D-90 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **Cross-entity checks are `coverage:` on a relationship, and the audit hangs off the *dependent* side. §10's last open question is settled.** §10 guessed "probably reconcile-style"; it is not, and the reason is structural rather than stylistic. A `reconcile` compares two **values** and alerts beyond a tolerance — there is no right-hand value on the referenced entity to compare against, and `right: 1` is neither a shape the closed grammar admits nor one it should grow. This asserts **existence**: every row of a relationship's referenced entity has at least `min` rows referencing it. That makes it the mirror of `referential`, which asks whether every *dependent* row has a parent, and both read the same two relations through the same `via` pairs — which is why it is declared on the **relationship** rather than on either entity. **Why an audit, when a disposition would have been meaningful.** Unlike a mart row (D89), a childless customer is a real silver row with a source identity, a reject table and a replay path, so routing it is not nonsense. It is still an audit, for a reason that only shows up in the DAG: routing would need the *referenced* entity's model to read the *dependent* one, while the dependent one already reads the referenced one through this very relationship — so the pair that most wants this check (an FK one way, a coverage check the other) is exactly the pair whose models would form a cycle. Attaching the audit to the dependent side instead adds **no edge the relationship did not already imply**. `on_fail` is `fail`/`flag` only; `quarantine` and `repair` are absent from the surface rather than lowered to something weaker. **Two emission details that are each a trap closed.** The body counts a *dependent* column, never `COUNT(*)`: a `LEFT JOIN` still produces one output row for an unmatched left row, so `COUNT(*)` answers 1 for a customer with no orders at all and the check would pass on precisely the rows it exists to find. And the dependent side is `@this_model` rather than a named relation — the macro is the one reference SQLMesh rewrites inside an AUDIT body (D29), so naming the relation resolved to the virtual layer *and* put the model into its own `depends_on`, which is how the first cut emitted it. The referenced side is a sibling and is declared in `depends_on`, the trap D40 closed for step audits. Verified by a real SQLMesh plan on a fixture added to the e2e tier for it: the comment above `step_resolution` there argues that nothing else loads SQLMesh and that the gap hid three defects in a row, and this is the same shape — an audit body joining a sibling, with a `depends_on` that exists only because of the audit. dbt refuses the project (its tests are predicates, with no grouped cross-relation form); Cube is not asked, because it builds nothing (S-0034/D-52). **Cost:** `ProjectIR` gains a field, so every fingerprint moves. **Not closed:** the check counts rows that *reached* silver, so a referenced row quarantined by its own rules reads as absent — right for "has an order", wrong for a check somebody phrases as "exists", and named here rather than discovered.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/guardrails/quality.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/lower.py` `src/bloomery/spec/entity.py` `tests/e2e/test_sqlmesh_replan.py` `tests/fixtures/coverage_check/entity_model.yaml` `tests/fixtures/dirty_corpus/entity_model.yaml` `tests/unit/test_fixtures.py`

### S-0041/D-34 — `LOCKED` (Deterministic union merge)

**Artifact shape varies with mapping count; `_source` stays merged-only (P2b).** The question D7 and D15 both defer, answered once for the provenance column, the metadata audit body and the collision audit together. The metadata audit becomes `PARTITION BY _source, _source_row_id` on a merged entity and stays `PARTITION BY _source_row_id` elsewhere. **The cost is a new precedent, stated here rather than discovered later:** until now the *set* of emitted artifacts varied with a spec, never a generated **body**. The alternative — `_source` on every entity, one uniform audit body, mapping count invisible in the artifacts — buys a reader the property that a merged entity looks like any other, and costs a corpus-wide golden re-stamp plus a constant column on every single-source silver model, which is precisely what D9 declined to pay on measured grounds. Continuing that decision is cheaper than reversing it, and reversing it buys nothing but uniformity. **A third option is named only to close it:** making `_source_row_id` globally unique in bronze would dissolve the question, and it does so by relocating the problem into S-0033/D-21's ingestion contract and breaking every table already landed under it.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_merged_cleaning.py` `tests/golden/test_sqlmesh_dialects.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0043/D-5 — `LOCKED` (The dbt singular-test surface)

**The model reference goes through `_reference_map`, never string formatting.** It is what makes a singular test a DAG participant rather than a query that happens to name a table, and it is already built for exactly this shape. Consequence: a singular test is ordered against its model by dbt, which is what makes "blocking" mean anything at all under D2.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/emit/steps.py`
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

### S-0061/D-1 — `LOCKED` (The SQLMesh project file)

bloomery emits `config.yaml` with `model_defaults` and **never** a `gateways:` block. The dbt precedent is not an analogy but the same rule: `dbt_project.yml` is emitted, `profiles.yml` is not, because a connection carries hosts and credentials and the compiler reads no environment. M2 measures that SQLMesh accepts the split.

- Paths: `examples/targets/run.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0061/D-3 — `LOCKED` (The SQLMesh project file)

`start` is **derived**, never a new spec key. The catalog's date dimension already states the project's temporal extent; a second declaration of one fact is two declarations that will disagree.

- Paths: `examples/targets/run.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0062/D-8 — `ASSUMED` (Ownership, classification and grants)

No spelling rule on `owner`. Every project spells this differently and a format check would refuse spellings correct for their reader.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/sqlmesh/__init__.py`

### S-0065/D-5 — `LOCKED` (Rollup marts and pre-aggregations)

An unprovable rollup is **refused**, never warned about. A rollup is read instead of the detail table, so a wrong one answers quickly and plausibly — the class this project refuses rather than approximates.

- Paths: `src/bloomery/cli/render.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/evidence.py` `src/bloomery/guardrails/stage.py` `src/bloomery/marts/rollup.py` `src/bloomery/semantic/rollup.py` `tests/fixtures/semantic_corpus/012-rollup-recounts-identities/problem.md` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
