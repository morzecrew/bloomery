<!-- torve:managed tests/fixtures/multi_mart_refusal — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/multi_mart_refusal/`

### S-0030/D-6 — `ASSUMED` (MetricFlow backend: manifest emitter and planner adapter)

Mart-coverage precheck runs **before** delegation and preserves the refusal policy: all measures on one mart (else `UnreachableAtGrain` with S-0028's exact per-metric grain/mart message), all dimensions flattened onto it, multi-candidate → `cost_hint` then lexicographic. MetricFlow could plan multi-hop joins; we refuse first — refuse-don't-guess enforced twice (coverage, then MetricFlow's resolver). Belt and braces.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/planner/coverage.py` `src/bloomery/planner/metricflow_planner.py` `tests/fixtures/multi_mart_refusal/marts.yaml` `tests/unit/test_emit/test_cube.py`

<!-- /torve:managed -->
