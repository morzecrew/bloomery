# RFC 0010 — Marts and role-playing dimensions

- **Status:** 📝 Draft
- **Scope:** The wide-mart gold layer as a first-class spec and IR concept: the `marts:`
  spec kind, build-time flattening of relationships and date roles, `MartIR`, and
  `DimensionRef` — the role-playing dimension model consumed by the mart builder, the
  native planner (RFC 0011), and the Cube emitter (RFC 0008). Covers mart definition and
  validation; does not cover query planning over marts (RFC 0011), the serialized planner
  artifact (RFC 0012), or the mart-level guardrails' error taxonomy (RFC 0006, amended).
  New modules: `bloomery/marts/`, spec additions in `bloomery/spec/`, IR additions in
  `bloomery/ir/`.
- **Related:** [`rfcs/_bloomery-changes.md`](_bloomery-changes.md) D2, D3; RFC 0002 (spec
  layer), RFC 0003 (IR), RFC 0006 (grain guard moves to compile time), RFC 0008 (SQLMesh
  emits the mart build), RFC 0011 (planner selects from marts).
- **Origin:** `_bloomery-changes.md` — the decision to own query planning, made tractable
  by constraining gold to wide pre-joined marts.

---

## 1. Summary

Gold is one wide, pre-joined mart per (grain × subject area): dimensions are flattened in
at build time, so there are no query-time joins on the common path. Marts are declared in
a fifth spec kind, validated at compile time (grain equality, fan-out-safe flatten paths,
collision-free prefixes), and lowered into `MartIR` — one definition read by both the
SQLMesh emitter (which builds the table, joins included) and the native planner (which
queries it, joins excluded). Role-playing dimensions are modeled once as `DimensionRef`
(dimension + role) and lowered per consumer.

## 2. Motivation

Every classic semantic-layer failure — join fan-out, role-playing dimensions, symmetric
aggregates, multi-fact root guessing — is a query-time-join problem
(`_bloomery-changes.md` §0). Because bloomery's operator controls the physical layer, the
join is moved to build time where the compiler can verify it: a mart's joins are checked
against declared relationship cardinalities once at compile, instead of being re-planned
per query. The planner then degrades to "assemble a GROUP BY," and the thing that builds
the table and the thing that queries it read the same `MartIR`, so they cannot disagree
about grain or columns.

## 3. Current state

RFCs 0002/0003 define the four spec kinds and the entity-level IR; relationships with
cardinality already exist in both (`Relationship`, `RelationshipIR`). The scaffold is in
place; no compiler code exists yet, so this lands as new design, not a migration.

## 4. Goals / Non-goals

**Goals**

- `marts:` spec kind, strict-parsed per RFC 0002 conventions.
- Deterministic flattening: relationship chains → prefixed columns; date roles → bucketed
  `<role>_<bucket>` columns.
- `MartIR` + `DimensionRef` in the IR, fingerprint-covered (RFC 0003).
- Compile-time refusal of fan-out (`GrainViolation`, `FanoutRisk` — RFC 0006).

**Non-goals**

- Query planning and mart *selection* — RFC 0011 (`bloomery/planner/select.py`).
- Cross-mart queries — refused by design, not planned (RFC 0011 hard rule).
- Automatic mart derivation from metrics — marts are authored; inference would reintroduce
  the silent choices this package exists to refuse.
- Incremental mart rebuild strategy — `materialization` semantics from RFC 0002 D7 apply
  to marts as to entities; anything smarter is gated on the wide-marts-are-affordable
  assumption (`_bloomery-changes.md` §11.1).

## 5. Design

### 5.1 Spec kind

A document self-identified by `marts_version: 1` (RFC 0002 §5.5 conventions; at most one
per project, optional — a project without marts compiles silver only):

```yaml
marts_version: 1
marts:
  order_items:
    grain: order_item            # must equal the base entity's grain
    base: order_item
    flatten:
      - {via: item_of_order,     prefix: order_}
      - {via: order_of_customer, prefix: customer_}
      - {date: order_date, role: ordered}    # → ordered_day … ordered_year
      - {date: ship_date,  role: shipped}
    measures: [gross_revenue, discount, net_revenue, quantity]
    partition_by: [days(ordered_day)]
    cost_hint: 3                 # relative scan cost, tie-breaking only; default 1
```

`flatten` steps are a discriminated union on `via` vs `date`. A `via:` step names a
declared relationship whose *from* side is the base entity or a previously flattened
entity (chains flatten transitively: `order_of_customer` is reachable because
`item_of_order` was flattened first — order of steps is authored and meaningful, RFC 0003
D4). `prefix` is required on `via:` steps; flattened columns are `<prefix><column>`.

### 5.2 Date roles

A `date:` step declares a role-playing time dimension: `{date: order_date, role: ordered}`
expands at build time into bucket columns `ordered_day`, `ordered_week`, `ordered_month`,
`ordered_quarter`, `ordered_year` — exactly the `TimeGrain` set of RFC 0011 minus `hour`
(hourly marts are storage-hostile; `hour` remains a planner-side truncation on `_day`
columns if ever needed — deliberately not expanded). The source column must be `date` or
`timestamp` typed. A mart may declare the same role at most once; two roles may share a
source column (rare but legal).

### 5.3 `DimensionRef`

```python
@dataclass(frozen=True, slots=True)
class DimensionRef:
    dimension: str                # "date", "customer_region", ...
    role: str | None = None       # "ordered" | "shipped" | None

    @property
    def qualified(self) -> str:
        return f"{self.role}_{self.dimension}" if self.role else self.dimension
```

Lives in `bloomery/ir/` (RFC 0003's tree; fingerprint-covered). Lowerings per consumer:
the mart builder joins/derives once per role, aliased; the planner reads the flattened
columns (no join — the problem does not exist there); the Cube emitter emits aliased join
paths per role. An unqualified reference to a dimension with multiple roles is
`AmbiguousDimension` naming the available roles — raised by whichever consumer resolves
the reference (planner: RFC 0011 D6).

### 5.4 `MartIR`

```python
@dataclass(frozen=True, slots=True)
class MartIR:
    name: str
    grain: str                                  # entity name
    base: str                                   # entity name
    columns: tuple[MartColumnIR, ...]           # sorted by name; the flattened wide schema
    measures: tuple[str, ...]                   # metric names, sorted
    dimensions: tuple[MartDimensionIR, ...]     # sorted by qualified name
    partition_by: tuple[PartitionSpec, ...]
    materialization: Materialization
    cost_hint: int

@dataclass(frozen=True, slots=True)
class MartColumnIR:
    name: str                                   # post-prefix physical name
    type: LogicalType
    source_entity: str
    source_column: str
    ref: DimensionRef | None                    # set for role/date-derived columns

@dataclass(frozen=True, slots=True)
class MartDimensionIR:
    ref: DimensionRef
    column: str                                 # the flattened column serving this ref
```

`ProjectIR` gains `marts: tuple[MartIR, ...]` (sorted by name). Flattening is computed at
IR build in `bloomery/marts/` — spec in, wide schema out, pure — so every consumer sees
the *resolved* column set, never the flatten recipe.

### 5.5 Validation (compile errors, batched with guardrails)

1. `grain` must equal the base entity's grain — a mart is a fact table at exactly its
   base grain. Measures listed must have `grain == mart.grain`, else `GrainViolation`.
   *Note:* `_bloomery-changes.md` D2 says "equal to or coarser" in prose but its own
   example makes coarser the violation; this RFC resolves the contradiction to strict
   equality — the safest reading, and the one its example and `fanout_trap` encode.
   Relaxation (pre-aggregated finer-grain measures) is deferred until a fixture demands it.
2. Every `via:` must name a declared relationship with `many_to_one` or `one_to_one`
   cardinality reachable from the already-flattened entity set; `one_to_many` is
   `FanoutRisk` (RFC 0006).
3. Post-prefix column collisions are errors, never auto-renamed.
4. `date:` roles must be unique per mart; source columns date/timestamp typed.
5. Measures must be reachable metrics (RFC 0005) whose entities are the mart's base.

The SQLMesh emitter lowers each `MartIR` to a gold-layer model
(`NamingPolicy.relation(name, Layer.GOLD)`): base entity SELECT joined once per `via:`
step and once per date role, projecting the flattened columns — the only place joins are
ever emitted for a mart.

## 6. Tests

Unit: flattening (chains, prefixes, collisions, role expansion), every validation rule.
Fixtures (RFC 0009, amended): `role_playing_dates` — grouping by `ordered_month` vs
`shipped_month` gives different, correct numbers, executed on DuckDB; `fanout_trap` —
compile-time `GrainViolation` (plus retained execution proof); `multi_mart_refusal` —
planner-side, RFC 0011. Property: flattening is deterministic (permuted spec dict order →
identical `MartIR`); every mart column traces to exactly one source entity column.

## 7. Docs

Concept page "The wide-mart gold layer" (why no query-time joins, the classic-problems
table from `_bloomery-changes.md` §0); reference page for the `marts:` spec kind; the
role-playing explanation with the `ordered_*`/`shipped_*` example.

## 8. Out of scope

- **Snowflaked / multi-hop dimension logic beyond relationship chains** — chains cover
  the domain; anything deeper is a modeling smell the compiler should not paper over.
- **Mart-level SCD** — marts rebuild from silver; history lives in silver SCD2 entities.
- **Cost-based mart selection beyond `cost_hint`** — a statistics-driven optimizer is a
  different product; `cost_hint` + lexicographic ties is deterministic and sufficient.

## 9. Risks

- *Wide marts may be unaffordable at scale* (storage / rebuild time) —
  `_bloomery-changes.md` §11.1's assumption; if it breaks, incremental mart strategy needs
  design before M5 ships. The spec shape (partition_by, materialization) already carries
  what that design would need.
- *Strict grain equality may prove too strict* (legitimate pre-aggregated measures) —
  accepted; loosening a refusal is backward-compatible, tightening one is not.

## 10. Unresolved questions

- Whether `MartDimensionIR` should also expose non-date flattened attributes as
  requestable dimensions automatically (current answer: yes — every flattened column is a
  dimension; the planner filters to what requests actually name). Implementation may
  narrow this if the surface proves noisy.

## 11. Decisions

| # | Decision |
| --- | --- |
| 1 | Gold is wide pre-joined marts declared in a fifth spec kind (`marts_version: 1`); no query-time joins on the common path. One `MartIR` is read by both the mart builder (SQLMesh, joins at build) and the planner (no joins) — they cannot disagree. |
| 2 | Measure grain must strictly equal mart grain; coarser or finer is `GrainViolation`. Resolves D2's prose/example contradiction to the strict reading; relaxation is a future additive change. |
| 3 | `flatten` via-steps require declared `many_to_one`/`one_to_one` relationships (else `FanoutRisk`); chains flatten transitively in authored order; prefixes mandatory; collisions are errors, never auto-renames. |
| 4 | Date roles expand to exactly `{day, week, month, quarter, year}` bucket columns named `<role>_<bucket>`; `hour` is deliberately not expanded. |
| 5 | `DimensionRef(dimension, role)` is the single role-playing model, defined in the IR and lowered per consumer (build-time join aliasing; planner column reads; Cube aliased join paths). |
| 6 | Mart flattening is resolved at IR build (`bloomery/marts/`, pure): consumers see the wide schema, never the recipe. `ProjectIR.marts` is fingerprint-covered. |
| 7 | Marts are optional: a project without a `marts:` document compiles silver only; the planner then refuses everything with `UnreachableAtGrain` (no marts, no serving surface). |
| 8 | `cost_hint` (int, default 1) is a tie-breaking scan-cost hint only; selection ties break lexicographically (RFC 0003 determinism). |

## 12. Phasing

Lands in M5 (`_bloomery-changes.md` D10) together with RFC 0011 — spec + flattening +
`MartIR` first (this RFC), planner second, since selection needs the catalogue to exist.
The mart-level guardrails (RFC 0006 amendments) land in M4 as validation rules with the
mart spec parsing stubbed, or with M5 if sequencing favors it; the acceptance fixtures are
`fanout_trap` (M4) and `role_playing_dates` (M5).
