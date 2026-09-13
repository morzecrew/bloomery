# RFC 0072 — Continuous fuzzing in CI

- **Status:** 📝 Draft
- **Scope:** Running RFC 0071's targets continuously: where the corpus lives
  between runs, which workflows run which targets for how long, and the replay
  job that checks the determinism claim no in-process target can reach. Adds
  workflows and a corpus store; changes no `src/bloomery/` code and no target.
  **Does not adopt ClusterFuzzLite** — §5.1 measures why, and names it as the
  demand-gated upgrade rather than the starting point. Gated on RFC 0071 P1:
  there is no point running in CI what has not run on a laptop.
- **Related:** RFC 0071 (the targets, oracles and seeds this schedules),
  RFC 0003 (the determinism invariants §5.4 tests at scale),
  [`.github/workflows/`](../.github/workflows/),
  [`pyproject.toml`](../pyproject.toml) (`requires-python`).
- **Origin:** The same external design note as RFC 0071, whose §4 and §12
  proposed ClusterFuzzLite on the OSS-Fuzz base image. Its compatibility branch
  was written as a contingency; measurement (§3) shows it is the only branch, and
  that changes the recommendation rather than the plan.

---

## 1. Summary

A nightly job that runs RFC 0071's targets against a persistent corpus, and a
weekly **replay** job that takes everything the corpus has accumulated and checks
byte-identical output across processes and hash seeds. Both run on
`actions/setup-python`, not in a fuzzing container. ClusterFuzzLite is the
upgrade path, priced in §5.1 and not taken now.

## 2. Motivation

**Without persistent storage, a fuzzer does nothing.** Random bytes essentially
never survive `yaml.safe_load`, so a run that starts from an empty corpus spends
its entire budget rediscovering that YAML has syntax. The corpus — not the CPU —
is the asset, and it is the single highest-leverage thing in this document.

**The determinism promise is not testable in one process.** RFC 0003 requires
byte-identical artifacts across processes and across `PYTHONHASHSEED`. RFC 0071
§5.1 can assert idempotency within a process and explicitly defers the rest here,
because no in-process assertion can make a cross-process claim. The replay job is
where the headline promise finally gets tested at scale — against thousands of
inputs a fuzzer selected for being *interesting*, rather than inputs a person
thought of. That is the highest-value job in this document, and notably it needs
no fuzzing infrastructure at all: it is an ordinary script.

**Findings arrive on a schedule a laptop does not keep.** Fuzzing pays over
weeks. A local lane is where targets are written and debugged; continuous
running is where they earn out.

## 3. Current state

Measured today against the live images and package index, not from the note's
metadata.

| Fact | Measured | Source |
|---|---|---|
| `base-builder-python:latest` | **Python 3.11.13** | `docker run … python3 -V` |
| `base-builder-python:ubuntu-24-04` | **Python 3.11.13** | same |
| bloomery's requirement | `requires-python = ">=3.12,<3.15"` | `pyproject.toml:4` |
| `pip3 install .` in the base image | **Fails** — hatchling errors preparing metadata under 3.11 | `pip3 install --no-deps --dry-run /src` |
| atheris in the base image | **3.0.0 preinstalled**, the last release with a cp311 wheel | `pip3 install --dry-run atheris` |
| atheris latest | 3.1.0 — wheels **cp312 / cp313 / cp314 only, and no sdist at all** | PyPI JSON API |

The note records that *"Atheris is not a constraint: it supports 3.11–3.14 with
prebuilt wheels."* That was true of atheris 3.0.0 and is no longer true of 3.1.0,
which dropped cp311 and stopped shipping a source distribution. The two facts
compose badly: the base image is pinned to the one interpreter bloomery cannot
run on, *and* to the one atheris release that still supports it.

The consequence is that the note's §4 decision table has only one live branch.
There is no tag where `pip3 install .` succeeds, so the CPython source-build
block is **mandatory rather than contingent** — a hand-maintained interpreter
build in a Dockerfile, plus a mandatory atheris reinstall against it, in a base
image whose layout is upstream's to reorganise. The note itself says: *"If you
fix it twice, switch to the plain-Atheris approach instead."* Knowing in advance
that it must be built once and maintained thereafter, this document does not
start there.

Also relevant: the repo runs a `Required Continuous Integration` status check on
`main`, and displays an OpenSSF Scorecard badge whose `Fuzzing` check looks for
ClusterFuzzLite or OSS-Fuzz specifically. §9 states plainly that this document
forgoes that check.

## 4. Goals / Non-goals

**Goals**

- Persist the corpus between runs, so week two is better than week one.
- Test RFC 0003's determinism claim across processes and hash seeds, at corpus scale.
- Keep the nightly cost inside a public repo's free runner budget, well clear of
  the 6-hour job cap.
- Report findings somewhere a person actually reads.
- Depend on nothing whose breakage silently produces a green check.

**Non-goals**

- **Crash deduplication and coverage dashboards.** Genuinely useful, genuinely
  ClusterFuzzLite's; §5.1 prices them and §12 names when to revisit.
- **The Scorecard `Fuzzing` check.** A badge is not a reason to maintain a
  CPython build (RFC 0071 §4 makes the same point about motivation).
- **Blocking PRs.** §5.5 — non-blocking on purpose, and for longer than feels
  comfortable.
- **Self-hosted runners.** A 2-vCPU runner is not the bottleneck; a bad corpus is.

## 5. Design

### 5.1 Plain Atheris on `setup-python`, not ClusterFuzzLite

| | ClusterFuzzLite | Plain Atheris on `setup-python` |
|---|---|---|
| Interpreter | Hand-built CPython 3.12 in a Dockerfile, atheris reinstalled against it, both to be re-fixed whenever upstream reorganises the base images | `python-version: '3.13'`, one line |
| Corpus | Managed sync to a storage repo, needs a second repo and a PAT | `actions/cache`, or a repo if the cache proves too small |
| Crash dedup | Yes | No — duplicate crashes must be eyeballed |
| Coverage report | Yes, on `gh-pages` | No |
| PR-diff targeting | Yes (`mode: code-change`) | No — whole-corpus runs only |
| SARIF | Yes, and reported as pointing into libFuzzer's own headers rather than your code | No |
| Silent-failure modes | Reported: coverage uploads that delete the previous report, batch jobs green having done nothing | The job's own log |

Every RFC 0071 target, oracle, seed and dictionary is **unchanged** either way —
they are libFuzzer arguments and an Atheris `TestOneInput`, not ClusterFuzzLite
API. That is what makes this reversible: adopting ClusterFuzzLite later is
writing a Dockerfile and three workflows, not rewriting the lane.

What we give up is real, and coverage reporting is the loss that matters. It is
the only signal separating *"found nothing because the code is correct"* from
*"found nothing because it never reached the code"*, and D4 keeps a
locally-runnable substitute rather than pretending the question does not exist.

### 5.2 The corpus

`actions/cache`, keyed per target, restored at job start and saved at job end.
Chosen over the note's dedicated storage repo because it needs no second
repository, no fine-grained PAT, and no secret in a workflow that runs
deliberately hostile input — and the token is the part of that arrangement worth
avoiding. The eviction rule (7 days without access, 10 GB per repo) is
comfortable for a nightly job; if either bound bites, D3 says what replaces it.

Seeds are built from the tree rather than committed twice: a script copies
`examples/**` and `tests/golden/**` YAML into each target's seed directory, so
the corpus floor tracks the examples instead of drifting from them.

### 5.3 The nightly batch

One workflow, on a schedule and on `workflow_dispatch`, matrixed over
`PYTHONHASHSEED: ['0', '1', 'random']` with `fail-fast: false`. The three entries
share one corpus, which is the point: an input discovered under one seed is
replayed under the others the following night, so a hash-order bug surfaces
within a day of becoming reachable. Roughly 50 minutes of runner time a night
across the matrix.

### 5.4 The replay job

Distinct from fuzzing, weekly, and the highest-value job here. Fuzzing explores;
**replay verifies** — it takes the accumulated corpus and applies the checks too
slow for the fuzzing loop:

- compile each input in **two separate processes** under different
  `PYTHONHASHSEED`, and diff artifacts byte for byte — the full RFC 0003 claim,
  which no in-process target can make;
- compile to all three targets across all three dialects;
- assert artifact ordering is stable independently of compile order.

`fuzz/replay.py` is an ordinary script — no instrumentation, no libFuzzer — so it
runs at full speed and can afford subprocesses. It exits non-zero with a diff on
any divergence. It is also the one job here that would be worth keeping if
everything else in this document were deleted, which is why D2 makes it P1.

### 5.5 The PR job, and why it stays non-blocking

A short run on PRs touching `src/**` or `fuzz/**`, with `concurrency` cancelling
superseded runs. **Non-blocking for at least a month**, and longer if findings
are still arriving: the early weeks are when the harness is wrong, and a red
required check on every PR during that period is how fuzzing setups get deleted.
D5 makes promotion a deliberate act with a stated condition rather than a thing
someone eventually does.

### Alternatives considered

**ClusterFuzzLite now, source-build and all.** Rejected on §3's measurement, not
on principle. It buys dedup, coverage and PR-diff targeting for a hand-maintained
interpreter build; taken *after* the lane has proven it finds things, the same
purchase is much easier to justify.

**Nightly runs with no persistence.** Rejected: it is the shape that produces a
green check every night having discovered nothing, which is worse than no job,
because it reads as coverage.

**A dedicated corpus repository and PAT from the start.** Rejected as premature
(§5.2). It is D3's answer if the cache proves too small — a real possibility,
just not one to build for before it happens.

## 6. Tests

Infrastructure, so the tests are about whether the jobs can lie.

- **The batch job must fail on a planted crash.** Commit a deliberately escaping
  input to the seed corpus on a scratch branch and confirm the job goes red. A
  scheduled job that has never been observed failing is not known to work — and
  the upstream tooling this document declines has a *reported* silent-failure
  mode of exactly this shape.
- **The replay job must fail on a planted nondeterminism.** Sabotage an emitter
  to sort by a set, and confirm the cross-seed diff catches it. This is the same
  discipline RFC 0071 §6 applies to its oracles.
- **Corpus growth is asserted, not assumed.** The batch job prints the corpus
  entry count before and after; a run where it never changes across a week is
  reported, since it means the cache is not round-tripping.
- **Not tested:** that the corpus is representative. That needs coverage
  measurement, which is D4's locally-runnable job.

## 7. Docs

`pages/docs/contributing/fuzzing.md` — the page RFC 0071 P1 creates — gains a
short section on what runs when, and how to fetch a crashing input from a failed
run. No user-facing page changes.

## 8. Out of scope

- **The targets themselves** — RFC 0071 §5.3. This document schedules them.
- **Schema-directed generation** — RFC 0073.
- **Fuzzing the container-backed examples.** A container per execution destroys
  throughput; the execution and e2e tiers own engines actually running.
- **Automatic issue filing from findings.** Triage is a person's job
  (RFC 0071 §5.7), and a bot that files a duplicate crash nightly is how the
  finding stream gets muted.

## 9. Risks

- **The lane rots quietly.** The chief risk of every scheduled job, and the
  reason §6's planted-failure tests exist rather than a green badge.
- **Cache eviction resets the corpus.** Costs weeks of accumulated exploration
  and is invisible in a green run. Mitigated by §6's entry-count assertion, and
  D3 names the escalation.
- **Duplicate crashes drown the signal.** The concrete cost of declining dedup.
  If one defect produces dozens of inputs a night, that is the trigger for §12's
  P4 rather than a reason to stop reporting.
- **No coverage report means the corpus can plateau unnoticed.** D4's local job
  is the mitigation, and it is weaker than the hosted one — it runs when someone
  remembers.
- **Forgoing the Scorecard `Fuzzing` check.** The badge is visible and this
  document leaves that check unsatisfied while the project does more fuzzing than
  before, which reads backwards to anyone reading only the badge. Accepted, and
  stated here so it is a decision rather than an oversight.
- **Findings arrive faster than they are triaged.** Then the schedule is wrong,
  not the targets: reduce the cadence rather than widening `EXPECTED`, which
  RFC 0071 D3 forbids anyway.

## 10. Unresolved questions

- **Does `actions/cache` hold a fuzzing corpus comfortably?** The bounds look
  ample on paper; nobody has run it here. One month of nightly runs answers it,
  and D3 pre-commits the response either way.
- **What cadence does the replay job want?** Weekly is a guess. Its runtime grows
  with the corpus, and the first month's numbers settle it.
- **Where does a finding get reported?** A failed scheduled job notifies whoever
  owns the repo and nobody else. Whether that is enough, or whether it wants an
  issue, is unsettled — and deliberately not answered by *"file one
  automatically"* (§8).

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | CI runs plain Atheris on `actions/setup-python`, not ClusterFuzzLite. Measured: both base-image tags ship Python 3.11.13, bloomery requires `>=3.12` and fails to build there, and atheris 3.1.0 has no cp311 wheel and no sdist — so the container path *requires* a hand-maintained CPython build from day one. Consequence: no crash dedup, no hosted coverage, no PR-diff targeting, and the Scorecard `Fuzzing` check stays unsatisfied. Locked because it is measurement, not preference; it is revisited by re-measuring (§12 P4), not by re-arguing. |
| 2 | `LOCKED` | The replay job lands in P1, before or alongside the batch job. It is the only thing here that tests RFC 0003's cross-process claim, it needs no fuzzing infrastructure, and it is the job worth keeping if everything else is dropped. Locked so that a phase slip cannot quietly reorder it behind the fuzzing jobs. |
| 3 | `ASSUMED` | The corpus lives in `actions/cache`, not a storage repo with a PAT. Assumed on stated bounds nobody has exercised here. If eviction or size bites, the departure is a dedicated corpus repository with a fine-grained token scoped to that repo alone — never a token that can write to `bloomery`, since these jobs run deliberately hostile input. |
| 4 | `ASSUMED` | Coverage is measured by a locally-runnable job rather than a hosted report. Weaker: it runs when someone remembers. Accepted because the alternative is D1's container. Depart if the corpus plateaus and nobody can say which modules it reaches. |
| 5 | `OPEN` | When the PR job becomes required. Not before a month non-blocking, and not while the harness is still producing findings per week — but the actual condition is a judgement about whether a red check would be believed. Execution states the condition it used. |
| 6 | `OPEN` | Nightly duration and matrix width. Three hash seeds is the shape D1's reasoning wants; the per-entry budget is a guess to be set from the first week's execution counts, which is also how a silently-failing job gets noticed. |
| 7 | `ASSUMED` | Seeds are generated from `examples/**` and `tests/golden/**` at build time rather than committed under `fuzz/`. Keeps the floor tracking the examples; depart if generation proves slower than the run it seeds. |

## 12. Phasing

- **P1 — the replay job.** `fuzz/replay.py` and its weekly workflow. No corpus
  needed to start: it can replay `examples/` and `tests/golden/` on day one and
  pick up the fuzz corpus when it exists. Ships the cross-process determinism
  check RFC 0003 has never had. **The whole of D2.**
- **P2 — the nightly batch.** The hash-seed matrix, `actions/cache` persistence,
  the corpus entry-count assertion, and §6's planted-crash test.
- **P3 — the PR job.** Non-blocking, path-filtered, concurrency-cancelled.
  Promotion to required is D5 and is not part of this phase.
- **P4 — revisit ClusterFuzzLite.** Demand-gated on *either* duplicate crashes
  becoming the dominant triage cost, *or* the corpus plateauing with no way to
  see where it reaches, *or* the base image gaining a tag on Python 3.12+ —
  re-measure §3's table rather than trusting this document's numbers, which have
  a shelf life.
