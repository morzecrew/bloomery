# RFC 0058 — Rollup marts and pre-aggregations

- **Status:** 🚧 In progress — the block D2 states is **lifted**: RFC 0037 and RFC 0040
  have both landed. §12's phasing and rows 9–14 were written at that moment, against the
  vocabulary those documents actually chose, which is what §12 said would happen. P1 is
  built; P2 and P3 are not. Neither of those two is *retired*, and this document is part
  of why — [`INDEX.md`](INDEX.md) names 0058 as a dependant of 0037, 0038 and 0040, all
  three of which stay in the tree until it does.
- **Scope:** One feature under two names. The ceiling review listed "aggregate marts" in
  its platform-metadata item and "no `pre_aggregations`" in its Cube item; they are the
  same thing — a mart at a coarser grain than its base, valid only when its measures are
  additive over the dimensions being dropped. Cube's `pre_aggregations` is the emitted
  form of it on one target.
- **Related:** RFC 0037 (semantic grain model and functional dependencies),
  RFC 0038 (measure semantic types and additivity algebra), RFC 0040 (safe rollup
  planner), [`src/bloomery/emit/cube/__init__.py`](../src/bloomery/emit/cube/__init__.py),
  [`src/bloomery/marts/`](../src/bloomery/marts/),
  RFC 0010 (the mart grain rule), RFC 0008 (ports and emitters — where Cube emission
  lives; retired at `7ba117b`), RFC 0013 (the MetricFlow backend, whose D3 is quoted
  below; retired at `33bc4f9`).
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

One test is inherited rather than invented here. RFC 0041 §10 asked for a property test
constructing a partition that merges two aggregate branches and asserting the merge is
refused without a preservation proof (D8). It was never written, because the optimization
pass it would test does not exist; whichever document builds one owes it, and it is named
here so the obligation has a live home until then.

## 7. Docs

When built. The page that matters is the one explaining *why a rollup was refused*, since
that refusal is the feature's whole product for anyone who declares a wrong one.

## 8. Out of scope

- Everything, until RFC 0037 and RFC 0040 land.
- Cube `accessPolicy`, `joins` between cubes — the other two members of the ceiling
  review's Cube item. Cube-to-cube joins are a *stated refusal* rather than a gap:
  the wide-mart design exists precisely so query-time joins do not happen, and emitting
  `joins` would hand back the thing it removed. The nearest decision written down is
  RFC 0013 D3 — one mart, one semantic model, and never one for a non-mart entity,
  "that would reintroduce the query-time joins the mart design exists to prevent"
  (`emit/metricflow/__init__.py`). That row is MetricFlow's, so it is the same position
  reached for a different target rather than a citation that covers Cube; the Cube
  emitter's own refusal has never been written, which is the gap this bullet names.

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

Both settled at the moment §12 named — rows 9 and 10. The questions stay written: what
each one weighed is why its row reads the way it does.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | "Aggregate marts" and Cube `pre_aggregations` are **one feature**, scheduled once. The ceiling review named it twice, and building it twice is the failure this row exists to prevent. |
| 2 | `LOCKED` | Blocked on RFC 0037 and RFC 0040. A rollup's safety is a functional-dependency question over an aggregation class, and both are those RFCs' vocabulary. Building first means inventing it worse and then owning two. |
| 3 | `LOCKED` | No hand-authored `additive_over:` escape hatch, at any point. It is an assertion nothing checks, it would be introduced as temporary, and it would become a second source of truth that disagrees with the proof. |
| 4 | `ASSUMED` | A rollup states the dimensions it **keeps**; what it drops is derived. Stating both is two statements of one fact. |
| 5 | `LOCKED` | An unprovable rollup is **refused**, never warned about. A rollup is read instead of the detail table, so a wrong one answers quickly and plausibly — the class this project refuses rather than approximates. |
| 6 | `ASSUMED` | The acceptance evidence is RFC 0042's semantic bug corpus plus an execution-tier comparison against the same request computed from silver. A golden proves nothing here. |
| 7 | `LOCKED` | Cube-to-cube `joins` stay out of this RFC. They reintroduce the query-time joins the wide-mart design removes — the position RFC 0013 D3 states for MetricFlow semantic models, reached independently for Cube rather than inherited from it. Cube's own refusal is unwritten, and writing it belongs with whatever RFC takes Cube's surface. |
| 8 | `LOCKED` | **No plan transformation may merge two aggregate branches before aggregation without proving the merge preserves every measure's grain.** Inherited from RFC 0041 §9 and §10, readable at `654d93e`: that document stated the rule and asked for a property test constructing such a partition and asserting the merge is refused. Neither was built, because the optimization pass §9 deferred it to does not exist. Parked here rather than dropped at RFC 0041's retirement, because this is the live document holding a preservation obligation (§5.2) and the two are one shape — a transformation is legal only when it can show the aggregate it produces is the one the detail would have produced. It is **not** a rollup-mart decision and does not gate this feature: it transfers to whatever document builds a `SemanticPlan` optimization pass, which owes §6's inherited test with it. `LOCKED` because a merge without the proof is silent double counting, which this sequence refuses rather than approximates. Recorded at RFC 0041's retirement — see `81df8cc`. |
| 9 | `ASSUMED` | A rollup is a `Mart` carrying `rollup_of:`, **not a distinct spec kind** — §10's first question. It reuses `measures`, `partition_by`, `materialization`, `assert:` and `cost_hint` unchanged, and the deciding half is that `measure_owners` already arbitrates between marts; a second kind would have to be taught that arbitration again, and row 14 is the arbitration this feature actually needs. "Stops a rollup being mistaken for a mart in every place that iterates marts" is a predicate on the node, not a second kind. |
| 10 | `ASSUMED` | **Rollups do not chain**: `rollup_of:` names a mart that is not itself a rollup, and a chain is refused — §10's second question. The obligation composes; its *premise* does not. Row 12 rests the grain half on R008, a measure embedded in a mart at that mart's grain, and a rollup's measures do not originate at the rollup's grain — they arrive there. Restating that premise is a phase of its own, and one refusal is cheaper than a wrong composition. |
| 11 | `ASSUMED` | **Kept dimensions are declared under their own key, never `grain:`.** Supersedes §5.1's spelling; D4's substance stands. `Mart.grain` names an entity and the mart builder refuses it unless it equals `base:` (RFC 0010 D2, `marts/flatten.py`), so §5.1's `grain: [ordered_month, customer_segment]` puts a column list and an entity name under one key. A rollup declares `rollup_of:` and `keep:`, and declares neither `base:` nor `grain:`. |
| 12 | `ASSUMED` | **The grain half of §5.2's obligation is discharged by R008, not by R006.** §5.2 calls it a functional-dependency question, written before the source was a mart. `GrainRef` admits only entity *key* columns — `_unknown` in `semantic/closure.py` refuses every other determinant — and a rollup's target is a set of mart columns, of which `customer_segment` is not a key and a date-role bucket like `ordered_month` is not an entity column at all. Nothing needs re-deriving: every column of a mart is determined by that mart's grain, so grouping by a subset partitions rows the mart already proved. What is left is the aggregation-class question, which is the whole of R013. |
| 13 | `ASSUMED` | **Superseded by 15.** **P1 admits `additive`, and `ratio` when both operands are carried by the rollup and each is itself admitted.** `semi_additive`, `distinct_count` and `non_additive` are refused, each under its own reason naming its own repair. Phase-scoped, and written as a row so no reader takes it for permanent: a semi-additive measure rolled to a coarser bucket is a `first`/`last` selection rather than a sum, which is a computation this phase does not build. Not an escape hatch — D3 stands, and none of the three becomes admissible by declaring anything. |
| 14 | `LOCKED` | **A rollup mart is never a measure owner and never a covering mart.** §4 makes query-time rollup selection RFC 0040's job and nothing in the code knows it: `measure_owners` picks the cheapest mart serving a measure, a rollup is by construction the cheapest, and so the first rollup declared would take detail-grain requests silently and answer them from monthly totals — quickly, plausibly and wrongly, which is the class §2 gives as the reason this feature is the one where being wrong is worst. `LOCKED` because reversing it is not a scheduling call: it is the planner learning to choose, and that is a different document's work. |
| 15 | `ASSUMED` | **Supersedes 13**, which execution corrected in two places (see [`logs/T-0033.md`](../logs/T-0033.md)). P1 admits `additive`, and `ratio` when the rollup carries both operands and each is itself **additive** — not "itself admitted", as 13 read: an operand that is a ratio sends the obligation back through the same question and nothing in the spec layer forbids two ratios naming each other, so the wider word had no termination argument, and additive operands are the only ones R011 grants anyway. Refused: `semi_additive`, `non_additive`, `distinct_count` **and `snapshot`** — 13 omitted the last because `SNAPSHOT` is not in `RESOLVABLE` and no project can mint one, which is a reason for the mapping to carry it for totality and not a reason for the row to read as a shorter list than the code. Phase-scoped as 13 was, and not an escape hatch: D3 stands, and none of the four becomes admissible by declaring anything. |
| 16 | `ASSUMED` | **The degenerate groupings are refused, and the degenerate repeat is not** (see [`logs/T-0033.md`](../logs/T-0033.md)). A rollup keeping *no* dimension, one keeping a column the mart does not have, one keeping *every* column, and a mart carrying no measure are all refused. The first and the last would otherwise be **proved**, because a reduction over an empty set grants everything and a proof resting on nothing is what RFC 0039 D1 refuses. The third would be proved *truly* — re-aggregating over nothing is sound — and is refused anyway: §1 defines a rollup as coarser than what it derives from, and answering yes would authorize a duplicate gold table that costs storage and answers nothing faster. A dimension named twice is one grouping stated twice and is canonicalized, the way `RollupContext` already treats a repeated as-of anchor. |

## 12. Phasing

The paragraph this replaces said phasing would be written once RFC 0037 and RFC 0040 had
landed, against the vocabulary they actually chose. They have, and it is. Rows 9-14 are
the decisions that cutting these phases forced.

**P1 — the obligation, as vocabulary.** `prove_mart_rollup` and rule R013 under
`semantic/`: given a mart, the dimensions a rollup keeps and the project, a `Proof` or a
`Refutation` per measure the rollup would carry. No spec key, no IR field, no emission,
and nothing in the compile path consulting it — the shape RFC 0037 itself shipped in, for
the reason §9 gives: this looks like an emitter feature, the safety obligation is
invisible from the emitter, and so the obligation is built first and where it can be read.

**P2 — the declaration, and the refusal.** `rollup_of:` and `keep:` (row 11), the IR and
resolution that build a rollup from its parent, D5's refusal wired to P1's answer, row
14's exclusion from `measure_owners` and from the planner's covering-mart search, and an
ordinary derived gold model on SQLMesh and dbt. D6's acceptance evidence lands here rather
than after: a semantic-corpus case, and the execution-tier comparison against the same
request computed from silver.

**P3 — Cube.** The `pre_aggregations` block §5.3 names, and §9's third risk — Cube's own
query-time matching rules against the obligation bloomery discharged — measured into
RFC 0043's capability matrix rather than asserted here.
