# RFC 0038 — Measure semantic types and additivity algebra

- **Status:** 📝 Draft — proposed, not started. Second in the semantic-correctness
  sequence; depends on [RFC 0037](0037-semantic-grain-model.md).
- **Scope:** Give measures explicit semantic types over value domain, origin grain,
  aggregation behaviour, units/currency, and derived-metric structure, and establish the
  minimum algebra needed for safe rollup decisions. Target-independent IR only.
- **Related:** [`src/bloomery/errors.py`](../src/bloomery/errors.py) —
  `AdditivityViolation`, `NonAdditiveWithoutComponents`, `CurrencyMismatch`;
  [`src/bloomery/ir/nodes.py`](../src/bloomery/ir/nodes.py) — `Additivity`,
  `SemiAdditiveRule`, `Unit`; RFC 0011 (native planner, retired), RFC 0023 (currency
  conversion, retired).
- **Non-goal:** Query planning. This RFC defines what must be proven, not how to build a
  plan.

---

## 1. Summary

A measure is not fully described by a SQL expression plus an aggregation function. Correct
aggregation depends on where the value originates and over which dimensions it is additive.

bloomery should model a measure conceptually as:

```text
Measure<ValueType, OriginGrain, AggregationSemantics, Unit>
```

This turns several existing guardrails into instances of semantic type checking and creates
a foundation for future safe planning.

## 2. Current state

Verified against the tree at `db0253e`. The vocabulary is **partly present and scattered**,
which is the finding that decides this RFC's shape:

- `Additivity` and `SemiAdditiveRule` are IR enums, carried on the *metric*.
- `Unit` and `TaxBasis` are IR enums, carried on the *column* — catalog metadata, reaching
  the IR through `ColumnIR`.
- Currency conversion shipped as a transform plus a refusal, not as a proof-producing rule.
- `AdditivityViolation` and `NonAdditiveWithoutComponents` police the metric layer;
  nothing joins them to a measure's origin grain.

So this RFC is largely a **consolidation with a type discipline**, not a greenfield model.
Where it adds genuinely new information, §7 says so.

## 3. Minimum semantic type

Each resolved measure must expose: value/logical type; origin grain; aggregation semantics;
unit, if declared; currency, if monetary; expression dependencies for derived measures; and
time semantics where aggregation depends on time.

These fields must be target-independent IR.

## 4. Additivity algebra

Initial closed set.

**`Additive`** — may be aggregated with its declared associative aggregation across any
proven rollup dimension not otherwise restricted. Item quantity, order revenue, shipping
amount at its true grain.

**`SemiAdditive`** — carries excluded axes:

```text
balance@{account, day}
aggregation: last
additive_over: account
non_additive_over: time
```

The planner may sum balances across accounts at one snapshot, and may not sum daily
balances across time.

**`NonAdditive`** — no generic rollup rule exists. A request requires a specific derived
operation or is refused.

**`Ratio`** — stores numerator and denominator semantics rather than treating the
materialized ratio as additive. Correct rollup is generally `SUM(numerator) /
SUM(denominator)`, not `AVG(materialized_ratio)`.

**`DistinctCount`** — carries the counted identity. Never additive across partitions unless
a later proof rule establishes disjointness.

**`Snapshot`** — point-in-time state, requiring explicit time-selection semantics
(first/last/as-of) before cross-time aggregation.

The implementation may stage these classes across releases, but the IR must not encode
future classes as arbitrary strings with target-specific interpretation.

## 5. Units and currency

Units are semantic types, not labels. The compiler must reject arithmetic that combines
incompatible units without an explicit declared conversion.

```text
Money<USD> + Money<EUR>     -> refusal without conversion
Distance<km> + Distance<m>  -> refusal or explicit conversion
Count<Order> / Count<Visit> -> Ratio with named operands
```

Existing currency conversion behaviour should become one proof-producing conversion rule
rather than a waiver that suppresses a mismatch.

## 6. Derived measures

Derived measures must retain dependency structure:

```text
conversion_rate = Ratio(numerator=converted_orders, denominator=sessions)
```

The resolved IR must make it possible for a later planner to aggregate operands
independently and apply the ratio after aggregation. A derived measure must not be lowered
so early that only opaque SQL remains.

### Type-checking rules

Incompatible units cannot be added or subtracted; compatible units may require an explicit
conversion; a ratio cannot inherit additive semantics merely because its result is numeric;
semi-additive restrictions survive aliases and derived expressions; aggregation cannot move
a measure to a finer grain; rollup permission depends on both RFC 0037's grain proof and
this RFC's aggregation semantics.

## 7. Backward compatibility

Existing authored specifications resolve to the new semantic type where their current
meaning is unambiguous. Where current syntax lacks information, the migration policy
prefers conservative semantics over guessing.

**No existing accepted project silently acquires a stronger additivity claim.** The
direction that needs watching is the opposite one: a project accepted today may be refused
once a measure carries an origin grain it did not previously declare, and that is a
breaking change requiring a migration note, not a silent tightening.

## 8. Diagnostics

Errors describe the semantic mismatch:

```text
metric gross_margin cannot be proven:
  revenue: Money<USD>
  cost:    Money<EUR>

No declared EUR -> USD conversion is available at the required time grain.
```

```text
metric account_balance cannot be summed across day:
  account_balance is semi-additive
  forbidden axis: time
```

## 9. Tests

Golden and type tests cover: additive rollup; forbidden refinement; currency mismatch;
explicit currency conversion; semi-additive time refusal; ratio preservation;
distinct-count non-additivity; derived metric dependency retention.

Property tests verify that wrapping or aliasing a measure never drops semantic
restrictions.

## 10. Unresolved questions

- **Where the origin grain is authored.** A measure's grain is today implied by the entity
  it is defined on. Whether it becomes explicit syntax or stays derived decides how much of
  §7's migration is mechanical.
- **Whether `Unit` moves from the column to the measure, or is read through it.** Both
  reach the same check; only one avoids two places to declare it.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | **The aggregation vocabulary is a closed typed set, never a target-interpreted string.** `Additive`, `SemiAdditive`, `NonAdditive`, `Ratio`, `DistinctCount`, `Snapshot`. Locked because the planner, the proof rules and every emitter branch on it: an open string set makes each target the authority for what a measure means, which is the arrangement this whole sequence exists to end. Staging the *implementation* across releases is fine; encoding a future class as a string is not. |
| 2 | `LOCKED` | **A ratio is stored as its operands, not as a materialized quotient.** `SUM(num)/SUM(den)` and `AVG(ratio)` differ, the second is what a numeric-looking column invites, and the difference is a plausible wrong number. This is also RFC 0041's precondition — a derived metric spanning two branches cannot be reconstructed after the operands are gone — so reversing it later strands that document. |
| 3 | `LOCKED` | **Units participate in type checking; incompatible arithmetic is refused without an explicit declared conversion.** Existing currency behaviour becomes a proof-producing rule rather than a waiver that suppresses the mismatch. Locked because a waiver and a proof are indistinguishable at the call site and only one of them survives being asked "on what basis?". |
| 4 | `ASSUMED` | **Migration prefers conservative semantics over inference; no project silently gains a stronger additivity claim.** The stated risk is one-directional in the RFC and is not: a measure acquiring an origin grain can *newly refuse* an accepted project. Not `LOCKED` because the conservative default may prove unusable in practice — if so, execution departs with a migration note naming the projects it moves, rather than quietly widening. |
| 5 | `ASSUMED` | **This is a consolidation of vocabulary that already exists in three places, not a greenfield model.** `Additivity` and `SemiAdditiveRule` are on the metric, `Unit` on the column, currency in a transform. Execution should expect to *move* declarations rather than invent them, and the risk is a second spelling of a fact rather than a missing one. |
| 6 | `OPEN` | **Whether a measure's origin grain becomes authored syntax or stays derived from its entity.** Derived is smaller and matches what projects already write; authored is explicit and survives a measure that outlives its defining entity. Whichever is chosen decides §7's migration cost, so decide it before the migration is written, and log the decision with the shape of spec it implies. |

## 12. Phasing

The classes may land in order of demand — `Additive` and `Ratio` first, since RFC 0040's
planner needs exactly those two, and `DistinctCount`/`Snapshot`/`SemiAdditive` behind the
gate RFC 0041 §9 sets. What may not be staged is D1: the enum is closed from the first
commit even where a member has no lowering yet.
