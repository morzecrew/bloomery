<!-- torve:managed tests/unit/test_quality — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/unit/test_quality/`

### S-0020/D-4 — `ASSUMED` (Intermediate representation and determinism contract)

All IR collections are tuples with explicit lexicographic sort, except authored-order fields (`key`, transform chains, recipe aliases, `partition_by`).

- Paths: `src/bloomery/ir/lower.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/dedupe.py` `src/bloomery/quality/lower.py` `src/bloomery/resolve/build.py` `tests/unit/test_quality/test_dedupe_and_reject.py` `tests/unit/test_resolve/test_build.py`

### S-0020/D-5 — `ASSUMED` (Intermediate representation and determinism contract)

Floats are banned in IR and emission; `Decimal`/int only.

- Paths: `src/bloomery/cli/serialize.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/steps.py` `src/bloomery/ir/fingerprint.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/request.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/common.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `src/bloomery/steps/manifest.py` `src/bloomery/steps/splice.py` `src/bloomery/transforms/_builtins.py` `src/bloomery/typing/types.py` `tests/execution/test_as_of_join.py` `tests/execution/test_currency_convert.py` `tests/execution/test_fanout_trap.py` `tests/execution/test_marts.py` `tests/execution/test_period_over_period.py` `tests/execution/test_rollup.py` `tests/fixtures/semantic_corpus/002-average-of-averages/naive.sql` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/golden/schema/marts.json` `tests/support/planning.py` `tests/support/semantic_corpus.py` `tests/unit/test_cli.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_planner/test_request.py` `tests/unit/test_quality/test_edges.py` `tests/unit/test_spec/test_metrics.py` `tests/unit/test_spec/test_quality.py` `tests/unit/test_steps/test_lowering.py` `tests/unit/test_steps/test_manifest_and_registry.py` `tests/unit/test_typing/test_types.py`

### S-0025/D-3 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Capability mismatch behavior is fail-loud: `UnsupportedByTarget` naming entity + feature. Silent degradation is forbidden.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/spec/quality.py` `src/bloomery/transforms/_builtins.py` `tests/property/test_compile_properties.py` `tests/unit/test_emit/test_base.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_quality/test_text_rules.py` `tests/unit/test_transforms/test_builtins.py`

### S-0026/D-9 — `ASSUMED` (Testing strategy and fixture corpus)

Coverage: branch on, `fail_under=80` overall, per-package floors ratcheting up (forze pattern); `bloomery/guardrails/` is floored at 100% branch from day one.

- Paths: `src/bloomery/guardrails/quality.py` `tests/README.md` `tests/unit/test_quality/test_coverage.py`

### S-0027/D-9 — `ASSUMED` (Marts and role-playing dimensions)

(Amended for `_bloomery-metricflow-pivot.md`) Marts are the emission source for MetricFlow semantic models — one mart = exactly one semantic model (S-0030 R1); a measure-carrying mart must declare a date role (`MartMissingTimeDimension` otherwise). Marts and role-playing are *more* load-bearing after the pivot, not less.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/marts/flatten.py` `src/bloomery/quality/mart.py` `src/bloomery/resolve/graph.py` `tests/fixtures/ecom_basic/marts.yaml` `tests/fixtures/quality_precedence/entity_model.yaml` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_fixtures.py` `tests/unit/test_quality/test_mart.py` `tests/unit/test_resolve/test_graph.py`

### S-0033/D-17 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(closed by D87)* **Repair deferred out of v1** (amends rows 2 and 8 as originally drafted): dispositions v1 = `flag | quarantine | fail`; `repair` moves to §10, demand-gated on a repair-recipe contract. Constraint recorded from review (credit: cubic): when repair lands it must carry a **distinct marker** separating "repaired, now correct" from "currently flagged bad", so `has_quality_flags` keeps meaning "currently suspect".

- Paths: `tests/unit/test_quality/test_repair.py`

### S-0033/D-18 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Disposition precedence for a row failing multiple rules — severity order `fail > quarantine > flag`: any failing `fail` rule stops the run (blocking audit); else any failing `quarantine` rule diverts the row, with **all** failed rule names recorded in the reject's `failed_rules` (flag-level failures included); else flags accumulate in `_quality_flags`. Deterministic for every combination — no compile-time rejection of rule/disposition combinations needed.

- Paths: `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/quality/catalogue.py` `src/bloomery/quality/predicates.py` `tests/e2e/test_sqlmesh_replan.py` `tests/execution/test_quality_precedence.py` `tests/fixtures/quality_precedence/entity_model.yaml` `tests/support/precedence.py` `tests/unit/test_quality/test_predicates.py`

### S-0033/D-19 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Three-valued logic: each rule defines a violation predicate and fires only when it is definitively TRUE — NULL-involved comparisons evaluating to SQL `UNKNOWN` do **not** fire (`not_null`/`coercible` own nulls; declare them if nulls are invalid). Applies to `range`/`length`/`pattern`/`in_enum`/`in_set`/`expression`/`referential` — a NULL fk is not an orphan. Corrects Document 5's referential lowering: the bare `COALESCE(fk, '__unknown__')` sketch was wrong (it maps a NULL fk to the unknown member); the lowering is `CASE WHEN ref.<pk> IS NULL AND fk IS NOT NULL THEN '__unknown__' ELSE fk END`.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/predicates.py` `tests/fixtures/quality_precedence/mapping_dups.yaml` `tests/unit/test_ir/test_nodes.py` `tests/unit/test_quality/test_predicates.py`

### S-0033/D-20 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Dedupe is a total order: after `field` DESC and the `tie_break` columns, the final sort key is the stable source-row identity `_source_row_id` — the winner is unique by construction *given the metadata contract* (D21): `_source_row_id` is declared **NOT NULL and unique per source row**, an ingestion-layer obligation enforced at run time by a generated blocking audit on the metadata columns (a data property, not compile-checkable). Null ordering pinned: `NULLS LAST` on **every** sort key including `_source_row_id` (defense in depth — DESC defaults to NULLS FIRST on several engines, so an illegally-null identity must still lose, never win).

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/quality/dedupe.py` `tests/execution/test_dedupe_and_audits.py` `tests/execution/test_quality_precedence.py` `tests/fixtures/quality_precedence/entity_model.yaml` `tests/support/precedence.py` `tests/unit/test_quality/test_dedupe_and_reject.py`

### S-0033/D-23 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

`_quality_flags` **and** `failed_rules` share one physical contract: rule names identifier-constrained at parse (no escaping in any lowering); the column is never NULL (empty array / empty delimited string per `DialectFeature.ARRAY`); delimited fallback joins with `,` in lexicographic rule-name order; `_quality_ok` generated per shape; flag-set equality across lowerings asserted in the dialect-matrix tier. The reject table's `failed_rules` lowers by exactly this contract — array where `DialectFeature.ARRAY`, else the lexicographic comma-delimited string.

- Paths: `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/spec/quality.py` `tests/engines/test_merged_cleaning_engines.py` `tests/unit/test_quality/test_flags.py` `tests/unit/test_spec/test_quality.py`

### S-0033/D-56 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **The dialects a `pattern` is checked against are the shipped ports, never the registry.** `registered_dialects()` is process-global and mutable, so an extension dialect registered by an unrelated import could decide whether an existing project compiles — the ambient dependency S-0020 exists to forbid, and one no golden would catch. The checked set is the constant `PATTERN_TARGET_DIALECTS = (duckdb, postgres, trino)`, overridable by an explicit argument the caller supplies. Recorded consequence: an extension dialect is no longer checked at compile time. Checking it would mean plumbing a dialect set into `build_project_ir`, which is dialect-free by construction and right to be — a project is portable or it is not, and the guardrail stage has no target. Named as the escape hatch, not built.

- Paths: `pages/docs/how-to/add-quality-rules.md` `src/bloomery/compile.py` `src/bloomery/dialects/__init__.py` `src/bloomery/quality/pattern.py` `tests/unit/test_compile.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_quality/test_edges.py`

### S-0033/D-91 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-11)* **A `coverage:` check's endpoints must have relations, and D90 checked neither.** `coverage_owner` documented itself "total by construction: the guardrail stage refuses an unresolvable name before emission runs" — true of the relationship *name* and of nothing else. Two holes, both found in review. A **referenced** entity that is declared but unmapped reached `_referenced_key`'s `next(...)` and raised a bare `StopIteration` mid-emission: an unbatched error after the guardrail stage had reported clean, exactly the shape `_resolve_side` refuses for reconcile. A **step-produced dependent** entity is worse than a crash — the emitter skips those in the entity loop, so the audit is built and attached to no model, and the check reports clean because it never runs. Both are now guardrail refusals, the first reusing `_side_entities` (which already models "has a relation" including step outputs) rather than inventing a second notion of it.

- Paths: `src/bloomery/emit/lower/reconcile.py` `src/bloomery/guardrails/quality.py` `tests/unit/test_quality/test_coverage.py`

### S-0034/D-49 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-09)* **D41 is built: metrics and `reconcile` reach step outputs, through a declared canonical link.** What was missing was a *surface*, not a mechanism. A metric is reachable iff every leaf of its `requires` closure is **available**, and a canonical field is available iff something draws a `canonical` edge to it — which only mapped entity fields could. So a step's columns were never available and any metric over one was unreachable, for a reason narrower than D41's own wording ("metric resolution keys on mappings") suggested. `StepWiring` gains `canonical: {<output>: {<column>: <canonical_field>}}`. On the **wiring**, not in the manifest: canonical names are the authored spec's vocabulary, and a manifest naming them could not be reused by a second project spelling them differently — the fork §5.7 exists to refuse. Never inferred from a matching column name, which is D43's argument about references applied to the same temptation. Nothing about metric resolution changed: the link draws the ordinary `canonical` edge and reachability follows. `reconcile` needed a second, unrelated repair — it resolved sides against *declared and mapped* entities, and a step output is neither, so a check naming one was refused as "declared but no mapping targets it", which is true and useless since the step writes the relation. Both kinds now answer through one `_SideEntity` view (field names and key), so the check asks what it needs rather than branching on provenance; declared-but-unmapped stays refused, which was always the real point. The refusal's wording now names both ways a relation can exist.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/resolve/graph.py` `src/bloomery/resolve/refs.py` `src/bloomery/spec/steps.py` `tests/fixtures/identity_resolution/catalog.yaml` `tests/fixtures/identity_resolution/steps.yaml` `tests/unit/test_quality/test_reconcile.py` `tests/unit/test_steps/test_step_canonicals.py` `tests/unit/test_unresolved.py`

### S-0040/D-11 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

The FX rate relation declares **both** interval ends (`valid_from` and `valid_to`), never `valid_from` alone. One end is not an interval: a fact row would match every rate at or before its anchor and the conversion would fan out. Deriving the upper bound with `LEAD(valid_from)` is rejected — it makes every conversion a window function over the whole rate table, and it extends the newest rate to infinity, so a stale feed converts at last week's rate instead of failing. Consequence: a gap in the rate table is a *miss*, taking D9's `unknown_member` disposition, rather than silently resolving to a neighbour.

- Paths: `src/bloomery/transforms/_builtins.py` `tests/execution/test_currency_convert.py` `tests/fixtures/currency_convert/catalog.yaml` `tests/unit/test_emit/test_currency_convert.py` `tests/unit/test_quality/test_lower.py` `tests/unit/test_spec/test_catalog.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-14 — `LOCKED` (Deterministic union merge)

**P1 refuses `dedupe:` and `quarantine:` on a merged entity** (§5.6). The boundary is drawn at those two block-level declarations because it is exact, not approximate: every use of the per-source row identity in the silver lowering sits behind one of them — the reject projection, the conservation audit, the dedupe sort key, the replay merge — and the `on_fail: fail` audit path references it zero times. A merged entity may still carry field and row rules (`flag`/`fail`), `assert:`, `references:` and `coverage:`. Consequence: P1 ships the union to entities with no dedupe and no quarantine, which is the shape the `multi_source` fixture needs, and the two blocks return in P2.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/plan/diff.py` `tests/fixtures/multi_source/entity_model.yaml` `tests/unit/test_plan/test_diff.py` `tests/unit/test_quality/test_reconcile.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-29 — `LOCKED` (Deterministic union merge)

**§5.6's consequence was wider than its argument — P1 refuses the whole quality system on a merged entity, not only `dedupe:` and `quarantine:`.** D14's *reason* survives measurement: every use of `_source_row_id` in the silver lowering does sit behind one of those two blocks. Its *consequence* — "a merged entity may therefore still carry field rules and row rules" — does not follow, because the row identity is not the only per-mapping coupling. **The rule lowering itself is per mapping, and sits behind neither block**: `lower_quality(entity, mapping, …)` takes one `Mapping` (`resolve/build.py`), so `mappings[0]` would silently win; `opts_in(entity, mapping)` is true when *that mapping's* fields carry `quality:`, so two mappings can disagree about whether the entity joined the system at all — and that same predicate selects `_try_cast_shape`, so opt-in reaches column lowering; a generated `coercible` rule carries `field_sources(mapping, column)`, *that mapping's* raw JSONPaths, which the extract projects per branch, so source B's branch would have to read source A's `$.a.b` off a relation that need not have it, for a rule evaluated once over the merged relation; generated `enum` spellings come from the mapping's transform chain the same way; and `check_quality`'s `by_target` dict keeps the **last** mapping per target, so every per-mapping quality guardrail would check one of N. The boundary D14 wanted — exact rather than approximate — is therefore `opts_in`, one predicate that already exists and already decides this. **`assert:`, `references:` and `coverage:` survive**, measured rather than assumed: `lower_asserts` reads the entity model and the draft IR and never a mapping, and the relationship-driven checks are entity-model-shaped. Consequence: P1 ships the union to entities outside the quality system, which is the shape the `multi_source` fixture needs, and P2 restores the system to a merged entity as one piece rather than in two unrelated halves. *Added by execution 2026-08-16 — see logs/T-0004.md (V-001, attempt 1).*

- Paths: `tests/unit/test_quality/test_reconcile.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-32 — `LOCKED` (Deterministic union merge)

**A rule's per-mapping dependency is projected as a branch-local column; the rule stays entity-grained (P2a).** The mechanism is not invented here — `coercible` already reads projected `_src_<rule>_<n>` aliases (`quality/predicates.py:source_alias`) rather than inline JSONPaths, because the raw paths live one level down in the extract SELECT, and P1 turned that projection site into `_branch_select`. So a fact only one branch knows already has a way to reach a rule the merged relation evaluates once. **D6 is not violated, and the reading that says it is — that projecting a verdict per branch just *is* "a rule evaluated per source" — mistakes what D6 argues.** D6 argues from the *row population* — "a rule evaluated per source would judge rows the merged relation does not contain" — and the union is `ALL`, so a branch-projected **scalar** verdict judges exactly the rows the union contains. Dedupe runs after the union and may drop a row; that row's flag is then unused, which is not a wrong answer. **The boundary is `WINDOWED_KINDS`** (`quality/predicates.py`, currently `{unique}`): a windowed verdict depends on the population and so may not be computed per branch — and it does not need to be, since its inputs are the produced column values, which D26's split already makes mapping-invariant. Consequence: `coercible` sheds its per-source alias set for one branch-computed boolean ("every source path *this branch* read was non-null"), which collapses the arity problem at the level where arity is known; `in_enum` takes the same shape rather than a second mechanism, its admissible set being the branch's own `enum_map` chain. **The tempting wrong fix is recorded so it is not re-proposed:** NULL-filling a missing `_src_` alias to make the arities agree renders `is_not_null` false, the conjunction never fires, and the rule silently stops checking on that branch — the failure D28 refuses by name, a check that quietly stops checking being worse than one that is absent.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/guardrails/quality.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/quality/lower.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/build.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_merged_cleaning.py` `tests/fixtures/multi_source_quality/mapping_legacy.yaml` `tests/support/quality_rules.py` `tests/unit/test_quality/test_lower.py` `tests/unit/test_quality/test_predicates.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
