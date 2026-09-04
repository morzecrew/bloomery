# RFC 0037 — Semantic grain model and functional dependencies

- **Status:** ✅ Complete — landed in `src/bloomery/semantic/`, and **retained rather than
  retired**: 0038, 0039, 0040, 0041, 0042, 0053 and 0058 all argue from this document's
  vocabulary, and deleting it would leave every one of them arguing from a premise that is
  no longer in the tree — the same reason a 🚧 RFC is retired whole rather than in part.
  It is retired with the last of its dependants. Execution's findings and the rows it
  proposes are in [`logs/T-0017.md`](../logs/T-0017.md); nothing below has been amended to
  agree with what was built. **Root of the semantic-correctness
  sequence** 0037 → 0038 → 0039 → 0040 → 0041, with 0042 runnable in parallel from day
  one, 0043 gated on it, and 0044 on the proof vocabulary being stable. The invariant the
  whole sequence preserves: **bloomery may expand the set of accepted queries only by
  adding explicit proof rules, and no existing refusal is weakened to make room.**
- **Scope:** Replace grain-as-name/equality reasoning in semantic planning with an explicit
  grain model derived from entity keys, declared relationships, and mechanically derivable
  functional dependencies. New IR below the planner and above target lowering; no change to
  mart flattening rules, no new query plans, no emitter surface.
- **Related:** [`src/bloomery/errors.py`](../src/bloomery/errors.py) —
  `GrainViolation`, `FanoutRisk`, `HistoricalFanout`, `AdditivityViolation`,
  `UnreachableAtGrain`; [`src/bloomery/planner/`](../src/bloomery/planner/) —
  `MetricRequest`, `QueryPlan`; RFC 0023 (as-of joins, retired); RFC 0010 (marts,
  retired); RFC 0011 (native planner, retired).
- **Origin:** Follow-up design for evolving bloomery from a validator into a semantic type
  checker and proof-producing planner without weakening its refusal semantics.

---

## 1. Summary

bloomery already knows facts that imply grain relationships: entity keys, relationship
cardinalities, measure origins, and SCD validity. Today several safety decisions reduce
those facts to local checks, including strict grain equality for measures embedded in
marts (`GrainViolation`, RFC 0010 D2).

This RFC introduces a first-class semantic model for **grain identity**, **functional
determination**, and **safe rollup reachability**.

The key distinction is:

- `CanRepresent(relation)` asks whether a physical/logical relation can expose a value
  without making ordinary downstream aggregation unsafe.
- `CanAnswer(query)` asks whether bloomery can construct a semantics-preserving plan for a
  requested result.

This RFC builds only the shared vocabulary required by both questions.

## 2. Motivation

A measure at `order` grain cannot be copied into an `order_item` mart without duplication.
The current refusal is correct and remains correct.

However, `shipping@order` can still be safely aggregated by `customer.country` if the model
proves:

1. each order determines exactly one customer;
2. country is determined by that customer;
3. shipping is additive across orders.

String inequality between `"order"` and `"country"` cannot express that proof. A semantic
grain model can.

## 3. Current state

Verified against the tree at `db0253e`:

- **The mart rule is grain string equality.** `GrainViolation` (`errors.py:381`) carries
  `offending_measures` as `(measure, its own grain)` pairs and fires when a mart measure's
  grain "does not strictly equal the mart grain".
- **Cardinality refusals already exist and are separate.** `FanoutRisk` (`errors.py:406`)
  is a `via:` flatten over a declared `one_to_many`; `HistoricalFanout` (`errors.py:414`)
  is a mart flattening or based on an `scd: type2` entity, and its docstring records *why*
  the two are distinct — the second's `cardinality:` is typically already correct.
- **The planner has a request and a plan** (`planner/request.py:351`,
  `planner/result.py:117`) and its own `UnreachableAtGrain` (`errors.py:680`).
- **Additivity is modelled at the metric level**, not as a measure-carried semantic type —
  `AdditivityViolation` and `NonAdditiveWithoutComponents` (`errors.py:365`, `429`).

None of these share a grain vocabulary. Each reduces the same underlying facts to its own
local check, which is what this RFC exists to change.

## 4. Goals / Non-goals

**Goals**

- Structural grain identity, not a display string.
- Functional dependencies represented explicitly, each with a stated basis.
- A deterministic closure that returns derivations rather than booleans.
- Directional rollup reachability answerable without SQL generation.

**Non-goals**

- Relaxing any mart rule. §7.
- Generating query plans. That is RFC 0040's job, on top of this.
- Inferring cardinality from warehouse data. §12.
- A general-purpose relational theorem prover. §12.

## 5. Design

### 5.1 Grain is semantic identity, not a display string

Introduce an immutable `Grain`/`GrainRef` representation whose identity is derived from
entity determinants. Human-readable entity names remain available for diagnostics.

A first implementation may restrict authored entity grains to the existing entity grain
declaration while representing the normalized determinant internally.

### 5.2 Relationships contribute functional dependencies only when justified

A declared `many_to_one` or `one_to_one` relationship from `A` to `B` establishes that an
`A` row determines the referenced `B` identity, subject to existing historical/SCD
qualifications.

A `one_to_many` or `many_to_many` relationship does not establish preservation of the left
grain for flattening or rollup.

### 5.3 Historical relationships are conditional dependencies

An SCD2 target is not functionally determined by an equality key alone. A valid `as_of`
anchor plus validity semantics may establish a time-qualified dependency.

The grain system must consume the same semantic fact the current `HistoricalFanout`
guardrail uses rather than inventing a second interpretation.

### 5.4 Rollup reachability is directional

Define a relation such as:

```python
can_roll_up(source_grain, target_grain, context) -> Proof | Refusal
```

The direction means that values originating at `source_grain` may be aggregated to
`target_grain` under the supplied semantic context. It must not be implemented as arbitrary
graph reachability.

### 5.5 Refinement is never implicit

Moving a measure from a coarser grain to a finer grain is not a rollup. No implicit
operation may duplicate a measure merely because SQL can perform the join.

`shipping@order → order_item` therefore remains unsafe unless a future explicit semantic
operation defines a different meaning. This RFC defines no such operation.

### 5.6 Proposed IR

Illustrative shape, not a frozen Python API:

```python
@dataclass(frozen=True, slots=True)
class GrainRef:
    determinants: tuple[EntityKeyRef, ...]


@dataclass(frozen=True, slots=True)
class FunctionalDependency:
    determinant: GrainRef
    dependent: SemanticRef
    basis: DependencyBasis
```

`DependencyBasis` identifies why the compiler believes the dependency: entity key; declared
`many_to_one`; declared `one_to_one`; qualified SCD2/as-of relationship; mechanically
derived transitive closure. No heuristic inference is permitted.

### 5.7 Composite grains

The representation must support composite grains even if initial authored syntax does not
expose every form: `{order_id, line_id}`, `{product_id, warehouse_id, day}`,
`{account_id, snapshot_day}`.

A composite grain is not a concatenated string. Determinants are canonicalized and compared
structurally.

### 5.8 Functional closure

Provide a deterministic operation conceptually equivalent to:

```text
closure(grain, project) -> determined semantic references + derivations
```

Used to answer: may `customer.country` be grouped from an order-grain source without
fanout? Does a requested dimension preserve the source row identity? Which relationships
are required to reach a dimension?

Every member of the closure carries a derivation, not only a boolean.

## 6. Tests

1. direct many-to-one closure;
2. transitive many-to-one closure;
3. one-to-many does not enter closure in the unsafe direction;
4. SCD2 without anchor does not establish dependency;
5. SCD2 with valid anchor does;
6. composite determinant equality is order-independent;
7. graph traversal is deterministic across authored order and hash seed;
8. current mart grain refusals remain unchanged.

Property tests generate small relationship graphs and verify that accepted dependencies
never cross a cardinality-expanding edge without an explicit rule.

## 7. Interaction with marts

This RFC does **not** change the mart contract. A wide mart still refuses a measure whose
origin grain is not the mart grain when embedding it would make normal aggregation unsafe.

The grain model should eventually become the implementation substrate for that refusal, but
replacing the implementation must preserve observable behaviour and golden diagnostics
unless a later RFC amends them explicitly.

## 8. API boundary

The grain engine sits below request planning and above raw target lowering. It must not
depend on SQLMesh, dbt, Cube, MetricFlow, or SQL syntax. Target-specific planners may
consume proven grain facts; they may not manufacture them.

## 9. Refusals

Structured refusals must at minimum distinguish: unknown grain; no functional path;
cardinality-expanding path; unqualified historical path; ambiguous path whose alternatives
imply different semantics; attempted refinement of a measure to a finer grain.

## 10. Unresolved questions

- **Whether `GrainRef` can be reached without an IR version bump.** The determinant
  representation is new IR; whether it rides existing nodes or adds one decides how much of
  §7's "preserve observable behaviour" is mechanical. Settled by the first implementation
  spike, not by this document.
- **Where the closure is cached, if anywhere.** Determinism (D6) constrains the answer;
  performance does not yet have a measurement to argue from.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | **Grain identity is structural, never a display string.** Every downstream document in this sequence compares grains — the planner's rollup proof, the measure's origin, the branch join key — so a string-equality identity here would be re-derived, differently, in four places. Human-readable names stay for diagnostics only. Reversing this after 0038–0041 land invalidates their comparisons rather than merely changing this one. |
| 2 | `LOCKED` | **Refinement is never implicit: a coarser measure is not moved to a finer grain because a join exists.** This is the guarantee the whole sequence rests on, and the one a planner is most tempted to break — SQL will happily produce the row, and the number is plausible and wrong. Any future operation that duplicates a measure must be an explicitly named semantic act with its own RFC, never a fallback. |
| 3 | `LOCKED` | **`one_to_many` and `many_to_many` contribute no dependency in the preserving direction, and no heuristic ever contributes one.** The closure admits only entity keys, declared `many_to_one`/`one_to_one`, qualified as-of relationships, and transitive closure over those. Locked because the value of every proof built on top is exactly the weakest fact admitted here. |
| 4 | `ASSUMED` | **The as-of qualification reuses `HistoricalFanout`'s semantic fact rather than restating it.** Two readings of SCD2 validity in one compiler is the divergence this project has paid for before — one body, two callers. Not `LOCKED` because the guardrail's fact may prove to be shaped for a mart question specifically, in which case execution extracts the shared half and logs the departure. |
| 5 | `ASSUMED` | **`can_roll_up` is directional and is not graph reachability.** Undirected reachability would accept `order → order_item` on the strength of an edge existing, which D2 refuses. Departing means finding a direction-carrying formulation that is not a relation over `(source, target, context)`. |
| 6 | `ASSUMED` | **Closure output carries a derivation per member, not a boolean.** RFC 0039 needs the derivation to build a proof tree and RFC 0042 needs it to pin a case to a rule; producing booleans now would mean re-deriving the reason later, from the answer. |
| 7 | `LOCKED` | **Determinism, on RFC 0003's terms: sorted tuples, no sets where order reaches output, byte-stable serialization across processes and hash seeds.** The closure is a graph walk, which is where nondeterminism enters this codebase most easily, and its output is destined for evidence artifacts. |
| 8 | `OPEN` | **Whether the mart's existing `GrainViolation` is re-implemented on this substrate, and when.** §7 requires observable behaviour and golden diagnostics to survive either way, so this is a sequencing question execution may answer: re-implement early and carry the risk of moving a shipped refusal, or leave the mart check alone until the planner work has exercised the substrate. Decide it with the first phase that has a reason to touch the mart path, and log the decision. **Superseded by D13**, which answers it. |
| 9 | `LOCKED` | **The grain model is derived from `ProjectIR`, never stored in it.** A grain computed on demand from `EntityIR.key` adds no field to any IR node, so `bloomery_ir_version` does not move, no project fingerprint does, and no golden does — which is what turns §7's "preserve observable behaviour" from an argument into a `git diff`. Locked because every document downstream inherits the constraint: 0038's measure types and 0039's proof IR are the next things tempted to put themselves on a node, and the first one that does spends the whole corpus's fingerprints. Verified by compiling every fixture × target × dialect on both sides of the branch — 251 cells, byte-identical. See `logs/T-0017.md` (D-086). |
| 10 | `ASSUMED` | **The as-of fact lives in `bloomery.semantic.qualify_as_of`, and the mart guard reads it from there.** D4's second branch is the one that happened: the guardrail's version was shaped for a mart question — it took a `ViaStep` and a `step_path` and returned `GuardrailError` leaves — so the shared half moved down and `_historical_leaf` now dispatches on `AsOfState`, keeping only the wording. Anything in this sequence that needs to know whether a historical hop is qualified calls that function; a second reading of SCD2 validity is the divergence D4 exists to prevent. See `logs/T-0017.md` (D-087). |
| 11 | `LOCKED` | **A dependency carries the column it was reached *through*, and an ambiguous path is defined over joined column pairs rather than relationship names.** §5.6's shape cannot express §9's ambiguity refusal: a billing and a shipping address are both `address.address_id` as a dependent and differ only in the determinant-side column, while one relationship declared in both directions is two names for one meaning. Comparing names alone gets both wrong, in opposite directions — a false refusal and a false proof. Locked because 0039's proof tree and 0042's cases both ask "is this the same route", and the answer has to be one answer. See `logs/T-0017.md` (D-088). |
| 12 | `ASSUMED` | **Nothing is cached.** §10's second question, answered as "nowhere, until a measurement argues otherwise". D7 makes a memo keyed on a graph walk a correctness question rather than a performance one, and there is still no measurement to argue from. `dependencies` is exposed separately from `closure` so a caller with many questions builds the set once without the model holding state. See `logs/T-0017.md` (D-090). |
| 13 | `ASSUMED` | **The mart's `GrainViolation` stays on grain-string equality until a planner has exercised this substrate.** Supersedes D8. The substrate has no consumer until RFC 0040, so moving a shipped refusal onto it now carries the whole of §7's risk for none of its benefit. RFC 0040 is the first phase with a reason to touch the mart path and is where the question is asked again. `ASSUMED` rather than `OPEN`: the question has been answered once, and re-answering it needs a reason. See `logs/T-0017.md` (D-089). |
| 14 | `ASSUMED` | **A cardinality-expanding refusal is classified by undirected connectivity, on the refusal path only.** The obvious implementation — re-close admitting `one_to_many` in its declared direction — is near-dead code, because such a relationship's `via` lands on the target's *foreign* key rather than its own, so the target never unfolds. D5 is unchanged and unweakened: it forbids *answering* the rollup question by reachability, and this runs only after the closure has already refused, turning one refusal into a better-worded one. See `logs/T-0017.md` (D-091). |
| 15 | `ASSUMED` | **`many_to_many` is struck from §5.2 and D3 — the enum has three members.** `Cardinality` is `many_to_one`, `one_to_one`, `one_to_many`, so both places named a cardinality no spec can declare and no IR can carry. Nothing was built for it. The `match` in `_admitted_directions` is exhaustive with no fallthrough, so adding a member fails the type check at the one place that has to decide about it — the prose's claim, enforced rather than restated. See `logs/T-0017.md` (D-092). |

## 12. Phasing

One document, no phases — it is vocabulary. What it unblocks is phased: RFC 0038 (measure
semantic types) and RFC 0039 (proof IR) both depend on it, and RFC 0040's planner depends
on all three.

**Out of scope for the whole sequence, stated once here:** multi-measure planning before
0041, derived metric rewrites, query SQL generation in this document, inferring cardinality
from warehouse data, accepting unsafe marts, and a general-purpose relational theorem
prover.
