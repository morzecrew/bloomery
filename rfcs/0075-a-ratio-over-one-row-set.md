# RFC 0075 — A ratio over one row set

- **Status:** 📝 Draft — design only, nothing built. Converts corpus case
  `009-null-denominator` from `unguarded` to refused, which with
  [RFC 0074](0074-declared-source-timezone.md) closes both cases holding
  [RFC 0042](0042-semantic-bug-corpus.md) open.
- **Scope:** Which rows a ratio is about, and what bloomery does when a row contributes to
  the numerator and nothing to the denominator. Touches `semantic/additivity.py` (R012's
  neighbourhood) and one new rule; reads facts the spec already carries. Does **not** change
  how a ratio is rebuilt, how it is emitted, or the ratio vocabulary itself.
- **Related:**
  [`src/bloomery/semantic/additivity.py`](../src/bloomery/semantic/additivity.py) (R012),
  [`src/bloomery/spec/quality.py`](../src/bloomery/spec/quality.py) (`RangeRule`),
  [`src/bloomery/ir/nodes.py`](../src/bloomery/ir/nodes.py) (`OnFail`),
  [`src/bloomery/emit/cube/__init__.py`](../src/bloomery/emit/cube/__init__.py)
  (`{num} / NULLIF({den}, 0)`),
  [`tests/fixtures/semantic_corpus/009-null-denominator/`](../tests/fixtures/semantic_corpus/009-null-denominator/),
  [`tests/fixtures/semantic_corpus/008-ratio-rollup/`](../tests/fixtures/semantic_corpus/008-ratio-rollup/)
  (the case R012 does answer), RFC 0038 (measure semantic types and additivity algebra;
  retired at `efba2b6`).
- **Origin:** Corpus case 009, which records the wrong answer and names RFC 0042 D5 as the
  decision a rule converting it would answer to.

---

## 1. Summary

R012 says a ratio is recomputed from operands that each roll up, never summed. Case 009
satisfies it exactly — additive operands, sum over sum, no nulls, a non-zero total
denominator — and returns `4.00` where the answer is `3.00`.

The rule is about *how* a ratio is rebuilt and says nothing about **which rows belong in
it**. A shipment cancelled after the carrier charged for it contributes `40.00` to the
numerator and `0` parcels to the denominator, and sum-over-sum charges its cost to the
parcels somebody else moved.

This RFC does not decide that such rows should be excluded. It decides that **bloomery must
not decide** — both readings are legitimate metrics and picking one silently is the defect —
and adds the rule that refuses until the author says which.

## 2. Motivation

**Every check a ratio normally gets, passes.** The shape is right, the operands are additive
and each rolls up, the denominator is not null, nothing divides by zero, and the total
denominator is `40`. Case 009's whole argument is that `008-ratio-rollup` and this one
together are the reason **R012 is not enough on its own**.

**The zero is a fact, not an absence.** Case 009 chose a zero over a null deliberately: `SUM`
skips a null so both spell the same `4.00`, but a null lets the wrong answer read as an
aggregation artefact where a zero is a count the source asserts. There is nothing missing to
notice.

**There are two right answers and the spec cannot tell them apart.** "What did it cost us to
ship a parcel" over the parcels we actually moved is `3.00`. The same question read as "total
carrier spend per parcel moved, overheads included" is `4.00`. Both are metrics somebody
wants; today both are spelled identically and the compiler picks one.

**`NULLIF` is already there and guards a different failure.** The Cube emitter writes
`{num} / NULLIF({den}, 0)` (`emit/cube/__init__.py:37`), which protects the case where the
*aggregate* denominator is zero. Case 009's aggregate denominator is `40`. The guard fires
never and reads, to anyone who finds it, as the zero-denominator question already handled.

## 3. Current state

Verified against the tree, and by compiling both arms of the case.

- **R012** (`semantic/additivity.py:245`) — "a ratio is recomputed from operands that each
  roll up, never summed". It premises on each operand's own roll-up proof and concludes about
  the reconstruction. Nothing in it quantifies over rows.
- **The fix already exists as a spec fact.** Case 009's `restricted` arm is the same ratio
  with `filter: [{dimension: parcels, op: gt, values: [0]}]` on **both** operands, and it is
  `accepted` on R012 and returns `3.00`. So the vocabulary to say which rows is present; what
  is absent is anything that notices the author did not use it.
- **Nothing compares the two operands' restrictions.** Measured, not assumed: take case
  009's `restricted` arm, remove the `filter:` from the **denominator** only, and the project
  compiles clean with all three metrics present. That is a second and sharper form of this
  bug — a quotient of two quantities about different things — and case 009 does not cover it
  at all.
- **`RangeRule`** (`spec/quality.py:707`) can already say `min: 1` on a field, with a
  per-rule `on_fail` disposition. `OnFail` (`ir/nodes.py:370`) has `QUARANTINE` and `FAIL`,
  which remove the row from the relation, and `FLAG`, which does not.
- **The corpus pins the wrong number on purpose.** `009/expected/result.json` holds `4.00`
  for `declared` and `3.00` for `restricted`, and `semantic_outcome.json` grades the first
  `unguarded` against RFC 0042 D5 — the corpus asserts the defect rather than tolerating it.

## 4. Goals / Non-goals

**Goals**

- A ratio whose denominator can be zero on some row is **refused** until the author states
  which rows the ratio is about.
- Both legitimate readings stay expressible, and neither is the default.
- The facts the rule reads are ones the spec already carries — a restriction on the operands,
  or a range rule that removes the row.
- Case 009's `declared` arm becomes a refusal; its `restricted` arm compiles unchanged and
  still returns `3.00`.

**Non-goals**

- **Choosing which reading is right.** That is the author's, per metric, and §5.1 is built
  around not taking it.
- **Excluding zero-denominator rows automatically.** It is one of the two answers, and making
  it the default reproduces the defect in the other direction — silently dropping cost
  somebody is accountable for.
- **Changing R012 or the ratio vocabulary.** R012 is right about what it covers. This is the
  neighbouring question it does not reach.
- **Runtime detection.** A row with a zero denominator is not a data error; it is a legal row
  the metric has no opinion about. There is nothing for an audit to flag.
- **Division-by-zero safety.** `NULLIF` handles the aggregate case and keeps doing so. This
  is about rows, not totals.

## 5. Design

### 5.1 The refusal is the product

> **R019** — every row contributing to a ratio's numerator contributes a non-zero amount to
> its denominator.

A ratio is refused unless R019 discharges. It discharges three ways, and each is the author
having stated a reading:

| Discharge | What the author wrote | Which reading |
|---|---|---|
| **restricted** | the same restriction on both operands, excluding rows where the denominator is zero | "per unit, over the units that exist" |
| **positive by construction** | the denominator's origin field carries a `range` rule with `min > 0` at a disposition that removes the row (`quarantine` or `fail`) | the same, asserted once for every metric over that field |
| **declared inclusive** | `ratio: {numerator, denominator, includes_zero_denominator: true}` | "total over units, overheads included" — the `4.00` reading, said out loud |

The third is the one that makes this design honest. Without it the rule would be "exclude
zero rows", which is a decision about somebody's business that a compiler has no standing to
make. With it, `4.00` is reachable by an author who means it and unreachable by one who has
not thought about it — which is the whole difference this RFC is trying to create.

**`flag` does not discharge.** A flagged row stays in the relation, so a range rule at that
disposition asserts nothing about what the ratio sums. The disposition is what makes the
premise true, which is why the rule reads it rather than the rule's existence.

### 5.2 Operand restrictions must agree, whether or not zero is involved

A ratio whose numerator is filtered to one row set and whose denominator to another is
wrong for a reason that has nothing to do with zeros: it is a quotient of two quantities
about different things. Today it compiles.

> **R019's second leg** — a ratio's operands are restricted identically.

This is cheaper than the zero question and catches a sharper bug, so it is the same rule's
first check rather than a separate one. Identity is over the *canonical* restriction — the
same predicate written in two orders is one restriction — which is a normalisation the IR
already needs for fingerprints to be stable.

The `declared` arm of case 009 passes this leg (both operands are unrestricted) and fails the
first, which is worth stating: **the two legs catch different projects**, and a design with
only the cheap one would report clean on the case this RFC exists for.

### 5.3 What the refusal says

```
metric 'cost_per_parcel' is a ratio whose denominator 'parcels' can be zero, and a row
with a zero denominator contributes cost to the numerator and no units to the denominator
— so its cost is charged to units other rows moved (RFC 0075 R019).

Two readings are available and bloomery will not choose:
  • per unit, over units that exist — restrict both operands:
      filter: [{dimension: parcels, op: gt, values: [0]}]
    or declare 'parcels' positive on the entity:
      quality: [{rule: range, min: 1, on_fail: quarantine}]
  • total over units, overheads included — say so:
      ratio: {numerator: carrier_cost, denominator: parcels,
              includes_zero_denominator: true}
```

Both fixes in the message, because a refusal that names one of two legitimate readings is
a refusal that pushes every author toward the same answer.

### 5.4 Alternatives considered

**Exclude zero-denominator rows silently.** The smallest change and the one every BI tool
makes. Rejected: it produces a number nobody asked for, it loses cost somebody is accountable
for, and the loss is invisible — the report is right about the parcels it counted and silent
about the `40.00` it dropped. Being wrong loudly is this project's whole posture.

**Refuse only when the denominator is *observed* zero.** Compile-time, so nothing is
observed; RFC 0003 forbids reading the data. The only compile-time reading is "can be zero",
which for an `int` field with no range rule is always true — which is why §5.1's second
discharge exists, and why a project that declares its fields well is not inconvenienced by
this rule at all.

**Put the declaration on the denominator's metric rather than on the ratio.**
`parcels: {..., never_zero: true}` reads well and is wrong: it is a claim about the *data*,
which the field's quality rules already own and own better, at a disposition that makes the
claim true. A second place to say it is a second thing to keep in step.

**A new `ratio.over:` naming a row set directly.** More expressive than reusing operand
filters, and a third way to spell something the spec already spells. Rejected under the rule
that decided case 009's own `restricted` arm: the restriction belongs where the rows are
chosen, and that is the operand.

## 6. Tests

- **Semantic:** R019's three discharges each prove; a ratio with disagreeing operand
  restrictions refutes on the second leg; a `flag`-disposition range rule does **not**
  discharge, which is the premise the rule actually rests on.
- **Corpus:** case 009's `declared` arm converts `unguarded → refused` with a `refusal.json`;
  its `restricted` arm still returns `3.00` on R012. Case 008 is untouched and its two arms
  still grade as they do — R012's own territory does not move.
- **A third arm on case 009 — `inclusive`** — declaring `includes_zero_denominator: true`
  and returning `4.00`, `accepted`. The corpus currently pins `4.00` as the *wrong* answer,
  and this is the arm that makes it a right one under a different question. Adding it is part
  of this work, not an afterthought: without it the `4.00` in `result.json` would be a number
  no arm produces.
- **Not tested:** that the chosen reading is the business's. Nothing can test that, and §9
  says so where a reader will meet it.

## 7. Docs

- `pages/docs/reference/errors.md` gains the refusal class.
- The guardrails page's ratio section gains the row question beside the reconstruction one.
  It currently explains `SUM(num)/NULLIF(SUM(den),0)` in a way that reads as the
  zero-denominator question being handled, and after this RFC that sentence is actively
  misleading.
- The how-to for metrics gains both spellings, in the order the refusal lists them.

## 8. Out of scope

- **Ratios of ratios**, and whether the leg composes through a derived metric whose inputs
  are themselves ratios. Named because it is the obvious next question; R014 owns derived
  metrics and the interaction is not designed here.
- **Weighted averages** spelled as a ratio of a product and a weight. Same rule applies and
  no extra design is needed, but no fixture covers it.
- **Negative denominators.** A denominator that can go below zero is a worse version of this
  bug and a different conversation: the quotient is not merely mis-attributed, it changes
  sign. `min > 0` covers it accidentally; nothing here covers it deliberately.
- **`NULLIF` on the aggregate.** Stays as it is.

## 9. Risks

- **`includes_zero_denominator: true` becomes the paste-past.** An author blocked by a
  refusal reaches for whichever fix is shortest, and this one is. Mitigated by message order —
  the restriction is listed first and the inclusive reading is spelled long — and by the key
  naming the consequence rather than the syntax. Not mitigated fully, and pretending
  otherwise would be the kind of claim §7 exists to keep out of the docs.
- **The refusal lands on correct projects.** A ratio whose denominator genuinely cannot be
  zero, in a project that never declared a range rule, is refused for a defect it does not
  have. That is the cost of a compile-time reading of "can be zero", it is real, and §5.1's
  second discharge is what makes it cheap to answer once per field rather than once per
  metric.
- **Restriction identity is a normalisation problem.** Two predicates that mean the same
  thing and are spelled differently must compare equal, or the second leg refuses correct
  projects. The IR's canonical form is the mitigation and it is also the risk: if it is not
  as canonical as assumed, the failure is a confusing refusal rather than a wrong number.
- **Read as arithmetic pedantry.** "Just filter the zeros" is what every reviewer will say
  first. The document has to lead with the two-readings argument or it will be implemented as
  the silent exclusion §5.4 rejects.

## 10. Unresolved questions

- Whether R019 should fire for a ratio used **only at a grain where the zero rows cannot
  appear** — a mart pre-filtered so no zero-denominator row reaches it. The premise is
  discharged by the relation rather than the declaration, and whether the proof can see that
  depends on how much the flattener records.
- Whether the second leg (`operands restricted identically`) should be its own rule with its
  own number. It catches a different bug, it is much cheaper, and it could land a phase
  earlier — against which, one rule that says "a ratio is over one row set" is one thing to
  learn rather than two.
- What `includes_zero_denominator: true` means on a ratio whose denominator has **no** zero
  rows. Harmless, or a declaration that should itself be refused as unnecessary? The second is
  tidier and adds a refusal nobody benefits from.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | **bloomery does not choose which rows a ratio is about.** Both readings — per unit over units that exist, and total over units with overheads included — are metrics somebody wants, and the defect is that they are spelled identically. The rule refuses until the author says; it never picks. Locked because every cheaper design is a compiler making a decision about somebody's business, and the wrong one is invisible in the output. |
| 2 | `LOCKED` | **The inclusive reading stays reachable and is spelled out loud.** Without it the rule reduces to "exclude zero rows", which is D1 reversed with extra steps: an author who means `4.00` must be able to say so, and be seen to have said so. |
| 3 | `LOCKED` | **A `flag` disposition does not discharge the positivity premise.** A flagged row stays in the relation, so the range rule asserts nothing about what the ratio sums. The disposition is the premise, not the rule's presence — reading the rule alone would be a proof that is true of a project where the rows are still there. |
| 4 | `ASSUMED` | **The row question is one rule with two legs, not two rules.** "A ratio is over one row set" is a single thing to learn, and the legs fail on different projects so neither is redundant. Departing means the phasing wants them apart — §10's second question — and the cost is a second number to cite. |
| 5 | `ASSUMED` | **The restriction is declared on the operands, not on the ratio.** Where the rows are chosen is where the restriction goes, which is the rule case 009's own `restricted` arm was written under. Departing means finding a restriction that cannot be expressed per operand. |
| 6 | `OPEN` | **Whether a pre-filtered mart discharges the premise by construction.** §10's first question: the relation may already exclude zero rows, and whether the proof can see that depends on what the flattener records. The executor decides against the IR as it stands and logs it. |
| 7 | `OPEN` | **Whether `includes_zero_denominator: true` on a denominator that cannot be zero is refused.** Tidier, and a refusal that helps nobody. Decide when writing the message; the deciding fact is whether the rule can tell "cannot be zero" from "not declared" without a second premise. |

## 12. Phasing

Two commits, the cheap leg first only if §10's second question says so — otherwise one:

1. **R019 and the refusal**, both legs, with case 009's `declared` arm converting and its
   `refusal.json` landing.
2. **The `inclusive` arm and `includes_zero_denominator:`**, which is what makes the `4.00`
   in `result.json` a number an arm produces rather than a wrong answer nothing reaches.

The order matters and is the opposite of comfortable: commit 1 refuses a spelling commit 2
makes expressible, so a project needing the inclusive reading is blocked between them. The
alternative — ship the escape hatch first — means the escape exists before the thing it
escapes, and every author who meets it has no reason to prefer the restriction. One commit is
better than either if the work fits, and §12 says so rather than defaulting to two.
