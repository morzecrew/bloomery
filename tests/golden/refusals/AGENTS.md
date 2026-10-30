<!-- torve:managed tests/golden/refusals — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/golden/refusals/`

### S-0023/D-4 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Currency codes are checked only when both operands declare one; distinct declared codes require an explicit `convert` transform. Absent codes are compatible — opt-in, unlike tax basis, so single-currency tenants aren't trained to paste constants.

- Paths: `src/bloomery/guardrails/arithmetic.py` `src/bloomery/resolve/build.py` `tests/fixtures/semantic_corpus/004-currency-mix/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/004-currency-mix/problem.md` `tests/golden/refusals/example-mixed-currency.txt` `tests/unit/test_guardrails/test_arithmetic.py`

### S-0023/D-13 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

The `over` of a semi-additive metric names the source column of a date role — the column a `{date: …, role: …}` flatten step is declared over — never a bucket that role produces (`<role>_day` and the rest), and every mart listing the metric among its measures must declare a date role over that column. A mart that does not is refused at the guardrail stage as `MartMissingTimeDimension`, and the MetricFlow emitter re-refuses it

- Paths: `src/bloomery/guardrails/metrics.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/planner/explain.py` `tests/unit/test_guardrails/test_metrics.py` `tests/fixtures/semi_additive_over_refusal/metrics.yaml` `tests/golden/refusals/semi_additive_over_refusal.txt` `pages/docs/reference/spec-schemas.md`
- Consequence: `over: snapshot_day` beside `{date: stock_date, role: snapshot}` is refused at `bloomery check`, naming `stock_date`, rather than compiling clean and failing only when the MetricFlow manifest is built; a mart added to a metric's listing without the role is refused even when another mart owns the metric

### S-0023/D-15 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

A canonical field may declare `per_unit: true`: its value is a rate that holds per unit of each row reading it, such as a unit cost or a price, rather than an amount of its own entity. The grain guard admits such an operand, in a metric or a derivation, where the grain reaches the operand's entity through a chain of declared relationships each many-to-one, either way round. Every other foreign-grain operand is refused under D-5 as before, a per-unit one read from the parent side included, and the refusal names the declaration where it would apply

- Paths: `src/bloomery/spec/catalog.py` `src/bloomery/guardrails/grain.py` `src/bloomery/guardrails/operands.py` `tests/unit/test_guardrails/test_per_unit_parent.py` `tests/unit/test_guardrails/test_per_unit_chain.py` `tests/golden/refusals/fanout_trap.txt` `pages/docs/reference/spec-schemas.md`
- Consequence: Cost of goods at order-line grain, `product_cost * line_quantity` with the cost on `product`, compiles once the catalog declares the cost per unit. Order shipping read per line, the `fanout_trap`, is refused as before, in the same expression shape. The declaration is not verified, so a per-unit amount summed per line overstates exactly as the fan-out D-5 refuses, and the declaration is where a reviewer looks for it. A marketplace sale reading the product's cost through its item, two many-to-one hops, compiles too (#382). A chain with one hop read one-to-many anywhere in it, from a parent to its children, is refused; a relationship declared one-to-many and read from the child's side is a many-to-one hop

### S-0027/D-2 — `ASSUMED` (Marts and role-playing dimensions)

Measure grain must strictly equal mart grain; coarser or finer is `GrainViolation`. Resolves D2's prose/example contradiction to the strict reading; relaxation is a future additive change.

- Paths: `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/semantic/proof.py` `src/bloomery/semantic/rollup.py` `tests/fixtures/fanout_trap/marts.yaml` `tests/fixtures/fanout_trap/metrics.yaml` `tests/fixtures/semantic_corpus/001-order-shipping-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/001-order-shipping-fanout/problem.md` `tests/fixtures/semantic_corpus/010-many-to-many-bridge/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/010-many-to-many-bridge/problem.md` `tests/golden/refusals/example-wrong-grain.txt` `tests/golden/refusals/fanout_trap.txt` `tests/support/semantic_corpus.py` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_semantic_corpus_guard.py`

### S-0040/D-1 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

Flattening an entity with `scd: type2` into a mart is **refused** at compile time, not silently emitted and not silently filtered to the current version. The join has no validity predicate and the relation has one row per version, so the emitted mart multiplies the base grain while every guardrail passes. Consequence: the only shipped way to use a historical dimension in a mart is a `type1` current-view entity built from it, until §5.3 exists.

- Paths: `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `tests/fixtures/scd2_mart_refusal/entity_model.yaml` `tests/fixtures/semantic_corpus/003-scd2-unqualified-join/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/003-scd2-unqualified-join/problem.md` `tests/golden/refusals/example-scd2-flatten.txt` `tests/golden/refusals/scd2_mart_refusal.txt` `tests/unit/test_fixtures.py` `tests/unit/test_guardrails/test_stage.py` `tests/unit/test_marts/test_flatten.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0040/D-2 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

A mart whose **`base`** is `scd: type2` is refused on the same account. There is no fan-out, but the declared `grain:` claims one row per entity while the relation holds one per version, so every measure counts revisions. Refusing both sides keeps "a mart's grain is what it says" true without exception.

- Paths: `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `tests/fixtures/scd2_as_of/marts.yaml` `tests/fixtures/scd2_mart_refusal/entity_model.yaml` `tests/fixtures/scd2_replay/marts.yaml` `tests/golden/refusals/scd2_mart_refusal.txt` `tests/unit/test_fixtures.py` `tests/unit/test_guardrails/test_stage.py` `tests/unit/test_marts/test_flatten.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
