# RFC 0065 — Consumer-declared evidence strictness

- **Status:** 📝 Draft — independent of the identity and history sequence. Reads
  [RFC 0039](0039-semantic-proof-ir.md)'s `Provenance` vocabulary, which ships today, and
  degrades to a two-state form for facts no proof rule has reached yet.
- **Scope:** A minimum evidence grade a mart or an exposure may require of the facts its
  measures rest on, refused at compile time. The `LOCKED` / `ASSUMED` / `OPEN` vocabulary the
  RFC corpus already uses for decisions, applied to spec assertions. One annotation on two
  spec kinds, one classification pass, one refusal. No SELECT changes.
- **Related:** [`src/bloomery/errors.py`](../src/bloomery/errors.py)
  (`GuardrailError.from_collected`),
  [`src/bloomery/semantic/proof.py`](../src/bloomery/semantic/proof.py) (`Provenance`),
  [`src/bloomery/cli/__init__.py`](../src/bloomery/cli/__init__.py) (`explain`),
  RFC 0038 (measure semantic types and additivity — the facts being graded, landed),
  RFC 0039 (closed-world checking — the global floor this sits above),
  RFC 0044 (`check` — where the refusal is most useful),
  RFC 0056 (exposures — the second place an annotation lands),
  RFC 0057 (declared source freshness — the same declaring-half pattern).
- **Origin:** The observation that this corpus grades its own decisions three ways and grades
  a project's assertions not at all. A `LOCKED` decision and an `ASSUMED` one are treated
  differently by every reader of an RFC; a declared additivity and an inferred one are treated
  identically by the compiler at the point a consumer would care.

---

## 1. Summary

RFC 0039 sets a floor: unknown is not safe, and a semantic operation is accepted only on a
finite derivation. That floor is global, and it admits three provenances that close an
obligation — `DECLARED`, `DERIVED` and `IMPORTED_VERIFIED` — treating them alike once they
have closed it.

For most marts that is right. For some the distinction is the whole point. A finance mart
that feeds a statutory report wants every measure's additivity and unit *declared*, not
derived from a default and not read out of somebody else's manifest; an exploration mart
wants whatever compiles.

Today there is no way to say which kind you are. This RFC lets a consumer declare a minimum:

```yaml
marts:
  - name: statutory_revenue
    requires_evidence: locked      # declared premises only
```

and refuses at compile time when a measure it reads rests on something weaker.

## 2. Motivation

**One floor cannot serve two audiences.** Raising the global floor to satisfy the strictest
mart breaks every exploratory project; leaving it where it is means the strict mart has no
way to be strict. The property is per-consumer and is currently expressible nowhere.

**The distinction the corpus makes about itself, it does not make about specs.** Every
decision table in this directory grades its rows `LOCKED`, `ASSUMED` or `OPEN`, because the
difference between a settled decision and a working assumption is worth writing down. A
project's assertions have the same shape and no consumer can act on it.

**`Provenance` is already recorded and nothing consumes the distinction.** `closes` is a
boolean over five members: a `DECLARED` fact and a `DERIVED` one are indistinguishable to
every caller once both have closed an obligation. The information is there and is spent.

**An inferred fact is invisible at the point it matters.** When a measure's additivity comes
from a default rather than a declaration, nothing downstream can tell. The number is produced
with the same confidence either way, and the first signal that a default was wrong is a
reconciliation failure in a report.

## 3. Current state

`GuardrailError.from_collected` aggregates violations, and a violation is binary: the check
passed or it did not. There is no consumer-side requirement to compare a premise against.

`Provenance` in `semantic/proof.py` has five members ordered by trust — `DECLARED`,
`DERIVED`, `IMPORTED_VERIFIED`, `INFERRED_HEURISTIC`, `UNKNOWN` — and one derived property,
`closes`, allowlisting the first three. That is the fact-level vocabulary this document
coarsens; it does not need a second one.

RFC 0038 has landed: a measure's value, origin grain, aggregation class and unit are
consolidated, `Additivity` is closed at six members, and `additivity: additive` is checked
rather than trusted. The node whose facts would carry a grade therefore exists, which is
what makes this schedulable now rather than blocked.

The `check` command of RFC 0044 is where such a refusal is worth the most: a CI gate that
fails when a strict mart's premises weaken is exactly the shape of that command.

## 4. Goals / Non-goals

**Goals**

- A mart or an exposure declares the weakest premise it will accept, and a violation is a
  compile-time refusal naming the measure, the fact and where the fact came from.
- Absence of the annotation reproduces today's behaviour exactly.
- The grade of a fact is derived from `Provenance`, never declared: an author cannot label a
  guess as declared.
- `explain` renders the grade alongside the fact, so the requirement is inspectable before it
  is enforced.

**Non-goals**

- **Raising or lowering RFC 0039's floor.** This sits strictly above it. A project that fails
  the floor fails regardless of any annotation here.
- **A second provenance vocabulary.** The grades are a projection of `Provenance`, not a
  parallel scale; D7 fixes the mapping so the two cannot drift.
- **Grading data quality.** This is about how a *semantic fact* was obtained, not about
  whether rows are good. RFC 0016's quality machinery is unrelated and stays so.
- **A trust score.** Ordered states, no arithmetic, nothing summed or averaged.
- **Per-column requirements.** The annotation is on the consumer, and it applies to every
  measure that consumer reads.

## 5. Design

### 5.1 The grades, and what they project from

Applied to a semantic fact — an additivity class, a unit, a grain, a functional dependency:

| Grade | `Provenance` | Meaning |
|---|---|---|
| `LOCKED` | `DECLARED` | The author declared it in a spec. |
| `ASSUMED` | `DERIVED`, `IMPORTED_VERIFIED` | Obtained mechanically — a default, an inference from a type, a propagation through a proof rule, or an exact read of an external artifact. Sound under RFC 0039 and not authored here. |
| `OPEN` | `INFERRED_HEURISTIC`, `UNKNOWN` | Does not close an obligation, so under RFC 0039's floor it does not compile at all. The grade exists so the three states are total. |

**The grade is derived, never written.** A spec cannot assert that its additivity is
`LOCKED`; it becomes `LOCKED` by being declared. Letting an author write the grade would make
it a second, unchecked claim about a claim — which is the failure mode the whole idea exists
to remove.

`IMPORTED_VERIFIED` landing in `ASSUMED` is the one placement worth arguing about, and D8
records that it is not settled: a fact read from a dbt manifest under an exact rule is not
authored *here*, which is what a statutory mart is asking about — but it was authored
somewhere, by someone, which is what the word "declared" means to a reader.

### 5.2 The annotation

`requires_evidence: locked | assumed` on a mart, and on an exposure under RFC 0056. Default
is `assumed`, which is what every project does today. There is no `open` requirement: it
would mean "accept anything", which is the absence of the annotation.

An exposure's requirement applies transitively to the marts and metrics it names. A dashboard
declaring `locked` makes the requirement of everything it reads, which is the point — the
strictness belongs to the consumer, and the consumer is often not the mart.

### 5.3 The refusal

Collected through the existing aggregate mechanism, so a project sees every violation at once
rather than one per run. The message names four things: the consumer, the measure, the fact,
and how the fact was obtained.

> `statutory_revenue` requires `locked`; measure `net_revenue` has `ASSUMED` additivity,
> derived by default from aggregation class `sum`. Declare it on the measure to satisfy this.

The last clause matters. A refusal that does not say what to write is a refusal a team works
around by deleting the annotation.

## 6. Tests

- **The default is invisible.** A project with no `requires_evidence` compiles byte-identically
  to the pre-change tree. Every existing fixture is this test.
- **A declared fact satisfies `locked`.** Declare additivity explicitly; the strict mart
  compiles.
- **A derived fact does not.** Remove the declaration, leaving the compiler to default it; the
  same mart is refused, and the message names the measure and the derivation.
- **The grade cannot be forged.** A spec attempting to write a grade on a fact is refused as
  an unknown field, not honoured.
- **Every `Provenance` member has a grade.** A member added to that enum without a row in
  §5.1's table fails, rather than defaulting into one — the same reasoning `_CLOSING`'s
  allowlist already uses.
- **Transitivity holds.** An exposure requiring `locked` refuses when a metric two hops down
  rests on a derived fact, and names the metric rather than the exposure.
- **Violations aggregate.** Three violations produce one error listing three, consistent with
  `GuardrailError.from_collected`.

## 7. Docs

`pages/docs/concepts/` — one section on evidence grades, sited with the semantic material.
The worked example is a finance mart, because that is the case that makes the feature
obviously worth having, and the counter-example is an exploration mart that should not adopt
it.

## 8. Out of scope

- A fourth grade splitting a proof-rule derivation from a default. Both are `DERIVED` today
  and telling them apart needs a distinction `Provenance` does not draw; adding one is a
  change to RFC 0039's enum, not to this document.
- Requirements on anything but measures. Dimensions and joins have facts too; measures are
  where the wrong number comes from.

## 9. Risks

- **A blanket `locked` becomes a chore and then a deletion.** A team that annotates every mart
  strictly will hit a wall of declarations, and the cheapest fix is removing the annotation —
  which loses the guarantee silently. The docs must argue for using it on few marts.
- **`ASSUMED` reads like a criticism and is not.** A mechanically derived fact is sound under
  RFC 0039; the grade records where it came from, not whether it is right. Wording that
  implies doubt will push teams to declare things they have not thought about, producing
  `LOCKED` facts that are worse than the defaults they replaced.
- **Two vocabularies, one word.** `LOCKED` on a decision row and `LOCKED` on a fact are
  related but not identical, and a reader moving between the RFC corpus and a refusal message
  may conflate them. Reusing the words is still right — inventing a second three-state scale
  would be worse — and the docs should say the two are analogous rather than the same.
- **A projection can drift from what it projects.** §5.1's table is a second place `Provenance`
  is enumerated. The test that every member has a grade is what keeps the two together, and it
  is the one test in §6 that must not be dropped as ritual.

## 10. Unresolved questions

- Whether `requires_evidence` belongs on the mart, the exposure, or the project with
  per-consumer overrides. The exposure is the truest owner and the mart is where authors will
  look first.
- Whether a fact declared in an imported project counts as `LOCKED` locally, or drops a grade
  on crossing a project boundary under RFC 0059 — the same question D8 asks of
  `IMPORTED_VERIFIED`, arriving from the other direction.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | A fact's grade is derived from how the compiler obtained it and can never be written in a spec. A declared grade is an unchecked claim about a claim. |
| 2 | `LOCKED` | This sits above RFC 0039's floor and never below it. No annotation here makes a project compile that would otherwise be refused. |
| 3 | `LOCKED` | Absence of the annotation is byte-identical to today. Strictness that arrives unrequested is a breaking change wearing a safety feature's clothes. |
| 4 | `LOCKED` | The refusal names how the fact was obtained and what to write instead. A message that only says "insufficient evidence" gets worked around by deleting the requirement. |
| 5 | `ASSUMED` | Three grades, not five. The consumer-facing question is "did a human here write this down", and `Provenance`'s finer distinctions do not change a mart's answer to it. |
| 6 | `OPEN` | Where the annotation lives: mart, exposure, or project with overrides (§10). |
| 7 | `LOCKED` | The grades are a total function of `Provenance` and every member maps to exactly one, checked by a test. A second vocabulary that drifted from the first would grade facts by a rule nobody could find. |
| 8 | `OPEN` | Whether `IMPORTED_VERIFIED` grades `ASSUMED` or `LOCKED` (§5.1). It is authored, and not authored here, and which of those a statutory consumer means is the question. |

## 12. Phasing

**P1** — grade derivation from `Provenance` and `explain` rendering it. No requirement, no
refusal: the grades become visible first, which is what tells a team whether the feature is
worth adopting.

**P2** — `requires_evidence` on marts, the refusal, and the aggregate message.

**P3** — the same annotation on exposures under RFC 0056, with transitivity.

P1 is worth landing alone and is close to free: RFC 0038 has consolidated the facts and
RFC 0039 already carries the provenance, so a project can see how much of its semantics is
declared and how much is defaulted, which is a useful number nobody currently has.
