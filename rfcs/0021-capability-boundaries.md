# RFC 0021 — Capability boundaries: identity resolution, dialects, closed questions

- **Status:** 📝 Draft
- **Scope:** Answering four capability questions that have been carried as open across
  multiple RFCs, and writing the answers down so they stop being carried. Identity
  resolution is **settled as a step, permanently**, and closed with a worked example
  rather than a new spec kind. Dialect coverage beyond the shipped three is **costed and
  left unbuilt**, demand-driven. Incremental-strategy inference is **closed as "no."**
  The Cube emitter's thinness is **recorded as a known asymmetry** in the equivalence
  tier. Adds one fixture, one docs page, and one paragraph of policy; adds no capability.
- **Related:** RFC 0005 (recipes — the compiler validates, never chooses),
  RFC 0008 (`DialectPort`, `Feature`),
  RFC 0009 D24 (the three-way equivalence tier), RFC 0010
  (marts as the gold shape), RFC 0017 (D36/D37 step outputs as entities, D49 `canonical:`
  links — the two mechanisms that make §5.1 work),
  [RFC 0020](0020-authoring-ergonomics.md) (the fixture doubles as a CLI example).
  Closes the original specification's §12 question 4 and RFC 0008 §10's materialization
  question.
- **Adoption audit:** every claim in §3 verified; no corrections were needed.

---

## 1. Summary

Four questions have been carried open across the corpus. Each has an answer available from
mechanisms already shipped; none has been written down, so each is re-litigated whenever it
surfaces.

**Identity resolution** stays a Tier 3 step, permanently — not deferred. RFC 0017 D36/D37
(step outputs synthesized as entities) and D49 (`canonical:` links on wirings) were built
for exactly this shape, and the evidence that it is solved is a worked example, not a new
concept. This RFC ships that example.

**Dialects** beyond DuckDB, Postgres and Trino are costed (~1 week each, Snowflake and
BigQuery being the likely first asks) and left unbuilt until a named consumer needs one.

**Incremental-strategy inference** is closed as "no." The explicit-with-derived-default
that shipped is the answer.

**The Cube emitter** is 281 LOC against SQLMesh's 798 — appropriate for its role, but it
makes the three-way equivalence tier asymmetric, and that asymmetry belongs written down
where a divergence will be triaged.

## 2. Motivation

An open question that is never closed is a recurring tax: it reappears in every planning
conversation, it invites speculative design, and — worst — it reads to a newcomer as a gap
in the library rather than a decision about its boundary.

Identity resolution is the clearest case. It has been deferred through the entire corpus
and is the single most likely thing a reader assumes is missing. It is not missing: the
mechanism exists, has shipped, and has tests. What is missing is a page saying so and a
fixture proving it. **"Deferred" and "solved by an existing mechanism" are materially
different statuses**, and only one of them is true.

The other three follow the same pattern at lower stakes. Writing an answer down — including
"no" and "not until someone asks" — converts a backlog item into a boundary, and boundaries
are what this library trades on.

## 3. Current state

Verified against `main` @ `3da72c5` (2026-08-12):

- **Identity resolution:** no `xref` or identity concept in `spec/`. The step registry
  ships with `sql_macro`, `sql_model` and `python_model` tiers; RFC 0017 D36/D37 synthesize
  step outputs as entities so marts and downstream models reference them; D49 lets a wiring
  declare `canonical:` links per output so metrics and `reconcile` can read them. The
  `step_resolution` fixture exercises the mechanism — but on a generic step, not on identity
  resolution, so nothing demonstrates the pattern the question is actually about.
- **Dialects:** `dialects/{duckdb,postgres,trino}.py` (+ `base.py`). MetricFlow 0.211 ships
  seven renderers — the four unimplemented are Snowflake, BigQuery, Databricks, Redshift.
- **Materialization:** `MaterializationName = Literal["full", "incremental_by_key",
  "incremental_by_partition"]`, explicit with a derived default (RFC 0002). SQLMesh lowering
  maps them to `INCREMENTAL_BY_UNIQUE_KEY` / `INCREMENTAL_BY_TIME_RANGE`.
- **Emitter sizes:** SQLMesh 798, dbt 731, MetricFlow 594, Cube 281 LOC. The three-way
  equivalence tier (RFC 0009 D24) compares MetricFlow-backed planner ↔ Cube ↔ hand-written
  reference SQL over one Postgres; `known_divergences.yaml` ships as `divergences: []`.

## 4. Goals / Non-goals

**Goals**

- Four questions answered in writing, with the reasoning that makes each answer
  re-derivable.
- Identity resolution demonstrated end to end on shipped mechanisms.
- Unbuilt capability costed, so "not yet" is a known quantity rather than an unknown.
- A stated triage order for equivalence-tier divergences.

**Non-goals**

- Building any dialect. This RFC costs them; it does not schedule them.
- Deepening the Cube emitter. Its scope is correct for its role.
- A first-class identity/xref spec concept — §5.1 argues against it.
- Changing `MaterializationName`, the step registry, or any emitter.

## 5. Design

### 5.1 Identity resolution is a step, permanently

**The argument.** Modelling identity resolution declaratively would require bloomery to
model blocking keys, similarity functions, thresholds and transitive closure — none of
which it can typecheck, none of which it can guardrail, and all of which vary per domain.
A spec kind bloomery cannot verify is a spec kind that provides worse guarantees than a
step, because a step at least carries a *declared, runtime-enforced* output contract
(RFC 0017 §6.4).

**The evidence it is already solved.** Three shipped mechanisms compose into exactly the
required shape:

| Need | Mechanism |
|---|---|
| Fuzzy matching bloomery cannot express | Tier 3 `python_model` with a typed manifest contract |
| Two outputs from one computation (`customer`, `customer_xref`) | Multiple declared outputs, one wrapper each (RFC 0017) |
| Marts referencing the resolved entity | D36/D37 — step outputs synthesized as entities |
| Metrics over resolved data | D49 — `canonical:` links declared per output on the wiring |
| Siblings agreeing within one run | The declared cross-output consistency audit (D40/D43/D44) |
| Reproducible backfills | `determinism: pure` + `runtime_lock` in step identity |

That last row is the one that makes identity resolution *safer* as a step than it would be
as a spec kind: `runtime_lock` means a `rapidfuzz` scorer change classifies as `RESTATING`
and backfills the outputs. A declarative similarity function would have no equivalent — the
compiler could not see that the semantics moved.

**What ships:** a fixture and a docs page, no code.

```text
tests/fixtures/identity_resolution/
  catalog.yaml  entity_model.yaml  mapping_crm.yaml  mapping_billing.yaml
  steps.yaml  marts.yaml  metrics.yaml
  registry/resolve_customers/{manifest.yaml, impl.py, fixtures/v1/*.csv}
```

Two sources whose customer records overlap on no shared key, a step producing
`silver.customer` and `silver.customer_xref`, a `references:` declaration between the
siblings, `canonical:` links so `customer_count` resolves, a mart over the resolved entity,
and an `expression` quality rule with `on_fail: fail` asserting `confidence >= 0.8`.

That rule is a good test of RFC 0016 D95's scope check as well: `confidence` is a column
of the step output, unqualified and boolean-compared, so it is exactly what an expression
rule is allowed to read.

It runs in the execution tier and in the `step_resolution` e2e cell — so the pattern is
*proven*, not illustrated. That is the difference between a docs page and a claim.

**Consequence for the platform:** the xref table lives in the step's registry, which is
platform code under RFC 0017's parameterize-never-fork rule. A second tenant needing
different matching sets `threshold: 0.9`; it does not get a forked step.

### 5.2 Dialects: costed, unbuilt

Each unimplemented dialect is a `DialectPort` implementation plus a golden-matrix column
plus an engine-tier cell. MetricFlow already ships the renderer for all four.

| Dialect | MetricFlow renderer | Estimated | Likely trigger |
|---|---|---|---|
| Snowflake | ✔ `snowflake.py` | ~1 week | Enterprise prospect; the most likely first ask |
| BigQuery | ✔ `big_query.py` | ~1 week + | GCP prospect. Costlier: `STRUCT`/`ARRAY` semantics and the partition model differ most from the shipped three |
| Databricks | ✔ `databricks.py` | ~1 week | Existing-lakehouse prospect |
| Redshift | ✔ `redshift.py` | ~1 week | Least likely |

**Policy: demand-driven, on a named consumer, never speculative.** The value of costing
them is that "we don't support Snowflake" becomes "Snowflake is about a week" — a different
answer in a sales conversation, and one that does not require building anything.

Each new dialect must declare its `Feature` set honestly (RFC 0008) rather than
approximating. RFC 0016 D84's Postgres `TRY_CAST` — implemented as a guard around
`pg_input_is_valid` — is the precedent: a dialect that cannot express a feature must say
so and be refused, not silently approximate it. BigQuery is flagged as the one most likely
to need a `Feature` addition rather than only an implementation.

A dialect also inherits the cost questions RFC 0016 D96 raised: whether its regex engine
backtracks decides whether a `pattern` rule can be a denial of service there, and that
belongs in the new dialect's own assessment rather than being assumed from the shipped
three.

### 5.3 Incremental-strategy inference: closed, "no"

The original specification asked whether incremental strategy should be inferred from
grain and partition key rather than declared. **Closed: no.**

`explicit-with-derived-default` already captures the easy case — an entity with a
partition key and a time dimension derives `incremental_by_partition` without the author
writing it. What inference would add is the *hard* case, where the derivation is
ambiguous, and there the failure mode is the one bloomery exists to avoid: a plausible
choice, silently made, producing a wrong backfill scope that surfaces as missing rows.

The general principle, worth stating because it recurs: **bloomery derives defaults; it
does not infer intent.** A default is visible in the compiled output and overridable. An
inference is a guess the author cannot see. RFC 0005 already draws this line for recipes —
the compiler validates a recorded recipe but never chooses one — and this is the same rule
applied to materialization.

Removed from the open list.

### 5.4 The Cube emitter's thinness is a triage note

281 LOC against SQLMesh's 798 is proportionate: Cube is the escape hatch and the
equivalence oracle, not a deployment target, and RFC 0008 D17 (one view per mart) plus
RFC 0017 D52 (Cube builds no relation, so it is asked nothing about steps) mean it
legitimately does less.

But it makes the three-way equivalence tier asymmetric — one mature leg (MetricFlow, 594
LOC, exercised by every planner test), one thin leg (Cube), one hand-written leg
(reference SQL). So:

> **Triage order for an equivalence divergence: suspect the Cube emitter first, the
> reference SQL second, the planner third.**

Written into `tests/equivalence/README` and this RFC. Not a policy about correctness — all
three are tested — but about where to look, and thirty seconds of stated prior beats
thirty minutes of symmetric searching.

`known_divergences.yaml` ships empty and should stay that way; an entry is a finding to
record as an amendment, not a tolerance to accumulate.

### 5.5 The disposition, stated

The four answers share a shape worth naming, because it is the disposition that keeps this
library smaller than the problem it solves:

> **Before adding a spec kind, ask whether it can be a referenced implementation instead
> of a modelled concept.** The step registry exists so the answer can be yes.

§5.1 is that question answered for identity resolution. The test for a future candidate:
*can bloomery typecheck it, guardrail it, and diff it meaningfully?* If not, it is a step —
and a step gives a declared contract, a runtime assertion, `runtime_lock` change
classification, and no compiler surface to get wrong.

## 6. Tests

Per RFC 0009 tiers. This RFC adds one fixture and its coverage; no new library code.

| Tier | Test |
|---|---|
| Golden | `identity_resolution` compiles to SQLMesh + dbt goldens (Cube per D52: asked nothing about steps). |
| Execution | Two sources with overlapping customers and no shared key resolve to one `canonical_id`; `customer_xref` maps both source ids; the cross-output consistency audit passes. |
| Execution | A metric over the step-produced entity resolves through its `canonical:` link — the D49 path, exercised on the case it was built for. |
| Execution | `confidence >= 0.8` with `on_fail: fail` blocks on a seeded low-confidence match. |
| e2e | `identity_resolution` joins the `step_resolution` cell — SQLMesh loads and runs the generated wrappers. |
| Unit | The step's golden fixtures (input CSV → expected outputs) run standalone, with no bloomery, per RFC 0017 §8.8. |
| Docs | The docs page's snippets are extracted from the fixture, not retyped. |

The last row matters: a docs example that drifts from a passing fixture is worse than no
example, because it is trusted.

## 7. Docs

- New `pages/docs/how-to/resolve-identities.md` — the pattern end to end, with a stated
  "why this is a step and not a spec kind."
- `pages/docs/concepts/step-registry.md` — §5.5's question as the test for future
  candidates.
- `pages/docs/reference/spec-schemas.md` — §5.3's derives-defaults-never-infers-intent
  principle at the materialization field.
- `tests/equivalence/README` — the triage order.
- A "supported dialects" note carrying §5.2's cost table, so the answer is public.

## 8. Out of scope

- Building any dialect.
- Deepening the Cube emitter.
- Any identity/xref spec concept.
- Changing `MaterializationName`.
- The platform's own step registry contents — the fixture ships a *demonstration* step,
  not a production one.

## 9. Risks

| Risk | Mitigation |
|---|---|
| A demonstration step is mistaken for a production identity resolver | The docs page and manifest both state it is a fixture: naive blocking, exact-then-fuzzy, no production tuning. Its value is the *wiring*, not the matching. |
| "Demand-driven dialects" becomes "never," and a prospect is lost on a week of work | §5.2 costs them precisely so the decision is a week's scheduling, not an unknown. Revisit at each release. |
| Closing inference forecloses a real ergonomic win | §5.3's principle is the durable part; if a specific inference is later shown safe *and* visible in output, it can be argued as an amendment. The default carries no such burden. |
| The triage order becomes a prior that hides a real planner bug | It orders investigation, not conclusions. Every divergence is still root-caused, and any entry in `known_divergences.yaml` is an amendment. |

## 10. Unresolved questions

None introduced. This RFC closes four:

- Identity resolution — §5.1, settled as a step, permanently.
- Incremental-strategy inference — §5.3, closed "no."
- Dialect coverage — §5.2, demand-driven with published costs.
- Cube emitter depth — §5.4, correct as-is; asymmetry recorded as triage order.

## 11. Decisions

| # | Decision |
| --- | --- |
| 1 | **Identity resolution is a Tier 3 step, permanently — not deferred.** Modelling it declaratively would require blocking keys, similarity functions and thresholds that bloomery can neither typecheck nor guardrail, so a spec kind would give *weaker* guarantees than a step's declared, runtime-enforced contract. RFC 0017 D36/D37 and D49 were built for this shape. |
| 2 | **The evidence is a fixture, not a claim.** `tests/fixtures/identity_resolution/` ships with two no-shared-key sources, a two-output step, a `references:` sibling declaration, `canonical:` links, a mart and a blocking confidence rule — running in the execution tier and the `step_resolution` e2e cell. "Deferred" and "solved by an existing mechanism" are materially different statuses, and only a passing fixture establishes the second. |
| 3 | **`runtime_lock` makes a step safer here than a spec kind would be**: a similarity-library change classifies `RESTATING` and backfills the outputs. A declarative similarity function would have no equivalent — the compiler could not see that the semantics moved. This is the strongest form of decision 1's argument and is recorded separately because it inverts the intuition. |
| 4 | **Dialects are demand-driven on a named consumer, never speculative**, and **costed** at roughly a week each (§5.2), BigQuery costlier. The value of costing is that "we don't support Snowflake" becomes "Snowflake is about a week" without building anything. |
| 5 | **A new dialect declares its `Feature` set honestly or is refused**, never silently approximating. RFC 0016 D84's Postgres `TRY_CAST` — a guard around the engine's own parser rather than an approximation — is the standard, and D96's regex-cost question is part of the same assessment. |
| 6 | **Incremental-strategy inference is closed: no.** The general principle, which recurs: **bloomery derives defaults; it does not infer intent.** A default is visible in compiled output and overridable; an inference is a guess the author cannot see. RFC 0005 draws the same line for recipes — validate a recorded choice, never make one. |
| 7 | **The Cube emitter's scope is correct**; its thinness is recorded as a **triage order** for equivalence divergences — Cube first, reference SQL second, planner third — in `tests/equivalence/README`. It orders investigation, not conclusions. `known_divergences.yaml` stays empty; an entry is an amendment, not a tolerance. |
| 8 | **The disposition is stated as a reusable test** (§5.5): before adding a spec kind, ask whether it can be a referenced implementation instead — *can bloomery typecheck it, guardrail it, and diff it meaningfully?* If not, it is a step. The registry exists so the answer can be yes, and the library stays smaller than the problem it solves. |

## 12. Phasing

Design locked by this RFC; implementation lands as wave **M18**. Independent of RFC 0018,
0019 and 0022 — it touches no public surface, no module layout, and no library code beyond
a fixture. It may execute at any point, including concurrently.

One soft ordering: the `identity_resolution` fixture doubles as RFC 0020's CLI worked
example, so landing it before or with M17 gives that RFC a richer demonstration than
`minimal`. Not a dependency.

Decisions 4–8 are documentation and policy and can land in a single small change ahead of
the fixture.
