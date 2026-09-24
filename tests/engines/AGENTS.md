<!-- torve:managed tests/engines — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/engines/`

### S-0012/D-1 — `LOCKED` (Validating a dialect port against an engine we cannot run)

An emulator, a surrogate engine or a compatible-wire shim is evidence, never the oracle: the real engine's own compiler is the dialect oracle, and no rung below the authoritative ones may be quoted as engine conformance

- Paths: `tests/engines/**` `tests/support/**`
- Consequence: A cloud port's acceptance is the authoritative rung's, so a port whose only green lanes are local has not been validated and a review says so; the local lanes stay worth running as the fast signal, and stay unable to close the port
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0012/D-2 — `LOCKED` (Validating a dialect port against an engine we cannot run)

Rung 4 carries a `surrogate` marker distinct from `engine`, so a lane backed by an emulator, a Spark session or a Postgres shim cannot select or report as the engine matrix does

- Paths: `pyproject.toml` `tests/engines/**`
- Consequence: The marker table gains a ninth entry when the first surrogate lane lands, and `engine(name)` keeps meaning Docker plus the real engine; a CI log distinguishes the two without anyone reading a test body
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0012/D-3 — `LOCKED` (Validating a dialect port against an engine we cannot run)

The authoritative compile rung exists for every cloud port, because every one of the four engines has one — `EXPLAIN USING JSON`, a dry run, `EXPLAIN`, `EXPLAIN EXTENDED` and `DESCRIBE QUERY` — and a port without it has no authoritative layer at all

- Paths: `tests/engines/**` `tests/support/**`
- Consequence: Each of the four ports owes a compile lane over the shared corpus before it can be called validated, and the lane costs a parse rather than a scan; the absence of a container stops being a blocker for any of them
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0012/D-6 — `ASSUMED` (Validating a dialect port against an engine we cannot run)

All six rungs run the shared fixture corpus rather than a per-engine one; a port-native fixture is added alongside, never instead, where an engine surface has no shared analogue

- Paths: `tests/fixtures/**` `tests/engines/**`
- Consequence: A divergence presents as one fixture behaving differently across ports, which is comparable; departing means an engine surface with genuinely no shared analogue, such as `VARIANT` or `SUPER`

### S-0013/D-3 — `ASSUMED` (Snowflake dialect port) — implementation: none

The OSS emulator `ghcr.io/sivchari/snowflake-emulator` is the default local lane and LocalStack for Snowflake is optional

- Paths: `tests/engines/**` `tests/support/**`
- Consequence: The default lane needs no token and no licence, which is the only thing that makes it a candidate for a per-pull-request slot at all, since a lane requiring a secret cannot run on a fork pull request; departing means the OSS emulator's documented gaps — no distributed execution, no meaningful access control, no warehouse management, no guaranteed transaction isolation — reaching a fixture that matters, in which case LocalStack becomes the default and its token constraint follows it

### S-0013/D-4 — `ASSUMED` (Snowflake dialect port) — implementation: none

Both emulators carry the `surrogate` marker, distinct from `engine`, and neither gates a release

- Paths: `tests/engines/**` `pyproject.toml`
- Consequence: `engine("snowflake")` over an emulator is the claim made in the one place it is invisible — a test name in a CI log — so the tier table grows a rung rather than reusing one, and a green surrogate lane can never be quoted as engine conformance

### S-0013/D-5 — `OPEN` (Snowflake dialect port) — implementation: none

Whether the LocalStack lane is maintained at all is decided from the defects each emulator found that the other missed, after one port's worth of work, and not before

- Paths: `tests/engines/**` `tests/support/**`
- Consequence: Two emulators is two maintenance surfaces, two pinned versions and two sets of documented gaps to know; whoever runs both counts what each caught and records the count, and a decision taken before that evidence exists is the thing this row refuses

### S-0014/D-3 — `LOCKED` (BigQuery dialect port) — implementation: none

The emulator lane is pinned to an exact image tag and is never the authoritative lane — it is evidence, marked as a surrogate, and the real service's own compiler is the oracle

- Paths: `tests/engines/test_bigquery_surrogate.py`
- Consequence: `latest` is not a lane, because a tier whose engine version can change under it cannot tell a regression from an upgrade; and a green surrogate run may never be quoted as engine conformance, which is why the claim has to be kept out of the test's name rather than only out of its body
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0014/D-6 — `OPEN` (BigQuery dialect port) — implementation: none

Whether the emulator lane runs on pull requests, and the executor decides it on measured runtime and on whether it catches anything rungs 1 through 3 miss

- Paths: `tests/engines/test_bigquery_surrogate.py` `.github/workflows/ci.yml`
- Consequence: It needs no credential, which makes it eligible where the other three ports' live lanes are not — and it is also the rung with the least authority, so a slot on every pull request buys time from every contributor for a signal that may be redundant

### S-0015/D-2 — `LOCKED` (Redshift dialect port) — implementation: none

A green Floci or LocalStack run proves PostgreSQL accepted the query, and the test name says so — the lane carries a surrogate marker and never claims the engine

- Paths: `tests/engines/test_redshift_surrogate.py`
- Consequence: Here the surrogate is not merely a different implementation, it is the engine bloomery already ships a port for, so a test named for the engine could be passing entirely on the PostgreSQL scaffold
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0015/D-5 — `ASSUMED` (Redshift dialect port) — implementation: none

LocalStack is optional while bloomery remains a pure compiler

- Paths: `tests/support/redshift.py` `tests/engines/test_redshift_surrogate.py`
- Consequence: It emulates control-plane and Data API surfaces bloomery does not touch, so no lane is blocked on it

### S-0016/D-3 — `LOCKED` (Databricks SQL dialect port) — implementation: none

The Spark lane is marked `surrogate("databricks_spark")`, never as the Databricks engine — local Spark checks shared Spark semantics, and only a live warehouse checks the Databricks dialect

- Paths: `tests/engines/test_databricks_surrogate.py` `pyproject.toml`
- Consequence: A green run in that lane cannot be quoted later as Databricks conformance, because the name a CI log prints already says what was tested
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0016/D-4 — `LOCKED` (Databricks SQL dialect port) — implementation: none

`DESCRIBE QUERY` is part of the authoritative lane, not an optional extra beside `EXPLAIN EXTENDED`

- Paths: `tests/support/databricks.py` `tests/engines/test_databricks_live.py`
- Consequence: The declared-versus-produced type contract is checked against the real analyzer without executing anything or scanning any data; without it, type conformance rests on the surrogate, which is precisely where Spark and Databricks SQL are documented to differ
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0016/D-6 — `ASSUMED` (Databricks SQL dialect port) — implementation: none

Databricks Free Edition is sufficient to bootstrap the live lane, provided the lane stays small — serverless-only, one `2X-Small` warehouse, fair-use quotas, no SLA

- Paths: `tests/engines/test_databricks_live.py` `.github/workflows/**`
- Consequence: The port is not blocked on anyone buying a workspace, and the live lane is sized by what the edition can carry rather than by what the offline tiers happen to cover

### S-0016/D-7 — `ASSUMED` (Databricks SQL dialect port) — implementation: none

The Spark surrogate lane is kept only if it catches defects the offline rungs miss; it is measured over one port's work and dropped on that evidence

- Paths: `tests/support/spark.py` `tests/engines/test_databricks_surrogate.py`
- Consequence: The lane's cost is justified by what it returns rather than by the plausibility of having it, and dropping it is a recorded outcome rather than neglect

### S-0026/D-21 — `ASSUMED` (Testing strategy and fixture corpus)

*(2026-08-10)* **The Trino engine tier is built, on the memory connector, and `spark` is struck from §5.2.** Trino was the engine bloomery made the most claims about and executed the least: three decisions — D83's reject-table constructions, D86's `normalize`/`charset`, D89's mart-assertion body shapes — were each verified against `trinodb/trino:483` **by hand**, through `docker exec`, because the repository carried no Trino client. A hand-verification is a claim with a date on it, not a test, and all three are now a permanent tier (`trino` + `testcontainers[trino]` in the `engines` group). The strongest assertion is the one D75 said was impossible: the `<entity>__reject` model *materializes*, and its `reject_id` is compared against the canon-bytes digest computed here in Python rather than against Trino agreeing with itself — cross-engine *agreement* being the property that identity actually needs, since a replay run on one engine must find the row another quarantined. Sabotage-verified: dropping the `LOWER` from Trino's `TO_HEX` makes the digest disagree in case alone, which the tier catches and which no rendering test could. **The connector is `memory`, diverging from §5.2's `trino+iceberg+minio (compose)` sketch**: bloomery emits SELECTs and models and never storage-format DDL, so an object store and a table format would be three more moving parts serving no assertion in this tier — recorded rather than silently simplified. **`spark` is struck from the same row.** S-0025 ships DuckDB, Postgres and Trino; there is no Spark dialect, so a Spark cell had nothing to exercise and the word promised a matrix column that could never have contained a test. It returns if and when a Spark dialect does.

- Paths: `tests/engines/test_trino.py` `tests/engines/test_trino_execution.py` `tests/support/cube.py` `tests/unit/test_examples.py`

### S-0033/D-10 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

One `<entity>__reject` table per entity with the §5.6 schema (stable sha256 `reject_id` for idempotent replay). Retention is **required** whenever any quarantine disposition exists — missing retention is a compile error; retention deletes **all** reject rows on expiry (unresolved measured from `last_seen`, resolved from `resolved_at`) and is the only deleter — replay never deletes. `redact:` paths apply at write time and must not intersect any path the entity's mappings read (`from` paths, recipe aliases included) — an intersecting redact is the compile error `RedactionConflict`. Bloomery emits the reject/replay artifacts and never executes them.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/errors.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `tests/engines/test_merged_cleaning_engines.py` `tests/fixtures/multi_source_quality/entity_model.yaml` `tests/unit/test_guardrails/test_quality.py`

### S-0033/D-21 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Ingestion metadata contract: entities using `quarantine` or `dedupe` require bronze `_load_id`, `_ingested_at`, `_source_row_id` (a stable per-source-row identity supplied by the ingestion layer, **NOT NULL and unique per source row** — data properties no compiler can check, so the lowering emits a generated **blocking audit** on the metadata columns: a null or duplicated `_source_row_id` stops the run); column absence is the new compile error `IngestionMetadataMissing` (`GuardrailError` leaf, `errors.py` per S-0019/D-3). `reject_id` = sha256 over the length-prefixed utf-8 **pair** (`source_relation`, `_source_row_id`) — canonical serialization per the S-0020 canon-bytes doctrine. This supersedes the triple this row first carried (this round's own earlier decision): `_load_id` is removed from the identity and becomes an attribute (the latest observing load) — re-deliveries of the same source row across loads must land on the **same** reject row (that is what `first_seen`/`last_seen` track); a per-load identity would mint a new row per retry and violate replay idempotence. A re-delivery updates `last_seen`/`_load_id`/`failed_rules` on the existing row.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/quality.py` `src/bloomery/quality/catalogue.py` `src/bloomery/quality/dedupe.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/transforms/_builtins.py` `tests/e2e/test_dbt_parse.py` `tests/e2e/test_sqlmesh_project.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_dedupe_and_audits.py` `tests/execution/test_merged_cleaning.py` `tests/execution/test_zoneless_utc.py` `tests/fixtures/dirty/README.md` `tests/fixtures/semi_additive_inventory/mapping.yaml` `tests/support/execution.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_trino.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_entity.py`

### S-0033/D-23 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

`_quality_flags` **and** `failed_rules` share one physical contract: rule names identifier-constrained at parse (no escaping in any lowering); the column is never NULL (empty array / empty delimited string per `DialectFeature.ARRAY`); delimited fallback joins with `,` in lexicographic rule-name order; `_quality_ok` generated per shape; flag-set equality across lowerings asserted in the dialect-matrix tier. The reject table's `failed_rules` lowers by exactly this contract — array where `DialectFeature.ARRAY`, else the lexicographic comma-delimited string.

- Paths: `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/spec/quality.py` `tests/engines/test_merged_cleaning_engines.py` `tests/unit/test_quality/test_flags.py` `tests/unit/test_spec/test_quality.py`

### S-0033/D-83 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **The reject table's two constructions are spelled by the dialect port, and Trino hosts it. D75 is closed — and Postgres turned out to be wrong in the same place, silently.** D75 recorded the two gaps and refused Trino at emit; the fix it named — a per-dialect hook rather than a shared AST — is built. `DialectPort` gains `text_sha256` and `json_object`, because a construction that differs per engine belongs to the port that knows the engine (S-0025/D-1), not to a lowering that is supposed to be dialect-neutral. Trino: `LOWER(TO_HEX(SHA256(TO_UTF8(…))))` and the standard keyword `JSON_OBJECT`. **The finding that was not in D75:** Postgres declared support for *both* features and has neither. Its `sha256` takes and returns `bytea`, so the plain spelling did not fail — it silently yielded bytes where every other engine yields a hex string, which would have made `reject_id` disagree across engines while looking like it worked; and it has no positional `json_object` at all (`function pg_catalog.json_object(unknown, integer, …) does not exist` — the SQL/JSON one arrived in 16 taking `KEY … VALUE` only, and the positional builder has always been `json_build_object`). D75's own sentence — "the one construction SQLGlot renders verbatim on every shipped dialect… holds for DuckDB and Postgres but not Trino" — was therefore half wrong, and it read as verified because the *other* half had been. It held only because Postgres never reached emission: D30 refuses a quality-carrying entity there for the unrelated `TRY_CAST` reason, so the reject table was never built for it. Postgres now has correct spellings that stay unreachable until D30 lifts, asserted at the port rather than through a compile so they cannot rot in the meantime. Verified by **executing the emitted model**, not the expressions: the full `__reject` SELECT runs on `trinodb/trino:483` and returns a `reject_id` byte-identical to the Python canon-bytes digest — cross-engine *agreement* being the property `reject_id` actually needs. The feature flags stay in the vocabulary: a fourth dialect may still lack either, and the refusal they drive is still the right answer for one that does.

- Paths: `src/bloomery/dialects/postgres.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/quality/reject.py` `tests/engines/test_merged_cleaning_engines.py` `tests/golden/test_sqlmesh_dialects.py` `tests/unit/test_emit/test_quality_artifacts.py`

### S-0033/D-84 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **Postgres hosts quality-carrying entities: `TRY_CAST` is a guard around Postgres' own input parser, not a regex. D30 is closed.** D30 named the escape hatch as "a per-type `CASE`-based fallback whose semantics are proven equal to `TRY_CAST`'s on the corpus", and a per-type regex is what that sounded like. It is the wrong build: a regex is an *approximation* of the parser, and it would have to be kept in step with it forever. `pg_input_is_valid` (Postgres 16+) is the parser, so `CASE WHEN pg_input_is_valid(x, 't') THEN CAST(x AS t) END` accepts exactly what `CAST` accepts and yields NULL exactly where `CAST` raises — equal **by construction** rather than by a proof that decays. Measured anyway, because a claim that is checked is a commitment: over a 57-value adversarial corpus × 5 types, 284 of 285 cases identical to plain `CAST` modulo NULL-on-error. The rewrite lives in the dialect's `render`, so the IR keeps the dialect-neutral `TryCast` node it already had. **The 285th case is the finding.** Postgres accepts `now`/`today`/`tomorrow`/`yesterday` as datetime input and resolves them to the *transaction timestamp*, so a bronze cell spelling `now` coerces to a different value on every run — a backfill disagreeing with the run it replaces, which S-0020 exists to prevent, arriving green and unrestatable. The temporal guard excludes them, which is the one place it is deliberately **stricter** than `CAST`: such a cell becomes a coercion failure the `coercible` rule disposes of, a quarantined row rather than a silently unstable one. It also moves Postgres *toward* DuckDB, which rejects `now` outright. Verified by execution, not rendering — rendering was never the hard part, and D30's whole point was that a plain `CAST` renders beautifully and aborts the run: the quality-carrying fixture materializes on postgres 16 with the clean row kept and one specimen per failure mode quarantined, `now` among them, and the tier is now a permanent engine test. Two harness traps recorded because both nearly produced a wrong answer: a *constant* subquery is folded at plan time, so the `CASE`'s other branch evaluates and raises — the guard is only safe over a column, which is what a bronze relation always is; and psycopg reports its own inability to represent `infinity` as an error indistinguishable from a SQL one, which made three engine-accepted values look rejected. **Not closed:** cast *semantics* still differ across engines — DuckDB coerces `'1.5'` to an int and Postgres does not — so the same spec quarantines different rows on different engines. That is inherent to running on different engines, predates this change, and is recorded here rather than implied to be fixed.

- Paths: `src/bloomery/dialects/postgres.py` `tests/engines/test_type_conformance.py` `tests/support/type_conformance.py` `tests/unit/test_docs_floor.py`

### S-0033/D-86 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **The catalogue gains `normalize` and `charset`, and the confusables table is deliberately not among them. D26 is closed.** D26 offered "a Unicode normal form **and/or** a confusables table"; only the first half is built as offered. `normalize` is `NORMALIZE(col, NFC) <> col` — the dialect-neutral node, rewritten to `NFC_NORMALIZE` inside DuckDB's `render` because DuckDB has that function and no `NORMALIZE`, while SQLGlot's duckdb generator renders one verbatim (the D83 shape: renders everywhere, defined in two places out of three). One form only: Postgres and Trino spell all four, DuckDB spells one, and a rule that compiles everywhere and runs on two engines out of three is what S-0025/D-3 exists to refuse. It is a **rule and never a transform** — normalizing silently would rewrite what a source delivered, which D1 forbids. **The table is refused on determinism grounds:** UTS#39 confusables is versioned Unicode data, so embedding it would make a row's disposition depend on which Unicode revision the compiler shipped — an ambient input by another name (S-0020), and one that would move dispositions under a dependency bump nobody read as a semantic change. `charset` declares the admissible characters instead, as `U+` codepoints and inclusive ranges, exactly one of `allow:`/`forbid:`, lowering through a single `TRANSLATE(col, members, '')` read two ways. Codepoints rather than characters because every character the rule exists to catch is invisible: a literal one in YAML is unreadable in review and indistinguishable from a space in a diff. The `allow` reading turns out to be *stronger* than the table would have been for the case that motivated it — an allow-list of the script a column is written in catches a Cyrillic homoglyph, a fullwidth digit and an Arabic-Indic digit alike, none of which any denylist enumerates completely. Three declaration refusals, all decidable from the spec alone and so `GuardrailError`s: a backwards range, a range crossing the surrogate block (checked on the *span*, not the endpoints — the block is 2048 wide, so an endpoint-only check would leave the real refusal to arrive from `MAX_CHARSET_SIZE`, a constant that has nothing to do with surrogates and could grow), and a set past that cap, which exists because the members become a string literal in every row's predicate and in the IR fingerprint. `TRANSLATE` carries **no** `DialectFeature`: all three engines spell it identically and its delete-when-shorter behaviour was executed on each rather than assumed; a feature flag earns its place where the *port* has to differ, which is why `normalize` has one and this does not. Verified by execution on postgres 16 as a permanent engine tier and on `trinodb/trino:483` by hand (no Trino client dependency yet — S-0026's outstanding work), both agreeing with DuckDB on every specimen including the null. **Found on the way:** the §6 matrix rendered through `node.sql(dialect="duckdb")` rather than through the port, so it executed SQL the emitter never emits. Here that surfaced as a failure — DuckDB has no `NORMALIZE` at all — but the failure is incidental to the direction of this particular rewrite. A port rewrite that produces something the *direct* render also accepts would have diverged silently, with the matrix green on SQL no artifact contains. It is routed through the port now.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/duckdb.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/quality/charset.py` `src/bloomery/quality/predicates.py` `src/bloomery/spec/quality.py` `tests/engines/test_postgres_text_rules.py` `tests/golden/schema/mapping.json`

### S-0041/D-32 — `LOCKED` (Deterministic union merge)

**A rule's per-mapping dependency is projected as a branch-local column; the rule stays entity-grained (P2a).** The mechanism is not invented here — `coercible` already reads projected `_src_<rule>_<n>` aliases (`quality/predicates.py:source_alias`) rather than inline JSONPaths, because the raw paths live one level down in the extract SELECT, and P1 turned that projection site into `_branch_select`. So a fact only one branch knows already has a way to reach a rule the merged relation evaluates once. **D6 is not violated, and the reading that says it is — that projecting a verdict per branch just *is* "a rule evaluated per source" — mistakes what D6 argues.** D6 argues from the *row population* — "a rule evaluated per source would judge rows the merged relation does not contain" — and the union is `ALL`, so a branch-projected **scalar** verdict judges exactly the rows the union contains. Dedupe runs after the union and may drop a row; that row's flag is then unused, which is not a wrong answer. **The boundary is `WINDOWED_KINDS`** (`quality/predicates.py`, currently `{unique}`): a windowed verdict depends on the population and so may not be computed per branch — and it does not need to be, since its inputs are the produced column values, which D26's split already makes mapping-invariant. Consequence: `coercible` sheds its per-source alias set for one branch-computed boolean ("every source path *this branch* read was non-null"), which collapses the arity problem at the level where arity is known; `in_enum` takes the same shape rather than a second mechanism, its admissible set being the branch's own `enum_map` chain. **The tempting wrong fix is recorded so it is not re-proposed:** NULL-filling a missing `_src_` alias to make the arities agree renders `is_not_null` false, the conjunction never fires, and the rule silently stops checking on that branch — the failure D28 refuses by name, a check that quietly stops checking being worse than one that is absent.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/guardrails/quality.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/quality/lower.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/build.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_merged_cleaning.py` `tests/fixtures/multi_source_quality/mapping_legacy.yaml` `tests/support/quality_rules.py` `tests/unit/test_quality/test_lower.py` `tests/unit/test_quality/test_predicates.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-34 — `LOCKED` (Deterministic union merge)

**Artifact shape varies with mapping count; `_source` stays merged-only (P2b).** The question D7 and D15 both defer, answered once for the provenance column, the metadata audit body and the collision audit together. The metadata audit becomes `PARTITION BY _source, _source_row_id` on a merged entity and stays `PARTITION BY _source_row_id` elsewhere. **The cost is a new precedent, stated here rather than discovered later:** until now the *set* of emitted artifacts varied with a spec, never a generated **body**. The alternative — `_source` on every entity, one uniform audit body, mapping count invisible in the artifacts — buys a reader the property that a merged entity looks like any other, and costs a corpus-wide golden re-stamp plus a constant column on every single-source silver model, which is precisely what D9 declined to pay on measured grounds. Continuing that decision is cheaper than reversing it, and reversing it buys nothing but uniformity. **A third option is named only to close it:** making `_source_row_id` globally unique in bronze would dissolve the question, and it does so by relocating the problem into S-0033/D-21's ingestion contract and breaking every table already landed under it.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_merged_cleaning.py` `tests/golden/test_sqlmesh_dialects.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0045/D-5 — `LOCKED` (`timestamp` is zoneless UTC, on every port)

The check exists, and it is a **conformance battery at the engine tiers over the transform registry** — not an emit-time assertion. Emit has no engine to ask and no usable static model of one; and a type-shaped check at emit invites a cast-shaped fix, which would have made this defect's type right and its value no less wrong. §7 has the measurement.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/postgres.py` `tests/engines/test_postgres_spellings.py` `tests/engines/test_type_conformance.py` `tests/execution/test_type_conformance.py` `tests/support/type_conformance.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_transforms/test_type_conformance_corpus.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0051/D-1 — `LOCKED` (The reject table on a merged entity)

**S-0033/D-10 stands: one reject table per entity, merged or not.** Its stated ground — per-mapping tables multiply into the small-file problem and make replay N-way — is a statement about the number of *relations*, and this design adds none. D10 answered a different question and its answer is still right. Consequence: S-0041/D-16's lock is discharged by keeping the decision, not by overturning it, and any future proposal for a per-mapping table argues against D10 as it always had to.

- Paths: `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_merged_cleaning.py` `tests/fixtures/multi_source_quality/entity_model.yaml`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0051/D-2 — `LOCKED` (The reject table on a merged entity)

**`source_relation`, `mapping`, `mapping_version` and `reject_id` are projected per union branch.** They are true of a branch and were only ever true of a model because there was one branch. `reject_id` moves with them out of necessity rather than symmetry: its first argument is the branch's relation name, which the union erases. Consequence: `reject_select` reads four more columns off the extract subquery and reads no `SourceIR` at all.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/plan/diff.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_merged_cleaning.py` `tests/unit/test_plan/test_diff.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0052/D-5 — `ASSUMED` (The offset-bearing timestamp)

**Detection is `SUBSTRING(x, 11)` plus two `LIKE`s, not a regex.** Portable with no per-port spelling and no escaping dialect, and correct for every ISO 8601 form these engines parse: the ten-character calendar date is the only place a `-` can appear innocently. Departing means a regex, and the cost of departing is three function names — `regexp_like`, `regexp_matches`, `~` — for the same boolean.

- Paths: `src/bloomery/dialects/base.py` `tests/engines/test_zoneless_utc.py`

### S-0055/D-1 — `LOCKED` (Multi-grain aggregate-then-join query planning)

**Aggregate, then join — never join, then aggregate and hope.** The whole document exists for this one ordering, and the alternative is the silent double count it names in §1. A later optimization pass may not reorder across it without a preservation proof.

- Paths: `src/bloomery/semantic/plan.py` `tests/engines/test_branch_join_engines.py` `tests/fixtures/semantic_corpus/006-two-grains-one-request/problem.md`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0055/D-17 — `ASSUMED` (Multi-grain aggregate-then-join query planning)

**`IS NOT DISTINCT FROM` is a declared `DialectFeature`, proven in the engine tier, not asserted from documentation.** It was executed on DuckDB and read about for Postgres and Trino; a planner that composes a join for three dialects on two readings is asserting a capability it has not seen. The feature enum is the existing place a dialect says what it can do, and an engine-tier test is where the claim stops being a citation. **Answered:** `tests/engines/test_branch_join_engines.py` executes the composed statement on all three, and the first thing it found was that the D13 spelling does not run on PostgreSQL at all — see D18.

- Paths: `src/bloomery/planner/compose.py` `tests/engines/test_branch_join_engines.py`

### S-0055/D-18 — `LOCKED` (Multi-grain aggregate-then-join query planning)

**The composition is a key domain and left joins, not a full outer join — D13's semantics, in the only spelling all three dialects run.** PostgreSQL refuses `FULL JOIN … ON a IS NOT DISTINCT FROM b` outright: *"FULL JOIN is only supported with merge-joinable or hash-joinable join conditions"*. The predicate is supported there, as every reference says, and not in that position. **This project already knew it**: `emit/lower/reconcile.py` emits the same long spelling for the same reason, and `spec-schemas.md` says why in the same words — so what the engine tier bought here was a rediscovery, and the cheaper check was a grep for the construct (logs/T-0026.md, D172). So the branches are CTEs, their keys are `UNION`ed into the domain of groups the answer has, and each branch is left-joined back onto that domain on `IS NOT DISTINCT FROM`. The null semantics are unchanged and now carried by two constructs that agree: `UNION` deduplicates NULL against NULL, and the left join matches a branch's NULL group to the domain's. Every group present in any branch appears exactly once, which is what the full outer join was for. `LOCKED` rather than `ASSUMED` because a later change back to the obvious shape would render on two dialects and fail to plan on the third (see logs/T-0026.md, D171).

- Paths: `tests/engines/test_branch_join_engines.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
