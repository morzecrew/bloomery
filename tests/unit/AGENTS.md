<!-- torve:managed tests/unit — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/unit/`

### S-0004/D-3 — `LOCKED` (Observability: logging and a warnings channel)

Logging is not load-bearing: no test may assert behaviour through log output, and no code path may branch on logger state, with `isEnabledFor` used purely to skip expensive message assembly as the one sanctioned read

- Paths: `tests/unit/test_logging_posture.py` `tests/unit/test_determinism_guard.py`
- Consequence: This is what keeps the channel deletable; a test that reads a log makes the log an API, and it is the rule a later change is most tempted to bend
- Check: `uv run pytest tests/unit/test_determinism_guard.py tests/unit/test_logging_posture.py -q` (shadow; runs as `decision:S-0004/D-3`, no log entry owed)

### S-0004/D-10 — `ASSUMED` (Observability: logging and a warnings channel)

The advisory vocabulary is a closed enum with no free-text constructor, and every member has a row in the reference's advisory table while every documented code is constructible — checked in both directions

- Paths: `src/bloomery/evidence.py` `pages/docs/reference/errors.md` `tests/unit/test_docs_floor.py`
- Consequence: Adding an advisory is a reviewed change that lands its documentation row with it; a documented code no path can construct fails the census, which is what blocks the deprecated-spelling advisory until a spelling is actually deprecated
- Check: `uv run pytest tests/unit/test_docs_floor.py -q` (shadow; runs as `decision:S-0004/D-10`, no log entry owed)

### S-0005/D-6 — `LOCKED` (Semantic proof IR and closed-world checking)

Proof serialization is deterministic: canonical premise order, stable rule identifiers, no memory addresses, no timestamps, no dependence on traversal order, and premises and facts sorted on construction rather than trusted in arrival order

- Paths: `src/bloomery/semantic/proof.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/cli/render.py` `tests/unit/test_determinism_guard.py`
- Consequence: Equivalent authored ordering produces equivalent proof serialization, so a golden or a continuous-integration assertion over a derivation is a statement about the design rather than about the order a dictionary happened to iterate in
- Check: `uv run pytest tests/unit/test_semantic/test_proof.py::test_premise_order_is_canonical_not_construction_order tests/unit/test_semantic/test_proof.py::test_serialization_carries_nothing_that_varies_between_processes -q` (shadow; runs as `decision:S-0005/D-6`, no log entry owed)

### S-0006/D-4 — `ASSUMED` (Evidence-based semantic capability matrix)

Rows are the cases of the semantic bug corpus under `tests/fixtures/semantic_corpus/`, not a separately invented taxonomy; a row the matrix needs and the corpus does not carry is a missing corpus case first

- Paths: `comparisons/MATRIX.md` `tests/unit/test_comparisons_floor.py`
- Consequence: Departing means the matrix needs a row no corpus case covers — in which case the case is what is missing, and it belongs in the corpus document before it belongs here
- Check: `uv run pytest tests/unit/test_comparisons_floor.py::test_matrix_rows_are_the_corpus_cases -q` (shadow; runs as `decision:S-0006/D-4`, no log entry owed)

### S-0006/D-10 — `ASSUMED` (Evidence-based semantic capability matrix)

A cell returns to `UNKNOWN` when the version it pins stops matching what the reproduction resolves, or when its check date leaves a twelve-month window — and the rule is a gate, not a sentence

- Paths: `comparisons/**` `tests/unit/test_comparisons_floor.py`
- Consequence: For a system this repository does not resolve as a dependency only the date half applies, and the bundle says so; the window is bounded at both ends, because a bound tested from one side let a future-dated bundle pass the gate whose purpose is noticing that a cell has stopped being current
- Check: `uv run pytest tests/unit/test_comparisons_floor.py -q` (shadow; runs as `decision:S-0006/D-10`, no log entry owed)

### S-0019/D-6 — `ASSUMED` (Spec layer and error model)

Parse-stage errors are batched per document (all failures reported at once).

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/errors.py` `src/bloomery/evidence.py` `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/build.py` `src/bloomery/resolve/refs.py` `src/bloomery/spec/common.py` `src/bloomery/spec/project.py` `src/bloomery/typing/check.py` `tests/unit/test_cli.py` `tests/unit/test_evidence.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_refs.py` `tests/unit/test_spec/test_mapping.py` `tests/unit/test_spec/test_project.py` `tests/unit/test_spec/test_sql_text.py`

### S-0020/D-5 — `ASSUMED` (Intermediate representation and determinism contract)

Floats are banned in IR and emission; `Decimal`/int only.

- Paths: `src/bloomery/cli/serialize.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/steps.py` `src/bloomery/ir/fingerprint.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/request.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/common.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `src/bloomery/steps/manifest.py` `src/bloomery/steps/splice.py` `src/bloomery/transforms/_builtins.py` `src/bloomery/typing/types.py` `tests/execution/test_as_of_join.py` `tests/execution/test_currency_convert.py` `tests/execution/test_fanout_trap.py` `tests/execution/test_marts.py` `tests/execution/test_period_over_period.py` `tests/execution/test_rollup.py` `tests/fixtures/semantic_corpus/002-average-of-averages/naive.sql` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/golden/schema/marts.json` `tests/support/planning.py` `tests/support/semantic_corpus.py` `tests/unit/test_cli.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_planner/test_request.py` `tests/unit/test_quality/test_edges.py` `tests/unit/test_spec/test_metrics.py` `tests/unit/test_spec/test_quality.py` `tests/unit/test_steps/test_lowering.py` `tests/unit/test_steps/test_manifest_and_registry.py` `tests/unit/test_typing/test_types.py`

### S-0020/D-11 — `ASSUMED` (Intermediate representation and determinism contract)

*(2026-08-12)* **A lookup that an earlier stage makes total says which stage, and no lookup may fail as a bare `StopIteration`.** `next(x for x in xs if …)` over a validated set is correct and fails terribly: no message, no source path, no hint about which stage was supposed to prevent it. One escaped from a `coverage` check naming an unmapped entity and read as a crash rather than as a missing refusal — the guardrail that would have caught it did not exist yet (S-0033/D-91). The invariant "every such lookup is total because a guardrail refused the case that would break it" was real and held everywhere but there; what it never had was somewhere to be *stated*, so drift was invisible. Two parts. `guaranteed(candidates, *, expected, by)` raises `InvariantViolated` naming its guarantor, so each call site carries the name of the check it depends on — the point is the `by=` argument, not the error. And an AST scan over `src/` fails on any bare `next(...)`, which is what keeps the form from returning. **The scan immediately paid for itself:** a `grep` had found six sites and the AST found **twelve** — `next(iter(xs))` and `next(generator_variable)` are the same hazard in spellings a regex written around one idiom does not see. That gap between what a scan sees and what a reader assumes it sees is the reason this is enforced rather than documented.

- Paths: `src/bloomery/errors.py` `tests/unit/test_errors.py` `tests/unit/test_signature_closure.py` `tests/unit/test_total_lookups.py`

### S-0022/D-3 — `ASSUMED` (Resolution: dependency DAG, recipes, reachability)

A canonical field is available iff some mapped field links to it via `canonical:` with a direct mapping or validated recipe. A metric is reachable iff every leaf of its `requires`/`requires_metrics` closure is available; unreachable metrics report the specific missing leaves and are stored in the IR (S-0020/D-6) as product-facing output.

- Paths: `src/bloomery/evidence.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/reach.py` `tests/unit/test_evidence.py` `tests/unit/test_unresolved.py`

### S-0024/D-2 — `ASSUMED` (Plan: spec diff and change classification)

`plan(old_ir | None, new_ir)` is a pure structural diff of two `ProjectIR`s — no external lineage, no I/O. `plan(None, ir)` = all ADDITIVE (initial deploy); `plan(ir, ir)` = empty, property-tested (S-0026).

- Paths: `src/bloomery/plan/diff.py` `src/bloomery/plan/model.py` `tests/unit/test_cli.py` `tests/unit/test_plan/test_diff.py` `tests/unit/test_plan/test_exposures.py` `tests/unit/test_plan/test_quality_changes.py` `tests/unit/test_plan/test_step_changes.py` `tests/unit/test_steps/test_step_entities.py`

### S-0025/D-13 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

(Reverses D6) Bloomery owns the date dimension: one catalog definition emits both the SQLMesh `gold.dim_date` model and the MetricFlow time-spine declaration (S-0030 R1). D6's demand-gate is satisfied — MetricFlow is the demand.

- Paths: `src/bloomery/emit/lower/marts.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/metrics.py` `tests/execution/test_marts.py` `tests/fixtures/ecom_basic/catalog.yaml` `tests/golden/schema/catalog.json` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_fixtures.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_metrics.py`

### S-0026/D-4 — `ASSUMED` (Testing strategy and fixture corpus)

The fixture corpus is exactly spec §7.7 (`minimal`, `ecom_basic`, `fanout_trap`, `semi_additive`, `messy_types`, `multi_source`, `evolution_v1..v5`), stored as YAML under `tests/fixtures/<name>/`, loaded only via public `load_project`/`load_catalog`. Consequence: the corpus is also the doc example set and future LLM-eval set — fixture edits carry corpus-level review weight. `multi_source` covers deterministic two-source union merge only; identity xref is out of scope for v0.1.

- Paths: `tests/fixtures/identity_resolution/entity_model.yaml` `tests/fixtures/multi_source/entity_model.yaml` `tests/unit/test_fixtures.py`

### S-0026/D-21 — `ASSUMED` (Testing strategy and fixture corpus)

*(2026-08-10)* **The Trino engine tier is built, on the memory connector, and `spark` is struck from §5.2.** Trino was the engine bloomery made the most claims about and executed the least: three decisions — D83's reject-table constructions, D86's `normalize`/`charset`, D89's mart-assertion body shapes — were each verified against `trinodb/trino:483` **by hand**, through `docker exec`, because the repository carried no Trino client. A hand-verification is a claim with a date on it, not a test, and all three are now a permanent tier (`trino` + `testcontainers[trino]` in the `engines` group). The strongest assertion is the one D75 said was impossible: the `<entity>__reject` model *materializes*, and its `reject_id` is compared against the canon-bytes digest computed here in Python rather than against Trino agreeing with itself — cross-engine *agreement* being the property that identity actually needs, since a replay run on one engine must find the row another quarantined. Sabotage-verified: dropping the `LOWER` from Trino's `TO_HEX` makes the digest disagree in case alone, which the tier catches and which no rendering test could. **The connector is `memory`, diverging from §5.2's `trino+iceberg+minio (compose)` sketch**: bloomery emits SELECTs and models and never storage-format DDL, so an object store and a table format would be three more moving parts serving no assertion in this tier — recorded rather than silently simplified. **`spark` is struck from the same row.** S-0025 ships DuckDB, Postgres and Trino; there is no Spark dialect, so a Spark cell had nothing to exercise and the word promised a matrix column that could never have contained a test. It returns if and when a Spark dialect does.

- Paths: `tests/engines/test_trino.py` `tests/engines/test_trino_execution.py` `tests/support/cube.py` `tests/unit/test_examples.py`

### S-0027/D-2 — `ASSUMED` (Marts and role-playing dimensions)

Measure grain must strictly equal mart grain; coarser or finer is `GrainViolation`. Resolves D2's prose/example contradiction to the strict reading; relaxation is a future additive change.

- Paths: `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/semantic/proof.py` `src/bloomery/semantic/rollup.py` `tests/fixtures/fanout_trap/marts.yaml` `tests/fixtures/fanout_trap/metrics.yaml` `tests/fixtures/semantic_corpus/001-order-shipping-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/001-order-shipping-fanout/problem.md` `tests/fixtures/semantic_corpus/010-many-to-many-bridge/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/010-many-to-many-bridge/problem.md` `tests/golden/refusals/example-wrong-grain.txt` `tests/golden/refusals/fanout_trap.txt` `tests/support/semantic_corpus.py` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_semantic_corpus_guard.py`

### S-0027/D-6 — `ASSUMED` (Marts and role-playing dimensions)

Mart flattening is resolved at IR build (`bloomery/marts/`, pure): consumers see the wide schema, never the recipe. `ProjectIR.marts` is fingerprint-covered.

- Paths: `src/bloomery/marts/flatten.py` `src/bloomery/resolve/build.py` `tests/unit/test_evidence.py` `tests/unit/test_resolve/test_build.py`

### S-0027/D-9 — `ASSUMED` (Marts and role-playing dimensions)

(Amended for `_bloomery-metricflow-pivot.md`) Marts are the emission source for MetricFlow semantic models — one mart = exactly one semantic model (S-0030 R1); a measure-carrying mart must declare a date role (`MartMissingTimeDimension` otherwise). Marts and role-playing are *more* load-bearing after the pivot, not less.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/marts/flatten.py` `src/bloomery/quality/mart.py` `src/bloomery/resolve/graph.py` `tests/fixtures/ecom_basic/marts.yaml` `tests/fixtures/quality_precedence/entity_model.yaml` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_fixtures.py` `tests/unit/test_quality/test_mart.py` `tests/unit/test_resolve/test_graph.py`

### S-0030/D-11 — `ASSUMED` (MetricFlow backend: manifest emitter and planner adapter)

Version-drift canary `test_metricflow_api_surface` is mandatory — we depend on internals with no stability guarantee; upgrades are deliberate PRs with goldens regenerated.

- Paths: `tests/unit/test_metricflow_canary.py`

### S-0033/D-56 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **The dialects a `pattern` is checked against are the shipped ports, never the registry.** `registered_dialects()` is process-global and mutable, so an extension dialect registered by an unrelated import could decide whether an existing project compiles — the ambient dependency S-0020 exists to forbid, and one no golden would catch. The checked set is the constant `PATTERN_TARGET_DIALECTS = (duckdb, postgres, trino)`, overridable by an explicit argument the caller supplies. Recorded consequence: an extension dialect is no longer checked at compile time. Checking it would mean plumbing a dialect set into `build_project_ir`, which is dialect-free by construction and right to be — a project is portable or it is not, and the guardrail stage has no target. Named as the escape hatch, not built.

- Paths: `pages/docs/how-to/add-quality-rules.md` `src/bloomery/compile.py` `src/bloomery/dialects/__init__.py` `src/bloomery/quality/pattern.py` `tests/unit/test_compile.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_quality/test_edges.py`

### S-0033/D-84 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **Postgres hosts quality-carrying entities: `TRY_CAST` is a guard around Postgres' own input parser, not a regex. D30 is closed.** D30 named the escape hatch as "a per-type `CASE`-based fallback whose semantics are proven equal to `TRY_CAST`'s on the corpus", and a per-type regex is what that sounded like. It is the wrong build: a regex is an *approximation* of the parser, and it would have to be kept in step with it forever. `pg_input_is_valid` (Postgres 16+) is the parser, so `CASE WHEN pg_input_is_valid(x, 't') THEN CAST(x AS t) END` accepts exactly what `CAST` accepts and yields NULL exactly where `CAST` raises — equal **by construction** rather than by a proof that decays. Measured anyway, because a claim that is checked is a commitment: over a 57-value adversarial corpus × 5 types, 284 of 285 cases identical to plain `CAST` modulo NULL-on-error. The rewrite lives in the dialect's `render`, so the IR keeps the dialect-neutral `TryCast` node it already had. **The 285th case is the finding.** Postgres accepts `now`/`today`/`tomorrow`/`yesterday` as datetime input and resolves them to the *transaction timestamp*, so a bronze cell spelling `now` coerces to a different value on every run — a backfill disagreeing with the run it replaces, which S-0020 exists to prevent, arriving green and unrestatable. The temporal guard excludes them, which is the one place it is deliberately **stricter** than `CAST`: such a cell becomes a coercion failure the `coercible` rule disposes of, a quarantined row rather than a silently unstable one. It also moves Postgres *toward* DuckDB, which rejects `now` outright. Verified by execution, not rendering — rendering was never the hard part, and D30's whole point was that a plain `CAST` renders beautifully and aborts the run: the quality-carrying fixture materializes on postgres 16 with the clean row kept and one specimen per failure mode quarantined, `now` among them, and the tier is now a permanent engine test. Two harness traps recorded because both nearly produced a wrong answer: a *constant* subquery is folded at plan time, so the `CASE`'s other branch evaluates and raises — the guard is only safe over a column, which is what a bronze relation always is; and psycopg reports its own inability to represent `infinity` as an error indistinguishable from a SQL one, which made three engine-accepted values look rejected. **Not closed:** cast *semantics* still differ across engines — DuckDB coerces `'1.5'` to an int and Postgres does not — so the same spec quarantines different rows on different engines. That is inherent to running on different engines, predates this change, and is recorded here rather than implied to be fixed.

- Paths: `src/bloomery/dialects/postgres.py` `tests/engines/test_type_conformance.py` `tests/support/type_conformance.py` `tests/unit/test_docs_floor.py`

### S-0033/D-90 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **Cross-entity checks are `coverage:` on a relationship, and the audit hangs off the *dependent* side. §10's last open question is settled.** §10 guessed "probably reconcile-style"; it is not, and the reason is structural rather than stylistic. A `reconcile` compares two **values** and alerts beyond a tolerance — there is no right-hand value on the referenced entity to compare against, and `right: 1` is neither a shape the closed grammar admits nor one it should grow. This asserts **existence**: every row of a relationship's referenced entity has at least `min` rows referencing it. That makes it the mirror of `referential`, which asks whether every *dependent* row has a parent, and both read the same two relations through the same `via` pairs — which is why it is declared on the **relationship** rather than on either entity. **Why an audit, when a disposition would have been meaningful.** Unlike a mart row (D89), a childless customer is a real silver row with a source identity, a reject table and a replay path, so routing it is not nonsense. It is still an audit, for a reason that only shows up in the DAG: routing would need the *referenced* entity's model to read the *dependent* one, while the dependent one already reads the referenced one through this very relationship — so the pair that most wants this check (an FK one way, a coverage check the other) is exactly the pair whose models would form a cycle. Attaching the audit to the dependent side instead adds **no edge the relationship did not already imply**. `on_fail` is `fail`/`flag` only; `quarantine` and `repair` are absent from the surface rather than lowered to something weaker. **Two emission details that are each a trap closed.** The body counts a *dependent* column, never `COUNT(*)`: a `LEFT JOIN` still produces one output row for an unmatched left row, so `COUNT(*)` answers 1 for a customer with no orders at all and the check would pass on precisely the rows it exists to find. And the dependent side is `@this_model` rather than a named relation — the macro is the one reference SQLMesh rewrites inside an AUDIT body (D29), so naming the relation resolved to the virtual layer *and* put the model into its own `depends_on`, which is how the first cut emitted it. The referenced side is a sibling and is declared in `depends_on`, the trap D40 closed for step audits. Verified by a real SQLMesh plan on a fixture added to the e2e tier for it: the comment above `step_resolution` there argues that nothing else loads SQLMesh and that the gap hid three defects in a row, and this is the same shape — an audit body joining a sibling, with a `depends_on` that exists only because of the audit. dbt refuses the project (its tests are predicates, with no grouped cross-relation form); Cube is not asked, because it builds nothing (S-0034/D-52). **Cost:** `ProjectIR` gains a field, so every fingerprint moves. **Not closed:** the check counts rows that *reached* silver, so a referenced row quarantined by its own rules reads as absent — right for "has an order", wrong for a check somebody phrases as "exists", and named here rather than discovered.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/guardrails/quality.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/lower.py` `src/bloomery/spec/entity.py` `tests/e2e/test_sqlmesh_replan.py` `tests/fixtures/coverage_check/entity_model.yaml` `tests/fixtures/dirty_corpus/entity_model.yaml` `tests/unit/test_fixtures.py`

### S-0034/D-3 — `ASSUMED` (The step registry: referenced implementations)

`StepRegistry` is a frozen compile **input** (steps mapping + macro bodies), assembled by the caller; `compile_project(..., steps: StepRegistry = EMPTY_REGISTRY)`. Unknown ref or version → `UnknownStep` naming available versions. **No dynamic loading path exists** — tenant specs can never become an arbitrary-code-execution surface.

- Paths: `src/bloomery/errors.py` `src/bloomery/spec/steps.py` `src/bloomery/steps/registry.py` `tests/unit/test_schema.py`

### S-0034/D-49 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-09)* **D41 is built: metrics and `reconcile` reach step outputs, through a declared canonical link.** What was missing was a *surface*, not a mechanism. A metric is reachable iff every leaf of its `requires` closure is **available**, and a canonical field is available iff something draws a `canonical` edge to it — which only mapped entity fields could. So a step's columns were never available and any metric over one was unreachable, for a reason narrower than D41's own wording ("metric resolution keys on mappings") suggested. `StepWiring` gains `canonical: {<output>: {<column>: <canonical_field>}}`. On the **wiring**, not in the manifest: canonical names are the authored spec's vocabulary, and a manifest naming them could not be reused by a second project spelling them differently — the fork §5.7 exists to refuse. Never inferred from a matching column name, which is D43's argument about references applied to the same temptation. Nothing about metric resolution changed: the link draws the ordinary `canonical` edge and reachability follows. `reconcile` needed a second, unrelated repair — it resolved sides against *declared and mapped* entities, and a step output is neither, so a check naming one was refused as "declared but no mapping targets it", which is true and useless since the step writes the relation. Both kinds now answer through one `_SideEntity` view (field names and key), so the check asks what it needs rather than branching on provenance; declared-but-unmapped stays refused, which was always the real point. The refusal's wording now names both ways a relation can exist.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/resolve/graph.py` `src/bloomery/resolve/refs.py` `src/bloomery/spec/steps.py` `tests/fixtures/identity_resolution/catalog.yaml` `tests/fixtures/identity_resolution/steps.yaml` `tests/unit/test_quality/test_reconcile.py` `tests/unit/test_steps/test_step_canonicals.py` `tests/unit/test_unresolved.py`

### S-0034/D-51 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-09)* **A macro declares its signature; it is never read off its body.** The first cut inferred the signature from the body's `:name` placeholders. That is the third appearance of one temptation, and it is refused for the third time — D43 refused fabricating references from matching key columns, D49 refused auto-linking canonical fields by name. The deciding argument is the ladder itself: Tier 0's `TransformSpec` declares `input_domain` **and** `output_type`, so a macro declaring neither would be the one tier whose inputs nothing checks, while §5.1's table claims Tier 1 can *parse and typecheck*. `StepManifest` gains `accepts: {column: type}` — a separate key from `inputs:`, which is relation-shaped for table steps, because one key meaning two things by kind reads fine only to whoever wrote it. The output type needs no new field: a macro has exactly one output of exactly one column (D18b). This buys three things. The **body** is checked against the declaration once, at the registry, where a disagreement is the platform's bug rather than a puzzle handed to every call site. The **call site** is checked against the declaration, so the message names what the macro expects instead of only which placeholder was unfilled. And a **chain** is typechecked *around* the link: the run before it against what it accepts, the run after it from what it produces — implemented as segments queued into the ordinary batch stage, so S-0023/D-2's one-aggregate property survives for chains containing a macro. Named cost, recorded rather than discovered: a genuinely polymorphic macro (`COALESCE(:a, :b)` over any type) must now pick a concrete type. Tier 0 carries the identical constraint through `input_domain`, so it is consistent rather than a new tax — but it is a real limit. A chain link must accept exactly one column, since a chain carries one running value; a two-column macro is refused there and pointed at the field shape.

- Paths: `src/bloomery/resolve/build.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/mapping.py` `tests/golden/schema/mapping.json` `tests/property/test_schema_agreement.py` `tests/unit/test_resolve/test_declared_zone.py` `tests/unit/test_schema.py`

### S-0035/D-1 — `ASSUMED` (Public surface and stability policy)

**Signature closure** is the root-namespace rule: any type appearing in a public signature, return, generic argument, or returned-dataclass field is itself exported from `bloomery`. **Fourteen** types are added under it (§5.1), the walk stopping at handle types (decision 9). Enforced by a unit test walking `get_type_hints`, not by review — a walk that decision 10 has to make runnable first.

- Paths: `src/bloomery/__init__.py` `src/bloomery/evidence.py` `src/bloomery/ir/nodes.py` `tests/unit/test_advisories.py` `tests/unit/test_ir/test_nodes.py` `tests/unit/test_package.py` `tests/unit/test_signature_closure.py`

### S-0035/D-2 — `ASSUMED` (Public surface and stability policy)

**Errors are the one exemption**, carried as an explicit allowlist in the closure test: the root keeps `BloomeryError`; leaves stay in `bloomery.errors`, which is a declared `__all__` and a supported import path. An exemption in code is visible; an exemption in someone's head is not.

- Paths: `tests/unit/test_signature_closure.py`

### S-0035/D-7 — `ASSUMED` (Public surface and stability policy)

**The four permissive version keys are pinned to `Literal[1]`**, matching `steps_version`. The draft proposed *adding* keys on the belief that four kinds lacked them; every kind already has one, and the key is the document-kind **discriminator** — a document without it cannot be identified at all, so "missing means 1" would break loading rather than preserve it. The real defect is that `spec_version: 99` and `mapping_version: 42` are accepted and silently read as v1, so a spec written for a future bloomery is misread rather than refused. `spec_version` keeps its irregular name: renaming is a breaking change for consistency alone.

- Paths: `src/bloomery/schema.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/entity.py` `src/bloomery/spec/exports.py` `src/bloomery/spec/exposures.py` `src/bloomery/spec/imports.py` `src/bloomery/spec/mapping.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `tests/unit/test_schema.py` `tests/unit/test_spec/test_document_versions.py` `tests/unit/test_spec/test_exports.py` `tests/unit/test_spec/test_exposures.py`

### S-0035/D-9 — `ASSUMED` (Public surface and stability policy)

**Closure stops at handle types**, named in §5.1: `ProjectIR`, `Project` and `Catalog` are received and passed back, never destructured, so the walk does not descend into them. Without this the rule is a fixpoint over the whole IR — measured at **65** additions — which would export S-0020's internals as public API under a naming rule. The cost is stated: a handle that grows a documented field stops being one, and the export list grows with it.

- Paths: `tests/unit/test_signature_closure.py`

### S-0035/D-10 — `ASSUMED` (Public surface and stability policy)

**The `TYPE_CHECKING` guard is lifted on public signatures before the closure test lands.** `typing.get_type_hints` currently raises `NameError` on 7 of the 29 exports, including `compile_project`, because `from __future__ import annotations` plus a `TYPE_CHECKING`-only import leaves the annotation naming something absent at run time. Decision 1's enforcement is unimplementable until those names are importable at run time — a prerequisite the design did not see, found by running the proposed walk rather than by reading it. Guards on internal signatures are untouched.

- Paths: `src/bloomery/evidence.py` `src/bloomery/resolve/facets.py` `src/bloomery/resolve/lineage.py` `src/bloomery/resolve/timeline.py` `src/bloomery/schema.py` `tests/unit/test_signature_closure.py`

### S-0036/D-6 — `ASSUMED` (Lowering decomposition)

**The existing static purity hook is promoted to a CI gate and widened**, not invented. A pre-commit `pygrep` already bans four spellings under `src/bloomery/`; the draft's claim that the invariants are "enforced behaviourally today" understated it. Two things are actually wrong: `just quality` runs only the gitleaks hook, so the guard is bypassed by `--no-verify` and by CI itself, and its vocabulary omits the *imports* that make I/O possible. The AST check replaces the hook rather than sitting beside it — two guards over one invariant drift — with `steps/contract.py` allowlisted as run-time rather than compile-time.

- Paths: `tests/unit/test_purity_guard.py`

### S-0037/D-1 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**The JSON Schema export ships first and is the highest-leverage item.** It is a day's work over `model_json_schema()` and serves four consumers at once — editor completion, control-plane form validation, drift-free reference docs, and constrained generation for machine-authored specs. The last is the one that changes a proposal loop's safety argument from a prompt instruction into a structural constraint.

- Paths: `src/bloomery/schema.py` `tests/unit/test_schema.py`

### S-0037/D-2 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**Every closed set appears in the schema as an `enum`**, never a free string: transforms, quality rules, `Op`, `LogicalType`, `OnFail`, `Additivity`, document versions. This is the property constrained generation depends on — a proposer choosing from an enum cannot invent a transform, so the refusal that would catch the invention never fires. Unit-tested per set.

- Paths: `src/bloomery/schema.py` `tests/golden/test_spec_schemas.py` `tests/property/test_schema_agreement.py` `tests/unit/test_schema.py`

### S-0037/D-3 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**Schema export is deterministic and golden-tested**, on the same discipline as every other bloomery output: sorted keys, stable `$defs` order, no addresses in descriptions. A nondeterministic golden is noise, and these goldens are how schema changes become reviewable.

- Paths: `src/bloomery/schema.py` `tests/golden/test_spec_schemas.py` `tests/unit/test_determinism_guard.py` `tests/unit/test_schema.py`

### S-0037/D-4 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**Six CLI commands, each a pure shell over one public function**, adding no logic of their own. Exit codes distinguish refusal (`1`) from usage error (`2`), because a refusal is a *correct* outcome and scripts must be able to tell. `--format json` returns the same structures the Python API does, so the CLI is not a second lossier surface.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/cli/render.py` `src/bloomery/cli/serialize.py` `tests/unit/test_cli.py`

### S-0037/D-5 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**`bloomery/cli/io.py` is the only module in the package permitted to touch the filesystem**, added to S-0036's purity allowlist as a named carve-out with a stated reason, and enforced one-directional by import-linter: the CLI may import the library, no library module may import the CLI. The shell reads paths; the library still only ever sees strings, so the no-I/O invariant is preserved *and made structurally obvious* rather than merely asserted.

- Paths: `src/bloomery/__init__.py` `src/bloomery/cli/io.py` `tests/unit/test_import_contracts.py`

### S-0037/D-6 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**No new runtime dependency.** `argparse` from the standard library, hand-rolled table rendering. A dependency on `rich`/`typer` would be a real cost for cosmetics in a library whose dependency discipline is one of its properties.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/cli/render.py` `tests/unit/test_cli.py`

### S-0037/D-7 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**Five refusals gain optional structured suggestion fields** (§5.4), additive. The draft cited two existing precedents; only one is real. `UnsupportedFilter.reason` is an attribute; **`UnknownMember.did_you_mean` is not** — its docstring has promised the field since S-0028 while the closest match is computed and thrown into prose. So `UnknownMember` joins the list as a fifth entry rather than serving as the model for it, and the field is what finally makes its own docstring true. Each field exposes a value bloomery **already computes and currently discards**. Absence is `()` or `None` in Python and `[]` or `null` in the CLI JSON — always present, never fabricated, and never silently dropped from a structure §5.2 promises matches the API (§5.4).

- Paths: `src/bloomery/errors.py` `tests/unit/test_error_suggestions.py` `tests/unit/test_marts/test_flatten.py`

### S-0037/D-8 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**Suggestions never become a second error contract**: they are optional, and nothing may be discoverable *only* through a suggestion. The primary contract stays `.reason` plus the message.

- Paths: `tests/unit/test_error_suggestions.py`

### S-0037/D-9 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**No execution, ever.** `explain` prints; `run` does not exist. This is what keeps the test suite infrastructure-free and the library a compiler. Config files, profiles, credentials, watch mode, daemons and scaffolding are refused for the same reason — each implies state or an opinion the library does not hold.

- Paths: `tests/unit/test_cli.py`

### S-0037/D-11 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**Suggestion payloads are typed values, not encoded strings.** `covering_marts` carries `MartCoverage(mart, metric, grain)` rather than `tuple[str, ...]`: the field promises per-metric grain, and a tuple of strings can only deliver it through a format the caller has to parse and nobody has documented. That is the failure this section exists to remove, so shipping it inside the fix would be self-defeating. Cost: two new public types (`MartCoverage`, `MeasureRef`) that S-0035's closure then reaches and root-exports.

- Paths: `src/bloomery/__init__.py` `src/bloomery/errors.py` `tests/unit/test_error_suggestions.py`

### S-0037/D-12 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**The purity carve-out is one file, not the CLI package.** Only `bloomery/cli/io.py` is allowlisted; `render.py` and the argument parser stay under the guard. A package-wide exemption would let any CLI module open a file while §5.3's tree still claimed one did — the guard and the document disagreeing, which is worse than no guard. The import direction is enforced separately, at package granularity, because it answers a different question.

- Paths: `src/bloomery/cli/io.py` `tests/unit/test_purity_guard.py`

### S-0039/D-3 — `ASSUMED` (`SpecEvidence`: spec analysis as a first-class output)

**Partial analysis is the point**: the pipeline runs to the first refusing stage and reports the prefix. "Seven metrics reachable, two blocked on `cogs`, one refusal at `mappings/crm.yaml`" is unavailable today at any price, and is the most useful sentence bloomery can produce about a spec it will not compile. This is the only new behaviour in the RFC, and the pipeline already supports it — stages are already sequential and already batch.

- Paths: `src/bloomery/evidence.py` `src/bloomery/resolve/build.py` `tests/unit/test_evidence.py` `tests/unit/test_semantic/test_ratio_rows.py`

### S-0039/D-5 — `ASSUMED` (`SpecEvidence`: spec analysis as a first-class output)

**`stage_reached` is mandatory to read**, stated first in the docstring and tested on the ambiguous case: an empty `unreachable` means "nothing unreachable" only at `COMPLETE`, and means "never computed" at `PARSE`. Without it the empty tuple is ambiguous in exactly the way that produces a wrong conclusion.

- Paths: `src/bloomery/cli/render.py` `src/bloomery/resolve/build.py` `tests/unit/test_cli.py` `tests/unit/test_resolve/test_lineage.py`

### S-0039/D-8 — `ASSUMED` (`SpecEvidence`: spec analysis as a first-class output)

**`bloomery resolve` (S-0037) is re-pointed at `evaluate()`** when this lands, gaining refusal reporting, as an amendment to that RFC rather than a new command. A spec author mid-draft wants reachability *and* refusals in one output.

- Paths: `src/bloomery/cli/__init__.py` `tests/unit/test_cli.py`

### S-0039/D-10 — `ASSUMED` (`SpecEvidence`: spec analysis as a first-class output)

**The composition is tested by equality**, not by inspection: for every fixture **that reaches the resolve stage**, `evaluate()`'s reachability equals `resolve()`'s. A parse-error fixture has no `resolve()` result to compare against — it is covered by the `stage_reached=PARSE` row instead, which asserts the analysis tuples are empty. A third entry point that drifts from the second is the failure mode this RFC could plausibly introduce.

- Paths: `tests/unit/test_evidence.py`

### S-0039/D-11 — `ASSUMED` (`SpecEvidence`: spec analysis as a first-class output)

**`UnreachableMetric` is extended, not redeclared, and the IR version moves with it.** The draft declared a new dataclass of that name in `evidence.py`; `ir/nodes.py:552` already has one, on `ProjectIR.unreachable` — the very tuple `SpecEvidence` projects. Two same-named public types differing by a field is a trap with no upside, so the IR type gains `via: tuple[str, ...] = ()` and is re-exported. The default does **not** make this free: the encoder writes each dataclass's field *count* and names, so any spec with an unreachable metric re-fingerprints and `bloomery_ir_version` goes 4 → 5. The draft's `name` → `metric` rename was measured at the identical cost; it is dropped for buying only a synonym, not for being expensive.

- Paths: `tests/unit/test_evidence.py` `tests/unit/test_resolve/test_reach.py`

### S-0040/D-1 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

Flattening an entity with `scd: type2` into a mart is **refused** at compile time, not silently emitted and not silently filtered to the current version. The join has no validity predicate and the relation has one row per version, so the emitted mart multiplies the base grain while every guardrail passes. Consequence: the only shipped way to use a historical dimension in a mart is a `type1` current-view entity built from it, until §5.3 exists.

- Paths: `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `tests/fixtures/scd2_mart_refusal/entity_model.yaml` `tests/fixtures/semantic_corpus/003-scd2-unqualified-join/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/003-scd2-unqualified-join/problem.md` `tests/golden/refusals/example-scd2-flatten.txt` `tests/golden/refusals/scd2_mart_refusal.txt` `tests/unit/test_fixtures.py` `tests/unit/test_guardrails/test_stage.py` `tests/unit/test_marts/test_flatten.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0040/D-2 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

A mart whose **`base`** is `scd: type2` is refused on the same account. There is no fan-out, but the declared `grain:` claims one row per entity while the relation holds one per version, so every measure counts revisions. Refusing both sides keeps "a mart's grain is what it says" true without exception.

- Paths: `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `tests/fixtures/scd2_as_of/marts.yaml` `tests/fixtures/scd2_mart_refusal/entity_model.yaml` `tests/fixtures/scd2_replay/marts.yaml` `tests/golden/refusals/scd2_mart_refusal.txt` `tests/unit/test_fixtures.py` `tests/unit/test_guardrails/test_stage.py` `tests/unit/test_marts/test_flatten.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0040/D-4 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

`convert` raises `UnsupportedByTarget` at **emit**, on all three dialects. It stays a registered transform with an unchanged typecheck, so the spec surface does not move and a future dialect clears the refusal by declaring a `Feature` — the mechanism S-0025 already provides.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/evidence.py` `src/bloomery/resolve/build.py` `src/bloomery/transforms/_builtins.py` `tests/fixtures/currency_convert_refusal/entity_model.yaml` `tests/support/type_conformance.py` `tests/unit/test_emit/test_currency_convert.py` `tests/unit/test_evidence.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-3 — `LOCKED` (Deterministic union merge)

Mappings are unioned in **lexicographic order of source name**, so the emitted artifact is byte-identical across processes. Row order is explicitly **not** claimed — `UNION ALL` is a bag, and nothing downstream may depend on source order.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/ir/nodes.py` `tests/unit/test_determinism_guard.py` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_resolve/test_build.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-5 — `LOCKED` (Deterministic union merge)

A key appearing in more than one source is refused by a generated **blocking** audit (`on_fail: fail`), not configurable to `flag` or `quarantine`. Overlap is either duplication or a shared key space by accident, and both are refusals. The message names the identity-resolution step as the escape hatch. Consequence: bloomery's union is for disjoint key sets, permanently — matching stays a step, and S-0038 is not reopened.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `tests/e2e/test_dbt_parse.py` `tests/e2e/test_sqlmesh_replan.py` `tests/execution/test_merged_cleaning.py` `tests/golden/test_sqlmesh_duckdb.py` `tests/unit/test_examples.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-26 — `ASSUMED` (Deterministic union merge)

**Answers D25 (`OPEN`) — option (a), and D25's blast-radius figure was wrong by an order of magnitude.** The lowered expression moves to a new column-grained `SourceColumnIR` on `SourceIR`; `ColumnIR` keeps the schema (§5.7). D25 said "37 `.columns` read sites" and estimated the cost from that; measured, **exactly 8 sites read a `ColumnIR` lowering field, in 3 files** — `plan/diff.py` (`renamed_from` ×4, `recipe_id`, `expr.sql`) and `emit/lower/silver.py` (`expr.ast()` ×2). Four of those eight are `renamed_from`, which D25 mis-assigned to the lowering half and which is declared on the EntityModel `Field`, so it does not move at all. The 37 was a count of `.columns` readers, and `.columns` readers are overwhelmingly *schema* readers — they survive untouched, which is the whole point of the split. **Real cost: two constructors where there was one, and four call sites.** The golden churn stands regardless — the IR shape moves and D17 bumps the version.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/operands.py` `src/bloomery/guardrails/stage.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/resolve/build.py` `src/bloomery/resolve/facets.py` `src/bloomery/resolve/steps.py` `src/bloomery/resolve/timeline.py` `tests/bench/test_hydration.py` `tests/support/ir_factory.py` `tests/support/plan_ir.py` `tests/unit/test_emit/test_cube.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_facets.py` `tests/unit/test_unresolved.py`

### S-0041/D-36 — `ASSUMED` (Deterministic union merge)

**Answers D28 — `direct:` is allowed on a merged entity when *every* mapping records one for the column, and refused when they disagree.** D28 refused the combination outright and handed P2 a choice between "one shadow projection per source with a null-safe audit" and "a coverage rule in D4's shape". Measured with the refusal disabled against two mappings that *agree*, the null-safe audit is answering the wrong question: the shadow column is duplicated on the entity **and on every branch**, the reconcile audit is emitted twice, and each branch carries the other's extraction — `shop__items` projecting `$.unit_price` off a relation that does not have it. That is not a NULL-shadow problem, it is `Derivation` being built per mapping while `_shadow` returns one projection: the same per-mapping-fact-on-a-shared-node shape D26 split for `expr` and D32 for the rule inputs. So the coverage rule is the answer and the null-safe audit is unnecessary under it — under agreement no branch's shadow is NULL for want of a path, and the reconcile check keeps the meaning it has on one source: the recipe-derived value against the direct value *that row's own mapping* extracted, which is D32's principle applied to a second reader. Consequence: `Derivation` carries its source relation, `path_conflict_amendments` fans out per source like every other lowering, and disagreement is refused by D33's pattern rather than tolerated. D28's row stands unamended — its refusal is correct until this one is executed, and what it predicted is the thing this has to be read against. *Added by execution 2026-09-03 — see logs/T-0012.md (F-8), which carries the probe output.*

- Paths: `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/build.py` `tests/execution/test_path_conflict.py` `tests/fixtures/path_conflict_merged/entity_model.yaml` `tests/fixtures/path_conflict_merged/mapping_legacy.yaml` `tests/golden/test_sqlmesh_duckdb.py` `tests/unit/test_fixtures.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_resolution.py`

### S-0042/D-8 — `LOCKED` (v0.1.0 release readiness)

The changelog section is cut **before** the tag. `hatch-vcs` derives the version from the tag, so a section cut afterwards describes a release that already shipped.

- Paths: `tests/unit/test_changelog_release.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0047/D-2 — `LOCKED` (The unresolved-work report)

**`options` is enumerated in catalog order and never sorted, ranked or scored.** Enumerating what the catalog declares is a projection; ordering is where a preference would hide. `Recipe`'s docstring makes catalog order *authored* ("ordered by reliability"), so re-sorting — alphabetically included — destroys information rather than normalizing it. Consequence: this is a deliberate exception to the sort-every-collection habit, and it needs the §6 test with a non-alphabetical catalog or the exception is untested.

- Paths: `src/bloomery/cli/render.py` `src/bloomery/evidence.py` `tests/unit/test_unresolved.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0047/D-3 — `LOCKED` (The unresolved-work report)

**The two gaps are distinguished, and that is the RFC's reason to exist.** `UNLINKED` and `UNMAPPED` are reported identically today and need different edits (§3). Consequence: the report reads the entity model, not only the DAG, which is why it lives in `evidence.py` and not in `resolve/`.

- Paths: `src/bloomery/evidence.py` `tests/unit/test_unresolved.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0047/D-5 — `ASSUMED` (The unresolved-work report)

**The report is a `COMPLETE`-stage product; a refusal empties it.** Recipe validation is in the pipeline's first stage, so a malformed choice costs the round's worklist (§3, cases (d)/(e)). Accepted because the refusal messages already name the fix precisely and the loop still terminates — fix the error, recompile, read the report. Graded `ASSUMED` rather than `LOCKED` because it is a claim about how an agent behaves, and whoever builds this may find the loop needs the partial report; the alternative is computing the options half before validation, which is possible since it needs no DAG.

- Paths: `src/bloomery/evidence.py` `tests/unit/test_unresolved.py`

### S-0047/D-7 — `OPEN` (The unresolved-work report)

**Whether the human CLI table prints open decisions.** JSON gets them by construction. The table is a summary (S-0037/D-4), and this is either the most useful line `bloomery resolve` could print or the one that turns a summary into a dump. Whoever builds this decides and logs it.

- Paths: `src/bloomery/cli/render.py` `tests/unit/test_cli.py`

### S-0047/D-9 — `LOCKED` (The unresolved-work report)

**Every entry names one edit; an entry that cannot is omitted.** The promise is not "here is a gap" but "here is the edit that would close it", and an entry a caller cannot act on is a worklist item that never clears. Consequence, and the only shape affected today: a canonical whose entity is built by more than one mapping is **not reported**, because its columns are per mapping (S-0041/D-26) and an entry keyed on `canonical` cannot say which document to edit. Nothing is hidden — the blocked metric is still `unreachable` — and the omission lifts when the report can carry a mapping identity, which is S-0041/phasing (P-2)'s question rather than this one's.

- Paths: `src/bloomery/evidence.py` `tests/unit/test_unresolved.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0056/D-2 — `LOCKED` (Production-style semantic bug corpus)

**Every case is hand-checkable — 3–20 rows, deterministic, order-independent.** A corpus case a reviewer cannot verify by eye is a test asserting whatever the implementation did on the day it was written, which is the failure mode this corpus is meant to catch in *other* people's pipelines.

- Paths: `tests/fixtures/semantic_corpus/001-order-shipping-fanout/data/rows.sql` `tests/fixtures/semantic_corpus/003-scd2-unqualified-join/problem.md` `tests/fixtures/semantic_corpus/006-two-grains-one-request/data/rows.sql` `tests/unit/test_semantic_corpus_guard.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0056/D-3 — `LOCKED` (Production-style semantic bug corpus)

**Each case pins a machine-readable outcome against a stable rule ID, not prose.** Prose is golden-tested only where diagnostics are already a public contract. This is what lets S-0005's rules cite cases and S-0006's matrix cite both without either restating the other.

- Paths: `tests/execution/test_semantic_corpus.py` `tests/support/semantic_corpus.py` `tests/unit/test_semantic_corpus_guard.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0057/D-4 — `LOCKED` (`bloomery check` and imported semantic provenance)

**A conflict between an imported and a declared fact refuses, naming both provenances.** Neither side wins by default — "declared is more true" is the rule that looks obvious and quietly overwrites a mechanically verified fact with an authored guess. A contradiction is a finding about the model, not a merge to resolve.

- Paths: `tests/unit/test_cli.py` `tests/unit/test_imports.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0057/D-5 — `ASSUMED` (`bloomery check` and imported semantic provenance)

**Counts report surfaces actually checked, never totals that imply unproven coverage.** A green `check` must not read as "every future query is safe", which is precisely what a large round number invites. Not `LOCKED` because the right *set* of categories is a presentation question execution may adjust.

- Paths: `src/bloomery/evidence.py` `tests/unit/test_cli.py` `tests/unit/test_evidence.py`

### S-0057/D-6 — `ASSUMED` (`bloomery check` and imported semantic provenance)

**Machine-readable output is mandatory and its refusal codes align with S-0005's rule IDs.** One vocabulary for the CLI, the proof IR and the corpus, or the three drift and CI asserts on the weakest of them.

- Paths: `tests/unit/test_cli.py`

### S-0062/D-1 — `LOCKED` (Ownership, classification and grants)

The three annotations change no SELECT. They reach metadata slots only, and an existing golden's SQL is byte-identical with them absent — asserted, not assumed.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/spec/entity.py` `src/bloomery/spec/quality.py` `tests/unit/test_tenant_guard.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0062/D-3 — `LOCKED` (Ownership, classification and grants)

`classification` is a **closed** vocabulary. An open string is a tag that cannot be routed, and the routing — the `redact` reconciliation and Cube's `public: false` — is the whole reason this is not a `meta` passthrough.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/spec/entity.py` `src/bloomery/spec/quality.py` `tests/unit/test_tenant_guard.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0062/D-4 — `LOCKED` (Ownership, classification and grants)

**Superseded by rows 9, 10 and 11.** `pii`/`secret` on a mapped field whose path is not redacted is a refusal **when the entity quarantines**, and silent otherwise. Unsatisfiable as written: a mapped field's path cannot be redacted — `_check_redaction` refuses that already — so both branches close and the classification has no legal spelling, which is the gap §2 opened this RFC to fill (see `logs/T-0050.md`, and `logs/T-0051.md` for the replacement).

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/spec/entity.py` `src/bloomery/spec/quality.py` `tests/unit/test_tenant_guard.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0062/D-9 — `LOCKED` (Ownership, classification and grants)

**Classification composes with `grants`, not with `redact`.** §2 paired it with redaction because "`redact:` is the nearest thing" — true when this was drafted, false once phase 4 shipped the one annotation with a mechanism behind it. `redact:` governs what a reject row keeps; `classification:` governs a column that is published; the two stay orthogonal (see `logs/T-0051.md`).

- Paths: `src/bloomery/guardrails/stage.py` `tests/unit/test_classification_guard.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0062/D-11 — `LOCKED` (Ownership, classification and grants)

A `pii`/`secret` column reaching a relation that **admits a role its source entity does not** is a refusal — a set difference, not a superset test, so disjoint grant sets are refused too: a role that can read the mart and not the entity is the leak whether or not the mart also admits the entity's roles; an **undeclared** audience on either side is an advisory, not a refusal. Refusing the unknown case would refuse every project managing gold grants outside bloomery, and the compiler can only call a contradiction where it holds both statements.

- Paths: `pages/docs/how-to/annotate-a-spec.md` `src/bloomery/errors.py` `src/bloomery/evidence.py` `src/bloomery/guardrails/classification.py` `src/bloomery/guardrails/stage.py` `tests/unit/test_classification_guard.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0066/D-7 — `OPEN` (Declared input currency for conversion)

**Whether `currency_in:` extends to `RecipeFieldMapping` and `MacroFieldMapping`.** This row assumed a recipe's chain can hold a conversion, and it cannot: a `Recipe` is `{id, requires, expr}` — a SQL expression over aliases, with no transform chain — and a macro's body is opaque SQL. Neither can carry a `convert` step, so neither can hold a conversion whose input would need declaring, and neither reaches the code that would ask. Answered "no" for both, and "yes" for `KeyField`, which this row did not think to ask about (see `logs/T-0025.md` (`logs/T-0025.md`), D158).

- Paths: `src/bloomery/evidence.py` `tests/unit/test_evidence.py`

### S-0074/D-14 — `ASSUMED` (Spec timeline)

**Row 13's shape promise holds and its value promise does not; supersedes 13 on that half alone.** `facets` is present and is a tuple in every phase, so the JSON a consumer reads never changes shape — but it is never *empty*, because S-0069 row 10 makes an empty delta mean "not a change" and the row is not emitted. Row 13's first reading — a pure rename reported as a change carrying nothing — is the wrong answer to S-0069/tests (§6.) The absence half of row 13 is unchanged. See `logs/T-0045.md`.

- Paths: `tests/unit/test_cli.py`

<!-- /torve:managed -->
