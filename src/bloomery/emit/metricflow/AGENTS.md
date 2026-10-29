<!-- torve:managed src/bloomery/emit/metricflow — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/emit/metricflow/`

### S-0022/D-12 — `ASSUMED` (Resolution: dependency DAG, recipes, reachability)

When a metric requires a canonical that a joined entity's column links, rather than a grain column, that canonical is bound per mart and not in the IR. Where a mart flattens that column, the expression the mart's measure, its rollups and the query planner's explanation read names the one mart column flattened from it, under that mart's prefix, and a name the mart already carries is read as written. The IR keeps the canonical. D-10's rules carry over: a date bucket is not such a column, a canonical two columns could stand for is left as written, and so is one whose column is spelled as a name the expression reads. The measure check of S-0050/D-16 reads the same bound expression, so a mart that does not flatten the column is refused by name

- Paths: `src/bloomery/ir/lower.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/lower/rollups.py` `src/bloomery/planner/explain.py` `tests/unit/test_guardrails/test_per_unit_parent.py`
- Consequence: A template can name a parent's canonical, and two marts that flatten the parent under different prefixes each read their own column from one definition. The IR, every fingerprint and `plan()`'s diff of two IRs are unchanged, because the binding happens after them; a query plan's SQL and explanation read the bound column. The planner's declared type for a bare-column measure still reads the expression as the IR has it, so a bare per-unit canonical gets the wide decimal it gives any expression

### S-0023/D-13 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

The `over` of a semi-additive metric names the source column of a date role — the column a `{date: …, role: …}` flatten step is declared over — never a bucket that role produces (`<role>_day` and the rest), and every mart listing the metric among its measures must declare a date role over that column. A mart that does not is refused at the guardrail stage as `MartMissingTimeDimension`, and the MetricFlow emitter re-refuses it

- Paths: `src/bloomery/guardrails/metrics.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/planner/explain.py` `tests/unit/test_guardrails/test_metrics.py` `tests/fixtures/semi_additive_over_refusal/metrics.yaml` `tests/golden/refusals/semi_additive_over_refusal.txt` `pages/docs/reference/spec-schemas.md`
- Consequence: `over: snapshot_day` beside `{date: stock_date, role: snapshot}` is refused at `bloomery check`, naming `stock_date`, rather than compiling clean and failing only when the MetricFlow manifest is built; a mart added to a metric's listing without the role is refused even when another mart owns the metric

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

### S-0059/D-5 — `ASSUMED` (Loose ends inside shipped subsystems)

The MetricFlow target emits its one artifact at the root as `semantic_manifest.json` (`MANIFEST_PATH`), not under a namespace: a MetricFlow project holds a single top-level manifest, and nothing else in the emitted tree competes for the name.

- Paths: `src/bloomery/emit/metricflow/__init__.py`

### S-0075/D-2 — `LOCKED` (Mechanical imports and per-relationship provenance)

**A dbt `relationships` test alone imports nothing.** It asserts every value exists in a target column and says nothing about the target being unique, so reading it as `many_to_one` invents the cardinality that makes the edge determine anything — S-0057/D-3's failure, by its own example. `many_to_one` from dbt requires the `relationships` test *and* a `unique`/`primary_key` on the named target. Locked because the tempting version of this importer is the one that skips the second test, and it would be indistinguishable in review from the correct one. Proposed by execution — see `logs/T-0053.md` (`logs/T-0053.md`) (D3, attempt 1).

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/guardrails/evidence.py` `src/bloomery/semantic/proof.py` `src/bloomery/spec/entity.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0075/D-10 — `LOCKED` (Mechanical imports and per-relationship provenance)

**A relationship's name is unique across a project.** Nothing made it so and every consumer treats it as a key, each resolving a collision differently and silently: a mart's `via:` takes the first match, `plan` keeps the last of a `{name: rel}` dict, and D1's lookup marked every same-named authored edge as imported. Refused at resolution rather than fixed per reader — the readers are four and the fact is one. Locked because D1's lookup is keyed by that name, so relaxing it reintroduces a wrong refusal rather than an ambiguity. Added by execution 2026-09-13 — see PR #115 review.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/guardrails/evidence.py` `src/bloomery/semantic/proof.py` `src/bloomery/spec/entity.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0087/D-1 — `ASSUMED` (What each emitter carries of the facts a spec declares)

A mart's owner reaches its MetricFlow semantic model and a metric's owner its metric, both as `config.meta.owner`; with no owner `config` stays null, and an entity's owner is not carried: an entity reaches MetricFlow only as entity elements inside the marts' semantic models, which carry the marts' owners; this answers S-0062/Q-2

- Paths: `src/bloomery/emit/metricflow/__init__.py` `tests/unit/test_ownership.py`
- Consequence: the fourth target carries the owner the other three already do

### S-0087/D-3 — `ASSUMED` (What each emitter carries of the facts a spec declares)

An exposure emits no MetricFlow `saved_query`, and this is not a refusal: a saved query is a request and an exposure a consumer, with no group-by, no slot for a mart, and metrics the manifest may lack; this answers S-0063/Q-1

- Paths: `src/bloomery/emit/metricflow/__init__.py` `tests/unit/test_emit/test_metricflow.py`
- Consequence: the manifest's `saved_queries` holds only queries someone wrote

### S-0092/D-8 — `ASSUMED` (Generated SQL agrees with a reference evaluator)

Only the build-time `divide` and a recipe's `/` carry the exact-division marker (S-0046/D-3, S-0090/D-3), which every port renders as exact division except DuckDB, whose division is knowingly inexact (`dialects/base.py`); every other division, at query time included, is the engine's own `/`. A ratio metric divides its numerator by `NULLIF(denominator, 0)`, in the composed planner and the Cube emitter alike, and MetricFlow's PostgreSQL rendering of a ratio casts the numerator to `DOUBLE PRECISION`. A metric's `expr` and a `derived:` expression keep their authored SQL: their `/` has no automatic zero guard, and its result type is the engine's for the emitted operand types and casts. This is intended: S-0020/D-5 bans floats in the IR and in emitted artifacts, not in the arithmetic an engine runs. The later query-time reference models these cases as stated here and cites this row.

- Paths: `src/bloomery/transforms/_builtins.py` `src/bloomery/planner/compose.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/emit/cube/__init__.py` `src/bloomery/planner/coverage.py`
- Consequence: a reference for query-time SQL has a stated semantics to hold the planner to, instead of guessing which division is meant

### S-0094/D-1 — `LOCKED` (Descriptions, labels and synonyms on fields and metrics)

Descriptions, labels and synonyms change no SELECT. They reach metadata slots only, and every existing golden's SQL is byte-identical with them absent, asserted rather than assumed

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py`
- Consequence: A project can add or edit any of the three without its models rebuilding or its fingerprinted SQL moving, beyond the one IR version bump of D-4
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0094/D-5 — `ASSUMED` (Descriptions, labels and synonyms on fields and metrics)

Each annotation reaches exactly the slots of the routing table in `where-each-lands` and no other. A field's description and label become a MetricFlow dimension's `description` and `label`, a Cube dimension's `description` and `title`, and a dbt column's `description`. A metric's label becomes MetricFlow's `label` and Cube's `title`, and its synonyms become `config.meta.synonyms` and `meta.synonyms`. Synonyms never go into a label or a description. dbt writes an entity's or a mart's `schema.yml` entry, and lists a column in it, whenever the column carries an annotation, whether or not it also has tests, a classification, an owner or grants

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py`
- Consequence: A reader of an artifact finds each annotation in the one place its target defines for it. SQLMesh carries none, until a consumer of its artifacts asks for `column_descriptions`

### S-0094/D-7 — `ASSUMED` (Descriptions, labels and synonyms on fields and metrics)

A mart column carries the description and label of the entity column it was flattened from, prefixed or not, and a date role's buckets carry their source column's. Every target looks a mart column up by `(source_entity, source_column)`, as MetricFlow already does for descriptions

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py`
- Consequence: `product_brand` on a wide mart shows the `brand` field's description, and no mart can describe one column differently from another

### S-0094/D-11 — `ASSUMED` (Descriptions, labels and synonyms on fields and metrics)

`Metric` and `MetricTemplate` gain optional `better`, one of `higher`, `lower` or `neither`: which direction of change in the metric is good news. It merges from a template as `label` does, the authored value first, and `MetricIR` gains it, with `bloomery_ir_version` moving by one. Absent from both, it is undeclared, `None`, and nothing is emitted. A ratio or derived metric never infers it from its parts. It becomes MetricFlow's `config.meta.better` and Cube's `meta.better` on the metric's measure, changes no SELECT, and a change to it is ADDITIVE, metadata only, as D-8 has it for the other annotations

- Paths: `src/bloomery/spec/common.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/catalog.py` `src/bloomery/resolve/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/emit/cube/__init__.py` `src/bloomery/plan/diff.py` `tests/unit/test_spec/test_metric_better.py`
- Consequence: A consumer that colours a delta, reads a target on a cost as a ceiling or alerts on pace takes the direction from the semantic layer's metadata instead of a list of metric names kept beside the display labels, which went stale on a rename. An undeclared metric reads as undeclared, so a consumer still chooses its own default for it. Every fingerprint of a project with a metric moves once

<!-- /torve:managed -->
