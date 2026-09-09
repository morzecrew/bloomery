# RFC 0039 — Semantic proof IR and closed-world checking

- **Status:** 🚧 In progress — §13's first phase has landed: the proof vocabulary, provenance,
  and the rollup answer RFC 0037 already returns expressed in it. No guardrail is deleted and
  no request changes outcome. RFC 0038 completed, and two of the three rules that waited on
  its premises are minted: **R011** additive rollup and **R012** derived ratio
  reconstruction, with corpus cases 008-011 as the evidence
  ([`logs/T-0029.md`](../logs/T-0029.md)). **Explicit unit conversion is the one rule of §3's
  seven still outstanding** — no corpus case names it and this phase added no premise for it,
  so minting it would be a rule with nothing to convert (RFC 0042 D5). `explain` renders
  proofs in RFC 0040 where the planner first holds one, so the document stays whole
  (`INDEX.md` — retire whole, never in part). Execution's findings and the
  rows it proposes are in [`logs/T-0020.md`](../logs/T-0020.md); nothing below has been amended
  to agree with what was built. Third in the semantic-correctness sequence; depends on
  [RFC 0037](0037-semantic-grain-model.md) and
  RFC 0038.
- **Scope:** Replace "absence of a violation" as the long-term model of query validity with
  explicit positive derivations. Introduce proof and refutation values that `bloomery
  explain` can render and planners can consume. No guardrail is deleted here.
- **Related:** [`src/bloomery/cli/__init__.py`](../src/bloomery/cli/__init__.py) — the
  existing `explain` command; [`src/bloomery/errors.py`](../src/bloomery/errors.py) — the
  guardrail aggregate this must not replace prematurely; RFC 0003 (determinism contract,
  retired).

---

## 1. Summary

bloomery's safety posture should be closed-world:

> Unknown is not safe.

A semantic operation is accepted only when the compiler can construct a finite derivation
from declared or mechanically derived facts. New releases expand capability by adding proof
rules, not by weakening guardrails.

## 2. Current state

`bloomery explain` already exists (`cli/__init__.py:443`) and renders a plan. What it
cannot do today is state *why* the plan is safe: the reasoning that admitted it is spread
across guardrail checks that ran, passed, and returned nothing. Absence of a raised error
is the whole of the current evidence, which is exactly what this RFC replaces.

The guardrail stage's aggregate error mechanism (`GuardrailError.from_collected`) is the
other half of the current design and is **kept** — §8.

## 3. Core contract

The semantic checker returns one of:

```text
Proven<T>
Refused
```

`Proven<T>` contains both the semantic result and a proof tree. `Refused` contains
structured failed obligations and remediation where known. A boolean `is_safe` is
insufficient as the primary internal representation.

### Proof objects

```python
@dataclass(frozen=True, slots=True)
class Proof:
    rule: RuleId
    premises: tuple["Proof", ...]
    facts: tuple[SemanticFactRef, ...]
    conclusion: SemanticJudgement
```

Example judgement:

```text
AdditiveRollup(measure=shipping, from=Order, to=CustomerCountry)
```

Rules include: entity-key determination; relationship preservation; transitive functional
dependency; additive rollup; explicit unit conversion; qualified as-of join; derived ratio
reconstruction. Each is named, documented, deterministic, and independently testable.

## 4. Provenance of facts

Every proof leaf identifies its provenance:

- `Declared` — directly authored in bloomery specs;
- `Derived` — mechanically implied by declared facts;
- `ImportedVerified` — imported from a machine-readable external artifact under a
  documented exact rule;
- `InferredHeuristic` — never sufficient for a correctness proof;
- `Unknown` — never sufficient.

The last two may be useful for diagnostics or migration tooling, but cannot close a proof
obligation.

## 5. Closed-world monotonicity

Desired release property, when specs are unchanged and no prior rule is found unsound:

```text
SafeQueries(N) ⊆ SafeQueries(N+1)
```

Capability grows by adding sound derivations. A new rule must include positive and
adversarial tests showing the boundary it admits.

If a previously accepted rule is discovered unsound, correctness wins over monotonicity;
the change is breaking and is documented explicitly.

## 6. Refutations

A refusal identifies the smallest failed obligation available:

```text
Cannot prove shipping by item_sku.

Required:
  preserve shipping@Order while grouping by Item.sku

Found:
  Order -> OrderItem is one_to_many

Reason:
  the path refines the measure grain and may duplicate shipping
```

Refutations are not formal proofs of impossibility. They state that bloomery has no
permitted derivation under the current rule set, and the wording must not claim more.

## 7. Explain surface

`bloomery explain` renders the same proof objects the planner consumes. No separate
prose-only explanation engine reconstructs reasoning from the final SQL.

```text
PROVEN revenue by customer.country

1. revenue originates at Order
2. Order.customer_id -> Customer is many_to_one
3. Customer -> country is functionally determined
4. revenue is additive across Order
5. therefore Order -> CustomerCountry is a safe rollup
```

Machine-readable output is available for CI and tooling, with stable rule IDs.

## 8. Relationship to existing guardrails

Existing guardrails remain valid. Migration proceeds by expressing current safety decisions
as proof obligations and refutations where practical, **not by deleting guardrails first**.

The mart compiler may continue to use its existing aggregate error mechanism while
internally consuming shared semantic facts.

## 9. Determinism

Proof trees are compiler outputs for evidence purposes, so RFC 0003's contract applies
without exception: canonical premise order; stable rule IDs; no memory addresses; no
timestamps; no arbitrary graph traversal order. Equivalent authored ordering produces
equivalent proof serialization.

## 10. Tests

Snapshot tests for proof trees; property tests for deterministic derivations; negative
tests ensuring unknown facts cannot close proofs; mutation and adversarial tests that
remove one premise and require refusal; parity tests showing existing guardrail boundaries
remain intact.

## 11. Unresolved questions

- **Whether a proof is retained after acceptance or discarded.** Rendering `explain`
  requires it; compiling a project may not. The answer decides whether proofs are a return
  value or an artifact.
- **How rule IDs are versioned.** They are a public contract the moment CI asserts on them,
  and this document does not say what happens when a rule is split.

## 12. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | **Unknown is not safe: a proof obligation is closed only by `Declared`, `Derived`, or a narrowly specified `ImportedVerified` fact.** `InferredHeuristic` and `Unknown` may inform diagnostics and never acceptance. This is the sequence's whole safety posture stated as a rule, and RFC 0044's import path is built against it — reversing it there would let a guessed fact from a foreign artifact close a correctness proof, which is the failure that document exists to prevent. |
| 2 | `LOCKED` | **The primary internal representation is `Proven<T>` / `Refused`, not a boolean.** A boolean discards the derivation, and every consumer downstream — `explain`, RFC 0042's per-case rule pinning, a refusal's smallest failed obligation — has to reconstruct it from the answer. Reconstruction after the fact is how a prose-only explanation engine gets written, which §7 refuses by name. |
| 3 | `LOCKED` | **Guardrails are expressed as obligations before any is deleted.** Migration order, not sentiment: a guardrail deleted in favour of a proof rule that turns out narrower is a silently accepted unsafe project, and the parity tests in §10 are what make the two comparable. The mart compiler keeps its aggregate error mechanism throughout. |
| 4 | `ASSUMED` | **Capability grows monotonically — `SafeQueries(N) ⊆ SafeQueries(N+1)` — except where a prior rule is found unsound.** Correctness beats monotonicity, and the exception is a breaking change with an explicit note rather than a quiet narrowing. Not `LOCKED` because the property is a release discipline rather than a compiler invariant: nothing in the code can enforce it, so grading it `LOCKED` would make a halt routine over something only review can check. |
| 5 | `ASSUMED` | **Rules are named, individually documented, and independently testable.** The alternative — one monolithic checker returning a tree — passes the same tests and cannot answer "which rule admitted this?", which RFC 0042 §10 requires of every corpus case. |
| 6 | `LOCKED` | **Proof serialization is deterministic under RFC 0003.** Canonical premise order, stable rule IDs, no addresses, no timestamps, no traversal-order dependence. Locked rather than assumed because a proof tree is evidence, a graph walk produces it, and this codebase's determinism failures have always entered through iteration order. |
| 7 | `OPEN` | **Whether a proof is retained after acceptance or discarded once the obligation closes.** `explain` needs it; a compile may not, and holding every proof for a large project is an unmeasured cost. Execution decides — a return value, a lazily rebuilt artifact, or retention behind a flag — and logs the decision with whatever measurement prompted it. |
| 8 | `OPEN` | **What happens to a rule ID when a rule is split or subsumed.** They become a public contract the moment CI asserts on them (RFC 0044 §6 aligns its refusal codes to them). Decide the versioning discipline before the first ID ships, since the choice is unmakeable afterwards. |
| 9 | `LOCKED` | **No plan transformation may merge two aggregate branches before aggregation without proving the merge preserves every measure's grain.** Inherited twice and built neither time: RFC 0041 §9 and §10 stated the rule and asked for a property test constructing such a partition and asserting the merge is refused; RFC 0058 D8 parked it when 0041 retired, because 0058 then held a live preservation obligation of the same shape. 0058 has now retired too, and the row is readable with its full argument at `efba2b6`. It lands here because a merge is legal exactly when it can *derive* that the aggregate it produces is the one the detail would have produced, which is this document's subject and not the rollup mart's — the two were one shape only for as long as 0058 was the nearest live home. It does **not** gate any phase of this RFC: it transfers on to whatever document builds a `SemanticPlan` optimization pass, and that document owes the inherited property test in its own Tests section, as 0058 §6 named it in its. `LOCKED` because a merge without the proof is silent double counting, which this sequence refuses rather than approximates. Transferred at RFC 0058's retirement — see [`logs/T-0035.md`](../logs/T-0035.md). |

## 13. Phasing

Proof objects and provenance first, with `explain` rendering them for requests the planner
already accepts — no capability change, which is what makes the parity tests in §10
meaningful. Rules land one at a time behind their own tests, each naming the RFC 0042 cases
it converts from refusal to acceptance.
