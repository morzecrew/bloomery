# RFC 0030 — The unresolved-work report

- **Status:** 📝 Draft — design proposed, not scheduled. The trigger is a recipe
  chooser that returns partial resolutions; see §12.
- **Scope:** Giving an **upstream chooser** — the agent that records `recipe:`
  ids into mappings — a machine-readable statement of what a spec leaves open
  and what would close it, so it can iterate to a fixed point across compile
  invocations. Adds an `UnresolvedWork` projection to
  [`SpecEvidence`](../src/bloomery/evidence.py) and restores `provenance` to
  it. **No spec surface changes and no new document kind**: the "undecided"
  state is already expressible and already compiles (§3), so this RFC adds a
  *report*, not a vocabulary. It deliberately does **not** let the compiler
  choose, rank, score or recommend a recipe — RFC 0005 D2 is untouched and this
  document exists partly to say why enumerating is not choosing. It also ships
  no chooser: bloomery has no agent, and this is an input to one.
- **Related:**
  [`src/bloomery/evidence.py`](../src/bloomery/evidence.py) (`SpecEvidence`,
  `evaluate`), [`src/bloomery/resolve/recipes.py`](../src/bloomery/resolve/recipes.py)
  (validates and never chooses), [`src/bloomery/resolve/reach.py`](../src/bloomery/resolve/reach.py)
  (`UnreachableMetric`, `missing`, `via`),
  [`src/bloomery/resolve/resolution.py`](../src/bloomery/resolve/resolution.py)
  (`Provenance`, `FieldProvenance`),
  [`src/bloomery/spec/catalog.py`](../src/bloomery/spec/catalog.py) (`Recipe`,
  `CanonicalField`), [`src/bloomery/cli/render.py`](../src/bloomery/cli/render.py)
  (`render_evidence`). RFC 0005 (the DAG, D2 "validates and never chooses", D3
  "`missing` names leaves"), RFC 0022 (`SpecEvidence`, D5 the stage-first rule,
  D8 the `resolve` re-point), RFC 0020 D4 (the CLI is not a lossier surface),
  RFC 0003 (determinism).
- **Origin:** Naming the work an agent would do surfaced that bloomery reports
  the *gap* and not the *decision*, and that two gaps needing different fixes
  are reported identically (§3).

---

## 1. Summary

An upstream chooser records recipe ids; the compiler validates them and never
chooses. That split is right and this RFC does not touch it. What the split
lacks is a loop: an agent that resolves a spec one decision at a time needs to
know, each round, **what is still open, what would close it, and what it has
already decided** — and today it can derive only the first, from a report that
cannot distinguish two situations demanding different edits.

So `SpecEvidence` gains `unresolved`, one entry per open decision, each naming
the canonical field that is unavailable, **the shape of the gap**, the recipes
the catalog offers with their required alias slots, and the metrics blocked on
it. It gains `provenance` back at the same time, because a loop needs its own
memory and that value is computed on every `resolve()` and thrown away.

Nothing is chosen and nothing is ranked. The report is a projection of the
catalog and the specs, joined the way a chooser would have to join them anyway.

## 2. Motivation

**Resolution is already a loop, and bloomery reports it as a snapshot.** A
chooser proposes an id, the compiler accepts or refuses it, and the next round
depends on what the last one changed. That is a fixed-point iteration whose
state lives entirely in the mapping documents — which is the right place for it
— but whose *progress* has to be re-derived from scratch each round.

**Two gaps that need different edits report identically.** Measured (§3, cases
`(c)` and the no-link case): a metric blocked because no entity field carries
`canonical: order.net_revenue`, and a metric blocked because a field carries the
link and no mapping produces it, both come back as

```
unreachable: [('total_net_revenue', ['order.net_revenue'], [])]
```

The first needs an entity-model edit; the second needs a mapping edit, and the
mapping edit is where the *choice* is. A chooser handed that tuple has to open
the entity model to find out which of the two it is looking at, and then open
the catalog to find out what its options are. Both joins are mechanical, both
are the compiler's own, and both are re-implemented by every caller that needs
them.

**The one thing a chooser must never do is guess, and the report makes guessing
easier than not.** `missing` names a canonical field. The recipes for it, and
what each one requires, are in the catalog under a different key
(`canonical_fields.<name>.recipes`), and the alias slots a recipe demands
(`Recipe.requires`) are matched against a mapping key (`from:`) in a third
document. A chooser that gets any part of that join wrong produces a `recipe:`
the compiler refuses — which is the loud failure RFC 0005 D2 wants, and also a
round wasted on something the compiler could have stated.

**And the loop has no memory.** `FieldProvenance` — direct, recipe (with the id),
or native, per mapped field — is computed by `resolve()` on every call and
**discarded**: it is not on `SpecEvidence`, so it has not been on the CLI since
RFC 0022 D8 re-pointed `bloomery resolve` at `evaluate()`. The value that says
"you already decided this one, and this is what you decided" exists, is
correct, and reaches nobody.

## 3. Current state

Verified against `main` @ `4f4c490` by compiling five specs, not by reading.

**The "undecided" state already exists and already compiles.** This is the
finding that decides the shape of the RFC: an entity field that carries a
`canonical:` link and that no mapping produces is a *legal, complete* spec whose
dependent metric is reported unreachable.

| Spec | `stage_reached` | reachable | unreachable |
| --- | --- | --- | --- |
| (a) field mapped directly | `complete` | `['total_net_revenue']` | — |
| (b) field records a recipe | `complete` | `['total_net_revenue']` | — |
| (c) field declared, **not mapped** | `complete` | — | `total_net_revenue` missing `order.net_revenue` |
| (c′) same, but `required: true` | `complete` | — | *identical to (c)* |
| (c″) **no field links** to the canonical | `complete` | — | *identical to (c)* |
| (d) recipe id not in the catalog | `resolve` | — | *not computed* |
| (e) recipe's `requires` unbound | `resolve` | — | *not computed* |

Three consequences, each load-bearing:

- **No spec vocabulary is needed.** Absence already means "undecided", including
  for a `required:` field — `required` constrains the emitted column, not the
  mapping. A `TODO:` marker would be a second way to say what absence says.
- **(c), (c′) and (c″) are indistinguishable in the report and need different
  fixes.** That is the gap.
- **(d) and (e) lose the report entirely.** Recipe validation runs inside
  `resolve()`, the pipeline's *first* stage, so a refusal there means
  reachability is never computed and `unreachable` is empty for the reason
  RFC 0022 D5 exists to disambiguate. A chooser that records one malformed
  choice gets a precise error and **no worklist**.

**The compiler's refusal messages are already the right shape.** Measured:

```
ResolutionError: recorded recipe 'nosuch' does not exist on canonical field
'order.net_revenue'; known recipes: ['direct_net', 'gross_minus_tax'].
The compiler never re-chooses — the upstream chooser must re-decide
```

That message already enumerates the options. This RFC generalizes what that one
error does well into a report that does not require being wrong first.

**`Recipe.requires` names alias slots, never canonical fields.**
[`resolve_recipe`](../src/bloomery/resolve/recipes.py) checks
`set(recipe.requires)` against `set(field_mapping.from_)` — the mapping's `from:`
keys, which bind to **source paths**. Both unbound requires and surplus aliases
are errors. This is what makes §5.4's termination argument structural rather
than hopeful.

**`SpecEvidence` today** carries `stage_reached`, `fingerprint`, `reachable`,
`unreachable`, `refusals`, `marts`, `entities` — and its JSON surface is those
seven keys, confirmed through `serialize.as_json_value`. No provenance.

## 4. Goals / Non-goals

**Goals**

- State every open decision, and for each one the edit that would close it.
- Distinguish "nothing links to this canonical" from "something links to it and
  nothing produces it", because they are different edits.
- Enumerate the options the catalog already declares, with the alias slots each
  demands, so a chooser does not re-implement a three-document join.
- Give the loop memory: what has already been decided, and how.
- Make termination a property of the design, argued rather than assumed.

**Non-goals**

- **Choosing.** RFC 0005 D2 stands untouched. Not for a single-option field
  either (D4).
- **Ranking, scoring or recommending.** Enumeration is a projection of the
  catalog; a ranking is an opinion, and an opinion is a choice with a
  disclaimer.
- **Shipping a chooser.** bloomery compiles; the agent is a caller.
- **A new spec surface or document kind.** §3 shows none is needed.
- **Changing what the compiler refuses.** Every refusal in §3 stays exactly as
  loud.

## 5. Design

### 5.1 The value

```python
class Gap(StrEnum):
    """Why a canonical field is unavailable — which decides the edit."""
    UNLINKED = "unlinked"   # no entity field carries `canonical: <name>`
    UNMAPPED = "unmapped"   # a field carries it; no mapping produces the field

@dataclass(frozen=True, slots=True)
class RecipeOption:
    """One derivation the catalog declares, as the chooser needs it."""
    id: str
    requires: tuple[str, ...]     # alias slots the mapping's `from:` must bind
    expr: str | None              # None = identity over a single requirement

@dataclass(frozen=True, slots=True)
class OpenDecision:
    canonical: str                     # the unavailable canonical field
    gap: Gap
    entity: str                        # the catalog entity it belongs to
    field: str | None                  # the linked field — set iff UNMAPPED
    options: tuple[RecipeOption, ...]  # catalog order (D2); may be empty
    blocks: tuple[str, ...]            # metrics blocked on it, sorted
```

`SpecEvidence` gains two fields:

```python
    unresolved: tuple[OpenDecision, ...] = ()
    provenance: tuple[FieldProvenance, ...] = ()
```

Both default to `()`, so every existing construction keeps working, and both are
read under the stage-first rule (RFC 0022 D5): empty means "nothing open" only
at `Stage.COMPLETE`.

`OpenDecision`s are sorted by `canonical`; `provenance` is sorted by
`(entity, field)`, which is the order `_field_provenance` already produces and
which is stated here because an order that is only an implementation's habit is
one a reimplementation may not keep. **`options` is the one collection here that
is not sorted** — see D2.

### 5.2 What "open" means, exactly

An entry exists for each canonical field that is (i) required by some effective
metric, transitively, (ii) not available, and (iii) actionable in the sense the
next paragraph fixes. Both halves already have an
implementation: `compute_reachability` walks the closure and
`available_canonicals` reads the `canonical`-labelled edges of the one shared
DAG. This RFC adds no second notion of availability — a report that disagreed
with reachability about what is missing would be worse than no report.

A canonical field nothing requires is **not** work. `blocks` is therefore never
empty, and it is what turns a worklist into a priority the *caller* can set:
bloomery says which metrics each decision unblocks and stops there.

**Every entry names one edit, and an entry that cannot is omitted** (D9). The
report's whole promise is "here is the edit that would close this", so an entry
a caller cannot act on is worse than a gap: it is a worklist item that never
clears. One shape has that problem today — a canonical whose entity is built by
**more than one mapping** (RFC 0024). Its columns are per mapping
(RFC 0024 D26), so a recipe choice has no single mapping to target, and an
`OpenDecision` keyed on `canonical` cannot say which document to edit. Such
entries are left out until the report can name the mapping, and nothing is
hidden by that: the metric blocked on the field is still reported unreachable by
the machinery that already existed.

### 5.3 The two gaps, and why the distinction is the point

`gap` is decided by one question, asked of the entity model rather than of the
mappings: does any entity field carry `canonical: <name>`?

- **`UNLINKED`** — none does. `entity` is the catalog's own `CanonicalField.entity`,
  which is where such a field would go; `field` is `None`; `options` are still
  enumerated, because the author will need them at the next step and the same
  join produces them.
- **`UNMAPPED`** — one does, and `entity`/`field` name it. This is the entry a
  chooser acts on: the edit is a mapping field, and `options` are what it may
  record.

Two fields, one question, and it is the question a caller currently answers by
opening the entity model.

### 5.4 Termination, argued

The loop is: read the report, record one choice, compile again. It terminates,
and the reason is structural rather than a bound anyone has to trust.

Let `O` be the set of open canonicals. `O` is a subset of the canonical fields
the effective metrics require transitively, which is fixed by the catalog and
the metric set — neither of which a chooser edits. Recording a choice binds a
recipe's `requires` to **source paths** (§3), never to canonical fields, so no
edit a chooser makes can add a member to `O`.

**Removing one takes up to two edits, and the two are different edits** — this
is where an earlier draft of this section was wrong, and the distinction §5.3
draws is exactly what makes it visible. An `UNMAPPED` entry is closed by a
mapping edit, which is the recipe choice. An `UNLINKED` entry cannot be: there
is no field to record a recipe on, so an entity-model edit adds the linked field
and the entry becomes `UNMAPPED`. That is progress without removal — `|O|` is
unchanged and the entry's `gap` has advanced — and no edit *in the loop* runs
the transition backwards, because closing an entry never removes a `canonical:`
link. A caller free to edit the entity model arbitrarily can of course undo its
own work; the bound is over a chooser that is trying to resolve, not over every
sequence of edits.

So the measure that decreases is not `|O|` but the pair
`(|O|, count of UNLINKED entries)` under lexicographic order: an entity-model
edit leaves the first component alone and decreases the second, a mapping edit
decreases the first. The loop therefore ends in at most `2|O|` rounds, at a
fixed point that is either "nothing open" or "the open entries have no options
and need source data that does not exist".

**A chooser that only writes mappings terminates on the `UNMAPPED` subset and
leaves every `UNLINKED` entry standing.** That is a correct outcome rather than
a stall, and it is the honest answer to who does which edit (§10).

**The one way this breaks is a change to `Recipe.requires`.** If a recipe were
ever allowed to require a *canonical* field rather than an alias slot, recipes
would compose, `O` would gain members mid-loop, and this argument would need
replacing with a cycle check. That is not proposed here and D6 records the
coupling so the next person to reach for it knows what it costs.

### 5.5 Where it lives, and where it does not

On `SpecEvidence`, not in a value of its own. RFC 0022 exists because assembling
an answer "from three calls and two exception handlers" is the failure; a second
analysis value would restore exactly that, and a caller would then have to
reconcile two reports that can disagree about which stage they describe.

It is computed in `evidence.py` from the `Resolution` the pipeline already
produces plus the catalog, and **not** in `resolve/`. `Resolution` is embedded in
IR construction and reaches fingerprinted output; a presentation join has no
business there.

### Alternatives considered

**A `TODO:`/`undecided:` marker in the mapping spec.** Rejected on §3's
measurement: absence already compiles and already reports. A marker would be a
second spelling of the same state, and the two would drift — a field marked
undecided *and* mapped, or mapped and still marked.

**Have the compiler pick when exactly one recipe qualifies.** Rejected, and D4
locks it. It is the most tempting erosion of RFC 0005 D2 because it looks free:
one option is not a choice. But "qualifies" is the compiler forming an opinion
about which recipes are applicable, the arity is a property of the catalog on
the day it was read, and a spec that silently acquires a derivation is one whose
author cannot see what produced their numbers.

**Rank the options** — by requirement count, by whether the source paths look
present, by any heuristic. Rejected: a ranked list is a recommendation, a
recommendation is a choice the caller is invited to accept, and the failure mode
is a chooser that takes the first row every time. The catalog's own order is
authored and is preserved (D2); nothing is added to it.

**Report the missing *source paths* rather than the recipes.** Rejected as
undecidable here: bloomery does no I/O (RFC 0003), so it cannot know which paths
a bronze relation actually carries. Reporting a guess as a fact is worse than
reporting the options and letting a caller that *can* read the source decide.

**Compute the report before validation, so (d)/(e) keep their worklist.**
Genuinely attractive and not taken — see D5, which records both sides.

## 6. Tests

- **The seven cases of §3 as a table-driven battery**, asserting the report for
  each. The claim is not that all three `(c)` cases differ — `(c)` and `(c′)`
  differ only in `required:`, which constrains the emitted column and not the
  mapping, so they must produce the **same** report. What must differ is
  `(c″)`: it is `UNLINKED` where the other two are `UNMAPPED`, and today all
  three are identical. Written as one parametrization rather than three tests so
  a reader sees which pair is meant to agree and which one is meant to split.
- **A loop test, run to a fixed point.** Start from a spec with several open
  decisions, apply each round's first entry mechanically, recompile, and assert
  the open set strictly shrinks and terminates. This is §5.4 as a check rather
  than as prose — and it is the test that would fail if `Recipe.requires` ever
  gained canonical semantics.
- **Determinism**: same specs in ⇒ identical report, across processes and hash
  seeds, like every other bloomery output.
- **`options` preserves catalog order** — asserted against a catalog whose
  recipe order is *not* alphabetical, so a stray `sorted()` fails it. Without
  that, the test passes on any catalog whose author happened to write them in
  order.
- **The report never names a canonical that reachability calls available**, over
  the fixture corpus: one notion of availability, asserted rather than intended.

## 7. Docs

- A how-to for the chooser loop, wherever
  [`evaluate-a-spec.md`](../pages/docs/how-to/evaluate-a-spec.md) leaves off:
  read the report, record one choice, recompile.
- The reference gains `OpenDecision`, `Gap`, `RecipeOption` and the two new
  `SpecEvidence` fields.
- **The docs must not describe the report as advice.** "Options the catalog
  declares" and never "suggestions", "candidates" or "the best recipe" — the
  wording is the mitigation for §9's first risk, and it is the one part of this
  document a reviewer should hold to the letter.

## 8. Out of scope

- **The chooser itself.** bloomery emits and never decides. Would change if
  someone proposes a chooser *in* bloomery, which would be a different RFC and
  would have to argue against RFC 0005 D2 head-on.
- **Source-path introspection** — knowing whether `$.gross` exists in a bronze
  relation. That needs I/O, which RFC 0003 forbids in compilation. Would change
  only with a separate, explicitly-impure tool.
- **Recipe composition** (a recipe requiring a canonical field). Named in §5.4
  because it is what would break termination, not because it is planned.
- **Multi-mapping entities.** A merged entity's fields are per mapping
  (RFC 0024 D26), so an open decision would have to be per `(entity, field,
  mapping)` to name an edit. Rather than leave that under-specified, D9 omits
  such entries from the report entirely — the blocked metric is still reported
  unreachable, so the gap stays visible and only the un-actionable worklist
  entry is withheld. Would change when the report carries a mapping identity,
  which belongs with RFC 0024 P2.

## 9. Risks

- **The report is read as advice.** The largest risk and the one this design is
  shaped around: a chooser that treats `options[0]` as a recommendation has
  reintroduced the compiler choosing, with the audit trail pointing at the
  agent. Mitigated by never ranking (D2), by the field name, and by §7's wording
  rule — all three are weaker than a mechanism, and no mechanism is available.
- **Catalog order is read as arbitrary and re-sorted by a consumer.** The
  inverse risk, and real: `Recipe`'s own docstring says recipes are "ordered by
  reliability in the catalog", so that order is authored information a caller
  can silently destroy. D2 states it; nothing enforces it downstream.
- **The loop is run against a spec that refuses.** By D5 the report is empty
  there, and an agent that does not read `stage_reached` first will read that as
  "nothing left to do" — the exact misreading RFC 0022 D5 exists to prevent,
  arriving through a new field.
- **`unresolved` and `unreachable` drift.** Two reports over one question. §5.2
  builds both from the same availability set and §6 asserts they agree; a future
  change that gives the report its own notion of availability is where this
  fails.

## 10. Unresolved questions

- **Does the human CLI table print it, or only `--format json`?** The table is a
  summary by design and RFC 0020 D4 puts the lossless surface in JSON. An open
  decision is arguably the most actionable thing `bloomery resolve` could say,
  which argues the other way. Whoever builds this decides (D7).
- **Should `blocks` name metrics only, or metrics and the marts that carry
  them?** Metrics are what reachability speaks in. A mart is what a reader
  recognizes.
- **Should `UNLINKED` entries live in a different collection?** D10 settles the
  mechanics — they close by an entity-model edit and a mapping-only chooser
  correctly leaves them standing — but not the presentation. One collection with
  a `gap` field says "same worklist, different edit"; two collections say "these
  are not yours". The second is a stronger claim about who a caller is, and this
  document is not ready to make it.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | **The report is derived; no spec surface changes.** §3 measured that a `canonical:`-linked field with no mapping is a legal, complete spec whose metric is reported unreachable — including when the field is `required:`. "Undecided" is therefore already expressible, and a marker would be a second spelling of it. Consequence: this RFC touches no document kind, no `spec_version`, and no parser. |
| 2 | `LOCKED` | **`options` is enumerated in catalog order and never sorted, ranked or scored.** Enumerating what the catalog declares is a projection; ordering is where a preference would hide. `Recipe`'s docstring makes catalog order *authored* ("ordered by reliability"), so re-sorting — alphabetically included — destroys information rather than normalizing it. Consequence: this is a deliberate exception to the sort-every-collection habit, and it needs the §6 test with a non-alphabetical catalog or the exception is untested. |
| 3 | `LOCKED` | **The two gaps are distinguished, and that is the RFC's reason to exist.** `UNLINKED` and `UNMAPPED` are reported identically today and need different edits (§3). Consequence: the report reads the entity model, not only the DAG, which is why it lives in `evidence.py` and not in `resolve/`. |
| 4 | `LOCKED` | **A single available option is still not chosen.** The tempting erosion of RFC 0005 D2, refused explicitly so it is not re-proposed as an optimization: "exactly one qualifies" requires the compiler to have an opinion about qualification, the arity is a fact about the catalog on one day, and a spec that silently acquires a derivation is one whose author cannot account for their own numbers. |
| 5 | `ASSUMED` | **The report is a `COMPLETE`-stage product; a refusal empties it.** Recipe validation is in the pipeline's first stage, so a malformed choice costs the round's worklist (§3, cases (d)/(e)). Accepted because the refusal messages already name the fix precisely and the loop still terminates — fix the error, recompile, read the report. Graded `ASSUMED` rather than `LOCKED` because it is a claim about how an agent behaves, and whoever builds this may find the loop needs the partial report; the alternative is computing the options half before validation, which is possible since it needs no DAG. |
| 6 | `LOCKED` | **Termination rests on `Recipe.requires` naming alias slots, never canonical fields.** Verified in `resolve_recipe`, which matches `requires` against the mapping's `from:` keys. Consequence: recipe *composition* would break the argument in §5.4, not merely complicate it, and would need a cycle check over recipes. Recorded here so the coupling is visible from the feature that would break it. |
| 7 | `OPEN` | **Whether the human CLI table prints open decisions.** JSON gets them by construction. The table is a summary (RFC 0020 D4), and this is either the most useful line `bloomery resolve` could print or the one that turns a summary into a dump. Whoever builds this decides and logs it. |
| 8 | `ASSUMED` | **`provenance` returns to `SpecEvidence`.** It is computed on every `resolve()` and discarded, and has been off the CLI since RFC 0022 D8. A loop needs its own memory, and the alternative is a chooser re-deriving its history from the mapping documents it wrote. Graded `ASSUMED` because it is additive and reversible: if it turns out no caller reads it, dropping the field costs nothing but a changelog line. Its order is `(entity, field)`, stated in §5.1 rather than left as the current implementation's habit. |
| 9 | `LOCKED` | **Every entry names one edit; an entry that cannot is omitted.** The promise is not "here is a gap" but "here is the edit that would close it", and an entry a caller cannot act on is a worklist item that never clears. Consequence, and the only shape affected today: a canonical whose entity is built by more than one mapping is **not reported**, because its columns are per mapping (RFC 0024 D26) and an entry keyed on `canonical` cannot say which document to edit. Nothing is hidden — the blocked metric is still `unreachable` — and the omission lifts when the report can carry a mapping identity, which is RFC 0024 P2's question rather than this one's. |
| 10 | `LOCKED` | **`UNLINKED` and `UNMAPPED` close by different edits, and termination is measured accordingly.** An `UNLINKED` entry has no field to record a recipe on, so an entity-model edit turns it into `UNMAPPED` — progress without removal. The decreasing measure is therefore `(|O|, count of UNLINKED)` lexicographically and the bound is `2|O|`, not `|O|` (§5.4). Consequence: a chooser that writes only mappings terminates on the `UNMAPPED` subset and correctly leaves `UNLINKED` entries standing, which is the honest answer to half of §10's third question. An earlier draft of §5.4 claimed every accepted choice removes an entry; it does not, and the two-gap distinction D3 draws is what makes the error visible. |

## 12. Phasing

**One phase**, and small: a projection, two dataclass fields, and the tests. The
work is §5.3's join and §6's battery; there is no lowering, no emitter and no
IR change.

**Gated on a chooser that returns partial resolutions** — the same demand gate
RFC 0023 D6 and RFC 0024 D31 apply, and for the same reason. Nothing is broken
while this is unbuilt: a caller can compute the join itself, and the compiler's
refusals already name their fixes. What the gate protects against is designing
the report *around* an agent that does not exist yet.

**But the design lands now, deliberately.** The context that makes this cheap to
specify — the five measured states, the `requires`-is-an-alias-slot fact, the
termination argument — is live today and decays. The prose does not.
