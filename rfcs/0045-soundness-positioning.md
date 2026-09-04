# RFC 0045 — Soundness positioning and the claims the docs may make

- **Status:** 📝 Draft — proposed. A **documentation** decision, not a code change; it
  binds what README and the reference pages may assert once proof-producing semantics land.
  [RFC 0039](0039-semantic-proof-ir.md) is recommended first, since the strong form of the
  claim is only true once proofs exist.
- **Scope:** The precise correctness claim bloomery makes, the representation-versus-
  answerability distinction the docs must draw, and the boundary around what is *not*
  proven. Arrived as `DOC-0001` in the semantic-correctness pack and is numbered into the
  corpus here, because "what the project may claim" is a decision with consequences and the
  corpus is where decisions with consequences live.
- **Related:** [`README.md`](../README.md) — the current one-line description;
  [`pages/docs/concepts/guardrails.md`](../pages/docs/concepts/guardrails.md);
  RFC 0001 (project foundations, retired).
- **Purpose:** Avoid both under-selling the compiler as "just artifact generation" and
  over-claiming that bloomery proves business truth.

---

## 1. The core claim

> bloomery does not prove that source data or business definitions are true. It proves that
> generated representations and accepted query plans preserve the semantics declared to
> bloomery, under a finite set of documented rules.

Short form:

> bloomery does not prove truth. It proves preservation of declared semantics.

## 2. The planner claim

Once RFCs 0039–0041 land:

> If bloomery returns a semantic query plan, every multiplicity-changing operation in that
> plan is justified by declared or mechanically derived semantic facts and a documented
> inference rule. If bloomery cannot construct that derivation, it refuses the request.

This is a stronger and more testable promise than "correct analytics", and it is false
before the capability exists — which is why §6 forbids publishing it early.

## 3. Representation versus answerability

The docs must draw this distinction explicitly, because the two look contradictory to a
reader who has not seen it stated:

**Representation safety** — a mart or emitted relation must not expose a measure in a shape
where ordinary downstream aggregation silently changes its declared meaning.

**Query answerability** — a request may still be answerable when bloomery can construct a
safe plan that preserves each measure at its origin grain until the correct aggregation
point.

```text
An order-level shipping measure is unsafe when repeated into an order-item mart. The same
measure may be safely answered by customer country when bloomery can aggregate from Order
to Country through grain-preserving relationships.
```

## 4. The closed-world statement

To the semantic and planner reference:

> Unknown is not safe. bloomery does not use heuristic schema inference as evidence of
> correctness. New capabilities are added by introducing explicit proof rules for
> additional safe operations.

## 5. The target-engine boundary

> SQLMesh, dbt, MetricFlow, Cube and the SQL dialects are compilation or execution targets.
> Their ability to generate executable SQL is not itself a bloomery correctness proof.
> Semantic acceptance happens before target lowering.

The list is adjusted to the actual supported integrations at publication time.

## 6. What bloomery explicitly does not prove

Documentation must state that bloomery cannot establish: correctness of source values;
truth of authored business definitions; undeclared business constraints; data-dependent
cardinality unless represented by a runtime audit; correctness of arbitrary custom code
outside the semantic contract; semantic facts inferred only heuristically from SQL.

## 7. README positioning

The current description is *"Entity-first spec compiler — declarative specs in, SQLMesh,
dbt and Cube artifacts out, byte-for-byte the same every time."* Its suggested evolution:

```text
bloomery is an entity-first semantic compiler. It turns declarative business semantics into
deterministic analytics artifacts and refuses representations or query plans it cannot
prove preserve declared grain, aggregation, unit, temporal, and relationship semantics.
```

After proof planning is production-ready, one further sentence may be added:

```text
For supported requests, bloomery derives a target-independent semantic plan before lowering
it to SQL or downstream semantic and runtime targets.
```

**Do not publish the second sentence before the capability exists.**

## 8. The documentation test

Every correctness statement in README must answer: what exact property is proven; from
which declared facts; at compile time or at run time; and what remains outside the
guarantee. A claim that cannot answer all four is rewritten.

## 9. Unresolved questions

- **Whether the determinism claim moves or stays.** The current description leads with
  byte-identical output, which is true, shipped, and the thing users can check today. The
  proposed replacement leads with semantics and drops it.
- **Who owns the "supported integrations" list in §5** so it does not go stale on the next
  target.

## 10. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | **The claim is preservation of declared semantics, never truth.** bloomery proves that what it emits and accepts preserves what it was told, under documented rules — not that the telling was right. Locked because every weaker phrasing of this ("correct analytics", "guaranteed correct metrics") is unfalsifiable and would be quoted back at the project the first time a wrong number came from a wrong declaration. |
| 2 | `LOCKED` | **The planner claim is not published before the capability exists.** §2's sentence is false today. A roadmap sentence in a README is read as a description of the current release, and a documentation claim that outruns the code is the one defect a reader cannot check against the code. |
| 3 | `LOCKED` | **Representation safety and query answerability are documented as distinct guarantees.** They look contradictory when a reader meets a refused mart and an accepted query over the same measure, and the distinction is RFC 0040 D1 stated for humans. Omitting it makes the refusal look arbitrary, which is how a correct refusal gets worked around. |
| 4 | `LOCKED` | **Every README correctness statement answers §8's four questions or is rewritten.** It is the gate that keeps the rest of this document from being a style preference: any sentence that cannot say what is proven, from what, when, and what is excluded, is a claim nobody can check. |
| 5 | `ASSUMED` | **Comparative statements about other systems are confined to what RFC 0043's reproductions support.** No universal "X cannot do Y". Not `LOCKED` here because RFC 0043 D5 already owns the rule; this row records that the docs are bound by it too. |
| 6 | `OPEN` | **Whether determinism stays in the README's lead.** The current sentence leads with byte-identical output — true today, checkable today, and the property users have. §7's replacement leads with semantics and drops it. Both are honest; they aim at different readers, and the decision belongs to whoever writes the sentence when §2's capability actually lands. |
| 7 | `OPEN` | **Who keeps §5's integration list current.** It goes stale the day a target is added or dropped, and a stale boundary statement is a wrong claim about what is and is not a correctness proof. Name an owner or a gate — a docs test asserting the list against the registered targets would be the durable answer. |

## 11. Phasing

§1, §3, §4, §5 and §6 may be written as soon as this is accepted: they describe what is
already true. §2 and §7's second sentence wait on the capability, and D2 is what holds them
back.
