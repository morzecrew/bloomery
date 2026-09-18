<!-- torve:managed tests/fixtures/evolution_v3 — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/evolution_v3/`

### S-0024/D-3 — `ASSUMED` (Plan: spec diff and change classification)

Renames are explicit only: `renamed_from: <old>` in the spec (carried as `ColumnIR.renamed_from`, an S-0020 amendment). No heuristic inference — determinism and auditability beat convenience. A stale annotation (old name absent from `old`, including `old is None`) raises `RenameTargetMissing` (`PlanError`), which forces the annotation to be dropped after one applied plan.

- Paths: `src/bloomery/errors.py` `src/bloomery/plan/diff.py` `src/bloomery/plan/model.py` `src/bloomery/spec/entity.py` `tests/fixtures/evolution_v3/entity_model.yaml` `tests/golden/schema/entity_model.json` `tests/property/test_plan_properties.py` `tests/unit/test_plan/test_diff.py` `tests/unit/test_plan/test_evolution.py`

<!-- /torve:managed -->
