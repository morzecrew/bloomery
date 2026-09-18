<!-- torve:managed tests/unit/test_dialects — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/unit/test_dialects/`

### S-0020/D-2 — `ASSUMED` (Intermediate representation and determinism contract)

SQL is stored in the IR as canonical dialect-neutral SQLGlot text (`SqlExpr`), re-parsed at emit. Consequence: SQLGlot version changes can change fingerprints; the exact pin (D4 §5.5) makes that a deliberate event.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/emit/lower/marts.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `src/bloomery/transforms/_builtins.py` `tests/support/type_conformance.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_postgres.py` `tests/unit/test_transforms/test_builtins.py` `tests/unit/test_transforms/test_type_conformance_corpus.py`

### S-0025/D-1 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Three independent ports (`TargetEmitter`, `DialectPort`, `NamingPolicy`), all `Protocol`s. Target and dialect never collapse into one adapter.

- Paths: `src/bloomery/dialects/__init__.py` `src/bloomery/dialects/base.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/naming.py` `src/bloomery/quality/flags.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_postgres.py`

### S-0025/D-5 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

v0.1 adapter set: SQLMesh + Cube + dbt targets; DuckDB + Postgres + Trino dialects. dbt is a port-abstraction proof, documented as such.

- Paths: `src/bloomery/compile.py` `src/bloomery/dialects/duckdb.py` `src/bloomery/dialects/postgres.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/runtime/sql_client.py` `tests/unit/test_dialects/test_duckdb.py` `tests/unit/test_dialects/test_postgres.py` `tests/unit/test_dialects/test_trino.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_runtime/test_sql_client.py`

### S-0025/D-8 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Emitter/dialect registries mirror the transform registry: immutable defaults + explicit overlay, collision is an error, iteration sorted (S-0021/D-6).

- Paths: `src/bloomery/dialects/__init__.py` `src/bloomery/emit/__init__.py` `src/bloomery/runtime/sql_client.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_emit/test_base.py`

### S-0033/D-9 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Silver gains `_quality_flags`/`_quality_ok`; marts gain `has_quality_flags` (S-0027 amendment). Array capability is `DialectFeature.ARRAY` — an engine property, deliberately diverging from Document 5's `TargetCapabilities` placement; dialects without it lower to a delimited string.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/marts/flatten.py` `src/bloomery/spec/common.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_steps/test_lowering.py`

### S-0033/D-21 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Ingestion metadata contract: entities using `quarantine` or `dedupe` require bronze `_load_id`, `_ingested_at`, `_source_row_id` (a stable per-source-row identity supplied by the ingestion layer, **NOT NULL and unique per source row** — data properties no compiler can check, so the lowering emits a generated **blocking audit** on the metadata columns: a null or duplicated `_source_row_id` stops the run); column absence is the new compile error `IngestionMetadataMissing` (`GuardrailError` leaf, `errors.py` per S-0019/D-3). `reject_id` = sha256 over the length-prefixed utf-8 **pair** (`source_relation`, `_source_row_id`) — canonical serialization per the S-0020 canon-bytes doctrine. This supersedes the triple this row first carried (this round's own earlier decision): `_load_id` is removed from the identity and becomes an attribute (the latest observing load) — re-deliveries of the same source row across loads must land on the **same** reject row (that is what `first_seen`/`last_seen` track); a per-load identity would mint a new row per retry and violate replay idempotence. A re-delivery updates `last_seen`/`_load_id`/`failed_rules` on the existing row.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/quality.py` `src/bloomery/quality/catalogue.py` `src/bloomery/quality/dedupe.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/transforms/_builtins.py` `tests/e2e/test_dbt_parse.py` `tests/e2e/test_sqlmesh_project.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_dedupe_and_audits.py` `tests/execution/test_merged_cleaning.py` `tests/execution/test_zoneless_utc.py` `tests/fixtures/dirty/README.md` `tests/fixtures/semi_additive_inventory/mapping.yaml` `tests/support/execution.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_trino.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_entity.py`

### S-0033/D-56 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **The dialects a `pattern` is checked against are the shipped ports, never the registry.** `registered_dialects()` is process-global and mutable, so an extension dialect registered by an unrelated import could decide whether an existing project compiles — the ambient dependency S-0020 exists to forbid, and one no golden would catch. The checked set is the constant `PATTERN_TARGET_DIALECTS = (duckdb, postgres, trino)`, overridable by an explicit argument the caller supplies. Recorded consequence: an extension dialect is no longer checked at compile time. Checking it would mean plumbing a dialect set into `build_project_ir`, which is dialect-free by construction and right to be — a project is portable or it is not, and the guardrail stage has no target. Named as the escape hatch, not built.

- Paths: `pages/docs/how-to/add-quality-rules.md` `src/bloomery/compile.py` `src/bloomery/dialects/__init__.py` `src/bloomery/quality/pattern.py` `tests/unit/test_compile.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_quality/test_edges.py`

### S-0045/D-5 — `LOCKED` (`timestamp` is zoneless UTC, on every port)

The check exists, and it is a **conformance battery at the engine tiers over the transform registry** — not an emit-time assertion. Emit has no engine to ask and no usable static model of one; and a type-shaped check at emit invites a cast-shaped fix, which would have made this defect's type right and its value no less wrong. §7 has the measurement.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/postgres.py` `tests/engines/test_postgres_spellings.py` `tests/engines/test_type_conformance.py` `tests/execution/test_type_conformance.py` `tests/support/type_conformance.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_transforms/test_type_conformance_corpus.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0052/D-3 — `LOCKED` (The offset-bearing timestamp)

**The guard lives in `strip_iso_text`, once, and every port inherits it.** The ports already must call that function or be refused at render (`dialects/base.py:305`), so this is the one place where "every target got the fix" is enforced by something other than memory. A per-port guard would land three times and drift in the copy no tier runs — the failure `logs/T-0012.md` F-1 recorded with D34's partition clause, forty lines from a lowering that had the right shape.

- Paths: `src/bloomery/dialects/base.py` `tests/unit/test_dialects/test_duckdb.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
