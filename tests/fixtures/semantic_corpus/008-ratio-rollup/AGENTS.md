<!-- torve:managed tests/fixtures/semantic_corpus/008-ratio-rollup — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/semantic_corpus/008-ratio-rollup/`

### S-0053/D-2 — `LOCKED` (Measure semantic types and additivity algebra)

**A ratio is stored as its operands, not as a materialized quotient.** `SUM(num)/SUM(den)` and `AVG(ratio)` differ, the second is what a numeric-looking column invites, and the difference is a plausible wrong number. This is also S-0055's precondition — a derived metric spanning two branches cannot be reconstructed after the operands are gone — so reversing it later strands that document.

- Paths: `src/bloomery/emit/lower/rollups.py` `src/bloomery/errors.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/mart.py` `tests/fixtures/semantic_corpus/002-average-of-averages/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/002-average-of-averages/problem.md` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/problem.md` `tests/fixtures/semantic_corpus/008-ratio-rollup/bloomery/declared/metrics.yaml` `tests/fixtures/semantic_corpus/008-ratio-rollup/bloomery/naive/metrics.yaml` `tests/fixtures/semantic_corpus/008-ratio-rollup/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/008-ratio-rollup/problem.md` `tests/fixtures/semantic_corpus/012-rollup-recounts-identities/problem.md` `tests/unit/test_emit/test_rollups.py` `tests/unit/test_guardrails/test_additivity.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_steps/test_step_canonicals.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0077/D-1 — `LOCKED` (A ratio over one row set)

**bloomery does not choose which rows a ratio is about.** Both readings — per unit over units that exist, and total over units with overheads included — are metrics somebody wants, and the defect is that they are spelled identically. The rule refuses until the author says; it never picks. Locked because every cheaper design is a compiler making a decision about somebody's business, and the wrong one is invisible in the output.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/semantic/additivity.py` `src/bloomery/spec/quality.py` `tests/fixtures/semantic_corpus/008-ratio-rollup/**` `tests/fixtures/semantic_corpus/009-null-denominator/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0077/D-13 — `LOCKED` (A ratio over one row set)

**`repair` does not discharge the positivity premise either.** D3 names only `flag`; this is D3's own sentence applied to the member it did not name. A repaired row stays in the relation carrying a fallback the rule cannot bound, because its recipe is a step and its fallback is whatever the author wrote. Only `quarantine` and `fail` discharge, because only those remove the row. Locked with D3: departing would mean proving a fallback is positive, which needs the step registry's output and is not a compile-time fact — see `logs/T-0063.md` (unlisted, 15:15Z).

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/semantic/additivity.py` `src/bloomery/spec/quality.py` `tests/fixtures/semantic_corpus/008-ratio-rollup/**` `tests/fixtures/semantic_corpus/009-null-denominator/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0077/D-14 — `LOCKED` (A ratio over one row set)

*Superseded by D16.* **A fourth discharge: the denominator counts a column that cannot be NULL.** §5.1's three discharges refuse every ratio in this repository — eight projects, including the two corpus cases §6 calls untouched — and five of the eight are counts, where the premise holds by construction and no declaration could add anything. A count counts the very rows the numerator sums, so a row contributing to the numerator contributes 1. Without this the rule refuses `revenue / order_count`, and §9's claim that a well-declared project is not inconvenienced is false for every project in the tree — see `logs/T-0063.md` (unlisted, 15:40Z).

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/semantic/additivity.py` `src/bloomery/spec/quality.py` `tests/fixtures/semantic_corpus/008-ratio-rollup/**` `tests/fixtures/semantic_corpus/009-null-denominator/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0077/D-16 — `LOCKED` (A ratio over one row set)

**`count` and `count_distinct` over a column that cannot be null both discharge.** Supersedes D14, which excluded the second on the grounds that a distinct count is about the group rather than the row — true, and not the premise. What R019 refuses is a denominator whose *per-row* contribution can be zero while the numerator's is not, and that is a property of a sum over a numeric column; a count of either kind is at least one for any non-empty row set. The exclusion was admitted wrong on the evidence of the message it produced: "nothing restricts … to rows with a non-zero `customer_id`" about a string column, telling the author to filter `customer_id > 0` — see `logs/T-0063.md` (unlisted, 15:55Z, attempt 2).

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/semantic/additivity.py` `src/bloomery/spec/quality.py` `tests/fixtures/semantic_corpus/008-ratio-rollup/**` `tests/fixtures/semantic_corpus/009-null-denominator/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
