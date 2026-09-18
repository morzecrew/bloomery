<!-- torve:managed tests/fixtures/semantic_corpus/007-distinct-users-fanout/expected — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/semantic_corpus/007-distinct-users-fanout/expected/`

### S-0053/D-1 — `LOCKED` (Measure semantic types and additivity algebra)

**The aggregation vocabulary is a closed typed set, never a target-interpreted string.** `Additive`, `SemiAdditive`, `NonAdditive`, `Ratio`, `DistinctCount`, `Snapshot`. Locked because the planner, the proof rules and every emitter branch on it: an open string set makes each target the authority for what a measure means, which is the arrangement this whole sequence exists to end. Staging the *implementation* across releases is fine; encoding a future class as a string is not.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/ir/nodes.py` `src/bloomery/spec/common.py` `tests/fixtures/semantic_corpus/005-semi-additive-balance/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/005-semi-additive-balance/problem.md` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/problem.md` `tests/unit/test_guardrails/test_additivity.py` `tests/unit/test_semantic/test_rollup.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0053/D-2 — `LOCKED` (Measure semantic types and additivity algebra)

**A ratio is stored as its operands, not as a materialized quotient.** `SUM(num)/SUM(den)` and `AVG(ratio)` differ, the second is what a numeric-looking column invites, and the difference is a plausible wrong number. This is also S-0055's precondition — a derived metric spanning two branches cannot be reconstructed after the operands are gone — so reversing it later strands that document.

- Paths: `src/bloomery/emit/lower/rollups.py` `src/bloomery/errors.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/mart.py` `tests/fixtures/semantic_corpus/002-average-of-averages/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/002-average-of-averages/problem.md` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/problem.md` `tests/fixtures/semantic_corpus/008-ratio-rollup/bloomery/declared/metrics.yaml` `tests/fixtures/semantic_corpus/008-ratio-rollup/bloomery/naive/metrics.yaml` `tests/fixtures/semantic_corpus/008-ratio-rollup/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/008-ratio-rollup/problem.md` `tests/fixtures/semantic_corpus/012-rollup-recounts-identities/problem.md` `tests/unit/test_emit/test_rollups.py` `tests/unit/test_guardrails/test_additivity.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_steps/test_step_canonicals.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
