<!-- torve:managed tests/fixtures/scd2_replay — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/scd2_replay/`

### S-0040/D-2 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

A mart whose **`base`** is `scd: type2` is refused on the same account. There is no fan-out, but the declared `grain:` claims one row per entity while the relation holds one per version, so every measure counts revisions. Refusing both sides keeps "a mart's grain is what it says" true without exception.

- Paths: `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `tests/fixtures/scd2_as_of/marts.yaml` `tests/fixtures/scd2_mart_refusal/entity_model.yaml` `tests/fixtures/scd2_replay/marts.yaml` `tests/golden/refusals/scd2_mart_refusal.txt` `tests/unit/test_fixtures.py` `tests/unit/test_guardrails/test_stage.py` `tests/unit/test_marts/test_flatten.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
