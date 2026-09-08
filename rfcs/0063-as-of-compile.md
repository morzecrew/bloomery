# RFC 0063 — As-of compile over spec history

- **Status:** 📝 Draft — depends on [RFC 0062](0062-stable-node-identity.md) P1. Not
  schedulable before it: history keyed to a name is history a rename destroys.
- **Scope:** Compiling a project as its specs stood at a past instant, so that an artifact
  set can be reconstructed for a date rather than only for the working tree. One new flag on
  `compile`, one resolution step in front of the loader, and a rule about where definition
  history comes from. No change to what a given set of specs compiles to.
- **Related:** [`src/bloomery/cli/__init__.py`](../src/bloomery/cli/__init__.py)
  (`compile`, `fingerprint`), [`src/bloomery/resolve/build.py`](../src/bloomery/resolve/build.py),
  RFC 0062 (identity), RFC 0060 (replay on a historical entity — *data* time, contrasted in
  §3), RFC 0044 (`check`), RFC 0003 (determinism — the invariant §9 tests).
- **Origin:** The question a metric owner asks after every unexplained movement: was it the
  data or was it us? The compiler holds half the answer and cannot currently be asked.

---

## 1. Summary

bloomery compiles the working tree. There is no way to ask what it *would have* compiled
last quarter, which means there is no way to establish, from the compiler, whether a number
moved because the warehouse changed or because a definition did.

```bash
bloomery compile --as-of 2026-03-01
```

resolves each spec to the version in force at that instant and compiles that. The output is
an ordinary artifact set with an ordinary fingerprint; what is new is the resolution step in
front of the loader, and the rule about where the version history comes from.

## 2. Motivation

**Two causes, one symptom, and no instrument.** A metric moves. The data may have changed,
the definition may have changed, or both. Warehouses answer the first question well and the
second not at all, because the definition is not in the warehouse. The definition is here.

**The audit question is asked in definition time, not data time.** "Reproduce the March
board pack" is not a request for March's rows under today's definitions — that is a
different number, and usually the wrong one. It is a request for March's rows under March's
definitions, and only the second half is missing.

**`fingerprint` already promises more than it can deliver alone.** A fingerprint identifies
an artifact set exactly. What it cannot do is *produce* the artifact set a past fingerprint
names, so the identity it establishes is unusable for anything but comparison of things you
still have.

**The history exists and the compiler refuses to look at it.** Every project storing specs
in git already has a complete, timestamped, per-file definition history. Nothing needs to be
recorded; something needs to be read.

## 3. Current state

`compile` reads the filesystem as it is. `resolve/build.py` loads specs, resolves references
and constructs the IR; there is no point in that path where a version, an instant or a
revision could be supplied.

**This is not RFC 0060.** That document is about a *data* row entering an entity whose
versions a target framework maintains — `scd: type2`, valid intervals in the warehouse. This
document is about *spec* versions, which no target framework knows exist. The two axes are
independent: one can ask for March's definitions over today's data, or today's definitions
over March's data, and both are meaningful. Conflating them would put a compiler-time
concern into an emitted SELECT, which is exactly the coupling `emit/lower/` exists to
prevent.

The distinction has a standard name — the two axes are transaction time and valid time —
and bloomery today has neither.

## 4. Goals / Non-goals

**Goals**

- `compile --as-of <instant>` produces the artifact set the project would have produced at
  that instant.
- The result is byte-identical to what an actual compile at that instant produced, given the
  same compiler version.
- The history source is explicit, and a project without one gets a clear refusal rather than
  a silent fallback to the working tree.
- `check` and `plan` accept the same flag, so a CI job can compare two instants.

**Non-goals**

- **Time-travelling the warehouse.** bloomery emits text; what data that text reads is the
  caller's business and is not addressed here.
- **A bloomery-owned version store.** §5 argues the history is already in the repository.
- **Reconstructing across compiler versions.** An artifact set from a compiler two minor
  versions back is not this document's promise; see D3.
- **Branching or what-if analysis.** One instant, one linear history, one output.
- **Moving the I/O boundary.** Compilation stays a pure function over spec strings; the
  resolver that produces those strings is the caller's side of the boundary, and D6 is
  where that is stated rather than assumed.

## 5. Design

### 5.1 Where history comes from

**Candidate A — the repository is the store of record.** `--as-of` resolves to a revision by
commit timestamp, and specs are read from that revision.

*For:* nothing is recorded that is not already recorded; the history is complete from the
project's first commit; there is no second source of truth to drift; and the property every
team already relies on — "the specs are in git" — becomes load-bearing rather than
incidental.

*Against:* it makes the CLI read a VCS, which is a dependency of a different kind from
anything in the tree today. Commit time is author-controlled and need not be monotonic. A
project whose specs are generated rather than committed has no history at all.

**Candidate B — declared validity on the spec.** Each spec carries `effective_from:`, and
older versions stay in the file as a list.

*For:* no VCS dependency; history is a spec fact like every other spec fact; a generated
project can produce it.

*Against:* the file grows without bound, every reader of a spec now reads a version list to
find the current definition, and the field is a second place to be wrong — a definition that
changed on the 3rd and says the 5th produces a confidently incorrect reconstruction, which
is worse than a refusal.

**Candidate C — refuse, and document the git recipe.** `git checkout` a revision, compile,
compare fingerprints.

*For:* zero code, and it works today.

*Against:* it works today and nobody does it, because the ergonomics are wrong at exactly
the moment it is needed — during an incident, against a dirty tree.

**Current lean: A.** Its objection is about dependency posture, which a decision row can
settle; B's objection is about correctness, which one cannot. A resolver port keeps the VCS
behind an interface, so B remains reachable as a second adapter for projects that need it.

### 5.2 The resolution step

A `HistoryResolver` port sits in front of the loader: given an instant, return the spec set
in force. The git adapter reads a revision. The working-tree adapter — the default, and what
runs when `--as-of` is absent — returns the filesystem. The compiler downstream of that port
is unchanged and does not know which adapter ran.

**The port is the determinism boundary, and it is the existing one.** Compilation already
takes spec strings and returns artifacts with no filesystem, network or environment access
(RFC 0003); reading files is already the CLI's job, on the caller's side of that line. A
history resolver is the same job with a revision argument, so the pure function stays pure
and the process gains a subprocess it did not have. D6 records that the second half of that
sentence is a real change and not a technicality.

### 5.3 What a refusal looks like

No `--as-of` support configured, or an instant before the project's first revision: refuse,
naming the earliest instant that *can* be resolved. Silently compiling the working tree when
asked for a past date would produce a confident, wrong artifact set — the failure mode this
whole document exists to remove.

## 6. Tests

- **Reconstruction is exact.** Compile at a revision, record the fingerprint; change specs;
  `compile --as-of <that revision's timestamp>`; fingerprints match.
- **The default path is untouched.** Without `--as-of`, the working-tree adapter runs and
  every existing fixture passes unchanged, byte for byte.
- **An unreachable instant is refused, not approximated.** A date before the first revision
  produces a refusal naming the earliest resolvable instant.
- **A dirty tree does not leak.** `--as-of` on a repository with uncommitted spec changes
  compiles the revision, not the tree, and says so.
- **The two axes stay separate.** A project with `scd: type2` entities compiles under
  `--as-of` without any change to the emitted SCD2 artifacts — spec time does not reach data
  time.
- **The pure half stays pure.** The determinism suite runs against the compiler entry point
  with strings supplied by the test, unchanged: no adapter, no subprocess, no clock.

## 7. Docs

`pages/docs/guides/` gains one task-shaped page: reproducing a past artifact set. Written
against the incident, since that is when it is read.

## 8. Out of scope

- RFC 0064's attribution — this document produces two artifact sets, and says nothing about
  why they differ.
- Range queries. One instant only; "every version between March and June" is a different
  interface with a different cost.
- Retention. How long a project keeps its history is a property of its repository.

## 9. Risks

- **Commit time is not definition time.** A definition change committed on the 5th and
  effective from the 1st reconstructs wrongly under Candidate A, and nothing detects it. The
  honest framing is that `--as-of` answers "what did the repository say" and not "what was
  true", and the docs must say which of the two they are offering.
- **A subprocess in a codebase that has none on this path is a posture change.** RFC 0003's
  invariant is about the compiler, and §5.2 keeps it — but "bloomery shells out to git" is a
  sentence this project has not written before, and a reader who knows the determinism rule
  will read the feature as breaking it unless the boundary is stated where they will look.
- **Squash-merge flattens history.** A project squashing every branch has commit granularity
  of a merge, not of an edit. The feature still works and is coarser than a reader expects,
  and the docs should say so rather than let it be discovered. This repository squash-merges,
  so it is its own worked example.

## 10. Unresolved questions

- Whether `--as-of` accepts a revision as well as an instant. A revision is unambiguous and
  an instant is what people have.
- What a fingerprint from a different compiler version should do under `--as-of`: refuse,
  warn, or produce and label. All three are defensible.
- Whether the git adapter shells out or uses a library. A subprocess inherits the ambient
  git configuration, which is environment the compiler's own rules forbid it to read.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | Spec time and data time are separate axes. `--as-of` resolves specs and reaches no emitted SELECT; RFC 0060's problem is not this one. |
| 2 | `LOCKED` | An unresolvable instant is refused. Falling back to the working tree produces a confidently wrong artifact set, which is the defect this document removes. |
| 3 | `LOCKED` | Reconstruction is promised within one compiler version. Across versions the specs may resolve and the emitted bytes still differ, and pretending otherwise makes the fingerprint a lie. |
| 4 | `OPEN` | Candidate A, B or C (§5.1). The lean is A behind a port, with B reachable as a second adapter. |
| 5 | `ASSUMED` | The working-tree adapter is the default and is what runs when the flag is absent. Anything else changes behaviour for projects that never asked for history. |
| 6 | `LOCKED` | The resolver sits on the caller's side of RFC 0003's boundary and the compiler entry point gains no I/O. A history feature that moved that line would trade the determinism guarantee for a convenience, and every other document in this corpus is written on top of it. |

## 12. Phasing

**P1** — the `HistoryResolver` port and the working-tree adapter, which is a refactor with
no user-visible change and no new dependency. This is where the byte-exactness test lands.

**P2** — the git adapter, `--as-of` on `compile`, and the refusal.

**P3** — the same flag on `check` and `plan`, which is what makes CI comparison possible.

P1 is worth landing on its own: it puts the seam in without committing to §5.1.
