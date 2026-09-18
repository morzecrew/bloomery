<!-- torve:managed tests/fixtures/period_over_period — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/period_over_period/`

### S-0050/D-4 — `ASSUMED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A derived metric need not be named in any mart's `measures:`.** It has no measure to place. It is emitted where every input's measure is emitted — the rule the ratio already uses — and the planner's coverage precheck resolves it to the mart carrying those measures. Naming it in `measures:` stays legal and inert, as it is for a ratio.

- Paths: `src/bloomery/emit/cube/__init__.py` `tests/fixtures/period_over_period/marts.yaml` `tests/unit/test_emit/test_period_over_period.py`

### S-0050/D-9 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A filter's dimension is checked against every mart listing the metric, at the guardrail stage.** Not at emit: a filter naming a column no mart flattens is a *model* error, decidable from the spec, and it should fail with the batched aggregate every other model error joins. Checking every listing mart rather than the owning one avoids reaching for the ownership rule from a layer below the module that defines it, and is a superset of what correctness needs.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/errors.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/semantic/additivity.py` `tests/fixtures/period_over_period/entity_model.yaml` `tests/unit/test_guardrails/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
