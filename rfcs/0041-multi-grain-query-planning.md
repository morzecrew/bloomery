# RFC 0041 — Multi-grain aggregate-then-join query planning

- **Status:** 🚧 In progress — §13a's P1 and P2 have both landed. P1: two or more
  additive branches, shared dimensions by provenance, no filters
  ([`logs/T-0026.md`](../logs/T-0026.md)). P2: a filter and the row policy placed on every
  branch or the request refused, `order_by`/`limit` on the composed statement, and a ratio
  or `derived:` metric whose components live on different branches computed above the join
  ([`logs/T-0027.md`](../logs/T-0027.md)). The held-back classes (§8, D8) are decided per
  class — all three stay out of branch planning, directly and as components (T-0027 D-183;
  `DistinctCount`'s lowering is [`logs/T-0028.md`](../logs/T-0028.md)) — and nothing further
  is scheduled. Depends on [RFC 0040](0040-safe-rollup-planner.md), complete.
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

Both are answered elsewhere now, and the text above is kept unchanged so the movement is
visible. The second is settled by D13 — one rule for every dialect rather than one per
engine, which is what D9's composed join makes possible, and what §5's "defined
explicitly" was asking for. The first is still a document of its own: P1 carries no
filters at all, and §13a's P2 places one only where D12's identity test licenses it.

## 12. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | **Aggregate, then join — never join, then aggregate and hope.** The whole document exists for this one ordering, and the alternative is the silent double count it names in §1. A later optimization pass may not reorder across it without a preservation proof. |
| 2 | `LOCKED` | **Branch uniqueness at the result grain is structural, from the preceding aggregate node, never inferred from data.** An inferred uniqueness is a data-dependent fact standing in for a proof, which RFC 0039 D1 refuses by name; here it would silently re-admit the multiplicity the branch split removed. |
| 3 | `LOCKED` | **Derived metrics spanning branches are evaluated after operand rollup.** `SUM(a)/SUM(b)` and a row-level `a/b` aggregated afterwards are different numbers, and this is the concrete reason RFC 0038 D2 keeps a ratio as its operands. Reversing either strands the other. |
| 4 | `ASSUMED` | **Any unknown precondition refuses the whole request rather than the branch.** Partial answers across a multi-grain request are how a caller receives a plausible subset and reads it as the whole. Not `LOCKED` because a partial-result surface with explicit missing-branch semantics is a coherent thing to design later — it is simply not this. |
| 5 | `ASSUMED` | **Filters that cannot be placed safely refuse; a filter is never duplicated across branches on a name match.** Column name equality is not semantic equality, and the failure is a silently narrowed branch. The refusal stands until cross-branch filter semantics are designed. |
| 6 | `ASSUMED` | **The first implementation is deliberately unoptimized — redundant scans are acceptable, a merged branch is not.** Optimization is a later semantics-preserving pass, because the merge that looks obviously safe is exactly the one that reintroduces the fanout. |
| 7 | `OPEN` | *(superseded by D11.)* **The tie-breaking rule for a canonical minimal partition.** §3 requires the partition be deterministic and minimal under *documented* tie-breaking, and does not say what the tie-break is. Whoever implements it decides and documents it, since several defensible orders exist and only a written one is reproducible. |
| 8 | `OPEN` | **Whether `DistinctCount`, `Snapshot` and `SemiAdditive` enter branch planning at all in P1.** §8 gates them on their proof rules being independently sound. Decide per class, with the corpus case each one converts, rather than as a group. |
| 9 | `LOCKED` | *(its SQL spelling superseded by D18; the route it decides stands.)* **The branch join is bloomery's own SQL, over N single-mart requests MetricFlow renders unchanged.** Each branch is exactly a request the parity corpus accepts today — carrying R008 and the single-mart proof it already has — and bloomery wraps the branch results in a join of its own — written here as `FULL OUTER JOIN … ON a.k IS NOT DISTINCT FROM b.k` with a coalesced key projection, which **D18 replaces**: PostgreSQL will not plan that spelling, and the composition is a key domain and left joins. What this row decides is the *route* — bloomery composes, MetricFlow renders the branches — and that is unchanged. The alternative was measured, not imagined: handing MetricFlow one multi-metric request makes its `CombineAggregatedOutputsNode` render the same shape, correctly. It is refused because unifying two marts' differently-prefixed flattenings of one dimension (`order__country` against `order_item__order_country`) costs a row-level mart-to-mart join that MetricFlow validates rather than bloomery, and because its filter pushdown reaches into every branch through that join — the duplication D5 refuses on name-match grounds. Both hand the engine the authority for cross-branch identity, which RFC 0040 D6 exists to keep in bloomery. `LOCKED` because the route decides the node vocabulary, the public surface and every test written against them. |
| 10 | `LOCKED` | **What D9 supersedes, and how far.** Retired documents carry no grade and are read as `LOCKED`, so an executor meeting one halts; these are superseded here, by the author, before the branch. RFC 0010 D1 "no query-time joins on the common path" and RFC 0011 D4 "never join at plan time" hold for **unaggregated rows**, which is the fan-out they were written against, and no longer for a join of branch outputs already unique at the result grain (D2). RFC 0013 D6's mart-coverage precheck reads "all measures of **one branch** on one mart" instead of all measures of a request. RFC 0013 D1's render-only embedding re-admits exactly one hand-written generator, **above** MetricFlow's output rather than instead of it — RFC 0040 D10's "small and provable", and the smallest thing that can be. **RFC 0013 D3 is untouched**: no semantic model for a non-mart entity, and D9's route needs none. |
| 11 | `LOCKED` | **Measures partition by owning mart, from `measure_owners` — closing D7.** The emitter, Cube and the coverage precheck already agree on which mart serves a measure, cheapest `cost_hint` then lexicographic; a planner that chose its own partition would be a second owner of that answer, and a partition disagreeing with the emitter's is the divergence class this codebase keeps paying for. The tie-break D7 asked for is therefore inherited rather than invented, and one measure belongs to exactly one branch by construction. |
| 12 | `LOCKED` | **A dimension is the same dimension across branches when its provenance triple matches — `(source_entity, source_column, ref)` — never when its name does.** This is §2's "proven common join key" made checkable, and `_same_source` in `planner/coverage.py` already compares that triple for P2's refusals. A branch that cannot produce a requested dimension by identity gets P2's `not_flattened` refusal and its flatten remediation, never a join to go and fetch it. Name equality is not identity, which is D5's reason applied to the key instead of to the filter. |
| 13 | `ASSUMED` | *(superseded by D18.)* **Null-safe key equality, one key row per group, no re-aggregation pass.** Groups missing from a branch surface as NULL measures, not as dropped rows, and a NULL group key joins to the other branch's NULL group key rather than failing `NULL = NULL` and splitting in two. MetricFlow's own combine node merges that split afterwards with `GROUP BY COALESCE(…)` and `MAX(…)`; composing the join ourselves means never making the split. `ASSUMED` rather than `LOCKED`: a caller who wants missing groups dropped is asking for an inner join, which is a later option on the same node, not a different design. |
| 14 | `ASSUMED` | **R010 is minted for the branch join: branch outputs are unique at the result grain, structurally, from the preceding aggregate.** D2 is the claim; a rule id is what an accepted plan cites, and RFC 0039 D8 keeps the registry append-only. R011 follows for D12's cross-mart dimension identity if the join node needs its own citation separate from the branches'. RFC 0042 D5 then owes each of them a corpus case. |
| 15 | `ASSUMED` | **The public plan surface widens deliberately: `PlanNode` opens from four kinds to five with `JoinAggregates`, and `QueryPlan` gains `marts`.** `SemanticPlan` was published beside `QueryPlan` at RFC 0040 P1, so this is an API decision rather than a detail. `QueryPlan.mart` and `Explanation.mart` are single names and a composed plan has no single answer for them; both are retained, holding the lexicographically first of `marts`, and `render()` names every branch. Retained rather than removed because they are pinned by goldens a capability phase should not be rewriting; a later document may drop them once nothing reads them. |
| 16 | `ASSUMED` | **The parity generator asks multi-metric cross-mart requests, or the suite is blind to the phase it guards.** RFC 0040 D-128 kept it single-metric, which is why P2's own conversions were invisible until an audit widened it. The baseline is regenerated on the merge base and the `UnreachableAtGrain → accepted` conversions are the licensed change (RFC 0040 D11 makes an unlicensed class change a parity event). |
| 17 | `ASSUMED` | **`IS NOT DISTINCT FROM` is a declared `DialectFeature`, proven in the engine tier, not asserted from documentation.** It was executed on DuckDB and read about for Postgres and Trino; a planner that composes a join for three dialects on two readings is asserting a capability it has not seen. The feature enum is the existing place a dialect says what it can do, and an engine-tier test is where the claim stops being a citation. **Answered:** `tests/engines/test_branch_join_engines.py` executes the composed statement on all three, and the first thing it found was that the D13 spelling does not run on PostgreSQL at all — see D18. |
| 18 | `LOCKED` | **The composition is a key domain and left joins, not a full outer join — D13's semantics, in the only spelling all three dialects run.** PostgreSQL refuses `FULL JOIN … ON a IS NOT DISTINCT FROM b` outright: *"FULL JOIN is only supported with merge-joinable or hash-joinable join conditions"*. The predicate is supported there, as every reference says, and not in that position. **This project already knew it**: `emit/lower/reconcile.py` emits the same long spelling for the same reason, and `spec-schemas.md` says why in the same words — so what the engine tier bought here was a rediscovery, and the cheaper check was a grep for the construct (logs/T-0026.md, D-172). So the branches are CTEs, their keys are `UNION`ed into the domain of groups the answer has, and each branch is left-joined back onto that domain on `IS NOT DISTINCT FROM`. The null semantics are unchanged and now carried by two constructs that agree: `UNION` deduplicates NULL against NULL, and the left join matches a branch's NULL group to the domain's. Every group present in any branch appears exactly once, which is what the full outer join was for. `LOCKED` rather than `ASSUMED` because a later change back to the obvious shape would render on two dialects and fail to plan on the third (see logs/T-0026.md, D-171). |

## 13. Phasing

Not scheduled. The precondition is RFC 0040 being stable through at least P3, since branch
planning is single-measure planning applied N times plus a join — and if the single-measure
half is still moving, every branch inherits the movement.

## 13a. Phasing, restated

§13's precondition names RFC 0040 P3, and RFC 0040 D9 withdrew that phase — the text above
stays so the withdrawal is visible rather than tidied away, and this is the gate that
replaces it. **The precondition is what exists on `main` today:** RFC 0040 P1 and P2 landed
(`SemanticPlan` beside `QueryPlan`; `UnreachableAtGrain.refusal_reason` carrying
proof-backed refusals), the parity suite keyed per request at 706 requests — 449 accepted,
257 refused — RFC 0038's `Ratio` minted, and RFC 0039's registry live through R009. Nothing
in that list is scheduled work, so the gate is met.

**P1 — two additive branches, shared dimensions, no filters.** Partition by owner (D11);
every requested dimension present on every branch by identity (D12) or the whole request
refuses (D4); each branch rendered as today's single-mart request; the results composed by
D9's join with D13's null semantics. `SemanticPlan` gains `JoinAggregates` and a branch
structure citing R010 (D14, D15); the parity generator is widened and its baseline
regenerated (D16); the dialect feature is declared and executed (D17); a corpus case is
written or case 001 gains an expectation (RFC 0042 D5). This alone converts the request
`wide-marts.md` uses as its example of a refusal.

**P2 — filters, row policy and derived metrics across branches.** A filter is placed only
on branches whose mart carries its dimensions by identity, and otherwise the request is
refused (D5, D12). A cross-branch ratio is `SUM(num) / NULLIF(SUM(den), 0)` evaluated in
the wrapper above the join (D3) — the expression the lowering package already emits for
Cube. `order_by` and `limit` move to the composed statement, keeping RFC 0011 D4's
clamping and its injection rules. The row policy must reach **every** branch; that is the
shape `audit_scans` already tests, and it is merge-blocking.

**Held back — `DistinctCount`, `Snapshot`, `SemiAdditive`** (§8, D8). RFC 0040 P1's
`_plannable` guard already keeps a semi-additive measure out of `SemanticPlan`, so nothing
new is needed to keep them out here. This is also where RFC 0038 §12's two remaining
members finally get their lowering question answered, which is the dependency pointing
back the other way.

**Cube is untouched throughout.** It emits one cube per mart with no `joins`, and RFC 0058
D7 keeps cube-to-cube joins out. This is a planner capability, delivered through
`bloomery plan` and the Python port on the three dialects the render-only client speaks.

One documentation defect to fix in P1's docs move: `wide-marts.md` and the planner how-to
describe the refusal as the contract, which P1 changes, and they also cite a "capability
declaration" marking joins disabled by policy. No such declaration exists in the planner
package. The README planner sentence stays unpublished until the capability lands
(RFC 0045 D2).
