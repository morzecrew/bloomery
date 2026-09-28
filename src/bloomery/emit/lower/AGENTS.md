<!-- torve:managed src/bloomery/emit/lower — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/emit/lower/`

### S-0003/D-1 — `LOCKED` (Replay on a historical entity)

bloomery computes no framework's SCD bookkeeping: no snapshot identity, no validity interval and no strategy hash is written or guessed anywhere on the replay path

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/sqlmesh/__init__.py`
- Consequence: dbt's `dbt_scd_id` is a hash over its own unique key and check columns, computed in its own macros; a guess that is wrong produces duplicate versions rather than an error, and a guess that is right makes this compiler an implementation of another framework's internals — which is the coupling the lowering layer exists to prevent
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0003/D-2 — `LOCKED` (Replay on a historical entity)

A recovered row reaches the entity through whatever produces the entity's versions, so the framework does the versioning it owns; nothing on the replay path writes to a `scd: type2` entity relation

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/resolve/build.py`
- Consequence: Writing past the framework is exactly what the shipped defect did, and it reported success — the admitted version carried a NULL interval and no snapshot identity, so the row was present, queryable and invisible to every as-of join
- Check: `uv run pytest tests/unit/test_emit/test_quality_artifacts.py -q -k replay_on_a_historical_entity` (shadow; runs as `decision:S-0003/D-2`, no log entry owed)

### S-0003/D-4 — `ASSUMED` (Replay on a historical entity)

Replay for `scd: type1` entities does not change: its relation is one bloomery's own SELECT defines, so the merge naming every column is correct there

- Paths: `src/bloomery/emit/lower/silver.py`
- Consequence: A shared rewrite would put the branch nobody needs in the path everybody takes; every type 1 fixture already exercises the merge
- Check: `uv run pytest tests/unit/test_emit/test_quality_artifacts.py -q -k replay_on_a_type_one_entity` (shadow; runs as `decision:S-0003/D-4`, no log entry owed)

### S-0003/D-7 — `ASSUMED` (Replay on a historical entity)

The route is a write back to bronze: replay re-delivers the recovered row to the bronze relation it came from, as a new delivery, and the ordinary pipeline admits it — no new relation, no change to the entity's SELECT

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/resolve/build.py` `pages/docs/concepts/data-quality.md`
- Consequence: The versioning, the audits and the conservation law hold by construction, because the row arrives through the path every other row arrives through; the cost is that bloomery now emits a statement that writes into the caller's landing zone

### S-0003/D-8 — `LOCKED` (Replay on a historical entity)

A recovered version's validity interval is whatever the framework assigns, and bloomery neither chooses nor supplies it

- Paths: `src/bloomery/emit/lower/silver.py`
- Consequence: Measured on both targets: dbt stamps its own wall clock on every version, and SQLMesh stamps an epoch start for an initial load and the run's execution time thereafter. Neither offers a caller-supplied value and the two disagree about the same first load, so choosing would mean computing a framework's bookkeeping
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0003/D-10 — `ASSUMED` (Replay on a historical entity)

A correction arriving by this route adds a version and closes the previous one; it does not rewrite history

- Paths: `src/bloomery/emit/lower/silver.py` `tools/spikes/rfc0060_dbt.py`
- Consequence: Measured on both targets by changing an existing row's value in bronze and re-running: each closes the standing version, opens a new one and retains the old. Routing through the framework means taking the framework's answer, so the question is answered by the route rather than chosen

### S-0019/D-7 — `ASSUMED` (Spec layer and error model)

`materialization` is explicit-with-derived-default (settles original open question #4); the resolved value is IR-recorded and diffable.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/ir/nodes.py` `src/bloomery/marts/flatten.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/entity.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_entity.py`

### S-0020/D-2 — `ASSUMED` (Intermediate representation and determinism contract)

SQL is stored in the IR as canonical dialect-neutral SQLGlot text (`SqlExpr`), re-parsed at emit. Consequence: SQLGlot version changes can change fingerprints; the exact pin (D4 §5.5) makes that a deliberate event.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/emit/lower/marts.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `src/bloomery/transforms/_builtins.py` `tests/support/type_conformance.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_postgres.py` `tests/unit/test_transforms/test_builtins.py` `tests/unit/test_transforms/test_type_conformance_corpus.py`

### S-0020/D-5 — `ASSUMED` (Intermediate representation and determinism contract)

Floats are banned in IR and emission; `Decimal`/int only.

- Paths: `src/bloomery/cli/serialize.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/steps.py` `src/bloomery/ir/fingerprint.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/request.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/common.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `src/bloomery/steps/manifest.py` `src/bloomery/steps/splice.py` `src/bloomery/transforms/_builtins.py` `src/bloomery/typing/types.py` `tests/execution/test_as_of_join.py` `tests/execution/test_currency_convert.py` `tests/execution/test_fanout_trap.py` `tests/execution/test_marts.py` `tests/execution/test_period_over_period.py` `tests/execution/test_rollup.py` `tests/fixtures/semantic_corpus/002-average-of-averages/naive.sql` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/golden/schema/marts.json` `tests/support/planning.py` `tests/support/semantic_corpus.py` `tests/unit/test_cli.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_planner/test_request.py` `tests/unit/test_quality/test_edges.py` `tests/unit/test_spec/test_metrics.py` `tests/unit/test_spec/test_quality.py` `tests/unit/test_steps/test_lowering.py` `tests/unit/test_steps/test_manifest_and_registry.py` `tests/unit/test_typing/test_types.py`

### S-0023/D-7 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Path conflict does not raise (`PathConflict` is not an error class): the compiler emits the derived column, a `<name>__direct` shadow, and a `RECONCILE` `AuditIR`. The forbidden thing is the silent choice; both paths are valid, so the refusal targets the silence, not the spec.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/quality.py` `src/bloomery/ir/lower.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/mapping.py` `tests/fixtures/path_conflict/entity_model.yaml` `tests/fixtures/path_conflict/mapping.yaml` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_ir/test_lower.py` `tests/unit/test_spec/test_mapping.py`

### S-0025/D-1 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Three independent ports (`TargetEmitter`, `DialectPort`, `NamingPolicy`), all `Protocol`s. Target and dialect never collapse into one adapter.

- Paths: `src/bloomery/dialects/__init__.py` `src/bloomery/dialects/base.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/naming.py` `src/bloomery/quality/flags.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_postgres.py`

### S-0025/D-3 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Capability mismatch behavior is fail-loud: `UnsupportedByTarget` naming entity + feature. Silent degradation is forbidden.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/spec/quality.py` `src/bloomery/transforms/_builtins.py` `tests/property/test_compile_properties.py` `tests/unit/test_emit/test_base.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_quality/test_text_rules.py` `tests/unit/test_transforms/test_builtins.py`

### S-0025/D-4 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

SQL rendering: SQLGlot AST → `DialectPort.render`; Jinja only ever sees pre-rendered strings (envelope templating).

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/emit/steps.py` `tests/property/test_compile_properties.py` `tests/unit/test_steps/test_dbt_and_cube_emission.py`

### S-0025/D-11 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

(Amended, S-0027) The SQLMesh emitter also builds marts: one gold-layer model per `MartIR`, the only join-emitting path for marts.

- Paths: `src/bloomery/emit/lower/marts.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py` `tests/unit/test_emit/test_sqlmesh.py`

### S-0025/D-13 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

(Reverses D6) Bloomery owns the date dimension: one catalog definition emits both the SQLMesh `gold.dim_date` model and the MetricFlow time-spine declaration (S-0030 R1). D6's demand-gate is satisfied — MetricFlow is the demand.

- Paths: `src/bloomery/emit/lower/marts.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/metrics.py` `tests/execution/test_marts.py` `tests/fixtures/ecom_basic/catalog.yaml` `tests/golden/schema/catalog.json` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_fixtures.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_metrics.py`

### S-0027/D-4 — `ASSUMED` (Marts and role-playing dimensions)

Date roles expand to exactly `{day, week, month, quarter, year}` bucket columns named `<role>_<bucket>`; `hour` is deliberately not expanded.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/lower/marts.py` `src/bloomery/marts/flatten.py` `src/bloomery/planner/coverage.py` `src/bloomery/planner/request.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `tests/golden/schema/marts.json`

### S-0027/D-8 — `ASSUMED` (Marts and role-playing dimensions)

`cost_hint` (int, default 1) is a tie-breaking scan-cost hint only; selection ties break lexicographically (S-0020 determinism).

- Paths: `src/bloomery/emit/lower/marts.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/spec/marts.py` `tests/golden/schema/marts.json` `tests/unit/test_emit/test_metricflow.py` `tests/unit/test_planner/test_coverage.py`

### S-0033/D-10 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

One `<entity>__reject` table per entity with the §5.6 schema (stable sha256 `reject_id` for idempotent replay). Retention is **required** whenever any quarantine disposition exists — missing retention is a compile error; retention deletes **all** reject rows on expiry (unresolved measured from `last_seen`, resolved from `resolved_at`) and is the only deleter — replay never deletes. `redact:` paths apply at write time and must not intersect any path the entity's mappings read (`from` paths, recipe aliases included) — an intersecting redact is the compile error `RedactionConflict`. Bloomery emits the reject/replay artifacts and never executes them.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/errors.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `tests/engines/test_merged_cleaning_engines.py` `tests/fixtures/multi_source_quality/entity_model.yaml` `tests/unit/test_guardrails/test_quality.py`

### S-0033/D-21 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Ingestion metadata contract: entities using `quarantine` or `dedupe` require bronze `_load_id`, `_ingested_at`, `_source_row_id` (a stable per-source-row identity supplied by the ingestion layer, **NOT NULL and unique per source row** — data properties no compiler can check, so the lowering emits a generated **blocking audit** on the metadata columns: a null or duplicated `_source_row_id` stops the run); column absence is the new compile error `IngestionMetadataMissing` (`GuardrailError` leaf, `errors.py` per S-0019/D-3). `reject_id` = sha256 over the length-prefixed utf-8 **pair** (`source_relation`, `_source_row_id`) — canonical serialization per the S-0020 canon-bytes doctrine. This supersedes the triple this row first carried (this round's own earlier decision): `_load_id` is removed from the identity and becomes an attribute (the latest observing load) — re-deliveries of the same source row across loads must land on the **same** reject row (that is what `first_seen`/`last_seen` track); a per-load identity would mint a new row per retry and violate replay idempotence. A re-delivery updates `last_seen`/`_load_id`/`failed_rules` on the existing row.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/quality.py` `src/bloomery/quality/catalogue.py` `src/bloomery/quality/dedupe.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/transforms/_builtins.py` `tests/e2e/test_dbt_parse.py` `tests/e2e/test_sqlmesh_project.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_dedupe_and_audits.py` `tests/execution/test_merged_cleaning.py` `tests/execution/test_zoneless_utc.py` `tests/fixtures/dirty/README.md` `tests/fixtures/semi_additive_inventory/mapping.yaml` `tests/support/execution.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_trino.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_entity.py`

### S-0033/D-22 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Replay merge semantics: replay applies the **same dedupe ordering** as the pipeline — a replayed candidate merges by entity key and wins/loses against an incumbent by the dedupe total order (recency, tie-breaks, `_source_row_id`); multiple rejects resolving to one key are ordered the same way. The per-entity replay batch is one atomic MERGE (transactionality is the executing engine's; bloomery emits the artifact); idempotence follows from the total order — re-running replay re-derives the same winners — and is defined over **semantic state** (winners merged, `resolved_at` transitions), observability columns excluded: `last_seen` updates only when a row is actually re-evaluated.

- Paths: `src/bloomery/emit/lower/silver.py` `tests/execution/test_quality_precedence.py` `tests/execution/test_replay_to_bronze.py` `tests/fixtures/quality_precedence/entity_model.yaml` `tests/support/precedence.py`

### S-0033/D-24 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12)* **The implicit `coercible` rule is opt-in per entity**, diverging from §5.2's "implicit, always present". An entity joins the quality system by declaring `quality:`, `quarantine:`, or any field-level `quality:`; `dedupe:` alone does not. Rationale: applying it universally gives every field in every existing project a `quarantine` disposition, which makes every project fail `QuarantineRetentionMissing` on its next compile — a break §12 budgets for `_quality_flags`'s schema churn but not for a hard compile refusal. Consequence: a project that wants coercion routing must opt in explicitly, and an entity with no quality surface keeps the shipped produce-or-raise transform lowering.

- Paths: `src/bloomery/emit/lower/silver.py`

### S-0033/D-25 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12)* **The ingestion-metadata columns carry no `coercible` rule, and the D21 audit must close the gap.** D6 forces `coercible` to `fail` on any field the dedupe order reads, but `_ingested_at`/`_load_id`/`_source_row_id` are ingestion metadata, not mapped fields — no rule is generated for them, and the D21 blocking audit asserts only that `_source_row_id` is non-null and unique. An uncastable `_ingested_at` therefore survives with dedupe ordering silently undefined. **Decided contract:** the D21 audit additionally asserts `_ingested_at` is castable to timestamp, blocking the run when it is not. Unimplemented as of M12 and held open by a strict-`xfail` execution test (`keys.csv::uncastable_ingested_at`) rather than a comment.

- Paths: `src/bloomery/emit/lower/silver.py`

### S-0033/D-30 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12; closed by D84)* **Postgres cannot host quality-carrying entities.** `coercible` needs a real NULL-on-failure cast (`DialectFeature.TRY_CAST`); sqlglot renders `TRY_CAST` on Postgres as a plain `CAST`, which aborts the run instead of marking the row, so the dialect declares the feature gap and compiling a quality-carrying entity for it raises `UnsupportedByTarget` — loud, never a silent degradation into an aborted run. Consequence for §6's dialect matrix: there is no Postgres dirty-corpus tier to add until either sqlglot renders a real `TRY_CAST` or the lowering grows a per-type `CASE`-based fallback whose semantics are proven equal to `TRY_CAST`'s on the corpus. Named as the escape hatch, not built.

- Paths: `pages/docs/reference/errors.md` `src/bloomery/emit/lower/silver.py`

### S-0033/D-31 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12)* **D25's contract is implemented; the strict `xfail` is closed.** The D21 blocking audit now reports a third condition beside the null and duplicate `_source_row_id` checks: `_ingested_at IS NOT NULL AND TRY_CAST(_ingested_at AS TIMESTAMP) IS NULL` — *present but uncastable*, built as a SQLGlot AST through the dialect port like every other term of the audit. `keys.csv::uncastable_ingested_at` (`key_018`) is now an ordinary passing execution assertion, paired with a non-trigger probe of two rows differing only in whether `_ingested_at` parses, so the check cannot go vacuous. Consequence for D30: the metadata audit needs `DialectFeature.TRY_CAST` **independently** of any `coercible` rule, and under D24 a *dedupe-only* entity carries no rules at all — so the audit lowering restates the refusal instead of relying on the coercible-rule one, and a dedupe-only entity compiled for Postgres is now `UnsupportedByTarget` as well. That is the edge of D30's sentence, reached, not a widening of it.

- Paths: `src/bloomery/emit/lower/silver.py`

### S-0033/D-32 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **A `fail` rule's audit reads the pre-route population.** Routing is stage 6 and an audit runs after the model is built, so an audit over `@this_model` sees only the rows the split kept — a row failing a `fail` rule *and* a `quarantine` rule was diverted and the run carried on, inverting D18's severity order. The body is a query over the staged extract (the same rows the routing predicate is evaluated over), which stays inside D29's two-relation scope limit because `referential` cannot carry `fail` (D6). Consequences: every kind lowers through the same `violation` predicate (retiring a `coercible`-at-`fail` special case that had silently redefined the rule as `not_null`), and FAIL-disposition rule names are recorded in **both** `failed_rules` and `_quality_flags`, so the quality mart's `rows_failed` is no longer structurally zero for the rules whose firing matters most.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `tests/execution/test_quarantine_replay.py` `tests/unit/test_emit/test_dbt.py`

### S-0033/D-61 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **The conservation audit asserts one leg, because the other could not fail.** The emitted body carried `entity_rows + diverted_rows <> surviving_rows OR surviving_rows > bronze_rows`, the second disjunct standing for "dedupe removes rows, it never invents any". It is a tautology: `_survivors` *is* the bronze relation with the dedupe `QUALIFY` over it, so the two counts are taken over the same rows and one is a filter of the other — no spec, no data and no lowering bug can make it fire. A check that cannot fail is worse than a missing one, because it reads as coverage; a reviewer counting the law's legs finds two and only one is doing anything. The disjunct is removed and `bronze_rows` stays a **projected** column: an audit reports its violating rows, and `deduped = bronze_rows − surviving_rows` is what makes a reported violation legible. §6's third leg is therefore carried by the property tier and by the quality mart's `rows_deduped` (D35), which is where a count that can be wrong actually lives.

- Paths: `src/bloomery/emit/lower/silver.py`

### S-0033/D-68 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **A quality-mart count is 0 on an empty partition, not NULL.** `SUM(CASE WHEN … THEN 1 ELSE 0 END)` answers 0 for a partition that has rows and matches none of them, and **NULL** for one with no rows at all — `SUM` over zero rows has nothing to sum, which the helper's own docstring denied. An entity with rules whose source delivered nothing this run (a first plan, a partition ahead of the data, an ordinary Tuesday) therefore published mart rows whose every measure was NULL, `rows_quarantined` among them — the numerator D34 exists to make correct. A NULL measure does not read as a small number: it drops out of the `SUM` behind `quality_quarantine_rate`, so the rate answers over a population smaller than the one it names. `COALESCE(…, 0)` around every count, and the docstring made true.

- Paths: `src/bloomery/emit/lower/quality_mart.py` `tests/execution/test_quality_mart.py`

### S-0033/D-69 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **A replay loser says why it is still out.** D22's `_one_winner_per_key` keeps one candidate per entity key and the MERGE keeps the better of candidate and incumbent, so a candidate that now **passes every rule** can be left behind by either. D36's third statement then re-derives `failed_rules` for every still-unresolved row, and for that row the honest re-derivation is *empty*: `resolved_at IS NULL, failed_rules = []` reads as "quarantined for these reasons: none", on a row that will lose the contest for as long as it exists and can only leave by retention. The re-evaluation now records the reserved entry `(superseded)` — parenthesised for D34's reason, since rule names are `[a-z0-9_]+` at parse and at generation (D23), so no authored or generated name can collide with it. It is recorded exactly when the row passes routing, which, read together with the statement's own `resolved_at IS NULL` filter, has one meaning: admitted by every rule and still not in the entity, so another row won its key. The alternative — keeping the stale `failed_rules` — was rejected as a lie: those rules no longer fire, and a reject row that names rules the current spec acquits is exactly the ageing account D36 closed. The row stays **unresolved**: a superseded reject is the replay-side analogue of a deduped row, and resolving it would claim into the conservation accounting that *this* bronze row reached the entity, when a different one did.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/quality/reject.py` `tests/execution/test_quality_precedence.py`

### S-0033/D-70 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix; escape hatch built by D88)* **`last_seen` is one clock — the data's.** It was written as the row's `_ingested_at` (the reject model, D36) and advanced to `CURRENT_TIMESTAMP` by replay's re-evaluation stamp: two meanings in one column, so no reader could say what a value in it was. §5.6 states both halves and settles neither, so the decision is made here. `last_seen` is **the latest delivery's `_ingested_at`** — when the source last delivered this row — and replay's third statement no longer touches it. The deciding argument is retention: §5.6 measures unresolved reject rows *from* `last_seen`, so a column a replay run advances makes an unresolved row immortal for as long as replay keeps running — §9's "quarantine as a PII lake" with its stated mitigation removed. The engine-clock reading cannot instead be pushed onto the write path either: the reject model is a MODEL query, and a clock call there breaks §6's idempotence and backfill-equivalence gates. What is lost, stated: the reject table no longer records *when* a row was last re-evaluated. What records it is `failed_rules`, re-derived from that evaluation — the clause §5.6 names first. A separate `last_evaluated_at` column is the escape hatch if that loss ever bites; it is named, not built, because it is a schema addition and §5.6's schema is this RFC's. This also strengthens D22: replay's third statement is now byte-for-byte idempotent, so the "observability columns excluded" caveat covers `resolved_at`'s timestamp alone. *(D88 built the escape hatch and re-widened that caveat to two columns — the statement stamps `last_evaluated_at`, so it is idempotent over semantic state again rather than byte-for-byte.)*

- Paths: `src/bloomery/emit/lower/silver.py` `tests/execution/test_quality_precedence.py`

### S-0033/D-83 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **The reject table's two constructions are spelled by the dialect port, and Trino hosts it. D75 is closed — and Postgres turned out to be wrong in the same place, silently.** D75 recorded the two gaps and refused Trino at emit; the fix it named — a per-dialect hook rather than a shared AST — is built. `DialectPort` gains `text_sha256` and `json_object`, because a construction that differs per engine belongs to the port that knows the engine (S-0025/D-1), not to a lowering that is supposed to be dialect-neutral. Trino: `LOWER(TO_HEX(SHA256(TO_UTF8(…))))` and the standard keyword `JSON_OBJECT`. **The finding that was not in D75:** Postgres declared support for *both* features and has neither. Its `sha256` takes and returns `bytea`, so the plain spelling did not fail — it silently yielded bytes where every other engine yields a hex string, which would have made `reject_id` disagree across engines while looking like it worked; and it has no positional `json_object` at all (`function pg_catalog.json_object(unknown, integer, …) does not exist` — the SQL/JSON one arrived in 16 taking `KEY … VALUE` only, and the positional builder has always been `json_build_object`). D75's own sentence — "the one construction SQLGlot renders verbatim on every shipped dialect… holds for DuckDB and Postgres but not Trino" — was therefore half wrong, and it read as verified because the *other* half had been. It held only because Postgres never reached emission: D30 refuses a quality-carrying entity there for the unrelated `TRY_CAST` reason, so the reject table was never built for it. Postgres now has correct spellings that stay unreachable until D30 lifts, asserted at the port rather than through a compile so they cannot rot in the meantime. Verified by **executing the emitted model**, not the expressions: the full `__reject` SELECT runs on `trinodb/trino:483` and returns a `reject_id` byte-identical to the Python canon-bytes digest — cross-engine *agreement* being the property `reject_id` actually needs. The feature flags stay in the vocabulary: a fourth dialect may still lack either, and the refusal they drive is still the right answer for one that does.

- Paths: `src/bloomery/dialects/postgres.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/quality/reject.py` `tests/engines/test_merged_cleaning_engines.py` `tests/golden/test_sqlmesh_dialects.py` `tests/unit/test_emit/test_quality_artifacts.py`

### S-0033/D-86 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **The catalogue gains `normalize` and `charset`, and the confusables table is deliberately not among them. D26 is closed.** D26 offered "a Unicode normal form **and/or** a confusables table"; only the first half is built as offered. `normalize` is `NORMALIZE(col, NFC) <> col` — the dialect-neutral node, rewritten to `NFC_NORMALIZE` inside DuckDB's `render` because DuckDB has that function and no `NORMALIZE`, while SQLGlot's duckdb generator renders one verbatim (the D83 shape: renders everywhere, defined in two places out of three). One form only: Postgres and Trino spell all four, DuckDB spells one, and a rule that compiles everywhere and runs on two engines out of three is what S-0025/D-3 exists to refuse. It is a **rule and never a transform** — normalizing silently would rewrite what a source delivered, which D1 forbids. **The table is refused on determinism grounds:** UTS#39 confusables is versioned Unicode data, so embedding it would make a row's disposition depend on which Unicode revision the compiler shipped — an ambient input by another name (S-0020), and one that would move dispositions under a dependency bump nobody read as a semantic change. `charset` declares the admissible characters instead, as `U+` codepoints and inclusive ranges, exactly one of `allow:`/`forbid:`, lowering through a single `TRANSLATE(col, members, '')` read two ways. Codepoints rather than characters because every character the rule exists to catch is invisible: a literal one in YAML is unreadable in review and indistinguishable from a space in a diff. The `allow` reading turns out to be *stronger* than the table would have been for the case that motivated it — an allow-list of the script a column is written in catches a Cyrillic homoglyph, a fullwidth digit and an Arabic-Indic digit alike, none of which any denylist enumerates completely. Three declaration refusals, all decidable from the spec alone and so `GuardrailError`s: a backwards range, a range crossing the surrogate block (checked on the *span*, not the endpoints — the block is 2048 wide, so an endpoint-only check would leave the real refusal to arrive from `MAX_CHARSET_SIZE`, a constant that has nothing to do with surrogates and could grow), and a set past that cap, which exists because the members become a string literal in every row's predicate and in the IR fingerprint. `TRANSLATE` carries **no** `DialectFeature`: all three engines spell it identically and its delete-when-shorter behaviour was executed on each rather than assumed; a feature flag earns its place where the *port* has to differ, which is why `normalize` has one and this does not. Verified by execution on postgres 16 as a permanent engine tier and on `trinodb/trino:483` by hand (no Trino client dependency yet — S-0026's outstanding work), both agreeing with DuckDB on every specimen including the null. **Found on the way:** the §6 matrix rendered through `node.sql(dialect="duckdb")` rather than through the port, so it executed SQL the emitter never emits. Here that surfaced as a failure — DuckDB has no `NORMALIZE` at all — but the failure is incidental to the direction of this particular rewrite. A port rewrite that produces something the *direct* render also accepts would have diverged silently, with the matrix green on SQL no artifact contains. It is routed through the port now.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/duckdb.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/quality/charset.py` `src/bloomery/quality/predicates.py` `src/bloomery/spec/quality.py` `tests/engines/test_postgres_text_rules.py` `tests/golden/schema/mapping.json`

### S-0033/D-87 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **`repair` lands, its recipe is a registered `sql_macro`, and its marker is its own column. D17 is closed.** D17 gated the disposition on a repair-recipe contract and left §10 asking *inline vs catalog-referenced*. S-0034's step registry answers both at once: a recipe is `ref@version` into the registry — declared signature, `runtime_lock`, determinism tier, trust-then-verify — and D1 already holds that specs reference implementations and never contain them, so an inline recipe would have been a second, weaker copy of all of it reachable only from here. **The lowering.** The recipe is spliced at IR build, where the registry lives, and travels as SQL in the rule's params the way an `expression` rule's body does — so emission needs no registry, and a version or `runtime_lock` bump lands in the IR where the fingerprint and `plan()` see it (measured: a body change classifies RESTATING and puts the entity in `replay_scope`, because the kind's params define neither an ordered interval nor a membership set and D52's undecidable-means-replay applies). The rewrite happens at the **extract** level, inside the column's own projection: `CASE WHEN <violation over the raw expression> THEN <recipe> ELSE <raw> END`. That placement is what makes every other rule see the repaired value with no extra nesting, and it forces both halves to be rewritten to read the column's expression rather than its name, since the column is being defined in the same `SELECT`. **The marker.** `_quality_repairs` is a separate column, which was cubic's condition in review and is the right one: a rule is recorded there when its recipe *ran and worked* — it fired over the value as delivered and no longer fires over the value that replaced it. `_quality_flags` stays empty for a repaired row, so `has_quality_flags` keeps meaning **currently suspect** and no mart already asking that question changes its answer. Unlike the two universal columns it is emitted only where a repair rule exists: §12 budgeted the silver-schema churn once, and a third column empty for every project not using the feature is not worth re-opening every golden and fingerprint for. **`fallback` is required**, for the same reason `on_fail` is (D2): a recipe that ran and failed leaves the rule violated and the row is disposed of exactly as if no repair had been declared — the alternative, a still-broken value landing in silver marked as fixed, is the `drop` this RFC refuses wearing a friendlier name. **Refusals**, each a property of the declaration alone: `repair` on `coercible` (it fires *because* the projection is already NULL, so the recipe would be handed the NULL rather than the text that failed to cast — fixing a value before coercion is a Tier 1 macro in the mapping, and the message says so), on `unique` (a property of a population; no rewrite of one row makes a duplicate unique), on a row rule (no column to rewrite), two repair rules on one column (both rewrite the same projection, so which value survives would depend on authoring order and the second recipe would judge a value the first had changed), a recipe accepting more than one column (a rule has no `from:` map, and inventing one would make a rule a second mapping surface), and a column the dedupe order reads (dedupe runs *before* the field rules per D7, so the winner would be chosen on the value as delivered and then have that value rewritten underneath it — D6's reasoning exactly). Verified by executing the emitted pipeline over three rows — one the recipe fixes, one it cannot, one it must not touch — and by sabotage: disabling the recipe, and dropping the "did it run" conjunct from the marker, each fail the assertion that names them. **Not built:** `gold.mart_data_quality` gains no `rows_repaired`, so repairs are observable in silver and not in the quality mart. Recorded rather than implied — adding a measure changes the mart schema, and no demand has asked for it.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/lower.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/spec/quality.py` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/golden/schema/steps.json` `tests/unit/test_spec/test_quality.py`

### S-0033/D-89 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **Mart-level checks are assertions, not quality rules. §10's open question is settled by the disposition model.** §8 deferred them as "blurs into reconciliation" and §10 asked "reconcile-shaped or new surface?" — the answer is neither, and what decides it is not taste. §5.9 draws the boundary at what a verdict *does*: a quality rule disposes of a **row**. A mart row is derived — no `_source_row_id`, no bronze payload, no reject table, no replay — so there is nothing to quarantine, nothing to repair, and nothing to bring back; and a `reconcile` compares *two sides*, which "no month has zero revenue" is not. What is left is D4's other half, "alert me", so `assert:` on a mart declares `{measure, agg, by, min/max, on_fail}` and lowers to an audit the mart model names. `quarantine` and `repair` are absent from its `on_fail` rather than lowered to something weaker, so an author who wanted routing learns it at the surface instead of from a mart that silently only alerts; `fail`/`flag` map to blocking/non-blocking exactly as `reconcile.on_fail` does (D38). The aggregate vocabulary is deliberately the *same tuple* the reconcile grammar uses — both compute one number over a column so a human can be told it is wrong, and two lists that mean the same thing drift. Bounds ride in `params` as text through the D57 carrier, for the same reason. **Resolution is against the flattened column set**, not the base entity's: `ordered_month` exists only because a `date:` step made it, and it is precisely the column §10's example groups by. **The body** is `SELECT <by…>, <agg>(<measure>) FROM @this_model [GROUP BY <by…>] HAVING <bound comparison>` — the value beside the group, because a failure a human must open the warehouse to understand gets ignored. A bare `HAVING` with no `GROUP BY` is the whole-mart form; both shapes were executed on DuckDB, postgres 16 and `trinodb/trino:483` rather than read out of three manuals, and all three agree. **What it cannot see, stated rather than implied:** D19 reaches the mart, so every aggregate but `count` is NULL over an empty group and the assertion stays silent — which is also why an assertion cannot notice a month that is *entirely missing*: no row means no group at all. `count` is the exception and is the one shape that catches an empty mart. Closing the missing-period case needs a join against the date spine, a coverage check with its own dependency, and it is named here rather than half-built. **dbt refuses a project carrying one**, sharing `refuse_steps`' message shape (**amended by D94**: this row said "dbt and Cube", and the Cube half was already obsolete when it was written — S-0034/D-52 had split the blanket Cube refusal on the argument that Cube builds no relation for anything, and Cube compiles the *entire* quality surface, quarantine and reject tables included, without a murmur; refusing this one check would single it out): neither has the audit form, and compiling clean while the declared gate does not exist is the failure D83 caught in the dialect ports. **Cost recorded:** `MartIR` gains a field, and the canonical encoder covers each node's field *names and count*, so every fingerprint in the corpus moves — the churn §12 budgets, spent deliberately. The fixture carrying the demonstration is `quality_precedence` rather than `ecom_basic`, because an assertion makes a project uncompilable for two targets and `ecom_basic` is the fixture those targets' goldens are built on.

- Paths: `src/bloomery/emit/base.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/marts/flatten.py` `src/bloomery/spec/marts.py` `tests/execution/test_quality_precedence.py` `tests/fixtures/quality_precedence/marts.yaml` `tests/golden/schema/marts.json`

### S-0033/D-90 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **Cross-entity checks are `coverage:` on a relationship, and the audit hangs off the *dependent* side. §10's last open question is settled.** §10 guessed "probably reconcile-style"; it is not, and the reason is structural rather than stylistic. A `reconcile` compares two **values** and alerts beyond a tolerance — there is no right-hand value on the referenced entity to compare against, and `right: 1` is neither a shape the closed grammar admits nor one it should grow. This asserts **existence**: every row of a relationship's referenced entity has at least `min` rows referencing it. That makes it the mirror of `referential`, which asks whether every *dependent* row has a parent, and both read the same two relations through the same `via` pairs — which is why it is declared on the **relationship** rather than on either entity. **Why an audit, when a disposition would have been meaningful.** Unlike a mart row (D89), a childless customer is a real silver row with a source identity, a reject table and a replay path, so routing it is not nonsense. It is still an audit, for a reason that only shows up in the DAG: routing would need the *referenced* entity's model to read the *dependent* one, while the dependent one already reads the referenced one through this very relationship — so the pair that most wants this check (an FK one way, a coverage check the other) is exactly the pair whose models would form a cycle. Attaching the audit to the dependent side instead adds **no edge the relationship did not already imply**. `on_fail` is `fail`/`flag` only; `quarantine` and `repair` are absent from the surface rather than lowered to something weaker. **Two emission details that are each a trap closed.** The body counts a *dependent* column, never `COUNT(*)`: a `LEFT JOIN` still produces one output row for an unmatched left row, so `COUNT(*)` answers 1 for a customer with no orders at all and the check would pass on precisely the rows it exists to find. And the dependent side is `@this_model` rather than a named relation — the macro is the one reference SQLMesh rewrites inside an AUDIT body (D29), so naming the relation resolved to the virtual layer *and* put the model into its own `depends_on`, which is how the first cut emitted it. The referenced side is a sibling and is declared in `depends_on`, the trap D40 closed for step audits. Verified by a real SQLMesh plan on a fixture added to the e2e tier for it: the comment above `step_resolution` there argues that nothing else loads SQLMesh and that the gap hid three defects in a row, and this is the same shape — an audit body joining a sibling, with a `depends_on` that exists only because of the audit. dbt refuses the project (its tests are predicates, with no grouped cross-relation form); Cube is not asked, because it builds nothing (S-0034/D-52). **Cost:** `ProjectIR` gains a field, so every fingerprint moves. **Not closed:** the check counts rows that *reached* silver, so a referenced row quarantined by its own rules reads as absent — right for "has an order", wrong for a check somebody phrases as "exists", and named here rather than discovered.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/guardrails/quality.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/lower.py` `src/bloomery/spec/entity.py` `tests/e2e/test_sqlmesh_replan.py` `tests/fixtures/coverage_check/entity_model.yaml` `tests/fixtures/dirty_corpus/entity_model.yaml` `tests/unit/test_fixtures.py`

### S-0033/D-91 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-11)* **A `coverage:` check's endpoints must have relations, and D90 checked neither.** `coverage_owner` documented itself "total by construction: the guardrail stage refuses an unresolvable name before emission runs" — true of the relationship *name* and of nothing else. Two holes, both found in review. A **referenced** entity that is declared but unmapped reached `_referenced_key`'s `next(...)` and raised a bare `StopIteration` mid-emission: an unbatched error after the guardrail stage had reported clean, exactly the shape `_resolve_side` refuses for reconcile. A **step-produced dependent** entity is worse than a crash — the emitter skips those in the entity loop, so the audit is built and attached to no model, and the check reports clean because it never runs. Both are now guardrail refusals, the first reusing `_side_entities` (which already models "has a relation" including step outputs) rather than inventing a second notion of it.

- Paths: `src/bloomery/emit/lower/reconcile.py` `src/bloomery/guardrails/quality.py` `tests/unit/test_quality/test_coverage.py`

### S-0033/D-92 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-11)* **`Reconcile.on_fail` is `flag | fail`, not the full disposition vocabulary.** It was typed `OnFailName`, so `quarantine` and `repair` parsed. Neither means anything here: a reconcile compares two *aggregates*, so there is no row to divert and no recipe surface to carry a repair. `repair` lowered to `OnFail.REPAIR` with no recipe and no fallback, went non-blocking, and wrote "repair" into the quality mart's disposition column as though it were a disposition something had applied. Narrowed at the spec surface, where the other row-routing refusals live.

- Paths: `src/bloomery/emit/lower/reconcile.py` `src/bloomery/spec/quality.py`

### S-0035/D-6 — `ASSUMED` (Public surface and stability policy)

**Deep imports outside a declared `__all__` carry no promise**, stated in the policy. This is what makes decision 3 a fix rather than a courtesy, and what keeps the subpackage layering meaningful.

- Paths: `src/bloomery/emit/lower/__init__.py`

### S-0036/D-1 — `ASSUMED` (Lowering decomposition)

**Split by pipeline stage, never by target.** A per-target lowering file would invert S-0025's port design — targets differ in *assembly* and share *lowering* — and would invite precisely the divergence the three-way equivalence tier exists to catch. `emit/lowering.py` becomes `emit/lower/{select,quality,steps,marts,audits}.py` with `__init__.py` as the pipeline and the only module emitters import.

- Paths: `src/bloomery/emit/lower/__init__.py`

### S-0040/D-4 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

`convert` raises `UnsupportedByTarget` at **emit**, on all three dialects. It stays a registered transform with an unchanged typecheck, so the spec surface does not move and a future dialect clears the refusal by declaring a `Feature` — the mechanism S-0025 already provides.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/evidence.py` `src/bloomery/resolve/build.py` `src/bloomery/transforms/_builtins.py` `tests/fixtures/currency_convert_refusal/entity_model.yaml` `tests/support/type_conformance.py` `tests/unit/test_emit/test_currency_convert.py` `tests/unit/test_evidence.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0040/D-6 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

Phase 2 (as-of join, FX relation) is **design-only and unscheduled**. Recording it here rather than in two future RFCs is the point: both consumers need one construct, and designing them apart would produce two.

- Paths: `src/bloomery/emit/lower/predicates.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-3 — `LOCKED` (Deterministic union merge)

Mappings are unioned in **lexicographic order of source name**, so the emitted artifact is byte-identical across processes. Row order is explicitly **not** claimed — `UNION ALL` is a bag, and nothing downstream may depend on source order.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/ir/nodes.py` `tests/unit/test_determinism_guard.py` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_resolve/test_build.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-5 — `LOCKED` (Deterministic union merge)

A key appearing in more than one source is refused by a generated **blocking** audit (`on_fail: fail`), not configurable to `flag` or `quarantine`. Overlap is either duplication or a shared key space by accident, and both are refusals. The message names the identity-resolution step as the escape hatch. Consequence: bloomery's union is for disjoint key sets, permanently — matching stays a step, and S-0038 is not reopened.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `tests/e2e/test_dbt_parse.py` `tests/e2e/test_sqlmesh_replan.py` `tests/execution/test_merged_cleaning.py` `tests/golden/test_sqlmesh_duckdb.py` `tests/unit/test_examples.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-6 — `LOCKED` (Deterministic union merge)

The union is the **first** silver stage: union → dedupe → rules. A rule evaluated per source would judge rows the merged relation does not contain, which is the same argument that fixed dedupe-before-rules in S-0033.

- Paths: `src/bloomery/emit/lower/silver.py` `tests/unit/test_resolve/test_build.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-7 — `ASSUMED` (Deterministic union merge)

A `_source` system column carries provenance. It is load-bearing rather than diagnostic: the collision audit reports which sources collided, and without it the report is unactionable on a multi-source entity.

- Paths: `pages/docs/reference/stability.md` `src/bloomery/emit/lower/silver.py` `src/bloomery/ir/nodes.py` `src/bloomery/spec/common.py` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_steps/test_lowering.py`

### S-0041/D-12 — `LOCKED` (Deterministic union merge)

`(target, source)` is **unique**: two mappings for one entity may not read the same source relation. Lexicographic ordering needs a total order and two branches on one relation tie, which would leave branch order undefined, `_source` ambiguous, and the collision audit unable to name a branch. Consequence: reading one relation twice is expressed as one mapping with a filter, not two mappings.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/resolve/build.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_resolve/test_build.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-13 — `LOCKED` (Deterministic union merge)

The collision audit reads the **union output, before dedupe**, and groups by **every** declared key column. Reading `silver.order` would let dedupe collapse the colliding rows before the audit counts them — the audit would be checking the one relation guaranteed not to contain what it looks for. Grouping by a partial key would merge distinct composite keys and block valid data, which on a blocking audit is the worst failure available.

- Paths: `src/bloomery/emit/lower/silver.py` `tests/execution/test_merged_cleaning.py` `tests/unit/test_emit/test_quality_artifacts.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-16 — `LOCKED` (Deterministic union merge)

**S-0033/D-10 is not reopened here.** That decision chose one reject table per entity *on the ground that per-mapping tables make replay N-way*, and a merged entity is N-way by construction. `reject_id` itself survives — it is already a digest of `(source_relation, row identity)`, so the pair was designed for exactly this — but replay re-runs *the* current mapping, and branching it per source is the thing D10 refused. N-way replay gets its own RFC, argued against D10 directly, rather than being decided inside a feature branch.

- Paths: `src/bloomery/emit/lower/silver.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-18 — `LOCKED` (Deterministic union merge)

**`_source` joins `RESERVED_MEMBER_NAMES`.** Every other generated column is reserved — `_quality_flags`, `_quality_ok`, `_load_id`, `_ingested_at`, `_source_row_id`, `has_quality_flags` — and a generated column that is not is one an author can collide with. Reserved unconditionally, not only on merged entities: a name that is legal until a second mapping arrives is a trap laid for the change that adds one.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/common.py` `tests/unit/test_spec/test_entity.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-19 — `ASSUMED` (Deterministic union merge)

**The quality mart accounts per entity, not per source.** Its mapping identity is `f"{source.relation}->{entity.name}"`, which has no single value on a merged entity. Per entity, because the mart's row is "one rule evaluation on this entity" and the rules run on the merged relation (D6) — a per-source split would report rule counts against a population the rule never saw. Provenance is still reachable: `_source` is a real column, so a per-source view is a filter rather than a schema.

- Paths: `src/bloomery/emit/lower/quality_mart.py` `src/bloomery/emit/lower/silver.py`

### S-0041/D-26 — `ASSUMED` (Deterministic union merge)

**Answers D25 (`OPEN`) — option (a), and D25's blast-radius figure was wrong by an order of magnitude.** The lowered expression moves to a new column-grained `SourceColumnIR` on `SourceIR`; `ColumnIR` keeps the schema (§5.7). D25 said "37 `.columns` read sites" and estimated the cost from that; measured, **exactly 8 sites read a `ColumnIR` lowering field, in 3 files** — `plan/diff.py` (`renamed_from` ×4, `recipe_id`, `expr.sql`) and `emit/lower/silver.py` (`expr.ast()` ×2). Four of those eight are `renamed_from`, which D25 mis-assigned to the lowering half and which is declared on the EntityModel `Field`, so it does not move at all. The 37 was a count of `.columns` readers, and `.columns` readers are overwhelmingly *schema* readers — they survive untouched, which is the whole point of the split. **Real cost: two constructors where there was one, and four call sites.** The golden churn stands regardless — the IR shape moves and D17 bumps the version.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/operands.py` `src/bloomery/guardrails/stage.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/resolve/build.py` `src/bloomery/resolve/facets.py` `src/bloomery/resolve/steps.py` `src/bloomery/resolve/timeline.py` `tests/bench/test_hydration.py` `tests/support/ir_factory.py` `tests/support/plan_ir.py` `tests/unit/test_emit/test_cube.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_facets.py` `tests/unit/test_unresolved.py`

### S-0041/D-31 — `LOCKED` (Deterministic union merge)

**P2 is demand-gated: the design lands now, the code waits for a named consumer.** S-0040/D-6 applies this test to its own P2 and this document did not, which left §12 reading as a queue rather than a boundary. The asymmetry has no justification — P1's refusals are honest, tested, and route to the shipped workaround, so nothing is broken while P2 is unbuilt, and P2a's cost falls on S-0033's rule catalogue, which every entity reads, merged or not. What is **not** deferred is the design: D29's couplings were measured against this tree while P1's context was live, and that context is the asset that decays — the prose does not. So D32–D35 are settled here and §12's P2a–P2c are specified; implementation begins when a project needs quality rules on a merged entity, and not before. Consequence: the two refusal messages stop saying "until P2 restores it". A promise in an error message is one a user plans around, and this decision makes P2 a phase rather than a date.

- Paths: `src/bloomery/emit/lower/silver.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-32 — `LOCKED` (Deterministic union merge)

**A rule's per-mapping dependency is projected as a branch-local column; the rule stays entity-grained (P2a).** The mechanism is not invented here — `coercible` already reads projected `_src_<rule>_<n>` aliases (`quality/predicates.py:source_alias`) rather than inline JSONPaths, because the raw paths live one level down in the extract SELECT, and P1 turned that projection site into `_branch_select`. So a fact only one branch knows already has a way to reach a rule the merged relation evaluates once. **D6 is not violated, and the reading that says it is — that projecting a verdict per branch just *is* "a rule evaluated per source" — mistakes what D6 argues.** D6 argues from the *row population* — "a rule evaluated per source would judge rows the merged relation does not contain" — and the union is `ALL`, so a branch-projected **scalar** verdict judges exactly the rows the union contains. Dedupe runs after the union and may drop a row; that row's flag is then unused, which is not a wrong answer. **The boundary is `WINDOWED_KINDS`** (`quality/predicates.py`, currently `{unique}`): a windowed verdict depends on the population and so may not be computed per branch — and it does not need to be, since its inputs are the produced column values, which D26's split already makes mapping-invariant. Consequence: `coercible` sheds its per-source alias set for one branch-computed boolean ("every source path *this branch* read was non-null"), which collapses the arity problem at the level where arity is known; `in_enum` takes the same shape rather than a second mechanism, its admissible set being the branch's own `enum_map` chain. **The tempting wrong fix is recorded so it is not re-proposed:** NULL-filling a missing `_src_` alias to make the arities agree renders `is_not_null` false, the conjunction never fires, and the rule silently stops checking on that branch — the failure D28 refuses by name, a check that quietly stops checking being worse than one that is absent.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/guardrails/quality.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/quality/lower.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/build.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_merged_cleaning.py` `tests/fixtures/multi_source_quality/mapping_legacy.yaml` `tests/support/quality_rules.py` `tests/unit/test_quality/test_lower.py` `tests/unit/test_quality/test_predicates.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-34 — `LOCKED` (Deterministic union merge)

**Artifact shape varies with mapping count; `_source` stays merged-only (P2b).** The question D7 and D15 both defer, answered once for the provenance column, the metadata audit body and the collision audit together. The metadata audit becomes `PARTITION BY _source, _source_row_id` on a merged entity and stays `PARTITION BY _source_row_id` elsewhere. **The cost is a new precedent, stated here rather than discovered later:** until now the *set* of emitted artifacts varied with a spec, never a generated **body**. The alternative — `_source` on every entity, one uniform audit body, mapping count invisible in the artifacts — buys a reader the property that a merged entity looks like any other, and costs a corpus-wide golden re-stamp plus a constant column on every single-source silver model, which is precisely what D9 declined to pay on measured grounds. Continuing that decision is cheaper than reversing it, and reversing it buys nothing but uniformity. **A third option is named only to close it:** making `_source_row_id` globally unique in bronze would dissolve the question, and it does so by relocating the problem into S-0033/D-21's ingestion contract and breaking every table already landed under it.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_merged_cleaning.py` `tests/golden/test_sqlmesh_dialects.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-35 — `LOCKED` (Deterministic union merge)

**`_source` joins the dedupe sort key, immediately ahead of `_source_row_id` (P2b).** `dedupe_sort_columns` ends in the row identity, and its totality argument is "no two rows can compare equal *given the D21 metadata contract*" — an identity unique per **source relation**. On a merged entity two rows from different sources sharing an entity key therefore compare equal and the survivor is undefined. That shape is what D5's collision audit refuses, but an audit runs *after* the model materialises, so the window is real and the totality argument would be leaning on a blocking check in a different artifact. Adding `_source` restores it structurally and locally, for one extra sort term on merged entities only (D34). It is the same defense-in-depth already pinned into that exact column by `NULLS LAST`, against an illegally-null identity the audit also catches. Consequence: where two rows would have compared equal, the survivor is the lexicographically-later source — arbitrary as business logic, deterministic as an artifact, and reachable only in the run the collision audit then stops.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/quality/dedupe.py` `tests/execution/test_merged_cleaning.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0043/D-5 — `LOCKED` (The dbt singular-test surface)

**The model reference goes through `_reference_map`, never string formatting.** It is what makes a singular test a DAG participant rather than a query that happens to name a table, and it is already built for exactly this shape. Consequence: a singular test is ordered against its model by dbt, which is what makes "blocking" mean anything at all under D2.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/emit/steps.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0043/D-10 — `LOCKED` (The dbt singular-test surface)

**The audit envelope separates from the audit body** (§5.3). `emit/steps.py` is target-neutral by position and not by content: its `_AUDIT` template bakes SQLMesh's `AUDIT (name …);` header in, so `quality_audits` and `consistency_audits` hand shared callers a SQLMesh artifact. A producer instead returns a *named body* — rendered SELECT, name, disposition — and each target wraps it. The alternative, a second template beside the first, gives one audit body two spellings maintained in parallel, which is the divergence the shared lowering exists to prevent. Consequence: this is the only structural change here, and it is what makes the remaining work a template and a path rather than five separate liftings. It also carries the relation in as a parameter, so `@this_model` stops being a literal the dbt side would rewrite by substitution.

- Paths: `src/bloomery/emit/base.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/steps.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_steps/test_dbt_and_cube_emission.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-8 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A metric filter is a typed predicate list — `{dimension, op, values}` — and never a SQL string.** A string would be dialect-bound, unvalidatable against the column's declared type, and an injection surface in a compiler whose input may be untrusted. The list is ANDed; a disjunction is expressed as `in`.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/semantic/additivity.py` `src/bloomery/spec/common.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_semantic/test_ratio_rows.py` `tests/unit/test_spec/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-9 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A filter's dimension is checked against every mart listing the metric, at the guardrail stage.** Not at emit: a filter naming a column no mart flattens is a *model* error, decidable from the spec, and it should fail with the batched aggregate every other model error joins. Checking every listing mart rather than the owning one avoids reaching for the ownership rule from a layer below the module that defines it, and is a superset of what correctness needs.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/errors.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/semantic/additivity.py` `tests/fixtures/period_over_period/entity_model.yaml` `tests/unit/test_guardrails/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-13 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**String values in a metric filter refuse `{` and `}`, at parse.** Both semantic targets template with braces — Jinja on MetricFlow, `{member}` on Cube — and a value carrying one would need per-target neutralization. One refusal beats two escaping rules that can disagree; a curly brace in a filtered dimension value has no BI use worth the divergence. At parse rather than at the guardrail because it is a property of the document alone, which is where S-0019/D-4 draws that line — unlike D9's dimension check, which needs the marts. NUL and floats are refused in the same validator, for the reasons they are refused everywhere else.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/spec/metrics.py` `tests/unit/test_spec/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-15 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**The filter renderer lives once, in `emit/lower/predicates.py`, parameterized by the target's column spelling.** Each target supplies how it names a column — `{{ Dimension('e__c') }}` for MetricFlow, `{CUBE}.c` for Cube — and the comparison syntax, list rendering and literal escaping are shared. Two renderers would be the same injection-safety rules spelled twice, which is the defect class this project keeps finding in itself.

- Paths: `src/bloomery/emit/lower/predicates.py` `tests/unit/test_emit/test_period_over_period.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0051/D-2 — `LOCKED` (The reject table on a merged entity)

**`source_relation`, `mapping`, `mapping_version` and `reject_id` are projected per union branch.** They are true of a branch and were only ever true of a model because there was one branch. `reject_id` moves with them out of necessity rather than symmetry: its first argument is the branch's relation name, which the union erases. Consequence: `reject_select` reads four more columns off the extract subquery and reads no `SourceIR` at all.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/plan/diff.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_merged_cleaning.py` `tests/unit/test_plan/test_diff.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0051/D-3 — `LOCKED` (The reject table on a merged entity)

**Replay filters each branch to `source_relation = '<branch>'`.** Without it a mapping's extraction runs over another mapping's payload and returns NULLs rather than raising — a silent wrong answer, which is the failure class this project refuses. The filter is sound because `(target, source)` is unique (S-0041/D-12), so the literal names exactly one branch.

- Paths: `src/bloomery/emit/lower/silver.py` `tests/execution/test_merged_cleaning.py` `tests/golden/test_sqlmesh_dialects.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0051/D-6 — `LOCKED` (The reject table on a merged entity)

**`_sole_source` stays.** The quality mart still has no merged form (S-0041/D-19), and the accessor's raising spelling is what made this whole area fail loudly rather than silently when P2 arrived. What changes is one caller, not the mechanism.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/quality/reject.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0053/D-2 — `LOCKED` (Measure semantic types and additivity algebra)

**A ratio is stored as its operands, not as a materialized quotient.** `SUM(num)/SUM(den)` and `AVG(ratio)` differ, the second is what a numeric-looking column invites, and the difference is a plausible wrong number. This is also S-0055's precondition — a derived metric spanning two branches cannot be reconstructed after the operands are gone — so reversing it later strands that document.

- Paths: `src/bloomery/emit/lower/rollups.py` `src/bloomery/errors.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/mart.py` `tests/fixtures/semantic_corpus/002-average-of-averages/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/002-average-of-averages/problem.md` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/problem.md` `tests/fixtures/semantic_corpus/008-ratio-rollup/bloomery/declared/metrics.yaml` `tests/fixtures/semantic_corpus/008-ratio-rollup/bloomery/naive/metrics.yaml` `tests/fixtures/semantic_corpus/008-ratio-rollup/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/008-ratio-rollup/problem.md` `tests/fixtures/semantic_corpus/012-rollup-recounts-identities/problem.md` `tests/unit/test_emit/test_rollups.py` `tests/unit/test_guardrails/test_additivity.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_steps/test_step_canonicals.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0060/D-1 — `LOCKED` (dbt as a complete quality target)

The reject table preserves `first_seen` / `last_evaluated_at` **in its own SELECT**, by `LEFT JOIN` to `{{ this }}` and `COALESCE`, not by dbt's `merge_exclude_columns`. Column exclusion cannot express a `COALESCE`, so it would leave a null unhealed where SQLMesh heals it — a divergence in the column retention reads — and it requires a `merge` strategy dbt-postgres does not have and dbt-duckdb has only above a DuckDB floor. Locks the reject model to one scan of itself per run, in exchange for working on every adapter.

- Paths: `src/bloomery/emit/lower/silver.py` `tests/e2e/test_dbt_quality.py`
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

### S-0062/D-8 — `ASSUMED` (Ownership, classification and grants)

No spelling rule on `owner`. Every project spells this differently and a format check would refuse spellings correct for their reader.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/sqlmesh/__init__.py`

### S-0066/D-3 — `LOCKED` (Declared input currency for conversion)

**The column's currency is what the chain's *last* conversion produces.** The existing per-marker check refuses a correct two-hop chain (§3), and bridging through a major currency is how minor pairs convert in practice. Locked because the guarantee the check buys is a property of where the chain ends, and any rule reading an intermediate step is reading a currency the column is never in.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/resolve/build.py` `tests/unit/test_resolve/test_currency_convert.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
