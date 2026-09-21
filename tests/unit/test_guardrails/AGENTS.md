<!-- torve:managed tests/unit/test_guardrails — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/unit/test_guardrails/`

### S-0002/D-1 — `LOCKED` (Multi-project composition) — implementation: partial

The boundary is an explicit export list, never "everything public by default": an entity, a mart or a metric may be named on it, grouped by kind, and a name absent from it is not exported however public it looks from inside the project

- Paths: `src/bloomery/spec/exports.py` `src/bloomery/guardrails/exports.py` `tests/unit/test_spec/test_exports.py` `tests/unit/test_guardrails/test_exports.py`
- Consequence: A project that exports its whole spec has no boundary, and its first refactor breaks every consumer; an export naming something the project does not declare is refused with `DanglingExport`, so the list is an assertion rather than a claim
- Check: `uv run pytest tests/unit/test_spec/test_exports.py tests/unit/test_guardrails/test_exports.py -q` (shadow; runs as `decision:S-0002/D-1`, no log entry owed)

### S-0002/D-6 — `ASSUMED` (Multi-project composition) — implementation: partial

Lineage node ids gain a project component for imported nodes only; a local node keeps its `<kind>.<name>` spelling

- Paths: `src/bloomery/resolve/graph.py` `src/bloomery/resolve/lineage.py` `src/bloomery/guardrails/lineage.py` `tests/unit/test_resolve/test_lineage.py` `tests/unit/test_guardrails/test_lineage.py`
- Consequence: Every existing id and every published citation stays valid — a node name is public surface and `bloomery lineage --node metric.gross_revenue` is a documented invocation — while two projects' graphs can be composed without collision

### S-0019/D-10 — `ASSUMED` (Spec layer and error model)

(Amended for `_bloomery-metricflow-pivot.md`) `metric_time` is a reserved dimension/field name, rejected at spec validation with a clear message (S-0030 R4). The `Metric` model reserves optional `cumulative:` (window / grain_to_date) and derived-expression forms lowered per S-0030's mapping table; both are additive spec surface, parse-validated only.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/spec/common.py` `src/bloomery/spec/entity.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `tests/golden/schema/catalog.json` `tests/golden/schema/entity_model.json` `tests/golden/schema/marts.json` `tests/golden/schema/metrics.json` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_spec/test_metrics.py`

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

### S-0030/D-8 — `ASSUMED` (MetricFlow backend: manifest emitter and planner adapter)

Filters (Jinja `where_constraints`) are the highest-risk surface: values never interpolated raw — typed per-dialect literal renderer or bind parameters; dimension names only from validated `DimensionRef`s via `names.py`; values type-checked against the dimension (`FilterTypeMismatch`); `contains`/`like` escape wildcards. Adversarial fuzz property test (injection strings, template syntax, unicode quotes, newlines) asserts parsed-SQL predicate structure unchanged and scanned relations exactly the expected mart — **merge-blocking**. *(Superseded by D16 — see §5.6 note.)*

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/planner/filters.py` `src/bloomery/planner/request.py` `tests/property/test_planner_properties.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_planner/test_filters.py`

### S-0032/D-5 — `ASSUMED` (Query vocabulary: filters, sort, pagination)

**D-Q5:** string-carrier scalars — `str` operands on ordering operators are parsed and validated against the resolved dimension's `LogicalType` at request-validation time, before any rendering: invalid → `FilterTypeMismatch`, non-finite → `InvalidLiteral`; **no SQL cast is ever emitted** (rendered literals are already in the dimension's type). `NaN`/`Infinity`/`-Infinity` refused even though they parse as `Decimal` — `lt "NaN"` fails open on Postgres and matches every row. `UUID` renders as a string literal against string-typed dimensions; no UUID `LogicalType` is added.

- Paths: `src/bloomery/errors.py` `src/bloomery/planner/filters.py` `src/bloomery/planner/parse.py` `src/bloomery/planner/request.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `tests/execution/test_period_over_period.py` `tests/property/test_planner_properties.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_planner/test_filters.py` `tests/unit/test_planner/test_request.py` `tests/unit/test_spec/test_metrics.py` `tests/unit/test_spec/test_quality.py`

### S-0033/D-3 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Coercion failure is a rule: transform chains lower to failure-marker form (`TRY_CAST`-style per dialect); the implicit, overridable `coercible` rule (default `quarantine`) disposes of it. Retires `Mapping.on_unmapped_enum` (S-0019 amendment — absorbed into `in_enum`/`coercible`) and supersedes S-0025/D-7's never-implemented emitter convention with the modeled reject table.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/guardrails/operands.py` `src/bloomery/quality/predicates.py` `src/bloomery/spec/mapping.py` `src/bloomery/spec/quality.py` `src/bloomery/transforms/_builtins.py` `tests/execution/test_path_conflict.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_spec/test_mapping.py`

### S-0033/D-10 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

One `<entity>__reject` table per entity with the §5.6 schema (stable sha256 `reject_id` for idempotent replay). Retention is **required** whenever any quarantine disposition exists — missing retention is a compile error; retention deletes **all** reject rows on expiry (unresolved measured from `last_seen`, resolved from `resolved_at`) and is the only deleter — replay never deletes. `redact:` paths apply at write time and must not intersect any path the entity's mappings read (`from` paths, recipe aliases included) — an intersecting redact is the compile error `RedactionConflict`. Bloomery emits the reject/replay artifacts and never executes them.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/errors.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `tests/engines/test_merged_cleaning_engines.py` `tests/fixtures/multi_source_quality/entity_model.yaml` `tests/unit/test_guardrails/test_quality.py`

### S-0033/D-12 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

`gold.mart_data_quality` is an ordinary semantic model (`run_date` as time dimension); quarantine rate is a `MetricRequest`. Reject tables are never exposed through `MetricRequest`. Deliberate divergence: no `tenant_id` column (Document 5 §7.5 has one) — hard invariant #3 and the tenant guard forbid it; `NamingPolicy` namespaces are the only tenant seam.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/quality/mart.py` `tests/execution/test_quality_mart.py` `tests/unit/test_guardrails/test_quality.py`

### S-0033/D-49 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **`in_enum`'s rule identity carries the chain's source spellings, not only its `enum_map` targets.** `enum_map` passes an *unmapped* value through untouched, so the raw values `in_enum` admits are the mapped spellings **plus** the targets. A widening therefore has two shapes — a new target, or a new spelling for an existing target (`PAYED → paid`) — and only the first changed a rule param, so `plan()` reported `replay_scope = ()` for the second while rows sat in the reject table on that rule's account. §6's replay test used only the shape that worked, so the gap was untested. The lowering now emits `spelling_NNNN` params beside `value_NNNN`. The pairing is deliberately *not* carried: re-pointing `a → x` to `a → y` when both are already targets changes the column's value — which the column diff reports — but changes nothing about which raw values this rule admits.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/quality/lower.py` `tests/unit/test_guardrails/test_quality.py`

### S-0033/D-56 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **The dialects a `pattern` is checked against are the shipped ports, never the registry.** `registered_dialects()` is process-global and mutable, so an extension dialect registered by an unrelated import could decide whether an existing project compiles — the ambient dependency S-0020 exists to forbid, and one no golden would catch. The checked set is the constant `PATTERN_TARGET_DIALECTS = (duckdb, postgres, trino)`, overridable by an explicit argument the caller supplies. Recorded consequence: an extension dialect is no longer checked at compile time. Checking it would mean plumbing a dialect set into `build_project_ir`, which is dialect-free by construction and right to be — a project is portable or it is not, and the guardrail stage has no target. Named as the escape hatch, not built.

- Paths: `pages/docs/how-to/add-quality-rules.md` `src/bloomery/compile.py` `src/bloomery/dialects/__init__.py` `src/bloomery/quality/pattern.py` `tests/unit/test_compile.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_quality/test_edges.py`

### S-0033/D-80 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, PR #7 review, self-audit of the fixes)* **The dedupe order outranks the nulling-chain skip, and a key column has a chain too.** D73's skip, applied uniformly, deleted the one `coercible` rule §5.4/D6 *forces*: on a column the dedupe order reads, an uncastable sort value leaves the order undefined, so the rule is FAIL-disposition and load-bearing rather than a convenience. The skip removed it and its blocking audit with no diagnostic, and `_check_dedupe_disposition` (which demands `on_fail: fail` there) plus D73's own refusal of an authored `coercible` on such a chain left the author refused coming and going — a false positive traded for a silently nondeterministic entity, which is the worse of the two. Dedupe-order columns are now exempt from both halves. Separately, `nullifying_steps` read `mapped_fields`' `None` for a key column as "no chain", but `KeyField` carries a `transform`: the key kept the exact false positive D73 removes, in its worst form, since a key has no `quality:` surface to declare the rule away and no guardrail could refuse it either. The key chain is now looked up. Also fixed here: `to_string` after `enum_map` is the identity on a string and was over-refused by D72; and an `in_enum` on a chain with **no** `enum_map` lowered to `NOT col IN ()` — invalid SQL everywhere and a rule rejecting every row — now refused in the same check, which is its natural home.

- Paths: `tests/fixtures/multi_source_quality/entity_model.yaml` `tests/unit/test_guardrails/test_quality.py`

### S-0040/D-1 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

Flattening an entity with `scd: type2` into a mart is **refused** at compile time, not silently emitted and not silently filtered to the current version. The join has no validity predicate and the relation has one row per version, so the emitted mart multiplies the base grain while every guardrail passes. Consequence: the only shipped way to use a historical dimension in a mart is a `type1` current-view entity built from it, until §5.3 exists.

- Paths: `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `tests/fixtures/scd2_mart_refusal/entity_model.yaml` `tests/fixtures/semantic_corpus/003-scd2-unqualified-join/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/003-scd2-unqualified-join/problem.md` `tests/golden/refusals/example-scd2-flatten.txt` `tests/golden/refusals/scd2_mart_refusal.txt` `tests/unit/test_fixtures.py` `tests/unit/test_guardrails/test_stage.py` `tests/unit/test_marts/test_flatten.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0040/D-2 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

A mart whose **`base`** is `scd: type2` is refused on the same account. There is no fan-out, but the declared `grain:` claims one row per entity while the relation holds one per version, so every measure counts revisions. Refusing both sides keeps "a mart's grain is what it says" true without exception.

- Paths: `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `tests/fixtures/scd2_as_of/marts.yaml` `tests/fixtures/scd2_mart_refusal/entity_model.yaml` `tests/fixtures/scd2_replay/marts.yaml` `tests/golden/refusals/scd2_mart_refusal.txt` `tests/unit/test_fixtures.py` `tests/unit/test_guardrails/test_stage.py` `tests/unit/test_marts/test_flatten.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0040/D-5 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

`_CONVERT_MARKER` is removed from the currency guardrail with D4. It is the token that permits mixed-currency arithmetic; leaving it would keep a compile-time "yes" whose only outcome is a run-time failure. Consequence: `CurrencyMismatch` becomes unconditional until §5.4 ships.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/arithmetic.py` `tests/unit/test_guardrails/test_arithmetic.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-12 — `LOCKED` (Deterministic union merge)

`(target, source)` is **unique**: two mappings for one entity may not read the same source relation. Lexicographic ordering needs a total order and two branches on one relation tie, which would leave branch order undefined, `_source` ambiguous, and the collision audit unable to name a branch. Consequence: reading one relation twice is expressed as one mapping with a filter, not two mappings.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/resolve/build.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_resolve/test_build.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-26 — `ASSUMED` (Deterministic union merge)

**Answers D25 (`OPEN`) — option (a), and D25's blast-radius figure was wrong by an order of magnitude.** The lowered expression moves to a new column-grained `SourceColumnIR` on `SourceIR`; `ColumnIR` keeps the schema (§5.7). D25 said "37 `.columns` read sites" and estimated the cost from that; measured, **exactly 8 sites read a `ColumnIR` lowering field, in 3 files** — `plan/diff.py` (`renamed_from` ×4, `recipe_id`, `expr.sql`) and `emit/lower/silver.py` (`expr.ast()` ×2). Four of those eight are `renamed_from`, which D25 mis-assigned to the lowering half and which is declared on the EntityModel `Field`, so it does not move at all. The 37 was a count of `.columns` readers, and `.columns` readers are overwhelmingly *schema* readers — they survive untouched, which is the whole point of the split. **Real cost: two constructors where there was one, and four call sites.** The golden churn stands regardless — the IR shape moves and D17 bumps the version.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/operands.py` `src/bloomery/guardrails/stage.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/resolve/build.py` `src/bloomery/resolve/facets.py` `src/bloomery/resolve/steps.py` `src/bloomery/resolve/timeline.py` `tests/bench/test_hydration.py` `tests/support/ir_factory.py` `tests/support/plan_ir.py` `tests/unit/test_emit/test_cube.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_facets.py` `tests/unit/test_unresolved.py`

### S-0041/D-33 — `LOCKED` (Deterministic union merge)

**Every mapping of an entity opts into the quality system, or none does; disagreement is refused (P2a).** `opts_in(entity, mapping)` is a disjunction over one mapping's field-level `quality:` blocks, so two mappings can disagree about whether the entity joined the system at all — and the same predicate selects `_try_cast_shape`, so the disagreement reaches column lowering and not only rule generation. This is not the "where is it computed" question D32 answers; it is two contradictory statements by an author, and the honest response to those is a refusal naming both source paths. It also settles a **fourth** per-mapping coupling D29 did not enumerate: `_repair_bodies` (`resolve/build.py`) reads `mapping.fields[<column>].quality[].repair`, so two mappings may name different repair recipes for one column. Under agreement that is the same refusal rather than a fifth case — and the spliced body itself is invariant, since it reads the *produced* column, not a source path. Consequence: `lower_quality` may go on taking one `Mapping`. Agreement is what makes any of them the same answer, and the refusal — not a merge rule — is what makes that safe.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/resolve/build.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_resolve/test_build.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-36 — `ASSUMED` (Deterministic union merge)

**Answers D28 — `direct:` is allowed on a merged entity when *every* mapping records one for the column, and refused when they disagree.** D28 refused the combination outright and handed P2 a choice between "one shadow projection per source with a null-safe audit" and "a coverage rule in D4's shape". Measured with the refusal disabled against two mappings that *agree*, the null-safe audit is answering the wrong question: the shadow column is duplicated on the entity **and on every branch**, the reconcile audit is emitted twice, and each branch carries the other's extraction — `shop__items` projecting `$.unit_price` off a relation that does not have it. That is not a NULL-shadow problem, it is `Derivation` being built per mapping while `_shadow` returns one projection: the same per-mapping-fact-on-a-shared-node shape D26 split for `expr` and D32 for the rule inputs. So the coverage rule is the answer and the null-safe audit is unnecessary under it — under agreement no branch's shadow is NULL for want of a path, and the reconcile check keeps the meaning it has on one source: the recipe-derived value against the direct value *that row's own mapping* extracted, which is D32's principle applied to a second reader. Consequence: `Derivation` carries its source relation, `path_conflict_amendments` fans out per source like every other lowering, and disagreement is refused by D33's pattern rather than tolerated. D28's row stands unamended — its refusal is correct until this one is executed, and what it predicted is the thing this has to be read against. *Added by execution 2026-09-03 — see logs/T-0012.md (F-8), which carries the probe output.*

- Paths: `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/build.py` `tests/execution/test_path_conflict.py` `tests/fixtures/path_conflict_merged/entity_model.yaml` `tests/fixtures/path_conflict_merged/mapping_legacy.yaml` `tests/golden/test_sqlmesh_duckdb.py` `tests/unit/test_fixtures.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_resolution.py`

### S-0049/D-3 — `LOCKED` (Mapping identity)

**`document` is set by the loader and is not part of the YAML vocabulary.** A document declaring its own name is a second source of truth that can disagree with the first. Consequence: `Mapping` cannot be constructed from YAML alone in a test without the loader — which is already how every test builds one.

- Paths: `src/bloomery/spec/common.py` `src/bloomery/spec/mapping.py` `tests/property/test_schema_agreement.py` `tests/unit/test_guardrails/test_operands.py` `tests/unit/test_spec/test_mapping.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

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

### S-0053/D-7 — `ASSUMED` (Measure semantic types and additivity algebra)

**A metric declaring `ratio:` declares `additivity: ratio`, and either half without the other is refused.** Until the member was minted the only spelling was `non_additive` with a `ratio:` block beside it, which made the additivity a field the compiler read for one thing and the author wrote for another — D5's second-spelling risk, installed as the only option. This newly refuses projects accepted yesterday, which §7 and D4 licence as a breaking change carrying a migration note rather than a silent tightening. Not `LOCKED` because the one-word migration is cheap to revisit; the alternatives — deriving the class from the block, or accepting both words — both leave the resolved IR disagreeing with the document that produced it. Bloomery's own generated `quality_quarantine_rate` was the first spec the guard refused, which states D2's reason rather than excepting it (see `logs/T-0023.md` (`logs/T-0023.md`), D145, D147).

- Paths: `src/bloomery/guardrails/additivity.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_guardrails/test_stage.py`

### S-0059/D-6 — `LOCKED` (Loose ends inside shipped subsystems)

The node-id collision is **refused**, not re-spelled. `Node.name` and the `lineage --node` argument are published surface, and the resolve API is not covered by the emitted-artifact stability caveat. Locks the bare `<entity>.<field>` spelling in: changing it later is a breaking change to every stored lineage id, which is exactly what this row buys.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/lineage.py` `src/bloomery/resolve/graph.py` `src/bloomery/resolve/timeline.py` `tests/unit/test_guardrails/test_lineage.py` `tests/unit/test_resolve/test_graph.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0059/D-8 — `ASSUMED` (Loose ends inside shipped subsystems)

The reservation is checked in one place over every entity name the graph can see, authored and step-synthesized alike, rather than at each of the two sites that mint names. One quantifier, one message.

- Paths: `src/bloomery/guardrails/lineage.py` `tests/unit/test_guardrails/test_lineage.py` `tests/unit/test_resolve/test_graph.py`

### S-0063/D-2 — `LOCKED` (Exposures and downstream consumers)

An exposure naming an undeclared metric or mart is refused. An exposure pointing at nothing reports clean, which is the failure mode the feature exists to remove.

- Paths: `pages/docs/how-to/declare-an-exposure.md` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/exposures.py` `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/graph.py` `tests/unit/test_guardrails/test_exposures.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0064/D-8 — `LOCKED` (Declared source freshness)

(Row 2A of the RFC's table.) Two mappings declaring **different** thresholds on one physical relation are refused, naming both. `_sources_artifact` emits one table entry per relation, so one of the two would be silently dropped — the same rule S-0041/D-33 applies to quality rules over a merged entity. Equal thresholds collapse and are not a conflict.

- Paths: `src/bloomery/guardrails/quality.py` `tests/unit/test_guardrails/test_quality.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0064/D-10 — `LOCKED` (Declared source freshness)

(Row 2C of the RFC's table.) **A threshold is a statement about the relation, not about the mapping that carries it.** So: the ingestion-metadata contract is required of the **declaring** mapping, because that is what asserts the relation exposes `_ingested_at`, and a sibling mapping of the same physical table has nothing to satisfy — it neither adds nor removes a column. And a mapping that omits a threshold is not disagreeing with one; it is making no statement about the relation, so the mixed case is legal. D2's "every consumer" and D2b's refusal each read as thorough and together admit **no valid configuration**: a plain entity sharing a relation with a quarantining one could neither declare (D2 refuses it) nor omit (D2b refuses it), and its only escape was to declare `quarantine:` it does not want. D2a survives untouched, because two different thresholds are a real disagreement about one thing.

- Paths: `tests/unit/test_guardrails/test_quality.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0070/D-3 — `LOCKED` (Consumer-declared evidence strictness)

Absence of the annotation is byte-identical to today. Strictness that arrives unrequested is a breaking change wearing a safety feature's clothes.

- Paths: `tests/unit/test_guardrails/test_evidence.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0070/D-4 — `LOCKED` (Consumer-declared evidence strictness)

The refusal names how the fact was obtained and what to write instead. A message that only says "insufficient evidence" gets worked around by deleting the requirement.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/evidence.py` `src/bloomery/guardrails/stage.py` `src/bloomery/semantic/proof.py` `tests/unit/test_guardrails/test_evidence.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0075/D-1 — `LOCKED` (Mechanical imports and per-relationship provenance)

**Provenance attaches to the relationship, not to the basis kind.** `BASIS_PROVENANCE` is keyed by `DependencyBasis` value, so today every `many_to_one` in a project shares one provenance and an imported edge cannot be told from an authored one — which is why `IMPORTED_VERIFIED` has no producer and S-0070's refusal has no project that can trip it. Locked because it is the whole of what makes the grade mean anything at the point a consumer asks; reversing it makes every other row here decoration. `FunctionalDependency.via` already carries the key such a lookup needs. Proposed by execution — see `logs/T-0053.md` (`logs/T-0053.md`) (D2, attempt 1).

- Paths: `pages/docs/concepts/what-bloomery-proves.md` `src/bloomery/guardrails/evidence.py` `tests/unit/test_guardrails/test_evidence.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0075/D-3 — `LOCKED` (Mechanical imports and per-relationship provenance)

**No IR node gains a provenance field.** `project_fingerprint` walks the IR dataclass tree, so a field there moves every fingerprint in the corpus for projects that import nothing — S-0070 row 17's hazard, arriving from the same direction a second time. The fact is read from the authored `EntityModel` at the guardrail stage, the shape `requires_evidence` already uses.

- Paths: `src/bloomery/semantic/proof.py` `tests/unit/test_guardrails/test_evidence.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0075/D-7 — `ASSUMED` (Mechanical imports and per-relationship provenance)

**`imported_from:` is a free string naming the artifact, and its presence is the fact.** A boolean would need a second key for the refusal to name the source, and an enum invites an author to write `declared` on something they did not read (§5's alternatives). Not `LOCKED` because a second importer may want structure; a string is the cheapest thing to widen.

- Paths: `src/bloomery/spec/entity.py` `tests/unit/test_guardrails/test_evidence.py`

<!-- /torve:managed -->
