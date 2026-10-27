<!-- torve:managed tests/fixtures/semi_additive_over_refusal — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/semi_additive_over_refusal/`

### S-0023/D-13 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

The `over` of a semi-additive metric names the source column of a date role — the column a `{date: …, role: …}` flatten step is declared over — never a bucket that role produces (`<role>_day` and the rest), and every mart listing the metric among its measures must declare a date role over that column. A mart that does not is refused at the guardrail stage as `MartMissingTimeDimension`, and the MetricFlow emitter re-refuses it

- Paths: `src/bloomery/guardrails/metrics.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/planner/explain.py` `tests/unit/test_guardrails/test_metrics.py` `tests/fixtures/semi_additive_over_refusal/metrics.yaml` `tests/golden/refusals/semi_additive_over_refusal.txt` `pages/docs/reference/spec-schemas.md`
- Consequence: `over: snapshot_day` beside `{date: stock_date, role: snapshot}` is refused at `bloomery check`, naming `stock_date`, rather than compiling clean and failing only when the MetricFlow manifest is built; a mart added to a metric's listing without the role is refused even when another mart owns the metric

<!-- /torve:managed -->
