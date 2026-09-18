<!-- torve:managed tests/unit/test_runtime — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/unit/test_runtime/`

### S-0025/D-5 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

v0.1 adapter set: SQLMesh + Cube + dbt targets; DuckDB + Postgres + Trino dialects. dbt is a port-abstraction proof, documented as such.

- Paths: `src/bloomery/compile.py` `src/bloomery/dialects/duckdb.py` `src/bloomery/dialects/postgres.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/runtime/sql_client.py` `tests/unit/test_dialects/test_duckdb.py` `tests/unit/test_dialects/test_postgres.py` `tests/unit/test_dialects/test_trino.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_runtime/test_sql_client.py`

### S-0031/D-2 — `ASSUMED` (Hydration and caching of the planner artifact)

`HydrationKey(spec_fingerprint, bloomery_version, metricflow_version)` — the `metricflow_version` component is new; a MetricFlow bump invalidates every cache entry.

- Paths: `src/bloomery/runtime/hydration.py` `tests/unit/test_runtime/test_hydration.py`

### S-0031/D-3 — `ASSUMED` (Hydration and caching of the planner artifact)

Two-level cache: L2 = post-`transform()` manifest JSON (~145 KB, ~23 ms to build) in the **caller's** store — bloomery defines only the key and the bytes (no I/O, hard invariant #1) via pure `build_manifest_bytes` / `hydrate_manifest`; L1 = hydrated `SemanticManifestLookup` (~1.6 MB, ~29 ms from L2) in an in-process LRU (`ManifestHydrator` Protocol + `LruManifestHydrator(max_entries=...)`). Post-transform storage makes hydration `parse_raw` + lookup only.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/runtime/hydration.py` `tests/unit/test_runtime/test_hydration.py`

### S-0031/D-5 — `ASSUMED` (Hydration and caching of the planner artifact)

Serialization via MetricFlow's pydantic-v1-style `.json()` / `.parse_raw()`, sorted keys where controllable; never pickle (not deterministic, not version-safe). Manifest determinism is S-0030's emitter contract; this RFC owns key + budgets + LRU.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/runtime/hydration.py` `tests/unit/test_runtime/test_hydration.py`

### S-0031/D-6 — `ASSUMED` (Hydration and caching of the planner artifact)

L1 sizing: ~1.6 MB/entry → 500 entries ≈ 800 MB; `max_entries` configurable; hit-rate exposed as a plain counter/attribute the caller reads — no metrics-framework dependency.

- Paths: `src/bloomery/runtime/hydration.py` `tests/unit/test_runtime/test_hydration.py`

### S-0031/D-7 — `ASSUMED` (Hydration and caching of the planner artifact)

Version mismatch is a cache **miss by construction** (the key changes), never an error — S-0029's `IncompatibleArtifact` is retired with it; the load-time refusal path cannot be reached because versions live in the key, not the artifact.

- Paths: `src/bloomery/runtime/hydration.py` `tests/unit/test_runtime/test_hydration.py`

<!-- /torve:managed -->
