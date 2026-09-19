<!-- torve:managed src/bloomery/emit/metricflow — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/emit/metricflow/`

### S-0025/D-9 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Every artifact carries a header comment with the project fingerprint — applied-vs-spec drift detection downstream.

- Paths: `src/bloomery/emit/base.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/emit/sqlmesh/__init__.py`

### S-0025/D-13 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

(Reverses D6) Bloomery owns the date dimension: one catalog definition emits both the SQLMesh `gold.dim_date` model and the MetricFlow time-spine declaration (S-0030 R1). D6's demand-gate is satisfied — MetricFlow is the demand.

- Paths: `src/bloomery/emit/lower/marts.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/metrics.py` `tests/execution/test_marts.py` `tests/fixtures/ecom_basic/catalog.yaml` `tests/golden/schema/catalog.json` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_fixtures.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_metrics.py`

### S-0027/D-8 — `ASSUMED` (Marts and role-playing dimensions)

`cost_hint` (int, default 1) is a tie-breaking scan-cost hint only; selection ties break lexicographically (S-0020 determinism).

- Paths: `src/bloomery/emit/lower/marts.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/spec/marts.py` `tests/golden/schema/marts.json` `tests/unit/test_emit/test_metricflow.py` `tests/unit/test_planner/test_coverage.py`

### S-0027/D-9 — `ASSUMED` (Marts and role-playing dimensions)

(Amended for `_bloomery-metricflow-pivot.md`) Marts are the emission source for MetricFlow semantic models — one mart = exactly one semantic model (S-0030 R1); a measure-carrying mart must declare a date role (`MartMissingTimeDimension` otherwise). Marts and role-playing are *more* load-bearing after the pivot, not less.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/marts/flatten.py` `src/bloomery/quality/mart.py` `src/bloomery/resolve/graph.py` `tests/fixtures/ecom_basic/marts.yaml` `tests/fixtures/quality_precedence/entity_model.yaml` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_fixtures.py` `tests/unit/test_quality/test_mart.py` `tests/unit/test_resolve/test_graph.py`

### S-0030/D-3 — `ASSUMED` (MetricFlow backend: manifest emitter and planner adapter)

`emit_manifest(ir, *, naming) -> PydanticSemanticManifest` is a pure deterministic emitter. One mart = exactly one semantic model; never a semantic model for a non-materialized entity (would reintroduce query-time joins). Every measure carries `agg_time_dimension`; a martless time dimension is `MartMissingTimeDimension` (new `GuardrailError` leaf). All collections sorted lexicographically before construction — the manifest is hashed/cached. Full IR→MetricFlow mapping and enum tables per §5.2.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `tests/fixtures/non_additive_aov/marts.yaml` `tests/unit/test_emit/test_metricflow.py`

### S-0030/D-4 — `ASSUMED` (MetricFlow backend: manifest emitter and planner adapter)

`SemiAdditivePolicy.rule` maps `last → MAX`, `first → MIN`; `avg`/`max`/`min` are not expressible via `non_additive_dimension` → `UnsupportedByTarget` naming the rule.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `tests/fixtures/non_additive_aov/marts.yaml` `tests/unit/test_emit/test_metricflow.py`

### S-0030/D-6 — `ASSUMED` (MetricFlow backend: manifest emitter and planner adapter)

Mart-coverage precheck runs **before** delegation and preserves the refusal policy: all measures on one mart (else `UnreachableAtGrain` with S-0028's exact per-metric grain/mart message), all dimensions flattened onto it, multi-candidate → `cost_hint` then lexicographic. MetricFlow could plan multi-hop joins; we refuse first — refuse-don't-guess enforced twice (coverage, then MetricFlow's resolver). Belt and braces.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/planner/coverage.py` `src/bloomery/planner/metricflow_planner.py` `tests/fixtures/multi_mart_refusal/marts.yaml` `tests/unit/test_emit/test_cube.py`

### S-0031/D-3 — `ASSUMED` (Hydration and caching of the planner artifact)

Two-level cache: L2 = post-`transform()` manifest JSON (~145 KB, ~23 ms to build) in the **caller's** store — bloomery defines only the key and the bytes (no I/O, hard invariant #1) via pure `build_manifest_bytes` / `hydrate_manifest`; L1 = hydrated `SemanticManifestLookup` (~1.6 MB, ~29 ms from L2) in an in-process LRU (`ManifestHydrator` Protocol + `LruManifestHydrator(max_entries=...)`). Post-transform storage makes hydration `parse_raw` + lookup only.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/runtime/hydration.py` `tests/unit/test_runtime/test_hydration.py`

### S-0031/D-5 — `ASSUMED` (Hydration and caching of the planner artifact)

Serialization via MetricFlow's pydantic-v1-style `.json()` / `.parse_raw()`, sorted keys where controllable; never pickle (not deterministic, not version-safe). Manifest determinism is S-0030's emitter contract; this RFC owns key + budgets + LRU.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/runtime/hydration.py` `tests/unit/test_runtime/test_hydration.py`

### S-0050/D-1 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A derived metric is `expr` over aliased inputs, each input a metric.** `inputs` is a mapping keyed by alias, not a list: the alias is the input's identity because `expr` references it, and a dict makes a duplicate alias unrepresentable rather than a validation. Consequence: `MetricIR` gains a `derived` field and the additivity guard must accept it as a decomposition.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/resolve/build.py` `src/bloomery/semantic/plan.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-2 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**An offset is `{window: "<count> <grain>"}` or `{to_grain: <grain>}`, exactly one.** The grain vocabulary is `day`, `week`, `month`, `quarter`, `year` — the mart's own date buckets (S-0027/D-4). `hour` is refused despite MetricFlow accepting it: the emitted time spine is day-grain, so an hourly offset would resolve against a spine that cannot express it.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-5 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**`cumulative:` is lowered, and the blanket `UnsupportedCumulative` refusal is deleted rather than narrowed.** The class goes with it: a reserved-surface error whose surface is no longer reserved is a class that can only mislead. Combinations that still cannot be lowered are refused by their own named guardrails (D7).

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/planner/semantic_plan.py` `tests/execution/test_period_over_period.py` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_planner/test_metricflow_planner.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-8 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A metric filter is a typed predicate list — `{dimension, op, values}` — and never a SQL string.** A string would be dialect-bound, unvalidatable against the column's declared type, and an injection surface in a compiler whose input may be untrusted. The list is ANDed; a disjunction is expressed as `in`.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/semantic/additivity.py` `src/bloomery/spec/common.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_semantic/test_ratio_rows.py` `tests/unit/test_spec/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0059/D-4 — `LOCKED` (Loose ends inside shipped subsystems)

`emit_manifest`'s missing-`date_dimension` `EmitError` propagates out of the emitter unchanged rather than being caught and re-raised as an emit-layer message. Two spellings of one refusal is how they come to disagree.

- Paths: `src/bloomery/emit/metricflow/__init__.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0059/D-5 — `OPEN` (Loose ends inside shipped subsystems)

The manifest's artifact path — `semantic_manifest.json` at the root, or under a namespace. Settled by execution; §10 states the case for the root.

- Paths: `src/bloomery/emit/metricflow/__init__.py`

### S-0075/D-2 — `LOCKED` (Mechanical imports and per-relationship provenance)

**A dbt `relationships` test alone imports nothing.** It asserts every value exists in a target column and says nothing about the target being unique, so reading it as `many_to_one` invents the cardinality that makes the edge determine anything — S-0057/D-3's failure, by its own example. `many_to_one` from dbt requires the `relationships` test *and* a `unique`/`primary_key` on the named target. Locked because the tempting version of this importer is the one that skips the second test, and it would be indistinguishable in review from the correct one. Proposed by execution — see `logs/T-0053.md` (`logs/T-0053.md`) (D3, attempt 1).

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/guardrails/evidence.py` `src/bloomery/semantic/proof.py` `src/bloomery/spec/entity.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0075/D-10 — `LOCKED` (Mechanical imports and per-relationship provenance)

**A relationship's name is unique across a project.** Nothing made it so and every consumer treats it as a key, each resolving a collision differently and silently: a mart's `via:` takes the first match, `plan` keeps the last of a `{name: rel}` dict, and D1's lookup marked every same-named authored edge as imported. Refused at resolution rather than fixed per reader — the readers are four and the fact is one. Locked because D1's lookup is keyed by that name, so relaxing it reintroduces a wrong refusal rather than an ambiguity. Added by execution 2026-09-13 — see PR #115 review.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/guardrails/evidence.py` `src/bloomery/semantic/proof.py` `src/bloomery/spec/entity.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
