<!-- torve:managed tests/unit/test_plan — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/unit/test_plan/`

### S-0024/D-2 — `ASSUMED` (Plan: spec diff and change classification)

`plan(old_ir | None, new_ir)` is a pure structural diff of two `ProjectIR`s — no external lineage, no I/O. `plan(None, ir)` = all ADDITIVE (initial deploy); `plan(ir, ir)` = empty, property-tested (S-0026).

- Paths: `src/bloomery/plan/diff.py` `src/bloomery/plan/model.py` `tests/unit/test_cli.py` `tests/unit/test_plan/test_diff.py` `tests/unit/test_plan/test_exposures.py` `tests/unit/test_plan/test_quality_changes.py` `tests/unit/test_plan/test_step_changes.py` `tests/unit/test_steps/test_step_entities.py`

### S-0024/D-3 — `ASSUMED` (Plan: spec diff and change classification)

Renames are explicit only: `renamed_from: <old>` in the spec (carried as `ColumnIR.renamed_from`, an S-0020 amendment). No heuristic inference — determinism and auditability beat convenience. A stale annotation (old name absent from `old`, including `old is None`) raises `RenameTargetMissing` (`PlanError`), which forces the annotation to be dropped after one applied plan.

- Paths: `src/bloomery/errors.py` `src/bloomery/plan/diff.py` `src/bloomery/plan/model.py` `src/bloomery/spec/entity.py` `tests/fixtures/evolution_v3/entity_model.yaml` `tests/golden/schema/entity_model.json` `tests/property/test_plan_properties.py` `tests/unit/test_plan/test_diff.py` `tests/unit/test_plan/test_evolution.py`

### S-0024/D-6 — `ASSUMED` (Plan: spec diff and change classification)

`Plan` = ordered `Change` tuple + `BackfillScope` + `downstream_impact` (from `MetricIR.depends_on`) + `has_changes`/`breaking` conveniences. All ordering lexicographic per S-0020 — plans are byte-comparable.

- Paths: `src/bloomery/plan/model.py` `tests/unit/test_plan/test_exposures.py`

### S-0024/D-7 — `ASSUMED` (Plan: spec diff and change classification)

Entity-level `grain`/`key`/`scd`/`materialization` changes are BREAKING at the entity subject (they redefine the row); column diffs are still reported alongside. Type changes follow the S-0021 lattice: widening = WIDENING, narrowing (incl. optional→required) and new required fields = BREAKING.

- Paths: `src/bloomery/plan/diff.py` `tests/fixtures/evolution_v5/entity_model.yaml` `tests/unit/test_plan/test_diff.py`

### S-0033/D-2 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

`OnFail = flag | quarantine | fail` (v1 — `repair` deferred, decision 17; landed in D87), explicit per rule, never a global default. Deliberately no `drop`: quarantine is drop plus recoverability; deletion happens via retention policy, with a paper trail.

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/spec/quality.py` `tests/unit/test_ir/test_nodes.py` `tests/unit/test_plan/test_quality_changes.py` `tests/unit/test_spec/test_quality.py`

### S-0033/D-57 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **`range` bounds are exact or refused.** `min`/`max` typed `int

- Paths: `src/bloomery/marts/flatten.py` `tests/unit/test_plan/test_quality_changes.py`

### S-0034/D-6 — `ASSUMED` (The step registry: referenced implementations)

`runtime_lock` is part of step identity: a dependency bump changes the step fingerprint and classifies `RESTATING`, triggering backfill (S-0024 amendment). Invisible — and wrong — without the lock.

- Paths: `src/bloomery/plan/diff.py` `tests/unit/test_plan/test_step_changes.py`

### S-0034/D-11 — `ASSUMED` (The step registry: referenced implementations)

Steps are IR and DAG citizens: `StepIR` nodes (ref, version, kind, determinism, `runtime_lock`, typed inputs/outputs) in a new `ProjectIR.steps` tuple (S-0020 amendment) and first-class `step.<ref>` DAG nodes (S-0022 amendment). Fingerprint coverage is the whole mechanism: any manifest change — `runtime_lock` included — shifts `project_fingerprint`; `plan()` sees an ordinary structural IR diff (no special-casing); the S-0031 hydration cache self-invalidates via `HydrationKey.spec_fingerprint`, no new key component.

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/resolve/graph.py` `tests/unit/test_plan/test_step_changes.py` `tests/unit/test_resolve/test_graph.py`

### S-0041/D-9 — `ASSUMED` (Deterministic union merge)

Change classification needs no new class — but adding a mapping to a single-source entity is **two** `ADDITIVE` changes, rows and the `_source` column, not one. `_source` exists only on merged entities (D7), so the column set does depend on mapping count; emitting it everywhere to avoid that would churn every golden in the corpus for a constant. Verify the removal rows during implementation: dropping to one mapping removes `_source`, and anything reading it must trip the existing contract check.

- Paths: `tests/unit/test_plan/test_diff.py` `tests/unit/test_resolve/test_build.py`

### S-0041/D-14 — `LOCKED` (Deterministic union merge)

**P1 refuses `dedupe:` and `quarantine:` on a merged entity** (§5.6). The boundary is drawn at those two block-level declarations because it is exact, not approximate: every use of the per-source row identity in the silver lowering sits behind one of them — the reject projection, the conservation audit, the dedupe sort key, the replay merge — and the `on_fail: fail` audit path references it zero times. A merged entity may still carry field and row rules (`flag`/`fail`), `assert:`, `references:` and `coverage:`. Consequence: P1 ships the union to entities with no dedupe and no quarantine, which is the shape the `multi_source` fixture needs, and the two blocks return in P2.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/plan/diff.py` `tests/fixtures/multi_source/entity_model.yaml` `tests/unit/test_plan/test_diff.py` `tests/unit/test_quality/test_reconcile.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0051/D-2 — `LOCKED` (The reject table on a merged entity)

**`source_relation`, `mapping`, `mapping_version` and `reject_id` are projected per union branch.** They are true of a branch and were only ever true of a model because there was one branch. `reject_id` moves with them out of necessity rather than symmetry: its first argument is the branch's relation name, which the union erases. Consequence: `reject_select` reads four more columns off the extract subquery and reads no `SourceIR` at all.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/plan/diff.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_merged_cleaning.py` `tests/unit/test_plan/test_diff.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0063/D-7 — `LOCKED` (Exposures and downstream consumers)

(Row 2A of the RFC's table.) `affected_exposures` walks marts as well as metrics. The metric-only walk is the shortcut that omits exactly the mart-only exposure, and an impact report that is confidently incomplete is worse than none.

- Paths: `src/bloomery/plan/diff.py` `tests/unit/test_plan/test_exposures.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
