<!-- torve:managed tests/fixtures/cross_mart_branches — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/cross_mart_branches/`

### S-0055/D-12 — `LOCKED` (Multi-grain aggregate-then-join query planning)

**A dimension is the same dimension across branches when its provenance triple matches — `(source_entity, source_column, ref)` — never when its name does.** This is §2's "proven common join key" made checkable, and `_same_source` in `planner/coverage.py` already compares that triple for P2's refusals. A branch that cannot produce a requested dimension by identity gets P2's `not_flattened` refusal and its flatten remediation, never a join to go and fetch it. Name equality is not identity, which is D5's reason applied to the key instead of to the filter.

- Paths: `src/bloomery/planner/compose.py` `src/bloomery/planner/coverage.py` `src/bloomery/planner/explain.py` `tests/fixtures/cross_mart_branches/entity_model.yaml` `tests/fixtures/cross_mart_branches/marts.yaml` `tests/unit/test_planner/test_metricflow_planner.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
