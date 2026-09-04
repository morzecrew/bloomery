# RFC 0040 — Safe rollup planner and SemanticPlan IR

- **Status:** 📝 Draft — proposed, not started. Fourth in the semantic-correctness
  sequence; depends on [RFC 0037](0037-semantic-grain-model.md),
  [RFC 0038](0038-measure-semantic-types-and-additivity.md) and
  [RFC 0039](0039-semantic-proof-ir.md).
- **Scope:** The first proof-producing query planner, answering single-measure requests
  across safe rollups while keeping unsafe wide-mart representations forbidden. Introduces
  a target-independent `SemanticPlan` produced only after every required obligation is
  proven.
- **Related:** [`src/bloomery/planner/`](../src/bloomery/planner/) — `MetricRequest`,
  `QueryPlan`, `UnreachableAtGrain`; RFC 0011 (native planner, retired), RFC 0012
  (CompiledSemantic, retired).

---

## 1. Summary

bloomery should distinguish **representation safety** from **query answerability**. A mart
may correctly refuse `shipping@Order` at `OrderItem` grain while the query planner safely
answers `shipping by customer.country`.

```text
MetricRequest -> semantic resolution -> proof/planning -> SemanticPlan
              -> target lowering -> SQL / MetricFlow / other target
```

SQL existence is never evidence of semantic validity.

## 2. Current state

A planner already exists: `MetricRequest` (`planner/request.py:351`) and `QueryPlan`
(`planner/result.py:117`), with `UnreachableAtGrain` as its refusal. This RFC does not
replace it wholesale — `SemanticPlan` is the layer that must exist *before* it, and P1
below is deliberately a no-capability-change re-expression so the two can be compared.

## 3. Initial capability

Phase 1 supports one measure; zero or more dimensions; additive measures; dimensions
reachable through grain-preserving relationships; safe rollup from measure origin to
requested result grain; existing valid temporal/as-of relationship semantics where
required. Unsupported shapes are refused, not delegated optimistically.

## 4. SemanticPlan IR

Illustrative nodes:

```text
Scan(entity)
PreservingJoin(relationship, optional_as_of)
Aggregate(input_grain, output_grain, measures, dimensions)
ConvertUnit(...)
Project(...)
Filter(...)
```

Every multiplicity-changing node references the proof that authorizes it. **A plan without
proofs is invalid IR** — not a plan that is merely unexplained.

## 5. Planning rule

For a single additive measure: resolve its origin grain; resolve requested dimensions;
compute functional dependencies and required relationship paths; reject any path that
refines or duplicates the measure; determine requested output grain; prove additive rollup
from origin to output; construct `SemanticPlan`; lower the plan to a target.

### Accepted example

```text
shipping@Order : Money<USD>, Additive
Order -> Customer : many_to_one
Customer.country : dimension
```

Request `shipping by customer.country`:

```text
Scan(Order)
  -> PreservingJoin(Customer)
  -> Aggregate(input_grain=Order, output_grain=CustomerCountry,
               measure=shipping, aggregation=sum)
```

The plan is safe even though a wide `OrderItem` mart containing repeated `shipping` remains
forbidden.

### Refused example

Request `shipping by item.sku`. If reaching `Item` requires `Order -> OrderItem`, the path
is cardinality-expanding relative to `shipping@Order`:

```text
REFUSED
No proof permits refining shipping from Order to OrderItem.
```

No target planner is invoked.

## 6. Target lowering

Target adapters receive a validated `SemanticPlan`. They may choose syntax and execution
mechanisms but must preserve the logical operators and may not introduce an unproven
multiplicity-changing join. A target that cannot faithfully represent the plan refuses that
target rather than silently rewriting semantics.

MetricFlow or another semantic engine may remain an execution and lowering backend. It is
not the source of bloomery's correctness decision, and bloomery must be able to explain the
plan before target lowering.

## 7. The mart contract does not move

No change to *measure grain must strictly equal mart grain* for embedding measures in a
wide mart under the current mart semantics.

A future RFC may define safe pre-aggregated mart constructs, but it must be explicit.
Query-time planning is not a back door that changes mart meaning.

## 8. Tests

Each phase's accepted shapes, each phase's refused shapes, and — the load-bearing one — a
parity suite asserting that every request refused before a phase is still refused after it,
except where a named proof rule deliberately converts a class.

## 9. Unresolved questions

- **What happens to `QueryPlan`.** Whether `SemanticPlan` lowers to it, replaces it, or
  sits beside it is a real fork and P1 exists partly to answer it.
- **Whether refusal messages change for requests that are already refused.**
  `UnreachableAtGrain`'s wording is a shipped surface; a refutation is a better message and
  a moved golden.

## 10. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | **Representation safety and query answerability are separate obligations, proven separately.** A mart refusing `shipping@Order` at `OrderItem` grain and a planner answering `shipping by customer.country` are both correct simultaneously. Locked because conflating them in either direction is a shipped defect: one way silently widens marts, the other way refuses answerable questions forever. |
| 2 | `LOCKED` | **A `SemanticPlan` whose multiplicity-changing nodes do not reference a proof is invalid IR, not merely unexplained.** The distinction decides whether the check can be skipped under time pressure. Every join that can duplicate a row carries its authorization or the plan does not typecheck. |
| 3 | `LOCKED` | **The mart contract does not move in this document.** Grain equality for embedded measures stands unchanged; a safe pre-aggregated mart construct needs its own RFC. Locked because query-time planning is precisely the plausible-looking back door into mart semantics, and the pressure to take it arrives exactly when the planner starts working. |
| 4 | `LOCKED` | **Target lowering may not introduce an unproven multiplicity-changing join; a target that cannot represent the plan refuses that target.** Rewriting rather than refusing is how a semantics-preserving plan becomes a wrong number in one emitter and not the others — the divergence class this codebase has paid for repeatedly, and here it would be invisible because the plan was proven. |
| 5 | `ASSUMED` | **P1 re-expresses today's accepted requests as `SemanticPlan` with no capability change.** It is what makes the §8 parity suite meaningful — a phase that added capability and re-expression together could not tell a regression from an intended widening. Departing means finding P1 cannot represent something already accepted, which is itself the finding. |
| 6 | `ASSUMED` | **MetricFlow and any other semantic engine stay execution backends, never the correctness authority.** bloomery explains the plan before lowering. Not `LOCKED` because it is a positioning statement this document cannot enforce alone; D4 is the enforceable half. |
| 7 | `OPEN` | **Whether `SemanticPlan` lowers to the existing `QueryPlan`, replaces it, or sits beside it.** Three shapes with different migration costs and different answers to "what does `bloomery plan` print". P1 exists partly to answer this from contact with the code; log the decision with what P1 found. |
| 8 | `OPEN` | **Whether refusals for already-refused requests may change wording.** A refutation is a better message than `UnreachableAtGrain`'s, and it moves a shipped golden. Decide whether the parity suite pins the *outcome* or the *text*, and say so before the first rule lands. |

## 11. Phasing

- **P1 — plan IR only.** Represent existing trivially safe requests as `SemanticPlan`; no
  capability expansion.
- **P2 — single-hop rollup.** One proven `many_to_one`/`one_to_one` dimension path.
- **P3 — transitive rollup.** RFC 0037's closure for multi-hop paths.
- **P4 — qualified temporal rollup.** Reuse as-of proof rules for SCD2 dimensions.

Each phase preserves prior refusals except where a new documented proof rule deliberately
converts one class to acceptance.
