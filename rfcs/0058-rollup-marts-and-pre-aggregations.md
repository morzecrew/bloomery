# RFC 0058 — Rollup marts and pre-aggregations

- **Status:** 📝 Draft — **blocked on RFC 0037**, deliberately and by construction. Not
  scheduled, and this document exists to say why rather than to be picked up.
- **Scope:** One feature under two names. The ceiling review listed "aggregate marts" in
  its platform-metadata item and "no `pre_aggregations`" in its Cube item; they are the
  same thing — a mart at a coarser grain than its base, valid only when its measures are
  additive over the dimensions being dropped. Cube's `pre_aggregations` is the emitted
  form of it on one target.
- **Related:** RFC 0037 (semantic grain model and functional dependencies),
  RFC 0038 (measure semantic types and additivity algebra), RFC 0040 (safe rollup
  planner), [`src/bloomery/emit/cube/__init__.py`](../src/bloomery/emit/cube/__init__.py),
  [`src/bloomery/marts/`](../src/bloomery/marts/),
  RFC 0010 (the mart grain rule), RFC 0013 (Cube emission; retired at `33bc4f9`).
- **Origin:** The ceiling review's second and third items, which name it twice. Splitting
  the platform-metadata line found the duplicate, and finding it is most of this
  document's value: it is the most bloomery-shaped item on either list and the one that
  must **not** be built first.

---

## 1. Summary

A rollup is a mart at a coarser grain than the one it derives from — daily revenue from
order items, monthly from daily. It is safe exactly when every measure it carries is
additive over the dimensions dropped, and unsafe in a way no test on the emitted SQL can
see: the query runs, the number is plausible, and it is a distinct count summed or an
average of averages.

bloomery cannot currently express the safety condition. Grain is a *string* — RFC 0010's
rule is that a mart is at exactly its base entity's grain, compared by name — and
additivity lives on a different node from the measure it constrains. RFC 0037 replaces
the string with structural identity and functional dependencies carrying their basis;
RFC 0038 gives a measure an aggregation class. Those two are what make "this rollup is
safe" a thing that can be *proved* rather than asserted.

So this RFC's content is one decision: **build it after RFC 0037 and RFC 0040, as their
first consumer.** Building it before means inventing their vocabulary a second time, in a
worse place, and then owning both.

## 2. Motivation

**The item is real and it is the most valuable one on either ceiling list.** A rollup is
what makes a semantic layer fast, and `pre_aggregations` is the reason a large fraction of
teams choose Cube at all. Emitting cubes with no pre-aggregation is emitting the surface
without the reason.

**It is also the item where being wrong is worst.** Every other platform-metadata feature
in the split is a declaration nobody's numbers depend on — an owner, a tag, an exposure.
A rollup is *read instead of the detail table*. A wrong one does not error; it answers,
and it answers quickly, which is exactly the plausible-but-wrong result this project
treats as its highest-severity class.

**The safety condition is already written down, three RFCs deep, and unbuilt.** RFC 0037
D-level work makes grain structural; RFC 0038 types a measure by aggregation class;
RFC 0039 turns acceptance into a positive derivation; RFC 0040 is a proof-producing
planner. A rollup is precisely a proof obligation of the shape those exist to discharge:
"these measures may be re-aggregated over these dropped dimensions".

**Building it first would fork the vocabulary.** Without RFC 0037 the only way to state
the condition is a per-measure `additive_over: [dims]` list authored by hand — an
assertion, not a proof, checked by nothing. Then RFC 0037 lands with functional
dependencies and the hand-authored list is either dead or, worse, a second source of
truth that disagrees.

## 3. Current state

Verified against the tree.

- **A mart is at exactly its base entity's grain** (RFC 0010 D2), and the grain is a
  string compared by name. `MartIR.grain` is prose — "one row per order item" — with no
  structure to reason over.
- **Additivity exists and is coarse.** A measure carries an additivity classification,
  and the guardrail stage refuses a non-additive measure in a context that would sum it;
  what it cannot express is "additive over *these* dimensions and not those", which is
  the whole of a rollup's safety.
- **Cube emission writes cubes, measures, dimensions and joins-by-construction.** No
  `pre_aggregations` key is emitted anywhere.
- **`marts/` builds one flattened relation per declared mart.** There is no notion of a
  mart derived from another mart — every mart reads silver.
- **RFC 0037, 0038, 0039, 0040 are all live and unstarted.** RFC 0042's semantic bug
  corpus — "cases where the SQL is valid, every cast succeeds and the number is wrong
  anyway" — is the acceptance evidence a rollup feature would need, and it is also
  unstarted.

## 4. Goals / Non-goals

**Goals of this document** (not of the feature):

- Record that "aggregate marts" and Cube `pre_aggregations` are one feature, so the two
  ceiling items do not get scheduled as two.
- Record why it is blocked, in a form that survives the ceiling review being forgotten.
- State the shape it should take once unblocked, tightly enough that whoever picks it up
  does not restart the analysis.

**Goals of the feature, when it is built**

- A mart declared as a rollup of another mart, at a stated coarser grain.
- Refusal — not a warning — when a measure it carries is not provably re-aggregable over
  the dropped dimensions.
- Cube `pre_aggregations` emitted from it; SQLMesh and dbt getting an ordinary derived
  model.

**Non-goals**

- **Building any of it now.**
- **A hand-authored `additive_over:` escape hatch**, then or now. That is the fork §2
  describes, and it would be introduced as a "temporary" measure and outlive everything.
- **Query-time rollup selection.** Choosing to read a rollup instead of the detail is the
  planner's job — RFC 0040 — not the emitter's.

## 5. Design

Deliberately thin. What is settled is the *shape*; the mechanism belongs to the RFCs this
waits on, and writing it in detail now would be writing RFC 0037's vocabulary before
RFC 0037 chooses it.

### 5.1 The shape

```yaml
marts:
  order_items_monthly:
    rollup_of: order_items
    grain: [ordered_month, customer_segment]
```

The mart names a parent and the dimensions it keeps. What it drops is derived — every
dimension of the parent not listed — because listing what you keep and what you drop is
two statements of one fact that will disagree.

### 5.2 The obligation

For each measure the rollup carries, a proof that re-aggregating it over the dropped
dimensions yields the same value as computing it at the coarse grain from silver. That is
a functional-dependency question (RFC 0037) over an aggregation class (RFC 0038),
discharged as a derivation (RFC 0039).

A `count(distinct …)` fails it. An `avg` fails it unless carried as a sum/count pair. A
`sum` over an additive measure passes. A semi-additive measure — a stock level, additive
over everything but time — passes for some dropped dimensions and not others, and that
is exactly the distinction a string grain cannot make and the reason this waits.

### 5.3 Targets

- **Cube**: a `pre_aggregations` block on the parent cube. This is the payoff and the
  reason the feature is worth its cost.
- **SQLMesh / dbt**: an ordinary gold model reading the parent mart. Nothing exotic —
  what makes it a rollup is the obligation discharged at compile, not the SQL.

## 6. Tests

When built: the semantic bug corpus (RFC 0042) is the acceptance evidence, and it is
named here rather than left to be discovered. A rollup feature whose tests are "the SQL
parses and the golden matches" has tested nothing about the only thing that can go wrong.
The load-bearing test is an execution-tier one comparing the rollup's answer against the
same request computed from silver, over data chosen so an unsafe rollup differs.

## 7. Docs

When built. The page that matters is the one explaining *why a rollup was refused*, since
that refusal is the feature's whole product for anyone who declares a wrong one.

## 8. Out of scope

- Everything, until RFC 0037 and RFC 0040 land.
- Cube `accessPolicy`, `joins` between cubes — the other two members of the ceiling
  review's Cube item. Cube-to-cube joins are a *stated refusal* rather than a gap:
  RFC 0013 D3 refuses a semantic model per entity precisely because it would reintroduce
  the query-time joins the wide-mart design exists to prevent, and emitting `joins` would
  hand back the thing the design removed.

## 9. Risks

- **Being built early because it looks like an emitter feature.** It looks like one: a
  YAML block and a Cube key. The safety obligation is invisible from the emitter, which is
  precisely why the temptation is dangerous. This section is the mitigation.
- **The hand-authored escape hatch.** Named twice in this document because it is the
  shortcut that would be proposed under deadline, and it is the one that costs the most
  later.
- **Cube's own pre-aggregation semantics may not match the obligation.** Cube decides at
  query time whether a pre-aggregation can serve a request, using its own rules. A rollup
  bloomery proves safe and Cube declines to use is wasted; one Cube uses that bloomery did
  not prove is a wrong number by Cube's reasoning rather than bloomery's. RFC 0043's
  capability matrix is where that comparison belongs.

## 10. Unresolved questions

- Whether a rollup is a `mart` with a `rollup_of` key or a distinct spec kind. The former
  reuses everything; the latter stops a rollup being mistaken for a mart in every place
  that iterates marts.
- Whether rollups may chain — a monthly rollup of a daily rollup. The obligation composes
  in principle; whether the proof does is RFC 0039's question.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | "Aggregate marts" and Cube `pre_aggregations` are **one feature**, scheduled once. The ceiling review named it twice, and building it twice is the failure this row exists to prevent. |
| 2 | `LOCKED` | Blocked on RFC 0037 and RFC 0040. A rollup's safety is a functional-dependency question over an aggregation class, and both are those RFCs' vocabulary. Building first means inventing it worse and then owning two. |
| 3 | `LOCKED` | No hand-authored `additive_over:` escape hatch, at any point. It is an assertion nothing checks, it would be introduced as temporary, and it would become a second source of truth that disagrees with the proof. |
| 4 | `ASSUMED` | A rollup states the dimensions it **keeps**; what it drops is derived. Stating both is two statements of one fact. |
| 5 | `LOCKED` | An unprovable rollup is **refused**, never warned about. A rollup is read instead of the detail table, so a wrong one answers quickly and plausibly — the class this project refuses rather than approximates. |
| 6 | `ASSUMED` | The acceptance evidence is RFC 0042's semantic bug corpus plus an execution-tier comparison against the same request computed from silver. A golden proves nothing here. |
| 7 | `LOCKED` | Cube-to-cube `joins` stay refused and are not part of this. RFC 0013 D3 refuses them because they reintroduce the query-time joins the wide-mart design removes; that is a design position, not a gap. |

## 12. Phasing

None. This RFC is not scheduled and has no phases; it is picked up after RFC 0037 and
RFC 0040 land, as their first consumer, and phasing is written then against the vocabulary
they actually chose.
