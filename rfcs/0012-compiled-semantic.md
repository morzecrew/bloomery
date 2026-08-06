# RFC 0012 — CompiledSemantic: serializable planner artifact

- **Status:** ❌ Superseded by [RFC 0014](0014-hydration-and-caching.md) — the MetricFlow pivot (_bloomery-metricflow-pivot.md R5) replaced the bespoke CompiledSemantic artifact with MetricFlow's transformed manifest; the surviving principles (deterministic serialization, never-migrate, LRU scaling) carry over to RFC 0014.
- **Scope:** `bloomery/ir/semantic.py`: the `CompiledSemantic` artifact — everything the
  `NativePlanner` (RFC 0011) needs and nothing else — plus `compile_semantic(ir)`,
  `dumps(cs) -> bytes`, `loads(data) -> CompiledSemantic`, the `IncompatibleArtifact` error
  (declared in `errors.py` per RFC 0002 D3), the widening of `NativePlanner.plan` to accept
  `ProjectIR | CompiledSemantic` (settling the input question RFC 0011 defers), and the
  hydration benchmark `tests/bench/test_hydration.py`. Does not cover mart modelling
  (RFC 0010), planning itself (RFC 0011), or IR serialization for external consumers — the
  RFC 0003 non-goal stands; this artifact is a private cache format.
- **Related:** [`_bloomery-changes.md`](_bloomery-changes.md) D5 (source), D1, D10 M6;
  RFC 0002 (errors), RFC 0003 (fingerprint, determinism), RFC 0009 (markers, property tier),
  RFC 0010 (mart IR), RFC 0011 (planner).
- **Origin:** D5 of the implementation-changes document; the Cube rejection analysis in its §0.

---

## 1. Summary

A frozen, deliberately narrow projection of `ProjectIR` that the planner consumes at request
time, serializable to canonical JSON bytes with `loads(dumps(cs)) == cs`, byte-deterministic
`dumps`, a hard `IncompatibleArtifact` refusal on version mismatch, and a CI-asserted
hydration budget of `loads` < 5 ms for a realistic model.

## 2. Motivation

This is the change that decides whether the platform reaches thousands of tenants (D5).
Cube's scaling ceiling comes from keeping every tenant's compiled model resident in memory —
single-digit to dozens of MB per tenant for compile/SQL/result caches, ~1–10 rps per API
node — forcing a sharded API + refresh-worker topology at hundreds of tenants. If the
compiled artifact is cheap to serialize and rehydrate, per-tenant state becomes a
**per-request LRU entry instead of resident memory**, and the ceiling moves by an order of
magnitude. The budget is load-bearing: per assumption #3 of the changes doc, `loads` at
50 ms instead of 5 ms kills the per-request LRU model. Size drives hydration time, so
`CompiledSemantic` carries everything the planner reads and nothing else — no source specs,
no catalog, no mapping lowering, no emit envelopes.

## 3. Current state

Greenfield module. RFC 0003 pins `ProjectIR`, `SqlExpr`, `project_fingerprint`, and the
determinism rules; its §4 non-goal excludes IR (de)serialization — specs are the durable
artifact, an IR is always recomputable. RFC 0011 defines `NativePlanner.plan` and defers
whether the hot path takes the full `ProjectIR`. RFC 0009 reserves the `perf` marker with no
benchmarks yet; `tests/bench/` does not exist; `errors.py` has no artifact error.

## 4. Goals / Non-goals

**Goals**

- `CompiledSemantic` + `compile_semantic` / `dumps` / `loads` in `bloomery/ir/semantic.py`,
  all four public API (spec §8 grows by exactly these).
- Round-trip and determinism contracts, property-tested (RFC 0009 tier 3).
- `loads` < 5 ms for ~30 entities / ~60 measures / ~8 marts, asserted in CI.
- Fail-closed versioning: `IncompatibleArtifact` on mismatch, never a migration.

**Non-goals**

- A stable cross-version wire format — same stance as the IR (RFC 0003 non-goal); the layout
  may change any release, which is exactly why `loads` refuses instead of migrating.
- IR serialization — `CompiledSemantic` is a *projection*; `ProjectIR` never touches disk.
- A caching tier or LRU implementation — the control plane owns storage and eviction;
  bloomery ships the value object and the codec (hard invariant #1, no I/O).

## 5. Design

### 5.1 Shape

Frozen slotted dataclasses per RFC 0003 D1, with RFC 0003 D4's ordering rules applied — a
deliberate divergence from D5's sketch, which used `Mapping[str, ...]` for measures and
dimensions. Mappings are banned in IR-adjacent value objects: sorted tuples of
`(name, value)` pairs keep the artifact hashable, `==`-comparable, and trivially canonical.

```python
# bloomery/ir/semantic.py

@dataclass(frozen=True, slots=True)
class CompiledSemantic:
    """Everything the planner needs, and nothing else. No source specs, no catalog."""
    marts: tuple[CompiledMart, ...]                          # sorted by name
    measures: tuple[tuple[str, CompiledMeasure], ...]        # sorted by name
    dimensions: tuple[tuple[str, CompiledDimension], ...]    # sorted by name
    fingerprint: str        # project_fingerprint of the source ProjectIR (RFC 0003 D3)
    bloomery_version: str   # importlib.metadata version at compile time

def compile_semantic(ir: ProjectIR) -> CompiledSemantic: ...
def dumps(cs: CompiledSemantic) -> bytes: ...
def loads(data: bytes) -> CompiledSemantic: ...   # raises IncompatibleArtifact
```

What the leaves carry — the planner's working set from RFC 0011's algorithm (validate →
select → lower → build), nothing more:

- `CompiledMart`: name, physical relation, grain, `cost_hint: int` (selection tie-breaking),
  flattened column names + `LogicalType`s — RFC 0010's post-flatten reality, joins burned in.
- `CompiledMeasure`: name, grain, agg, additivity policy — `Additivity` plus
  `SemiAdditivePolicy` / `RatioSpec` where applicable (D4) — and the measure expression as
  dialect-neutral `SqlExpr` text (RFC 0003 §5.2), re-parsed at plan time.
- `CompiledDimension`: name, type, role-qualified column names per mart (`ordered_month`,
  `shipped_month` — D3), so `AmbiguousDimension` errors can name the available roles.

Deliberately stripped: transform chains, mapping provenance, audits, unreachable metrics,
relationships (flattening already consumed them), partition specs, emit envelopes. The
planner reads none of these; every stripped field is hydration time saved.

### 5.2 Serialization: canonical JSON

`dumps` emits canonical JSON: keys sorted, compact separators (`(",", ":")`), UTF-8, one
trailing `\n` never (bytes, not an artifact file). No floats exist (RFC 0003 D5): `Decimal`
serializes as strings, ints as ints. `loads` rebuilds the frozen dataclasses; tuple sort
order is re-imposed on load so equality never depends on producer behavior.

**Alternatives considered.** *pickle* — rejected on D5's reasoning: not safe across versions
(arbitrary code on load) and not deterministic (memoization, protocol drift). *msgpack* —
allowed by D5 and faster to parse, but a runtime dependency for an unproven need; JSON is
stdlib, human-diffable in a cache inspector, and expected to clear the budget for an
artifact this narrow. **msgpack is the named escape hatch**: if the §6 benchmark cannot meet
5 ms on JSON, the codec swaps behind the same `dumps`/`loads` signatures — a codec change
invalidates caches like any release (§5.3), by design.

### 5.3 Versioning, refusal, cache key

```python
class IncompatibleArtifact(BloomeryError): ...   # declared in errors.py (RFC 0002 D3)
```

`loads` compares the artifact's `bloomery_version` against the running package version;
mismatch raises `IncompatibleArtifact` naming both versions. It **never migrates**. The
caller's contract: specs are the durable artifact, compiled semantics are cache — on
mismatch, recompile from specs (parse → resolve → `compile_semantic`) and overwrite the
entry. Cache key recipe for the control plane, documented with the API:

```python
cache_key = sha256(spec_fingerprint + bloomery_version + "semantic")
```

(the `"semantic"` suffix reserves the namespace for future artifact kinds).

### 5.4 Planner input

`NativePlanner.plan` accepts `ProjectIR | CompiledSemantic` (settles RFC 0011's deferred
question). Given a `ProjectIR` it calls `compile_semantic` internally — the convenience path
for tests and small callers. The hot path takes `CompiledSemantic` directly: the control
plane hydrates from cache and never touches the IR at request time. The planner reads only
`CompiledSemantic` fields internally, so the convenience path cannot drift from the hot one.

## 6. Tests

- **Property (RFC 0009 tier 3):** for generated valid projects: `loads(dumps(cs)) == cs`
  (structural equality); `dumps(cs)` byte-identical for a given `cs`;
  `dumps(compile_semantic(ir))` byte-identical for a given `ir`. Cross-process determinism
  joins the RFC 0003 §5.6 subprocess test: differing `PYTHONHASHSEED` values must produce
  identical `dumps` bytes.
- **Unit:** version-mismatch → `IncompatibleArtifact`; truncated/garbage bytes → typed error,
  never a bare `json.JSONDecodeError`; stripped fields provably absent from the bytes.
- **Benchmark (M6 gate):** `tests/bench/test_hydration.py` — `bench` is a new directory in
  the RFC 0009 D2 tree, marked `perf` so it runs in the scheduled job, not the inner loop
  (RFC 0009 D3). The realistic-model fixture (~30 entities / ~60 measures / ~8 marts) is
  generated programmatically, not authored YAML. Measure `loads` via `time.perf_counter`
  over N=50 iterations, assert on the **median**: ceiling 5 ms locally, a documented relaxed
  multiplier (3×) on shared CI runners. A regression fails CI.

## 7. Docs

API reference for the four public names with the cache-key recipe and the
recompile-on-mismatch contract, worded honestly: the byte format is *not* stable across
bloomery versions and must never be treated as an export format. The determinism explanation
page (RFC 0003 §7) gains a paragraph on artifact determinism.

## 8. Out of scope

- **msgpack codec** — named escape hatch (§5.2), built only if the benchmark forces it.
- **Artifact compression** — the control plane may gzip entries; bloomery hands over bytes.
- **Cross-version migration** — would require freezing the layout (non-goal); revisited only
  if recompile-on-miss is ever measured too slow at fleet scale.

## 9. Risks

- *JSON parse dominates hydration; the 5 ms budget fails.* Mitigation: the artifact is
  deliberately narrow (§5.1) and the bench gate catches bloat the day it lands; msgpack is
  the pre-named fallback with no API change.
- *Version-string coupling to release cadence — every release invalidates every cached
  artifact.* Accepted: recompile from specs is cheap, and silent cross-version reuse is the
  failure mode this design refuses.
- *CI timing flakiness on the bench.* Mitigation: median over 50 iterations plus the
  documented 3× CI multiplier; the assertion tests a regression cliff, not a microsecond.

## 10. Unresolved questions

- None blocking. Implementation is free to settle the exact JSON field spelling and the
  `CompiledMart`/`CompiledMeasure`/`CompiledDimension` field lists, provided §5.1's
  carried/stripped split and the §11 contracts hold.

## 11. Decisions

| # | Decision |
| --- | --- |
| 1 | `CompiledSemantic` exists to move the scaling ceiling: per-tenant compiled state becomes a per-request LRU entry, not resident memory (contrast: Cube's MB-per-tenant residency, ~1–10 rps/node). It carries everything the planner needs and nothing else — no source specs, no catalog, no mapping lowering, no emit envelopes — because size drives hydration time. |
| 2 | Shape per D5 with RFC 0003 determinism rules applied: `marts: tuple[CompiledMart, ...]`; measures/dimensions as **sorted tuples of `(name, value)` pairs**, a deliberate divergence from D5's `Mapping` sketch (RFC 0003 D4); plus `fingerprint` (source ProjectIR's) and `bloomery_version`. |
| 3 | Serialization is canonical JSON — sorted keys, compact separators, UTF-8, no floats (`Decimal` as strings, ints as ints). Not pickle (D5: unsafe across versions, nondeterministic). Not msgpack (no new dependency); msgpack is the named escape hatch if the 5 ms budget fails on JSON. |
| 4 | Contracts, all property-tested (RFC 0009): `loads(dumps(cs)) == cs`; `dumps` byte-identical for a given `cs` across processes and `PYTHONHASHSEED`; `dumps(compile_semantic(ir))` byte-identical for a given `ir`. |
| 5 | `loads` on a `bloomery_version` mismatch raises `IncompatibleArtifact` (new `BloomeryError` leaf, declared in `errors.py` per RFC 0002 D3) — never migrates. Caller recompiles from specs (durable artifact; compiled semantics are cache). Cache key: `sha256(spec_fingerprint + bloomery_version + "semantic")`. |
| 6 | Hydration budget: `loads` < 5 ms for ~30 entities / ~60 measures / ~8 marts, enforced by `tests/bench/test_hydration.py` (new `bench` directory): programmatic fixture, `time.perf_counter`, N=50, assert on the median, 5 ms locally / 3× on CI, marked `perf` for the scheduled job (RFC 0009 D3). A regression fails CI. |
| 7 | `NativePlanner.plan` accepts `ProjectIR \| CompiledSemantic`; a `ProjectIR` is compiled internally (convenience path), the hot path takes `CompiledSemantic` directly. Settles the question RFC 0011 defers. |
| 8 | `compile_semantic`, `dumps`, `loads`, `CompiledSemantic` are public API — spec §8 grows by exactly these. The field layout is **not** a public stable format across versions (same stance as the IR, RFC 0003 non-goal) — which is precisely why D5 refuses instead of migrating. |

## 12. Phasing

Ships as milestone M6 (D10): `semantic.py`, `IncompatibleArtifact`, the property contracts,
and the hydration benchmark land together — M6 is done when `loads` is under 5 ms, asserted
in CI. Depends on RFC 0010 (mart IR) and RFC 0011 (planner); the §5.4 planner widening
amends the RFC 0011 port in the same PR.
