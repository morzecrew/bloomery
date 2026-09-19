<!-- torve:managed tests/fixtures/coarsening_rollup — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/coarsening_rollup/`

### S-0079/D-8 — `ASSUMED` (Determinations reach the IR and the rollup lowering) — implementation: none

The end-to-end proof is one **new** golden fixture, `coarsening_rollup`, registered in the three golden drivers' `EXPECTED_PATHS` tables — not an extension of `rollup_mart`

- Paths: `tests/fixtures/coarsening_rollup/**` `tests/golden/coarsening_rollup/**` `tests/golden/test_cube.py` `tests/golden/test_dbt_postgres.py` `tests/golden/test_sqlmesh_duckdb.py`
- Consequence: `rollup_mart` keeps answering the measure question alone, so a future diff in either fixture says which question moved. It also keeps the two phases' golden directories disjoint — the first phase's regeneration and the second phase's new artifacts are never the same file

<!-- /torve:managed -->
