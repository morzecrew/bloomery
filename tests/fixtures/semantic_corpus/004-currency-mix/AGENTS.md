<!-- torve:managed tests/fixtures/semantic_corpus/004-currency-mix — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/semantic_corpus/004-currency-mix/`

### S-0023/D-4 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Currency codes are checked only when both operands declare one; distinct declared codes require an explicit `convert` transform. Absent codes are compatible — opt-in, unlike tax basis, so single-currency tenants aren't trained to paste constants.

- Paths: `src/bloomery/guardrails/arithmetic.py` `src/bloomery/resolve/build.py` `tests/fixtures/semantic_corpus/004-currency-mix/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/004-currency-mix/problem.md` `tests/golden/refusals/example-mixed-currency.txt` `tests/unit/test_guardrails/test_arithmetic.py`

### S-0053/D-3 — `LOCKED` (Measure semantic types and additivity algebra)

**Superseded in part by D9 (currency) and D10 (units).** **Units participate in type checking; incompatible arithmetic is refused without an explicit declared conversion.** Existing currency behaviour becomes a proof-producing rule rather than a waiver that suppresses the mismatch. Locked because a waiver and a proof are indistinguishable at the call site and only one of them survives being asked "on what basis?".

- Paths: `tests/fixtures/semantic_corpus/004-currency-mix/problem.md`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
