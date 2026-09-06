# RFC 0040 — Safe rollup planner and SemanticPlan IR

- **Status:** ✅ Complete — §11a's P1 and P2 have both landed and P3-P4 are withdrawn, so
  nothing here is in progress. P1 is `SemanticPlan` beside `QueryPlan`, built from the same
  resolution the explanation reads, with §8's parity suite capturing 531 requests before
  anything moved; **nothing lowers from the plan yet** — MetricFlow still plans from the
  request, which is what makes P1 a re-expression with no capability change (D5). P2 is
  proof-backed refusal: a dimension another mart carries is refused with the obligation and
  the spec edit that discharges it rather than an `UnknownMember` guess. **§11's phasing was
  revised before P2 began** — see §11a and D9-D11: the single-hop rollup had no route to SQL
  and no route from a spec, so the capability arrives as RFC 0041's aggregate-then-join
  (D10). §4's `PreservingJoin` and `ConvertUnit` and §5's cross-entity rule are unbuilt and,
  under §11a, are not this document's to build.

  **Retained rather than retired**, on the same reasoning `INDEX.md` applies to 0037: 0041
  and 0058 argue from this document's vocabulary. 0058 §5 places its safety condition
  across four documents — grain and functional dependencies in 0037, aggregation class in
  0038, derivation in 0039, the proof-producing planner here — so what this one supplies is
  the rollup-proof half the condition is stated in terms of, and deleting it would leave
  0058 arguing from a premise no longer in the tree. It is retired with the last of its
  dependants.
  Execution's findings and the rows it proposes are in [`logs/T-0021.md`](../logs/T-0021.md)
  and [`logs/T-0022.md`](../logs/T-0022.md); no prose below has been amended to agree with
  what was built — §5 and §11 keep their text and carry pointers to what replaced them. Fourth in the
  semantic-correctness sequence; depends on [RFC 0037](0037-semantic-grain-model.md),
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

> This example is the semantic argument, not a phase. `PreservingJoin` has no route to SQL
> in this codebase and no route from a spec that does not already flatten the hop, so
> §11a builds none of it; the shape it illustrates arrives, if it does, through RFC 0041
> (D9, D10).

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
| 8 | `OPEN` | **Superseded by D11.** **Whether refusals for already-refused requests may change wording.** A refutation is a better message than `UnreachableAtGrain`'s, and it moves a shipped golden. Decide whether the parity suite pins the *outcome* or the *text*, and say so before the first rule lands. Answered during P1 — the suite pins the outcome and the exception class, never the wording — and closed by D11, which adds the case P1 could not need. The grade stays `OPEN` because the table is append-only and a grade records what was asked of an executor at the time; the supersession marker above is what a reader acts on (see logs/T-0021.md, D-119). |
| 9 | `LOCKED` | **P2 produces proof-backed refusals, not query-time joins; §11 is superseded by §11a.** The single-hop rollup §11 asked for has no route to SQL — the manifest emitter pins "never a semantic model for a non-mart entity", so a `PreservingJoin` has no relation to reach and bloomery has no second generator to reach it with — and no route from a spec either: across every buildable fixture, zero marts have an unflattened single hop from their own grain, because `flatten: {via: …}` already settles that join at build time. The capability would be a second mechanism for something this design does once, earlier, with the fan-out proof already discharged. Locked because it re-scopes this document and re-gates RFC 0041 and RFC 0058. Added by execution 2026-09-06 — see logs/T-0022.md (D-132 and D-133, attempt 1). |
| 10 | `ASSUMED` | **When cross-grain capability is wanted, it arrives as RFC 0041's aggregate-then-join, never as a `PreservingJoin` over unaggregated rows.** Joining two results already aggregated to a common grain cannot fan out, so the generator that does it is small and provable; joining raw rows before aggregation is the primary source of silent double counting and needs the most machinery to get right. Building the dangerous half first, to serve a class with no instances, is the wrong order. Not `LOCKED` because it is a sequencing preference, departable if RFC 0041 proves harder than the narrow join. Added by execution 2026-09-06 — see logs/T-0022.md (D-132, attempt 1). |
| 11 | `LOCKED` | **A refusal that changes exception class is a parity event, even when no capability was added.** D8 settled that the suite pins outcome and class rather than wording; this closes the gap that leaves. Converting `UnknownMember` into a refutation reads as "just a better message" and is exactly the change someone waves through under time pressure, while `parity_baseline.tsv` is the only thing that would have noticed. A phase that moves a class edits the baseline and names the rule in the commit. Added by execution 2026-09-06 — see logs/T-0022.md (D-134, attempt 1). |

## 11. Phasing

> **Superseded by §11a** (D9). Kept verbatim: P2–P4 as written below are what execution
> found unbuildable, and deleting them would erase the disagreement that produced the
> revision.

- **P1 — plan IR only.** Represent existing trivially safe requests as `SemanticPlan`; no
  capability expansion.
- **P2 — single-hop rollup.** One proven `many_to_one`/`one_to_one` dimension path.
- **P3 — transitive rollup.** RFC 0037's closure for multi-hop paths.
- **P4 — qualified temporal rollup.** Reuse as-of proof rules for SCD2 dimensions.

Each phase preserves prior refusals except where a new documented proof rule deliberately
converts one class to acceptance.

## 11a. Revised phasing (supersedes §11)

- **P1 — plan IR only.** Landed. Unchanged from §11.
- **P2 — proof-backed refusal.** A request this project cannot serve is refused with a
  refutation naming the obligation and the spec edit that discharges it, in place of
  `UnknownMember`'s nearest-name guess. No capability expansion, no query-time join, no
  invariant moved. This is where RFC 0039 §13's parked rules first hold a planner's
  question (D9).
- **P3 and P4 are withdrawn as written.** Transitive and qualified-temporal hops inherit
  P2's missing execution story wholesale; there is nothing to phase until D10's generator
  question is answered.
- **Capability, when wanted, is RFC 0041's** — aggregate each branch to a common grain and
  join only after, which is safe by construction and needs a far smaller generator than a
  `PreservingJoin` over raw rows (D10).

The rule the phases share is unchanged and now has D11 behind it: each phase preserves
prior refusals except where a named proof rule deliberately converts a class, and a
conversion — of outcome *or* of exception class — edits `parity_baseline.tsv` and says
which rule did it.
