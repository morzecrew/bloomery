# What bloomery proves

This page states the correctness claim precisely: what property bloomery establishes,
from which facts, at what time, and what stays outside it. It exists because both
directions of over- and under-statement are easy. "Artifact generator" undersells a
compiler that refuses arithmetic; "guaranteed correct metrics" oversells one that has
only ever read your declarations.

The claim in one sentence:

!!! quote "The core claim"

    bloomery does not prove that source data or business definitions are true. It proves
    that generated representations and accepted query plans preserve the semantics
    declared to bloomery, under a finite set of documented rules.

Shorter, and worth memorising, because every other sentence on this page is a
consequence of it:

> **bloomery does not prove truth. It proves preservation of declared semantics.**

If you tell bloomery that `shipping` is an order-grain measure in dollars, it will refuse
every representation and every plan that would silently make it mean something else. If
`shipping` is actually per-parcel, or the column holds euros, nothing here will save
you — that is a wrong declaration, and bloomery has no access to the world the
declaration is about.

## Representation and answerability are different questions

These two look contradictory the first time you meet them together, which is why they
are stated side by side rather than discovered.

**Representation safety** — a mart or emitted relation must not expose a measure in a
shape where ordinary downstream aggregation silently changes its declared meaning. This
is what the [guardrails](guardrails.md) enforce, and it is a property of the artifact.

**Query answerability** — a request may still be answerable when bloomery can construct a
plan that preserves each measure at its origin grain until the correct aggregation point.
This is a property of a *plan*, decided per request.

The same measure can fail the first and pass the second:

```text
An order-level shipping measure is unsafe when repeated into an order-item mart. The same
measure may be safely answered by customer country when bloomery can aggregate from Order
to Country through grain-preserving relationships.
```

Nothing has been relaxed between those two sentences. The mart is refused because storing
the measure at line grain makes every later `SUM` overstate. The query is answerable
because a plan exists that aggregates at order grain *first* and joins after — and note
the condition: it is answered when such a plan can be built, and
[refused when one cannot](../how-to/plan-a-metric-request.md#refusals), not
answered approximately in the meantime.

Without the distinction stated, the refusal reads as arbitrary — and an arbitrary-looking
refusal is one somebody works around.

## Unknown is not safe

!!! quote "The closed-world rule"

    bloomery does not use heuristic schema inference as evidence of correctness. New
    capabilities are added by introducing explicit proof rules for additional safe
    operations.

A fact bloomery was not told is not a fact it assumes benign. Nothing here reads your SQL
and concludes what a column must have meant, and no capability arrives by relaxing a check
— it arrives as a named rule stating what it admits and what evidence closes it, so the
set of accepted requests only ever grows deliberately.

The practical consequence is that a refusal can mean "this is unsafe" *or* "no rule covers
this yet", and both come out as a refusal rather than a guess.

!!! note "Where the proof obligation has reached, and where it has not"

    This is a direction of travel with real ground already taken, not a finished state,
    and the difference is worth knowing. Some acceptances are backed by a positive
    derivation — a rollup's re-aggregability, a ratio rebuilt from its operands, a
    cross-grain request aggregated before it is joined. Others are backed by a documented
    check that found nothing wrong, which is a weaker thing: it rules out the failures
    somebody thought of.

    Both refuse rather than guess, so neither answers you wrongly in silence. But only the
    first can say *why* it is safe, and converting the second into the first, one rule at
    a time, is ongoing work.

## Targets are not the proof

!!! quote "The target boundary"

    SQLMesh, dbt, MetricFlow, Cube and the SQL dialects are compilation or execution
    targets. Their ability to generate executable SQL is not itself a bloomery correctness
    proof. Semantic acceptance happens before target lowering.

That SQLMesh plans your models, or that Cube loads your data model, says those tools
accepted the syntax. It says nothing about grain, additivity, units or tax basis, because
none of them models those. Semantic acceptance has already happened by the time an
artifact is written — a project that will not compile never reaches a target at all, and a
target that happily runs a wrong query would not have been given one.

## What bloomery cannot establish

The boundary, stated plainly, because a guarantee whose edges are vague is quoted well
past them:

- **Correctness of source values.** Whether the number in the column is the right number.
- **Truth of authored business definitions.** Whether `revenue` should have included
  refunds is a question about your business, not about your specs.
- **Undeclared business constraints.** A rule nobody wrote down constrains nothing.
- **Data-dependent cardinality**, unless represented by a runtime audit. Whether a
  relationship is *actually* one-to-many in today's data is a fact about rows;
  [quality rules](data-quality.md) measure it at run time, and the compiler cannot.
- **Correctness of arbitrary custom code** outside the semantic contract. A
  [step](step-registry.md) declares its input and output types and those are enforced;
  what its body computes is its author's claim, not bloomery's.
- **Semantic facts inferred only heuristically from SQL.** Anything reverse-engineered
  from a query rather than declared.

This list is not the same as what bloomery does not **do** — that one is about execution
and orchestration: it runs no SQL, schedules nothing, reads no warehouse. This one is
about evidence: things bloomery runs no check for, and will not be able to, because the
facts they need never arrive in a spec.

## Reading a correctness claim

Any sentence in this documentation asserting that bloomery is correct about something
answers four questions, or it gets rewritten:

1. **What exact property is proven?**
2. **From which declared facts?**
3. **At compile time or at run time?**
4. **What remains outside the guarantee?**

Applied to the grain guardrail, for example: a measure is never embedded in a mart at a
grain coarser than its own *(property)*, from the measure's declared `grain:` and the
mart's declared grain *(facts)*, at compile time *(when)* — and it establishes nothing
about whether the measure's own declared grain is the truth *(residue)*.

A claim that cannot answer all four is one nobody can check, which makes it marketing
rather than documentation.
