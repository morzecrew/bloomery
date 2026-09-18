<!-- torve:managed pages/docs/concepts — rendered from the corpus; do not edit by hand -->

## Decisions governing `pages/docs/concepts/`

### S-0023/D-6 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Additivity: `non_additive` metrics are never materialized as stored numbers (components only); `semi_additive` metrics aggregate only over dimensions other than their `over:` dimension. Enforced at IR build **and** re-refused by emitters (S-0025) — defense in depth.

- Paths: `pages/docs/concepts/guardrails.md` `src/bloomery/guardrails/additivity.py` `src/bloomery/planner/coverage.py` `tests/fixtures/semantic_corpus/002-average-of-averages/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/002-average-of-averages/problem.md` `tests/fixtures/semantic_corpus/005-semi-additive-balance/problem.md` `tests/unit/test_guardrails/test_additivity.py`

### S-0075/D-1 — `LOCKED` (Mechanical imports and per-relationship provenance)

**Provenance attaches to the relationship, not to the basis kind.** `BASIS_PROVENANCE` is keyed by `DependencyBasis` value, so today every `many_to_one` in a project shares one provenance and an imported edge cannot be told from an authored one — which is why `IMPORTED_VERIFIED` has no producer and S-0070's refusal has no project that can trip it. Locked because it is the whole of what makes the grade mean anything at the point a consumer asks; reversing it makes every other row here decoration. `FunctionalDependency.via` already carries the key such a lookup needs. Proposed by execution — see `logs/T-0053.md` (`logs/T-0053.md`) (D2, attempt 1).

- Paths: `pages/docs/concepts/what-bloomery-proves.md` `src/bloomery/guardrails/evidence.py` `tests/unit/test_guardrails/test_evidence.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
