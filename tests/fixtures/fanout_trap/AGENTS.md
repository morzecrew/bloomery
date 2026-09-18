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

<!-- /torve:managed -->
