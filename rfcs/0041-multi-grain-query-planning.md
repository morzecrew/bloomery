# RFC 0041 — Multi-grain aggregate-then-join query planning

- **Status:** 📝 Draft — proposed, **not scheduled**. High semantic complexity; this should
  not start until single-measure proof planning is stable. Depends on
  [RFC 0040](0040-safe-rollup-planner.md).
- **Scope:** Answer requests containing measures from different origin grains by
  independently aggregating each safe branch to a common result grain and joining only
  after aggregation.
- **Related:** [RFC 0038](0038-measure-semantic-types-and-additivity.md) — the
  operand-preserving derived-measure IR this document depends on absolutely.

---

## 1. Summary

Naively joining facts of different grains before aggregation is a primary source of silent
double counting.

```text
revenue  @ Order
shipping @ Order
quantity @ OrderItem
```

Requested by `customer.country`, a single joined relation at `OrderItem` grain duplicates
`revenue` and `shipping`. The query is nevertheless answerable:

```text
Order branch:      aggregate revenue, shipping -> Country
OrderItem branch:  aggregate quantity          -> Country
join branches at Country
```

This is **aggregate-then-join**, never join-then-hope.

## 2. Preconditions

Multi-grain planning is allowed only if every measure independently has a proof to the
requested result grain; each branch can be aggregated without using another branch's finer
grain; branch outputs have a proven common join key and result grain; joining branch
outputs does not reintroduce multiplicity; and null semantics for missing branch groups are
explicit.

If any condition is unknown, refuse.

## 3. Metric partitioning

The planner groups requested measures by compatible semantic source plan. A partition is
not based only on identical entity names: measures may share a branch when the planner
proves that the joins required before aggregation preserve every measure in that branch.

The algorithm is deterministic and prefers a canonical minimal partition under documented
tie-breaking.

## 4. Branch plan

Each branch starts at a source capable of representing its measures at their true grain;
performs only grain-preserving joins needed for dimensions and filters; applies conversions
required before aggregation; aggregates to the common requested grain; and emits one row
per result-grain key. Only then may branches be joined.

```text
Branch A
  Scan(Order); Join(Customer)   # preserving
  Aggregate Country: SUM(revenue), SUM(shipping)

Branch B
  Scan(OrderItem); Join(Order); Join(Customer)   # many_to_one, many_to_one
  Aggregate Country: SUM(quantity)

JoinAggregates(grain=Country, left=Branch A, right=Branch B)
```

## 5. Join of aggregate branches

The join operator asserts that each input is unique at the common result grain. **That
uniqueness is structural from the preceding aggregate node, never inferred from warehouse
data.**

The initial implementation uses a deterministic full-outer semantic join so groups present
on only one side are not lost, with target-specific null handling defined explicitly.

## 6. Filters

Filters are dangerous because applying them at different branches can change meaning.
Initial rule: a filter may be pushed into a branch only if its referenced dimensions are
functionally available there without unsafe refinement; otherwise the request is refused
until cross-branch filter semantics are explicitly designed.

Do not duplicate a filter across branches merely because columns share a name.

## 7. Derived metrics

Derived metrics spanning branches are computed **after** their operands reach the common
result grain:

```text
revenue_per_item = revenue / quantity
```

becomes `SUM(revenue@Order) / SUM(quantity@OrderItem)` at the requested result grain, not a
row-level expression before branch aggregation. RFC 0038's operand-preserving IR is
mandatory here.

## 8. Measure classes held back

`DistinctCount`, `Snapshot` and `SemiAdditive` are not part of P1 unless their proof rules
are already implemented and independently sound. The planner must not generalize additive
branch planning to them by accident.

## 9. Cost is secondary to soundness

The first planner may generate redundant scans or subqueries. Optimization is a later
semantics-preserving pass over `SemanticPlan`. No optimization may merge branches before
aggregation unless it proves that doing so preserves all measure grains.

## 10. Tests

Mixed `Order`/`OrderItem` additive measures answered at a common coarser grain; each branch
independently proven; branch-join uniqueness asserted structurally; filters that cannot be
safely placed refused; derived metrics evaluated after operand rollup; held-back measure
classes still refused. Property tests should attempt to construct a partition that merges
two branches and assert the merge is refused without a preservation proof.

## 11. Unresolved questions

- **Cross-branch filter semantics.** §6 refuses rather than defines them, deliberately, and
  the definition is a document of its own.
- **Full-outer join null semantics per target.** "Defined explicitly" is the requirement;
  what the definition *is* differs per engine and is not settled here.

## 12. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | **Aggregate, then join — never join, then aggregate and hope.** The whole document exists for this one ordering, and the alternative is the silent double count it names in §1. A later optimization pass may not reorder across it without a preservation proof. |
| 2 | `LOCKED` | **Branch uniqueness at the result grain is structural, from the preceding aggregate node, never inferred from data.** An inferred uniqueness is a data-dependent fact standing in for a proof, which RFC 0039 D1 refuses by name; here it would silently re-admit the multiplicity the branch split removed. |
| 3 | `LOCKED` | **Derived metrics spanning branches are evaluated after operand rollup.** `SUM(a)/SUM(b)` and a row-level `a/b` aggregated afterwards are different numbers, and this is the concrete reason RFC 0038 D2 keeps a ratio as its operands. Reversing either strands the other. |
| 4 | `ASSUMED` | **Any unknown precondition refuses the whole request rather than the branch.** Partial answers across a multi-grain request are how a caller receives a plausible subset and reads it as the whole. Not `LOCKED` because a partial-result surface with explicit missing-branch semantics is a coherent thing to design later — it is simply not this. |
| 5 | `ASSUMED` | **Filters that cannot be placed safely refuse; a filter is never duplicated across branches on a name match.** Column name equality is not semantic equality, and the failure is a silently narrowed branch. The refusal stands until cross-branch filter semantics are designed. |
| 6 | `ASSUMED` | **The first implementation is deliberately unoptimized — redundant scans are acceptable, a merged branch is not.** Optimization is a later semantics-preserving pass, because the merge that looks obviously safe is exactly the one that reintroduces the fanout. |
| 7 | `OPEN` | **The tie-breaking rule for a canonical minimal partition.** §3 requires the partition be deterministic and minimal under *documented* tie-breaking, and does not say what the tie-break is. Whoever implements it decides and documents it, since several defensible orders exist and only a written one is reproducible. |
| 8 | `OPEN` | **Whether `DistinctCount`, `Snapshot` and `SemiAdditive` enter branch planning at all in P1.** §8 gates them on their proof rules being independently sound. Decide per class, with the corpus case each one converts, rather than as a group. |

## 13. Phasing

Not scheduled. The precondition is RFC 0040 being stable through at least P3, since branch
planning is single-measure planning applied N times plus a join — and if the single-measure
half is still moving, every branch inherits the movement.
