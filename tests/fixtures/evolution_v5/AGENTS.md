<!-- torve:managed tests/fixtures/evolution_v5 — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/evolution_v5/`

### S-0024/D-7 — `ASSUMED` (Plan: spec diff and change classification)

Entity-level `grain`/`key`/`scd`/`materialization` changes are BREAKING at the entity subject (they redefine the row); column diffs are still reported alongside. Type changes follow the S-0021 lattice: widening = WIDENING, narrowing (incl. optional→required) and new required fields = BREAKING.

- Paths: `src/bloomery/plan/diff.py` `tests/fixtures/evolution_v5/entity_model.yaml` `tests/unit/test_plan/test_diff.py`

<!-- /torve:managed -->
