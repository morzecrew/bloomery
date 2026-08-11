# RFC 0008 — Ports and emitters: targets, dialects, naming

- **Status:** 🚧 In progress — shipped 2026-08-07 (M2–M10): all three ports, the
  SQLMesh/Cube/dbt emitters and DuckDB/Postgres/Trino dialects, and the D6 reversal
  (`gold.dim_date` emitted per RFC 0013 D5); remaining: emitted-SQL verification on
  the engine matrix beyond Postgres (Trino) and the containerized target e2e tiers
  (RFC 0009 nightly lane).
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

- ~~Exact SQLMesh audit vocabulary for range-sanity clauses (builtin `not_null` etc. vs
  custom audit files)~~ — **settled 2026-08-10, D16.** Both, and the criterion is not
  what SQLMesh has: a clause takes each framework's **native** audit where *both*
  frameworks have one meaning exactly it, and otherwise both render one predicate
  bloomery builds. The pinned sqlmesh does ship `accepted_range` and
  `match_regex_pattern_list`, semantically equal to what bloomery emits; taking them
  would strand the shared predicate with dbt as its only consumer.
- ~~Whether Cube views should be emitted per metric or per metric-grain group~~ —
  **settled 2026-08-10, D17.** Neither: **per mart**. A per-grain view over two marts
  at one grain would need a `join_path` between them, and bloomery models no
  relationship between marts — so it could only be emitted by inventing a join.

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

| 16 | *(2026-08-10)* **A clause takes a native audit where both targets have one, and a shared predicate otherwise. §10's audit-vocabulary question is settled — and not by availability.** The split that shipped is `not_null`/`enum` inline in SQLMesh's `MODEL` block and as dbt's native tests, with `min`/`max`/`regex` as an `audits/*.sql` artifact on one side and a generic test on the other (`dbt_utils.expression_is_true` as this decision was written; **amended by D18** to a macro bloomery emits, which changes the vehicle and not the split). §10 framed the question as "builtin vs custom, settled against the pinned sqlmesh" — which turns out to be the wrong axis. The pinned sqlmesh (0.236) **does** ship `accepted_range` and `match_regex_pattern_list`, and their queries read identically to `audit_predicate`'s: `accepted_range(min_v := N)` is `column < N`, and `match_regex_pattern_list(patterns := [p])` is `NOT REGEXP_LIKE(column, p)`. (Compared by reading both ASTs, not by executing them — stated because "identical" is the kind of claim that deserves to say how it was reached.) So availability was never the constraint. **The criterion is agreement between the two targets.** dbt-core has native `not_null` and `accepted_values` and no range or regex test at all — `dbt_utils` is a package, not core. For the first two, each framework says the same thing in its own vocabulary and bloomery uses each one's, which is why they read natively on both. For the rest, only SQLMesh has a builtin, and taking it would leave `audit_predicate` with dbt as its sole consumer: one function builds the violations form and the assertion form side by side, and that shared construction is the only thing making "select `amount > 100`" and "assert `amount <= 100`" provably the same check rather than two opinions that happen to agree today. A test pins the split per kind per target, and a second asserts the declined builtins still exist — a decision resting on a fact nobody checks is how an RFC row rots. |

| 17 | *(2026-08-10)* **One Cube view per mart. §10's grouping question is settled, and the answer is neither of the two it offered.** §10 asked "per metric or per metric-grain group"; what shipped is per **mart**, and the emitter's own comment called it "the simplest defensible grouping" — true but weaker than the actual reason. **Per-grain is not expressible.** Two marts may share a grain (nothing forbids it, and the corpus now has a case), and merging them into one view means a Cube view over two cubes, which needs a `join_path` between them. bloomery models **no relationship between marts** — they are independently pre-joined at build time (RFC 0010 D1) — so the join would have to be invented, which is the move this project refuses everywhere from `unknown_member` sentinels to fabricated step references. **Per-metric buys nothing.** `measure_owners` already resolves each metric to exactly one mart, so a per-metric view would carry that mart's whole dimension set once per metric and fragment the subject area a view exists to present. The distinguishing case — two marts at one grain — was untested until this decision, because every fixture's marts happened to differ in grain; it now has a test, along with one asserting a view names exactly one cube, which is the structural half of the same argument. |

| 18 | *(2026-08-11)* **The dbt target defines the generic test it declares; the emitted project depends on no package.** D16's dbt half had to name *some* vehicle for `min`/`max`/`regex`/`reconcile`, and the only one dbt offers is `dbt_utils.expression_is_true` — which D16 itself noted "is a package, not core" without following the consequence. The consequence is that bloomery emitted a project **declaring a test it did not define**: `dbt compile` stops at ``'dbt_utils' is undefined. … install package dependencies with "dbt deps"``, for every project carrying one of those four clauses. Two fixes were available — emit a `packages.yml` pinning `dbt-labs/dbt_utils`, or define the test — and the second wins on the thing this compiler is for: artifacts are a pure function of the specs (RFC 0003), and a `packages.yml` makes the output complete only after a *network fetch* the compiler is forbidden from performing and the consumer may not be able to perform at all. So `macros/bloomery_expression_is_true.sql` is emitted, iff `schema.yml` declares the test. Three things follow. **It is `ArtifactKind.AUDIT`, not `CONFIG`** — it is the custom audit *body* for this target, the exact counterpart of the `audits/<name>.sql` file SQLMesh gets for the same kinds and from the same `audit_predicate`, which makes D16's "one function, two forms" symmetry structural rather than incidental. **The body is `dbt_utils`' `default__test_expression_is_true` minus the `column_name` branch bloomery never takes**, so the replaced semantics are preserved exactly — including that a NULL expression *passes*, `NOT NULL` being NULL and selecting no row, which is RFC 0016 D19's Kleene discipline arrived at from dbt's side. **The emission condition reads the emitted schema rather than re-deriving the entity filter**, so the project can neither declare the test without the macro nor carry it unused, and a test pins both directions. |
| 19 | *(2026-08-11)* **`dbt parse` does not validate that a declared test resolves; the e2e tier now compiles.** Recorded because the *tier built to catch this class of defect did not catch it*, and the reason is a documented overclaim rather than a missing fixture: RFC 0009's dbt cell asserted parse, and its module docstring claimed parse checks "whether a declared test is a thing dbt recognizes". It does not — parse validates the *shape* of a `schema.yml` entry and never resolves the macro behind the name. Demonstrated by renaming the test to `utter_nonsense_not_a_test`, which parse accepted in silence. Only `compile` renders test bodies, so D18's defect was invisible for as long as the tier stopped at parse. The parse pass stays (it is the cheap "dbt loads this at all" check, and the malformed-`config()` control belongs to it) and a compile pass joins it over every fixture. The build pass that D20 later added sits on top of both. |

| 20 | *(2026-08-11)* **The dbt target emits a real DAG, and keeps the naming policy owning namespaces. RFC 0009 D22 is closed — with both of its candidates, not one.** D22 found `dbt build` could not pass: models named their inputs literally (`FROM silver.order_item`), so dbt had no edges to order them by *and* materialized each into the profile's target schema while the `FROM` clause said `silver`. It offered two fixes with an "or" between them, and the "or" was the mistake — **neither is sufficient alone, and each repairs the other's cost.** `+schema` config alone places the relations and leaves ordering absent, so a gold model still races its silver input. `ref()`/`source()` alone orders the DAG but resolves names through dbt's schema config, which is the objection D22 raised: the naming port stops owning the namespace. Together: `ref()` for every relation bloomery emits and `source()` for bronze, `+schema: <ns>` per model directory, and a `generate_schema_name` override returning the configured schema **verbatim** — because dbt's default returns `<target.schema>_<custom>`, which would put models in `main_silver` while `sources.yml` (which never passes through that macro) still said `bronze`, honouring the policy in half the project. **How it is emitted.** Shared lowering is untouched: both targets build inputs as `exp.table_(relation, db=namespace)`, and the dbt emitter rewrites *table nodes only*, mapping `(namespace, relation)` to a reference. A namespace-less table is never rewritten, which is what keeps a CTE reference from being mistaken for a model; a table the map does not know is left literal rather than guessed at, because inventing a `ref()` for a relation bloomery did not write would name a model dbt cannot find. An SCD2 entity resolves to its **snapshot**, the only thing this target builds for it. **The cost, stated.** D5's port-abstraction proof compared the two targets' SELECTs byte for byte and can no longer: the `FROM` clauses differ by construction. It is restated, not weakened — resolve the references, drop namespaces, and the SQL is identical on every projection, join, cast and dialect quirk, so the entire difference between the targets is one documented substitution. The namespaces the comparison erases are asserted separately, against the `+schema` config and the override. |
| 21 | *(2026-08-11)* **The dbt e2e tier builds, and the thing a passing build proves least visibly gets its own control.** D20 has two halves and a green `dbt build` only obviously demonstrates one. Ordering is self-announcing — a gold model running before its silver input errors on a missing relation, and sabotaging the rewrite fails exactly the three fixtures that have a gold→silver edge and no others. Placement is not: with the `generate_schema_name` override deleted, every model still builds and every mart still finds its inputs, because `ref()` follows dbt wherever dbt put them. What breaks is only that the relations are no longer where the naming policy said — so that control asserts on the **warehouse's schema list**, not on the build's exit code, and requires `main_silver` to be present so a control that stopped discriminating fails rather than passes silently. Sources are seeded **empty** and the tier says so: structure — resolution, ordering, placement — fails identically on an empty warehouse, and arithmetic is the execution and equivalence tiers' claim, not restated here. |

| 22 | *(2026-08-11)* **The emitted `schema.yml` targets dbt `>=1.10,<2`, and the generic-test form is what sets that floor.** Found by a deprecation warning in D21's new build pass — "arguments to generic tests should be nested under the `arguments` property" — which looked like housekeeping and was not. **The two spellings are mutually exclusive**, measured on four real installs by compiling this repo's own emitted project rather than inferred from a changelog: flat compiles on 1.9.10, 1.10.22, 1.11.12 and 1.12.0 (warning from 1.10 on); nested is a **compilation error** on 1.9 and clean on all three later ones. So the choice is a compatibility range, not a style, and the only version that discriminates is 1.9 — which is what makes the nested form worth taking. Adopting it at a floor of 1.12 (the version that happened to be installed) would have cost three further minor versions for nothing; the floor is the version the feature actually arrived in. **What this exposed is bigger than the warning.** Which dbt versions the *emitted artifact* works on had never been written down anywhere. `dbt-core>=1.9` was a **dev** dependency — the test environment, not the product — unbounded, so CI silently tested against whatever resolved that day, while the artifact's own compatibility was a matter of nobody having asked. RFC 0008 §5.5 calls dbt "the compatibility target" without ever saying compatible with *what*. It now says: the dependency is bounded `>=1.10,<2` (as sqlmesh and metricflow already were — dbt was the one framework left floating), the range is stated in the emitter's docstring, and a test pins the emitted form with the measured matrix in its docstring, so the bound and the form can only move together. `not_null` is unaffected: it takes no arguments and stays a bare name on every version. |

## 12. Phasing

M2: SQLMesh emitter + DuckDB dialect (minimal `FULL` models). M3–M4 extend lowering
(recipes, audits). M5 adds mart build emission (RFC 0010); M6 the MetricFlow manifest
emitter (RFC 0013). M10 (renumbered per `_bloomery-metricflow-pivot.md` §8): Trino +
Postgres dialects, Cube emitter, dbt emitter — the port validation milestone; do not
defer past it (a second target discovered late means an IR rewrite, spec §11).
