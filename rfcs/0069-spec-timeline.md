# RFC 0069 — Spec timeline

- **Status:** ✅ Complete — all three phases have landed. P1 the value and the walk; P2
  the facets, with [RFC 0064](0064-definition-supersession.md) P1+P2, which is the document
  that owns them; P3 `bloomery timeline`, positional directories and `--format json`.
  **Retained rather than retired, at the author's instruction**, and it is a root of a live
  sequence in the sense [`INDEX.md`](INDEX.md) describes: RFC 0064 is still in progress and
  argues in this document's vocabulary — its rows 9 and 13 say the `supersedes` edge *is*
  `TimelineChange` and that the command surface is this one. Execution's findings and the
  rows it proposed are in [`logs/T-0043.md`](../logs/T-0043.md),
  [`logs/T-0045.md`](../logs/T-0045.md) and [`logs/T-0046.md`](../logs/T-0046.md); rows 14
  and 9's neighbours were appended from them, and nothing below has been amended to agree
  with what was built. Depends on [RFC 0062](0062-stable-node-identity.md) P1 for identity;
  assumes [RFC 0068](0068-caller-assembled-spec-history.md)'s answer to where history comes
  from.
- **Scope:** A second walk over a project, beside lineage. `lineage()` answers "what does
  this depend on"; `timeline()` answers "how has this changed". One value type, one pure
  function, one N-ary CLI command, and a rule that bloomery never parses an instant. No
  history fetching, no store, no new dependency.
- **Related:** [`src/bloomery/resolve/lineage.py`](../src/bloomery/resolve/lineage.py)
  (`lineage`, `Lineage` — the surface this mirrors),
  [`src/bloomery/plan/diff.py`](../src/bloomery/plan/diff.py) (`plan`, the existing two-spec-set
  function), [`src/bloomery/cli/__init__.py`](../src/bloomery/cli/__init__.py) (`plan`'s
  two-directory command, the precedent for an N-ary one), RFC 0062 (identity), RFC 0064
  (the delta), RFC 0068 (who assembles history), RFC 0056 (exposures — the sink a change
  reaches).
- **Origin:** Rejecting RFC 0063 established that the caller supplies spec history and cost
  one CLI flag. What it exposed is that the interesting gap was never *fetching* — it is
  **arity**. `plan(old, new)` takes two. A question a person actually asks — "how has this
  metric changed this quarter" — takes N, and there is no shape for that.

---

## 1. Summary

bloomery can compare two spec sets. It cannot describe a series of them.

```python
timeline(history, "metric.gross_revenue")
```

where `history` is an ordered sequence of `(label, ProjectIR)` the caller assembled — from
git revisions, from a table of versioned YAML, from directories on disk. The result is a
value: the versions this node had, and what changed between each adjacent pair.

It is the same shape as `lineage()` and answers the other question a reader has about a
node. Lineage is structure across the project at one instant; a timeline is one node across
the project's history. Both are pure functions over data the caller holds, and neither
reads anything.

## 2. Motivation

**"How did this change" is asked as often as "what does this touch", and only one has an
answer.** A metric owner meets a number they do not recognise. Lineage tells them what feeds
it. Nothing tells them that its filter moved three weeks ago.

**Two is an arbitrary number and it is the only one available.** `plan(old, new)` is the
whole of what exists, so a quarter's worth of change is either one lossy before/after or
sixty-odd pairwise calls the caller stitches together — and stitching them is where the
identity matching, the ordering and the add/delete edge cases get re-implemented, wrongly,
by every caller in turn.

**This is the feature that makes RFC 0062's ids pay.** A stable `id:` is currently an
investment against a rename, with the return arriving in a lineage graph that mostly looks
the same either way. Matching a node across sixty versions is where minting an id is
obviously worth it, and where not minting one is obviously visible: a rename becomes a
delete and an add, in a rendering a person is looking at.

**A UI wants a series, not a diff.** A change log beside a metric, a sparkline of when a
definition moved, a "what did this look like in March" picker — all of them read a sequence.
Handing a UI two IRs and asking it to do the matching puts the compiler's vocabulary in a
front end.

## 3. Current state

- **`lineage(graph, root, direction, *, max_depth) -> Lineage`** is the shape this mirrors:
  a pure function over a value the caller holds, returning a value with the root always
  present so an empty answer is still an answer.
- **`plan(old: ProjectIR | None, new: ProjectIR) -> Plan`** is the only version-aware
  function, and it is strictly pairwise. `plan(None, new)` is the initial deploy.
- **RFC 0062 P1 has landed**: an optional write-once `id:` on every spec kind that mints a
  node, and node ids built from it. Matching across versions has a key to use where one was
  adopted, and a name where one was not.
- **RFC 0064 is unstarted** and owns the delta between two versions — the facet table
  (grain, filter, unit, additivity, inputs, body) and the `supersedes` edge. Its §5.2 said
  the two versions come from RFC 0063; RFC 0068 rejected that and put the caller in charge,
  which changes where the pair comes from and nothing about the pair.
- **`bloomery plan old/ new/` takes two spec directories positionally.** An N-ary command is
  an extension of a shape the CLI already has, and needs no flag that resolves an instant.
- **Nothing in the tree parses a timestamp for ordering.** `datetime` is imported for the
  planner's literal grammar and the clock members are banned outright; there is no
  instant-comparison code to reuse, and §5.3 argues there should not be.

## 4. Goals / Non-goals

**Goals**

- `timeline(history, node)` returns the versions of one node and the change between each
  adjacent pair, as a value.
- The history is caller-assembled and consumed once, in the order given, so a generator
  that fetches lazily works.
- A node that never changed is a first-class answer, not an empty one.
- Identity is RFC 0062's id where adopted and the name otherwise, and the result says which
  it used.
- A CLI command renders it, and `--format json` is the shape a UI consumes.

**Non-goals**

- **Fetching history.** RFC 0068 D1. The caller hands over the sequence.
- **Parsing or comparing instants.** §5.3 — labels are opaque and order is positional.
- **Storing anything.** The walk is derived on demand, like RFC 0064's graph.
- **Attributing a change to the data.** RFC 0064's non-goal, unchanged and inherited.
- **Interpolating between entries.** If the caller supplies March and June, the answer is
  "it changed between these two", never "it changed in April".
- **A second delta vocabulary.** The facets are RFC 0064's, and if that document's table
  changes this one follows rather than forking.

## 5. Design

### 5.1 The value

```python
@dataclass(frozen=True, slots=True)
class SpecVersion:
    label: str
    project: Project
    catalog: Catalog | None = None

timeline(history: Iterable[SpecVersion], node: str) -> Timeline
```

**An entry carries the spec side, not the IR, and that is forced rather than chosen.**
A `ProjectIR` does not retain the authored `id:` — RFC 0062 substitutes it while building
node ids and the IR keeps only names, because putting the field in the IR would move every
fingerprint in the corpus and break that document's own D3 ("absent everywhere, a project
compiles byte for byte as it does today"). A timeline handed only IRs therefore *cannot*
match by id, which makes §5.2 unimplementable. Taking the `Project` fixes it at the source:
`node_keys(project, catalog)` is pure, and the IR each entry needs for P2's facets is
derivable from the same pair.

`Iterable`, not `Sequence`: §4 promises a generator is accepted, and a generator is not a
sequence. It is consumed once, in order, and never re-iterated — a caller fetching from a
store pays for every pass.

`Timeline` carries the node it was asked about, one entry per history entry, and the changes
between adjacent *present* entries:

```python
@dataclass(frozen=True, slots=True)
class Timeline:
    node: str
    entries: tuple[Entry, ...]      # Entry(label, present: bool) — one per history entry
    changes: tuple[Change, ...]     # Change(before, after, matched_by, facets=())
```

**One entry per history entry, present or not.** A gap is `present=False` at its own label,
which is what stops an implementation dropping the label or inventing a shape for it: the
absence has a position, and a reader can see *which* entry the node was missing from rather
than only that something was missing between two others. That is what makes a
delete-and-recreate distinguishable from a rename, which is the case RFC 0062 exists for.

It mirrors `Lineage` deliberately, including the property that matters most there: a node
that never changed returns a one-entry timeline with no changes rather than an empty one,
because "this has not moved since March" is the answer a reader came for at least as often
as the other.

**`facets` is empty in P1 and populated in P2.** P1 reports *that* two adjacent versions
differ; P2 fills in RFC 0064's facet vocabulary. The field is present from the start and
grows a value rather than appearing later, so the JSON a consumer reads does not change
shape between phases — which matters because §9 already notes a UI pins this earlier than a
library usually wants.

### 5.2 Identity

RFC 0062's stable id where the project adopted one, the node name where it did not. Mixed
adoption is legal — 0062 D4 allows partial adoption — so the answer is per node.

**Matching is decided per adjacent pair, and recorded there.** `Change.matched_by` says
whether that boundary was crossed by id or by name. Per pair rather than per timeline
because adoption is a thing that *happens*: a project that mints an `id:` in April has a
name-matched boundary in March and an id-matched one after, and a single per-timeline answer
would have to lie about one of them.

A pair matches by id only when **both** sides carry one. An id present on one side and
absent on the other falls back to the name, which is right in the common case — adopting an
id without renaming is continuous — and honest in the case it cannot recover: adopting an id
*and* renaming in the same entry reads as a delete and an add, because nothing connects the
two definitions except a guess about their shape.

Where a name was used and the name changed, the timeline shows a delete and an add. That is
not a defect to be papered over with heuristics: matching two definitions by their *shape*
is a guess, and a confidently wrong history is worse than an honest gap. The remedy is a
row in the spec, and the rendering should say so where it happens.

### 5.3 bloomery never parses an instant

The labels are opaque strings. They are carried into the result, rendered, and compared for
nothing. **Order is positional** — the sequence the caller supplies is the order, and
bloomery neither sorts nor validates it.

This is the decision that keeps the feature free of a class of problem it has no business
owning: time zones, resolution, clock skew, a commit timestamp that is not the definition's
effective date, two entries claiming the same instant. Every one of those is a property of
the caller's store, and every one of them is answerable there and unanswerable here. A
compiler that sorted its input by parsing dates would be asserting a total order over data
it did not produce.

The cost is stated: a caller who supplies entries out of order gets a timeline that is out
of order, and nothing refuses it. That is the same trust the corpus already places in
`plan(old, new)`, where nothing checks that `old` is older.

**Opaque is not the same as arbitrary, and the docs say so.** The recommended label is one
canonical form — `YYYY-MM-DDTHH:MM:SSZ`, UTC, no offset and no fractional part — because
that form and only that form sorts lexicographically into chronological order. ISO-8601 at
large does not: `2026-03-01T00:00:00-01:00` sorts *before* `2026-03-01T00:00:00Z` and is an
hour *later*, and a fractional part reorders against a whole second. Recommending
"ISO-8601" without narrowing it would hand a consumer a sort that is right until the day
someone's store emits a local offset.

`--format json` carries labels verbatim, so a consumer that wants to sort can — and sorting
is a rendering decision made by the layer that knows what the labels mean. The
recommendation is a convention, enforced nowhere; a label of `"before"` and `"after"` is a
legitimate history of two entries.

### 5.4 The surface

```console
$ bloomery timeline q1/ q2/ q3/ --node metric.gross_revenue
metric.gross_revenue  (3 versions, 2 changes)
  q1/ → q2/   filter   added: status in ('paid')
  q2/ → q3/   grain    order → order_item
```

Positional spec directories, exactly as `plan old/ new/` takes two. The caller materialised
them; bloomery resolves nothing. `--format json` emits the value, which is what a UI reads.

This does not reintroduce what RFC 0068 D2 refuses. That row bans a flag obliging bloomery
to know what a history *is* — which store, which instant-to-version mapping, what to do when
it is ambiguous. A list of directories obliges none of it.

### Alternatives considered

**A `HistoryResolver` port the caller implements.** Considered and rejected in RFC 0068: a
protocol nothing calls is documentation with syntax, and one bloomery calls inverts control
into the one part of the codebase whose value is that it has none. Structural typing also
means declaring it later costs nothing — code written today conforms retroactively.

**Timeline as a phase of RFC 0064.** That document is pairwise throughout, including its
command surface and its three phases. Generalising it in place would rewrite it rather than
extend it, and the pairwise delta is worth having on its own.

**Instants as `datetime`, sorted by bloomery.** Rejected in §5.3. It buys validation of an
order the caller already knows and costs a timezone semantics nobody asked this project to
own.

**A timestamp on the spec — `effective_from:` or similar.** This is RFC 0063 §5.1's
Candidate B, argued down there for being a second place to be wrong, and it has a second
problem that argument did not name: `project_fingerprint` is a content hash of `ProjectIR`.
If the field enters the IR, an identical definition that someone re-dated produces a
different fingerprint — the fingerprint becomes a function of *when* rather than of *what*,
which is the one thing it exists not to be. If it stays out of the IR, it is a spec field
the compiler ignores, present for exactly one feature and silently wrong whenever an author
forgets it.

It also fails the rule the corpus's existing history annotations follow. `renamed_from:` and
RFC 0062's `id:` carry what the compiler **cannot derive**; a timestamp is what the caller's
store already knows, and a second copy of a fact is a fact that can disagree with itself.
RFC 0062 D6 states the sharp version while arguing that an `id:` is write-once: *an
annotation only exists in the current spec*. A date in the March file records what March's
author believed, which is not the same as when March happened.

**Auto-stamping at compile.** Not a design choice — `datetime.datetime.now` is on the
banned-import list under `src/bloomery/` ("no ambient clock", RFC 0003 §5.5). A compiler
that stamped the time would stop being a function of its inputs.

**Storing the timeline.** A derived value recomputed from inputs is the corpus's shape for
everything else, and a stored history is a second source of truth that can disagree with
the specs.

## 6. Tests

- **A node that never changed** returns one version and no changes, not an empty timeline.
- **A rename without an `id:`** reads as a delete and an add; the same rename **with** one
  reads as a single node across the boundary. The pair is the test that RFC 0062 pays.
- **A gap is an absence, not a skip.** A node missing from a middle entry gets its own
  entry at that label with `present=False`, and the changes step over it rather than
  eliding to a single change that spans it.
- **Order is positional.** A history supplied in reverse produces a reversed timeline and no
  refusal — pinned so that adding a sort later is a visible decision rather than a fix.
- **The labels are never parsed.** A history whose labels are `"a"`, `"b"`, `"c"` works
  identically to one whose labels are dates.
- **Lazy consumption.** A generator is accepted and read once; the test asserts it is not
  re-iterated, since a caller fetching from a store pays for every pass.
- **An id adopted partway through** keeps one node across the boundary, and the change at
  that boundary reports `matched_by` as the name rather than the id. Adopting an id *and*
  renaming in one entry reads as a delete and an add — asserted, because it is the case the
  rule cannot recover and a reader should find it written down rather than discover it.
- **`facets` is empty in P1 and the shape does not change in P2.** Asserted against the
  field's presence, so a consumer pinned to the P1 JSON keeps parsing after P2 lands.
- **The facets are RFC 0064's**, asserted against that vocabulary rather than restated, so
  the two cannot fork.

## 7. Docs

`pages/docs/how-to/trace-a-definition-over-time.md`, sited beside
[`trace-lineage.md`](../pages/docs/how-to/trace-lineage.md) — the two are the pair this
document argues they are, and a reader who found one should see the other. It must state
§5.3's cost plainly: bloomery reports the order it was given, and the ISO-8601
recommendation is where a reader meets it — a page that shows `"q1"`, `"q2"` labels and
says nothing about ordering teaches the wrong habit by example.

## 8. Out of scope

- **Ranges over the dependency graph.** "Every metric that changed in Q1" is a different
  query with a different cost; this is one node.
- **RFC 0064's command surface.** It keeps its own; this adds one beside it.
- **Rendering.** A sparkline is a front end's business; `--format json` is the contract.
- **Bisecting.** "Find the entry where this changed" is a caller loop over this function.

## 9. Risks

- **Sixty IRs is sixty compiles.** A quarter of daily history is a real cost and it lands on
  the caller, who is also the only party able to decide the resolution they need. The docs
  should show a coarse history first.
- **Positional order is trust, and trust is occasionally misplaced.** §5.3 accepts this; the
  mitigation is that it is stated in the docs and pinned by a test, not that it cannot
  happen.
- **The pairwise delta does not exist yet.** RFC 0064 is unstarted, so this document's
  useful half depends on a document nobody has scheduled. P1 below is shaped to be worth
  landing before it.
- **A UI reading `--format json` pins the value's shape earlier than a library usually
  wants.** Worth knowing before the first consumer ships, not after.

## 10. Unresolved questions

- Whether `timeline()` should *also* accept a prebuilt `ProjectIR` beside the `Project`,
  saving P2 a build the caller may already have done. Row 11 settles that the `Project` is
  required — identity lives there and nowhere else — and leaves open whether the IR may be
  supplied alongside it as a cache.
- Whether a node absent from every entry is an empty timeline or a refusal. `lineage()`
  refuses an unknown node, and the two should probably agree.
- Whether the CLI command should accept a manifest file listing entries, for the caller with
  sixty of them and a shell that will not take sixty arguments.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | bloomery never parses, sorts or compares the labels. Order is positional and the caller owns it. Parsing instants would make this project the owner of timezone and resolution semantics over data it did not produce, and every one of those questions is answerable in the caller's store and unanswerable here. |
| 2 | `LOCKED` | History is caller-assembled and consumed once, in order. Inherited from RFC 0068 D1; restated because this is the document a reader lands on when they want the feature, and the constraint has to be where they look. |
| 3 | `LOCKED` | The delta vocabulary is RFC 0064's and is never restated here. Two tables describing one thing is the drift this corpus has paid for before. |
| 4 | `ASSUMED` | A node that never changed returns a one-version timeline. It mirrors `Lineage`'s root-always-present rule, and "this has not moved" is a result rather than a miss. |
| 5 | `ASSUMED` | Matching is RFC 0062's id where adopted and the name otherwise, per node, with the result saying which. No shape-based heuristic recovers a rename: a confidently wrong history is worse than an honest delete-and-add. |
| 6 | `ASSUMED` | The CLI command takes spec directories positionally, like `plan`. It resolves nothing, so RFC 0068 D2 is untouched. |
| 7 | `OPEN` | Whether an unknown node is an empty timeline or a refusal (§10), and whether `lineage()`'s answer should change to match. |
| 8 | `OPEN` | Whether the command accepts a manifest file for long histories (§10). |
| 9 | `ASSUMED` | **Superseded by 10.** ISO-8601 labels are a documented **convention**, enforced nowhere. It sorts lexicographically and is what a store hands over anyway, so a consumer that wants an order has one — but the recommendation lives in the docs rather than in a check, because row 1 says bloomery does not read the labels and a validator would be reading them. Timestamping the spec itself is refused for a different reason, in §5.1's alternatives: it would put a fact the caller's store already holds into the fingerprint. |

| 10 | `ASSUMED` | **The recommended label is `YYYY-MM-DDTHH:MM:SSZ` — UTC, no offset, no fractional part — and not "ISO-8601" at large; supersedes 9.** Only that form sorts lexicographically into chronological order: `2026-03-01T00:00:00-01:00` sorts before `2026-03-01T00:00:00Z` and is an hour later, and a fractional part reorders against a whole second. Row 9's reasoning is unchanged and its claim was too wide. Still a convention and still enforced nowhere, because row 1 says bloomery does not read the labels. |
| 11 | `LOCKED` | **A history entry carries the `Project`, not the `ProjectIR`.** The IR does not retain the authored `id:` — RFC 0062 substitutes it while building node ids and keeps only names, because a field in the IR would move every fingerprint and break that document's D3. A timeline handed only IRs cannot match by id, which makes row 5 unimplementable; taking the spec side fixes it at the source, and the IR P2 needs is derivable from the same pair. Locked because reversing it silently reduces identity to name matching, which is the failure this feature exists to avoid. |
| 12 | `ASSUMED` | **Matching is decided per adjacent pair and recorded on the change, and a pair matches by id only when both sides carry one.** Adoption is something that happens partway through a history, so one per-timeline answer would have to lie about one side of it. Adopting an id without renaming stays continuous; adopting one *and* renaming in the same entry reads as a delete and an add, which is the honest answer rather than a shape-matching guess. |
| 13 | `ASSUMED` | **Partly superseded by 14.** **The value carries one entry per history entry, present or absent, and `facets` exists from P1 as an empty tuple.** An absence with a position says which entry the node was missing from rather than only that something was missing; and a field that grows a value rather than appearing in P2 keeps the JSON shape stable across phases, which §9 notes a UI pins earlier than a library usually wants. |
| 14 | `ASSUMED` | **Row 13's shape promise holds and its value promise does not; supersedes 13 on that half alone.** `facets` is present and is a tuple in every phase, so the JSON a consumer reads never changes shape — but it is never *empty*, because RFC 0064 row 10 makes an empty delta mean "not a change" and the row is not emitted. Row 13's first reading — a pure rename reported as a change carrying nothing — is the wrong answer to RFC 0064 §6. The absence half of row 13 is unchanged. See `logs/T-0045.md`. |

## 12. Phasing

**P1** — the value type, `timeline()`, identity matching and absence handling, reporting
*that* a version differs without saying how: `facets` is present and empty. Depends on
nothing unstarted — the comparison is IR equality per node, over the IR built from each
entry's `Project`.

**P2** — the facets, which is RFC 0064's delta applied to each adjacent pair. This is the
half a reader actually wants and it cannot land before that document.

**P3** — the CLI command and `--format json`.

P1 is worth landing alone and is honest on its own: "this definition changed between these
two entries, and not between those" is already more than exists, and it is the half that
makes RFC 0062's ids visibly pay.
