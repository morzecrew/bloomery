# RFC 0068 — Caller-assembled spec history

- **Status:** 📝 Draft — supersedes RFC 0063 (as-of compile; rejected and retired at `074a571`), in
  the change that lands this. What 0063 wanted is already reachable; what it proposed to
  build would have cost the property the rest of this corpus is written on top of.
- **Scope:** A decision and its evidence: bloomery does not read spec history, because the
  caller already hands it spec text and the compiler has no notion of time. Plus the two
  small things that turn "happens to work" into "supported" — a test pinning the
  strings-in entry point, and a how-to written against the incident. No new flag, no
  adapter, no dependency.
- **Related:** [`src/bloomery/spec/project.py`](../src/bloomery/spec/project.py)
  (`load_project`), [`src/bloomery/cli/io.py`](../src/bloomery/cli/io.py) (the one door to a
  disk), [`src/bloomery/cli/__init__.py`](../src/bloomery/cli/__init__.py) (`_load`, and the
  `--steps` precedent at its `resolve` body), RFC 0003 (determinism — the property this
  protects), RFC 0017 (steps — where this question was answered the first time),
  RFC 0064 (supersession — the document that cited 0063 and does not need it),
  RFC 0020 (the CLI's I/O boundary).
- **Origin:** Reviewing RFC 0063 before executing its P1 and finding that P1's capability
  delta was zero, that the seam it added already existed, and that this repository had
  already decided the same question the other way for `StepRegistry`.

---

## 1. Summary

RFC 0063 proposed `bloomery compile --as-of <instant>`: a history resolver in front of the
loader, a git adapter behind it, and a refusal when an instant cannot be resolved.

It is not needed, because **as-of compile is not a compiler feature**. It is *fetch the
right spec text*, then *compile* — and the second half already accepts exactly that:

```python
rows = {name: yaml for name, yaml in store.fetch(as_of="2026-03-01")}
ir = build_project_ir(load_project(rows), catalog)
```

`load_project` takes `Mapping[str, str]`. Where those strings came from — a git revision, a
Postgres table, an S3 prefix, a tarball — is the caller's business, and bloomery is
better for not knowing.

This document records that decision, and ships the two things that make it a contract
rather than an accident.

## 2. Motivation

**The capability already exists; only its status was unclear.** A reader looking for
"reproduce March" finds no flag and concludes bloomery cannot do it. What is missing is a
sentence in the docs and a test holding the entry point still — not a subsystem.

**The proposed subsystem costs the corpus's central property.** RFC 0003's "compilation does
no I/O" is not a style rule; it is the premise every other document here is written on.
RFC 0063 kept the letter of it — the resolver sits on the CLI's side — and paid in a VCS
dependency, the first subprocess under `src/bloomery/`, and three risks it lists itself.
Its own §9 concedes that *"bloomery shells out to git" is a sentence this project has not
written before*. A design needing a `LOCKED` row to promise it is not breaking the thing it
appears to break is a design worth re-reading.

**This question already has an answer in this tree.** `StepRegistry` is a caller-assembled
compile input, and the CLI deliberately offers no `--steps` for it (RFC 0017 §5.3). Spec
history is the same shape: an input the caller assembles from a store bloomery should not
know about. `--as-of` would settle that question the opposite way, in the same file.

**The one real benefit is ergonomic, and it is smaller than it looks.** RFC 0063 §5.1's
Candidate C — "document the git recipe" — is dismissed with "it works today and nobody does
it, because the ergonomics are wrong during an incident". That is a fair observation about
people, and the fix for it is a page written against the incident, which is what §7 of that
document already asked for.

## 3. Current state

Verified against the tree, and the first two are what decide this.

- **`load_project(sources: Mapping[str, str]) -> Project`** is public, exported from the
  package root, and pure. Compiling a spec set that never touched this filesystem works
  today: `load_project` → `build_project_ir` → `compile_project`, measured on a fixture
  supplied as strings.
- **`plan(old: ProjectIR | None, new: ProjectIR) -> Plan`** takes two IRs. Comparing two
  instants — RFC 0063's P3, and the thing that makes CI comparison possible — is already
  expressible by building both sides from strings.
- **`cli/io.py` is the only module in the package that reads or writes files** (RFC 0020 D5,
  D12), enforced by a lint rule that bans `os` and `pathlib` everywhere else with one
  `noqa` per exempted line. Its docstring states the invariant this document relies on:
  *"Everything here returns `str`. The library never sees a path."*
- **`_load(directory, catalog_path)` is one function making one call** to
  `read_spec_directory`, and it is the only call in `src/`. RFC 0063 P1's "seam in front of
  the loader" is a name for something already there.
- **`subprocess` is absent from the banned-import list**, and nothing under
  `src/bloomery/` uses one. The guard that mechanically enforces RFC 0003 would therefore
  not have noticed the adapter RFC 0063 P2 proposed (§8).
- **RFC 0064 cites RFC 0063 throughout** and does not depend on it: §5.2 needs "two compiles
  at two instants", which is two IRs however obtained, and its own §3 notes that `plan()`
  already classifies changes between two spec sets.

## 4. Goals / Non-goals

**Goals**

- Record that spec history is caller-assembled, with the evidence, so the question is not
  re-opened from scratch.
- Make the strings-in entry point a pinned contract rather than an implementation detail a
  refactor may quietly narrow.
- Give the incident reader the page RFC 0063 §7 asked for, without the flag.

**Non-goals**

- **A history resolver port.** One implementation and no second caller; the extension point
  is `load_project`'s signature and has been since RFC 0002.
- **`--as-of` on any command.** §5.2 says why the CLI is the wrong place for it.
- **Telling callers how to store history.** Git, Postgres, object storage and a directory of
  tarballs are all correct answers, and choosing one for them is how a library acquires a
  dependency its users did not ask for.
- **Attribution between two compiles.** RFC 0064, unchanged.

## 5. Design

### 5.1 The decision

bloomery compiles the spec text it is handed. It does not resolve, fetch, or version that
text, and it has no notion of when a spec was written.

That is not a limitation to be lifted later. It is what makes every artifact set
reproducible from its inputs alone, which is the promise `fingerprint` rests on.

### 5.2 Why the CLI is the wrong place for the convenience

A flag on `compile` looks like ergonomics and is actually a coupling. `--as-of` obliges
bloomery to know what a history *is*: which store holds it, how an instant maps to a
version, what to do when the mapping is ambiguous. Every one of those is a question with a
different right answer per project, and none of them is a question about compiling.

The comparison that settles it is `--steps`. A `StepRegistry` is assembled by the caller
from wherever step manifests live, and the CLI offers no flag to assemble one, for exactly
this reason. A reader who accepts that and then meets `--as-of` learns that the rule holds
except where it was inconvenient.

### 5.3 What ships instead

- **A test** that compiles a fixture supplied as a `dict[str, str]` with no filesystem
  access in the path, asserting the artifacts are byte-identical to the same project
  compiled from disk. It pins the entry point's shape: a refactor narrowing `load_project`
  to something path-shaped fails here rather than in a user's pipeline.
- **A how-to** — *reproduce a past artifact set* — written against the incident. Fetch the
  spec text as it stood, compile, compare fingerprints. It shows a git recipe and a
  query-shaped one, because those are the two stores readers actually have, and it says
  plainly that bloomery neither knows nor cares which.

### Alternatives considered

**Build RFC 0063 P1 anyway, as a seam for later.** A Protocol with one implementation, in
front of a function with one caller, for a flag that does not exist. If P2 never lands it is
pure cost; if P2 lands, the seam it needs is one parameter away either way.

**Keep 0063 open but unscheduled.** Rejected because an unscheduled document still shapes
the ones that cite it: RFC 0064 was written believing this was coming, and RFC 0062's status
line justifies a decision by what "RFC 0063 reads". Leaving a design in the corpus that will
not be built is how the corpus stops being trustworthy.

**Ship the how-to with no RFC.** The page would answer "how", and the question that keeps
coming back is "why not a flag". That belongs in a decision table, once.

## 6. Tests

- **The strings-in path compiles.** A project assembled as a `dict[str, str]` produces the
  same artifacts as the same project read from disk, byte for byte.
- **No filesystem in that path.** The compile half runs with `pathlib` and `os` unavailable
  to it, which is the property the lint rule asserts statically and this asserts at runtime.
- **Two spec sets still diff.** `plan()` over two IRs built from two string sets classifies
  changes — the P3 capability, shown to exist.
- **The docs page's recipe is the one that runs.** Its code block is checked against the
  library's actual signatures, so the page cannot drift from the API the way a documented
  refusal drifted from its template in T-0041.

## 7. Docs

`pages/docs/how-to/reproduce-a-past-artifact-set.md`. Task-shaped, written against the
incident. It must say which question is being answered — "what did your store say the
definitions were", not "what was true on that date" — because RFC 0063 §9's first risk is a
property of any history, not of git.

## 8. Out of scope

- **Banning `subprocess` under `src/bloomery/`.** §3 records that the guard has this hole;
  closing it is a change to the lint configuration with its own blast radius, and it is not
  needed to decide this question. Worth doing, separately.
- **RFC 0064.** It cites 0063 and needs two IRs, which it can have.
- **Whether `fingerprint` should record the compiler version.** RFC 0063 D3 and §10 raise
  it; it is a real question about `fingerprint` and survives this rejection untouched.

## 9. Risks

- **An incident reader still has to do two steps.** Fetch, then compile. The page is the
  mitigation and it is a weaker mitigation than a flag would be; this document accepts that
  trade deliberately rather than pretending the gap is zero.
- **"No I/O" is a promise about the library that a reader may hear as a promise about the
  CLI.** The CLI reads files — that is its job. The line is `cli/io.py`, and the how-to
  should show the boundary rather than assert it.
- **A rejected RFC's number keeps being cited.** RFC 0064 cites 0063 nine times. That is
  what `RETIRED.md` is for, and those citations stay readable; but a reader of 0064 will
  meet a premise that no longer holds, and only the retirement row tells them so.

## 10. Unresolved questions

- Whether the how-to should ship a runnable example under `examples/`, which would make the
  recipe executable rather than quoted, at the cost of a directory that needs a git history
  to demonstrate anything.
- Whether `plan()`'s two-IR signature deserves a documented "compare two instants" framing
  of its own, or whether that is the how-to's job.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | bloomery does not read spec history. The caller hands it spec text; where that text came from is outside the library and outside the CLI. Reversing this re-opens RFC 0003's boundary, which every document in this corpus is written on top of. |
| 2 | `LOCKED` | No `--as-of` on any command. The flag would oblige bloomery to know what a history is — which store, which instant-to-version mapping, what to do when it is ambiguous — and none of those is a question about compiling. `--steps` is the same question already answered this way (RFC 0017 §5.3). |
| 3 | `LOCKED` | RFC 0063 is rejected, not deferred. An unscheduled design still shapes the documents that cite it, and two already cite this one. |
| 4 | `ASSUMED` | The strings-in entry point gets a test that would fail if it were narrowed. It is a public signature with no guard today, and the cost of pinning it is one test. |
| 5 | `ASSUMED` | The how-to shows both a git recipe and a query-shaped one. Showing only git would re-introduce, in prose, the assumption the rejection removes. |
| 6 | `OPEN` | Whether the how-to's recipe ships as a runnable example (§10). |

## 12. Phasing

One change: the rejection, the test, and the page. There is no half of this worth landing
alone — the test without the page leaves the capability undiscoverable, and the page
without the rejection leaves two documents in the corpus proposing to build it anyway.
