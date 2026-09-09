# RFC 0038 — Measure semantic types and additivity algebra

- **Status:** ✅ Complete — §12's phases have all landed. `Additivity` is closed at six
  members and `additivity: additive` is checked rather than trusted, converting corpus
  cases 002 and 005 from `unguarded` to `refused` (RFC 0042 §8); `Ratio` is minted (D7,
  D8); `DistinctCount` is minted, with corpus case 007 as the case it converts, and
  `Snapshot` is answered — its declaration is `semi_additive` with a `rule`, so it stays in
  the closed set and out of the authored one (D11). D6 closed as derived, and §3's
  consolidation and §10's `Unit` question closed as met by the fields in place (D12).
  Execution's findings and the rows it proposed are in [`logs/T-0019.md`](../logs/T-0019.md),
  [`logs/T-0023.md`](../logs/T-0023.md), [`logs/T-0024.md`](../logs/T-0024.md) and
  [`logs/T-0028.md`](../logs/T-0028.md); nothing below has been amended to agree with what
  was built. **D3 is superseded in part** — its currency clause by D9 and its unit clause
  by D10, both proposed from T-0024, where executing it halted: the waiver it replaces was
  already deleted, and the fact a currency rule would read does not exist in the spec
  language. That fact is [RFC 0061](0061-declared-input-currency-for-conversion.md)'s.
  **Stays in the tree** as the root of a live sequence (`INDEX.md`): RFC 0058 argues in its
  aggregation-class vocabulary, and it is retired with it.
  Second in the semantic-correctness sequence; depends on
  [RFC 0037](0037-semantic-grain-model.md).
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
| 3 | `LOCKED` | **Superseded in part by D9 (currency) and D10 (units).** **Units participate in type checking; incompatible arithmetic is refused without an explicit declared conversion.** Existing currency behaviour becomes a proof-producing rule rather than a waiver that suppresses the mismatch. Locked because a waiver and a proof are indistinguishable at the call site and only one of them survives being asked "on what basis?". |
| 4 | `ASSUMED` | **Migration prefers conservative semantics over inference; no project silently gains a stronger additivity claim.** The stated risk is one-directional in the RFC and is not: a measure acquiring an origin grain can *newly refuse* an accepted project. Not `LOCKED` because the conservative default may prove unusable in practice — if so, execution departs with a migration note naming the projects it moves, rather than quietly widening. |
| 5 | `ASSUMED` | **This is a consolidation of vocabulary that already exists in three places, not a greenfield model.** `Additivity` and `SemiAdditiveRule` are on the metric, `Unit` on the column, currency in a transform. Execution should expect to *move* declarations rather than invent them, and the risk is a second spelling of a fact rather than a missing one. |
| 6 | `OPEN` | *(closed: derived, gated on the axis being exposed — logs/T-0019.md D-107, logs/T-0028.md.)* **Whether a measure's origin grain becomes authored syntax or stays derived from its entity.** Derived is smaller and matches what projects already write; authored is explicit and survives a measure that outlives its defining entity. Whichever is chosen decides §7's migration cost, so decide it before the migration is written, and log the decision with the shape of spec it implies. |
| 7 | `ASSUMED` | **A metric declaring `ratio:` declares `additivity: ratio`, and either half without the other is refused.** Until the member was minted the only spelling was `non_additive` with a `ratio:` block beside it, which made the additivity a field the compiler read for one thing and the author wrote for another — D5's second-spelling risk, installed as the only option. This newly refuses projects accepted yesterday, which §7 and D4 licence as a breaking change carrying a migration note rather than a silent tightening. Not `LOCKED` because the one-word migration is cheap to revisit; the alternatives — deriving the class from the block, or accepting both words — both leave the resolved IR disagreeing with the document that produced it. Bloomery's own generated `quality_quarantine_rate` was the first spec the guard refused, which states D2's reason rather than excepting it (see [`logs/T-0023.md`](../logs/T-0023.md), D-145, D-147). |
| 8 | `LOCKED` | **A site branching on additivity tests the property it means, never the member it happened to observe.** Fifteen sites across the emitters, the planner and the guardrails read `NON_ADDITIVE`, and twelve of them meant something else — nine "never emits a measure", three "a ratio specifically" — so minting `RATIO` narrowed twelve branches at once and no test in the tree could see it. `bloomery.ir.COMPUTED` is that property under its own name, and is already complete for all six members. Locked because it is what the `RESOLVABLE` canary's promise rests on: minting `DistinctCount` or `Snapshot` is an enum edit and a lowering, not a second sweep of fifteen judgement calls (see [`logs/T-0023.md`](../logs/T-0023.md), D-146). |
| 9 | `ASSUMED` | **Supersedes D3's currency clause.** D3 asks currency behaviour to become a proof-producing rule "rather than a waiver that suppresses the mismatch", and there is no waiver: RFC 0023 D5 deleted the `CONVERT_CURRENCY` marker, and what stands in its place is a declaration the guard reads. The mixed-currency refusal is unconditional and unwaivable; a conversion's output was checked against the catalog at resolution — every step's, which RFC 0061 §5.3 then narrowed to the last one, because comparing each refused a correct two-hop chain. What is missing is not a rule but the fact a rule would read — a conversion's declared *input*, which the spec language cannot express, so `{convert: [JPY, USD, paid_at]}` applies the yen rate to euros and compiles clean. That fact is [RFC 0061](0061-declared-input-currency-for-conversion.md)'s, and R009 is minted there rather than here. Added by execution 2026-09-06 — see [`logs/T-0024.md`](../logs/T-0024.md) (D-153, D-154, D-155, attempt 1). |
| 10 | `ASSUMED` | **Supersedes D3's unit clause, scoping it to the refusal it already has.** "Refused without an explicit declared conversion" reads on units as well as currency, and for units there is no conversion to declare: `convert` is currency-only by signature and by its `fx_rates:` backing, and `Unit` has two members. So §5's `Distance<km> + Distance<m>` has its refusal and nothing else, and naming an escape an author cannot write is worse than naming none. A declared unit conversion needs factors and a dimension algebra — a document, not a row, and unwritten. Added by execution 2026-09-06 — see [`logs/T-0024.md`](../logs/T-0024.md) (D-156, attempt 1). |
| 11 | `ASSUMED` | **`Snapshot` is declared as `semi_additive` with a `rule`; it has no authored word.** §4 asks a snapshot for "explicit time-selection semantics (first/last/as-of) before cross-time aggregation", and `semi_additive: {over: <axis>, rule: first|last}` is exactly that declaration: the axis and the selection, lowered by every emitter, and what converted corpus case 005. There is no request-level as-of, so a snapshot declared without a rule could only be refused — and D1's snapshot rule already refuses the `additive` claim and names `semi_additive` as the fix. A second word for one fact is the risk D5 names and D7 removed for ratios, and it converts no corpus case, which under RFC 0042 D5 is the reason not to mint it. `SNAPSHOT` stays in the closed set (D1) and out of `RESOLVABLE`; minted as syntax only for a consumer `semi_additive` cannot serve — a request-level as-of, or RFC 0058's rollup obligation on a measure declaring no rule. `DistinctCount`, by contrast, had a concrete consumer: a `count_distinct` measure was undeclarable under every word, and D2's own remedy named a route no author could take. Added by execution 2026-09-08 — see [`logs/T-0028.md`](../logs/T-0028.md). |
| 12 | `ASSUMED` | **§3 is met by the fields in place; the consolidated node is not built, and `Unit` stays on the column.** T-0019's D-108 deferred the single `Measure<…>` node to the first consumer needing it in one piece — RFC 0040's planner — and RFC 0040 and RFC 0041 both shipped reading the seven facts §3 lists where they are: `MetricIR.{grain, additivity, agg, expr, ratio, derived, semi_additive}` and `ColumnIR.{unit, currency}`. Every one is target-independent IR, which is what §3 demands; the consolidation is a refactor with no reader. §10's second question closes the same way: `Unit` is read through the column, as RFC 0061's conversion rule reads currency. Added by execution 2026-09-08 — see [`logs/T-0028.md`](../logs/T-0028.md). |

## 12. Phasing

The classes may land in order of demand — `Additive` and `Ratio` first, since RFC 0040's
planner needs exactly those two, and `DistinctCount`/`Snapshot`/`SemiAdditive` behind the
gate RFC 0041 §9 sets. What may not be staged is D1: the enum is closed from the first
commit even where a member has no lowering yet.
