# RFC 0025 — v0.1.0 release readiness

- **Status:** 📝 Draft
- **Scope:** What must be true before bloomery is tagged `0.1.0` — the point at which the
  stability promises in `pages/docs/reference/stability.md` stop describing an intention
  and start binding. Three groups: the **ratchets** RFC 0001 §8 deferred to exactly this
  moment (docs floors, per-package coverage floors, a perf gate), the **navigability** of a
  design corpus that is now 22 deleted documents and 2,142 live citations, and the
  **release act** itself. Explicitly **not** a feature RFC: nothing here adds capability,
  and no unbuilt capability gates the release. Touches `justfile`, `.github/workflows/`,
  `pyproject.toml`, `codecov.yml`, `rfcs/`, `CHANGELOG.md` and docs; no source changes.
- **Related:** RFC 0001 §8 (the deferral this collects —
  `git show f4ae4a0^:rfcs/0001-project-foundations.md`), RFC 0009 (the test tiers the
  floors ratchet), RFC 0014 (the hydration budgets the perf gate would enforce),
  RFC 0018 (the stability surfaces that become binding),
  [`justfile`](../justfile) (`quality`, `coverage`, `test`),
  [`.github/workflows/release.yaml`](../.github/workflows/release.yaml) (trusted publishing,
  already built), [`codecov.yml`](../codecov.yml) (informational by RFC 0001 D4),
  [`pages/docs/reference/stability.md`](../pages/docs/reference/stability.md) ("Before 0.1"),
  [`rfcs/INDEX.md`](INDEX.md) (the retirement policy).
- **Origin:** Collected from RFC 0001 §8's explicit deferral, whose stated trigger —
  "they land at v0.1.0 release, not scaffold time" — has arrived; plus finding F5 of the
  external review of `main` @ `828fd5b` (2026-08-14).

---

## 1. Summary

RFC 0001 §8 deferred three ratchets with a reason — *"ratchets need something to ratchet;
they land at v0.1.0 release, not scaffold time"* — and that condition now holds. This RFC
collects them, adds the one problem the corpus grew into since, and states what the release
act consists of.

**The ratchets.** A docs floor, per-package coverage floors, and a perf gate. Each has
something to ratchet now and did not in August of scaffold time.

**Navigability.** The RFC corpus is empty by design: 0001–0022 all landed or were rejected,
each deleted in the change that finished it. The policy is right and this RFC does not
reopen it. But source, tests and docs carry **2,142 citations of the form `RFC NNNN`**
across 21 distinct documents — 524 to RFC 0016 alone — and every one of them names a file
that is not in the tree. Recovering one requires the full history, which five of the six
CI checkouts do not have. A three-column `RETIRED.md` restores the lookup without weakening
the policy.

**The release.** Publishing machinery already exists — trusted publishing to PyPI, tag-driven
versioning via `hatch-vcs`. What is missing is the decision and the changelog section, not a
pipeline.

Nothing here gates on a feature. The two open capability RFCs (0023, 0024) are independent:
0023's refusals are *better* landed before the tag, 0024 is not release-relevant at all.

## 2. Motivation

**A stability promise that has never been tested is a draft.**
`pages/docs/reference/stability.md` states three surfaces and what each promises, then ends
with "Before 0.1: the API is not stable yet. Anything described here may change." Writing
the promises early was correct — the surface is cheapest to get right while nothing depends
on it — but they remain unexercised. A release is what converts them into obligations, and
the ratchets are what make the obligations enforceable rather than aspirational.

**The deferral's own trigger has fired.** RFC 0001 §8 did not say "someday"; it named the
release. Leaving the ratchets unbuilt past their stated trigger is how a deliberate deferral
quietly becomes an oversight — which is the same failure mode this project's RFC retirement
policy exists to prevent for designs.

**The corpus has a hole the policy did not anticipate.** Retiring RFCs was the right call
and INDEX.md argues it well. What it did not anticipate is scale: 2,142 citations is not a
handful of historical pointers, it is the primary way the codebase explains itself. Reading
`RFC 0016 D84` at [`dialects/postgres.py:68`](../src/bloomery/dialects/postgres.py) requires
knowing the policy, having full history, running `git log --diff-filter=D -- rfcs/`, and
matching a number to a filename the reader does not know. In a shallow clone — what
`actions/checkout` does by default, and what five of the six checkouts in
[`ci.yml`](../.github/workflows/ci.yml) get — it is not recoverable at all.

**Docs can already describe behaviour that does not exist.** Verified while reviewing this
work: `pages/docs/concepts/data-quality.md` carries a warning block stating that Postgres
*"cannot host a quality-carrying entity — nor a dedupe-only one"*, and
`pages/docs/reference/errors.md` repeats it. RFC 0016 D83/D84 closed that limitation.
Measured on `main` @ `828fd5b`: compiling `dirty_corpus` for Postgres emits 70 artifacts —
the same count as DuckDB — with `pg_input_is_valid` rendering in exactly the 66 artifacts
where DuckDB renders `TRY_CAST`. **The external reviewer read that warning and concluded
Postgres was "closer to a demo dialect than a peer".** A stale refusal in the docs cost a
supported dialect its standing with a careful reader, and nothing in the gate could have
caught it. That is the argument for the docs floor being about *claims*, not links.

## 3. Current state

Verified against `main` @ `828fd5b` (2026-08-14).

**Already shipped, and more than RFC 0001 §8 assumed:**

- A **per-package coverage floor already exists** — `just coverage` runs
  `coverage report --include="src/bloomery/guardrails/*" --fail-under=100`
  ([`justfile:76`](../justfile)). RFC 0009 D9's "an untested guardrail branch is an unshipped
  guardrail" is enforced today. So this ratchet is a *generalization*, not a build.
- Global `fail_under = 80` ([`pyproject.toml:214`](../pyproject.toml)), mirrored in
  [`codecov.yml`](../codecov.yml), which is `informational: true` by RFC 0001 D4 so it never
  becomes a second branch-protection authority.
- A **perf tier exists**: the `perf` marker and `tests/bench/test_hydration.py`, excluded
  from `just test`. RFC 0014 measured 10.5 ms median cold against a 50 ms budget. What is
  missing is a *gate* — nothing fails when a number regresses.
- **Publishing is built**: [`release.yaml`](../.github/workflows/release.yaml) has a
  `publish` job on the `pypi` environment using pinned
  `pypa/gh-action-pypi-publish`, with the version dynamic through `hatch-vcs`
  (`version-file = "src/bloomery/_version.py"`). The release is a tag, not a project.
- `just quality -s` runs ten checks and is byte-identical locally and in CI.

**Not shipped:**

- No docs floor of any kind. `just build-docs` reports build issues; nothing checks that a
  documented refusal exists, that a documented error class is exported, or that a cited
  file path resolves.
- No perf gate.
- No coverage floor on any package but `guardrails/`.
- `CHANGELOG.md` has one section, `## [Unreleased]`; no version has been cut.
- `rfcs/` holds only `INDEX.md`. Next free number is 0023 (0026 after this batch).

## 4. Goals / Non-goals

**Goals**

- Land RFC 0001 §8's three ratchets, generalizing the one that already exists.
- Make an `RFC NNNN` citation resolvable from a shallow clone.
- State the release act: what is cut, what is tagged, what the promise becomes.

**Non-goals**

- **Any feature.** Nothing in §5 changes what bloomery compiles.
- **Reopening RFC retirement.** The policy stays; §5.4 adds an index, not the documents.
- **Making codecov blocking.** RFC 0001 D4 decided that deliberately; a second
  branch-protection authority is a worse outcome than an unenforced percentage.
- **A 1.0 stability promise.** 0.1 makes the surfaces *stated and versioned*, not frozen.
- **Deciding the release date.** This says what "ready" means, not when.

## 5. Design

### 5.1 The docs floor — claims, not links

A link checker would not have caught the Postgres warning: every link on that page resolves.
The floor therefore checks **claims that are mechanically checkable against the code**:

1. **Every error class named in `pages/docs/reference/errors.md` exists** and is importable
   from `bloomery.errors`. Cheap, total, and catches a renamed or deleted refusal.
2. **Every documented refusal fires.** The strongest and the one that would have caught
   F4 — a table of (documented refusal → a fixture or inline spec that triggers it), asserted
   in the test suite. A refusal a test cannot provoke is either removed from the code or
   removed from the docs; both are correct outcomes and the gate does not care which.
3. **Every repo-relative path cited in docs resolves.** Mechanical, and it is the check that
   decays fastest without a gate.

This is deliberately not "documentation coverage" in the docstring sense. The failure this
project actually suffered is a *true statement that stopped being true*, and only (2) catches
that class.

### 5.2 Per-package coverage floors

Generalize the existing `guardrails/ = 100% branch` into a declared table, one entry per
package, in `pyproject.toml` so `just coverage` and CI read one source:

```toml
[tool.bloomery.coverage-floors]
"src/bloomery/guardrails/*" = 100   # RFC 0009 D9 — shipped today
"src/bloomery/spec/*"       = 95
"src/bloomery/resolve/*"    = 95
"src/bloomery/emit/*"       = 90
```

**The numbers are `OPEN` (D5).** They must be set from *measured* current coverage, one
notch below it — a floor above the current number fails on day one, and a floor far below it
ratchets nothing. Set them when the table is built, not now.

### 5.3 The perf gate

`tests/bench/test_hydration.py` measures; nothing fails. The gate asserts RFC 0014's stated
budgets — 50 ms cold, 10 ms warm — as a **ceiling with headroom**, not a regression detector
against a stored baseline.

A stored-baseline comparison is the obvious alternative and is rejected: CI runners vary
enough that a percentage-drift check on a millisecond-scale measurement produces flakes,
and a flaky gate is one people learn to re-run. An absolute ceiling with 3–5× headroom over
the measured 10.5 ms catches an order-of-magnitude regression, which is the only kind worth
blocking a merge on, and never fires on a noisy runner.

### 5.4 `rfcs/RETIRED.md`

Three columns, appended by hand in the same change that retires a document:

```markdown
| # | Title | Retired in |
|---|---|---|
| 0016 | Data quality: declarative cleansing, dispositions, quarantine | `f4ae4a0` |
| 0021 | Capability boundaries: identity resolution, dialects, closed questions | `828fd5b` |
```

`git show f4ae4a0^:rfcs/0016-data-quality.md` then prints the document, and the reader needed
only the number they already had.

This **strengthens** the retirement policy rather than weakening it. INDEX.md's argument is
that a retired RFC alongside the code becomes a second, drifting account of current
behaviour. A table of numbers, titles and SHAs is not an account of anything — it cannot
drift, because it describes no behaviour. What it restores is the one thing deletion cost:
the ability to follow a citation.

It does not solve the shallow-clone case by itself — `git show` still needs the object. It
converts a four-step search requiring a full clone into a one-step lookup requiring one, and
that is worth the two lines per retirement. Making the *content* reachable from a shallow
clone would mean keeping the documents, which is the policy this does not reopen.

### 5.5 The release act

1. `CHANGELOG.md` — cut `## [Unreleased]` into `## [0.1.0]`, per the Keep a Changelog format
   already in use.
2. `pages/docs/reference/stability.md` — replace the "Before 0.1" section with the promise in
   force. This is the substantive edit: the same sentences change from description to
   obligation.
3. `pages/docs/get-started/installation.md` — Git install becomes PyPI install.
4. Tag `v0.1.0`. `hatch-vcs` and `release.yaml` do the rest.

Ordering matters for exactly one pair: the changelog section is cut **before** the tag,
because `hatch-vcs` derives the version from the tag and a changelog cut afterwards
describes a release that already shipped.

## 6. Tests

- The docs floor is itself tests (§5.1) — an error-class walk, a documented-refusal table,
  a path-resolution check. They live in the unit tier and run in `just test`.
- The coverage floors are asserted by `just coverage`, which CI already runs.
- The perf gate is a `perf`-marked assertion on a scheduled lane, not on every PR.
- `RETIRED.md` gets a consistency check in `rfc_index.py check`: every number in
  `RETIRED.md` must be absent from `rfcs/`, and every number below the next-free claim must
  appear in exactly one of the two. That makes the table's completeness mechanical rather
  than remembered.

## 7. Docs

- `stability.md` — the "Before 0.1" replacement in §5.5, and it is the one place where
  wording must be exact: "stable" means SemVer over the Python API and per-kind versioning
  over spec YAML, and explicitly **not** byte-stability of emitted artifacts across
  versions. That promise reads backwards and will be misread on the first upgrade diff.
- `installation.md` — PyPI.
- `CONTRIBUTING.md` — the retirement procedure gains its `RETIRED.md` row.
- **Correcting the stale Postgres warning is not part of this RFC.** It is a defect on
  `main` and should be fixed as one, on its own, before or independently of the release.
  It appears here only as the evidence for §5.1.

## 8. Out of scope

- **RFC 0023's refusals.** Independent work, but the *timing* is coupled: refusing a
  construct that previously compiled is a bug fix before 0.1 and a breaking change after.
  Named here so the coupling is not discovered late; not scheduled by this RFC.
- **RFC 0024.** No release relevance — the refusal it lifts is honest and tested.
- **The four unbuilt dialects.** Demand-gated by RFC 0021; a release does not change that.
- **OpenSSF Scorecard badge curation** — RFC 0001 §8 deferred it too, the workflow ships, and
  badge curation gates nothing.
- **devcontainer / Docker tooling** — RFC 0001 §8's third deferral, with no stated trigger.
- **A 1.0 roadmap.** What 1.0 means is a different conversation and does not belong in the
  document that defines 0.1.

## 9. Risks

- **The ratchets become ceremony.** A floor set below current coverage ratchets nothing
  while looking like a gate. Mitigated by D5: set every number from measurement, one notch
  below current.
- **The perf gate flakes and gets ignored.** The named failure mode of every timing check in
  CI. Mitigated by §5.3's absolute ceiling with headroom instead of a drift comparison.
- **`RETIRED.md` is read as a return of the corpus** and someone starts adding summaries to
  the rows. Mitigated by keeping it three columns; a fourth column is where drift would
  start, and the fourth column is the one someone will want.
- **0.1 is read as "stable".** It is a first release with SemVer in force below 1.0, where
  minor versions may still break. The stability page must say which promises bind at 0.1 and
  which wait for 1.0.
- **The release is treated as a milestone rather than a gate.** Tagging with the ratchets
  unbuilt would deliver the version number and none of the enforcement it exists to switch
  on, leaving the promises exactly as unexercised as they are today.

## 10. Unresolved questions

- **Do the docs-floor checks belong in `just quality` or `just test`?** They are tests by
  construction (§5.1 item 2 compiles fixtures), but a reader looking for "is the tree
  healthy" looks at `quality`. Splitting them across both would make `quality` no longer
  byte-identical to CI, which RFC 0001 D4 protects.
- **Is 0.1 the right number**, or is 0.0.x more honest for a first published artifact? 0.1
  is what every existing document says; changing it now would ripple through those pages for
  a gain in honesty that may not exist.
- **Which promises bind at 0.1 and which at 1.0?** §5.5 says the stability page changes; it
  does not say the API is frozen. The split needs stating before the tag, not after.
- **Should `RETIRED.md` be generated rather than hand-appended?** `git log --diff-filter=D`
  can produce it, but a generated file that regenerates differently on a shallow clone is
  worse than a committed one. §5.4 assumes hand-appended, checked mechanically.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | The three RFC 0001 §8 ratchets land before the `v0.1.0` tag, not after. Their stated trigger was the release; deferring them past it converts a deliberate deferral into an oversight, and a promise nothing enforces is what the release exists to stop. |
| 2 | `LOCKED` | The docs floor checks **claims**, not links. A link checker would have passed the stale Postgres warning that cost the dialect its standing with a careful reader; a documented-refusal table would have failed. Consequence: every refusal the docs describe must be reachable by a test, so adding a documented refusal without a test becomes impossible. |
| 3 | `ASSUMED` | The per-package floors generalize the existing `guardrails/ = 100%` rather than replacing it. That floor already encodes RFC 0009 D9 and is not up for renegotiation. |
| 4 | `LOCKED` | The perf gate is an **absolute ceiling with headroom** against RFC 0014's budgets, never a drift comparison against a stored baseline. Runner variance makes percentage drift on millisecond measurements flaky, and a flaky gate is one people learn to re-run. |
| 5 | `OPEN` | The floor percentages in §5.2. Each must be set from measured current coverage, one notch below — above it fails on day one, far below it ratchets nothing. The executor measures and logs the numbers. |
| 6 | `LOCKED` | `rfcs/RETIRED.md` is three columns — number, title, retiring SHA — and **never a summary**. A fourth column would reintroduce the drifting second account the retirement policy exists to prevent; three columns describe no behaviour and so cannot drift. |
| 7 | `ASSUMED` | `RETIRED.md` is hand-appended in the retiring change and checked by `rfc_index.py check`, not generated. A generated file that regenerates differently on a shallow clone is worse than a committed one. |
| 8 | `LOCKED` | The changelog section is cut **before** the tag. `hatch-vcs` derives the version from the tag, so a section cut afterwards describes a release that already shipped. |
| 9 | `ASSUMED` | Codecov stays `informational: true` (RFC 0001 D4). The floors are enforced by `just coverage`, which is the same authority locally and in CI; a second branch-protection authority is a worse outcome than an unenforced percentage. |
| 10 | `OPEN` | Which stability promises bind at 0.1 versus 1.0. §5.5 changes the page; it does not freeze the API. The split must be stated before the tag — after it, the first answer given becomes the promise. |

## 12. Phasing

**P1 — the ratchets (§5.1, §5.2, §5.3) and `RETIRED.md` (§5.4).** Independent of each other
and of everything else; each can land alone. `RETIRED.md` is the cheapest and is worth doing
first regardless of release timing — it pays off every time anyone follows a citation, and
2,142 citations means that is often.

**P2 — the release act (§5.5).** Gated on P1 by D1, and on the answer to D10.

**Coupled but not gated:** RFC 0023's P1 refusals. They are a bug fix before the tag and a
breaking change after, so if they are going to land at all, they land before P2. This RFC
does not schedule them; it names the deadline they inherit.
