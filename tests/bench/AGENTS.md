<!-- torve:managed tests/bench — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/bench/`

### S-0041/D-26 — `ASSUMED` (Deterministic union merge)

**Answers D25 (`OPEN`) — option (a), and D25's blast-radius figure was wrong by an order of magnitude.** The lowered expression moves to a new column-grained `SourceColumnIR` on `SourceIR`; `ColumnIR` keeps the schema (§5.7). D25 said "37 `.columns` read sites" and estimated the cost from that; measured, **exactly 8 sites read a `ColumnIR` lowering field, in 3 files** — `plan/diff.py` (`renamed_from` ×4, `recipe_id`, `expr.sql`) and `emit/lower/silver.py` (`expr.ast()` ×2). Four of those eight are `renamed_from`, which D25 mis-assigned to the lowering half and which is declared on the EntityModel `Field`, so it does not move at all. The 37 was a count of `.columns` readers, and `.columns` readers are overwhelmingly *schema* readers — they survive untouched, which is the whole point of the split. **Real cost: two constructors where there was one, and four call sites.** The golden churn stands regardless — the IR shape moves and D17 bumps the version.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/operands.py` `src/bloomery/guardrails/stage.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/resolve/build.py` `src/bloomery/resolve/facets.py` `src/bloomery/resolve/steps.py` `src/bloomery/resolve/timeline.py` `tests/bench/test_hydration.py` `tests/support/ir_factory.py` `tests/support/plan_ir.py` `tests/unit/test_emit/test_cube.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_facets.py` `tests/unit/test_unresolved.py`

### S-0042/D-13 — `LOCKED` (v0.1.0 release readiness)

The perf gate runs in **two** places: informational on the scheduled lane, blocking on a release-candidate job in the tag workflow. A gate only on a schedule can run after the tag, which would satisfy D1 on paper and enforce nothing. The other two ratchets need no equivalent — they already run on every PR.

- Paths: `tests/bench/test_hydration.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
