<!-- torve:managed tests — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/`

### S-0026/D-9 — `ASSUMED` (Testing strategy and fixture corpus)

Coverage: branch on, `fail_under=80` overall, per-package floors ratcheting up (forze pattern); `bloomery/guardrails/` is floored at 100% branch from day one.

- Paths: `src/bloomery/guardrails/quality.py` `tests/README.md` `tests/unit/test_quality/test_coverage.py`

### S-0042/D-2 — `LOCKED` (v0.1.0 release readiness)

The docs floor checks **claims**, not links. A link checker would have passed the stale Postgres warning that cost the dialect its standing with a careful reader; a documented-refusal table would have failed. Consequence: every refusal the docs describe must be reachable by a test, so adding a documented refusal without a test becomes impossible.

- Paths: `tests/conftest.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0092/D-5 — `ASSUMED` (Generated SQL agrees with a reference evaluator) — implementation: none

`tests/conftest.py` registers Hypothesis profiles: `dev` (the default), `ci` (fewer examples, derandomized, `print_blob` on) and `nightly` (more examples), chosen by `HYPOTHESIS_PROFILE`. Every CI job that runs property or engine tests sets `ci`, except the engine job's nightly schedule, which sets `nightly`; the phases' acceptance commands set `ci` too.

- Paths: `tests/conftest.py` `.github/workflows/ci.yml`
- Consequence: a failure in CI prints the blob that reproduces it locally, and the nightly run searches wider than a pull request can afford

<!-- /torve:managed -->
