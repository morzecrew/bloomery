<!-- torve:managed src/bloomery/typing — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/typing/`

### S-0019/D-6 — `ASSUMED` (Spec layer and error model)

Parse-stage errors are batched per document (all failures reported at once).

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/errors.py` `src/bloomery/evidence.py` `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/build.py` `src/bloomery/resolve/refs.py` `src/bloomery/spec/common.py` `src/bloomery/spec/project.py` `src/bloomery/typing/check.py` `tests/unit/test_cli.py` `tests/unit/test_evidence.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_refs.py` `tests/unit/test_spec/test_mapping.py` `tests/unit/test_spec/test_project.py` `tests/unit/test_spec/test_sql_text.py`

### S-0020/D-5 — `ASSUMED` (Intermediate representation and determinism contract)

Floats are banned in IR and emission; `Decimal`/int only.

- Paths: `src/bloomery/cli/serialize.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/steps.py` `src/bloomery/ir/fingerprint.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/request.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/common.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `src/bloomery/steps/manifest.py` `src/bloomery/steps/splice.py` `src/bloomery/transforms/_builtins.py` `src/bloomery/typing/types.py` `tests/execution/test_as_of_join.py` `tests/execution/test_currency_convert.py` `tests/execution/test_fanout_trap.py` `tests/execution/test_marts.py` `tests/execution/test_period_over_period.py` `tests/execution/test_rollup.py` `tests/fixtures/semantic_corpus/002-average-of-averages/naive.sql` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/golden/schema/marts.json` `tests/support/planning.py` `tests/support/semantic_corpus.py` `tests/unit/test_cli.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_planner/test_request.py` `tests/unit/test_quality/test_edges.py` `tests/unit/test_spec/test_metrics.py` `tests/unit/test_spec/test_quality.py` `tests/unit/test_steps/test_lowering.py` `tests/unit/test_steps/test_manifest_and_registry.py` `tests/unit/test_typing/test_types.py`

### S-0021/D-4 — `ASSUMED` (Logical types and the transform registry)

Unknown transform name → `UnknownTransformError` naming the closest match, computed with `difflib.get_close_matches` over the sorted registry — deterministic suggestions, no external fuzzy dependency.

- Paths: `src/bloomery/typing/check.py`

<!-- /torve:managed -->
