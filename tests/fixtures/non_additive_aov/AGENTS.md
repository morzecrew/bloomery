<!-- torve:managed tests/fixtures/non_additive_aov — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/non_additive_aov/`

### S-0028/D-5 — `ASSUMED` (Native planner: MetricRequest → QueryPlan)

Additivity lowering per D4 exactly: additive → SUM at requested grain; semi-additive (`SemiAdditivePolicy(over, rule ∈ last/first/avg/max/min)`) → sum across every dimension except `over`, rule along `over` (coarser requested grain: rule within each bucket, then sum); non-additive → never stored/summed, recomputed from additive components (`RatioSpec` → `SUM(num)/NULLIF(SUM(den),0)`); missing components = `NonAdditiveWithoutComponents` at resolution/guardrail stage (S-0023 defense-in-depth).

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/coverage.py` `src/bloomery/planner/explain.py` `src/bloomery/planner/result.py` `src/bloomery/spec/common.py` `tests/fixtures/non_additive_aov/marts.yaml` `tests/fixtures/non_additive_aov/metrics.yaml` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_planner/test_coverage.py`

### S-0030/D-3 — `ASSUMED` (MetricFlow backend: manifest emitter and planner adapter)

`emit_manifest(ir, *, naming) -> PydanticSemanticManifest` is a pure deterministic emitter. One mart = exactly one semantic model; never a semantic model for a non-materialized entity (would reintroduce query-time joins). Every measure carries `agg_time_dimension`; a martless time dimension is `MartMissingTimeDimension` (new `GuardrailError` leaf). All collections sorted lexicographically before construction — the manifest is hashed/cached. Full IR→MetricFlow mapping and enum tables per §5.2.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `tests/fixtures/non_additive_aov/marts.yaml` `tests/unit/test_emit/test_metricflow.py`

### S-0030/D-4 — `ASSUMED` (MetricFlow backend: manifest emitter and planner adapter)

`SemiAdditivePolicy.rule` maps `last → MAX`, `first → MIN`; `avg`/`max`/`min` are not expressible via `non_additive_dimension` → `UnsupportedByTarget` naming the rule.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `tests/fixtures/non_additive_aov/marts.yaml` `tests/unit/test_emit/test_metricflow.py`

<!-- /torve:managed -->
