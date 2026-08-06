# RFC 0007 — Plan: spec diff and change classification

- **Status:** 📝 Draft
- **Scope:** The plan stage (`bloomery/plan/`) and the public
  `plan(old_ir | None, new_ir) -> Plan`: a pure structural diff of two `ProjectIR`s
  that classifies every change (`ADDITIVE | WIDENING | RENAME | RESTATING | BREAKING`),
  computes backfill scope and downstream metric impact from IR edges, and enforces the
  expand/contract rule (`ContractViolation`). Covers explicit rename via
  `renamed_from:` and one IR addition (`ColumnIR.renamed_from`). Does not cover how
  IRs are built (RFC 0003/0004/0005), what executes a plan (orchestration is a
  non-goal, spec §1.3), or type-lattice definitions (RFC 0004).
- **Related:** [`rfcs/_original-smelter-spec.md`](_original-smelter-spec.md) §5.5, §8;
  RFC 0002 §5.4 (`PlanError` in the hierarchy), RFC 0003 (IR being diffed,
  `MetricIR.depends_on`, determinism), RFC 0004 (widening lattice),
  RFC 0009 (`evolution_v1..v5` fixtures, property tests).

---

## 1. Summary

`plan()` diffs two frozen IRs and returns a `Plan`: an ordered tuple of classified
`Change` records, a `BackfillScope`, and `downstream_impact` computed from the IR's own
`depends_on` edges — no external lineage, no I/O. `plan(None, ir)` is an initial deploy
(everything ADDITIVE); `plan(ir, ir)` is empty. Renames are explicit
(`renamed_from:` in the spec) — never inferred. Dropping or narrowing a field a live
metric still references raises `ContractViolation`; every other change, including
BREAKING ones, is *classified and returned*, not refused — the caller decides.

## 2. Motivation

Specs evolve; the dangerous changes are the ones that look harmless. A recipe swap
keeps the column name and type but changes what every historical number means; a field
drop compiles fine until the quarter-end metric built on it returns NULL. The control
plane needs a machine-readable answer to "what does applying this spec do?" *before*
anything executes — which entities backfill, whether history restates, which metrics
move — and it needs that answer computable from the two IRs alone, because the compiler
has no I/O (spec §1.2) and no external lineage system to ask. The IR already carries
the dependency edges (RFC 0003 D6 territory: product-facing outputs live in the IR);
`plan()` is the function that reads them.

## 3. Current state

Greenfield. RFC 0003 defines `ProjectIR` as value-like precisely so this stage can be a
structural diff, and `MetricIR.depends_on` is explicitly "kept for `plan()`'s
downstream-impact computation" (RFC 0003 §5.1). One addition is needed:
`ColumnIR.renamed_from: str | None` (§5.3 below) — an amendment to RFC 0003's
`ColumnIR`, fingerprint-included like any other field.

## 4. Goals / Non-goals

**Goals**

- `ChangeClass` exactly as spec §5.5; every diffable difference maps to exactly one
  class, deterministically.
- Pure function of `(old_ir | None, new_ir)`; output ordering lexicographic
  (RFC 0003 determinism) so plans are byte-comparable in tests and CI.
- Expand/contract enforced here — `ContractViolation` before a destructive plan is
  ever returned.

**Non-goals**

- Fuzzy rename inference (similarity scores, type+position heuristics) — determinism
  and auditability beat convenience; a wrong rename guess silently rewrites history.
- Executing or scheduling anything (backfills, migrations) — the `Plan` is the
  interface; orchestration is the caller's job (spec §1.3).
- Diffing artifacts or SQL text — the IR is the semantic unit; artifact diffs are what
  golden tests are for (RFC 0009).

## 5. Design

### 5.1 Public shape

```python
class ChangeClass(StrEnum):
    ADDITIVE   = "additive"     # new optional column / metric — metadata-only
    WIDENING   = "widening"     # decimal(10,2) → decimal(12,2), per RFC 0004 lattice
    RENAME     = "rename"       # field identity preserved via renamed_from
    RESTATING  = "restating"    # same column, different meaning — backfill
    BREAKING   = "breaking"     # drop / narrow / grain / key / scd / materialization

@dataclass(frozen=True, slots=True)
class Change:
    entity: str | None          # None for project-level subjects (metrics)
    subject: str                # "field:unit_price" | "metric:net_revenue" | "entity:order_item"
    change_class: ChangeClass
    detail: str                 # human-readable, deterministic wording
    old: str | None             # compact repr of the old value, where meaningful
    new: str | None

@dataclass(frozen=True, slots=True)
class BackfillScope:
    entities: tuple[str, ...]   # sorted; entities whose stored rows must be recomputed
    restates_history: bool      # True iff any RESTATING change is present

@dataclass(frozen=True, slots=True)
class Plan:
    changes: tuple[Change, ...]             # sorted by (entity or "", subject, change_class)
    backfill_scope: BackfillScope
    downstream_impact: tuple[str, ...]      # affected metric names, sorted
    @property
    def has_changes(self) -> bool: ...
    @property
    def breaking(self) -> tuple[Change, ...]: ...

def plan(old: ProjectIR | None, new: ProjectIR) -> Plan: ...
```

`plan(None, new)` classifies every entity, field, and metric ADDITIVE with an empty
backfill scope — the initial-deploy case. `plan(ir, ir)` returns an empty plan; this is
property-tested for arbitrary generated projects (RFC 0009), which is what makes the
SQLMesh replan-is-a-no-op e2e assertion (spec §7.6) an end-to-end restatement of a
property the diff already guarantees structurally.

### 5.2 The diff walk

Entities match by name; within an entity, columns match by name with `renamed_from`
providing the identity bridge (§5.3); metrics match by name. Classification per matched
pair, in precedence order:

1. **Entity level:** a change to `grain`, `key`, `scd`, or `materialization` is
   BREAKING at `entity:<name>` — these redefine what a row *is*, so no column-level
   class can soften them. Column diffs within the entity are still computed and
   reported (they drive backfill scope).
2. **Type:** widening per the RFC 0004 lattice → WIDENING; narrowing or incompatible →
   BREAKING. `optional → required` is a narrowing (BREAKING); a *new* required field is
   likewise BREAKING — historical rows cannot satisfy it; add it optional, backfill,
   then tighten.
3. **Semantics (RESTATING):** same column name and type, but a changed `canonical:`
   link, changed `recipe_id`, changed transform chain, or changed source path
   (`SourceIR` lowering). The number's meaning changed while its shape didn't — the
   entity joins `backfill_scope.entities` and `restates_history` becomes true.
4. **Presence:** in `new` only → ADDITIVE; in `old` only → BREAKING (subject to §5.4).

Dropping a metric is BREAKING but *legal* — BREAKING is a classification the caller
acts on, not a refusal. The only refusal in this stage is `ContractViolation` (§5.4).

### 5.3 Explicit rename

An entity field may declare `renamed_from: <old_name>` in the spec; it is carried onto
`ColumnIR.renamed_from`. The differ classifies the pair as one RENAME (identity
preserved — no drop, no add, no backfill) after validating that `<old_name>` exists in
`old` and is not simultaneously present in `new`. A `renamed_from` whose old name is
absent from `old` — including `old is None` — is a stale annotation and raises
`RenameTargetMissing` (a `PlanError`). Consequence: the annotation is one-shot by
construction. Once a plan applies, the next `old` contains only the new name, so a
leftover annotation fails the very next `plan()` — staleness detection *forces* the
spec cleanup rather than politely tolerating drift.

Without the annotation, a rename is what it structurally is: a drop (BREAKING) plus an
add (ADDITIVE). Heuristic inference (match by type and position, edit distance) was
considered and rejected: a wrong guess silently maps history onto an unrelated column,
and no confidence threshold makes that auditable. One line of YAML is cheap;
un-restating a mis-inferred rename is not.

### 5.4 Expand/contract enforcement

Before the `Plan` is returned, the differ checks every dropped or narrowed field
against metric references:

- referenced by a metric **reachable in `new`** → `ContractViolation`;
- referenced by a metric that was reachable in `old` and is *absent from `new` in the
  same plan* → `ContractViolation` too. Removing the metric and its field together is
  the classic "delete the evidence" move; the contract requires the metric's removal to
  land (and be seen by consumers) in a prior version. Deprecation must come first.

`ContractViolation` is a `PlanError` (RFC 0002 §5.4) naming the field, the referencing
metrics, and the required sequence. Reference edges come from `MetricIR.depends_on` —
the same edges that feed `downstream_impact`, so the check costs one extra set
intersection over data the stage already walks.

### 5.5 Worked example: `evolution_v1..v5`

The RFC 0009 fixture sequence and its expected classifications (M5's acceptance
criterion, spec §11). Baseline v1: `order_item(order_id, line_no, unit_price
decimal(10,2) canonical direct, quantity)`, metric `gross_revenue`.

| Step | Spec change | Expected plan |
| --- | --- | --- |
| `plan(None, v1)` | initial deploy | every entity/field/metric ADDITIVE; empty backfill; `breaking == ()` |
| v1 → v2 | add optional `discount`; widen `unit_price` to `decimal(12,4)` | ADDITIVE `field:discount`; WIDENING `field:unit_price`; no backfill |
| v2 → v3 | `quantity` → `qty` with `renamed_from: quantity`; add metric `net_revenue` (uses `discount`) | RENAME `field:qty`; ADDITIVE `metric:net_revenue`; no backfill |
| v3 → v4 | `unit_price` mapping switches recipe `direct` → `from_total` (source column withdrawn) | RESTATING `field:unit_price`; backfill `{order_item}`, `restates_history=True`; `downstream_impact = (gross_revenue, net_revenue)` |
| v4 → v5 | remove metric `net_revenue`; `scd: type1 → type2` on `order_item` | BREAKING `metric:net_revenue`; BREAKING `entity:order_item` (scd) — returned, not raised |
| v4 → v5′ (negative) | drop `discount` while `net_revenue` still references it | `ContractViolation` raised; no `Plan` returned |
| `plan(vN, vN)` | identity, every N | empty plan (property-tested) |

The v3 rename doubles as the staleness proof: replaying v3's spec against v3's own IR
(annotation still present, `quantity` gone from `old`) raises `RenameTargetMissing`.

## 6. Tests

- Unit: every classification branch — one minimal IR pair per row of the §5.2
  precedence order, plus both `ContractViolation` arms, `RenameTargetMissing`
  (including `old is None`), and rename-with-both-names-present.
- Fixtures: `evolution_v1..v5` asserted exactly as the §5.5 table, as byte-compared
  plan snapshots (ordering is part of the contract).
- Property (Hypothesis, RFC 0009): `plan(ir, ir)` is empty for all generated projects;
  `plan(a, b)` classifying nothing BREAKING implies `b`'s columns ⊇ `a`'s
  metric-referenced columns; `plan` output is invariant under input construction order
  (determinism).

## 7. Docs

How-to `pages/how-to/evolve-a-spec.md`: the expand/contract sequence with the
`evolution` fixtures as the running example, including the deliberate
`ContractViolation` and the `renamed_from` one-shot lifecycle. Reference page for
`Plan`/`Change`/`ChangeClass`. The docs must not promise rename inference — state
plainly that unannotated renames are drop+add.

## 8. Out of scope

- **Plan application/serialization format** — the control plane consumes the `Plan`
  object in-process; a wire format would freeze the shape before M5 validates it
  (same doctrine as RFC 0003 §8 for the IR). Escape hatch: a versioned export once a
  second consumer exists.
- **Catalog diffs** — `plan()` compares project IRs; a changed catalog manifests as
  changed resolved columns/recipes and is classified through them. Diffing catalogs
  directly is a vertical-governance concern, not a tenant-plan concern.
- **Cost/row-count estimates in `backfill_scope`** — requires profiling data the
  compiler doesn't have (spec §1.3); the scope names entities, the caller prices them.

## 9. Risks

- *Explicit-rename friction*: authors will forget `renamed_from` and see a scary
  BREAKING+ADDITIVE pair. Mitigation: when a dropped and an added field in the same
  entity share a type, the `ContractViolation`/BREAKING detail text mentions
  `renamed_from` as the likely fix — a hint in the message, never a guess in the
  classification.
- *RESTATING over-triggering* on semantically-neutral transform-chain refactors
  (e.g. reordering commuting transforms). Accepted for v0.1: false backfills are
  visible and cheap relative to silent restatements; a normalization pass over
  transform chains can tighten this later without changing the contract.
- *Entity-level BREAKING masking useful column detail* — mitigated by still emitting
  column-level changes alongside the entity-level record (§5.2 rule 1).

## 10. Unresolved questions

- None blocking. Implementation is free to settle `detail` string wording and the
  exact `subject` grammar, provided both are deterministic and the §5.5 table's
  classifications hold verbatim.

## 11. Decisions

| # | Decision |
| --- | --- |
| 1 | `ChangeClass` is exactly spec §5.5's five members: ADDITIVE, WIDENING, RENAME, RESTATING, BREAKING. Every diffable difference maps to exactly one. |
| 2 | `plan(old_ir \| None, new_ir)` is a pure structural diff of two `ProjectIR`s — no external lineage, no I/O. `plan(None, ir)` = all ADDITIVE (initial deploy); `plan(ir, ir)` = empty, property-tested (RFC 0009). |
| 3 | Renames are explicit only: `renamed_from: <old>` in the spec (carried as `ColumnIR.renamed_from`, an RFC 0003 amendment). No heuristic inference — determinism and auditability beat convenience. A stale annotation (old name absent from `old`, including `old is None`) raises `RenameTargetMissing` (`PlanError`), which forces the annotation to be dropped after one applied plan. |
| 4 | RESTATING = same column name+type with changed semantics: changed `canonical:` link, `recipe_id`, transform chain, or source path. It always adds the entity to `backfill_scope` with `restates_history=True`. |
| 5 | Expand/contract is enforced in this stage: dropping/narrowing a field referenced by a metric reachable in `new`, or by an old-reachable metric that vanished in the same plan, raises `ContractViolation` (`PlanError`). Deprecation must land in a prior version. This is the stage's only refusal — BREAKING changes are classified and returned, not raised. |
| 6 | `Plan` = ordered `Change` tuple + `BackfillScope` + `downstream_impact` (from `MetricIR.depends_on`) + `has_changes`/`breaking` conveniences. All ordering lexicographic per RFC 0003 — plans are byte-comparable. |
| 7 | Entity-level `grain`/`key`/`scd`/`materialization` changes are BREAKING at the entity subject (they redefine the row); column diffs are still reported alongside. Type changes follow the RFC 0004 lattice: widening = WIDENING, narrowing (incl. optional→required) and new required fields = BREAKING. |

## 12. Phasing

Ships in M9 (renumbered again per `_bloomery-metricflow-pivot.md` §8; previously M7 per
`_bloomery-changes.md` D10 — marts/planner/hydration moved ahead because evolution is a
month-two problem): "done when `evolution_v1..v5` classified
correctly; contract violation caught." Depends on the IR (M1, RFC 0003) and on
resolution/typing filling `recipe_id`, `depends_on`, and resolved `materialization`
(M2–M4). The `ColumnIR.renamed_from` field lands with M1's IR shape so no IR migration is
needed at M7. Mart diffs (RFC 0010) classify with the same machinery: mart
grain/base/flatten changes are BREAKING at the mart subject; measure-list growth is
ADDITIVE.
