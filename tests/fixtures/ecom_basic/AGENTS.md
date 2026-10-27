<!-- torve:managed tests/fixtures/ecom_basic — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/ecom_basic/`

### S-0025/D-13 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

(Reverses D6) Bloomery owns the date dimension: one catalog definition emits both the SQLMesh `gold.dim_date` model and the MetricFlow time-spine declaration (S-0030 R1). D6's demand-gate is satisfied — MetricFlow is the demand.

- Paths: `src/bloomery/emit/lower/marts.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/metrics.py` `tests/execution/test_marts.py` `tests/fixtures/ecom_basic/catalog.yaml` `tests/golden/schema/catalog.json` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_fixtures.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_metrics.py`

### S-0027/D-9 — `ASSUMED` (Marts and role-playing dimensions)

(Amended for `_bloomery-metricflow-pivot.md`) Marts are the emission source for MetricFlow semantic models — one mart = exactly one semantic model (S-0030 R1); a measure-carrying mart must declare a date role (`MartMissingTimeDimension` otherwise). Marts and role-playing are *more* load-bearing after the pivot, not less.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/marts/flatten.py` `src/bloomery/quality/mart.py` `src/bloomery/resolve/graph.py` `tests/fixtures/ecom_basic/marts.yaml` `tests/fixtures/quality_precedence/entity_model.yaml` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_fixtures.py` `tests/unit/test_quality/test_mart.py` `tests/unit/test_resolve/test_graph.py`

<!-- /torve:managed -->
