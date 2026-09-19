<!-- torve:managed src/bloomery/transforms — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/transforms/`

### S-0020/D-2 — `ASSUMED` (Intermediate representation and determinism contract)

SQL is stored in the IR as canonical dialect-neutral SQLGlot text (`SqlExpr`), re-parsed at emit. Consequence: SQLGlot version changes can change fingerprints; the exact pin (D4 §5.5) makes that a deliberate event.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/emit/lower/marts.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `src/bloomery/transforms/_builtins.py` `tests/support/type_conformance.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_postgres.py` `tests/unit/test_transforms/test_builtins.py` `tests/unit/test_transforms/test_type_conformance_corpus.py`

### S-0020/D-5 — `ASSUMED` (Intermediate representation and determinism contract)

Floats are banned in IR and emission; `Decimal`/int only.

- Paths: `src/bloomery/cli/serialize.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/steps.py` `src/bloomery/ir/fingerprint.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/request.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/common.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `src/bloomery/steps/manifest.py` `src/bloomery/steps/splice.py` `src/bloomery/transforms/_builtins.py` `src/bloomery/typing/types.py` `tests/execution/test_as_of_join.py` `tests/execution/test_currency_convert.py` `tests/execution/test_fanout_trap.py` `tests/execution/test_marts.py` `tests/execution/test_period_over_period.py` `tests/execution/test_rollup.py` `tests/fixtures/semantic_corpus/002-average-of-averages/naive.sql` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/golden/schema/marts.json` `tests/support/planning.py` `tests/support/semantic_corpus.py` `tests/unit/test_cli.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_planner/test_request.py` `tests/unit/test_quality/test_edges.py` `tests/unit/test_spec/test_metrics.py` `tests/unit/test_spec/test_quality.py` `tests/unit/test_steps/test_lowering.py` `tests/unit/test_steps/test_manifest_and_registry.py` `tests/unit/test_typing/test_types.py`

### S-0021/D-3 — `ASSUMED` (Logical types and the transform registry)

Starter set is exactly: `trim upper lower to_string to_int to_decimal to_bool parse_ts parse_date to_utc enum_map coalesce nullif split_part regex_extract strip_prefix strip_suffix multiply divide round abs concat json_path`, plus `convert` as the explicit currency-conversion marker required by the currency guardrail (S-0023).

- Paths: `src/bloomery/transforms/_builtins.py` `tests/unit/test_transforms/test_builtins.py` `tests/unit/test_transforms/test_registry.py`

### S-0021/D-6 — `ASSUMED` (Logical types and the transform registry)

`register_transform(spec)` is public API; the default registry is a module-level immutable mapping built at import, extensions live in a process-global overlay, name collisions are errors, and all registry iteration is sorted by name. Consequence: determinism is scoped to a fixed installed extension set.

- Paths: `src/bloomery/steps/registry.py` `src/bloomery/transforms/__init__.py` `src/bloomery/transforms/registry.py`

### S-0021/D-7 — `ASSUMED` (Logical types and the transform registry)

Transform builders produce SQLGlot AST only — never string formatting. Dialect rendering happens at emit (S-0025); dialect incapability is an emit-time `DialectPort` feature failure, never a typing concern.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/steps/splice.py` `src/bloomery/transforms/_builtins.py` `tests/unit/test_steps/test_splice.py`

### S-0025/D-3 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Capability mismatch behavior is fail-loud: `UnsupportedByTarget` naming entity + feature. Silent degradation is forbidden.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/spec/quality.py` `src/bloomery/transforms/_builtins.py` `tests/property/test_compile_properties.py` `tests/unit/test_emit/test_base.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_quality/test_text_rules.py` `tests/unit/test_transforms/test_builtins.py`

### S-0025/D-7 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Quarantine is an emitter convention (`<entity>__quarantine` artifact), not IR surface (settles #5; revisit on a second policy consumer).

- Paths: `src/bloomery/spec/mapping.py` `src/bloomery/transforms/_builtins.py`

### S-0033/D-3 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Coercion failure is a rule: transform chains lower to failure-marker form (`TRY_CAST`-style per dialect); the implicit, overridable `coercible` rule (default `quarantine`) disposes of it. Retires `Mapping.on_unmapped_enum` (S-0019 amendment — absorbed into `in_enum`/`coercible`) and supersedes S-0025/D-7's never-implemented emitter convention with the modeled reject table.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/guardrails/operands.py` `src/bloomery/quality/predicates.py` `src/bloomery/spec/mapping.py` `src/bloomery/spec/quality.py` `src/bloomery/transforms/_builtins.py` `tests/execution/test_path_conflict.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_spec/test_mapping.py`

### S-0033/D-21 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Ingestion metadata contract: entities using `quarantine` or `dedupe` require bronze `_load_id`, `_ingested_at`, `_source_row_id` (a stable per-source-row identity supplied by the ingestion layer, **NOT NULL and unique per source row** — data properties no compiler can check, so the lowering emits a generated **blocking audit** on the metadata columns: a null or duplicated `_source_row_id` stops the run); column absence is the new compile error `IngestionMetadataMissing` (`GuardrailError` leaf, `errors.py` per S-0019/D-3). `reject_id` = sha256 over the length-prefixed utf-8 **pair** (`source_relation`, `_source_row_id`) — canonical serialization per the S-0020 canon-bytes doctrine. This supersedes the triple this row first carried (this round's own earlier decision): `_load_id` is removed from the identity and becomes an attribute (the latest observing load) — re-deliveries of the same source row across loads must land on the **same** reject row (that is what `first_seen`/`last_seen` track); a per-load identity would mint a new row per retry and violate replay idempotence. A re-delivery updates `last_seen`/`_load_id`/`failed_rules` on the existing row.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/quality.py` `src/bloomery/quality/catalogue.py` `src/bloomery/quality/dedupe.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/transforms/_builtins.py` `tests/e2e/test_dbt_parse.py` `tests/e2e/test_sqlmesh_project.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_dedupe_and_audits.py` `tests/execution/test_merged_cleaning.py` `tests/execution/test_zoneless_utc.py` `tests/fixtures/dirty/README.md` `tests/fixtures/semi_additive_inventory/mapping.yaml` `tests/support/execution.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_trino.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_entity.py`

### S-0040/D-4 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

`convert` raises `UnsupportedByTarget` at **emit**, on all three dialects. It stays a registered transform with an unchanged typecheck, so the spec surface does not move and a future dialect clears the refusal by declaring a `Feature` — the mechanism S-0025 already provides.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/evidence.py` `src/bloomery/resolve/build.py` `src/bloomery/transforms/_builtins.py` `tests/fixtures/currency_convert_refusal/entity_model.yaml` `tests/support/type_conformance.py` `tests/unit/test_emit/test_currency_convert.py` `tests/unit/test_evidence.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0040/D-11 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

The FX rate relation declares **both** interval ends (`valid_from` and `valid_to`), never `valid_from` alone. One end is not an interval: a fact row would match every rate at or before its anchor and the conversion would fan out. Deriving the upper bound with `LEAD(valid_from)` is rejected — it makes every conversion a window function over the whole rate table, and it extends the newest rate to infinity, so a stale feed converts at last week's rate instead of failing. Consequence: a gap in the rate table is a *miss*, taking D9's `unknown_member` disposition, rather than silently resolving to a neighbour.

- Paths: `src/bloomery/transforms/_builtins.py` `tests/execution/test_currency_convert.py` `tests/fixtures/currency_convert/catalog.yaml` `tests/unit/test_emit/test_currency_convert.py` `tests/unit/test_quality/test_lower.py` `tests/unit/test_spec/test_catalog.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

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

### S-0044/D-6 — `ASSUMED` (ISO 8601 timestamps across dialects)

`parse_date: ISO8601` is in scope with `parse_ts`. It lowers the same way, to `CAST(… AS DATE)`, and a date has no `T` — but the two are one branch in one builder, and fixing one while leaving the other reads as an oversight rather than a boundary.

- Paths: `src/bloomery/transforms/_builtins.py` `tests/unit/test_transforms/test_builtins.py`

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

### S-0046/D-1 — `ASSUMED` (Transform types the engine agrees with)

A builder is told its **input logical type**. `Builder` becomes `(input type, column AST, *args) -> AST` or gains it by keyword; the declaration and the construction then read the same fact. This is the enabling change for §2.1 and §2.2.

- Paths: `src/bloomery/resolve/build.py` `src/bloomery/transforms/registry.py` `tests/support/type_conformance.py` `tests/unit/test_transforms/test_registry.py`

### S-0046/D-2 — `ASSUMED` (Transform types the engine agrees with)

Arithmetic transforms **narrow their own result** to the type they declare, rather than leaving it to `build.py`'s terminal cast — which only fires when the chain's terminal type differs from the field's, and so never fires for a chain ending in `multiply`.

- Paths: `src/bloomery/transforms/_builtins.py` `tests/unit/test_transforms/test_builtins.py`

### S-0046/D-3 — `ASSUMED` (Transform types the engine agrees with)

`divide` carries a **neutral-text marker**, the pattern S-0044/D-4 established for `parse_ts`, because a flag on the node does not survive the round trip and re-reading every `Div` at render would change integer division in metric expressions.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/transforms/_builtins.py`

### S-0046/D-5 — `OPEN` (Transform types the engine agrees with)

Whether `to_bool`/`to_int` across the boolean boundary get a PostgreSQL spelling (`x::int::boolean`) or a refusal. A spelling is cheap; a refusal is honest about `to_bool` over an arbitrary integer having no agreed meaning.

- Paths: `src/bloomery/transforms/_builtins.py` `tests/unit/test_transforms/test_builtins.py`

### S-0052/D-1 — `LOCKED` (The offset-bearing timestamp)

**`parse_ts: ISO8601` reads a local wall clock, and text carrying a numeric UTC offset is out of contract.** This is S-0045's contract restated at the boundary that enforces it, not a new rule: `to_utc` is the only door into UTC, so a value that states its own zone is telling the compiler something the declaration already claimed to know. Locking it is what makes §5.3's refusal a consequence rather than a preference — an implementation that "helpfully" converted would be contradicting the spec layer, not extending it.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/transforms/_builtins.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0066/D-2 — `LOCKED` (Declared input currency for conversion)

**A currency is never inferred — not from a column name, a source path, or the data.** S-0038 closed inference for this class and S-0005/D-1 refuses `INFERRED_HEURISTIC` as a way to close an obligation. Locked because a guess here is indistinguishable at the call site from a declaration, which is the property that makes the guess dangerous rather than merely imprecise.

- Paths: `src/bloomery/guardrails/arithmetic.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/catalog.py` `src/bloomery/transforms/_builtins.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0076/D-1 — `LOCKED` (Declared source timezone)

**A zone is declared, never inferred.** Not from the column name, not from a project default, not from the values. An inferred zone is indistinguishable from a declared one once written down, and the failure it produces is a five-hour shift with full compiler blessing. Locked because every cheaper alternative is a way of making the wrong answer easier to reach than today.

- Paths: `src/bloomery/semantic/denomination.py` `src/bloomery/spec/mapping.py` `src/bloomery/transforms/_builtins.py` `src/bloomery/typing/types.py` `tests/fixtures/semantic_corpus/011-timezone-boundary/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0076/D-3 — `LOCKED` (Declared source timezone)

**`zone_in: UTC` is a declaration, not a no-op.** A feed whose wall clocks really are UTC says so. Today that claim is made by silence and silence cannot be checked; the key's only job is to turn an unfalsifiable default into a sentence somebody wrote.

- Paths: `src/bloomery/semantic/denomination.py` `src/bloomery/spec/mapping.py` `src/bloomery/transforms/_builtins.py` `src/bloomery/typing/types.py` `tests/fixtures/semantic_corpus/011-timezone-boundary/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
