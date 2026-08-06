# Determinism

This page explains the property the whole architecture rests on: `compile(x)` equals
`compile(x)` byte-for-byte, across processes, machines, and Python hash seeds. It
covers why byte-stability is load-bearing rather than cosmetic, what the project
fingerprint promises and pointedly does not, the rules that keep the package
deterministic, and how those rules are enforced mechanically rather than by vigilance.

## Why bytes, not just semantics

"Semantically equivalent output" would be cheaper to guarantee. Four consumers need
more than that:

- **`plan()` is a structural diff of two IRs.** If compiling the same specs twice could
  produce different IRs, every diff would drown in phantom changes and change
  classification would be noise.
- **Golden tests assert byte equality.** Every fixture × target × dialect pair renders
  to a checked-in file; an unexplained diff means the compiler changed behavior. That
  signal only exists if unchanged behavior produces unchanged bytes.
- **The SQLMesh replan must be a no-op.** The strongest end-to-end test in the suite
  writes emitted artifacts into a SQLMesh context, plans, and asserts
  `plan.has_changes` is false — the compiler and SQLMesh agree on what the models mean,
  proven end to end. Nondeterministic emission breaks this first.
- **The hydration cache is keyed by fingerprint.** At request time the planner hydrates
  a MetricFlow manifest from a cache whose key includes the spec fingerprint. If equal
  specs could fingerprint differently, the cache would silently miss forever; if
  different specs could collide, it would silently serve the wrong tenant's semantics.

## The fingerprint

```python
project_fingerprint(ir)   # "blm1:3f9a…"  — sha256 over a canonical encoding of the IR
```

The fingerprint is a content hash of the entire `ProjectIR`, computed over a
purpose-built canonical byte encoding (not JSON — JSON invites float-formatting and
key-ordering bugs). The `blm1:` prefix makes it greppable in logs and artifact headers.
It answers "has anything about this project's compiled meaning changed?" and it keys
two caches: the caller's compilation cache, and — as `HydrationKey.spec_fingerprint` —
the planner's manifest hydration cache.

What it is **not**:

- **Not stable across bloomery versions.** The IR shape version is part of the hash, so
  an IR change alters every fingerprint loudly instead of colliding silently. Specs are
  the durable thing; fingerprints and artifacts are cache.
- **Not a migration key.** The full hydration key is
  `HydrationKey(spec_fingerprint, bloomery_version, metricflow_version)` — a bump of
  bloomery *or* of the pinned MetricFlow changes the key, so the old cache entry is
  simply never looked up again. Version mismatch is a cache miss by construction, never
  an error and never a migration: on a miss, rebuild from specs.

## The rules

Stated once, applied package-wide:

1. **No clocks, no randomness, no environment.** `datetime.now()`, `uuid4()`,
   `random`, `os.environ`, filesystem, and network are all banned under the package. If
   an artifact ever needs a timestamp, it is an input parameter.
2. **Never iterate a set where order can reach output.** Every IR collection is a
   tuple; dict-shaped data is stored as sorted key-value tuples.
3. **Floats are banned** in the IR and on emission paths — `Decimal` or `int` only.
   Float repr is the classic cross-platform byte-drift source.
4. **Ties break lexicographically.** Topological sort ties, mart-selection ties,
   violation ordering in error aggregates — every ordering decision has an explicit,
   stable sort key. Sorting is never left to insertion accidents.
5. **SQLGlot is pinned exactly.** Its canonical rendering is part of the output, so a
   version bump is a deliberate PR that regenerates goldens, never an ambient drift.

## Enforcement

Intent does not survive contact with a hash-randomized dict, so the contract is proven
by test, not review. The cornerstone is the cross-seed subprocess test: compile the
same fixture in two fresh interpreter processes with different `PYTHONHASHSEED` values
and assert identical bytes.

```python
def test_determinism_across_processes(project):
    out1 = run_compile_subprocess(project, env={"PYTHONHASHSEED": "0"})
    out2 = run_compile_subprocess(project, env={"PYTHONHASHSEED": "1"})
    assert out1 == out2   # artifact bytes and fingerprint, identical
```

Any set iteration or hash-ordered traversal anywhere on the output path fails this test
immediately, because hash randomization changes iteration order between the two
processes. Around it sit property tests (compiling twice in-process yields identical
results; the fingerprint survives a spec round trip) and lint rules that reject set
iteration and float literals in the IR before a human ever reviews them.

Determinism is also why the compiler never chooses — recipes are recorded upstream and
validated here, as [Specs and the catalog](specs-and-catalog.md) explains, and every
refusal the [guardrails](guardrails.md) make is exactly reproducible for the same spec.
