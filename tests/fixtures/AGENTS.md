<!-- torve:managed tests/fixtures — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/`

### S-0009/D-7 — `ASSUMED` (Continuous fuzzing in CI)

Fuzz seeds are generated from `examples/**` and `tests/fixtures/**` — the examples and the spec fixtures behind the golden tier — at build time rather than committed a second time under `fuzz/`

- Paths: `examples/**` `tests/fixtures/**`
- Consequence: The corpus floor tracks the examples instead of drifting from them, so a new example is a new seed without anyone copying it

### S-0012/D-6 — `ASSUMED` (Validating a dialect port against an engine we cannot run)

All six rungs run the shared fixture corpus rather than a per-engine one; a port-native fixture is added alongside, never instead, where an engine surface has no shared analogue

- Paths: `tests/fixtures/**` `tests/engines/**`
- Consequence: A divergence presents as one fixture behaving differently across ports, which is comparable; departing means an engine surface with genuinely no shared analogue, such as `VARIANT` or `SUPER`

<!-- /torve:managed -->
