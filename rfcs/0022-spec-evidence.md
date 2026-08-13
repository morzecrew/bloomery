# RFC 0022 — `SpecEvidence`: spec analysis as a first-class output

- **Status:** 📝 Draft
- **Scope:** One new public function, `evaluate(project) -> SpecEvidence`, returning
  everything knowable about a spec **without touching data**: reachable and unreachable
  metrics with their specific missing leaves, batched refusals with source paths, and a
  mart summary. A re-presentation of `resolve()` plus batched compile errors under one
  call and one return type. Adds no analysis bloomery does not already perform, executes
  nothing, and reads no data.
- **Related:** RFC 0005 (`Resolution`, reachability with specific missing leaves — the
  substance this exposes), RFC 0002 (batched errors with source paths), RFC 0006 (the
  batched guardrail stage), RFC 0010 (mart grain and flattening — the summary),
  RFC 0018 (**blocking**: signature closure covers
  the new return type),
  [RFC 0020](0020-authoring-ergonomics.md) (`bloomery resolve` is re-pointed at this),
  [RFC 0021](0021-capability-boundaries.md) §5.5 (the boundary this respects).
- **Adoption audit:** every claim in §3 verified; no corrections were needed.

---

## 1. Summary

A caller who wants to know what a spec *would* produce — before running anything, before
data exists — currently writes a `try`/`except` around `compile_project` to collect
refusals, a separate `resolve()` call for reachability, and their own walk of the IR for
mart shape. Three calls, two exception paths, one hand-rolled traversal, repeated by every
consumer.

`evaluate()` returns all of it as one frozen value:

```python
def evaluate(project: Project, *, catalog: Catalog | None = None,
             steps: StepRegistry = EMPTY_REGISTRY) -> SpecEvidence
```

It adds no capability. Its contribution is naming a concept the library already computes
and currently discards at the exception boundary — and making a *partial* answer available
where today a single refusal collapses the whole analysis.

## 2. Motivation

**The immediate consumer is a proposal loop.** A machine-authored spec needs an assessment
before a human reviews it, and the assessment that matters is not "did it compile" but
"what would it give you." Bloomery knows: which metrics resolve, which do not and *which
specific leaf is missing*, what refusals fired and where. Today a consumer reaches that
through an exception handler, which is the wrong shape twice over — refusal is a normal
outcome here, not an error condition, and an exception carries one batch where the caller
wants the batch *and* the reachability that would have followed.

**The deeper point is partiality.** `compile_project` is all-or-nothing by design, and
correctly so: it emits artifacts or it refuses. But a reviewer reading a draft spec wants
"seven metrics reachable, two blocked on `cogs`, one refusal at
`mappings/crm.yaml:fields.email`" — an assessment that survives the refusal. That is not
available today at any price, and it is the single most useful sentence bloomery can
produce about a spec it will not compile.

**The reachability half is already the best thing the library knows.** RFC 0005 computes,
for every unreachable metric, the specific missing leaf. "You would get revenue and order
count but not margin, because nothing maps to `cogs`" is the sentence that makes a review
take thirty seconds instead of twenty minutes. It is reachable today only by calling
`resolve()` and knowing to.

## 3. Current state

Verified against `main` @ `3da72c5` (2026-08-12):

- `resolve(project, catalog) -> Resolution` — root-exported, returns reachable and
  unreachable metrics with missing leaves per RFC 0005. Raises on cross-spec reference
  errors (batched).
- `compile_project(...) -> tuple[EmittedArtifact, ...]` — raises `BloomeryError` on any
  refusal; the batched refusal set is carried on the exception.
- `build_project_ir(...) -> ProjectIR` — the shared front half of both.
- Guardrails (RFC 0006) and quality declaration refusals (RFC 0016) batch within their
  stage; a batch from an earlier stage prevents a later stage running at all.
- No function returns "everything knowable" as a value. No summary of mart shape is
  exposed; a caller wanting grain and measure sets walks `ProjectIR` directly.
- `Resolution` is exported; `ProjectIR` is not (RFC 0018 §5.1 fixes that).

## 4. Goals / Non-goals

**Goals**

- One call, one frozen return type, for "what would this spec give me."
- A **partial** assessment where the current API gives none — refusals reported *alongside*
  whatever analysis completed.
- Refusals as a value in the normal path, not only on an exception.
- No new analysis, no execution, no data access.

**Non-goals**

- **Data-dependent evidence** — coercion failure rates, null deltas, sample rows, row
  counts. All require execution, which is the library's boundary. The platform composes
  `evaluate()` with its own dry-run.
- Replacing `resolve()` or `compile_project()`. Both stay; `evaluate()` composes them.
- Cost or performance estimation. Bloomery does not know table sizes.
- Judgement. `SpecEvidence` carries facts; approve/reject is the caller's.
- Suggestions beyond RFC 0020's structured refusal fields, which `evaluate()` surfaces
  unchanged.

## 5. Design

### 5.1 The type

```python
# bloomery/evidence.py  (new, public)

# UnreachableMetric is NOT declared here — the IR already has it (see below);
# it gains `via` and is re-exported:
#
#     name: str
#     missing: tuple[str, ...]     # the specific leaves — RFC 0005's substance
#     via: tuple[str, ...] = ()    # intermediate metrics, when blocked transitively

@dataclass(frozen=True)
class MartSummary:
    name: str
    grain: str
    measures: tuple[str, ...]
    dimensions: tuple[str, ...]     # role-qualified
    materialization: MaterializationName

@dataclass(frozen=True)
class SpecEvidence:
    reachable: tuple[str, ...]
    unreachable: tuple[UnreachableMetric, ...]
    refusals: tuple[BloomeryError, ...]     # batched, each with source_path
    marts: tuple[MartSummary, ...]
    entities: tuple[str, ...]
    stage_reached: Stage                    # how far analysis got
    fingerprint: str | None                 # None when the IR did not build
```

All tuples sorted, and each by a **declared key** — determinism applies here as
everywhere, and `sorted()` over `BloomeryError` or `MartSummary` values does not merely
order badly, it raises `TypeError`: neither defines `__lt__`, and Python has no
lexicographic fallback for dataclasses or exceptions. The keys are part of the contract,
not an implementation detail:

| Field | Sort key |
|---|---|
| `reachable`, `entities` | the string itself |
| `unreachable` | `(name, missing, via)` |
| `marts` | `(name, grain)` |
| `refusals` | `(source_path or "", type(err).__name__, str(err))` |

`source_path` is optional on `BloomeryError`, so the empty string stands in for `None`
rather than the sort failing on a mixed tuple — a refusal with no source path sorts first
and deterministically.

**`UnreachableMetric` already exists**, in
[`ir/nodes.py:552`](../src/bloomery/ir/nodes.py) — as `(name, missing)`, populated by
`resolve()` and carried on `ProjectIR.unreachable`. Declaring a second dataclass of the
same name in `bloomery/evidence.py` and root-exporting it would leave two types with one
name, differing in a field, one of them reachable from `ProjectIR` and the other from
`SpecEvidence`; a caller comparing them would get `False` and no explanation.

So `evidence.py` does not define it. The **IR type is extended** with `via: tuple[str, ...]
= ()`, defaulted so every existing construction keeps working, and re-exported. That is
also what §5.2's "projection, not recomputation" already implies: `SpecEvidence.unreachable`
*is* `ProjectIR.unreachable`, not a copy of it in a parallel shape.

**That addition is not free, and the default does not make it free.** The canonical
encoder ([`ir/fingerprint.py:54`](../src/bloomery/ir/fingerprint.py)) writes a
dataclass as its class name, its **field count**, then each field name and value:

```text
CS17:UnreachableMetric2:S4:nameS1:xS7:missingT1:S1:y      # today
CS17:UnreachableMetric3:S4:nameS1:xS7:missingT1:S1:yS3:viaT0:   # with via
```

So every spec with an unreachable metric gets a new `blm1:` fingerprint, and
`bloomery_ir_version` goes 4 → 5 — the managed path RFC 0016 and RFC 0017 already took.
The draft's `name` → `metric` rename costs **exactly the same** by the same encoding, so
cost is not what decides between them: the rename is dropped because it buys a synonym,
while `via` carries information nothing else does.

`stage_reached` is what makes partiality honest:

```python
class Stage(StrEnum):
    PARSE = "parse"; RESOLVE = "resolve"; TYPECHECK = "typecheck"
    GUARDRAILS = "guardrails"; MARTS = "marts"; COMPLETE = "complete"
```

Empty `unreachable` means *nothing is unreachable* only at `COMPLETE`. At `PARSE` it means
reachability was never computed. Without this field an empty tuple is ambiguous in exactly
the way that produces a wrong conclusion, so **every consumer must read `stage_reached`
before reading anything else**, and the docstring says so.

### 5.2 Partial analysis: run every stage that can run

`evaluate()` runs the pipeline and, at the first stage that refuses, **stops and reports
what completed** — rather than propagating.

```text
parse ──▶ resolve ──▶ typecheck ──▶ guardrails ──▶ marts ──▶ COMPLETE
  │          │            │             │            │
  └──────────┴────────────┴─────────────┴────────────┴──▶ SpecEvidence(stage_reached=…)
```

Two deliberate constraints:

**Stages are not reordered or skipped to salvage more.** A guardrail refusal means the
model is wrong; continuing to mart summarization would report a shape derived from a spec
bloomery has already said is invalid. `stage_reached` is honest about where analysis
became untrustworthy — an over-eager partial answer is worse than an incomplete one.

**Within a stage, batching is unchanged.** RFC 0002/0006's batched reporting already
collects every refusal in a stage; `evaluate()` surfaces that batch, it does not re-batch.

This is the only genuinely new behaviour in the RFC, and it is behaviour the pipeline
already supports — the stages are already sequential and already batch. What is new is not
throwing away the prefix.

### 5.3 `evaluate()` composes; it does not reimplement

```python
def evaluate(project, *, catalog=None, steps=EMPTY_REGISTRY) -> SpecEvidence:
    """Everything knowable about a spec without touching data.

    Never raises for a spec-level refusal — refusals are the return value.
    Read `stage_reached` before interpreting any other field.
    """
```

It calls the same `build_project_ir` → `resolve` path everything else does. `MartSummary`
is projected from `ProjectIR`, not recomputed. No analysis exists here that does not exist
elsewhere.

**Programming errors still raise.** A `TypeError` from a malformed `StepRegistry`, a
`MemoryError`, anything that is a bug rather than a spec judgement — those propagate.
`evaluate()` catches `BloomeryError` and nothing else. A function that returns instead of
raising on a caller bug would be worse than the exception path it replaces.

`InvariantViolated` (RFC 0003 D11) is the one subclass where that rule bites: it *is* a
`BloomeryError` by inheritance and *is* a bloomery bug by meaning, so it would be caught
and reported as a spec refusal. It is re-raised explicitly rather than swallowed — the
narrow catch is only as good as the taxonomy under it, and this is the known soft spot.

### 5.4 Consumers

**The proposal loop** (the platform):

```python
ev = evaluate(proposed_project, catalog=catalog, steps=registry)
if ev.stage_reached is not Stage.COMPLETE:
    return reject(ev.refusals)              # structured, with source paths
present_to_reviewer(reachable=ev.reachable, blocked=ev.unreachable, marts=ev.marts)
```

The reviewer sees "seven metrics, two blocked on `cogs`, three marts" — which, combined
with a data-dependent dry-run the platform runs separately, is the evidence payload the
approve/reject decision needs.

**`bloomery resolve`** (RFC 0020) re-points at `evaluate()` and gains refusal reporting:
the CLI today would print reachability or raise; afterwards it prints reachability *and*
refusals, which is what a spec author actually wants when the spec is mid-draft.

**Editors and CI** — `--format json` over `SpecEvidence` is a diffable assessment of a
spec change, complementing `plan()`'s assessment of a spec *diff*.

### 5.5 Where the boundary sits

`SpecEvidence` is deliberately half of what a reviewer needs. The other half is
data-dependent — coercion rates, null deltas, sample rows — and requires execution.

```text
bloomery.evaluate()   →  static evidence      (specs only, no data)
platform dry-run      →  data evidence        (sample rows through the emitted SQL)
             ↘
        one review payload
```

This is RFC 0021 §5.5's disposition applied to an output rather than an input: the thing
bloomery can compute without data, it computes; the thing it cannot, it does not pretend
to. The temptation here is real — `evaluate()` looks like the natural home for "and also
run it against a sample" — and taking it would put an engine connection inside the
compiler, ending the infrastructure-free test suite in the same commit.

## 6. Tests

Per RFC 0009 tiers. Unit-tier throughout — no infrastructure.

| Tier | Test |
|---|---|
| Unit | Every **valid** fixture: `evaluate()` returns `stage_reached=COMPLETE`, `refusals=()`, and `reachable`/`unreachable` **equal to** what `resolve()` returns — the composition is proven, not assumed. The deliberately invalid fixtures are covered by the three rows below, which assert the opposite outcome. |
| Unit | `fanout_trap` returns `stage_reached=GUARDRAILS` with the `GrainViolation` in `refusals`, and does **not** raise. |
| Unit | A spec with a parse error returns `stage_reached=PARSE`, `fingerprint=None`, and empty analysis tuples. |
| Unit | A spec refused at `guardrails` still carries the `resolve`-stage reachability computed before the refusal — the partiality claim, tested on the case it exists for. |
| Unit | `evaluate()` never raises `BloomeryError` **other than `InvariantViolated`** for any fixture, including deliberately invalid ones. The exclusion is not a caveat on the promise, it is §5.3's boundary: `InvariantViolated` subclasses `BloomeryError` but reports a bloomery bug, not a spec refusal, so reporting it as one would hide it. |
| Unit | A programming error (malformed `StepRegistry` type) **does** raise — the catch is narrow. |
| Unit | `InvariantViolated` propagates rather than being reported as a refusal (§5.3). |
| Unit | `MartSummary` fields match `ProjectIR` for every fixture with marts (projection, not recomputation). |
| Property | `evaluate()` is deterministic across `PYTHONHASHSEED`; all tuples sorted. |
| Unit | RFC 0018 signature closure holds — `SpecEvidence`, `UnreachableMetric`, `MartSummary`, `Stage` **and `MaterializationName`** are root-exported. The last is reached through `MartSummary.materialization` and is easy to miss precisely because it is a `Literal` alias rather than a class; RFC 0018's own inventory missed `LogicalType` the same way. |
| Unit | RFC 0020's suggestion fields survive into `refusals` unchanged. |

The fourth row is the one that would catch a regression to the old behaviour: it is easy to
implement `evaluate()` as a `try`/`except` around `compile_project` that discards the
prefix, which passes every other test here.

## 7. Docs

- New `pages/docs/how-to/evaluate-a-spec.md` — the call, the `stage_reached` contract, the
  proposal-loop shape.
- `pages/docs/reference/api.md` — the four new types.
- `pages/docs/concepts/compile-pipeline.md` — the stage sequence, now user-visible through
  `Stage`.
- `pages/docs/how-to/use-the-cli.md` (RFC 0020) — `bloomery resolve` re-pointed.

## 8. Out of scope

- Data-dependent evidence of any kind. The boundary, restated in §5.5.
- Cost or row-count estimation.
- Approve/reject judgement, scoring, or confidence.
- Replacing `resolve()` or `compile_project()`.
- Caching. Callers cache on `fingerprint`, as they do for compilation.

## 9. Risks

| Risk | Mitigation |
|---|---|
| `evaluate()` becomes the place data-dependent evidence gets added | §5.5 and decision 6 state the refusal; RFC 0019's purity guard blocks an engine import in `src/` structurally. The pressure is predictable and the guard is not advisory. |
| `stage_reached` is ignored and an empty `unreachable` at `PARSE` is read as "all reachable" | The docstring leads with it; §6 tests the ambiguous case; the CLI renderer prints the stage first. It cannot be made impossible, only loud. |
| Partial analysis reports a shape derived from an invalid spec | §5.2: stages are never reordered or skipped to salvage more, and analysis stops at the first refusing stage. An over-eager partial answer is worse than an incomplete one. |
| A third entry point diverges from `compile_project`'s view of a spec | It composes the same `build_project_ir` → `resolve` path; §6's equality test against `resolve()` is the guard. |
| The narrow `except BloomeryError` swallows a bug wearing a `BloomeryError` | Known and named: `InvariantViolated` is exactly that, and is re-raised explicitly (§5.3). Any future leaf meaning "bloomery bug" must join it — recorded as the assumption this rests on. |

## 10. Unresolved questions

1. Should `SpecEvidence` carry the compiled artifacts when `stage_reached is COMPLETE`?
   It would let a caller replace `compile_project` entirely. Leaning: no — a type meaning
   "assessment" should not sometimes also mean "output," and compilation is per-target
   while evidence is not.
2. Should `MartSummary` include an estimated column count, or anything shape-adjacent
   beyond names? Leaning: no — it is one step from row estimates, which is one step from
   needing data.
3. Does `evaluate()` need a `targets` parameter, so target-specific refusals
   (`UnsupportedByTarget`) appear? Today it stops before emission and cannot see them.
   Leaning: yes eventually, as `targets: tuple[Target, ...] = ()` with an `EMIT` stage —
   but only once a consumer needs it, since it makes evidence target-dependent and the
   proposal loop's first question is target-independent.
4. Should `Stage` be public, or is exposing the pipeline's internal sequence a coupling
   bloomery will regret? It must be public for `stage_reached` to be readable; the question
   is whether adding a stage is then a breaking change. Leaning: treat `Stage` as an
   open enum in the policy — consumers compare against `COMPLETE` and treat everything else
   as incomplete.

## 11. Decisions

| # | Decision |
| --- | --- |
| 1 | **`evaluate(project) -> SpecEvidence` is added**, composing `build_project_ir` → `resolve` and the batched refusal stages under one call and one frozen return type. It adds no analysis bloomery does not already perform; the contribution is naming the concept and stopping its discard at the exception boundary. |
| 2 | **Refusals are a return value, not an exception**, because a refusal on a draft spec is a normal outcome that a caller wants *alongside* the analysis that completed — not instead of it. `evaluate()` never raises `BloomeryError` — **except `InvariantViolated`**, which subclasses it but reports a bloomery bug rather than a spec refusal, and so propagates (decision 7). Programming errors outside the hierarchy propagate too; the catch is narrow by construction. |
| 3 | **Partial analysis is the point**: the pipeline runs to the first refusing stage and reports the prefix. "Seven metrics reachable, two blocked on `cogs`, one refusal at `mappings/crm.yaml`" is unavailable today at any price, and is the most useful sentence bloomery can produce about a spec it will not compile. This is the only new behaviour in the RFC, and the pipeline already supports it — stages are already sequential and already batch. |
| 4 | **Stages are never reordered or skipped to salvage more analysis.** A guardrail refusal means the model is wrong; summarizing marts past it would report a shape derived from a spec bloomery has already called invalid. An over-eager partial answer is worse than an incomplete one. |
| 5 | **`stage_reached` is mandatory to read**, stated first in the docstring and tested on the ambiguous case: an empty `unreachable` means "nothing unreachable" only at `COMPLETE`, and means "never computed" at `PARSE`. Without it the empty tuple is ambiguous in exactly the way that produces a wrong conclusion. |
| 6 | **Data-dependent evidence stays out, permanently.** Coercion rates, null deltas and sample rows require execution; the platform composes `evaluate()` with its own dry-run into one review payload. `evaluate()` is the natural-looking home for "and also run it against a sample," and taking that step would put an engine connection inside the compiler and end the infrastructure-free test suite in the same commit. |
| 7 | **The catch is narrow: `BloomeryError` only, minus `InvariantViolated`.** Programming errors — a malformed registry, a `MemoryError` — propagate. `InvariantViolated` (RFC 0003 D11) is a `BloomeryError` by inheritance and a bloomery bug by meaning, so it is re-raised explicitly rather than reported as a spec refusal; a narrow catch is only as good as the taxonomy beneath it. Both tested. |
| 8 | **`bloomery resolve` (RFC 0020) is re-pointed at `evaluate()`** when this lands, gaining refusal reporting, as an amendment to that RFC rather than a new command. A spec author mid-draft wants reachability *and* refusals in one output. |
| 9 | **`SpecEvidence` carries facts, never judgement** — no score, no confidence, no approve/reject. The reviewer decides; bloomery reports. This mirrors RFC 0005's rule that the compiler validates a recorded recipe but never chooses one. |
| 10 | **The composition is tested by equality**, not by inspection: for every fixture **that reaches the resolve stage**, `evaluate()`'s reachability equals `resolve()`'s. A parse-error fixture has no `resolve()` result to compare against — it is covered by the `stage_reached=PARSE` row instead, which asserts the analysis tuples are empty. A third entry point that drifts from the second is the failure mode this RFC could plausibly introduce. |
| 11 | **`UnreachableMetric` is extended, not redeclared, and the IR version moves with it.** The draft declared a new dataclass of that name in `evidence.py`; `ir/nodes.py:552` already has one, on `ProjectIR.unreachable` — the very tuple `SpecEvidence` projects. Two same-named public types differing by a field is a trap with no upside, so the IR type gains `via: tuple[str, ...] = ()` and is re-exported. The default does **not** make this free: the encoder writes each dataclass's field *count* and names, so any spec with an unreachable metric re-fingerprints and `bloomery_ir_version` goes 4 → 5. The draft's `name` → `metric` rename was measured at the identical cost; it is dropped for buying only a synonym, not for being expensive. |

## 12. Phasing

Design locked by this RFC; implementation lands as wave **M19**, after RFC 0018's M15
(decision 1 adds root exports, which the signature-closure test must already exist to
police) and preferably after RFC 0020's M17, so `bloomery resolve` is re-pointed rather
than written twice.

Independent of RFC 0019 and RFC 0021.

Within the wave: `SpecEvidence` and the stage-stopping pipeline first (decisions 1–5, 7),
then the CLI re-point (decision 8) as an amendment appended to RFC 0020.
