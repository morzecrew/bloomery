# RFC 0019 — Lowering decomposition

- **Status:** 📝 Draft
- **Scope:** Splitting `emit/lowering.py` (2,274 LOC) by *pipeline stage* rather than by
  target, into an `emit/lower/` package; the same treatment for `plan/diff.py` (1,468 LOC)
  where it decomposes cleanly. A refactor: no behaviour change, no emitted-artifact
  change, every golden file byte-identical before and after. Adds two structural CI
  guards — a purity check and an import-layering check — that make the decomposition
  hold.
- **Related:** RFC 0008 (the three-port design this
  preserves), RFC 0007 (`plan/diff.py`), RFC 0016 / RFC 0017 (the two RFCs whose lowering
  shares this file), [RFC 0009](0009-testing-strategy.md) (the golden matrix that proves
  the refactor inert),
  [RFC 0018](0018-public-surface-and-stability.md) decision 6 (deep imports carry no
  promise — which is what makes moving these paths free).
- **Adoption audit:** §5.2 and §5.4 overstated what is missing; both corrected, and §10's
  third question is answered.

---

## 1. Summary

`emit/lowering.py` is the junction where every spec kind meets every emitter: 9.4% of the
library in one file. It is target-independent by design — the ports split on *assembly*,
not on lowering — so it is the natural home for accidental coupling, and the natural place
for a change made for one target to quietly constrain another.

This RFC splits it into `emit/lower/` by pipeline stage (`select`, `quality`, `steps`,
`audits`, `marts`), with a strict import layering enforced in CI. Behaviour is unchanged
and the golden matrix proves it: every emitted byte identical before and after.

Two guards land with it — a static purity check and an import-linter contract for the new
layering. Both extend enforcement that already exists in weaker form; §5.2 and §5.4 say
exactly how much is new.

## 2. Motivation

Size alone is not the argument — a 2,274-line file that decomposes into five cohesive
stages is a filing problem, not a design problem. The argument is what the file *is*:

**It is the only place where all four emitters, all five spec kinds, and both run-time
subsystems (quality, steps) are simultaneously in scope.** Everything else in the codebase
sees a slice. RFC 0008's port design keeps targets apart and RFC 0016/0017 keep their
domains apart, and then all of it converges here.

Two symptoms are worth naming as the trigger this RFC pre-empts, because both are cheap to
check and expensive to discover late:

- A change made for one target requires reading another target's code to be sure it is
  safe.
- The module imports from more than three sibling packages.

The second is already true. And the amendment histories point the same way: RFC 0017's
D25/D32 (an escaping boundary fixed in one place and missed in another *within the same
file*) and D53/D56 (a literal guard re-cut twice) are exactly the defect shape that a
file this wide produces — a rule applied at one site and not at its sibling, with nothing
structural to say the two sites were the same rule.

Now is when this is free. Post-RFC 0018 the module paths are declared non-public
(decision 6), the golden matrix makes a refactor provably inert, and no consumer is bound
to the layout.

## 3. Current state

Verified against `main` @ `3da72c5` (2026-08-12):

| Module | LOC | % of `src` |
|---|---|---|
| `emit/lowering.py` | 2,274 | 9.4% |
| `plan/diff.py` | 1,468 | 6.0% |
| `guardrails/quality.py` | 1,062 | 4.4% |
| `spec/quality.py` | 920 | 3.8% |
| `resolve/build.py` | 878 | 3.6% |
| `ir/nodes.py` | 805 | 3.3% |
| `emit/sqlmesh/__init__.py` | 798 | 3.3% |

Source total: 24,338 LOC. Tests: 30,845 (1.27:1).

Quality spans `spec/quality.py` + `guardrails/quality.py` + `quality/*` — 3.4k LOC — 14%
of the library for one RFC. Steps span `spec/steps.py` + `resolve/steps.py` +
`emit/steps.py` + `steps/*` — 2.5k.

Both `emit/lowering.py` and `plan/diff.py` are single modules, not packages. Neither is
in any `__all__`; both are reached only by intra-package import.

**Enforcement that already exists**, and which §5.2/§5.4 extend rather than introduce:

- `pyproject.toml` carries an import-linter **`layers`** contract over the whole pipeline
  (`planner → compile|runtime → emit → naming → plan → resolve → guardrails → quality →
  marts → ir → dialects → transforms → steps → typing → spec → errors`) plus a
  `forbidden` contract, "Emitters never import the spec layer". Both run in `just quality`.
- `.pre-commit-config.yaml` carries a **static** `pygrep` hook banning
  `datetime.now|uuid4|time.time(|os.environ` under `src/bloomery/`.
- `just quality` runs `pre-commit run gitleaks` only — so the pygrep hook above is **not**
  a CI gate. It fires on a local commit and nowhere else.

## 4. Goals / Non-goals

**Goals**

- No module in `src/` where all targets, all spec kinds and both run-time subsystems are
  simultaneously in scope.
- A stated import layering *within* `emit/`, enforced mechanically, that makes "which
  stage may see which" answerable without reading.
- Byte-identical emission across the refactor, proven rather than asserted.
- The existing static purity guard promoted to a CI gate and widened.

**Non-goals**

- Any behaviour change, any emitted-artifact change, any public API change.
- Splitting `guardrails/quality.py` or `spec/quality.py`. They are large but *cohesive* —
  one domain, one RFC, one reader. Size is not the trigger; convergence is.
- A line-count budget or a lint rule on file length. The trigger is structural (§2's two
  symptoms), and a numeric cap would force bad splits on cohesive modules.
- Reducing quality's 14% share. That share reflects the domain's real intricacy
  (RFC 0016's amendment history is the evidence), not accidental bloat.
- Restating the pipeline-wide layers contract, which already exists (§3).

## 5. Design

### 5.1 Split by stage, not by target

The decomposition axis matters more than the decomposition. Splitting by target
(`lower/sqlmesh.py`, `lower/dbt.py`, …) would **invert RFC 0008's port design**: targets
are supposed to differ in assembly and share lowering, and a per-target lowering file
invites exactly the divergence the three-way equivalence tier exists to catch.

Splitting by stage preserves it — one lowering, consumed by every target's assembly:

```text
emit/
  lower/
    __init__.py      the stage pipeline; the only module emitters import
    select.py        extract → transform chain → projection
    quality.py       rules, dispositions, routing, flags, dedupe   (RFC 0016)
    steps.py         Tier 1 splice, Tier 2/3 wiring, contract call (RFC 0017)
    marts.py         flattening, role expansion                    (RFC 0010)
    audits.py        assert, coverage, reconcile, conservation
  base.py            unchanged — TargetEmitter, TargetCapabilities, Feature
  sqlmesh/ dbt/ cube/ metricflow/    unchanged — assembly only
```

Boundaries are drawn where the pipeline order (RFC 0016 §5.1: extract → transform →
dedupe → field rules → row rules → route) already draws them. Stages that turn out to
share more than a shared-helpers module can carry are a finding to record, not a boundary
to erase.

### 5.2 Import layering — three new contracts, not four

The pipeline-wide layering is **already enforced** (§3): the `layers` contract in
`pyproject.toml` covers `spec → ir → resolve → emit` and the rest, and it runs in
`just quality`. The draft of this RFC listed it as a fourth contract "now written down";
it is written down, and re-adding it would be a duplicate.

What that contract does *not* constrain is direction *within* `bloomery.emit`, because the
whole package is one layer. So three genuinely new `forbidden` contracts:

1. **No `emit/lower/*` module imports any `emit/<target>/` module.** Lowering is
   target-independent; this is the contract that keeps it so.
2. **No `emit/lower/*` module imports a sibling stage** except through
   `emit/lower/__init__.py` or a shared `emit/lower/_shared.py`. Stages compose in the
   pipeline, not laterally.
3. **No `emit/<target>/` module imports another target.**

Contract 1 is the one that would have caught the class of defect §2 cites. Contract 2 is
the one that keeps the split from decaying back into a monolith spread over five files.

All three hold on today's tree — verified by grep before writing them (§10.3), so they
land green and stay green rather than requiring a pre-refactor cleanup.

### 5.3 `plan/diff.py`

Same treatment where it decomposes cleanly:

```text
plan/
  diff/
    __init__.py      the diff entry point
    entities.py      field-level: add, widen, rename, narrow, drop
    marts.py         grain, flatten set, measure set
    quality.py       rule, disposition, dedupe changes → RESTATING + replay_scope
    steps.py         ref/version/runtime_lock changes → RESTATING
    classify.py      the ChangeClass decision table; contract-violation checks
    scope.py         backfill_scope, replay_scope, downstream impact from IR edges
  model.py           unchanged
```

`classify.py` and `scope.py` are the parts worth isolating: the ChangeClass decision table
is the single most consequential piece of logic in the library (it decides what gets
backfilled), and it is currently interleaved with the structural walking that feeds it.

If `plan/diff.py` turns out not to decompose this cleanly on contact, **do the
`emit/lowering.py` half and record the finding** rather than forcing it. Two clean splits
are worth more than one clean and one contrived.

### 5.4 The purity guard becomes a CI gate, and widens

A static guard already exists and is narrower than this RFC's draft assumed: a pre-commit
`pygrep` hook bans `datetime.now|uuid4|time.time(|os.environ` under `src/bloomery/`. It is
not a replacement for the behavioural tests and it is not nothing.

Two things are genuinely wrong with it, and both are the change:

**It is not a CI gate.** `just quality` runs `pre-commit run gitleaks` and no other hook,
so `git commit --no-verify` — or any path that does not run pre-commit locally — bypasses
it entirely. A guard that CI does not run is a convention.

**Its vocabulary is short.** It catches four spellings; it does not catch the imports that
would make I/O possible in the first place.

```text
banned imports:  os, pathlib, requests, httpx, boto3, sqlalchemy, duckdb, tempfile, socket
banned calls:    datetime.now, datetime.today, time.time, time.monotonic,
                 random.*, uuid.uuid1, uuid.uuid4, os.environ
```

Verified today: none of those imports appears anywhere under `src/bloomery/`, so the
widened guard lands green.

Two deliberate carve-outs, each with a named allowlist entry:

- `steps/contract.py` — runs at *run time* inside a generated wrapper, not at compile
  time. It still imports nothing beyond `bloomery.errors` (RFC 0017), so it passes as
  written; the allowlist entry exists so a future addition there is a decision.
- Any module that legitimately needs `os.environ` — there are none today, and the guard
  is what keeps that true.

Implemented as an AST check in the existing quality gate, replacing the pygrep hook rather
than sitting beside it — two guards over one invariant drift. It remains no substitute for
the behavioural tests: a step could still read a clock through an import bloomery does not
name. It moves the *common* failure from a test run to a review comment, with a line
number, on every PR rather than on every local commit.

### 5.5 The refactor is proven inert

Non-negotiable and mechanical:

1. Snapshot every golden artifact on `main`.
2. Refactor.
3. Assert byte-identical goldens across every fixture × target × dialect cell.
4. Assert `project_fingerprint` unchanged for every fixture.

A golden diff during this wave means the refactor changed behaviour and must be fixed —
it is never a regeneration. That inversion of the usual golden-file workflow is what makes
a 3,700-line move safe, and it should be stated in the PR description so no reviewer
regenerates on autopilot.

## 6. Tests

Per RFC 0009 tiers. This wave adds almost no test *content* — its correctness argument is
that the existing suite is unchanged and still passes.

| Tier | Test |
|---|---|
| Golden | Every cell byte-identical to the pre-refactor snapshot. Blocking; regeneration forbidden. |
| Unit | `project_fingerprint` unchanged per fixture. |
| Lint | The three new import-linter contracts (§5.2), alongside the two that already exist. |
| Lint | The purity AST check (§5.4), with its allowlist, running in `just quality`. |
| Unit | A deliberately-planted violation of each new import contract is caught — the guard is tested, not just present. |
| Unit | The purity check catches a planted `import os` and a planted `datetime.now()`, and the pygrep hook it replaces is gone rather than duplicated. |
| All existing | Unchanged. No test file is edited except for module paths in imports. |

The planted-violation test matters: an import-linter contract that has never failed is
indistinguishable from one that is misconfigured.

## 7. Docs

- `pages/docs/concepts/compile-pipeline.md` — the stage decomposition, which now mirrors
  the prose the page already carries.
- A `CONTRIBUTING`-adjacent note stating the layering contracts and where to add a new
  stage.
- No user-facing change: nothing here is public under RFC 0018 decision 6.

## 8. Out of scope

- `guardrails/quality.py`, `spec/quality.py`, `resolve/build.py`, `ir/nodes.py` — large,
  cohesive, single-domain. Revisit only if §2's two symptoms appear.
- Any file-length lint rule.
- Reducing the quality subsystem's footprint.
- Splitting `emit/<target>/` modules; SQLMesh at 798 LOC is a single cohesive assembler.
- Restating the pipeline-wide `layers` contract, which already exists and passes.

## 9. Risks

| Risk | Mitigation |
|---|---|
| A large refactor with no behaviour change is a large diff nobody reviews carefully | §5.5's byte-identical gate is the review: the goldens assert what a reviewer cannot. Land it as one PR per stage, each independently green. |
| Stages turn out to share more than expected, and `_shared.py` becomes the new monolith | Contract 2 forbids lateral imports, so shared code must be *named* shared. If `_shared.py` exceeds ~300 LOC the split was drawn wrong — record it and redraw. |
| `plan/diff.py` does not decompose cleanly | §5.3: do the lowering half, record the finding, leave `diff.py` whole. Explicitly permitted. |
| The purity guard produces false positives on test helpers | It runs over `src/` only. `tests/` legitimately touches the filesystem and the clock. |
| Replacing the pygrep hook loses coverage between the two implementations | The AST check is a superset of the hook's four spellings, and §6 plants one of each. The hook is removed in the same change that adds the check, never before. |

## 10. Unresolved questions

1. Does `emit/lower/audits.py` belong as a stage, or does each audit kind belong with its
   originating stage (assert → select, coverage → quality, consistency → steps)? Leaning
   toward a stage: audits share an emission shape and are consumed by target assembly
   uniformly, which is the cohesion test. Settle on contact.
2. Should the `Feature` capability check live in `emit/lower/__init__.py` or stay in each
   emitter? Today it is per-emitter, which duplicates the check but keeps refusal messages
   target-specific. Leaning: leave it — a shared check would produce a generic message
   where a specific one is what a user needs.
3. ~~Is there a pre-existing violation of contract 1 (lowering importing a target)?~~
   **Answered at adoption: no.** `emit/lowering.py` imports no target module, no target
   imports another, and the three pipeline-layering properties the draft worried about
   (`spec ↛ ir`, `ir ↛ resolve`, `resolve ↛ emit`) all hold — the last three because the
   existing `layers` contract has been enforcing them all along. The contracts land green.

## 11. Decisions

| # | Decision |
| --- | --- |
| 1 | **Split by pipeline stage, never by target.** A per-target lowering file would invert RFC 0008's port design — targets differ in *assembly* and share *lowering* — and would invite precisely the divergence the three-way equivalence tier exists to catch. `emit/lowering.py` becomes `emit/lower/{select,quality,steps,marts,audits}.py` with `__init__.py` as the pipeline and the only module emitters import. |
| 2 | **Size is not the trigger; convergence is.** `emit/lowering.py` is split because it is the one module where every target, every spec kind and both run-time subsystems are simultaneously in scope. `guardrails/quality.py` (1,062) and `spec/quality.py` (920) are not split: large but cohesive, one domain, one reader. No file-length rule is adopted — it would force bad splits on cohesive modules. |
| 3 | **Two structural symptoms are the stated trigger** for splitting any future module: a change for one target requiring another target's code to be read, or imports from more than three sibling packages. Written down so the next call is not a judgement made from scratch. |
| 4 | **Three new import-linter contracts** (§5.2), each proven by a planted violation. The draft listed four; the fourth — the pipeline-wide layering — **already exists** in `pyproject.toml` as a `layers` contract and runs in `just quality`, so adding it would duplicate an enforced rule. What that contract cannot see is direction *inside* `bloomery.emit`, which is one layer to it; the three new contracts cover exactly that. All three hold today, so they land green. |
| 5 | **The refactor is proven inert by byte-identical goldens**, and during this wave **a golden diff is a bug, never a regeneration** — stated in the PR description. That inversion of the normal workflow is what makes moving 3,700 lines safe, and stating it prevents a reviewer regenerating on autopilot. `project_fingerprint` is asserted unchanged alongside. |
| 6 | **The existing static purity hook is promoted to a CI gate and widened**, not invented. A pre-commit `pygrep` already bans four spellings under `src/bloomery/`; the draft's claim that the invariants are "enforced behaviourally today" understated it. Two things are actually wrong: `just quality` runs only the gitleaks hook, so the guard is bypassed by `--no-verify` and by CI itself, and its vocabulary omits the *imports* that make I/O possible. The AST check replaces the hook rather than sitting beside it — two guards over one invariant drift — with `steps/contract.py` allowlisted as run-time rather than compile-time. |
| 7 | **`plan/diff.py` is split on the same axis if it decomposes cleanly, and left whole if it does not** (§5.3), with the finding recorded either way. Two clean splits are worth more than one clean and one contrived. `classify.py` and `scope.py` are the parts worth isolating regardless: the ChangeClass table decides what gets backfilled and is currently interleaved with the walking that feeds it. |
| 8 | **No behaviour, artifact, or public-API change.** This wave is inert by construction; anything it changes is a defect. |

## 12. Phasing

Design locked by this RFC; implementation lands as wave **M16**, after RFC 0018's M15 —
not because it depends on the public surface, but because RFC 0018 decision 6 is what
makes these module moves free, and landing the closure test first means the refactor
cannot silently change the public namespace.

Independent of RFC 0020–0022. Sequence within the wave: the three contracts and the purity
guard land **first** — green, since §10.3 confirms there is nothing pre-existing to fix —
so the refactor is executed against a stated target rather than producing one; then one PR
per stage, each with green goldens; then `plan/diff.py` or its recorded deferral.
