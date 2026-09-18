<!-- torve:managed src/bloomery/runtime — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/runtime/`

### S-0004/D-2 — `LOCKED` (Observability: logging and a warnings channel)

A log record never carries nondeterminism of bloomery's making — no timestamp, id or counter the compiler invented — and is built only from values the pipeline already holds: stage names, counts, fingerprints and source paths

- Paths: `src/bloomery/spec/project.py` `src/bloomery/resolve/build.py` `src/bloomery/compile.py` `src/bloomery/runtime/hydration.py` `src/bloomery/planner/metricflow_planner.py`
- Consequence: A record's timestamp exists only if the caller's handler adds one, on the caller's side of the I/O boundary; the pre-commit bans on the clock and the id generator get no exemption for a logging call site
- Check: `uv run pytest tests/unit/test_determinism_guard.py -q` (shadow; runs as `decision:S-0004/D-2`, no log entry owed)

### S-0004/D-4 — `ASSUMED` (Observability: logging and a warnings channel)

Two levels only, to start — `INFO` for one bounded record per stage per compile and `DEBUG` for per-entity and per-artifact detail — and no record at `WARNING` or above anywhere, because that severity belongs to the advisory channel

- Paths: `src/bloomery/spec/project.py` `src/bloomery/resolve/build.py` `src/bloomery/compile.py` `src/bloomery/runtime/hydration.py` `src/bloomery/planner/metricflow_planner.py`
- Consequence: The INFO budget is pinned not to grow with the project, which is what "safe to leave on in production" has to mean to be worth saying; a third level costs a log line rather than a contract, which is why this is not `LOCKED`
- Check: `uv run pytest tests/unit/test_logging_posture.py -q` (shadow; runs as `decision:S-0004/D-4`, no log entry owed)

### S-0004/D-13 — `ASSUMED` (Observability: logging and a warnings channel)

Modules obtain their stage logger by the documented name literally — `bloomery.spec`, `bloomery.resolve`, `bloomery.guardrails`, `bloomery.emit`, `bloomery.runtime`, `bloomery.planner` — and never through `getLogger(__name__)`

- Paths: `src/bloomery/spec/project.py` `src/bloomery/resolve/build.py` `src/bloomery/compile.py` `src/bloomery/runtime/hydration.py` `src/bloomery/planner/metricflow_planner.py`
- Consequence: The two idioms ship different stable sets, and `__name__` would make the documented names a strict subset of the real ones; tuning works either way through the hierarchy, so what differs is only which names are the promise
- Check: `uv run pytest tests/unit/test_logging_posture.py -q` (shadow; runs as `decision:S-0004/D-13`, no log entry owed)

### S-0004/D-14 — `ASSUMED` (Observability: logging and a warnings channel)

`bloomery.runtime` records at DEBUG, not at INFO, until the bench lane says otherwise

- Paths: `src/bloomery/runtime/hydration.py`
- Consequence: Widening a level later is backward-compatible where narrowing one is not, so DEBUG is the end that cannot cause the chattiness Q-2 names as the risk
- Check: `uv run pytest tests/unit/test_logging_posture.py -q` (shadow; runs as `decision:S-0004/D-14`, no log entry owed)

### S-0025/D-5 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

v0.1 adapter set: SQLMesh + Cube + dbt targets; DuckDB + Postgres + Trino dialects. dbt is a port-abstraction proof, documented as such.

- Paths: `src/bloomery/compile.py` `src/bloomery/dialects/duckdb.py` `src/bloomery/dialects/postgres.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/runtime/sql_client.py` `tests/unit/test_dialects/test_duckdb.py` `tests/unit/test_dialects/test_postgres.py` `tests/unit/test_dialects/test_trino.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_runtime/test_sql_client.py`

### S-0025/D-8 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Emitter/dialect registries mirror the transform registry: immutable defaults + explicit overlay, collision is an error, iteration sorted (S-0021/D-6).

- Paths: `src/bloomery/dialects/__init__.py` `src/bloomery/emit/__init__.py` `src/bloomery/runtime/sql_client.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_emit/test_base.py`

### S-0030/D-1 — `ASSUMED` (MetricFlow backend: manifest emitter and planner adapter)

S-0028's hand-written lowering (algorithm steps 3–4: additivity lowering + SQLGlot assembly) and mart selection as its own module are **superseded**: MetricFlow (Apache 2.0, `metricflow==0.211.*` pinned tightly) is embedded as a render-only library — no dbt project, no adapter, no dbt-core, no execution. Verified: vendored semantic interfaces in the wheel; plain-Pydantic manifest constructible in code; `SqlClient` is a Protocol and `explain()` never executes (`RenderOnlySqlClient` raises `NotImplementedError` on query/execute/dry_run). Motivating numbers: ~29 ms cold hydration, ~1.6 MB/tenant vs Cube's 5–40 MB.

- Paths: `src/bloomery/runtime/sql_client.py`

### S-0031/D-1 — `ASSUMED` (Hydration and caching of the planner artifact)

Supersedes S-0029: the planner artifact is MetricFlow's own transformed manifest, not a bespoke `CompiledSemantic`. Survivors carried over: deterministic serialization, version-mismatch-refuses-never-migrates, the LRU-instead-of-resident-memory scaling argument, and specs-are-durable / artifacts-are-cache.

- Paths: `src/bloomery/runtime/hydration.py`

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

### S-0031/D-8 — `ASSUMED` (Hydration and caching of the planner artifact)

The LRU is confined mutable state: `runtime/` is the one impure-adjacent package (no I/O; `fetch_l2` is caller-owned), kept out of the compile pipeline by an import-linter contract — nothing in the compile path imports `runtime/`.

- Paths: `src/bloomery/runtime/hydration.py`

### S-0031/D-9 — `ASSUMED` (Hydration and caching of the planner artifact)

**V3 verified (2026-08-07):** budgets **confirmed and kept** at 50 ms cold / 10 ms warm — measured cold hydration 10.5 ms median (`parse_raw` 5.7 ms + lookup 4.5 ms; ~19 ms worst-case with the lazy first-`explain()` tail), 1.54 MB/lookup at 30 models / 90 metrics / 144.9 KB payload, ≥4× headroom. Two additions: the bench suite gains a 3× model-size point, and hydration may issue one optional throwaway `explain()` to absorb the lazy-initialization tail before a lookup counts as warm ([`spikes/metricflow/VERIFICATION.md`](spikes/metricflow/VERIFICATION.md)).

- Paths: `src/bloomery/runtime/hydration.py`

<!-- /torve:managed -->
