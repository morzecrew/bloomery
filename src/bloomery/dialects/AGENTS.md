<!-- torve:managed src/bloomery/dialects — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/dialects/`

### S-0012/D-8 — `OPEN` (Validating a dialect port against an engine we cannot run)

Whether a cloud port ships in-tree or as an extension package registered through `register_dialect`; decide it before the first cloud port lands

- Paths: `src/bloomery/dialects/**`
- Consequence: Moving a shipped dialect between the two is a breaking change either way, so the choice is cheap now and expensive later

### S-0020/D-2 — `ASSUMED` (Intermediate representation and determinism contract)

SQL is stored in the IR as canonical dialect-neutral SQLGlot text (`SqlExpr`), re-parsed at emit. Consequence: SQLGlot version changes can change fingerprints; the exact pin (D4 §5.5) makes that a deliberate event.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/emit/lower/marts.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `src/bloomery/transforms/_builtins.py` `tests/support/type_conformance.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_postgres.py` `tests/unit/test_transforms/test_builtins.py` `tests/unit/test_transforms/test_type_conformance_corpus.py`

### S-0021/D-7 — `ASSUMED` (Logical types and the transform registry)

Transform builders produce SQLGlot AST only — never string formatting. Dialect rendering happens at emit (S-0025); dialect incapability is an emit-time `DialectPort` feature failure, never a typing concern.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/steps/splice.py` `src/bloomery/transforms/_builtins.py` `tests/unit/test_steps/test_splice.py`

### S-0025/D-1 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Three independent ports (`TargetEmitter`, `DialectPort`, `NamingPolicy`), all `Protocol`s. Target and dialect never collapse into one adapter.

- Paths: `src/bloomery/dialects/__init__.py` `src/bloomery/dialects/base.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/naming.py` `src/bloomery/quality/flags.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_postgres.py`

### S-0025/D-3 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Capability mismatch behavior is fail-loud: `UnsupportedByTarget` naming entity + feature. Silent degradation is forbidden.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/spec/quality.py` `src/bloomery/transforms/_builtins.py` `tests/property/test_compile_properties.py` `tests/unit/test_emit/test_base.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_quality/test_text_rules.py` `tests/unit/test_transforms/test_builtins.py`

### S-0025/D-4 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

SQL rendering: SQLGlot AST → `DialectPort.render`; Jinja only ever sees pre-rendered strings (envelope templating).

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/emit/steps.py` `tests/property/test_compile_properties.py` `tests/unit/test_steps/test_dbt_and_cube_emission.py`

### S-0025/D-5 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

v0.1 adapter set: SQLMesh + Cube + dbt targets; DuckDB + Postgres + Trino dialects. dbt is a port-abstraction proof, documented as such.

- Paths: `src/bloomery/compile.py` `src/bloomery/dialects/duckdb.py` `src/bloomery/dialects/postgres.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/runtime/sql_client.py` `tests/unit/test_dialects/test_duckdb.py` `tests/unit/test_dialects/test_postgres.py` `tests/unit/test_dialects/test_trino.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_runtime/test_sql_client.py`

### S-0025/D-8 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Emitter/dialect registries mirror the transform registry: immutable defaults + explicit overlay, collision is an error, iteration sorted (S-0021/D-6).

- Paths: `src/bloomery/dialects/__init__.py` `src/bloomery/emit/__init__.py` `src/bloomery/runtime/sql_client.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_emit/test_base.py`

### S-0033/D-3 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Coercion failure is a rule: transform chains lower to failure-marker form (`TRY_CAST`-style per dialect); the implicit, overridable `coercible` rule (default `quarantine`) disposes of it. Retires `Mapping.on_unmapped_enum` (S-0019 amendment — absorbed into `in_enum`/`coercible`) and supersedes S-0025/D-7's never-implemented emitter convention with the modeled reject table.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/guardrails/operands.py` `src/bloomery/quality/predicates.py` `src/bloomery/spec/mapping.py` `src/bloomery/spec/quality.py` `src/bloomery/transforms/_builtins.py` `tests/execution/test_path_conflict.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_spec/test_mapping.py`

### S-0033/D-9 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Silver gains `_quality_flags`/`_quality_ok`; marts gain `has_quality_flags` (S-0027 amendment). Array capability is `DialectFeature.ARRAY` — an engine property, deliberately diverging from Document 5's `TargetCapabilities` placement; dialects without it lower to a delimited string.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/marts/flatten.py` `src/bloomery/spec/common.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_steps/test_lowering.py`

### S-0033/D-21 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Ingestion metadata contract: entities using `quarantine` or `dedupe` require bronze `_load_id`, `_ingested_at`, `_source_row_id` (a stable per-source-row identity supplied by the ingestion layer, **NOT NULL and unique per source row** — data properties no compiler can check, so the lowering emits a generated **blocking audit** on the metadata columns: a null or duplicated `_source_row_id` stops the run); column absence is the new compile error `IngestionMetadataMissing` (`GuardrailError` leaf, `errors.py` per S-0019/D-3). `reject_id` = sha256 over the length-prefixed utf-8 **pair** (`source_relation`, `_source_row_id`) — canonical serialization per the S-0020 canon-bytes doctrine. This supersedes the triple this row first carried (this round's own earlier decision): `_load_id` is removed from the identity and becomes an attribute (the latest observing load) — re-deliveries of the same source row across loads must land on the **same** reject row (that is what `first_seen`/`last_seen` track); a per-load identity would mint a new row per retry and violate replay idempotence. A re-delivery updates `last_seen`/`_load_id`/`failed_rules` on the existing row.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/quality.py` `src/bloomery/quality/catalogue.py` `src/bloomery/quality/dedupe.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/transforms/_builtins.py` `tests/e2e/test_dbt_parse.py` `tests/e2e/test_sqlmesh_project.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_dedupe_and_audits.py` `tests/execution/test_merged_cleaning.py` `tests/execution/test_zoneless_utc.py` `tests/fixtures/dirty/README.md` `tests/fixtures/semi_additive_inventory/mapping.yaml` `tests/support/execution.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_trino.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_entity.py`

### S-0033/D-56 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **The dialects a `pattern` is checked against are the shipped ports, never the registry.** `registered_dialects()` is process-global and mutable, so an extension dialect registered by an unrelated import could decide whether an existing project compiles — the ambient dependency S-0020 exists to forbid, and one no golden would catch. The checked set is the constant `PATTERN_TARGET_DIALECTS = (duckdb, postgres, trino)`, overridable by an explicit argument the caller supplies. Recorded consequence: an extension dialect is no longer checked at compile time. Checking it would mean plumbing a dialect set into `build_project_ir`, which is dialect-free by construction and right to be — a project is portable or it is not, and the guardrail stage has no target. Named as the escape hatch, not built.

- Paths: `pages/docs/how-to/add-quality-rules.md` `src/bloomery/compile.py` `src/bloomery/dialects/__init__.py` `src/bloomery/quality/pattern.py` `tests/unit/test_compile.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_quality/test_edges.py`

### S-0033/D-83 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **The reject table's two constructions are spelled by the dialect port, and Trino hosts it. D75 is closed — and Postgres turned out to be wrong in the same place, silently.** D75 recorded the two gaps and refused Trino at emit; the fix it named — a per-dialect hook rather than a shared AST — is built. `DialectPort` gains `text_sha256` and `json_object`, because a construction that differs per engine belongs to the port that knows the engine (S-0025/D-1), not to a lowering that is supposed to be dialect-neutral. Trino: `LOWER(TO_HEX(SHA256(TO_UTF8(…))))` and the standard keyword `JSON_OBJECT`. **The finding that was not in D75:** Postgres declared support for *both* features and has neither. Its `sha256` takes and returns `bytea`, so the plain spelling did not fail — it silently yielded bytes where every other engine yields a hex string, which would have made `reject_id` disagree across engines while looking like it worked; and it has no positional `json_object` at all (`function pg_catalog.json_object(unknown, integer, …) does not exist` — the SQL/JSON one arrived in 16 taking `KEY … VALUE` only, and the positional builder has always been `json_build_object`). D75's own sentence — "the one construction SQLGlot renders verbatim on every shipped dialect… holds for DuckDB and Postgres but not Trino" — was therefore half wrong, and it read as verified because the *other* half had been. It held only because Postgres never reached emission: D30 refuses a quality-carrying entity there for the unrelated `TRY_CAST` reason, so the reject table was never built for it. Postgres now has correct spellings that stay unreachable until D30 lifts, asserted at the port rather than through a compile so they cannot rot in the meantime. Verified by **executing the emitted model**, not the expressions: the full `__reject` SELECT runs on `trinodb/trino:483` and returns a `reject_id` byte-identical to the Python canon-bytes digest — cross-engine *agreement* being the property `reject_id` actually needs. The feature flags stay in the vocabulary: a fourth dialect may still lack either, and the refusal they drive is still the right answer for one that does.

- Paths: `src/bloomery/dialects/postgres.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/quality/reject.py` `tests/engines/test_merged_cleaning_engines.py` `tests/golden/test_sqlmesh_dialects.py` `tests/unit/test_emit/test_quality_artifacts.py`

### S-0033/D-84 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **Postgres hosts quality-carrying entities: `TRY_CAST` is a guard around Postgres' own input parser, not a regex. D30 is closed.** D30 named the escape hatch as "a per-type `CASE`-based fallback whose semantics are proven equal to `TRY_CAST`'s on the corpus", and a per-type regex is what that sounded like. It is the wrong build: a regex is an *approximation* of the parser, and it would have to be kept in step with it forever. `pg_input_is_valid` (Postgres 16+) is the parser, so `CASE WHEN pg_input_is_valid(x, 't') THEN CAST(x AS t) END` accepts exactly what `CAST` accepts and yields NULL exactly where `CAST` raises — equal **by construction** rather than by a proof that decays. Measured anyway, because a claim that is checked is a commitment: over a 57-value adversarial corpus × 5 types, 284 of 285 cases identical to plain `CAST` modulo NULL-on-error. The rewrite lives in the dialect's `render`, so the IR keeps the dialect-neutral `TryCast` node it already had. **The 285th case is the finding.** Postgres accepts `now`/`today`/`tomorrow`/`yesterday` as datetime input and resolves them to the *transaction timestamp*, so a bronze cell spelling `now` coerces to a different value on every run — a backfill disagreeing with the run it replaces, which S-0020 exists to prevent, arriving green and unrestatable. The temporal guard excludes them, which is the one place it is deliberately **stricter** than `CAST`: such a cell becomes a coercion failure the `coercible` rule disposes of, a quarantined row rather than a silently unstable one. It also moves Postgres *toward* DuckDB, which rejects `now` outright. Verified by execution, not rendering — rendering was never the hard part, and D30's whole point was that a plain `CAST` renders beautifully and aborts the run: the quality-carrying fixture materializes on postgres 16 with the clean row kept and one specimen per failure mode quarantined, `now` among them, and the tier is now a permanent engine test. Two harness traps recorded because both nearly produced a wrong answer: a *constant* subquery is folded at plan time, so the `CASE`'s other branch evaluates and raises — the guard is only safe over a column, which is what a bronze relation always is; and psycopg reports its own inability to represent `infinity` as an error indistinguishable from a SQL one, which made three engine-accepted values look rejected. **Not closed:** cast *semantics* still differ across engines — DuckDB coerces `'1.5'` to an int and Postgres does not — so the same spec quarantines different rows on different engines. That is inherent to running on different engines, predates this change, and is recorded here rather than implied to be fixed.

- Paths: `src/bloomery/dialects/postgres.py` `tests/engines/test_type_conformance.py` `tests/support/type_conformance.py` `tests/unit/test_docs_floor.py`

### S-0033/D-86 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **The catalogue gains `normalize` and `charset`, and the confusables table is deliberately not among them. D26 is closed.** D26 offered "a Unicode normal form **and/or** a confusables table"; only the first half is built as offered. `normalize` is `NORMALIZE(col, NFC) <> col` — the dialect-neutral node, rewritten to `NFC_NORMALIZE` inside DuckDB's `render` because DuckDB has that function and no `NORMALIZE`, while SQLGlot's duckdb generator renders one verbatim (the D83 shape: renders everywhere, defined in two places out of three). One form only: Postgres and Trino spell all four, DuckDB spells one, and a rule that compiles everywhere and runs on two engines out of three is what S-0025/D-3 exists to refuse. It is a **rule and never a transform** — normalizing silently would rewrite what a source delivered, which D1 forbids. **The table is refused on determinism grounds:** UTS#39 confusables is versioned Unicode data, so embedding it would make a row's disposition depend on which Unicode revision the compiler shipped — an ambient input by another name (S-0020), and one that would move dispositions under a dependency bump nobody read as a semantic change. `charset` declares the admissible characters instead, as `U+` codepoints and inclusive ranges, exactly one of `allow:`/`forbid:`, lowering through a single `TRANSLATE(col, members, '')` read two ways. Codepoints rather than characters because every character the rule exists to catch is invisible: a literal one in YAML is unreadable in review and indistinguishable from a space in a diff. The `allow` reading turns out to be *stronger* than the table would have been for the case that motivated it — an allow-list of the script a column is written in catches a Cyrillic homoglyph, a fullwidth digit and an Arabic-Indic digit alike, none of which any denylist enumerates completely. Three declaration refusals, all decidable from the spec alone and so `GuardrailError`s: a backwards range, a range crossing the surrogate block (checked on the *span*, not the endpoints — the block is 2048 wide, so an endpoint-only check would leave the real refusal to arrive from `MAX_CHARSET_SIZE`, a constant that has nothing to do with surrogates and could grow), and a set past that cap, which exists because the members become a string literal in every row's predicate and in the IR fingerprint. `TRANSLATE` carries **no** `DialectFeature`: all three engines spell it identically and its delete-when-shorter behaviour was executed on each rather than assumed; a feature flag earns its place where the *port* has to differ, which is why `normalize` has one and this does not. Verified by execution on postgres 16 as a permanent engine tier and on `trinodb/trino:483` by hand (no Trino client dependency yet — S-0026's outstanding work), both agreeing with DuckDB on every specimen including the null. **Found on the way:** the §6 matrix rendered through `node.sql(dialect="duckdb")` rather than through the port, so it executed SQL the emitter never emits. Here that surfaced as a failure — DuckDB has no `NORMALIZE` at all — but the failure is incidental to the direction of this particular rewrite. A port rewrite that produces something the *direct* render also accepts would have diverged silently, with the matrix green on SQL no artifact contains. It is routed through the port now.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/duckdb.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/quality/charset.py` `src/bloomery/quality/predicates.py` `src/bloomery/spec/quality.py` `tests/engines/test_postgres_text_rules.py` `tests/golden/schema/mapping.json`

### S-0033/D-93 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-11)* **D84's run-dependent deny-list was defeated by a tab.** The narrowing read `LOWER(BTRIM(value)) IN ('now', 'today', …)`, and Postgres' `BTRIM` defaults to trimming **spaces only** while its datetime scanner skips tabs, newlines and carriage returns too. Verified on PostgreSQL 16: `'now\t'`, `'now\n'` and `'now\r'` each pass `pg_input_is_valid`, survive the trim with their whitespace intact, miss the deny-list, and cast to the transaction timestamp — so D84's guard was comparing a string the engine would never see, and the determinism it exists to protect leaked through a whitespace character. Now an anchored `[[:space:]]`-tolerant pattern. Spelled as a POSIX class rather than an `E' \t\n\r\f\v'` trim argument because the emitted SQL is a reviewed artifact and an escape string puts literal control characters into every golden — the readability argument D86 already made for spelling invisible characters as codepoints.

- Paths: `src/bloomery/dialects/postgres.py`

### S-0044/D-1 — `LOCKED` (ISO 8601 timestamps across dialects)

`{parse_ts: ISO8601}` must accept the `T` separator on every shipping dialect. The argument names a standard; a whitelisted transform that implements it on two ports of three is a defect in the transform, not a caveat for the docs.

- Paths: `examples/lakehouse/**` `src/bloomery/dialects/postgres.py` `src/bloomery/dialects/trino.py` `src/bloomery/ir/nodes.py` `src/bloomery/transforms/_builtins.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0044/D-2 — `LOCKED` (ISO 8601 timestamps across dialects)

The fix may **not** be a blanket render-time rewrite of `CAST(… AS TIMESTAMP)` on Trino. Emitted artifacts already cast operands that are timestamps and NULLs, and `REPLACE` over either is a type error, not a no-op (§2).

- Paths: `examples/lakehouse/**` `src/bloomery/dialects/postgres.py` `src/bloomery/dialects/trino.py` `src/bloomery/ir/nodes.py` `src/bloomery/transforms/_builtins.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0044/D-3 — `LOCKED` (ISO 8601 timestamps across dialects)

The fix lives in the **neutral spelling**, not at the port, because provenance does not survive the canonical-text round-trip (§3). Any option that needs the dialect to know a cast came from `parse_ts` is out.

- Paths: `examples/lakehouse/**` `src/bloomery/dialects/postgres.py` `src/bloomery/dialects/trino.py` `src/bloomery/ir/nodes.py` `src/bloomery/transforms/_builtins.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0044/D-4 — `OPEN` (ISO 8601 timestamps across dialects)

Which option of §4. The lean is **(a)**: it is the only one that keeps the DuckDB and PostgreSQL artifacts unchanged in meaning, keeps one producer for the construct, and makes a fourth dialect fail loud rather than quietly wrong.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/transforms/_builtins.py`

### S-0044/D-7 — `LOCKED` (ISO 8601 timestamps across dialects)

Until this lands, the divergence is **documented, not refused**. (d) is the S-0025/D-3-pure answer and it breaks working projects to punish a bug they already routed around; the projects that hit it hit it loudly, through the `coercible` rule, not silently.

- Paths: `examples/lakehouse/**` `src/bloomery/dialects/postgres.py` `src/bloomery/dialects/trino.py` `src/bloomery/ir/nodes.py` `src/bloomery/transforms/_builtins.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0045/D-1 — `LOCKED` (`timestamp` is zoneless UTC, on every port)

`to_utc` produces a **zoneless UTC** value. The type is already documented as always-UTC and the map already declares `TIMESTAMP`; producing a zone-aware value contradicts both.

- Paths: `examples/lakehouse/**` `src/bloomery/dialects/base.py` `src/bloomery/transforms/_builtins.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0045/D-2 — `LOCKED` (`timestamp` is zoneless UTC, on every port)

The normalization lives in the **ports**, not in the transform builder. The three spellings are one meaning, and a builder produces dialect-neutral AST (S-0021/D-7). The neutral tree keeps carrying `AtTimeZone`; each port renders the whole interpretation.

- Paths: `examples/lakehouse/**` `src/bloomery/dialects/base.py` `src/bloomery/transforms/_builtins.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0045/D-3 — `LOCKED` (`timestamp` is zoneless UTC, on every port)

This is a **restating** change: artifacts change, spec meaning does not, and stored values move. A project that built tables before this has data whose derived dates were wrong; a restatement is the migration.

- Paths: `examples/lakehouse/**` `src/bloomery/dialects/base.py` `src/bloomery/transforms/_builtins.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0045/D-4 — `LOCKED` (`timestamp` is zoneless UTC, on every port)

No new spec surface. A per-column "keep the zone" escape hatch would reintroduce the ambiguity this removes, and nothing has asked for one.

- Paths: `examples/lakehouse/**` `src/bloomery/dialects/base.py` `src/bloomery/transforms/_builtins.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0045/D-5 — `LOCKED` (`timestamp` is zoneless UTC, on every port)

The check exists, and it is a **conformance battery at the engine tiers over the transform registry** — not an emit-time assertion. Emit has no engine to ask and no usable static model of one; and a type-shaped check at emit invites a cast-shaped fix, which would have made this defect's type right and its value no less wrong. §7 has the measurement.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/postgres.py` `tests/engines/test_postgres_spellings.py` `tests/engines/test_type_conformance.py` `tests/execution/test_type_conformance.py` `tests/support/type_conformance.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_transforms/test_type_conformance_corpus.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0046/D-3 — `ASSUMED` (Transform types the engine agrees with)

`divide` carries a **neutral-text marker**, the pattern S-0044/D-4 established for `parse_ts`, because a flag on the node does not survive the round trip and re-reading every `Div` at render would change integer division in metric expressions.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/transforms/_builtins.py`

### S-0052/D-1 — `LOCKED` (The offset-bearing timestamp)

**`parse_ts: ISO8601` reads a local wall clock, and text carrying a numeric UTC offset is out of contract.** This is S-0045's contract restated at the boundary that enforces it, not a new rule: `to_utc` is the only door into UTC, so a value that states its own zone is telling the compiler something the declaration already claimed to know. Locking it is what makes §5.3's refusal a consequence rather than a preference — an implementation that "helpfully" converted would be contradicting the spec layer, not extending it.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/transforms/_builtins.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0052/D-2 — `LOCKED` (The offset-bearing timestamp)

**Out-of-contract text becomes NULL; it is never converted and never raises.** NULL is the project's existing spelling for text that is not what the spec said it was, which is why this needs no new reporting surface: `coercible`, the reject table and D21's audit all already read it. Raising was rejected because the offending value is one row's bytes and a compiler that stops the pipeline on one row has no way back; converting was rejected in §5.3 on two independent grounds, one of them measured. Consequence: on an entity with no `quality:` block the refusal is silent, which §9 accepts and §8's door is the answer to.

- Paths: `src/bloomery/dialects/base.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0052/D-3 — `LOCKED` (The offset-bearing timestamp)

**The guard lives in `strip_iso_text`, once, and every port inherits it.** The ports already must call that function or be refused at render (`dialects/base.py:305`), so this is the one place where "every target got the fix" is enforced by something other than memory. A per-port guard would land three times and drift in the copy no tier runs — the failure `logs/T-0012.md` F-1 recorded with D34's partition clause, forty lines from a lowering that had the right shape.

- Paths: `src/bloomery/dialects/base.py` `tests/unit/test_dialects/test_duckdb.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0052/D-4 — `ASSUMED` (The offset-bearing timestamp)

**A `Z` suffix is kept and truncated as it is today.** `Z` names UTC, the target type *is* UTC and zoneless, so the wall clock and the instant are the same number and nothing is lost — where a numeric offset loses exactly the difference between them. Not `LOCKED`, because the reasoning holds only while no `to_utc:` follows in the chain (§5.2): with one, the author has declared a zone the data contradicts, and that case stays wrong. Departing here means refusing `Z` too, which needs §8's door built first — there is otherwise no legal spelling for the commonest bronze timestamp there is.

- Paths: `src/bloomery/dialects/base.py`

### S-0052/D-5 — `ASSUMED` (The offset-bearing timestamp)

**Detection is `SUBSTRING(x, 11)` plus two `LIKE`s, not a regex.** Portable with no per-port spelling and no escaping dialect, and correct for every ISO 8601 form these engines parse: the ten-character calendar date is the only place a `-` can appear innocently. Departing means a regex, and the cost of departing is three function names — `regexp_like`, `regexp_matches`, `~` — for the same boolean.

- Paths: `src/bloomery/dialects/base.py` `tests/engines/test_zoneless_utc.py`

### S-0052/D-6 — `ASSUMED` (The offset-bearing timestamp)

**F-9's framing is corrected in the record: the truncation is uniform across PostgreSQL, Trino and DuckDB, not a Trino divergence.** It matters because it decides where the fix may live: a real divergence would belong in `dialects/trino.py`, and shipping it there would have left the other two ports wrong while a green engine tier said otherwise. *Recorded here rather than by amending the log, which is append-only.*

- Paths: `src/bloomery/dialects/base.py`

### S-0055/D-13 — `ASSUMED` (Multi-grain aggregate-then-join query planning)

*(superseded by D18.)* **Null-safe key equality, one key row per group, no re-aggregation pass.** Groups missing from a branch surface as NULL measures, not as dropped rows, and a NULL group key joins to the other branch's NULL group key rather than failing `NULL = NULL` and splitting in two. MetricFlow's own combine node merges that split afterwards with `GROUP BY COALESCE(…)` and `MAX(…)`; composing the join ourselves means never making the split. `ASSUMED` rather than `LOCKED`: a caller who wants missing groups dropped is asking for an inner join, which is a later option on the same node, not a different design.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/planner/compose.py` `tests/unit/test_planner/test_compose.py`

<!-- /torve:managed -->
