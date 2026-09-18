<!-- torve:managed src/bloomery/guardrails — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/guardrails/`

### S-0019/D-3 — `ASSUMED` (Spec layer and error model)

Every raisable failure derives from `BloomeryError` and carries `source_path`; all error classes are declared in `bloomery/errors.py` so `except BloomeryError` needs one import. Pydantic/yaml exceptions never escape.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/quality.py` `src/bloomery/spec/common.py`

### S-0019/D-6 — `ASSUMED` (Spec layer and error model)

Parse-stage errors are batched per document (all failures reported at once).

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/errors.py` `src/bloomery/evidence.py` `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/build.py` `src/bloomery/resolve/refs.py` `src/bloomery/spec/common.py` `src/bloomery/spec/project.py` `src/bloomery/typing/check.py` `tests/unit/test_cli.py` `tests/unit/test_evidence.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_refs.py` `tests/unit/test_spec/test_mapping.py` `tests/unit/test_spec/test_project.py` `tests/unit/test_spec/test_sql_text.py`

### S-0019/D-10 — `ASSUMED` (Spec layer and error model)

(Amended for `_bloomery-metricflow-pivot.md`) `metric_time` is a reserved dimension/field name, rejected at spec validation with a clear message (S-0030 R4). The `Metric` model reserves optional `cumulative:` (window / grain_to_date) and derived-expression forms lowered per S-0030's mapping table; both are additive spec surface, parse-validated only.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/spec/common.py` `src/bloomery/spec/entity.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `tests/golden/schema/catalog.json` `tests/golden/schema/entity_model.json` `tests/golden/schema/marts.json` `tests/golden/schema/metrics.json` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_spec/test_metrics.py`

### S-0022/D-2 — `ASSUMED` (Resolution: dependency DAG, recipes, reachability)

The compiler never chooses a recipe. The mapping's recorded `recipe:` id is validated — id exists on the catalog field, every `requires` name bound by the mapping's `from` aliases (exactly) — else `ResolutionError`. Choice happens upstream; the compiler reproduces it (determinism + auditability, spec §3.4). Consequence: catalog evolution can invalidate recorded choices, and that is a loud error, not a silent re-choice.

- Paths: `src/bloomery/evidence.py` `src/bloomery/guardrails/operands.py` `src/bloomery/resolve/recipes.py` `src/bloomery/resolve/resolution.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/mapping.py` `tests/golden/schema/catalog.json` `tests/golden/schema/mapping.json` `tests/unit/test_resolve/test_edge_shapes_offcorpus.py` `tests/unit/test_resolve/test_recipes.py`

### S-0023/D-1 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

All seven spec-§5.4 guardrails ship in v0.1 as compile errors — never warnings, no severity/suppression knob. A knob makes "error" negotiable, which defeats the stage's purpose.

- Paths: `src/bloomery/guardrails/__init__.py`

### S-0023/D-2 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Violations are batched project-wide: leaf errors (`UnitMismatch`, `TaxBasisMismatch`, `CurrencyMismatch`, `GrainMismatch`, `AdditivityViolation`, `AssertLoweringError`) are collected and raised as one `GuardrailError` aggregate, sorted by `(source_path, type)`. Matches S-0019/D-6.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/arithmetic.py` `src/bloomery/guardrails/quality.py` `src/bloomery/guardrails/stage.py` `src/bloomery/quality/reconcile.py` `src/bloomery/resolve/build.py` `src/bloomery/resolve/steps.py` `tests/fixtures/fanout_trap/metrics.yaml` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_guardrails/test_stage.py` `tests/unit/test_steps/test_lowering.py`

### S-0023/D-3 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

`unit`/`tax_basis` originate only on catalog canonical fields and propagate via `canonical:`; a monetary operand without metadata is `unknown`, and `unknown` in any `+`/`-` is an error. No inference from names or values, ever.

- Paths: `src/bloomery/guardrails/arithmetic.py` `src/bloomery/guardrails/operands.py` `tests/unit/test_guardrails/test_arithmetic.py` `tests/unit/test_guardrails/test_grain.py`

### S-0023/D-4 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Currency codes are checked only when both operands declare one; distinct declared codes require an explicit `convert` transform. Absent codes are compatible — opt-in, unlike tax basis, so single-currency tenants aren't trained to paste constants.

- Paths: `src/bloomery/guardrails/arithmetic.py` `src/bloomery/resolve/build.py` `tests/fixtures/semantic_corpus/004-currency-mix/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/004-currency-mix/problem.md` `tests/golden/refusals/example-mixed-currency.txt` `tests/unit/test_guardrails/test_arithmetic.py`

### S-0023/D-5 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Grain guard: derivation operands must share the derivation's grain or the expression must contain an explicit aggregation over the finer grain. No automatic allocation. `fanout_trap` (S-0026) is the numeric proof.

- Paths: `src/bloomery/guardrails/grain.py` `tests/execution/test_fanout_trap.py` `tests/fixtures/fanout_trap/catalog.yaml` `tests/fixtures/semantic_corpus/001-order-shipping-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/001-order-shipping-fanout/problem.md` `tests/unit/test_guardrails/test_grain.py`

### S-0023/D-6 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Additivity: `non_additive` metrics are never materialized as stored numbers (components only); `semi_additive` metrics aggregate only over dimensions other than their `over:` dimension. Enforced at IR build **and** re-refused by emitters (S-0025) — defense in depth.

- Paths: `pages/docs/concepts/guardrails.md` `src/bloomery/guardrails/additivity.py` `src/bloomery/planner/coverage.py` `tests/fixtures/semantic_corpus/002-average-of-averages/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/002-average-of-averages/problem.md` `tests/fixtures/semantic_corpus/005-semi-additive-balance/problem.md` `tests/unit/test_guardrails/test_additivity.py`

### S-0023/D-7 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Path conflict does not raise (`PathConflict` is not an error class): the compiler emits the derived column, a `<name>__direct` shadow, and a `RECONCILE` `AuditIR`. The forbidden thing is the silent choice; both paths are valid, so the refusal targets the silence, not the spec.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/quality.py` `src/bloomery/ir/lower.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/mapping.py` `tests/fixtures/path_conflict/entity_model.yaml` `tests/fixtures/path_conflict/mapping.yaml` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_ir/test_lower.py` `tests/unit/test_spec/test_mapping.py`

### S-0023/D-8 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Range sanity: the guardrail stage validates `assert:` clauses for well-typedness against the field's `LogicalType` only (`AssertLoweringError`); lowering to target-native audits happens via `AuditIR` at emit (S-0020, S-0025).

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/asserts.py` `src/bloomery/guardrails/stage.py` `src/bloomery/quality/predicates.py` `src/bloomery/spec/entity.py` `src/bloomery/spec/quality.py` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/unit/test_guardrails/test_asserts.py` `tests/unit/test_guardrails/test_quality.py`

### S-0023/D-9 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

`check_guardrails(draft: ProjectIR) -> ProjectIR` is pure; its only amendment is path-conflict handling (shadow column + audit). All other guardrails are read-only checks.

- Paths: `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/build.py` `tests/property/test_guardrail_properties.py` `tests/unit/test_guardrails/test_stage.py`

### S-0023/D-10 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Mart-level fan-out guard runs at compile time (_bloomery-changes.md D2, S-0027): `GrainViolation` (a measure whose grain is coarser than the mart's grain listed in a finer-grain mart's `measures`) and `FanoutRisk` (a `flatten:` step whose `via:` relationship is not `many_to_one`/`one_to_one`) are `GuardrailError` leaves, batched like the rest. `fanout_trap` now fails at compile time; its execution assertion is kept because it documents why the compile error exists.

- Paths: `src/bloomery/guardrails/grain.py` `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/build.py` `tests/execution/test_as_of_join.py` `tests/execution/test_fanout_trap.py` `tests/fixtures/fanout_trap/marts.yaml` `tests/unit/test_guardrails/test_stage.py`

### S-0023/D-11 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Additivity extends with `NonAdditiveWithoutComponents` (a `non_additive` metric declared without a `RatioSpec` or equivalent additive decomposition — nothing to recompute from); `SemiAdditivePolicy(over, rule)` with `rule ∈ {last, first, avg, max, min}` replaces the bare `over:` annotation (_bloomery-changes.md D4). The query-time lowering of `rule` is S-0028's, not this stage's.

- Paths: `src/bloomery/guardrails/additivity.py` `tests/fixtures/semi_additive_inventory/metrics.yaml` `tests/unit/test_guardrails/test_additivity.py`

### S-0026/D-9 — `ASSUMED` (Testing strategy and fixture corpus)

Coverage: branch on, `fail_under=80` overall, per-package floors ratcheting up (forze pattern); `bloomery/guardrails/` is floored at 100% branch from day one.

- Paths: `src/bloomery/guardrails/quality.py` `tests/README.md` `tests/unit/test_quality/test_coverage.py`

### S-0027/D-8 — `ASSUMED` (Marts and role-playing dimensions)

`cost_hint` (int, default 1) is a tie-breaking scan-cost hint only; selection ties break lexicographically (S-0020 determinism).

- Paths: `src/bloomery/emit/lower/marts.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/spec/marts.py` `tests/golden/schema/marts.json` `tests/unit/test_emit/test_metricflow.py` `tests/unit/test_planner/test_coverage.py`

### S-0028/D-5 — `ASSUMED` (Native planner: MetricRequest → QueryPlan)

Additivity lowering per D4 exactly: additive → SUM at requested grain; semi-additive (`SemiAdditivePolicy(over, rule ∈ last/first/avg/max/min)`) → sum across every dimension except `over`, rule along `over` (coarser requested grain: rule within each bucket, then sum); non-additive → never stored/summed, recomputed from additive components (`RatioSpec` → `SUM(num)/NULLIF(SUM(den),0)`); missing components = `NonAdditiveWithoutComponents` at resolution/guardrail stage (S-0023 defense-in-depth).

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/coverage.py` `src/bloomery/planner/explain.py` `src/bloomery/planner/result.py` `src/bloomery/spec/common.py` `tests/fixtures/non_additive_aov/marts.yaml` `tests/fixtures/non_additive_aov/metrics.yaml` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_planner/test_coverage.py`

### S-0030/D-8 — `ASSUMED` (MetricFlow backend: manifest emitter and planner adapter)

Filters (Jinja `where_constraints`) are the highest-risk surface: values never interpolated raw — typed per-dialect literal renderer or bind parameters; dimension names only from validated `DimensionRef`s via `names.py`; values type-checked against the dimension (`FilterTypeMismatch`); `contains`/`like` escape wildcards. Adversarial fuzz property test (injection strings, template syntax, unicode quotes, newlines) asserts parsed-SQL predicate structure unchanged and scanned relations exactly the expected mart — **merge-blocking**. *(Superseded by D16 — see §5.6 note.)*

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/planner/filters.py` `src/bloomery/planner/request.py` `tests/property/test_planner_properties.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_planner/test_filters.py`

### S-0033/D-3 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Coercion failure is a rule: transform chains lower to failure-marker form (`TRY_CAST`-style per dialect); the implicit, overridable `coercible` rule (default `quarantine`) disposes of it. Retires `Mapping.on_unmapped_enum` (S-0019 amendment — absorbed into `in_enum`/`coercible`) and supersedes S-0025/D-7's never-implemented emitter convention with the modeled reject table.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/guardrails/operands.py` `src/bloomery/quality/predicates.py` `src/bloomery/spec/mapping.py` `src/bloomery/spec/quality.py` `src/bloomery/transforms/_builtins.py` `tests/execution/test_path_conflict.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_spec/test_mapping.py`

### S-0033/D-12 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

`gold.mart_data_quality` is an ordinary semantic model (`run_date` as time dimension); quarantine rate is a `MetricRequest`. Reject tables are never exposed through `MetricRequest`. Deliberate divergence: no `tenant_id` column (Document 5 §7.5 has one) — hard invariant #3 and the tenant guard forbid it; `NamingPolicy` namespaces are the only tenant seam.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/quality/mart.py` `tests/execution/test_quality_mart.py` `tests/unit/test_guardrails/test_quality.py`

### S-0033/D-13 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

The guardrail boundary (§5.9) is normative: guardrail = the model is wrong, compile time; quality rule = the data is wrong, run time. Nothing decidable from the spec alone enters `quality/`.

- Paths: `src/bloomery/guardrails/metrics.py` `src/bloomery/quality/__init__.py` `src/bloomery/spec/quality.py`

### S-0033/D-21 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Ingestion metadata contract: entities using `quarantine` or `dedupe` require bronze `_load_id`, `_ingested_at`, `_source_row_id` (a stable per-source-row identity supplied by the ingestion layer, **NOT NULL and unique per source row** — data properties no compiler can check, so the lowering emits a generated **blocking audit** on the metadata columns: a null or duplicated `_source_row_id` stops the run); column absence is the new compile error `IngestionMetadataMissing` (`GuardrailError` leaf, `errors.py` per S-0019/D-3). `reject_id` = sha256 over the length-prefixed utf-8 **pair** (`source_relation`, `_source_row_id`) — canonical serialization per the S-0020 canon-bytes doctrine. This supersedes the triple this row first carried (this round's own earlier decision): `_load_id` is removed from the identity and becomes an attribute (the latest observing load) — re-deliveries of the same source row across loads must land on the **same** reject row (that is what `first_seen`/`last_seen` track); a per-load identity would mint a new row per retry and violate replay idempotence. A re-delivery updates `last_seen`/`_load_id`/`failed_rules` on the existing row.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/quality.py` `src/bloomery/quality/catalogue.py` `src/bloomery/quality/dedupe.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/transforms/_builtins.py` `tests/e2e/test_dbt_parse.py` `tests/e2e/test_sqlmesh_project.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_dedupe_and_audits.py` `tests/execution/test_merged_cleaning.py` `tests/execution/test_zoneless_utc.py` `tests/fixtures/dirty/README.md` `tests/fixtures/semi_additive_inventory/mapping.yaml` `tests/support/execution.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_trino.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_entity.py`

### S-0033/D-27 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12)* **`referential` on a self-relationship is refused at compile time.** The lowering is a `LEFT JOIN` inside the dependent entity's own model (§5.4), so a rule whose relationship's `to` side is the declaring entity is unexecutable — a model cannot join the table it is being built from, and the emitted SQL would either fail or resolve against a stale previous version and answer the wrong question. It is a `GuardrailError` (bare, per §5.9's five-named-leaves rule) naming both alternatives: model the referenced side as a separate entity built from the same source, or express the check as a `reconcile:` block, which runs silver→mart against finished tables. Self-referencing *data* stays expressible; the single-entity *shape* does not.

- Paths: `src/bloomery/guardrails/quality.py`

### S-0033/D-45 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **A `referential` rule whose `via` names no relationship is a guardrail refusal.** Resolution (S-0022) validates the `relationships:` block itself and never inspects `entity.quality`, so a typo'd `via` reached the lowering's relationship lookup and came out as a raw `KeyError` — not a `BloomeryError`, never batched into the stage's single aggregate (S-0019/D-3), and naming a compiler internal instead of the typo. The refusal is a bare `GuardrailError` naming both the unknown relationship and the declared ones. Consequence for the lowering: it may not assume the lookup is total, because the guardrail stage runs *after* the draft is built — an unresolvable rule lowers to nothing and the stage refuses before anything is emitted.

- Paths: `src/bloomery/guardrails/quality.py`

### S-0033/D-46 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **A `referential` rule's relationship must run *from* the declaring entity.** The lowering reads `via`'s from-columns off *this* entity's extract (§5.4), so a rule naming a relationship declared between two other entities emits a `LEFT JOIN` whose `ON` clause references columns the model never projects — a run-time binder failure from a spec that compiled clean. D27 refused the same class of unexecutable join by comparing only the relationship's `to` side, which let a `cust → cust` self relationship borrowed by an unrelated entity slip past the very check written for it. The check now compares both sides: `from` must be the declaring entity, and `to` must not be (D27, unchanged).

- Paths: `src/bloomery/guardrails/quality.py`

### S-0033/D-47 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **`dedupe.field`/`tie_break` must name a column the entity declares.** They lower straight into `ORDER BY <column> DESC NULLS LAST` (§5.4), so a typo compiled clean and failed at run time in the engine's binder — the exact class of failure the guardrail stage exists to move to compile time. Legal targets are the entity's fields and key **plus** the three ingestion-metadata columns (D21): `_ingested_at` is the usual `dedupe.field` and no mapping declares it as a field, so restricting to mapped fields would refuse the documented spelling.

- Paths: `src/bloomery/guardrails/quality.py`

### S-0033/D-49 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **`in_enum`'s rule identity carries the chain's source spellings, not only its `enum_map` targets.** `enum_map` passes an *unmapped* value through untouched, so the raw values `in_enum` admits are the mapped spellings **plus** the targets. A widening therefore has two shapes — a new target, or a new spelling for an existing target (`PAYED → paid`) — and only the first changed a rule param, so `plan()` reported `replay_scope = ()` for the second while rows sat in the reject table on that rule's account. §6's replay test used only the shape that worked, so the gap was untested. The lowering now emits `spelling_NNNN` params beside `value_NNNN`. The pairing is deliberately *not* carried: re-pointing `a → x` to `a → y` when both are already targets changes the column's value — which the column diff reports — but changes nothing about which raw values this rule admits.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/quality/lower.py` `tests/unit/test_guardrails/test_quality.py`

### S-0033/D-71 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **An authored rule name may not be one generation already issues.** D50 made generated names order-independent; they were not **name**-independent. An authored `expression` rule called `status_in_set` sorted ahead of the field's own generated `status_in_set` and took it, pushing the generated rule to `status_in_set_2` — so an edit to the entity's `quality:` block silently renamed a rule declared on a *field*. That name is the key of a time series: the `rule` dimension of `gold.mart_data_quality` (§5.8) and an entry in every reject row's `failed_rules` (D23). `plan()` is honest about the move — a removal, an addition and a replay — which is precisely the problem: none of that happened to the rule, which goes on firing on the same rows under a name nothing in the spec spells. Refused at compile as a bare `GuardrailError` naming both the claimed name and every name generation owns on that entity, because both arbitrations are wrong: renaming the generated rule moves a series key, renaming the authored one contradicts what a human wrote. Making generated names collision-proof *by construction* was rejected as the primary fix — the only free namespace inside D23's `[a-z0-9_]+` is a prefix nobody would want in a mart dimension — but the structural half is kept anyway: name assignment reserves the generated names in their own pass first, so a generated name is a function of the mapping alone and a future suffix cannot defeat the refusal from underneath.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/quality/lower.py`

### S-0033/D-72 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, PR #7 review)* **A quality predicate derived from a transform chain must be derived from the chain's *final* value, and the compiler refuses where it cannot prove that.** Two rules read the chain and both read it at the wrong point. `in_enum`'s admissible set is the `enum_map` targets and spellings (D49) while the predicate tests the column's final value, so a step *after* the `enum_map` moves that value off the set: `{enum_map: [paid, paid]}` then `upper` quarantined **every correctly-mapped row** — executed on DuckDB the entity came out empty and all three rows sat in the reject table, the worst failure this feature has. Lowering targets through the remaining chain is not available to a compiler that executes nothing (`regex_extract`, `split_part` and the `strip_*` family are only evaluable by running SQL — S-0020), so the chain is refused at compile instead, naming the offending step. A further `enum_map` may follow: the union of both steps' targets contains every reachable final value, so the set can only be too generous, and too generous never withholds a good row. No fixture could have caught it — every `enum_map` in the corpus happens to be the last step.

- Paths: `src/bloomery/guardrails/quality.py`

### S-0033/D-90 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **Cross-entity checks are `coverage:` on a relationship, and the audit hangs off the *dependent* side. §10's last open question is settled.** §10 guessed "probably reconcile-style"; it is not, and the reason is structural rather than stylistic. A `reconcile` compares two **values** and alerts beyond a tolerance — there is no right-hand value on the referenced entity to compare against, and `right: 1` is neither a shape the closed grammar admits nor one it should grow. This asserts **existence**: every row of a relationship's referenced entity has at least `min` rows referencing it. That makes it the mirror of `referential`, which asks whether every *dependent* row has a parent, and both read the same two relations through the same `via` pairs — which is why it is declared on the **relationship** rather than on either entity. **Why an audit, when a disposition would have been meaningful.** Unlike a mart row (D89), a childless customer is a real silver row with a source identity, a reject table and a replay path, so routing it is not nonsense. It is still an audit, for a reason that only shows up in the DAG: routing would need the *referenced* entity's model to read the *dependent* one, while the dependent one already reads the referenced one through this very relationship — so the pair that most wants this check (an FK one way, a coverage check the other) is exactly the pair whose models would form a cycle. Attaching the audit to the dependent side instead adds **no edge the relationship did not already imply**. `on_fail` is `fail`/`flag` only; `quarantine` and `repair` are absent from the surface rather than lowered to something weaker. **Two emission details that are each a trap closed.** The body counts a *dependent* column, never `COUNT(*)`: a `LEFT JOIN` still produces one output row for an unmatched left row, so `COUNT(*)` answers 1 for a customer with no orders at all and the check would pass on precisely the rows it exists to find. And the dependent side is `@this_model` rather than a named relation — the macro is the one reference SQLMesh rewrites inside an AUDIT body (D29), so naming the relation resolved to the virtual layer *and* put the model into its own `depends_on`, which is how the first cut emitted it. The referenced side is a sibling and is declared in `depends_on`, the trap D40 closed for step audits. Verified by a real SQLMesh plan on a fixture added to the e2e tier for it: the comment above `step_resolution` there argues that nothing else loads SQLMesh and that the gap hid three defects in a row, and this is the same shape — an audit body joining a sibling, with a `depends_on` that exists only because of the audit. dbt refuses the project (its tests are predicates, with no grouped cross-relation form); Cube is not asked, because it builds nothing (S-0034/D-52). **Cost:** `ProjectIR` gains a field, so every fingerprint moves. **Not closed:** the check counts rows that *reached* silver, so a referenced row quarantined by its own rules reads as absent — right for "has an order", wrong for a check somebody phrases as "exists", and named here rather than discovered.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/guardrails/quality.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/lower.py` `src/bloomery/spec/entity.py` `tests/e2e/test_sqlmesh_replan.py` `tests/fixtures/coverage_check/entity_model.yaml` `tests/fixtures/dirty_corpus/entity_model.yaml` `tests/unit/test_fixtures.py`

### S-0033/D-91 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-11)* **A `coverage:` check's endpoints must have relations, and D90 checked neither.** `coverage_owner` documented itself "total by construction: the guardrail stage refuses an unresolvable name before emission runs" — true of the relationship *name* and of nothing else. Two holes, both found in review. A **referenced** entity that is declared but unmapped reached `_referenced_key`'s `next(...)` and raised a bare `StopIteration` mid-emission: an unbatched error after the guardrail stage had reported clean, exactly the shape `_resolve_side` refuses for reconcile. A **step-produced dependent** entity is worse than a crash — the emitter skips those in the entity loop, so the audit is built and attached to no model, and the check reports clean because it never runs. Both are now guardrail refusals, the first reusing `_side_entities` (which already models "has a relation" including step outputs) rather than inventing a second notion of it.

- Paths: `src/bloomery/emit/lower/reconcile.py` `src/bloomery/guardrails/quality.py` `tests/unit/test_quality/test_coverage.py`

### S-0033/D-95 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-12)* **An `expression` rule is a predicate over the entity's own columns — enforced, not merely documented.** `ExpressionRule.expr` was a bare string, parsed and spliced into the silver model with nothing checking it: the one authored-SQL surface in the framework with no resolution step, while every neighbour has one (`dedupe` columns D47, `reconcile` sides against a closed grammar, mart `assert` measures, recipe aliases exactly, `coverage` endpoints D91). Three refusals, each closing something **measured** rather than imagined. **A subquery**, and the reason is corruption at least as much as access: the qualifier pass that binds a bare column to the extract descends *into* a subquery, so `amt > (SELECT amt FROM other)` was emitted as `_extract.amt > (SELECT _extract.amt FROM other)` — correlated to the outer row, reading nothing from `other`. Executed on DuckDB with `amt` 10 against 1: the author's predicate is true so the rule must not fire, and it fired, flagging a good row — under `quarantine` that diverts it out of silver, which is data loss from a rule that reads correctly in the spec. A row predicate needs no subquery, and one that did could not be trusted to mean what it says; a comparison against another relation is what `reconcile:` is for. **A column the entity does not declare** — D47's own words, "a run-time binder failure on a model that compiled clean". **A qualified reference**, because the extract supplies the qualifier and a written one either names a relation the rule cannot read or shadows bloomery's. **Left open, deliberately:** the function vocabulary. `amt > pg_sleep(10)` still compiles, and narrowing that means giving expression rules a closed function list the way S-0021 gives transform chains one — a design decision about the surface, not a defect anything here demonstrated. Recorded rather than quietly widened, because the difference between "measured and fixed" and "seemed unsafe so I restricted it" is the difference this corpus is written to preserve.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `tests/unit/test_spec/test_sql_text.py`

### S-0034/D-41 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-08, M13 re-audit; built by D49)* **D36 claimed more than shipped: metrics and `reconcile` still cannot reference a step output.** §5.8 names "downstream mappings, marts, and metrics"; marts work and metrics do not — metric resolution keys on *mappings*, and a step entity has none, so a measure over a step column is `unreachable metric … no mapped derivation path`. `reconcile` refuses them too, for the same reason. Both fail loud rather than silently, so this is a documentation defect and not a correctness one — but the RFC row is the authority (CLAUDE.md), and a row claiming more than the code does is the kind of drift the corpus exists to prevent. D36 is narrowed to marts and downstream models; metrics and reconcile over step outputs are the next increment, named like D39 names quality rules.

- Paths: `src/bloomery/guardrails/quality.py` `tests/unit/test_steps/test_step_canonicals.py`

### S-0034/D-49 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-09)* **D41 is built: metrics and `reconcile` reach step outputs, through a declared canonical link.** What was missing was a *surface*, not a mechanism. A metric is reachable iff every leaf of its `requires` closure is **available**, and a canonical field is available iff something draws a `canonical` edge to it — which only mapped entity fields could. So a step's columns were never available and any metric over one was unreachable, for a reason narrower than D41's own wording ("metric resolution keys on mappings") suggested. `StepWiring` gains `canonical: {<output>: {<column>: <canonical_field>}}`. On the **wiring**, not in the manifest: canonical names are the authored spec's vocabulary, and a manifest naming them could not be reused by a second project spelling them differently — the fork §5.7 exists to refuse. Never inferred from a matching column name, which is D43's argument about references applied to the same temptation. Nothing about metric resolution changed: the link draws the ordinary `canonical` edge and reachability follows. `reconcile` needed a second, unrelated repair — it resolved sides against *declared and mapped* entities, and a step output is neither, so a check naming one was refused as "declared but no mapping targets it", which is true and useless since the step writes the relation. Both kinds now answer through one `_SideEntity` view (field names and key), so the check asks what it needs rather than branching on provenance; declared-but-unmapped stays refused, which was always the real point. The refusal's wording now names both ways a relation can exist.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/resolve/graph.py` `src/bloomery/resolve/refs.py` `src/bloomery/spec/steps.py` `tests/fixtures/identity_resolution/catalog.yaml` `tests/fixtures/identity_resolution/steps.yaml` `tests/unit/test_quality/test_reconcile.py` `tests/unit/test_steps/test_step_canonicals.py` `tests/unit/test_unresolved.py`

### S-0040/D-5 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

`_CONVERT_MARKER` is removed from the currency guardrail with D4. It is the token that permits mixed-currency arithmetic; leaving it would keep a compile-time "yes" whose only outcome is a run-time failure. Consequence: `CurrencyMismatch` becomes unconditional until §5.4 ships.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/arithmetic.py` `tests/unit/test_guardrails/test_arithmetic.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-1 — `LOCKED` (Deterministic union merge)

Several mappings may target one entity; they are merged with `UNION ALL`. This replaces the refusal at `resolve/build.py:849` and keeps the promise its message makes. Consequence: `EntityIR` gains a set of source mappings where it had one, and every consumer reading "the mapping" of an entity must be revisited.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `tests/unit/test_resolve/test_build.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-14 — `LOCKED` (Deterministic union merge)

**P1 refuses `dedupe:` and `quarantine:` on a merged entity** (§5.6). The boundary is drawn at those two block-level declarations because it is exact, not approximate: every use of the per-source row identity in the silver lowering sits behind one of them — the reject projection, the conservation audit, the dedupe sort key, the replay merge — and the `on_fail: fail` audit path references it zero times. A merged entity may still carry field and row rules (`flag`/`fail`), `assert:`, `references:` and `coverage:`. Consequence: P1 ships the union to entities with no dedupe and no quarantine, which is the shape the `multi_source` fixture needs, and the two blocks return in P2.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/plan/diff.py` `tests/fixtures/multi_source/entity_model.yaml` `tests/unit/test_plan/test_diff.py` `tests/unit/test_quality/test_reconcile.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-26 — `ASSUMED` (Deterministic union merge)

**Answers D25 (`OPEN`) — option (a), and D25's blast-radius figure was wrong by an order of magnitude.** The lowered expression moves to a new column-grained `SourceColumnIR` on `SourceIR`; `ColumnIR` keeps the schema (§5.7). D25 said "37 `.columns` read sites" and estimated the cost from that; measured, **exactly 8 sites read a `ColumnIR` lowering field, in 3 files** — `plan/diff.py` (`renamed_from` ×4, `recipe_id`, `expr.sql`) and `emit/lower/silver.py` (`expr.ast()` ×2). Four of those eight are `renamed_from`, which D25 mis-assigned to the lowering half and which is declared on the EntityModel `Field`, so it does not move at all. The 37 was a count of `.columns` readers, and `.columns` readers are overwhelmingly *schema* readers — they survive untouched, which is the whole point of the split. **Real cost: two constructors where there was one, and four call sites.** The golden churn stands regardless — the IR shape moves and D17 bumps the version.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/operands.py` `src/bloomery/guardrails/stage.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/resolve/build.py` `src/bloomery/resolve/facets.py` `src/bloomery/resolve/steps.py` `src/bloomery/resolve/timeline.py` `tests/bench/test_hydration.py` `tests/support/ir_factory.py` `tests/support/plan_ir.py` `tests/unit/test_emit/test_cube.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_facets.py` `tests/unit/test_unresolved.py`

### S-0041/D-32 — `LOCKED` (Deterministic union merge)

**A rule's per-mapping dependency is projected as a branch-local column; the rule stays entity-grained (P2a).** The mechanism is not invented here — `coercible` already reads projected `_src_<rule>_<n>` aliases (`quality/predicates.py:source_alias`) rather than inline JSONPaths, because the raw paths live one level down in the extract SELECT, and P1 turned that projection site into `_branch_select`. So a fact only one branch knows already has a way to reach a rule the merged relation evaluates once. **D6 is not violated, and the reading that says it is — that projecting a verdict per branch just *is* "a rule evaluated per source" — mistakes what D6 argues.** D6 argues from the *row population* — "a rule evaluated per source would judge rows the merged relation does not contain" — and the union is `ALL`, so a branch-projected **scalar** verdict judges exactly the rows the union contains. Dedupe runs after the union and may drop a row; that row's flag is then unused, which is not a wrong answer. **The boundary is `WINDOWED_KINDS`** (`quality/predicates.py`, currently `{unique}`): a windowed verdict depends on the population and so may not be computed per branch — and it does not need to be, since its inputs are the produced column values, which D26's split already makes mapping-invariant. Consequence: `coercible` sheds its per-source alias set for one branch-computed boolean ("every source path *this branch* read was non-null"), which collapses the arity problem at the level where arity is known; `in_enum` takes the same shape rather than a second mechanism, its admissible set being the branch's own `enum_map` chain. **The tempting wrong fix is recorded so it is not re-proposed:** NULL-filling a missing `_src_` alias to make the arities agree renders `is_not_null` false, the conjunction never fires, and the rule silently stops checking on that branch — the failure D28 refuses by name, a check that quietly stops checking being worse than one that is absent.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/guardrails/quality.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/quality/lower.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/build.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_merged_cleaning.py` `tests/fixtures/multi_source_quality/mapping_legacy.yaml` `tests/support/quality_rules.py` `tests/unit/test_quality/test_lower.py` `tests/unit/test_quality/test_predicates.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-33 — `LOCKED` (Deterministic union merge)

**Every mapping of an entity opts into the quality system, or none does; disagreement is refused (P2a).** `opts_in(entity, mapping)` is a disjunction over one mapping's field-level `quality:` blocks, so two mappings can disagree about whether the entity joined the system at all — and the same predicate selects `_try_cast_shape`, so the disagreement reaches column lowering and not only rule generation. This is not the "where is it computed" question D32 answers; it is two contradictory statements by an author, and the honest response to those is a refusal naming both source paths. It also settles a **fourth** per-mapping coupling D29 did not enumerate: `_repair_bodies` (`resolve/build.py`) reads `mapping.fields[<column>].quality[].repair`, so two mappings may name different repair recipes for one column. Under agreement that is the same refusal rather than a fifth case — and the spliced body itself is invariant, since it reads the *produced* column, not a source path. Consequence: `lower_quality` may go on taking one `Mapping`. Agreement is what makes any of them the same answer, and the refusal — not a merge rule — is what makes that safe.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/resolve/build.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_resolve/test_build.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-36 — `ASSUMED` (Deterministic union merge)

**Answers D28 — `direct:` is allowed on a merged entity when *every* mapping records one for the column, and refused when they disagree.** D28 refused the combination outright and handed P2 a choice between "one shadow projection per source with a null-safe audit" and "a coverage rule in D4's shape". Measured with the refusal disabled against two mappings that *agree*, the null-safe audit is answering the wrong question: the shadow column is duplicated on the entity **and on every branch**, the reconcile audit is emitted twice, and each branch carries the other's extraction — `shop__items` projecting `$.unit_price` off a relation that does not have it. That is not a NULL-shadow problem, it is `Derivation` being built per mapping while `_shadow` returns one projection: the same per-mapping-fact-on-a-shared-node shape D26 split for `expr` and D32 for the rule inputs. So the coverage rule is the answer and the null-safe audit is unnecessary under it — under agreement no branch's shadow is NULL for want of a path, and the reconcile check keeps the meaning it has on one source: the recipe-derived value against the direct value *that row's own mapping* extracted, which is D32's principle applied to a second reader. Consequence: `Derivation` carries its source relation, `path_conflict_amendments` fans out per source like every other lowering, and disagreement is refused by D33's pattern rather than tolerated. D28's row stands unamended — its refusal is correct until this one is executed, and what it predicted is the thing this has to be read against. *Added by execution 2026-09-03 — see logs/T-0012.md (F-8), which carries the probe output.*

- Paths: `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/build.py` `tests/execution/test_path_conflict.py` `tests/fixtures/path_conflict_merged/entity_model.yaml` `tests/fixtures/path_conflict_merged/mapping_legacy.yaml` `tests/golden/test_sqlmesh_duckdb.py` `tests/unit/test_fixtures.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_resolution.py`

### S-0050/D-1 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A derived metric is `expr` over aliased inputs, each input a metric.** `inputs` is a mapping keyed by alias, not a list: the alias is the input's identity because `expr` references it, and a dict makes a duplicate alias unrepresentable rather than a validation. Consequence: `MetricIR` gains a `derived` field and the additivity guard must accept it as a decomposition.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/resolve/build.py` `src/bloomery/semantic/plan.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-5 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**`cumulative:` is lowered, and the blanket `UnsupportedCumulative` refusal is deleted rather than narrowed.** The class goes with it: a reserved-surface error whose surface is no longer reserved is a class that can only mislead. Combinations that still cannot be lowered are refused by their own named guardrails (D7).

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/planner/semantic_plan.py` `tests/execution/test_period_over_period.py` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_planner/test_metricflow_planner.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-6 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A cumulative metric is `additive` and keeps its own measure.** The additivity describes the measure, the window describes the accumulation over time. Declaring it `non_additive` would trip `NonAdditiveWithoutComponents` with nothing to decompose into, which is the guard doing its job on a metric that has misdescribed itself.

- Paths: `src/bloomery/guardrails/metrics.py` `tests/unit/test_guardrails/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-7 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**`derived:` and `cumulative:` on one metric is refused.** A derived metric has no measure and a cumulative window accumulates one; the combination names two mutually exclusive shapes, and MetricFlow has no type for it. Refused by name at the guardrail stage rather than left to produce an invalid manifest.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/metrics.py` `tests/unit/test_guardrails/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-9 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A filter's dimension is checked against every mart listing the metric, at the guardrail stage.** Not at emit: a filter naming a column no mart flattens is a *model* error, decidable from the spec, and it should fail with the batched aggregate every other model error joins. Checking every listing mart rather than the owning one avoids reaching for the ownership rule from a layer below the module that defines it, and is a superset of what correctness needs.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/errors.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/semantic/additivity.py` `tests/fixtures/period_over_period/entity_model.yaml` `tests/unit/test_guardrails/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0053/D-1 — `LOCKED` (Measure semantic types and additivity algebra)

**The aggregation vocabulary is a closed typed set, never a target-interpreted string.** `Additive`, `SemiAdditive`, `NonAdditive`, `Ratio`, `DistinctCount`, `Snapshot`. Locked because the planner, the proof rules and every emitter branch on it: an open string set makes each target the authority for what a measure means, which is the arrangement this whole sequence exists to end. Staging the *implementation* across releases is fine; encoding a future class as a string is not.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/ir/nodes.py` `src/bloomery/spec/common.py` `tests/fixtures/semantic_corpus/005-semi-additive-balance/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/005-semi-additive-balance/problem.md` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/problem.md` `tests/unit/test_guardrails/test_additivity.py` `tests/unit/test_semantic/test_rollup.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0053/D-2 — `LOCKED` (Measure semantic types and additivity algebra)

**A ratio is stored as its operands, not as a materialized quotient.** `SUM(num)/SUM(den)` and `AVG(ratio)` differ, the second is what a numeric-looking column invites, and the difference is a plausible wrong number. This is also S-0055's precondition — a derived metric spanning two branches cannot be reconstructed after the operands are gone — so reversing it later strands that document.

- Paths: `src/bloomery/emit/lower/rollups.py` `src/bloomery/errors.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/mart.py` `tests/fixtures/semantic_corpus/002-average-of-averages/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/002-average-of-averages/problem.md` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/problem.md` `tests/fixtures/semantic_corpus/008-ratio-rollup/bloomery/declared/metrics.yaml` `tests/fixtures/semantic_corpus/008-ratio-rollup/bloomery/naive/metrics.yaml` `tests/fixtures/semantic_corpus/008-ratio-rollup/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/008-ratio-rollup/problem.md` `tests/fixtures/semantic_corpus/012-rollup-recounts-identities/problem.md` `tests/unit/test_emit/test_rollups.py` `tests/unit/test_guardrails/test_additivity.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_steps/test_step_canonicals.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0053/D-5 — `ASSUMED` (Measure semantic types and additivity algebra)

**This is a consolidation of vocabulary that already exists in three places, not a greenfield model.** `Additivity` and `SemiAdditiveRule` are on the metric, `Unit` on the column, currency in a transform. Execution should expect to *move* declarations rather than invent them, and the risk is a second spelling of a fact rather than a missing one.

- Paths: `src/bloomery/guardrails/additivity.py`

### S-0053/D-7 — `ASSUMED` (Measure semantic types and additivity algebra)

**A metric declaring `ratio:` declares `additivity: ratio`, and either half without the other is refused.** Until the member was minted the only spelling was `non_additive` with a `ratio:` block beside it, which made the additivity a field the compiler read for one thing and the author wrote for another — D5's second-spelling risk, installed as the only option. This newly refuses projects accepted yesterday, which §7 and D4 licence as a breaking change carrying a migration note rather than a silent tightening. Not `LOCKED` because the one-word migration is cheap to revisit; the alternatives — deriving the class from the block, or accepting both words — both leave the resolved IR disagreeing with the document that produced it. Bloomery's own generated `quality_quarantine_rate` was the first spec the guard refused, which states D2's reason rather than excepting it (see [`logs/T-0023.md`](logs/T-0023.md), D145, D147).

- Paths: `src/bloomery/guardrails/additivity.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_guardrails/test_stage.py`

### S-0059/D-6 — `LOCKED` (Loose ends inside shipped subsystems)

The node-id collision is **refused**, not re-spelled. `Node.name` and the `lineage --node` argument are published surface, and the resolve API is not covered by the emitted-artifact stability caveat. Locks the bare `<entity>.<field>` spelling in: changing it later is a breaking change to every stored lineage id, which is exactly what this row buys.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/lineage.py` `src/bloomery/resolve/graph.py` `src/bloomery/resolve/timeline.py` `tests/unit/test_guardrails/test_lineage.py` `tests/unit/test_resolve/test_graph.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0059/D-8 — `ASSUMED` (Loose ends inside shipped subsystems)

The reservation is checked in one place over every entity name the graph can see, authored and step-synthesized alike, rather than at each of the two sites that mint names. One quantifier, one message.

- Paths: `src/bloomery/guardrails/lineage.py` `tests/unit/test_guardrails/test_lineage.py` `tests/unit/test_resolve/test_graph.py`

### S-0062/D-6 — `LOCKED` (Ownership, classification and grants)

`grants: {select: []}` and an absent `grants:` block are different. The first says no role may select; the second says bloomery has no opinion and the warehouse's grants stand.

- Paths: `src/bloomery/guardrails/classification.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0062/D-9 — `LOCKED` (Ownership, classification and grants)

**Classification composes with `grants`, not with `redact`.** §2 paired it with redaction because "`redact:` is the nearest thing" — true when this was drafted, false once phase 4 shipped the one annotation with a mechanism behind it. `redact:` governs what a reject row keeps; `classification:` governs a column that is published; the two stay orthogonal (see `logs/T-0051.md`).

- Paths: `src/bloomery/guardrails/stage.py` `tests/unit/test_classification_guard.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0062/D-10 — `LOCKED` (Ownership, classification and grants)

`secret` on a column a **published relation** carries is a refusal — a mart or a rollup, unconditionally. A published relation is the thing `secret` says this column is not part of, so the two statements cannot both hold. Independent of redaction, and of whether anything is granted.

- Paths: `pages/docs/how-to/annotate-a-spec.md` `src/bloomery/errors.py` `src/bloomery/evidence.py` `src/bloomery/guardrails/classification.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0062/D-11 — `LOCKED` (Ownership, classification and grants)

A `pii`/`secret` column reaching a relation that **admits a role its source entity does not** is a refusal — a set difference, not a superset test, so disjoint grant sets are refused too: a role that can read the mart and not the entity is the leak whether or not the mart also admits the entity's roles; an **undeclared** audience on either side is an advisory, not a refusal. Refusing the unknown case would refuse every project managing gold grants outside bloomery, and the compiler can only call a contradiction where it holds both statements.

- Paths: `pages/docs/how-to/annotate-a-spec.md` `src/bloomery/errors.py` `src/bloomery/evidence.py` `src/bloomery/guardrails/classification.py` `src/bloomery/guardrails/stage.py` `tests/unit/test_classification_guard.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0063/D-2 — `LOCKED` (Exposures and downstream consumers)

An exposure naming an undeclared metric or mart is refused. An exposure pointing at nothing reports clean, which is the failure mode the feature exists to remove.

- Paths: `pages/docs/how-to/declare-an-exposure.md` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/exposures.py` `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/graph.py` `tests/unit/test_guardrails/test_exposures.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0064/D-8 — `LOCKED` (Declared source freshness)

(Row 2A of the RFC's table.) Two mappings declaring **different** thresholds on one physical relation are refused, naming both. `_sources_artifact` emits one table entry per relation, so one of the two would be silently dropped — the same rule S-0041/D-33 applies to quality rules over a merged entity. Equal thresholds collapse and are not a conflict.

- Paths: `src/bloomery/guardrails/quality.py` `tests/unit/test_guardrails/test_quality.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0065/D-5 — `LOCKED` (Rollup marts and pre-aggregations)

An unprovable rollup is **refused**, never warned about. A rollup is read instead of the detail table, so a wrong one answers quickly and plausibly — the class this project refuses rather than approximates.

- Paths: `src/bloomery/cli/render.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/evidence.py` `src/bloomery/guardrails/stage.py` `src/bloomery/marts/rollup.py` `src/bloomery/semantic/rollup.py` `tests/fixtures/semantic_corpus/012-rollup-recounts-identities/problem.md` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0070/D-4 — `LOCKED` (Consumer-declared evidence strictness)

The refusal names how the fact was obtained and what to write instead. A message that only says "insufficient evidence" gets worked around by deleting the requirement.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/evidence.py` `src/bloomery/guardrails/stage.py` `src/bloomery/semantic/proof.py` `tests/unit/test_guardrails/test_evidence.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0075/D-1 — `LOCKED` (Mechanical imports and per-relationship provenance)

**Provenance attaches to the relationship, not to the basis kind.** `BASIS_PROVENANCE` is keyed by `DependencyBasis` value, so today every `many_to_one` in a project shares one provenance and an imported edge cannot be told from an authored one — which is why `IMPORTED_VERIFIED` has no producer and S-0070's refusal has no project that can trip it. Locked because it is the whole of what makes the grade mean anything at the point a consumer asks; reversing it makes every other row here decoration. `FunctionalDependency.via` already carries the key such a lookup needs. Proposed by execution — see [`logs/T-0053.md`](logs/T-0053.md) (D2, attempt 1).

- Paths: `pages/docs/concepts/what-bloomery-proves.md` `src/bloomery/guardrails/evidence.py` `tests/unit/test_guardrails/test_evidence.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
