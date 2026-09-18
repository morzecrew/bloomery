<!-- torve:managed tests/fixtures/dirty — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/dirty/`

### S-0033/D-1 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

The governing principle: **specs describe, specs reference implementations, specs never contain implementations.** Bronze gets no cleansing (replay source); gold gets none (rebuildable).

- Paths: `src/bloomery/spec/quality.py` `tests/fixtures/dirty/README.md` `tests/golden/schema/mapping.json`

### S-0033/D-21 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Ingestion metadata contract: entities using `quarantine` or `dedupe` require bronze `_load_id`, `_ingested_at`, `_source_row_id` (a stable per-source-row identity supplied by the ingestion layer, **NOT NULL and unique per source row** — data properties no compiler can check, so the lowering emits a generated **blocking audit** on the metadata columns: a null or duplicated `_source_row_id` stops the run); column absence is the new compile error `IngestionMetadataMissing` (`GuardrailError` leaf, `errors.py` per S-0019/D-3). `reject_id` = sha256 over the length-prefixed utf-8 **pair** (`source_relation`, `_source_row_id`) — canonical serialization per the S-0020 canon-bytes doctrine. This supersedes the triple this row first carried (this round's own earlier decision): `_load_id` is removed from the identity and becomes an attribute (the latest observing load) — re-deliveries of the same source row across loads must land on the **same** reject row (that is what `first_seen`/`last_seen` track); a per-load identity would mint a new row per retry and violate replay idempotence. A re-delivery updates `last_seen`/`_load_id`/`failed_rules` on the existing row.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/quality.py` `src/bloomery/quality/catalogue.py` `src/bloomery/quality/dedupe.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/transforms/_builtins.py` `tests/e2e/test_dbt_parse.py` `tests/e2e/test_sqlmesh_project.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_dedupe_and_audits.py` `tests/execution/test_merged_cleaning.py` `tests/execution/test_zoneless_utc.py` `tests/fixtures/dirty/README.md` `tests/fixtures/semi_additive_inventory/mapping.yaml` `tests/support/execution.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_trino.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_entity.py`

### S-0033/D-85 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **The corpus has a `range` specimen, and it is a pair. D28 is closed.** D28 recorded that no corpus row casts cleanly and *then* violates a declared bound, so `range` was lowered, matrixed, and reported in the quality mart while diverting nothing anywhere in the corpus. The scope of that gap is narrower than the sentence sounds and worth stating exactly: `range` *was* live at execution, in the `quality_precedence` fixture at `on_fail: fail`, where it blocks a run rather than diverting a row. What had no specimen was the **quarantine** side — the two-way split, the reject row, the conservation accounting — which is the side the rest of this RFC is built around. `keys.csv` gains a **pair**, not a row, because one row cannot pin a bound: `amount_at_range_min` (`0.000000000`) and `amount_below_range_min` (`-0.000000001`) are one ulp apart with opposite dispositions, so `min` lowering to `col <= min` instead of `col < min` becomes a test failure rather than a silently over-eager quarantine. A chaos mutation that drops the `min` bound entirely was written and then **removed**: measured against the pre-D28 corpus it was already caught by `test_quality_precedence`, so it detects nothing the battery could not already see, and a mutation that adds no detection inflates the battery without strengthening it. Recorded because the measurement contradicted the reason for adding it.

- Paths: `tests/fixtures/dirty/README.md`

<!-- /torve:managed -->
