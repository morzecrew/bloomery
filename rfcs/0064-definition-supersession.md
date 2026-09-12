# RFC 0064 — Definition supersession and change attribution

- **Status:** 🚧 In progress — §12's P1 and P2 have landed together, as that section asks:
  the facet vocabulary and the dependency closure, over the walk
  [RFC 0069](0069-spec-timeline.md) P1 built. The `supersedes` edge §5.1 designs is that
  walk's `TimelineChange` rather than a new edge kind in the IR, the additivity facet ships
  plain rather than waiting for P3's provenance wording, and D6 is answered by a totality
  test over the IR models. Execution's findings and the rows it proposes are in
  [`logs/T-0045.md`](../logs/T-0045.md); nothing below has been amended to agree with what
  was built. **P3 — the exposure sinks and RFC 0039's provenance vocabulary — is
  unscheduled.** Depends on [RFC 0062](0062-stable-node-identity.md) for identity,
  and on having two spec sets to compare. RFC 0063 was where those were to come from; it
  was rejected and retired at `074a571`, and [RFC 0068](0068-caller-assembled-spec-history.md)
  puts the caller in charge of assembling them instead — which changes where the pair comes
  from and nothing about the pair. Last of the three-document history sequence.
- **Scope:** A `supersedes` edge between two versions of the same node, and the command that
  reads it: given a metric and two instants, state what about its definition changed and what
  that reaches. One new edge kind in the lineage graph, one new command surface. No spec
  fields, no artifact changes.
- **Related:** [`src/bloomery/guardrails/lineage.py`](../src/bloomery/guardrails/lineage.py),
  [`src/bloomery/ir/nodes.py`](../src/bloomery/ir/nodes.py),
  [`src/bloomery/plan/model.py`](../src/bloomery/plan/model.py) (`ChangeClass`),
  [`src/bloomery/cli/__init__.py`](../src/bloomery/cli/__init__.py) (`explain`, `lineage`,
  `plan`), RFC 0062, RFC 0063, RFC 0056 (exposures — the sink an attribution reaches),
  RFC 0039 (proof IR — the vocabulary a semantic diff should be stated in).
- **Origin:** The half of "was it the data or was it us?" that RFC 0063 makes answerable and
  does not answer. That document produces two artifact sets; this one says why they differ.

---

## 1. Summary

With RFC 0063, a reader can compile March and compile today. Comparing the two is then a
diff over emitted text, which is the wrong altitude: it reports that a `CASE` arm moved and
not that the definition of revenue stopped excluding returns.

This document adds the edge that makes the comparison semantic. Two versions of a node,
identified by RFC 0062's stable id, are related by `supersedes`, and the graph carries what
changed between them at the level the specs are written in — grain, filter, unit,
additivity, the set of inputs.

```bash
bloomery explain metric.mtr_7f3a9c --changed-between 2026-03-01 2026-06-01
```

answers with a semantic delta and the exposures it reaches, not with a text diff.

## 2. Motivation

**A number changed and the cause is not in the number.** The reason lives in a spec edit,
possibly months old, possibly in a shared dimension nobody associates with this metric. The
current instrument for finding it is `git log` over a directory, read by a person who
already suspects where to look.

**A text diff answers the wrong question.** Emitted SQL differs for reasons that are not
semantic: a renamed CTE, a reordered join, a compiler change. A reader comparing two
artifact sets has to decide which differences matter, which is the judgement the compiler is
supposed to be making.

**The lineage graph already knows what a metric depends on and not what it used to be.**
`lineage` answers "what feeds this" and, with RFC 0056, "what does this feed". The missing
axis is "what was this", and it is the axis every incident starts on.

**`plan()` classifies but does not describe.** `ChangeClass` says a change was `RESTATING`
or `BREAKING`; it does not say the filter gained a predicate. The classification is what a
gate needs and the description is what a person needs, and only the first exists.

**Attribution is what makes the other two documents worth having.** Identity without history
is bookkeeping; history without attribution is two artifact sets and a manual diff. This is
the document that turns the sequence into an answer.

## 3. Current state

The lineage graph holds dependency edges between nodes that exist now. It has no notion of a
node having existed differently, because until RFC 0062 there was no identity to hang two
versions on and until RFC 0063 no way to obtain the earlier one.

`plan()` classifies changes between two spec sets and reports them structurally through
`ChangeClass` — additive, widening, rename, restating, breaking. What it does not do is say
*what* about a node changed in the vocabulary of the spec, and it operates between the tree
and a target rather than between two instants.

There is no edge kind in `ir/nodes.py` for a relation between two versions of one node. Every
edge today is between two different nodes at one time.

## 4. Goals / Non-goals

**Goals**

- A reader can ask why a metric's output changed and get an answer in spec vocabulary.
- The answer distinguishes a definition change from no definition change. "Nothing about
  this metric changed; look at the data" is a first-class, valuable result.
- A definition change reports the exposures and marts it reaches, reusing RFC 0056's sinks.
- Superseded versions are retained, not overwritten. The graph gains history rather than
  moving.

**Non-goals**

- **Attributing a change to the data.** bloomery does not read the warehouse. When the
  definition did not change, the answer is "not here", and pointing at the warehouse is the
  caller's next step, not this compiler's claim.
- **Quantifying impact.** How much a number moved is a warehouse question. This says what
  changed and what it reaches, never by how much.
- **Automatic rollback.** Naming a superseded version is not offering to restore it.
- **A semantic diff of arbitrary SQL.** Only what the specs declare is compared; a
  hand-written SQL body changing is reported as "the body changed" and not analysed.
- **Replacing `ChangeClass`.** The classification stays what a gate reads; this adds a
  description beside it, for a person.

## 5. Design

### 5.1 The edge

`supersedes` relates two node versions sharing one stable id. It carries the instant the
later version took effect and a structured delta.

The delta is expressed in spec terms and nothing else:

| Facet | Example |
|---|---|
| grain | order → order line |
| filter | a predicate added, removed or altered |
| unit | minor → major currency units |
| additivity | additive → semi-additive |
| inputs | a canonical entity added to or dropped from the set |
| body | opaque change to a hand-written expression |

`body` is deliberately coarse. Reporting "the expression changed" honestly is better than
reporting a token diff dressed as semantics.

### 5.2 Where the versions come from

Two compiles under RFC 0063 at two instants, matched by RFC 0062's ids. Nodes present at
both instants with differing definitions get a `supersedes` edge; nodes present at one only
are an add or a delete and are reported as such, not as a supersession.

This means the graph is *derived on demand*, not stored. Nothing persists between runs, and
the feature holds no state — which is the property that keeps it a pure function like
everything else.

### 5.3 The command surface

`explain <node> --changed-between A B` reports, per changed node on the metric's dependency
closure:

- the facets that changed, in the table's vocabulary
- the instant of the change, to the granularity RFC 0063's history source supports
- the exposures and marts downstream, from RFC 0056

**The closure is the point.** A metric whose own definition never moved can still change
because a dimension it joins was redefined. Reporting only the metric would be the same
narrow answer `git log` already gives.

### 5.4 Relation to the proof IR

Where RFC 0039's vocabulary exists, a facet delta should be stated in it — a change from a
proven additive rollup to an unproven one is a stronger statement than "additivity
changed". `Provenance` already ships with five members and a `closes` split, so a delta that
moved a fact from `DECLARED` to `INFERRED_HEURISTIC` is expressible today; the additivity
facet should say so rather than reporting only that the class changed. This document does
not depend on that and adopts it as those rules land.

## 6. Tests

- **A pure rename attributes nothing.** With RFC 0062, renaming a metric between the two
  instants produces a renamed node and an empty delta. If a rename shows up as a definition
  change, identity is not doing its job.
- **A filter change is attributed and located.** Add a predicate; the delta names the filter
  facet and the instant, and the reached exposures match RFC 0056's downstream set.
- **An unchanged metric over changed data reports nothing.** The valuable negative: the
  answer is "no definition change", and the test asserts it is stated rather than empty.
- **A transitive change is found.** Change a shared dimension, ask about a metric two hops
  away, and the changed node is named — not the metric.
- **A body change is reported coarsely.** Editing a hand-written expression yields the `body`
  facet and no claim about what it means.
- **Derivation is stateless.** Running the command twice over the same pair of instants
  produces identical output, and no file is written.

## 7. Docs

The incident page RFC 0063 introduces gains its second half: having reconstructed both
artifact sets, this is how to ask what moved. One page, one worked example, written as the
sequence a person actually performs.

## 8. Out of scope

- Storing the version graph. §5.2 derives it; persistence is a cache with an invalidation
  problem and no demonstrated need.
- Changes to the compiler itself. Two instants under different compiler versions are outside
  RFC 0063's promise and therefore outside this one.
- Column-level attribution within a mart, which needs identity below node level (RFC 0062
  §8).

## 9. Risks

- **A facet list is a closed world that will be wrong.** Every spec feature added later must
  decide which facet it lands in, and one that lands in none is silently unattributed —
  reported as unchanged when it changed. `check` should refuse a spec field that no facet
  covers, which turns the failure into a build error rather than a wrong answer.
- **The delta invites over-reading.** "Additivity changed" does not mean the number is wrong;
  it means a property the compiler tracks moved. Wording that implies fault will be quoted in
  incident reviews as if it were a verdict.
- **Cost is two full compiles.** For a large project that is not free, and the command will
  be run during incidents when patience is short. If it is slow enough to discourage use, it
  does not exist.
- **Coarse history granularity propagates.** RFC 0063's risk about squash-merges arrives here
  as an attribution that names a merge rather than an edit.

## 10. Unresolved questions

- Whether `plan()` should emit `supersedes` edges for the tree-versus-target comparison it
  already performs, making the same vocabulary available without RFC 0063.
- Whether an unchanged-definition answer should attempt to name what *else* could have moved,
  or stop cleanly at the compiler's boundary. Helpfulness here risks claiming knowledge of a
  warehouse this package does not read.
- Whether the facet list should be derived from the spec models rather than written out, so
  that D6's failure mode is a type error instead of a review miss.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | The delta is stated in spec vocabulary, never as a text diff of emitted SQL. A reader who has to decide which textual differences are semantic is doing the compiler's job. |
| 2 | `LOCKED` | Superseded versions are related, never overwritten. History that replaces cannot answer the question the feature exists for. |
| 3 | `LOCKED` | The compiler never attributes a change to data. "No definition change" is the complete and correct answer when the definition did not change. |
| 4 | `LOCKED` | Attribution runs over the dependency closure, not the named node. The single-node answer is the one `git log` already gives badly. |
| 5 | `ASSUMED` | The version graph is derived per invocation and not persisted. Statelessness is worth more than the compile it saves until a measurement says otherwise. |
| 6 | `OPEN` | **Superseded by 8.** Whether an unattributable spec field is a `check` refusal or a warning (§9). |
| 7 | `ASSUMED` | The delta sits beside `ChangeClass` rather than replacing it. A gate reads a class and a person reads a description, and collapsing the two costs whichever reader was not being served. |
| 8 | `ASSUMED` | **Neither — a test, plus a loud invariant; supersedes 6.** A `check` refusal would reject an author's specs for a gap in a table that ships with the compiler, and there is no warnings channel to put it in (RFC 0033 is unstarted). `test_every_field_of_every_comparable_record_has_a_facet` enumerates every field of every record the comparison can reach and requires a facet or an explicit identity exclusion for each, so a spec field added later turns red in CI — which is the mechanical failure §10's third question asks for. In production the same gap raises `InvariantViolated` rather than reporting a wrong answer. See `logs/T-0045.md`. |
| 9 | `ASSUMED` | **The `supersedes` edge is RFC 0069's `TimelineChange`, and `ir/nodes.py` gains no edge kind.** §5.1 and §3 designed a new edge before that walk existed; it now relates two versions of one node, carries the delta, and is derived per invocation exactly as §5.2 requires. Two records of one relation would be two places to be wrong, and the lineage graph is built from one project at one instant, so a cross-version edge in it has no version to belong to. D2 is satisfied by it: the earlier version is related to the later and neither is overwritten. See `logs/T-0045.md`. |
| 10 | `ASSUMED` | **The facets decide what a change *is*: one is emitted iff at least one facet differs, and `name`, `ref` and `id` belong to no facet.** §6's first test is that a pure rename attributes nothing, and it cannot be had any other way — a rename either moves no facet or is not a change. Identity is RFC 0062's business and is excluded once rather than blanked per kind, so the rule has one statement. See `logs/T-0045.md`. |
| 11 | `ASSUMED` | **Ten facet members, keyed by `(record type, field)`, with no fall-through.** §5.1's six are metric-shaped and the comparison spans seven node kinds and ten record types; `QUALITY`, `STORAGE`, `RUNTIME` and `METADATA` are what the rest need. Keyed by the pair because one field name means two things across kinds — `kind` on an `ExposureIR` is what a consumer *is*, and on a `StepIR` what executes it. An unmapped field raises: a field silently classified as metadata is exactly the failure §9 names. See `logs/T-0045.md`. |
| 12 | `ASSUMED` | **The additivity facet ships with the rest rather than waiting for P3.** §12 deferred it to P3 "stated in RFC 0039's provenance vocabulary", and under row 10 that would have made `agg: sum → avg` move no facet and therefore not be a change at all — §9's first risk, produced by the phasing. P3's deliverable is the *wording*, which §5.4 already presumes a facet to reword. See `logs/T-0045.md`. |
| 13 | `ASSUMED` | **§5.3's `explain <node> --changed-between A B` is struck.** `explain` is RFC 0066's command — its subject is a metric *request*, not a graph node — and the timeline's own command is RFC 0069 P3's. `--changed-between` is refused by RFC 0068 D2 in any case: it obliges bloomery to resolve an instant to a version, which is the caller's. Recorded rather than dropped, because a phase list with a command surface silently missing reads as a phase fully delivered. See `logs/T-0045.md`. |

## 12. Phasing

**P1** — the edge kind and the delta over the facets that need no proof vocabulary: grain,
filter, unit, inputs, body. Reported for one node.

**P2** — the dependency closure, which is what makes the answers correct rather than local.

**P3** — the exposure sinks from RFC 0056, and the additivity facet stated in RFC 0039's
provenance vocabulary.

P1 is demonstrable and incomplete: it will report a metric as unchanged when a dimension
beneath it moved. Ship it only with that stated, or land P1 and P2 together.
