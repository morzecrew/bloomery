<!-- torve:managed tests/fixtures/semantic_corpus/007-distinct-users-fanout — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/semantic_corpus/007-distinct-users-fanout/`

### S-0053/D-1 — `LOCKED` (Measure semantic types and additivity algebra)

**The aggregation vocabulary is a closed typed set, never a target-interpreted string.** `Additive`, `SemiAdditive`, `NonAdditive`, `Ratio`, `DistinctCount`, `Snapshot`. Locked because the planner, the proof rules and every emitter branch on it: an open string set makes each target the authority for what a measure means, which is the arrangement this whole sequence exists to end. Staging the *implementation* across releases is fine; encoding a future class as a string is not.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/ir/nodes.py` `src/bloomery/spec/common.py` `tests/fixtures/semantic_corpus/005-semi-additive-balance/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/005-semi-additive-balance/problem.md` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/problem.md` `tests/unit/test_guardrails/test_additivity.py` `tests/unit/test_semantic/test_rollup.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0053/D-2 — `LOCKED` (Measure semantic types and additivity algebra)

**A ratio is stored as its operands, not as a materialized quotient.** `SUM(num)/SUM(den)` and `AVG(ratio)` differ, the second is what a numeric-looking column invites, and the difference is a plausible wrong number. This is also S-0055's precondition — a derived metric spanning two branches cannot be reconstructed after the operands are gone — so reversing it later strands that document.

- Paths: `src/bloomery/emit/lower/rollups.py` `src/bloomery/errors.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/mart.py` `tests/fixtures/semantic_corpus/002-average-of-averages/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/002-average-of-averages/problem.md` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/problem.md` `tests/fixtures/semantic_corpus/008-ratio-rollup/bloomery/declared/metrics.yaml` `tests/fixtures/semantic_corpus/008-ratio-rollup/bloomery/naive/metrics.yaml` `tests/fixtures/semantic_corpus/008-ratio-rollup/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/008-ratio-rollup/problem.md` `tests/fixtures/semantic_corpus/012-rollup-recounts-identities/problem.md` `tests/unit/test_emit/test_rollups.py` `tests/unit/test_guardrails/test_additivity.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_steps/test_step_canonicals.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0055/D-8 — `OPEN` (Multi-grain aggregate-then-join query planning)

**Whether `DistinctCount`, `Snapshot` and `SemiAdditive` enter branch planning at all in P1.** §8 gates them on their proof rules being independently sound. Decide per class, with the corpus case each one converts, rather than as a group.

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/semantic/rollup.py` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/problem.md` `tests/fixtures/semantic_corpus/012-rollup-recounts-identities/problem.md` `tests/unit/test_planner/test_coverage.py`

### S-0056/D-5 — `ASSUMED` (Production-style semantic bug corpus)

**A new proof rule names the cases it converts from refusal to acceptance.** The corpus is the design gate: a rule that converts nothing has no demonstrated purpose, and a rule that converts a case without supplying a correct result and proof fails review. Not `LOCKED` because a soundness fix may legitimately convert *nothing* while still being necessary.

- Paths: `tests/fixtures/semantic_corpus/007-distinct-users-fanout/problem.md` `tests/fixtures/semantic_corpus/009-null-denominator/problem.md` `tests/fixtures/semantic_corpus/011-timezone-boundary/problem.md`

<!-- /torve:managed -->
