# RFC 0008 — Ports and emitters: targets, dialects, naming

- **Status:** 📝 Draft
- **Scope:** The three ports (`TargetEmitter`, `DialectPort`, `NamingPolicy`), the lowering
  stage that turns `ProjectIR` into `EmittedArtifact`s, and the concrete adapters shipped in
  v0.1: SQLMesh (primary target), Cube and dbt (secondary targets), DuckDB / Trino /
  Postgres dialects, `DefaultNaming` / `TenantPrefixNaming`. Settles original-spec open
  questions #1 (files vs Python models), #3 (date dimension) and #5 (quarantine). New
  modules: `bloomery/emit/`, `bloomery/dialects/`, `bloomery/naming.py`. Does not cover how
  the IR is computed (RFCs 0004–0006) or diffed (RFC 0007).
- **Related:** [`rfcs/_original-smelter-spec.md`](_original-smelter-spec.md) §4, §5.6, §9,
  §12; RFC 0003 (IR, `SqlExpr`), RFC 0006 (additivity defense-in-depth at emit).

---

## 1. Summary

Target and dialect vary independently, so they are independent ports: an emitter renders
framework envelopes and asks a `DialectPort` to render SQL and physical types; a
`NamingPolicy` maps logical entities to physical `(namespace, relation)` pairs — the only
tenant-shaped seam in the package. v0.1 ships SQLMesh/dbt/Cube emitters and
DuckDB/Postgres/Trino dialects. Capability mismatches raise `UnsupportedByTarget`; nothing
silently degrades.

## 2. Motivation

Collapsing target and dialect into one adapter produces an N×M explosion of near-duplicate
templates (spec §4.2): SQLMesh-on-Trino and dbt-on-Trino share every line of dialect logic;
SQLMesh-on-DuckDB and SQLMesh-on-Trino share every line of envelope logic. The three-port
split is the single most load-bearing design decision in the package, and M8 (second
target and second dialect, renumbered per `_bloomery-changes.md` D10) exists precisely to
validate it before the IR fossilizes.

## 3. Current state

Greenfield. RFC 0003 fixes the IR the emitters consume (`SqlExpr` stored as canonical
dialect-neutral SQLGlot text, re-parsed at emit) and the artifact ordering rules (sorted by
path, single trailing newline).

## 4. Goals / Non-goals

**Goals**

- Ports as `typing.Protocol`s — adapters need no base-class import to conform.
- `compile_project(project, *, target, dialect, naming, catalog)` returns
  `tuple[EmittedArtifact, ...]` — pure data out, byte-deterministic.
- `register_emitter(emitter)` extension point (spec §8) so adapter packages
  (`bloomery-iceberg`-style) can add targets without touching the core.
- Capability negotiation: the core queries `TargetCapabilities` and either lowers
  differently or raises `UnsupportedByTarget` with the entity/feature named.

**Non-goals**

- Executing anything. SQLMesh/dbt/Cube run elsewhere; e2e tests (RFC 0009) prove
  acceptance, the package never shells out.
- Gold serving / query APIs — Cube emission is the boundary; serving is the consumer's job.
- Registering Python models into a live SQLMesh context — see §5.6.

## 5. Design

### 5.1 Ports

```python
class TargetEmitter(Protocol):
    """IR → framework artifacts. Knows nothing about SQL dialects."""
    name: str                                   # "sqlmesh" | "dbt" | "cube" | ...
    def capabilities(self) -> TargetCapabilities: ...
    def emit(self, ir: ProjectIR, ctx: EmitContext) -> tuple[EmittedArtifact, ...]: ...

class DialectPort(Protocol):
    """SQL rendering + physical type mapping. Wraps SQLGlot; knows nothing about targets."""
    name: str                                   # "duckdb" | "postgres" | "trino" | ...
    def render(self, node: exp.Expression) -> str: ...
    def physical_type(self, t: LogicalType) -> str: ...
    def supports(self, feature: DialectFeature) -> bool: ...

class NamingPolicy(Protocol):
    """Logical name → physical (namespace, relation). The only tenant-shaped seam."""
    def relation(self, entity: str, layer: Layer) -> tuple[str, str]: ...
```

```python
@dataclass(frozen=True, slots=True)
class TargetCapabilities:
    supported: frozenset[Feature]   # membership-checked; any output-reaching iteration is sorted()

class Feature(StrEnum):            # amended per _bloomery-changes.md D6 + pivot R8
    SEMI_ADDITIVE      = "semi_additive"
    NON_ADDITIVE       = "non_additive"
    CUMULATIVE         = "cumulative"          # pivot R8
    DERIVED_METRIC     = "derived_metric"      # pivot R8
    ROLE_PLAYING_DIM   = "role_playing_dim"
    MULTI_FACT         = "multi_fact"
    QUERY_TIME_JOIN    = "query_time_join"
    ROW_LEVEL_SECURITY = "row_level_security"
    VARIANT_COLUMN     = "variant_column"
    SCD_TYPE_2         = "scd_type_2"
    INCREMENTAL        = "incremental"
    AUDITS             = "audits"

@dataclass(frozen=True, slots=True)
class EmitContext:
    dialect: DialectPort
    naming: NamingPolicy
    fingerprint: str           # project_fingerprint(ir) — stamped into artifact headers
```

`Layer` = `{BRONZE, SILVER, GOLD}`. `DefaultNaming` → `("silver", entity)`;
`TenantPrefixNaming(prefix)` → `(f"{prefix}_silver", entity)` — tenant scoping as ordinary
spec values, per hard invariant #3.

Registries: module-level immutable defaults + explicit `register_emitter` /
`register_dialect` overlay, same shape and same collision-is-an-error rule as the transform
registry (RFC 0004 D6). Lookup by unknown name raises `EmitError` listing known names.

Declared support (amended per `_bloomery-changes.md` D6): SQLMesh — `SCD_TYPE_2`,
`VARIANT_COLUMN`, `INCREMENTAL`, `AUDITS`, all additivity features; Cube —
`QUERY_TIME_JOIN`, `MULTI_FACT`, `ROW_LEVEL_SECURITY`, `ROLE_PLAYING_DIM` (semi-additive
support verified empirically before the equivalence suite trusts it, RFC 0009); dbt —
most, with `SCD_TYPE_2` lowered to a snapshot. The **planner (RFC 0011 contract,
RFC 0013 MetricFlow backend) is a fourth port**, not a `TargetEmitter` — different
lifecycle (request-time, hot path) — but it declares capabilities in the same vocabulary:
semi/non-additive, cumulative, derived, role-playing, RLS, and *not*
`MULTI_FACT`/`QUERY_TIME_JOIN`. Nuance per the pivot: MetricFlow *can* plan query-time
joins; bloomery refuses them by policy at the coverage precheck (RFC 0013 R3) — a
deliberate policy, not a limitation; the capability docstring says so, so nobody "fixes"
it later. Unsupported combinations raise `UnsupportedByTarget` at compile time. Never
degrade silently.

### 5.2 Lowering

`emit()` receives an IR whose expressions are dialect-neutral (`SqlExpr`). Per entity the
emitter builds one `SELECT` as a SQLGlot AST — source columns extracted from the bronze
relation (JSONPath lowering per RFC 0004's `json_path` transform), transform chains applied,
recipe expressions inlined — then hands the finished AST to `DialectPort.render`. Jinja
renders only the envelope (the `MODEL (...)` block, the dbt config header, YAML scaffolding)
from templates that interpolate *pre-rendered strings*, never SQL fragments. Each artifact
carries a generated-by header comment including the fingerprint, so drift between applied
artifacts and specs is detectable downstream.

### 5.3 SQLMesh emitter (primary)

- One `MODEL (...)` + `SELECT` file per entity: `models/silver/<entity>.sql`.
- `kind`: `FULL`, `INCREMENTAL_BY_UNIQUE_KEY(unique_key=...)`, or
  `INCREMENTAL_BY_TIME_RANGE` per the IR's resolved `materialization`; SCD type 2 entities
  use native `SCD_TYPE_2_BY_KEY` (capability `native_scd2`).
- `grain`, `partitioned_by`, `audits` populated from `EntityIR`; range-sanity audits
  (RFC 0006 D7) become SQLMesh `audits` with companion `audits/<entity>_<audit>.sql`
  artifacts where a custom audit body is needed.
- Path-conflict reconciliation (RFC 0006 D6) emits the `<field>__direct` shadow column and
  a non-blocking audit comparing the two.
- Mart builds (amended, RFC 0010): each `MartIR` lowers to a gold-layer model
  (`models/gold/<mart>.sql` via `NamingPolicy.relation(name, Layer.GOLD)`) — the base
  entity joined once per flatten step and once per date role, projecting the wide column
  set. The only place joins are ever emitted for a mart; the planner (RFC 0011) reads the
  built table joinlessly.

### 5.4 Cube emitter (semantic)

- `model/cubes/<entity>.yml` per gold-relevant entity; `model/views/` for metric views.
- Measures carry `type` (sum / count / count_distinct / number) and
  `meta.additivity` / `meta.grain` propagated from `MetricIR`.
- Non-additive metrics emit as calculated measures over their additive components; a
  request to store one is refused at guardrail stage already (RFC 0006 D5), and the emitter
  re-checks — defense in depth, `UnsupportedByTarget` if reached.
- `sql_table` comes from `NamingPolicy.relation(entity, Layer.GOLD)`; Cube has no
  SCD/incremental concepts — those capabilities are `False` and irrelevant rather than
  errors (Cube consumes tables SQLMesh maintains).

### 5.5 dbt emitter (compatibility)

- `models/silver/<entity>.sql` with `{{ config(...) }}` headers; SCD type 2 lowers to a
  `snapshots/<entity>_snapshot.sql`; audits lower to `schema.yml` tests
  (`not_null`, `accepted_values`, `dbt_utils.expression_is_true`-shaped generic tests).
- Anything unmappable (e.g. an audit kind with no test equivalent) raises
  `UnsupportedByTarget` naming the entity and feature. Its real job is proving the port
  abstraction (spec §9); it ships minimal but honest.

### 5.6 Settled open questions

- **#1 Files vs Python models:** the emitter contract is *file-shaped artifacts as data*
  (`EmittedArtifact.path/content`). The pure-function invariant already forbids touching a
  filesystem, so "files" cost nothing and keep dbt/Cube symmetric. A multi-tenant caller
  that prefers SQLMesh Python-model registration can build it *on top of* the artifact
  stream; a native registration API is deliberately out of scope until a real deployment
  demands it. Locks us to text artifacts; revisiting means a second emit method, not a
  rewrite.
- **#3 Date dimension:** ~~not emitted in v0.1~~ — **reversed by the MetricFlow pivot
  (D13 below):** bloomery owns the date dimension. MetricFlow requires a declared time
  spine; the SQLMesh emitter builds `gold.dim_date` from a single catalog definition and
  the manifest's `PydanticTimeSpine` points at it (RFC 0013 R1 rule 4). The original
  reasoning (no tenant spec drives it) is answered: the *catalog* drives it, which is
  exactly the vertical-level home it needed.
- **#5 Quarantine:** an emitter-level convention, not IR entities.
  `on_unmapped_enum: quarantine` lowers to a `<entity>__quarantine` model artifact holding
  rejected rows; the IR carries only the mapping's declared policy. IR-as-entities would be
  more honest but doubles IR surface before M6 validates it — revisit if a second policy
  consumer appears.

### 5.7 Alternatives considered

- **One combined Target×Dialect adapter** — rejected: N×M template duplication, and M6
  would multiply it (spec §4.2).
- **Jinja for SQL** — rejected outright (spec §2): string-templated SQL makes multi-dialect
  support aspirational and emitted SQL unparseable in tests.
- **Emitter-owned dialects** (dialect as emitter constructor arg, no port) — rejected:
  dbt-on-Trino and SQLMesh-on-Trino would each carry Trino type-mapping quirks.

## 6. Tests

Golden matrix per (fixture × target × dialect) — RFC 0009 §golden; property invariants
(emitted SQL parses under the target dialect; SELECT columns ↔ declared fields);
execution tests run SQLMesh-emitted DuckDB SQL in-process; e2e proves SQLMesh
`plan.has_changes == False` on replan, `dbt parse` accepts, Cube `/meta` matches.
`UnsupportedByTarget` paths get unit tests per emitter.

## 7. Docs

How-to per target (`pages/how-to/emit-sqlmesh.md`, `emit-cube.md`, `emit-dbt.md`),
explanation page on the three-port architecture with the spec §4 diagram, reference page
for `EmittedArtifact` / capabilities / naming policies.

## 8. Out of scope

- **Spark dialect** — engine-matrix tested post-v0.1; adding a `DialectPort` is the
  designed extension path.
- **Iceberg table-format specifics** (partition transforms beyond `days/months/years/hours`,
  table properties) — adapter-package territory (`bloomery-iceberg`).
- **Cube pre-aggregations** — perf tuning, not correctness; demand-gated.

## 9. Risks

- *SQLMesh MODEL-block syntax drift* across sqlmesh versions — mitigated by the e2e replan
  test pinned to the locked sqlmesh version; the envelope template changes only in a
  deliberate bump PR.
- *dbt emitter read as production-grade* — it is a port-abstraction proof (spec §9); docs
  say so explicitly.
- *Capability flags too coarse* — accepted for v0.1; flags can only be split (never merged)
  without breaking adapters.

## 10. Unresolved questions

- Exact SQLMesh audit vocabulary for range-sanity clauses (builtin `not_null` etc. vs
  custom audit files) — implementation settles against the pinned sqlmesh version.
- Whether Cube views should be emitted per metric or per metric-grain group —
  implementation settles; goldens lock the choice.

## 11. Decisions

| # | Decision |
| --- | --- |
| 1 | Three independent ports (`TargetEmitter`, `DialectPort`, `NamingPolicy`), all `Protocol`s. Target and dialect never collapse into one adapter. |
| 2 | Emitters produce file-shaped text artifacts as data (settles open question #1). No filesystem writes, no live-context registration in core — callers build that on top. |
| 3 | Capability mismatch behavior is fail-loud: `UnsupportedByTarget` naming entity + feature. Silent degradation is forbidden. |
| 4 | SQL rendering: SQLGlot AST → `DialectPort.render`; Jinja only ever sees pre-rendered strings (envelope templating). |
| 5 | v0.1 adapter set: SQLMesh + Cube + dbt targets; DuckDB + Postgres + Trino dialects. dbt is a port-abstraction proof, documented as such. |
| 6 | Date dimension not emitted in v0.1 (settles #3, demand-gated). |
| 7 | Quarantine is an emitter convention (`<entity>__quarantine` artifact), not IR surface (settles #5; revisit on a second policy consumer). |
| 8 | Emitter/dialect registries mirror the transform registry: immutable defaults + explicit overlay, collision is an error, iteration sorted (RFC 0004 D6). |
| 9 | Every artifact carries a header comment with the project fingerprint — applied-vs-spec drift detection downstream. |
| 10 | (Amended for `_bloomery-changes.md` D6) `TargetCapabilities` is a `frozenset[Feature]` over a closed `Feature` StrEnum — membership-checked, sorted at any output-reaching iteration. The native planner (RFC 0011) is a fourth port sharing this vocabulary; its lack of `QUERY_TIME_JOIN`/`MULTI_FACT` is the fan-out-impossibility property, documented as a feature. |
| 11 | (Amended, RFC 0010) The SQLMesh emitter also builds marts: one gold-layer model per `MartIR`, the only join-emitting path for marts. |
| 12 | (Amended for `_bloomery-metricflow-pivot.md` R8) `Feature` gains `CUMULATIVE` and `DERIVED_METRIC`. The planner's declared capabilities are RFC 0013's; `QUERY_TIME_JOIN` is refused **by policy** at the coverage precheck even though MetricFlow supports it. |
| 13 | (Reverses D6) Bloomery owns the date dimension: one catalog definition emits both the SQLMesh `gold.dim_date` model and the MetricFlow time-spine declaration (RFC 0013 R1). D6's demand-gate is satisfied — MetricFlow is the demand. |
| 14 | (Amended, RFC 0013) A sixth artifact consumer joins the emit family: `emit/metricflow` produces a `PydanticSemanticManifest` (an object, not text — the one emitter whose output is data for `runtime/` hydration rather than an `EmittedArtifact` file; manifest JSON goldens keep it reviewable). |

## 12. Phasing

M2: SQLMesh emitter + DuckDB dialect (minimal `FULL` models). M3–M4 extend lowering
(recipes, audits). M5 adds mart build emission (RFC 0010); M6 the MetricFlow manifest
emitter (RFC 0013). M10 (renumbered per `_bloomery-metricflow-pivot.md` §8): Trino +
Postgres dialects, Cube emitter, dbt emitter — the port validation milestone; do not
defer past it (a second target discovered late means an IR rewrite, spec §11).
