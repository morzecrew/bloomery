# RFC 0033 — Observability: logging and a warnings channel

- **Status:** 📝 Draft — proposed, not started. Argued here so that the two gaps the
  production-readiness audit named ("zero logging in `src/`; `QueryPlan.warnings` exists
  but is planner-only, and no compile-time analogue") get a settled design before any
  code, rather than an ad-hoc `logging.info` sprinkled where it first seemed useful.
- **Scope:** Two additions to the library's observational surface: (1) stdlib
  `logging` under a single `"bloomery"` logger hierarchy, stage-level and silent by
  default, across the compile path (`load_project`, resolution, guardrails, lowering,
  emission) and the runtime seams (hydration misses, planner delegation); (2) a
  **structured warnings channel** for compile-time advisories — findings that are not
  refusals — carried on values, not on a side channel. Also names the runtime
  `DeprecationWarning` signal, whose policy [`stability.md`](../pages/docs/reference/stability.md)
  already records, as the third and only use of Python's `warnings` module. No behaviour
  of any existing artifact changes; no existing signature breaks (one evidence type
  gains a field).
- **Related:** RFC 0003 (determinism invariants — the constraint everything here is
  designed under), RFC 0011 (`QueryPlan.warnings`, the precedent this generalizes),
  RFC 0014 D6 (hydration counters over an observability dependency — the same taste
  applied here), RFC 0020 (the CLI, which becomes the first consumer),
  [`pages/docs/reference/stability.md`](../pages/docs/reference/stability.md) (the
  deprecation policy this gives a mechanism to).
- **Origin:** The "Road to Bloomery 1.0" production-readiness audit (2026-09-01), §3
  Hardening: "No logging, no compile-path warnings channel, no deprecation mechanism."
  The deprecation half was answered in docs the same day; this RFC is the design for the
  other two, split out because both add public surface to a library whose core promise
  is purity, and that deserves an argument rather than a patch.

---

## 1. Summary

bloomery's compile path is a pure function and must stay one. That is compatible with
observability, but only under discipline, so this RFC draws the line first and designs
inside it:

- **Logging is telemetry about execution, never an output.** A `"bloomery"` logger
  hierarchy emits stage-level records; the library attaches no handler, configures no
  format, reads no clock of its own, and produces byte-identical artifacts whether the
  caller listens or not (D1–D4).
- **Warnings are findings, and findings are values.** A compile-time advisory — a
  construct that is legal but suspicious, a spelling that will change — is a typed
  `Advisory` carried on the evidence the caller already receives, exactly as
  `QueryPlan.warnings` already does at request time (D5–D7). Nothing important is ever
  *only* logged.
- **Python's `warnings` module is reserved for deprecation**, the one case where the
  interpreter-level channel is the point: test suites run with `-W error` are the
  audience (D8).

## 2. Motivation

**A caller embedding a slow compile is blind.** `compile_project` on a large project is
a single opaque call: no way to see which stage is running, how many entities resolved,
or where the time went. The bench lane (RFC 0009 §5.9) answers "how long", not "where";
a library that will be embedded in schedulers and services should answer both without a
debugger.

**The planner has a warnings channel and the compiler does not.** `QueryPlan.warnings`
exists because some findings are worth saying and not worth refusing over — a clamped
limit, an inapplicable grain. The compile path has the same class of finding (§5.3 lists
the first three candidates) and today its only choices are refuse, stay silent, or grow
a docs caveat nobody reads at compile time. The asymmetry is an accident of which
surface was built last, not a design.

**Deprecation policy exists; its mechanism does not.** `stability.md` promises a
runtime `DeprecationWarning` whenever an old spelling can survive one more minor
release. Nothing in `src/` can currently emit one under a coherent category, so the
first real deprecation would invent the mechanism under deadline — the exact failure
mode writing-it-down-first exists to prevent.

## 3. The constraint: what purity actually forbids

RFC 0003's invariants are about **inputs**: no clock, no randomness, no environment, no
filesystem — same specs in, byte-identical artifacts out, across processes and hash
seeds. Logging sits on the **output** side of that line: a `logger.info(...)` call reads
nothing ambient in bloomery's own code and cannot reach the returned artifacts.
Timestamps on log records are produced by the *handler* the caller installed, on the
caller's side of the boundary, which is where RFC 0003 already places I/O.

Three rules keep it that way, and each is enforceable:

- **D1 — No handler, ever.** The library's only configuration act is
  `logging.getLogger("bloomery").addHandler(logging.NullHandler())` at package import,
  the stdlib-documented posture for libraries. No `basicConfig`, no format, no level.
  A grep-able invariant, testable as one.
- **D2 — Log records never carry nondeterminism of bloomery's making.** Messages are
  built from the same deterministic values the pipeline already holds (stage names,
  counts, fingerprints, source paths). The pre-commit pygrep bans on `datetime.now`,
  `time.time` and `uuid4` under `src/` stay exactly as they are — logging gives them no
  exemption. A record's timestamp exists only if a handler adds one.
- **D3 — Logging is not load-bearing.** No test may assert behaviour *through* log
  output, and no code path may branch on logger state (`isEnabledFor` used purely to
  skip expensive message assembly is the one sanctioned read). The determinism suite
  gains one check: compile the corpus with a capturing handler at DEBUG and with none,
  and diff the artifacts — byte-identical, or the build fails.
- **D4 — Two levels only, to start.** `INFO`: one record per stage per compile
  (`"resolve: 412 entities"`), bounded, safe to leave on in production. `DEBUG`:
  per-entity/per-artifact detail, unbounded, for a developer with a specific question.
  No `WARNING`-level records at all — that severity belongs to the warnings channel
  (§5), and putting findings in logs is exactly the "only logged" failure D5 forbids.

## 4. Design: the logger surface

One hierarchy, named by stage, so a caller can tune without knowing internals:

```
bloomery              # NullHandler lives here
bloomery.spec         # load_project, document parsing
bloomery.resolve      # resolution walk
bloomery.guardrails   # batch sizes, per-check counts
bloomery.emit         # per-target artifact counts
bloomery.runtime      # hydration hits/misses (the counters, now narrated)
bloomery.planner      # delegation boundary
```

The CLI becomes the first consumer:

- **D9 — CLI verbosity is a handler, not a channel.** `--verbose` attaches a stderr
  `StreamHandler` at INFO to the `"bloomery"` logger for the duration of `main`, `-vv`
  at DEBUG; the handler is removed before `main` returns, so an embedder calling
  `main()` as a function is not left with a mutated global logger. The flag is a
  *view* over the same records any embedder gets, never a second instrumentation
  path — which also gives the feature a test surface that is a user surface. Whether
  the flag squares with RFC 0020's "no config" posture is open question 3; D9 fixes
  what the flag *means* if it lands, not that it lands.

## 5. Design: the warnings channel

### 5.1 Findings are values

A compile-time advisory is a frozen `Advisory(code, message, source_path)` — `code`
from a closed enum (mirroring `KNOWN_UNSUPPORTED`'s taste for closed vocabularies), the
message under the same "what's wrong / why / the way out" contract refusals carry, the
source path pointing into the authored document. Advisories are **sorted, deduplicated
tuples** (RFC 0003: tuples, not sets), under rules stated here rather than left to a
default (`evidence.py` already sorts its collections by explicit keys because sorting
evidence values directly is not a safe default):

- **Sort key:** `(code.value, source_path or "", message)` — total, explicit, and
  stable under a missing source path, which normalizes to the empty string for
  ordering while staying `None` on the value.
- **Identity:** two advisories are duplicates exactly when all three fields are equal;
  deduplication keeps the first of an equal pair, which the total sort makes
  indistinguishable from keeping any.

They ride the values a caller already receives:

- `evaluate(...)` → `SpecEvidence.advisories` — new field, default empty, **appended
  after `provenance`**, today's final field. "Additive" holds positionally only for an
  appended field: `SpecEvidence` is a plain frozen dataclass, and a field inserted
  earlier silently rebinds positional construction. A positional-construction
  regression test lands with the field.
- `compile_project(...)` — **D6, the one genuinely open signature question.** Artifacts
  out is the whole contract, and this RFC's preferred answer is to leave it alone:
  callers who want advisories call `evaluate`, which already exists to answer "what
  does the compiler think of this project" and already carries evidence. The
  alternative — a `CompileReport` wrapping artifacts plus advisories behind a new
  entry point — is recorded here as the fallback if real usage shows callers skipping
  `evaluate` and losing warnings in practice. Deciding this needs a consumer, not a
  guess; the field on `SpecEvidence` is useful under either answer and ships first.

### 5.2 What a warning is not

A refusal that lost its nerve. The bar for an advisory is: **the spec is legal, the
compiled artifacts are correct, and there is still something the author would want to
know.** Anything where the numbers could be wrong stays a refusal — this RFC does not
soften "refuse rather than answer wrongly", and a review that finds an advisory where a
refusal belongs should treat it as a defect (D7).

### 5.3 First candidates

Three advisories are in scope for the first change, chosen because each was requested
by an audit finding or an existing docs caveat:

1. **Inexact recipe division** — `dialects.md` documents that a catalog recipe's `/`
   is inexact on every engine; the author of a spec using one currently learns that
   only by reading the reference. (`ADVISORY_INEXACT_DIVISION`)
2. **A quality rule on a column no rule class strengthens** — legal, correct, and
   usually a typo'd column name that happened to exist. (`ADVISORY_UNSTRENGTHENED_RULE`)
3. **A deprecated spelling still being accepted** — the compile-time twin of D8's
   runtime warning, so spec authors see the move in `evaluate` output and CI, not only
   in Python test suites. (`ADVISORY_DEPRECATED_SPELLING`)

The enum is closed and each addition is a reviewed change; there is no free-text
advisory constructor.

## 6. Design: deprecation

- **D8 — `warnings.warn(..., BloomeryDeprecationWarning)` at the old call site**, where
  `BloomeryDeprecationWarning(DeprecationWarning)` is exported so `filterwarnings` can
  target bloomery precisely, naming the replacement and the removal release — the
  exact text `stability.md` promises. **At most once per process per spelling, by an
  explicit guard** — a module-level set of spellings already warned — not by the
  warnings machinery's default filter, which deduplicates on
  (message, category, module, lineno) and is caller-overridable in both directions:
  an `always` filter would repeat bloomery's warning per call without the guard, and
  the guard cannot *show* a warning a caller's `ignore` filter hides — it only bounds
  how often bloomery emits. This is the only use of the `warnings` module in `src/`;
  advisories (§5) and log records (§4) each have their own channel, and the three do
  not blur. The guard is process-global mutable state, so it is documented alongside
  the thread-safety contract: a duplicate emission under a concurrent first hit is
  harmless and tolerated rather than locked against.

## 7. What is deliberately absent

- **No observability dependency** — no structlog, no OpenTelemetry. RFC 0014 D6 made
  this call for counters and it holds for records: the stdlib logger is the seam, and
  anything richer is the caller's adapter.
- **No metrics registry, no tracing spans.** Counters that matter are already values
  (`hits`/`misses`); spans belong to the embedder who knows what a request is.
- **No log-based contracts.** Message text is not API; only the logger *names* are
  stable, documented in `stability.md`'s deep-import terms.
- **No progress callbacks.** A `on_stage=` callable was considered and dropped: it
  invites callers to mutate state mid-compile and duplicates what a DEBUG handler
  already sees.

## 8. Testing sketch

- D1/D3 as direct tests: importing `bloomery` installs exactly one `NullHandler` and
  no level; the determinism suite compiles the corpus with and without a DEBUG
  capturing handler and byte-compares artifacts.
- Advisory messages join the refusal-text golden corpus
  (`tests/golden/test_refusal_messages.py` grows a sibling), because an advisory
  message degrading silently is the same defect class as a refusal message degrading.
- The docs floor extends its census: every `ADVISORY_*` code documented, every
  documented code constructible — the same closed-vocabulary discipline
  `KNOWN_UNSUPPORTED` already has.
- One CLI test per verbosity flag, asserting records reach stderr and artifacts do not
  change.

## 9. Open questions

1. **D6's shape** — `SpecEvidence.advisories` alone, or also a `CompileReport`? Held
   open until a real embedder asks; the evidence field ships either way.
2. **Whether `bloomery.runtime` records at INFO or only DEBUG** — a hydration miss is
   per-request telemetry and INFO may be too chatty for a hot service; measure in the
   bench lane before choosing.
3. **Whether the CLI's `--verbose` belongs in this RFC or in a CLI amendment** — it is
   listed here (D9) because it is the first consumer, but RFC 0020's "no config"
   posture should be re-read before the flag lands.
