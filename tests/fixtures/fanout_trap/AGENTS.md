<!-- torve:managed tests/fixtures/fanout_trap — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/fanout_trap/`

### S-0023/D-2 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Violations are batched project-wide: leaf errors (`UnitMismatch`, `TaxBasisMismatch`, `CurrencyMismatch`, `GrainMismatch`, `AdditivityViolation`, `AssertLoweringError`) are collected and raised as one `GuardrailError` aggregate, sorted by `(source_path, type)`. Matches S-0019/D-6.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/arithmetic.py` `src/bloomery/guardrails/quality.py` `src/bloomery/guardrails/stage.py` `src/bloomery/quality/reconcile.py` `src/bloomery/resolve/build.py` `src/bloomery/resolve/steps.py` `tests/fixtures/fanout_trap/metrics.yaml` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_guardrails/test_stage.py` `tests/unit/test_steps/test_lowering.py`

### S-0023/D-5 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Grain guard: derivation operands must share the derivation's grain or the expression must contain an explicit aggregation over the finer grain. No automatic allocation. `fanout_trap` (S-0026) is the numeric proof.

- Paths: `src/bloomery/guardrails/grain.py` `tests/execution/test_fanout_trap.py` `tests/fixtures/fanout_trap/catalog.yaml` `tests/fixtures/semantic_corpus/001-order-shipping-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/001-order-shipping-fanout/problem.md` `tests/unit/test_guardrails/test_grain.py`

### S-0023/D-10 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Mart-level fan-out guard runs at compile time (_bloomery-changes.md D2, S-0027): `GrainViolation` (a measure whose grain is coarser than the mart's grain listed in a finer-grain mart's `measures`) and `FanoutRisk` (a `flatten:` step whose `via:` relationship is not `many_to_one`/`one_to_one`) are `GuardrailError` leaves, batched like the rest. `fanout_trap` now fails at compile time; its execution assertion is kept because it documents why the compile error exists.

- Paths: `src/bloomery/guardrails/grain.py` `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/build.py` `tests/execution/test_as_of_join.py` `tests/execution/test_fanout_trap.py` `tests/fixtures/fanout_trap/marts.yaml` `tests/unit/test_guardrails/test_stage.py`

### S-0027/D-2 — `ASSUMED` (Marts and role-playing dimensions)

Measure grain must strictly equal mart grain; coarser or finer is `GrainViolation`. Resolves D2's prose/example contradiction to the strict reading; relaxation is a future additive change.

- Paths: `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/semantic/proof.py` `src/bloomery/semantic/rollup.py` `tests/fixtures/fanout_trap/marts.yaml` `tests/fixtures/fanout_trap/metrics.yaml` `tests/fixtures/semantic_corpus/001-order-shipping-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/001-order-shipping-fanout/problem.md` `tests/fixtures/semantic_corpus/010-many-to-many-bridge/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/010-many-to-many-bridge/problem.md` `tests/golden/refusals/example-wrong-grain.txt` `tests/golden/refusals/fanout_trap.txt` `tests/support/semantic_corpus.py` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_semantic_corpus_guard.py`

### S-0056/D-8 — `LOCKED` (Production-style semantic bug corpus)

**A third outcome, `unguarded` — it compiles, and the planner returns the naive number — and §8's gate read in both directions.** Two of the phase-one cases were neither refused nor correct: an average and a snapshot balance both declared `additivity: additive` compile clean, because nothing verifies that an `additive` claim is true. With only "refuse" and "prove" available such a case can be written as a fiction or left out, and leaving it out drops exactly the cases S-0053 exists to convert. So a new rule names the cases it converts from refusal to acceptance *and* the ones it converts from unguarded to refused. Locked because the word is the corpus's whole claim to being a design gate rather than a transcript, and every case's vocabulary rests on it — see `logs/T-0018.md` (D096).

- Paths: `tests/fixtures/dirty/**` `tests/fixtures/fanout_trap/**` `tests/fixtures/semantic_corpus/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0056/D-12 — `LOCKED` (Production-style semantic bug corpus)

**An expectation's outcome is defined by the number the planner returns, asserted by running the SQL bloomery rendered.** The first execution ran the two hand-written queries as standalone SQL and planned nothing, so `accepted` and `unguarded` asserted identically and the difference rested on whether the cited RFC was still in the `rfcs` directory (since retired) — a fact about the repository, not about the case. That proxy would have passed a mis-modelled case, and did: case 002's naive metric over line-grain rows returns the *right* answer, because an average over lines is right, and the average-of-averages bug needs an average already taken. Locked because it is the difference between the corpus asserting behaviour and asserting its own bookkeeping — see `logs/T-0018.md` (D101), where it is logged as this task's one `drift`.

- Paths: `tests/fixtures/dirty/**` `tests/fixtures/fanout_trap/**` `tests/fixtures/semantic_corpus/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
