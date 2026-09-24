<!-- torve:managed tests/support — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/support/`

### S-0010/D-3 — `OPEN` (Generating from the spec schema)

Whether the generator is `hypothesis-jsonschema`'s `from_schema()` or a hand-written strategy over the subset of JSON Schema bloomery emits is decided by execution, with the tiebreak being the fraction of generated documents that reach the resolver — never the dependency's release date

- Paths: `tests/property/**` `tests/support/**` `pyproject.toml`
- Consequence: Adopting the dependency adds a `dev`-group entry to `pyproject.toml` carrying the same explanatory comment style `jsonschema` already has; declining it puts a maintained strategy in this repository instead. Either way the measured fraction is logged, so the choice is re-decidable on evidence rather than re-argued.

### S-0010/D-6 — `ASSUMED` (Generating from the spec schema)

Cross-document consistency is produced by generating a pool of names the documents then draw from, rather than generating each document independently and hoping its references resolve

- Paths: `tests/property/**` `tests/support/**`
- Consequence: The generator is stateful across a project's documents, so the reach fraction for a set is not the fraction for a single kind and the two are reported separately; a pool that constrains the generated space more than it buys is a departure to log against this row, not a bug

### S-0012/D-1 — `LOCKED` (Validating a dialect port against an engine we cannot run)

An emulator, a surrogate engine or a compatible-wire shim is evidence, never the oracle: the real engine's own compiler is the dialect oracle, and no rung below the authoritative ones may be quoted as engine conformance

- Paths: `tests/engines/**` `tests/support/**`
- Consequence: A cloud port's acceptance is the authoritative rung's, so a port whose only green lanes are local has not been validated and a review says so; the local lanes stay worth running as the fast signal, and stay unable to close the port
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0012/D-3 — `LOCKED` (Validating a dialect port against an engine we cannot run)

The authoritative compile rung exists for every cloud port, because every one of the four engines has one — `EXPLAIN USING JSON`, a dry run, `EXPLAIN`, `EXPLAIN EXTENDED` and `DESCRIBE QUERY` — and a port without it has no authoritative layer at all

- Paths: `tests/engines/**` `tests/support/**`
- Consequence: Each of the four ports owes a compile lane over the shared corpus before it can be called validated, and the lane costs a parse rather than a scan; the absence of a container stops being a blocker for any of them
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0012/D-4 — `LOCKED` (Validating a dialect port against an engine we cannot run)

No engine driver, cloud SDK or Spark session enters `src/bloomery`; live harnesses live in `tests/support/` and their drivers are test-only dependency groups, never installed for `uv add bloomery`

- Paths: `src/bloomery/**` `tests/support/**` `pyproject.toml`
- Consequence: A cloud port adds a port module and a test harness and nothing else to the install path, so the package stays a pure compiler and its dependency closure stays free of a JVM and four vendor SDKs
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0013/D-3 — `ASSUMED` (Snowflake dialect port) — implementation: none

The OSS emulator `ghcr.io/sivchari/snowflake-emulator` is the default local lane and LocalStack for Snowflake is optional

- Paths: `tests/engines/**` `tests/support/**`
- Consequence: The default lane needs no token and no licence, which is the only thing that makes it a candidate for a per-pull-request slot at all, since a lane requiring a secret cannot run on a fork pull request; departing means the OSS emulator's documented gaps — no distributed execution, no meaningful access control, no warehouse management, no guaranteed transaction isolation — reaching a fixture that matters, in which case LocalStack becomes the default and its token constraint follows it

### S-0013/D-5 — `OPEN` (Snowflake dialect port) — implementation: none

Whether the LocalStack lane is maintained at all is decided from the defects each emulator found that the other missed, after one port's worth of work, and not before

- Paths: `tests/engines/**` `tests/support/**`
- Consequence: Two emulators is two maintenance surfaces, two pinned versions and two sets of documented gaps to know; whoever runs both counts what each caught and records the count, and a decision taken before that evidence exists is the thing this row refuses

### S-0013/D-7 — `ASSUMED` (Snowflake dialect port) — implementation: none

No Snowflake credential — the LocalStack auth token included — enters the repository or is reachable from an untrusted pull request, and a lane that finds none skips with a stated reason rather than failing

- Paths: `tests/support/**` `.github/workflows/**`
- Consequence: The token is read from the environment and `.env` is already gitignored, so the harness adds nothing there; the live lanes run on `main`, on releases, on a schedule and on manual dispatch behind a GitHub Environment, and a red lane on a missing variable would train people to ignore the lane

### S-0014/D-5 — `ASSUMED` (BigQuery dialect port) — implementation: none

A tiny dedicated BigQuery dataset exists before the dry-run lane does, so that name and type resolution actually run against something

- Paths: `tests/support/bigquery.py`
- Consequence: A dry run over a query that references nothing validates syntax and little else, which would make the lane look authoritative in a report while proving roughly what rung 3 already proves for free

### S-0015/D-3 — `LOCKED` (Redshift dialect port) — implementation: none

Fixtures are split into `postgres-compatible` and `redshift-native`, and the native class never runs on the surrogate

- Paths: `tests/support/redshift.py`
- Consequence: Without the split, the surrogate lane's coverage number silently includes cases it cannot speak to — which is how a partial lane comes to be read as a full one
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0015/D-5 — `ASSUMED` (Redshift dialect port) — implementation: none

LocalStack is optional while bloomery remains a pure compiler

- Paths: `tests/support/redshift.py` `tests/engines/test_redshift_surrogate.py`
- Consequence: It emulates control-plane and Data API surfaces bloomery does not touch, so no lane is blocked on it

### S-0016/D-4 — `LOCKED` (Databricks SQL dialect port) — implementation: none

`DESCRIBE QUERY` is part of the authoritative lane, not an optional extra beside `EXPLAIN EXTENDED`

- Paths: `tests/support/databricks.py` `tests/engines/test_databricks_live.py`
- Consequence: The declared-versus-produced type contract is checked against the real analyzer without executing anything or scanning any data; without it, type conformance rests on the surrogate, which is precisely where Spark and Databricks SQL are documented to differ
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0016/D-7 — `ASSUMED` (Databricks SQL dialect port) — implementation: none

The Spark surrogate lane is kept only if it catches defects the offline rungs miss; it is measured over one port's work and dropped on that evidence

- Paths: `tests/support/spark.py` `tests/engines/test_databricks_surrogate.py`
- Consequence: The lane's cost is justified by what it returns rather than by the plausibility of having it, and dropping it is a recorded outcome rather than neglect

### S-0016/D-10 — `ASSUMED` (Databricks SQL dialect port) — implementation: none

No cloud credential is reachable from an untrusted pull request and the default test tiers never require one: the live lane runs on `main`, on a schedule and on manual dispatch behind the `databricks-free` GitHub Environment rather than raw repository secrets, against the dedicated `workspace.bloomery_conformance` catalog and schema, with compile-only and execution jobs kept separate, and a live test skips with a stated reason when the variables are absent rather than failing

- Paths: `.github/workflows/**` `.env.example` `tests/support/databricks.py`
- Consequence: A public pull request cannot run arbitrary SQL under a maintainer's cloud identity, the cheap lane cannot accidentally scan or bill, and a contributor with no credentials sees a stated skip rather than a red suite

### S-0020/D-2 — `ASSUMED` (Intermediate representation and determinism contract)

SQL is stored in the IR as canonical dialect-neutral SQLGlot text (`SqlExpr`), re-parsed at emit. Consequence: SQLGlot version changes can change fingerprints; the exact pin (D4 §5.5) makes that a deliberate event.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/emit/lower/marts.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `src/bloomery/transforms/_builtins.py` `tests/support/type_conformance.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_postgres.py` `tests/unit/test_transforms/test_builtins.py` `tests/unit/test_transforms/test_type_conformance_corpus.py`

### S-0020/D-5 — `ASSUMED` (Intermediate representation and determinism contract)

Floats are banned in IR and emission; `Decimal`/int only.

- Paths: `src/bloomery/cli/serialize.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/steps.py` `src/bloomery/ir/fingerprint.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/request.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/common.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `src/bloomery/steps/manifest.py` `src/bloomery/steps/splice.py` `src/bloomery/transforms/_builtins.py` `src/bloomery/typing/types.py` `tests/execution/test_as_of_join.py` `tests/execution/test_currency_convert.py` `tests/execution/test_fanout_trap.py` `tests/execution/test_marts.py` `tests/execution/test_period_over_period.py` `tests/execution/test_rollup.py` `tests/fixtures/semantic_corpus/002-average-of-averages/naive.sql` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/golden/schema/marts.json` `tests/support/planning.py` `tests/support/semantic_corpus.py` `tests/unit/test_cli.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_planner/test_request.py` `tests/unit/test_quality/test_edges.py` `tests/unit/test_spec/test_metrics.py` `tests/unit/test_spec/test_quality.py` `tests/unit/test_steps/test_lowering.py` `tests/unit/test_steps/test_manifest_and_registry.py` `tests/unit/test_typing/test_types.py`

### S-0025/D-2 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Emitters produce file-shaped text artifacts as data (settles open question #1). No filesystem writes, no live-context registration in core — callers build that on top.

- Paths: `src/bloomery/emit/base.py` `src/bloomery/emit/steps.py` `tests/golden/test_sqlmesh_duckdb.py` `tests/support/execution.py`

### S-0025/D-20 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

*(2026-08-11)* **The dbt target emits a real DAG, and keeps the naming policy owning namespaces. S-0026/D-22 is closed — with both of its candidates, not one.** D22 found `dbt build` could not pass: models named their inputs literally (`FROM silver.order_item`), so dbt had no edges to order them by *and* materialized each into the profile's target schema while the `FROM` clause said `silver`. It offered two fixes with an "or" between them, and the "or" was the mistake — **neither is sufficient alone, and each repairs the other's cost.** `+schema` config alone places the relations and leaves ordering absent, so a gold model still races its silver input. `ref()`/`source()` alone orders the DAG but resolves names through dbt's schema config, which is the objection D22 raised: the naming port stops owning the namespace. Together: `ref()` for every relation bloomery emits and `source()` for bronze, `+schema: <ns>` per model directory, and a `generate_schema_name` override returning the configured schema **verbatim** — because dbt's default returns `<target.schema>_<custom>`, which would put models in `main_silver` while `sources.yml` (which never passes through that macro) still said `bronze`, honouring the policy in half the project. **How it is emitted.** Shared lowering is untouched: both targets build inputs as `exp.table_(relation, db=namespace)`, and the dbt emitter rewrites *table nodes only*, mapping `(namespace, relation)` to a reference. A namespace-less table is never rewritten, which is what keeps a CTE reference from being mistaken for a model; a table the map does not know is left literal rather than guessed at, because inventing a `ref()` for a relation bloomery did not write would name a model dbt cannot find. An SCD2 entity resolves to its **snapshot**, the only thing this target builds for it. **The cost, stated.** D5's port-abstraction proof compared the two targets' SELECTs byte for byte and can no longer: the `FROM` clauses differ by construction. It is restated, not weakened — resolve the references, drop namespaces, and the SQL is identical on every projection, join, cast and dialect quirk, so the entire difference between the targets is one documented substitution. The namespaces the comparison erases are asserted separately, against the `+schema` config and the override.

- Paths: `src/bloomery/emit/dbt/__init__.py` `tests/e2e/test_dbt_parse.py` `tests/property/test_compile_properties.py` `tests/support/compiling.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_quality_mart.py`

### S-0026/D-21 — `ASSUMED` (Testing strategy and fixture corpus)

*(2026-08-10)* **The Trino engine tier is built, on the memory connector, and `spark` is struck from §5.2.** Trino was the engine bloomery made the most claims about and executed the least: three decisions — D83's reject-table constructions, D86's `normalize`/`charset`, D89's mart-assertion body shapes — were each verified against `trinodb/trino:483` **by hand**, through `docker exec`, because the repository carried no Trino client. A hand-verification is a claim with a date on it, not a test, and all three are now a permanent tier (`trino` + `testcontainers[trino]` in the `engines` group). The strongest assertion is the one D75 said was impossible: the `<entity>__reject` model *materializes*, and its `reject_id` is compared against the canon-bytes digest computed here in Python rather than against Trino agreeing with itself — cross-engine *agreement* being the property that identity actually needs, since a replay run on one engine must find the row another quarantined. Sabotage-verified: dropping the `LOWER` from Trino's `TO_HEX` makes the digest disagree in case alone, which the tier catches and which no rendering test could. **The connector is `memory`, diverging from §5.2's `trino+iceberg+minio (compose)` sketch**: bloomery emits SELECTs and models and never storage-format DDL, so an object store and a table format would be three more moving parts serving no assertion in this tier — recorded rather than silently simplified. **`spark` is struck from the same row.** S-0025 ships DuckDB, Postgres and Trino; there is no Spark dialect, so a Spark cell had nothing to exercise and the word promised a matrix column that could never have contained a test. It returns if and when a Spark dialect does.

- Paths: `tests/engines/test_trino.py` `tests/engines/test_trino_execution.py` `tests/support/cube.py` `tests/unit/test_examples.py`

### S-0026/D-24 — `ASSUMED` (Testing strategy and fixture corpus)

*(2026-08-10)* **The Cube container and the three-way equivalence tier are built; `QueryPlan.columns` does not name the columns the SQL returns.** §5.2's last tier-6 cell and §5.8's tier-7 both need Cube alive, so one harness pairs it with the Postgres holding the mart it describes — on one network, with the table created from `MartIR` through the Postgres dialect port rather than a hand-written column list, since a third statement of the schema would be free to drift from the two that matter. **Cube loads what bloomery emits**, and the load-bearing assertion is the `meta:` block: S-0025/ports says the emitted `additivity`/`grain`/`semi_additive` is what a consumer audits Cube's behaviour against, which is only true if it survives to the API — no golden can show that, and dropping it from the emitter fails the test that names it. The tier does not stop at `/meta`: it issues a query, because parsing a model and running its measure expression are different claims. **Equivalence** points both engines at one relation by construction — Cube's `sql_table` and the planner's SQL name the same `gold.mart_<name>` under the naming policy — so a difference can only come from the query rather than from two seeding routines kept in step. The corpus is smaller than §5.8's "~40 requests", visibly and deliberately: the *classes* buy the coverage (an additive measure at three grains, an ungrouped request, a ratio recomputed per group, a multi-metric request), each costs a Cube round trip in a nightly lane, and growing it is adding YAML entries. The reference SQL runs on **every** request that declares one rather than only after a disagreement — §5.8 calls it the tiebreaker, and a tiebreaker nobody has ever checked cannot break a tie. `known_divergences.yaml` ships **empty**, with its required shape asserted, because §5.8 holds that a silent divergence is a bug in one of the implementations and a pre-populated file would let the first real one hide among plausible neighbours. The ratio fixture seeds groups of **unequal size** on purpose: a ratio averaged from stored per-row values agrees with a ratio of summed components on equal-sized groups and only on those, so equal groups would let the wrong arithmetic pass. Sabotage-verified — a wrong Cube measure expression fails ten of the fifteen. **The finding.** `QueryPlan.columns` is S-0028's "self-describing envelope", but its dimension descriptors carry the *requested* name (`ordered_month`) while the SQL MetricFlow generates aliases them its own way (`order_item__ordered_day__month`). Positional binding works and is what every consumer in this repo does; binding by name silently finds nothing. Two ways to close it, **neither built** — wrap the generated SQL in an outer SELECT aliasing to the requested names (S-0030's call, since MetricFlow owns the aliasing), or state in S-0028 that the envelope is positional and `name` is the request's word rather than the frame's. Recorded because it was written down nowhere. **One harness trap, recorded because it cost a wrong diagnosis:** Postgres logs "database system is ready to accept connections" *twice* — once on the unix socket while `initdb` runs its scripts, then again for real — so a container waiting on the first occurrence connects during the init shutdown and fails with "server closed the connection unexpectedly". It is a race, so it failed intermittently and read as container-memory pressure; the fix is the `PostgresContainer` class the other engine tiers already use, not fewer containers.

- Paths: `src/bloomery/planner/result.py` `tests/equivalence/test_three_way.py` `tests/support/equivalence.py` `tests/unit/test_planner/test_names.py`

### S-0027/D-2 — `ASSUMED` (Marts and role-playing dimensions)

Measure grain must strictly equal mart grain; coarser or finer is `GrainViolation`. Resolves D2's prose/example contradiction to the strict reading; relaxation is a future additive change.

- Paths: `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/semantic/proof.py` `src/bloomery/semantic/rollup.py` `tests/fixtures/fanout_trap/marts.yaml` `tests/fixtures/fanout_trap/metrics.yaml` `tests/fixtures/semantic_corpus/001-order-shipping-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/001-order-shipping-fanout/problem.md` `tests/fixtures/semantic_corpus/010-many-to-many-bridge/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/010-many-to-many-bridge/problem.md` `tests/golden/refusals/example-wrong-grain.txt` `tests/golden/refusals/fanout_trap.txt` `tests/support/semantic_corpus.py` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_semantic_corpus_guard.py`

### S-0033/D-18 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Disposition precedence for a row failing multiple rules — severity order `fail > quarantine > flag`: any failing `fail` rule stops the run (blocking audit); else any failing `quarantine` rule diverts the row, with **all** failed rule names recorded in the reject's `failed_rules` (flag-level failures included); else flags accumulate in `_quality_flags`. Deterministic for every combination — no compile-time rejection of rule/disposition combinations needed.

- Paths: `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/quality/catalogue.py` `src/bloomery/quality/predicates.py` `tests/e2e/test_sqlmesh_replan.py` `tests/execution/test_quality_precedence.py` `tests/fixtures/quality_precedence/entity_model.yaml` `tests/support/precedence.py` `tests/unit/test_quality/test_predicates.py`

### S-0033/D-20 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Dedupe is a total order: after `field` DESC and the `tie_break` columns, the final sort key is the stable source-row identity `_source_row_id` — the winner is unique by construction *given the metadata contract* (D21): `_source_row_id` is declared **NOT NULL and unique per source row**, an ingestion-layer obligation enforced at run time by a generated blocking audit on the metadata columns (a data property, not compile-checkable). Null ordering pinned: `NULLS LAST` on **every** sort key including `_source_row_id` (defense in depth — DESC defaults to NULLS FIRST on several engines, so an illegally-null identity must still lose, never win).

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/quality/dedupe.py` `tests/execution/test_dedupe_and_audits.py` `tests/execution/test_quality_precedence.py` `tests/fixtures/quality_precedence/entity_model.yaml` `tests/support/precedence.py` `tests/unit/test_quality/test_dedupe_and_reject.py`

### S-0033/D-21 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Ingestion metadata contract: entities using `quarantine` or `dedupe` require bronze `_load_id`, `_ingested_at`, `_source_row_id` (a stable per-source-row identity supplied by the ingestion layer, **NOT NULL and unique per source row** — data properties no compiler can check, so the lowering emits a generated **blocking audit** on the metadata columns: a null or duplicated `_source_row_id` stops the run); column absence is the new compile error `IngestionMetadataMissing` (`GuardrailError` leaf, `errors.py` per S-0019/D-3). `reject_id` = sha256 over the length-prefixed utf-8 **pair** (`source_relation`, `_source_row_id`) — canonical serialization per the S-0020 canon-bytes doctrine. This supersedes the triple this row first carried (this round's own earlier decision): `_load_id` is removed from the identity and becomes an attribute (the latest observing load) — re-deliveries of the same source row across loads must land on the **same** reject row (that is what `first_seen`/`last_seen` track); a per-load identity would mint a new row per retry and violate replay idempotence. A re-delivery updates `last_seen`/`_load_id`/`failed_rules` on the existing row.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/quality.py` `src/bloomery/quality/catalogue.py` `src/bloomery/quality/dedupe.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/transforms/_builtins.py` `tests/e2e/test_dbt_parse.py` `tests/e2e/test_sqlmesh_project.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_dedupe_and_audits.py` `tests/execution/test_merged_cleaning.py` `tests/execution/test_zoneless_utc.py` `tests/fixtures/dirty/README.md` `tests/fixtures/semi_additive_inventory/mapping.yaml` `tests/support/execution.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_trino.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_entity.py`

### S-0033/D-22 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Replay merge semantics: replay applies the **same dedupe ordering** as the pipeline — a replayed candidate merges by entity key and wins/loses against an incumbent by the dedupe total order (recency, tie-breaks, `_source_row_id`); multiple rejects resolving to one key are ordered the same way. The per-entity replay batch is one atomic MERGE (transactionality is the executing engine's; bloomery emits the artifact); idempotence follows from the total order — re-running replay re-derives the same winners — and is defined over **semantic state** (winners merged, `resolved_at` transitions), observability columns excluded: `last_seen` updates only when a row is actually re-evaluated.

- Paths: `src/bloomery/emit/lower/silver.py` `tests/execution/test_quality_precedence.py` `tests/execution/test_replay_to_bronze.py` `tests/fixtures/quality_precedence/entity_model.yaml` `tests/support/precedence.py`

### S-0033/D-84 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **Postgres hosts quality-carrying entities: `TRY_CAST` is a guard around Postgres' own input parser, not a regex. D30 is closed.** D30 named the escape hatch as "a per-type `CASE`-based fallback whose semantics are proven equal to `TRY_CAST`'s on the corpus", and a per-type regex is what that sounded like. It is the wrong build: a regex is an *approximation* of the parser, and it would have to be kept in step with it forever. `pg_input_is_valid` (Postgres 16+) is the parser, so `CASE WHEN pg_input_is_valid(x, 't') THEN CAST(x AS t) END` accepts exactly what `CAST` accepts and yields NULL exactly where `CAST` raises — equal **by construction** rather than by a proof that decays. Measured anyway, because a claim that is checked is a commitment: over a 57-value adversarial corpus × 5 types, 284 of 285 cases identical to plain `CAST` modulo NULL-on-error. The rewrite lives in the dialect's `render`, so the IR keeps the dialect-neutral `TryCast` node it already had. **The 285th case is the finding.** Postgres accepts `now`/`today`/`tomorrow`/`yesterday` as datetime input and resolves them to the *transaction timestamp*, so a bronze cell spelling `now` coerces to a different value on every run — a backfill disagreeing with the run it replaces, which S-0020 exists to prevent, arriving green and unrestatable. The temporal guard excludes them, which is the one place it is deliberately **stricter** than `CAST`: such a cell becomes a coercion failure the `coercible` rule disposes of, a quarantined row rather than a silently unstable one. It also moves Postgres *toward* DuckDB, which rejects `now` outright. Verified by execution, not rendering — rendering was never the hard part, and D30's whole point was that a plain `CAST` renders beautifully and aborts the run: the quality-carrying fixture materializes on postgres 16 with the clean row kept and one specimen per failure mode quarantined, `now` among them, and the tier is now a permanent engine test. Two harness traps recorded because both nearly produced a wrong answer: a *constant* subquery is folded at plan time, so the `CASE`'s other branch evaluates and raises — the guard is only safe over a column, which is what a bronze relation always is; and psycopg reports its own inability to represent `infinity` as an error indistinguishable from a SQL one, which made three engine-accepted values look rejected. **Not closed:** cast *semantics* still differ across engines — DuckDB coerces `'1.5'` to an int and Postgres does not — so the same spec quarantines different rows on different engines. That is inherent to running on different engines, predates this change, and is recorded here rather than implied to be fixed.

- Paths: `src/bloomery/dialects/postgres.py` `tests/engines/test_type_conformance.py` `tests/support/type_conformance.py` `tests/unit/test_docs_floor.py`

### S-0034/D-5 — `ASSUMED` (The step registry: referenced implementations)

Determinism tiers: `pure` (freely backfillable) | `seeded` (seed required in the spec, recorded) | `nondeterministic` (**compile error**). Restatement is the organizing capability of the architecture; refusing nondeterminism is the load-bearing constraint, not conservatism.

- Paths: `src/bloomery/errors.py` `src/bloomery/ir/nodes.py` `tests/support/identity.py` `tests/unit/test_steps/test_identity_demo.py`

### S-0040/D-4 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

`convert` raises `UnsupportedByTarget` at **emit**, on all three dialects. It stays a registered transform with an unchanged typecheck, so the spec surface does not move and a future dialect clears the refusal by declaring a `Feature` — the mechanism S-0025 already provides.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/evidence.py` `src/bloomery/resolve/build.py` `src/bloomery/transforms/_builtins.py` `tests/fixtures/currency_convert_refusal/entity_model.yaml` `tests/support/type_conformance.py` `tests/unit/test_emit/test_currency_convert.py` `tests/unit/test_evidence.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-26 — `ASSUMED` (Deterministic union merge)

**Answers D25 (`OPEN`) — option (a), and D25's blast-radius figure was wrong by an order of magnitude.** The lowered expression moves to a new column-grained `SourceColumnIR` on `SourceIR`; `ColumnIR` keeps the schema (§5.7). D25 said "37 `.columns` read sites" and estimated the cost from that; measured, **exactly 8 sites read a `ColumnIR` lowering field, in 3 files** — `plan/diff.py` (`renamed_from` ×4, `recipe_id`, `expr.sql`) and `emit/lower/silver.py` (`expr.ast()` ×2). Four of those eight are `renamed_from`, which D25 mis-assigned to the lowering half and which is declared on the EntityModel `Field`, so it does not move at all. The 37 was a count of `.columns` readers, and `.columns` readers are overwhelmingly *schema* readers — they survive untouched, which is the whole point of the split. **Real cost: two constructors where there was one, and four call sites.** The golden churn stands regardless — the IR shape moves and D17 bumps the version.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/operands.py` `src/bloomery/guardrails/stage.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/resolve/build.py` `src/bloomery/resolve/facets.py` `src/bloomery/resolve/steps.py` `src/bloomery/resolve/timeline.py` `tests/bench/test_hydration.py` `tests/support/ir_factory.py` `tests/support/plan_ir.py` `tests/unit/test_emit/test_cube.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_facets.py` `tests/unit/test_unresolved.py`

### S-0041/D-32 — `LOCKED` (Deterministic union merge)

**A rule's per-mapping dependency is projected as a branch-local column; the rule stays entity-grained (P2a).** The mechanism is not invented here — `coercible` already reads projected `_src_<rule>_<n>` aliases (`quality/predicates.py:source_alias`) rather than inline JSONPaths, because the raw paths live one level down in the extract SELECT, and P1 turned that projection site into `_branch_select`. So a fact only one branch knows already has a way to reach a rule the merged relation evaluates once. **D6 is not violated, and the reading that says it is — that projecting a verdict per branch just *is* "a rule evaluated per source" — mistakes what D6 argues.** D6 argues from the *row population* — "a rule evaluated per source would judge rows the merged relation does not contain" — and the union is `ALL`, so a branch-projected **scalar** verdict judges exactly the rows the union contains. Dedupe runs after the union and may drop a row; that row's flag is then unused, which is not a wrong answer. **The boundary is `WINDOWED_KINDS`** (`quality/predicates.py`, currently `{unique}`): a windowed verdict depends on the population and so may not be computed per branch — and it does not need to be, since its inputs are the produced column values, which D26's split already makes mapping-invariant. Consequence: `coercible` sheds its per-source alias set for one branch-computed boolean ("every source path *this branch* read was non-null"), which collapses the arity problem at the level where arity is known; `in_enum` takes the same shape rather than a second mechanism, its admissible set being the branch's own `enum_map` chain. **The tempting wrong fix is recorded so it is not re-proposed:** NULL-filling a missing `_src_` alias to make the arities agree renders `is_not_null` false, the conjunction never fires, and the rule silently stops checking on that branch — the failure D28 refuses by name, a check that quietly stops checking being worse than one that is absent.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/guardrails/quality.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/quality/lower.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/build.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_merged_cleaning.py` `tests/fixtures/multi_source_quality/mapping_legacy.yaml` `tests/support/quality_rules.py` `tests/unit/test_quality/test_lower.py` `tests/unit/test_quality/test_predicates.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0045/D-5 — `LOCKED` (`timestamp` is zoneless UTC, on every port)

The check exists, and it is a **conformance battery at the engine tiers over the transform registry** — not an emit-time assertion. Emit has no engine to ask and no usable static model of one; and a type-shaped check at emit invites a cast-shaped fix, which would have made this defect's type right and its value no less wrong. §7 has the measurement.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/postgres.py` `tests/engines/test_postgres_spellings.py` `tests/engines/test_type_conformance.py` `tests/execution/test_type_conformance.py` `tests/support/type_conformance.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_transforms/test_type_conformance_corpus.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0046/D-1 — `ASSUMED` (Transform types the engine agrees with)

A builder is told its **input logical type**. `Builder` becomes `(input type, column AST, *args) -> AST` or gains it by keyword; the declaration and the construction then read the same fact. This is the enabling change for §2.1 and §2.2.

- Paths: `src/bloomery/resolve/build.py` `src/bloomery/transforms/registry.py` `tests/support/type_conformance.py` `tests/unit/test_transforms/test_registry.py`

### S-0056/D-3 — `LOCKED` (Production-style semantic bug corpus)

**Each case pins a machine-readable outcome against a stable rule ID, not prose.** Prose is golden-tested only where diagnostics are already a public contract. This is what lets S-0005's rules cite cases and S-0006's matrix cite both without either restating the other.

- Paths: `tests/execution/test_semantic_corpus.py` `tests/support/semantic_corpus.py` `tests/unit/test_semantic_corpus_guard.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
