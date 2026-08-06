# RFC 0014 — Hydration and caching of the planner artifact

- **Status:** 📝 Draft
- **Scope:** `bloomery/runtime/hydration.py`: the `HydrationKey`, the pure L2 codec
  (`build_manifest_bytes` / `hydrate_manifest`), the `ManifestHydrator` Protocol and its
  default `LruManifestHydrator`, the revised hydration budgets asserted in
  `tests/bench/test_hydration.py`, and the import-linter rule keeping `runtime/` out of the
  compile path. Supersedes RFC 0012 (`CompiledSemantic`): the planner artifact is now
  MetricFlow's own transformed manifest, not a bespoke dataclass. Does not cover manifest
  emission (RFC 0013) or L2 storage — Redis/control-plane I/O is the caller's, per hard
  invariant #1.
- **Related:** [`_bloomery-metricflow-pivot.md`](_bloomery-metricflow-pivot.md) §R5, §1.3,
  §6, §7 (V1/V3), §8; RFC 0003 (fingerprint, determinism), RFC 0009 (`perf` marker,
  `tests/bench/`), [RFC 0012](0012-compiled-semantic.md) (superseded — principles survive),
  RFC 0013 (MetricFlow backend; emitter determinism, M4.5).
- **Origin:** R5 of the MetricFlow pivot document, amending D5 of `_bloomery-changes.md`.

---

## 1. Summary

A two-level cache around MetricFlow's transformed manifest: L2 is the post-`transform()`
manifest JSON (~145 KB), keyed by `HydrationKey(spec_fingerprint, bloomery_version,
metricflow_version)` and stored by the caller; L1 is the hydrated `SemanticManifestLookup`
(~1.6 MB) in an in-process LRU inside `bloomery/runtime/`. Bloomery ships the key, the pure
build/parse functions, and the LRU — never the store. Budgets: 50 ms cold, 10 ms warm,
CI-asserted.

## 2. Motivation

RFC 0012's scaling argument stands: per-tenant planner state must be a per-request LRU entry,
not resident memory (contrast Cube's 5–40 MB/tenant residency). What changed is the artifact.
The MetricFlow pivot (R5) replaced the `NativePlanner` and with it the bespoke
`CompiledSemantic` projection — the thing the planner consumes at request time is now a
`SemanticManifestLookup` built from a `PydanticSemanticManifest`. Measured on a realistic
30-model / 90-metric tenant (pivot §1.3): `transform()` ~23 ms (build-time), `parse_raw`
~15 ms + `SemanticManifestLookup` ~13 ms (**~29 ms cold hydration**), ~1.6 MB resident per
hydrated tenant. Those numbers make the LRU model work — and they also bury RFC 0012's 5 ms
`loads` budget, which was set for a narrow dataclass, not a semantic graph. This RFC records
the honest replacement: 5 ms is not achievable and not needed, because the LRU absorbs the
cold cost.

## 3. Current state

`bloomery/runtime/` does not exist; RFC 0012's `bloomery/ir/semantic.py` was never built
(the RFC is superseded before implementation, so nothing is deleted). RFC 0003 pins
`project_fingerprint`; RFC 0009 reserves `tests/bench/` and the `perf` marker with the
hydration benchmark as its single asserted entry. RFC 0013 defines `emit_manifest(ir)` and
its determinism contract (sorted collections, golden `manifest.json` per fixture). The pivot
doc's reference implementation confirms `transform()` is mandatory before
`SemanticManifestLookup` and that the manifest exposes pydantic-v1-style `.json()` /
`.parse_raw()`.

## 4. Goals / Non-goals

**Goals**

- One cache key covering all three invalidation axes, including the MetricFlow version.
- Pure L2 codec: `ProjectIR → bytes` and `bytes → SemanticManifestLookup`, no I/O.
- A default in-process L1 (`LruManifestHydrator`) with configurable size and readable
  hit-rate.
- Revised budgets (50 ms cold / 10 ms warm) asserted in CI, replacing RFC 0012 §6.

**Non-goals**

- L2 storage, eviction, or transport — Redis/control-plane concerns; bloomery defines the
  key and the bytes only (hard invariant #1, no I/O — unchanged from RFC 0012).
- Manifest determinism — that is RFC 0013's emitter contract; this RFC owns key, budgets,
  and LRU.
- A stable cross-version artifact format — the survivor doctrine from RFC 0012: specs are
  durable, artifacts are cache; on any version change, rebuild from specs.

## 5. Design

### 5.1 Key and codec

```python
# bloomery/runtime/hydration.py

@dataclass(frozen=True, slots=True)
class HydrationKey:
    spec_fingerprint: str     # project_fingerprint(ir) — RFC 0003 D3
    bloomery_version: str
    metricflow_version: str   # NEW vs RFC 0012 — a MetricFlow bump invalidates every entry

def hydration_key(ir: ProjectIR) -> HydrationKey: ...

def build_manifest_bytes(ir: ProjectIR, *, naming: NamingPolicy) -> bytes:
    """emit_manifest (RFC 0013) → PydanticSemanticManifestTransformer.transform → .json().
    Pure; ~23 ms transform on the reference tenant."""

def hydrate_manifest(data: bytes) -> SemanticManifestLookup:
    """parse_raw + SemanticManifestLookup. No transform — L2 stores POST-transform."""
```

Storing the manifest **post-`transform()`** is load-bearing: it moves the ~23 ms transform
to build time, so cold hydration is exactly `parse_raw` + lookup construction (~29 ms
measured). Serialization uses MetricFlow's pydantic-v1-style `.json()` / `.parse_raw()`,
sorted keys where controllable. **Never pickle** — not deterministic, not version-safe —
the same rejection RFC 0012 recorded, restated because the temptation returns with a
pydantic object graph.

### 5.2 Two-level cache

| Level | Content | Cost | Where |
|---|---|---|---|
| L2 | post-`transform()` manifest JSON (~145 KB) | ~23 ms to build | caller's store (Redis / control plane), keyed by `HydrationKey` |
| L1 | hydrated `SemanticManifestLookup` (~1.6 MB) | ~29 ms from L2 bytes | in-process LRU in `bloomery/runtime/` |

```python
class ManifestHydrator(Protocol):
    def get(self, ir: ProjectIR) -> SemanticManifestLookup: ...

class LruManifestHydrator:
    def __init__(self, max_entries: int = 500,
                 fetch_l2: Callable[[HydrationKey], bytes | None] | None = None): ...
    def get(self, ir: ProjectIR) -> SemanticManifestLookup:
        # L1 hit → return (~budgeted 10 ms incl. keying).
        # Miss → fetch_l2(key) if provided (the CALLER's I/O, injected — bloomery
        # performs none) → hydrate_manifest; else build_manifest_bytes(ir) → hydrate.
    hits: int; misses: int          # plain counters — no metrics-framework dependency
    @property
    def hit_rate(self) -> float: ...
```

L1 sizing: ~1.6 MB/entry → 500 entries ≈ 800 MB; `max_entries` is the caller's knob, and
the hit-rate counter is a plain attribute the caller polls into whatever metrics system it
runs — bloomery takes no observability dependency.

### 5.3 Version mismatch is a miss, not an error

Because every version participates in the key, a bloomery or MetricFlow bump changes the
key, and the old entry is simply never looked up again — a cache **miss by construction**.
This retires RFC 0012's `IncompatibleArtifact`: that design put the version *inside* the
artifact and refused on load; this design puts it in the key, so the refusal path cannot be
reached. The doctrine is identical (never migrate, rebuild from specs); only the mechanism
moved from load-time check to key construction. `IncompatibleArtifact` is not declared in
`errors.py`.

### 5.4 Purity honesty: the LRU is process-global mutable state

The LRU is mutable state inside an otherwise pure library. This is deliberate and confined:
`bloomery/runtime/` is the one impure-*adjacent* package — it still performs no I/O (the
only I/O seam is the injected `fetch_l2`, owned and executed by the caller), but it holds
memory across calls because the 29 ms cold-hydration cost is the entire reason the package
exists. The confinement is mechanical, not conventional: an import-linter contract forbids
anything in the compile path (`spec/`, `ir/`, `resolve/`, `typing/`, `guardrails/`,
`transforms/`, `marts/`, `plan/`, `emit/`) from importing `bloomery/runtime/`. Only
`planner/` (request time) may.

### 5.5 Budgets

**50 ms cold / 10 ms warm**, replacing RFC 0012's 5 ms. The 5 ms target is recorded as
**not achievable and not needed**: measured cold cost is dominated by MetricFlow's own
`parse_raw` + graph build, and the per-request LRU model survives because the warm path —
the common case — is a dict hit.

**V3 verified (2026-08-07,
[`spikes/metricflow/VERIFICATION.md`](../spikes/metricflow/VERIFICATION.md)) — budgets
CONFIRMED, kept as-is.** Measured on the reference tenant (30 semantic models / 90 metrics,
144.9 KB payload), median of 25 runs: **cold hydration 10.5 ms** (`parse_raw` 5.7 ms +
`SemanticManifestLookup` 4.5 ms), **~19 ms worst-case** including the lazy first-`explain()`
tail (`SemanticManifestLookup` defers ~6 ms of graph work to the first query),
**1.54 MB/lookup** (confirms §5.2 L1 sizing). Both budgets hold with **≥4× headroom** even
counting the lazy tail; extrapolation is roughly linear (~35 ms cold at 100 models), still
inside budget. Two additions: the §6 bench suite gains a **3× model-size point**, and
hydration should optionally issue one **throwaway `explain()`** to absorb the
lazy-initialization tail before a lookup is marked warm (pre-warm note — cheap, and it
keeps first-query latency out of the warm path).

## 6. Tests

`tests/bench/test_hydration.py` (RFC 0009 `tests/bench/`, `-m perf`, scheduled lane):
median over N=50 `time.perf_counter` iterations, documented relaxed CI multiplier (3×),
asserting cold `hydrate_manifest` < 50 ms and warm `LruManifestHydrator.get` < 10 ms on the
reference tenant fixture (built programmatically via RFC 0013's emitter), **plus a 3×
model-size point** (~90 models) to keep the roughly-linear extrapolation V3 measured
honest as tenants grow. Unit: key changes
on each of the three components; LRU evicts at `max_entries`; hit/miss counters; miss path
falls back to build when `fetch_l2` is absent or returns `None`. Round-trip:
`hydrate_manifest(build_manifest_bytes(ir))` accepts every fixture manifest. Byte-level
determinism of `build_manifest_bytes` is asserted under RFC 0013's golden/emitter suites,
not re-tested here.

## 7. Docs

API reference for `HydrationKey`, the codec pair, `ManifestHydrator`/`LruManifestHydrator`,
with the caller contract stated plainly: L2 storage is yours; the bytes are not a stable
export format; on key mismatch you will simply miss — rebuild from specs and overwrite.

## 8. Out of scope

- **Pre-warming on tenant login** — enters scope only if V3 measures cold hydration
  > 150 ms at real scale (pivot §7); named as the escape hatch, not built. *(V3 measured
  10.5 ms — the trigger is nowhere near met; stays out of scope. Distinct and in scope: the
  §5.5 optional throwaway-`explain()` pre-warm inside hydration, which absorbs the lazy
  first-query tail, not the cold cost.)*
- **L2 compression** — the caller may gzip its store entries; bloomery hands over bytes.
- **Saved-query caching** (`PydanticSavedQuery`) — pivot open question #5, deferred past M11.

## 9. Risks

- *Hydration cost at real tenant scale.* 30 models measured; some tenants will be bigger.
  Gated by **V3** (largest constructible real tenant; >150 ms cold triggers the §8
  pre-warming escape hatch). This RFC's budgets are provisional until V3 reports.
  **RESOLVED (V3 PASS, 2026-08-07):** 10.5 ms cold measured, ≥4× headroom, budgets no
  longer provisional (§5.5); the 3× bench point watches for larger-tenant growth.
- *pydantic v1/v2 coexistence.* MetricFlow's v1-shim `.json()`/`.parse_raw()` alongside
  bloomery's v2 models — gated by **V1** (RFC 0013 M4.5). Blocking everything here.
  **RESOLVED (V1 PASS, 2026-08-07):** coexistence verified on Python 3.12/3.13/3.14 in
  both import orders; manifests round-trip through `.json()`/`.parse_raw()`.
- *`.json()` key ordering not fully controllable* → L2 bytes could differ across producers
  for one manifest. Contained: the cache key is the spec fingerprint, not a hash of the
  bytes, so equal-but-reordered bytes cost nothing at lookup; byte determinism remains
  RFC 0013's contract to tighten.
- *The LRU read as license for state elsewhere.* Mitigated mechanically: the §5.4
  import-linter contract, plus the RFC 0003 §5.5 rules still applying package-wide.

## 10. Unresolved questions

- V1 and V3 outcomes (RFC 0013 M4.5) — they gate the budget numbers and the pre-warming
  decision, not the design shape. Implementation is free to settle `fetch_l2` ergonomics
  and the exact counter surface. **Answered (2026-08-07): V1 and V3 both PASS**
  ([`spikes/metricflow/VERIFICATION.md`](../spikes/metricflow/VERIFICATION.md)); budgets
  confirmed (§5.5), login-time pre-warming stays out of scope (§8).

## 11. Decisions

| # | Decision |
| --- | --- |
| 1 | Supersedes RFC 0012: the planner artifact is MetricFlow's own transformed manifest, not a bespoke `CompiledSemantic`. Survivors carried over: deterministic serialization, version-mismatch-refuses-never-migrates, the LRU-instead-of-resident-memory scaling argument, and specs-are-durable / artifacts-are-cache. |
| 2 | `HydrationKey(spec_fingerprint, bloomery_version, metricflow_version)` — the `metricflow_version` component is new; a MetricFlow bump invalidates every cache entry. |
| 3 | Two-level cache: L2 = post-`transform()` manifest JSON (~145 KB, ~23 ms to build) in the **caller's** store — bloomery defines only the key and the bytes (no I/O, hard invariant #1) via pure `build_manifest_bytes` / `hydrate_manifest`; L1 = hydrated `SemanticManifestLookup` (~1.6 MB, ~29 ms from L2) in an in-process LRU (`ManifestHydrator` Protocol + `LruManifestHydrator(max_entries=...)`). Post-transform storage makes hydration `parse_raw` + lookup only. |
| 4 | Budgets: **50 ms cold / 10 ms warm**, asserted in `tests/bench/test_hydration.py` (median over N iterations, relaxed CI multiplier, `perf` marker — RFC 0009). RFC 0012's 5 ms is recorded as not achievable and not needed; the LRU absorbs the ~29 ms measured cold cost. |
| 5 | Serialization via MetricFlow's pydantic-v1-style `.json()` / `.parse_raw()`, sorted keys where controllable; never pickle (not deterministic, not version-safe). Manifest determinism is RFC 0013's emitter contract; this RFC owns key + budgets + LRU. |
| 6 | L1 sizing: ~1.6 MB/entry → 500 entries ≈ 800 MB; `max_entries` configurable; hit-rate exposed as a plain counter/attribute the caller reads — no metrics-framework dependency. |
| 7 | Version mismatch is a cache **miss by construction** (the key changes), never an error — RFC 0012's `IncompatibleArtifact` is retired with it; the load-time refusal path cannot be reached because versions live in the key, not the artifact. |
| 8 | The LRU is confined mutable state: `runtime/` is the one impure-adjacent package (no I/O; `fetch_l2` is caller-owned), kept out of the compile pipeline by an import-linter contract — nothing in the compile path imports `runtime/`. |
| 9 | **V3 verified (2026-08-07):** budgets **confirmed and kept** at 50 ms cold / 10 ms warm — measured cold hydration 10.5 ms median (`parse_raw` 5.7 ms + lookup 4.5 ms; ~19 ms worst-case with the lazy first-`explain()` tail), 1.54 MB/lookup at 30 models / 90 metrics / 144.9 KB payload, ≥4× headroom. Two additions: the bench suite gains a 3× model-size point, and hydration may issue one optional throwaway `explain()` to absorb the lazy-initialization tail before a lookup counts as warm ([`spikes/metricflow/VERIFICATION.md`](../spikes/metricflow/VERIFICATION.md)). |

## 12. Phasing

Ships as pivot milestone **M8** (R5): key, codec, `LruManifestHydrator`, and the benchmark
land together — done when 50 ms cold / 10 ms warm is asserted in CI. Gated on RFC 0013's
M4.5 verification tasks **V1** (dependency coexistence — blocking everything) and **V3**
(hydration at real scale — blocking the budget numbers; >150 ms cold pulls §8 pre-warming
into scope) — **both gates cleared 2026-08-07 (V1/V3 PASS, §10)**. Depends on RFC 0013's
`emit_manifest` for the build path.
