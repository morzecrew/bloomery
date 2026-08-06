# RFC 0003 — Intermediate representation and determinism contract

- **Status:** 📝 Draft
- **Scope:** The frozen, hashable IR that the compile pipeline produces and every emitter
  consumes (`bloomery/ir/`), the `project_fingerprint` content hash, and the package-wide
  determinism rules that make `compile(x) == compile(x)` byte-for-byte. Covers the IR data
  model and its construction ordering guarantees; does not cover how the IR is *computed*
  (resolution — RFC 0005; typing — RFC 0004) or consumed (emitters — RFC 0008; diffing —
  RFC 0007).
- **Related:** [`rfcs/_original-smelter-spec.md`](_original-smelter-spec.md) §5.6, §6;
  RFC 0002 (specs the IR is built from), RFC 0007 (`plan()` diffs two IRs),
  RFC 0008 (emitters read the IR).

---

## 1. Summary

A frozen dataclass tree (`ProjectIR`) with all collections ordered, every SQL expression a
SQLGlot AST held in normalized-serialized form, and a stable SHA-256 fingerprint. Plus the
determinism rules enforced across the package: no sets iterated, no clocks, no randomness,
lexicographic tie-breaks, `PYTHONHASHSEED`-independence proven by test.

## 2. Motivation

Everything downstream rests on the IR being value-like: `plan()` (RFC 0007) is a structural
diff of two IRs; caching keys off `project_fingerprint`; golden tests assert byte equality;
the SQLMesh e2e test asserts a replan is a no-op. Any nondeterminism — a set iteration, a
dict ordered by insertion accident, a float repr — breaks all four at once, usually
intermittently. The IR is therefore designed so the deterministic thing is the only easy
thing to write.

## 3. Current state

Greenfield; RFC 0002 defines the frozen spec models the IR builder consumes.

## 4. Goals / Non-goals

**Goals**

- `ProjectIR`: frozen, hashable, `==`-comparable by value, order-normalized.
- `project_fingerprint(ir) -> str`: stable across processes, machines, Python versions in
  the support matrix, and `PYTHONHASHSEED` values.
- Determinism rules stated once here and enforced mechanically (lint + tests), not by
  vigilance.

**Non-goals**

- IR stability across bloomery versions — the IR is *not* a public serialization format in
  v0.1 (`Everything else is private`, spec §8). The fingerprint is stable per version;
  cross-version fingerprint compatibility is explicitly not promised.
- Backward-compatible IR (de)serialization to disk — callers persist specs, not IRs; an IR
  is always recomputable from specs.

## 5. Design

### 5.1 IR shape

Frozen `@dataclass(frozen=True, slots=True)` — not Pydantic. The IR is compiler-internal;
it needs hashing and structural sharing, not validation (its builder is the validator).

```python
@dataclass(frozen=True, slots=True)
class ProjectIR:
    bloomery_ir_version: int            # bumped when IR shape changes; part of fingerprint
    entities: tuple[EntityIR, ...]      # sorted by name
    metrics: tuple[MetricIR, ...]       # sorted by name; only *reachable* metrics
    unreachable: tuple[UnreachableMetric, ...]  # name + missing leaves — product-facing
    relationships: tuple[RelationshipIR, ...]
    marts: tuple[MartIR, ...]           # sorted by name — wide-mart gold layer (RFC 0010)

@dataclass(frozen=True, slots=True)
class EntityIR:
    name: str
    grain: str
    key: tuple[str, ...]                # authored order preserved (it is meaningful)
    scd: SCDKind
    materialization: Materialization    # resolved (explicit or derived) — RFC 0002 D7
    partition_by: tuple[PartitionSpec, ...]
    columns: tuple[ColumnIR, ...]       # sorted by name
    source: SourceIR                    # bronze relation + key/field lowering
    audits: tuple[AuditIR, ...]         # sorted by (kind, column)

@dataclass(frozen=True, slots=True)
class ColumnIR:
    name: str
    type: LogicalType                   # RFC 0004
    canonical: str | None
    unit: Unit | None
    tax_basis: TaxBasis | None
    expr: SqlExpr                       # the lowered expression producing this column
    recipe_id: str | None               # which catalog recipe produced expr, if any
    renamed_from: str | None            # explicit rename annotation, consumed by plan() (RFC 0007 D3)
    required: bool
```

`MetricIR` carries `name, grain, additivity, agg, expr | ratio, depends_on: tuple[str, ...]`
(the DAG edges, kept for `plan()`'s downstream-impact computation).

### 5.2 SQL expressions in the IR: `SqlExpr`

SQLGlot `exp.Expression` objects are mutable and their `__eq__`/`__hash__` are structural
but version-sensitive. The IR therefore stores expressions as:

```python
@dataclass(frozen=True, slots=True)
class SqlExpr:
    sql: str          # canonical form: node.sql(dialect=None, normalize=True, pretty=False)
    def ast(self) -> exp.Expression: ...   # parse_one(self.sql) — cached, never mutated in place
```

The canonical dialect-neutral string is the value; dialect-specific rendering happens at
emit time from a fresh parse. This makes the IR trivially hashable and its equality
independent of SQLGlot object identity, at the cost of a re-parse per emit (cheap, and pure).

### 5.3 Ordering rules

- Every collection is a `tuple`. `set`/`frozenset` never appear in IR fields.
- Sort keys are always explicit and lexicographic on stable identifiers (entity name,
  column name, metric name) — never on insertion order, except where authored order is
  semantic (`key`, transform chains, recipe `requires` aliases, partition specs).
- Dict-shaped data (e.g. enum maps in transforms) is stored as
  `tuple[tuple[str, str], ...]` sorted by key.

### 5.4 Fingerprint

```python
def project_fingerprint(ir: ProjectIR) -> str:
    # sha256 over a canonical serialization; prefixed for greppability
    return "blm1:" + sha256(_canon_bytes(ir)).hexdigest()
```

`_canon_bytes` walks the dataclass tree emitting a length-prefixed, type-tagged byte stream
(field name + value, recursively; tuples length-prefixed; enums by value; `Decimal` by
`str()`; no floats exist in the IR — decimal precision params are ints). Not JSON: JSON
tempts float formatting and key-ordering bugs; a purpose-built canonical encoding is ~40
lines and has no such trapdoors. `bloomery_ir_version` is included, so an IR shape change
changes every fingerprint loudly rather than colliding silently.

### 5.5 Determinism rules (package-wide)

1. No `datetime.now()`, `time()`, `uuid4()`, `random`, `os.environ`, filesystem, network —
   anywhere under `src/bloomery/`. Timestamps, if an artifact ever needs one, are inputs.
2. Never iterate a `set` where order can reach output. Enforced: ruff flake8-bugbear +
   a repo grep-lint (`just lint` fails on `for .* in .*set(` and on `frozenset` in
   `src/bloomery/ir/`), plus the process-level test below.
3. All floats banned in IR and emission paths (`Decimal` or int only). Ruff rule + review.
4. `sqlglot` pinned **exact** (`sqlglot==X.Y.Z`) in the lockfile *and* as `sqlglot>=X.Y.Z,<X.Y+1`
   in package metadata; bumping regenerates goldens in a dedicated PR.
5. Emission sorts artifacts by `path`; artifact content ends with exactly one `\n`; `\n`
   line endings only.

### 5.6 Determinism tests (the enforcement)

- `test_fingerprint_across_processes`: compile the same fixture in two subprocesses with
  `PYTHONHASHSEED=0` and `=1`; artifact bytes and fingerprints must be identical.
- Property test: `compile(p) == compile(p)` (twice in-process, fresh objects).
- `fingerprint(build_ir(specs)) == fingerprint(build_ir(parse(dump(specs))))` — fingerprint
  survives a spec round-trip.

## 6. Tests

As §5.6, plus unit tests for `_canon_bytes` (every IR node type reachable, distinct values
→ distinct bytes, permuted inputs → identical IR → identical bytes).

## 7. Docs

Explanation page `pages/explanation/determinism.md`: why byte-stable output is the core
property, what the fingerprint is and is not (not cross-version stable), how goldens relate.

## 8. Out of scope

- **IR serialization for external consumers** — the control plane caches by fingerprint and
  recompiles on miss; shipping a stable IR format would freeze internals before M6 validates
  them. Escape hatch: a versioned export can be added once two targets have proven the shape.
- **Structural sharing / interning optimizations** — correctness first; profile later.

## 9. Risks

- *SQLGlot canonical form drifts between versions* → fingerprints and goldens change on
  bump. Accepted: the pin-bump PR regenerates both, and the e2e replan test catches semantic
  drift.
- *`SqlExpr` re-parse cost at emit* — accepted; emission is not a hot loop, purity wins.

## 10. Unresolved questions

- None blocking. Exact `_canon_bytes` tag scheme is implementation-free.

## 11. Decisions

| # | Decision |
| --- | --- |
| 1 | IR is frozen stdlib dataclasses (slots), not Pydantic — validation happens at build, value semantics matter after. |
| 2 | SQL is stored in the IR as canonical dialect-neutral SQLGlot text (`SqlExpr`), re-parsed at emit. Consequence: SQLGlot version changes can change fingerprints; the exact pin (D4 §5.5) makes that a deliberate event. |
| 3 | `project_fingerprint` = `"blm1:" + sha256(canonical bytes)`; includes `bloomery_ir_version`; stable within a bloomery version, explicitly not across versions. |
| 4 | All IR collections are tuples with explicit lexicographic sort, except authored-order fields (`key`, transform chains, recipe aliases, `partition_by`). |
| 5 | Floats are banned in IR and emission; `Decimal`/int only. |
| 6 | Unreachable metrics are IR members (`unreachable` tuple with missing leaves), not log lines — they are product-facing output. |
| 7 | Determinism is enforced by subprocess tests with differing `PYTHONHASHSEED`, not by convention. |
| 8 | (Amended for `_bloomery-changes.md`) `ProjectIR.marts` (`MartIR`, RFC 0010) and `DimensionRef` join the IR and are fingerprint-covered; `MetricIR` carries the typed additivity policy (`SemiAdditivePolicy` / `RatioSpec`, RFC 0011). `bloomery/ir/` additionally hosts the serializable `CompiledSemantic` planner artifact (RFC 0012) — the IR itself remains non-serialized internal surface. |

## 12. Phasing

M1 ships the IR node types, `SqlExpr`, `_canon_bytes`, `project_fingerprint`, and the
process-level determinism test wired to the `minimal` fixture. The IR builder itself grows
across M2–M4 as resolution, typing, and guardrails land.
