<!-- torve:managed tests/golden — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/golden/`

### S-0009/D-7 — `ASSUMED` (Continuous fuzzing in CI)

Fuzz seeds are generated from `examples/**` and `tests/golden/**` at build time rather than committed a second time under `fuzz/`

- Paths: `examples/**` `tests/golden/**`
- Consequence: The corpus floor tracks the examples instead of drifting from them, so a new example is a new seed without anyone copying it

<!-- /torve:managed -->
