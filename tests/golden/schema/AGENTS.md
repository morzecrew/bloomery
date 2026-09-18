<!-- torve:managed tests/golden/schema — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/golden/schema/`

### S-0019/D-4 — `ASSUMED` (Spec layer and error model)

Parse validates shape and grammar only; reference existence (entities, transforms, canonical fields) is deferred to resolve/typecheck. Consequence: a shape-valid spec with dangling references parses fine — callers must run `resolve` to trust it.

- Paths: `src/bloomery/marts/flatten.py` `src/bloomery/resolve/refs.py` `src/bloomery/spec/__init__.py` `src/bloomery/spec/entity.py` `src/bloomery/spec/mapping.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `tests/golden/schema/metrics.json` `tests/property/test_schema_agreement.py` `tests/unit/test_spec/test_entity.py`

### S-0019/D-9 — `ASSUMED` (Spec layer and error model)

(Amended for `_bloomery-changes.md`) A fifth spec kind `marts:` joins the four (S-0027); `semi_additive` metrics carry a typed `SemiAdditivePolicy` and `non_additive` metrics a `RatioSpec` (S-0028/D-5). Spec-layer scope is still shape/grammar only.

- Paths: `src/bloomery/spec/common.py` `src/bloomery/spec/marts.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_spec/test_metrics.py`

### S-0019/D-10 — `ASSUMED` (Spec layer and error model)

(Amended for `_bloomery-metricflow-pivot.md`) `metric_time` is a reserved dimension/field name, rejected at spec validation with a clear message (S-0030 R4). The `Metric` model reserves optional `cumulative:` (window / grain_to_date) and derived-expression forms lowered per S-0030's mapping table; both are additive spec surface, parse-validated only.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/spec/common.py` `src/bloomery/spec/entity.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `tests/golden/schema/catalog.json` `tests/golden/schema/entity_model.json` `tests/golden/schema/marts.json` `tests/golden/schema/metrics.json` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_spec/test_metrics.py`

### S-0020/D-5 — `ASSUMED` (Intermediate representation and determinism contract)

Floats are banned in IR and emission; `Decimal`/int only.

- Paths: `src/bloomery/cli/serialize.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/steps.py` `src/bloomery/ir/fingerprint.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/request.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/common.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `src/bloomery/steps/manifest.py` `src/bloomery/steps/splice.py` `src/bloomery/transforms/_builtins.py` `src/bloomery/typing/types.py` `tests/execution/test_as_of_join.py` `tests/execution/test_currency_convert.py` `tests/execution/test_fanout_trap.py` `tests/execution/test_marts.py` `tests/execution/test_period_over_period.py` `tests/execution/test_rollup.py` `tests/fixtures/semantic_corpus/002-average-of-averages/naive.sql` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/golden/schema/marts.json` `tests/support/planning.py` `tests/support/semantic_corpus.py` `tests/unit/test_cli.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_planner/test_request.py` `tests/unit/test_quality/test_edges.py` `tests/unit/test_spec/test_metrics.py` `tests/unit/test_spec/test_quality.py` `tests/unit/test_steps/test_lowering.py` `tests/unit/test_steps/test_manifest_and_registry.py` `tests/unit/test_typing/test_types.py`

### S-0022/D-2 — `ASSUMED` (Resolution: dependency DAG, recipes, reachability)

The compiler never chooses a recipe. The mapping's recorded `recipe:` id is validated — id exists on the catalog field, every `requires` name bound by the mapping's `from` aliases (exactly) — else `ResolutionError`. Choice happens upstream; the compiler reproduces it (determinism + auditability, spec §3.4). Consequence: catalog evolution can invalidate recorded choices, and that is a loud error, not a silent re-choice.

- Paths: `src/bloomery/evidence.py` `src/bloomery/guardrails/operands.py` `src/bloomery/resolve/recipes.py` `src/bloomery/resolve/resolution.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/mapping.py` `tests/golden/schema/catalog.json` `tests/golden/schema/mapping.json` `tests/unit/test_resolve/test_edge_shapes_offcorpus.py` `tests/unit/test_resolve/test_recipes.py`

### S-0023/D-8 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Range sanity: the guardrail stage validates `assert:` clauses for well-typedness against the field's `LogicalType` only (`AssertLoweringError`); lowering to target-native audits happens via `AuditIR` at emit (S-0020, S-0025).

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/asserts.py` `src/bloomery/guardrails/stage.py` `src/bloomery/quality/predicates.py` `src/bloomery/spec/entity.py` `src/bloomery/spec/quality.py` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/unit/test_guardrails/test_asserts.py` `tests/unit/test_guardrails/test_quality.py`

### S-0024/D-3 — `ASSUMED` (Plan: spec diff and change classification)

Renames are explicit only: `renamed_from: <old>` in the spec (carried as `ColumnIR.renamed_from`, an S-0020 amendment). No heuristic inference — determinism and auditability beat convenience. A stale annotation (old name absent from `old`, including `old is None`) raises `RenameTargetMissing` (`PlanError`), which forces the annotation to be dropped after one applied plan.

- Paths: `src/bloomery/errors.py` `src/bloomery/plan/diff.py` `src/bloomery/plan/model.py` `src/bloomery/spec/entity.py` `tests/fixtures/evolution_v3/entity_model.yaml` `tests/golden/schema/entity_model.json` `tests/property/test_plan_properties.py` `tests/unit/test_plan/test_diff.py` `tests/unit/test_plan/test_evolution.py`

### S-0025/D-13 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

(Reverses D6) Bloomery owns the date dimension: one catalog definition emits both the SQLMesh `gold.dim_date` model and the MetricFlow time-spine declaration (S-0030 R1). D6's demand-gate is satisfied — MetricFlow is the demand.

- Paths: `src/bloomery/emit/lower/marts.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/metrics.py` `tests/execution/test_marts.py` `tests/fixtures/ecom_basic/catalog.yaml` `tests/golden/schema/catalog.json` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_fixtures.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_metrics.py`

### S-0027/D-3 — `ASSUMED` (Marts and role-playing dimensions)

`flatten` via-steps require declared `many_to_one`/`one_to_one` relationships (else `FanoutRisk`); chains flatten transitively in authored order; prefixes mandatory; collisions are errors, never auto-renames.

- Paths: `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `src/bloomery/spec/marts.py` `tests/golden/schema/marts.json` `tests/unit/test_marts/test_flatten.py` `tests/unit/test_spec/test_marts.py`

### S-0027/D-4 — `ASSUMED` (Marts and role-playing dimensions)

Date roles expand to exactly `{day, week, month, quarter, year}` bucket columns named `<role>_<bucket>`; `hour` is deliberately not expanded.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/lower/marts.py` `src/bloomery/marts/flatten.py` `src/bloomery/planner/coverage.py` `src/bloomery/planner/request.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `tests/golden/schema/marts.json`

### S-0027/D-7 — `ASSUMED` (Marts and role-playing dimensions)

Marts are optional: a project without a `marts:` document compiles silver only; the planner then refuses everything with `UnreachableAtGrain` (no marts, no serving surface).

- Paths: `src/bloomery/marts/flatten.py` `src/bloomery/spec/marts.py` `tests/golden/schema/marts.json`

### S-0027/D-8 — `ASSUMED` (Marts and role-playing dimensions)

`cost_hint` (int, default 1) is a tie-breaking scan-cost hint only; selection ties break lexicographically (S-0020 determinism).

- Paths: `src/bloomery/emit/lower/marts.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/spec/marts.py` `tests/golden/schema/marts.json` `tests/unit/test_emit/test_metricflow.py` `tests/unit/test_planner/test_coverage.py`

### S-0028/D-5 — `ASSUMED` (Native planner: MetricRequest → QueryPlan)

Additivity lowering per D4 exactly: additive → SUM at requested grain; semi-additive (`SemiAdditivePolicy(over, rule ∈ last/first/avg/max/min)`) → sum across every dimension except `over`, rule along `over` (coarser requested grain: rule within each bucket, then sum); non-additive → never stored/summed, recomputed from additive components (`RatioSpec` → `SUM(num)/NULLIF(SUM(den),0)`); missing components = `NonAdditiveWithoutComponents` at resolution/guardrail stage (S-0023 defense-in-depth).

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/coverage.py` `src/bloomery/planner/explain.py` `src/bloomery/planner/result.py` `src/bloomery/spec/common.py` `tests/fixtures/non_additive_aov/marts.yaml` `tests/fixtures/non_additive_aov/metrics.yaml` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_planner/test_coverage.py`

### S-0033/D-1 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

The governing principle: **specs describe, specs reference implementations, specs never contain implementations.** Bronze gets no cleansing (replay source); gold gets none (rebuildable).

- Paths: `src/bloomery/spec/quality.py` `tests/fixtures/dirty/README.md` `tests/golden/schema/mapping.json`

### S-0033/D-5 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Closed field-rule catalogue: `coercible`, `not_null`, `range`, `length`, `pattern` (portable regex subset, compile-time validated per target dialect via sqlglot), `in_enum`, `in_set`, `normalize` and `charset` (added by D86, which closed D26), `unique` (evaluated per partition slice in both full and incremental modes — the partition is the scope unit either way; cross-partition duplicates out of scope in every mode, dedupe's job; sampling rejected per Document 5 §11.3). New rules are RFC amendments, not config.

- Paths: `src/bloomery/quality/catalogue.py` `src/bloomery/quality/pattern.py` `src/bloomery/quality/predicates.py` `src/bloomery/quality/reconcile.py` `src/bloomery/spec/quality.py` `src/bloomery/spec/steps.py` `tests/golden/schema/mapping.json`

### S-0033/D-86 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **The catalogue gains `normalize` and `charset`, and the confusables table is deliberately not among them. D26 is closed.** D26 offered "a Unicode normal form **and/or** a confusables table"; only the first half is built as offered. `normalize` is `NORMALIZE(col, NFC) <> col` — the dialect-neutral node, rewritten to `NFC_NORMALIZE` inside DuckDB's `render` because DuckDB has that function and no `NORMALIZE`, while SQLGlot's duckdb generator renders one verbatim (the D83 shape: renders everywhere, defined in two places out of three). One form only: Postgres and Trino spell all four, DuckDB spells one, and a rule that compiles everywhere and runs on two engines out of three is what S-0025/D-3 exists to refuse. It is a **rule and never a transform** — normalizing silently would rewrite what a source delivered, which D1 forbids. **The table is refused on determinism grounds:** UTS#39 confusables is versioned Unicode data, so embedding it would make a row's disposition depend on which Unicode revision the compiler shipped — an ambient input by another name (S-0020), and one that would move dispositions under a dependency bump nobody read as a semantic change. `charset` declares the admissible characters instead, as `U+` codepoints and inclusive ranges, exactly one of `allow:`/`forbid:`, lowering through a single `TRANSLATE(col, members, '')` read two ways. Codepoints rather than characters because every character the rule exists to catch is invisible: a literal one in YAML is unreadable in review and indistinguishable from a space in a diff. The `allow` reading turns out to be *stronger* than the table would have been for the case that motivated it — an allow-list of the script a column is written in catches a Cyrillic homoglyph, a fullwidth digit and an Arabic-Indic digit alike, none of which any denylist enumerates completely. Three declaration refusals, all decidable from the spec alone and so `GuardrailError`s: a backwards range, a range crossing the surrogate block (checked on the *span*, not the endpoints — the block is 2048 wide, so an endpoint-only check would leave the real refusal to arrive from `MAX_CHARSET_SIZE`, a constant that has nothing to do with surrogates and could grow), and a set past that cap, which exists because the members become a string literal in every row's predicate and in the IR fingerprint. `TRANSLATE` carries **no** `DialectFeature`: all three engines spell it identically and its delete-when-shorter behaviour was executed on each rather than assumed; a feature flag earns its place where the *port* has to differ, which is why `normalize` has one and this does not. Verified by execution on postgres 16 as a permanent engine tier and on `trinodb/trino:483` by hand (no Trino client dependency yet — S-0026's outstanding work), both agreeing with DuckDB on every specimen including the null. **Found on the way:** the §6 matrix rendered through `node.sql(dialect="duckdb")` rather than through the port, so it executed SQL the emitter never emits. Here that surfaced as a failure — DuckDB has no `NORMALIZE` at all — but the failure is incidental to the direction of this particular rewrite. A port rewrite that produces something the *direct* render also accepts would have diverged silently, with the matrix green on SQL no artifact contains. It is routed through the port now.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/duckdb.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/quality/charset.py` `src/bloomery/quality/predicates.py` `src/bloomery/spec/quality.py` `tests/engines/test_postgres_text_rules.py` `tests/golden/schema/mapping.json`

### S-0033/D-87 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **`repair` lands, its recipe is a registered `sql_macro`, and its marker is its own column. D17 is closed.** D17 gated the disposition on a repair-recipe contract and left §10 asking *inline vs catalog-referenced*. S-0034's step registry answers both at once: a recipe is `ref@version` into the registry — declared signature, `runtime_lock`, determinism tier, trust-then-verify — and D1 already holds that specs reference implementations and never contain them, so an inline recipe would have been a second, weaker copy of all of it reachable only from here. **The lowering.** The recipe is spliced at IR build, where the registry lives, and travels as SQL in the rule's params the way an `expression` rule's body does — so emission needs no registry, and a version or `runtime_lock` bump lands in the IR where the fingerprint and `plan()` see it (measured: a body change classifies RESTATING and puts the entity in `replay_scope`, because the kind's params define neither an ordered interval nor a membership set and D52's undecidable-means-replay applies). The rewrite happens at the **extract** level, inside the column's own projection: `CASE WHEN <violation over the raw expression> THEN <recipe> ELSE <raw> END`. That placement is what makes every other rule see the repaired value with no extra nesting, and it forces both halves to be rewritten to read the column's expression rather than its name, since the column is being defined in the same `SELECT`. **The marker.** `_quality_repairs` is a separate column, which was cubic's condition in review and is the right one: a rule is recorded there when its recipe *ran and worked* — it fired over the value as delivered and no longer fires over the value that replaced it. `_quality_flags` stays empty for a repaired row, so `has_quality_flags` keeps meaning **currently suspect** and no mart already asking that question changes its answer. Unlike the two universal columns it is emitted only where a repair rule exists: §12 budgeted the silver-schema churn once, and a third column empty for every project not using the feature is not worth re-opening every golden and fingerprint for. **`fallback` is required**, for the same reason `on_fail` is (D2): a recipe that ran and failed leaves the rule violated and the row is disposed of exactly as if no repair had been declared — the alternative, a still-broken value landing in silver marked as fixed, is the `drop` this RFC refuses wearing a friendlier name. **Refusals**, each a property of the declaration alone: `repair` on `coercible` (it fires *because* the projection is already NULL, so the recipe would be handed the NULL rather than the text that failed to cast — fixing a value before coercion is a Tier 1 macro in the mapping, and the message says so), on `unique` (a property of a population; no rewrite of one row makes a duplicate unique), on a row rule (no column to rewrite), two repair rules on one column (both rewrite the same projection, so which value survives would depend on authoring order and the second recipe would judge a value the first had changed), a recipe accepting more than one column (a rule has no `from:` map, and inventing one would make a rule a second mapping surface), and a column the dedupe order reads (dedupe runs *before* the field rules per D7, so the winner would be chosen on the value as delivered and then have that value rewritten underneath it — D6's reasoning exactly). Verified by executing the emitted pipeline over three rows — one the recipe fixes, one it cannot, one it must not touch — and by sabotage: disabling the recipe, and dropping the "did it run" conjunct from the marker, each fail the assertion that names them. **Not built:** `gold.mart_data_quality` gains no `rows_repaired`, so repairs are observable in silver and not in the quality mart. Recorded rather than implied — adding a measure changes the mart schema, and no demand has asked for it.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/lower.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/spec/quality.py` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/golden/schema/steps.json` `tests/unit/test_spec/test_quality.py`

### S-0033/D-89 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **Mart-level checks are assertions, not quality rules. §10's open question is settled by the disposition model.** §8 deferred them as "blurs into reconciliation" and §10 asked "reconcile-shaped or new surface?" — the answer is neither, and what decides it is not taste. §5.9 draws the boundary at what a verdict *does*: a quality rule disposes of a **row**. A mart row is derived — no `_source_row_id`, no bronze payload, no reject table, no replay — so there is nothing to quarantine, nothing to repair, and nothing to bring back; and a `reconcile` compares *two sides*, which "no month has zero revenue" is not. What is left is D4's other half, "alert me", so `assert:` on a mart declares `{measure, agg, by, min/max, on_fail}` and lowers to an audit the mart model names. `quarantine` and `repair` are absent from its `on_fail` rather than lowered to something weaker, so an author who wanted routing learns it at the surface instead of from a mart that silently only alerts; `fail`/`flag` map to blocking/non-blocking exactly as `reconcile.on_fail` does (D38). The aggregate vocabulary is deliberately the *same tuple* the reconcile grammar uses — both compute one number over a column so a human can be told it is wrong, and two lists that mean the same thing drift. Bounds ride in `params` as text through the D57 carrier, for the same reason. **Resolution is against the flattened column set**, not the base entity's: `ordered_month` exists only because a `date:` step made it, and it is precisely the column §10's example groups by. **The body** is `SELECT <by…>, <agg>(<measure>) FROM @this_model [GROUP BY <by…>] HAVING <bound comparison>` — the value beside the group, because a failure a human must open the warehouse to understand gets ignored. A bare `HAVING` with no `GROUP BY` is the whole-mart form; both shapes were executed on DuckDB, postgres 16 and `trinodb/trino:483` rather than read out of three manuals, and all three agree. **What it cannot see, stated rather than implied:** D19 reaches the mart, so every aggregate but `count` is NULL over an empty group and the assertion stays silent — which is also why an assertion cannot notice a month that is *entirely missing*: no row means no group at all. `count` is the exception and is the one shape that catches an empty mart. Closing the missing-period case needs a join against the date spine, a coverage check with its own dependency, and it is named here rather than half-built. **dbt refuses a project carrying one**, sharing `refuse_steps`' message shape (**amended by D94**: this row said "dbt and Cube", and the Cube half was already obsolete when it was written — S-0034/D-52 had split the blanket Cube refusal on the argument that Cube builds no relation for anything, and Cube compiles the *entire* quality surface, quarantine and reject tables included, without a murmur; refusing this one check would single it out): neither has the audit form, and compiling clean while the declared gate does not exist is the failure D83 caught in the dialect ports. **Cost recorded:** `MartIR` gains a field, and the canonical encoder covers each node's field *names and count*, so every fingerprint in the corpus moves — the churn §12 budgets, spent deliberately. The fixture carrying the demonstration is `quality_precedence` rather than `ecom_basic`, because an assertion makes a project uncompilable for two targets and `ecom_basic` is the fixture those targets' goldens are built on.

- Paths: `src/bloomery/emit/base.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/marts/flatten.py` `src/bloomery/spec/marts.py` `tests/execution/test_quality_precedence.py` `tests/fixtures/quality_precedence/marts.yaml` `tests/golden/schema/marts.json`

### S-0034/D-13 — `ASSUMED` (The step registry: referenced implementations)

Implementation binding: `StepRegistry` gains `sql_bodies: Mapping[tuple[str, int], str]` (`sql_model` bodies, parsed at compile like `macro_bodies`); `StepManifest` gains `entrypoint: str` (`"package.module:function"`) for `python_model`, and the generated wrapper imports it at **run time**. The no-dynamic-loading rule is scoped to compile time — bloomery never imports or executes step code while compiling (manifests and SQL text only); runtime import of platform-owned code by the generated model is the normal SQLMesh execution path, and registry build (caller-side) verifies the entrypoint resolves.

- Paths: `src/bloomery/spec/mapping.py` `src/bloomery/steps/manifest.py` `tests/e2e/test_sqlmesh_replan.py` `tests/golden/schema/mapping.json`

### S-0034/D-51 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-09)* **A macro declares its signature; it is never read off its body.** The first cut inferred the signature from the body's `:name` placeholders. That is the third appearance of one temptation, and it is refused for the third time — D43 refused fabricating references from matching key columns, D49 refused auto-linking canonical fields by name. The deciding argument is the ladder itself: Tier 0's `TransformSpec` declares `input_domain` **and** `output_type`, so a macro declaring neither would be the one tier whose inputs nothing checks, while §5.1's table claims Tier 1 can *parse and typecheck*. `StepManifest` gains `accepts: {column: type}` — a separate key from `inputs:`, which is relation-shaped for table steps, because one key meaning two things by kind reads fine only to whoever wrote it. The output type needs no new field: a macro has exactly one output of exactly one column (D18b). This buys three things. The **body** is checked against the declaration once, at the registry, where a disagreement is the platform's bug rather than a puzzle handed to every call site. The **call site** is checked against the declaration, so the message names what the macro expects instead of only which placeholder was unfilled. And a **chain** is typechecked *around* the link: the run before it against what it accepts, the run after it from what it produces — implemented as segments queued into the ordinary batch stage, so S-0023/D-2's one-aggregate property survives for chains containing a macro. Named cost, recorded rather than discovered: a genuinely polymorphic macro (`COALESCE(:a, :b)` over any type) must now pick a concrete type. Tier 0 carries the identical constraint through `input_domain`, so it is consistent rather than a new tax — but it is a real limit. A chain link must accept exactly one column, since a chain carries one running value; a two-column macro is refused there and pointed at the field shape.

- Paths: `src/bloomery/resolve/build.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/mapping.py` `tests/golden/schema/mapping.json` `tests/property/test_schema_agreement.py` `tests/unit/test_resolve/test_declared_zone.py` `tests/unit/test_schema.py`

### S-0050/D-1 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A derived metric is `expr` over aliased inputs, each input a metric.** `inputs` is a mapping keyed by alias, not a list: the alias is the input's identity because `expr` references it, and a dict makes a duplicate alias unrepresentable rather than a validation. Consequence: `MetricIR` gains a `derived` field and the additivity guard must accept it as a decomposition.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/resolve/build.py` `src/bloomery/semantic/plan.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-2 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**An offset is `{window: "<count> <grain>"}` or `{to_grain: <grain>}`, exactly one.** The grain vocabulary is `day`, `week`, `month`, `quarter`, `year` — the mart's own date buckets (S-0027/D-4). `hour` is refused despite MetricFlow accepting it: the emitted time spine is day-grain, so an hourly offset would resolve against a spine that cannot express it.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-8 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A metric filter is a typed predicate list — `{dimension, op, values}` — and never a SQL string.** A string would be dialect-bound, unvalidatable against the column's declared type, and an injection surface in a compiler whose input may be untrusted. The list is ANDed; a disjunction is expressed as `in`.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/semantic/additivity.py` `src/bloomery/spec/common.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_semantic/test_ratio_rows.py` `tests/unit/test_spec/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0066/D-5 — `ASSUMED` (Declared input currency for conversion)

**Per-row denomination is admitted by the vocabulary from the first commit, and refused as unbuilt until P2.** Adding it later means a second mechanism for "what currency is this in", which is the argument that withdrew S-0054's P3. Not `LOCKED` because if P1 shows the `column:` form distorts the declaration's shape, a separate spelling is a defensible retreat — but it must then be designed, not improvised.

- Paths: `src/bloomery/spec/mapping.py` `tests/golden/schema/mapping.json`

<!-- /torve:managed -->
