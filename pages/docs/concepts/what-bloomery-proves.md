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

!!! quote "The planner claim"

    If bloomery returns a semantic query plan, every multiplicity-changing operation in
    that plan is justified by declared or mechanically derived semantic facts and a
    documented inference rule. If bloomery cannot construct that derivation, it refuses
    the request.

This is stronger and more testable than "correct analytics", and it was **false until
recently** — which is why it is worth knowing what changed. Every request the planner
answers now carries a derivation. Four request shapes used to be answered without one: a
metric computed from others, a semi-additive measure, a cumulative one, and two metrics
restricted differently. They were answered *correctly* — the number was never the problem
— but nothing could say why, and while that was so the claim above could not honestly be
made about the whole system.

What it does not claim is that the SQL is generated from the plan. bloomery decides what
to compute and states it; the query is still produced alongside. The derivation is
evidence about the answer, not the machinery that produces it.

## A guardrail that stayed silent, and a proof that closed

Both run, and they are not two spellings of one check.

A [guardrail](guardrails.md) asks *did anything I know how to look for go wrong?*, and its
green answer is the absence of a complaint. Nothing in that silence separates "this was
checked and holds" from "no rule here looked at it at all", because silence carries no
detail — which is why a guardrail can only ever tell you what bloomery did not find.

A proof asks *which named rule admits this, resting on which facts?*, and its answer is an
object: the rule that closed the obligation, the premises under it, and a provenance on
every leaf. `bloomery explain` prints it, so the distinction is one a reader meets rather
than one the architecture keeps to itself.

Guardrails keep their own aggregate refusal throughout — one error carrying every
violation found, not the first — while consuming the same semantic facts the proofs rest
on. One store of facts, two ways of reading it, so the answer and the argument for it
cannot drift apart quietly.

### The provenances that may never close one

A proof is only as strong as the weakest fact any of its leaves admitted, so whether a
fact can close an obligation is decided by where the fact came from:

| Provenance | Closes an obligation |
| --- | --- |
| `declared` — authored in a spec | yes |
| `derived` — mechanically implied by declared facts | yes |
| `imported_verified` — read from an external artifact under an exact documented rule | yes |
| `inferred_heuristic` — a guess, however good | **never** |
| `unknown` — no fact at all | **never** |

The last two are carried rather than discarded, and the reason is the refusal: one that
found a heuristic match can say what it found instead of only what it lacked. They may
inform a diagnostic; they may not close an acceptance, so a project resting on one does
not compile.

The line runs through one place — `Provenance.closes` in
`src/bloomery/semantic/proof.py` — rather than through each rule that needs it, because a
second copy of the line that drifted would not look like a safety change in review.

It is not the line the grades below draw. `derived` closes an obligation and grades
`ASSUMED`: closure is about soundness, the grade about authorship, and a project resting
entirely on derived facts is sound and entirely undeclared.

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

## How a fact was obtained, and asking for better

Every fact under a proof carries where it came from, and `bloomery explain` prints the
grade beside it:

```console
$ bloomery explain specs/ --metrics line_discount,shipping_count
Evidence (2 locked, 2 assumed)
  ASSUMED branch:order_items
          order_items is aggregated to the requested grain before the join, so it holds
          one row per key
  ASSUMED branch:orders
          orders is aggregated to the requested grain before the join, so it holds one
          row per key
  LOCKED  mart:order_items.line_discount
          line_discount is a measure of order_items, whose grain is order_item
  LOCKED  mart:orders.shipping_count
          shipping_count is a measure of orders, whose grain is order
```

Three grades, and they answer one question — **did a human here write this down?**

| Grade | Means |
| --- | --- |
| `LOCKED` | Somebody declared it in a spec, or it follows necessarily from something they did. |
| `ASSUMED` | The compiler obtained it soundly on its own — a proof rule, a propagation, an exact read of an external artifact. |
| `OPEN` | Closes nothing. A project resting on one does not compile at all, so you will not be handed one. |

`ASSUMED` is **not** a criticism. A derived fact is sound; the grade records where it came
from, not whether it is right. Treating it as doubt pushes you to declare things you have
not thought about, and a `LOCKED` fact nobody considered is worse than the default it
replaced.

### Requiring the stronger kind

A mart can say it will not rest on anything the compiler worked out for itself:

```yaml
marts:
  statutory_revenue:
    grain: order
    base: order
    measures: [net_revenue]
    requires_evidence: locked    # declared premises only
```

The default is `assumed`, which is what every project does today — leaving the key out is
byte-for-byte the same as writing it. There is no `open`: that would mean "accept
anything", which is the absence of the annotation rather than a third setting.

When a premise is weaker than the mart asked for, the refusal names the consumer, its
measures, the column, and how the compiler reached it:

```
mart 'statutory_revenue' requires 'locked'; its measures ('net_revenue') rest on column
'customer_tier', which the compiler reached by '<basis>' rather than from anything an
author wrote (S-0070/the-grades-and-what-they-project-from). Fix: declare the relationship that carries
'customer_tier', or set 'requires_evidence: assumed' on this mart
```

The basis above is a placeholder rather than a name you could grep for, because every way
the compiler believes a dependency *from your own specs* is something an author declared or
follows necessarily from one — an entity's key determining its own columns is the second
kind. That refusal is waiting for a weaker premise the compile path does not yet mint.

**A premise from another project's artifacts does reach it.** A relationship carrying
`imported_from:` was read out of an artifact rather than written here, so it grades
`ASSUMED` however ordinary its cardinality — and a strict mart whose columns are carried
through one is refused, in its own words:

```yaml
relationships:
  - name: item_of_order
    from: order_item
    to: order
    via: {order_id: order_id}
    cardinality: many_to_one
    imported_from: metricflow:semantic_manifest.json
```

```
mart 'statutory_revenue' requires 'locked'; its measures ('net_revenue') rest on column
'order_customer_id', carried by 'item_of_order' — read out of
'metricflow:semantic_manifest.json' rather than written here (S-0075/D-1). Fix: author
the relationship in this project and drop its 'imported_from:', or set
'requires_evidence: assumed' on this mart
```

The fix differs from the one above, and that is why the sentence does: the relationship
*is* declared, so "declare the relationship" would send you to write a line that already
exists. What a strict mart is asking is whether somebody **here** wrote it.

`imported_from:` names the artifact and is written by an importer, not by hand. Nothing
checks that — bloomery cannot tell a hand-typed one from a generated one, and writing it
on a relationship you authored silently lowers that relationship's grade.

### The consumer is often not the mart

A dashboard is the thing somebody signs off, and it usually reads several marts none of
which knows it is feeding a statutory report. So an **exposure** carries the same key, and
its requirement applies to everything beneath it:

```yaml
exposures:
  exec_dashboard:
    kind: dashboard
    owner: finance@example.com
    depends_on:
      metrics: [net_revenue]
    requires_evidence: locked    # of every mart below this, too
```

That reaches the marts named under `depends_on.marts`, and — this is the point — every
mart carrying a metric named under `depends_on.metrics`. **Every** such mart, not the one
the compiler happens to emit the measure on: which mart serves a query is chosen when the
query is planned, so a guarantee that held for only one of them would not hold for the
number on the dashboard.

The two refusals mirror the mart's, naming the metric that reached the mart and sending
you to the exposure's own key:

```
exposure 'exec_dashboard' requires 'locked'; it reads mart 'statutory_revenue' (carrying
metric 'net_revenue'), whose column 'customer_tier' the compiler reached by '<basis>' rather
than from anything an author wrote (S-0070/the-grades-and-what-they-project-from). Fix: declare the relationship that
carries 'customer_tier', or set 'requires_evidence: assumed' on this exposure
```

```
exposure 'exec_dashboard' requires 'locked'; it reads mart 'statutory_revenue' (carrying
metric 'net_revenue'), whose column 'order_customer_id' comes in through 'item_of_order' —
read out of 'metricflow:semantic_manifest.json' rather than written here (S-0075/D-1). Fix:
author the relationship in this project and drop its 'imported_from:', or set
'requires_evidence: assumed' on this exposure
```

A mart that carries its own `requires_evidence: locked` is not reported twice: its own
refusal says the same thing with the same repair, so the exposure adds nothing to it.

**Use it on few consumers.** A finance mart feeding a statutory report is the case it
exists for: someone signs that number, and "the compiler worked it out" is not an answer they can
give a regulator. An exploration mart is the counter-example — it wants whatever compiles,
and annotating it strictly buys a wall of declarations whose cheapest fix is deleting the
requirement, which loses the guarantee everywhere at once.

Two notes worth having before you adopt it:

- **This sits above the proof floor and never below it.** Every fact a strict mart refuses
  is one that already closed its obligation — the project is sound and would compile
  without the annotation. You are asking a different question, not a harder version of the
  same one.
- **`LOCKED` here and `LOCKED` on an RFC decision are analogous, not the same.** One grades
  a design decision, the other grades a fact about your project.

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
