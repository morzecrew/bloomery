<!-- torve:managed tests/fixtures/role_playing_dates — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/role_playing_dates/`

### S-0026/D-12 — `ASSUMED` (Testing strategy and fixture corpus)

The corpus grows to fourteen fixtures (D7): `role_playing_dates`, `semi_additive_inventory` (the former `semi_additive`, renamed and extended), `non_additive_aov`, and `multi_mart_refusal` join the spec §7.7 set; `fanout_trap` now proves the compile-time `GrainViolation` (S-0023) and keeps its execution-level wrong-sum proof.

- Paths: `tests/execution/test_marts.py` `tests/fixtures/role_playing_dates/entity_model.yaml`

<!-- /torve:managed -->
