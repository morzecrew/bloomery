<!-- torve:managed tests/fixtures/semantic_corpus/003-scd2-unqualified-join/expected — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/semantic_corpus/003-scd2-unqualified-join/expected/`

### S-0040/D-1 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

Flattening an entity with `scd: type2` into a mart is **refused** at compile time, not silently emitted and not silently filtered to the current version. The join has no validity predicate and the relation has one row per version, so the emitted mart multiplies the base grain while every guardrail passes. Consequence: the only shipped way to use a historical dimension in a mart is a `type1` current-view entity built from it, until §5.3 exists.

- Paths: `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `tests/fixtures/scd2_mart_refusal/entity_model.yaml` `tests/fixtures/semantic_corpus/003-scd2-unqualified-join/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/003-scd2-unqualified-join/problem.md` `tests/golden/refusals/example-scd2-flatten.txt` `tests/golden/refusals/scd2_mart_refusal.txt` `tests/unit/test_fixtures.py` `tests/unit/test_guardrails/test_stage.py` `tests/unit/test_marts/test_flatten.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0040/D-8 — `OPEN` (Temporal joins: SCD2 flattening and currency conversion)

The as-of anchor's spelling and location. §5.3 proposes `as_of:` on the `flatten` entry; a mart-level default and a relationship-level declaration are both defensible. Whoever builds Phase 2 decides and logs it. It must be **declared** either way — inference is closed by S-0038.

- Paths: `tests/fixtures/semantic_corpus/003-scd2-unqualified-join/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/003-scd2-unqualified-join/problem.md` `tests/unit/test_marts/test_flatten.py`

<!-- /torve:managed -->
