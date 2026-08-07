# RFC 0017 — The step registry: referenced implementations

- **Status:** 📝 Draft
- **Scope:** The escape hatch for logic that cannot be declared: the four-tier
  implementation ladder, the `StepManifest` contract, the frozen `StepRegistry`
  compile input (`compile_project` gains a `steps:` parameter), compile-time trust of
  declared outputs with a generated non-optional runtime contract assertion,
  determinism tiers (`nondeterministic` is a compile error), and `runtime_lock` in
  step identity so dependency bumps classify `RESTATING`. New package:
  `bloomery/steps/`. Amends RFC 0003 (`ProjectIR` gains a `steps` tuple —
  fingerprint coverage, §5.6), RFC 0005 (new DAG node kind `step.<ref>`, §5.6), and
  RFC 0007 (RESTATING trigger set); adds three errors to the RFC 0002 hierarchy. Step *bodies* live in the platform repo — never in
  bloomery, never in tenant specs — so this RFC covers the contract surface only.
  Ships as a pair with RFC 0016: the escape hatch is only safe because quality rules
  apply at its boundary.
- **Related:** [`rfcs/_bloomery-quality-and-steps.md`](_bloomery-quality-and-steps.md)
  (Document 5, §6, §8.7–§8.8, §9–§11); RFCs 0002, 0004 (Tier 0), 0007, 0008 (D2
  file-shaped artifacts), 0009 (backfill-equivalence gate), 0016;
  [`src/bloomery/compile.py`](../src/bloomery/compile.py),
  [`src/bloomery/emit/base.py`](../src/bloomery/emit/base.py),
  [`src/bloomery/plan/model.py`](../src/bloomery/plan/model.py).
- **Origin:** Document 5 §6 (its M9.5 slot corresponds to this RFC's M13).

---

## 1. Summary

Some cleansing genuinely is code — entity resolution, fuzzy matching, ML scoring.
RFC 0016's principle still governs: **specs describe, specs reference
implementations, specs never contain implementations.** A step is platform code, in
git, reviewed as code, described by a versioned manifest, referenced from tenant
specs by `use: ref@version`, and wired into the same DAG so lineage, `plan()`
diffing, and backfill still work. Bloomery receives manifests as a frozen
`StepRegistry` compile input (no dynamic loading, ever), trusts declared outputs at
compile time, and emits a wrapper that verifies the declaration at run time with a
non-optional contract assertion. Nondeterministic steps are refused at compile; a
step's pinned dependency hash is part of its identity, so a library bump restates
history exactly like a spec change.

## 2. Motivation

Every platform accumulates cleansing SQL and Python beside the generated models.
Left there, it drifts from the spec and is invisible to `plan()` — a step change
silently skips its backfill, the precise failure RFC 0016 §2 names. Pulled *into*
specs as code blobs, it becomes unreviewable, undeterminable, and an
arbitrary-code-execution surface fed by tenant data. Today `compile_project` has no
step input and the DAG (RFC 0005) cannot represent a node the compiler didn't lower
itself — real requirements ("resolve customers across source systems") have no home
that preserves the restatement guarantee the architecture is organized around.

## 3. Current state

- `compile_project(project, *, target, dialect, naming=None, catalog=None)` — no
  `steps` parameter ([`compile.py`](../src/bloomery/compile.py) ~line 40).
- Artifacts are file-shaped text ([`emit/base.py`](../src/bloomery/emit/base.py));
  `ArtifactKind` is `MODEL | AUDIT | CONFIG` — a generated `.py` wrapper fits `MODEL`
  with a `.py` path, no new kind needed (RFC 0008 D2: artifacts as data).
- `plan()` is shipped (M9): `RESTATING` and `BackfillScope` exist
  ([`plan/model.py`](../src/bloomery/plan/model.py)) — the classifier this RFC hooks
  into is real, so §12's ordering constraint is already satisfied.
- The transform whitelist (RFC 0004) is Tier 0 of the ladder; nothing above it exists.

## 4. Goals / Non-goals

**Goals:** every non-declarative implementation referenced, versioned,
contract-checked, and visible to `plan()`; zero dynamic loading; backfillability
preserved across steps — the load-bearing constraint.

**Non-goals:** hosting or testing step bodies (platform-repo territory, §6 —
bloomery sees manifests and macro bodies only); executing steps (bloomery emits
wrappers; SQLMesh runs them); static analysis of bodies for nondeterminism (caught
behaviorally, §6); sandboxing tenant code (structurally unnecessary — tenants cannot
supply code, D7).

## 5. Design

### 5.1 The four-tier ladder

Rule: **use the lowest tier that works.**

| Tier | Kind | Scope | Bloomery can | Use when |
|---|---|---|---|---|
| 0 | DSL transform | expression | typecheck fully | whitelist covers it (RFC 0004) |
| 1 | `sql_macro` | expression | **parse and typecheck** | one gnarly expression |
| 2 | `sql_model` | table | parse, infer schema | multi-step SQL, windows, recursive CTEs |
| 3 | `python_model` | table | **nothing — trust + verify** | fuzzy matching, ML, genuinely not SQL |

Tier 1 is free at runtime: the macro body is a SQL expression with named parameters;
bloomery parses it with sqlglot and splices it into the generated SELECT — the model
stays one query and column-level lineage sees straight through. Most "we need Python"
requirements turn out to be Tier 1 or 2 on inspection. Tier 3's real costs are named
and paid deliberately: data leaves the engine, becomes memory-bound, and loses
column-level lineage (`lineage: coarse`).

### 5.2 Step manifest

Manifest and body live in the **platform** repo — not in bloomery, not in tenant specs:

```yaml
# steps/resolve_customers/manifest.yaml
ref: resolve_customers
version: 3
kind: python_model                 # sql_macro | sql_model | python_model
entrypoint: platform_steps.resolve_customers:resolve   # python_model only; imported at run time (§5.8)
determinism: pure                  # pure | seeded | nondeterministic
runtime_lock: sha256:a91f…         # hash of the pinned dependency set (§5.6)
inputs:
  raw: {grain: customer_source_row, requires: [source_system, source_id, email, name]}
outputs:
  customer:
    grain: customer
    key: [canonical_id]            # the grain's uniqueness key — what the contract enforces
    produces:
      canonical_id: {type: string, required: true}
      confidence:   {type: decimal(4,3)}
  customer_xref:
    grain: xref
    key: [source_system, source_id]
    produces: {source_system: {type: string, required: true},
               source_id: {type: string, required: true},
               canonical_id: {type: string, required: true}, method: {type: string}}
parameters:
  threshold: {type: decimal, default: 0.85, min: 0, max: 1}
lineage: coarse                    # coarse | column
```

Each output's `key` names the concrete columns over which its grain is unique — the prose
`grain` names the level; `key` is what `assert_step_contract` enforces (§5.4). `entrypoint`
(`"package.module:function"`, `python_model` only) names the platform function the
generated wrapper imports at run time (§5.8); registry build verifies it resolves (§5.3).

A tenant spec wires it and nothing more — `use: ref@version`, input/output bindings,
parameters within declared bounds, and optionally RFC 0016 quality rules on outputs
(the reason the two RFCs ship as a pair — quality applies at the escape hatch's edge):

```yaml
steps:
  - use: resolve_customers@3
    inputs:  {raw: silver.customer_raw}
    outputs: {customer: silver.customer, customer_xref: silver.customer_xref}
    parameters: {threshold: 0.9}
    quality:
      - {rule: expression, expr: "confidence >= 0.8", on_fail: flag, applies_to: customer}
```

### 5.3 Purity: the registry is a compile input

Bloomery must not read step files from disk — that breaks hard invariant #1. The
caller assembles:

```python
@dataclass(frozen=True)
class StepRegistry:
    steps: Mapping[tuple[str, int], StepManifest]   # (ref, version) -> manifest
    macro_bodies: Mapping[tuple[str, int], str]     # sql_macro bodies, for parsing
    sql_bodies: Mapping[tuple[str, int], str]       # sql_model bodies, parsed at compile like macro_bodies

def compile_project(project, *, target, dialect, naming=None, catalog=None,
                    steps: StepRegistry = EMPTY_REGISTRY) -> tuple[EmittedArtifact, ...]: ...
```

A spec referencing `resolve_customers@3` when the registry holds only `@2` — or
nothing — is `UnknownStep` at compile time, **naming the available versions**. There
is **no dynamic loading path**: no import hooks, no entry points, no paths in specs.
That absence is what keeps tenant specs from ever becoming an
arbitrary-code-execution surface. The rule's scope is **compile time**: bloomery never
imports or executes step code while compiling — it consumes manifests and SQL text,
nothing else. Runtime import of platform-owned code by the generated model (§5.4's wrapper
importing the manifest `entrypoint`) is the normal SQLMesh execution path, not an
exception; and registry **build** — caller-side tooling — verifies each `entrypoint`
resolves before the registry ever reaches `compile_project`.

The constructor snapshots its mappings into an immutable, canonically sorted internal form
(tuple-of-pairs over a copied dict) at construction: mutating a caller's dict after
construction cannot affect compilation, and byte-identical compilation is guaranteed from
the snapshot alone.

### 5.4 Trust the declaration, verify at runtime

Bloomery cannot infer a Python function's output schema, so: **compile time** trusts
`outputs.*.produces` and typechecks downstream models against it — the DAG stays
complete and `plan()` computes backfills across the step; at **run time** the
generated wrapper asserts reality matches the declaration:

```python
# generated python_model wrapper (an EmittedArtifact, models/silver/customer.py)
@model("silver.customer", kind="FULL", columns={...from manifest...})
def execute(context, **kwargs):
    from platform_steps.resolve_customers import resolve  # manifest `entrypoint`, imported at run time
    raw = context.fetchdf("SELECT * FROM silver.customer_raw")
    out = resolve(raw, threshold=Decimal("0.9"))
    assert_step_contract(out, MANIFEST)     # generated — not optional, not configurable
    return out["customer"]                  # this wrapper's declared output; customer_xref has its own (§5.8)
```

`assert_step_contract` checks, in order: every declared output present; no undeclared
outputs; column set matches exactly; types assignable; `required: true` columns
null-free; declared grain unique — uniqueness enforced over the output's declared
`key` columns (§5.2). **The assertion is non-optional and
non-configurable** — without it, `produces` decays into stale documentation within a
quarter: a claim that is checked is a commitment, a claim that isn't is a comment.
The checker lives in `bloomery/steps/contract.py`, a dependency-light module the
generated wrapper imports at target runtime (the only bloomery module intended for
import outside compilation). pandas does **not** join bloomery's runtime
dependencies: `contract.py` is emitted-code-facing and imports pandas lazily, inside
the generated wrapper's runtime path only; callers executing `python_model` steps
install the `bloomery[steps]` extra (pandas and nothing else), and compile-time use
of the registry needs no pandas. New errors, declared in `errors.py` per RFC 0002 D3:
`UnknownStep` (compile), `StepDeterminismError` (compile), `StepContractViolation`
(runtime, raised only by generated code).

### 5.5 Determinism tiers

| Tier | Meaning | Bloomery behaviour |
|---|---|---|
| `pure` | same inputs → byte-identical outputs | backfillable freely |
| `seeded` | deterministic given an explicit seed | seed **required** in the spec wiring (`StepDeterminismError` if absent); recorded |
| `nondeterministic` | reads clock, network, or unseeded RNG | **compile error** (`StepDeterminismError`) |

A nondeterministic step makes backfills disagree with original runs, which destroys
the ability to restate — the one capability the whole architecture is organized
around. Refusing it is not conservatism; it is the load-bearing constraint.

### 5.6 Runtime pinning

A step's behaviour depends on its libraries — `rapidfuzz` changing a scorer between
minor versions silently changes entity-resolution output, and nothing in any spec
would show it. `runtime_lock` (a hash of the step-runtime dependency set, computed at
registry build time) is **part of step identity**: a dependency bump changes the step
fingerprint, which `plan()` classifies `RESTATING`, which triggers a backfill
(RFC 0007 amendment, appended when this ships). Correct behaviour, and invisible
without the lock.

The mechanism, precisely — this is how `plan()` sees a step change without
special-casing. Steps enter the IR as `StepIR` nodes (`ref`, `version`, `kind`,
`determinism`, `runtime_lock`, typed inputs/outputs — plus the **resolved parameters** as
canonically sorted `(name, value)` pairs with `Decimal`-as-str per the canon-bytes
doctrine, the recorded **seed** for seeded steps, and the input/output **wiring** as sorted
pairs) and the resolution DAG as
first-class nodes — an RFC 0005 amendment adds the node kind `step.<ref>`. That makes
them fingerprint-covered: an RFC 0003 amendment gives `ProjectIR` a `steps` tuple, so
any manifest change — including `runtime_lock` alone — changes `project_fingerprint`,
and `plan()` sees it as an ordinary structural IR diff; a parameter, seed, or wiring
change in the tenant spec is therefore a `RESTATING` diff exactly like a `runtime_lock`
bump. The hydration cache
(RFC 0014) self-invalidates by the same route: `HydrationKey.spec_fingerprint` shifts
automatically, so no new key component is needed — stated explicitly because it is
the part that would otherwise look like an omission.

### 5.7 Multi-tenant rule: parameterize, never fork

Steps are platform code. A tenant configures parameters; a tenant never supplies a
body. When a tenant needs something the library can't do, the step is generalized
into a parameterized form — never `resolve_customers_acme`. A requirement that
genuinely cannot generalize is a useful signal: it is bespoke consulting, not
product; knowing that explicitly beats discovering it in a directory of
near-identical step files. The payoff is the compounding-library loop: "tenant 1
needs custom matching → a parameterized step is written → tenant 2 sets
`threshold: 0.9` and reuses it. The library grows; the bespoke surface shrinks."

### 5.8 Emission and the DAG

`sql_macro` splices into the entity SELECT — still one query, lineage-transparent.
`sql_model` emits an ordinary model artifact from the registry `sql_bodies` entry (parsed
at compile like `macro_bodies`, schema-checked against `produces`). `python_model` emits a
**generated** SQLMesh
Python-model artifact — `.py` text, consistent with RFC 0008 D2's file-shaped
artifacts — importing the manifest `entrypoint` at run time and wrapping it with the §5.4
contract assertion.

**Multi-output emission** (resolved; supersedes the draft's execute-exactly-once
constraint — see decision 16): each declared output gets its **own generated wrapper
model**; each wrapper imports the entrypoint, executes the step, and returns its own
output. Re-execution across the output models is semantically safe **by construction**:
nondeterministic steps are compile-refused and seeded steps re-execute with the same
recorded seed, so pure/seeded ⇒ identical results. `assert_step_contract` runs in
**every** wrapper against **all** declared outputs — cheap, and it catches a
partial-output lie wherever the run starts. The cost — N executions for N outputs — is
documented; a single-execution staging optimization is a demand-gated, named escape
hatch, not built.

Step
outputs are entities in the DAG, grain taken from the manifest: downstream mappings,
marts, and metrics reference them like any silver entity, and RFC 0016 quality rules
attach at that boundary. Two steps declaring the same output relation is a compile
error (settles Document 5 §11.5 — explicitly refused, not implicitly assumed).

## 6. Tests

- **The adversarial fake-step battery** (Document 5 §8.7) — every liar fails loudly:
  extra column, omitted column, wrong type, null in `required`, duplicate grain keys,
  undeclared output table → each a named `StepContractViolation` at run time.
- **Nondeterminism is caught behaviorally**: a fake step reading `datetime.now()`
  passes the contract check but fails RFC 0016's backfill-equivalence merge gate —
  static analysis of bodies is explicitly out of scope, which is why that gate must
  stay merge-blocking.
- **Step golden fixtures live in the platform repo**, versioned with the step
  (`fixtures/v3/input_raw.csv`, `expected_*.csv`), runnable with no tenant, no
  catalog, no bloomery. Out of bloomery's suite; the registry owner's documented
  obligation, with the review rule: **a version bump requires new fixtures** — a `@4`
  reusing `@3`'s expected outputs is a review failure, because unchanged outputs
  should not have been a version bump.
- Bloomery-side units: `UnknownStep` naming available versions,
  `StepDeterminismError` both arms, wrapper-artifact goldens per kind, macro splice
  parse/typecheck, duplicate-output refusal.

## 7. Docs

A how-to on the migration path (Document 5 §9): **wrap, don't refactor** (manifest,
register `@1`, `lineage: coarse`, claim `pure` and *verify* it via the
backfill-equivalence gate rather than assuming) → get it into the DAG (`plan()` sees
it, backfills stop being manual) → push down the ladder (most SQL scripts collapse to
Tier 2; a surprising number of Python ones are Tier 1 expressions wearing a
dataframe) → extract declared rules as you go. The ladder explanation names Tier 3's
real costs; the reference page states parameterize-never-fork as policy.

## 8. Out of scope

- **A step SDK / decorator package** (`@step(...)`) — platform-repo tooling; bloomery
  consumes manifests, not decorators. Escape hatch: extract `steps/contract.py` into
  a micro-package if the runtime-import dependency chafes.
- **Registry build tooling** (computing `runtime_lock`, validating fixtures) — the
  registry owner's; bloomery validates what it is handed.
- **Steps depending on steps** — a step's inputs are entities; chains already express
  themselves through the DAG.

## 9. Risks

- *`produces` drift between manifest and body* — the exact risk the non-optional
  runtime assertion exists for; residual window is one run, not one quarter.
- *Runtime-import coupling*: generated wrappers import `bloomery.steps.contract`, so
  the step runtime must have bloomery installed. Accepted — dependency-light by
  construction; the §8 escape hatch is named.
- *Ladder erosion* — everything lands as Tier 3 because it's easiest. Mitigated by
  review policy (lowest tier that works) and Tier 3's visible costs.
- *Seeded steps misdeclared as `pure`* — caught behaviorally by the
  backfill-equivalence gate, not before one bad backfill; accepted, stated in docs.

## 10. Unresolved questions

- Exact `StepManifest` Pydantic surface (parameter-bounds grammar, `requires`
  strictness) — implementation settles within §5.2's shape.
- Whether `sql_model` bodies take parameters via Jinja or sqlglot placeholder
  substitution — implementation settles; RFC 0013's injection-boundary lesson (fuzz
  the boundary) applies either way.

## 11. Decisions

| # | Decision |
| --- | --- |
| 1 | Four-tier ladder — DSL transform → `sql_macro` (parsed + typechecked, spliced into the SELECT, lineage-transparent) → `sql_model` (parsed, schema inferred) → `python_model` (trust + verify) — with the rule: **lowest tier that works**. Tier 3's costs (data leaves the engine, memory-bound, coarse lineage) are named, not hidden. |
| 2 | `StepManifest` per §5.2: `ref`, `version`, `kind`, `determinism`, `runtime_lock`, typed `inputs`/`outputs` with grain + `key` (the grain's uniqueness columns) + `produces`, bounded `parameters`, `lineage: coarse\|column`. Step bodies live in the platform repo — never in bloomery, never in tenant specs; tenant specs wire `use: ref@version` + bindings + parameters + optional RFC 0016 quality rules on outputs. |
| 3 | `StepRegistry` is a frozen compile **input** (steps mapping + macro bodies), assembled by the caller; `compile_project(..., steps: StepRegistry = EMPTY_REGISTRY)`. Unknown ref or version → `UnknownStep` naming available versions. **No dynamic loading path exists** — tenant specs can never become an arbitrary-code-execution surface. |
| 4 | Trust-then-verify: compile time trusts `produces` (DAG complete, downstream typechecked, `plan()` computes backfills across the step); the generated wrapper carries a non-optional, non-configurable `assert_step_contract` (outputs present, none undeclared, exact column set, assignable types, required-null check, grain uniqueness over the output's declared `key`). A claim that is checked is a commitment; a claim that isn't is a comment. New errors: `UnknownStep`, `StepDeterminismError` (compile), `StepContractViolation` (runtime, raised by generated code). |
| 5 | Determinism tiers: `pure` (freely backfillable) \| `seeded` (seed required in the spec, recorded) \| `nondeterministic` (**compile error**). Restatement is the organizing capability of the architecture; refusing nondeterminism is the load-bearing constraint, not conservatism. |
| 6 | `runtime_lock` is part of step identity: a dependency bump changes the step fingerprint and classifies `RESTATING`, triggering backfill (RFC 0007 amendment). Invisible — and wrong — without the lock. |
| 7 | Multi-tenant rule: **parameterize, never fork.** Tenants configure parameters, never supply bodies; a requirement that cannot generalize is bespoke consulting, not product. The compounding loop (tenant 1's need → parameterized step → tenant 2 reuses) grows the library and shrinks the bespoke surface. |
| 8 | Emission: `sql_macro` splices into the entity SELECT (one query); `sql_model` emits an ordinary model artifact from the registry body; `python_model` emits a generated SQLMesh Python-model `.py` artifact (RFC 0008 D2 file-shaped) wrapping the impl + contract assertion. Step outputs are DAG entities with manifest grain; two steps writing one output is a compile error (settles Document 5 §11.5). |
| 9 | Testing: the §8.7 adversarial fake-step battery (every liar fails loudly); nondeterminism caught behaviorally by the backfill-equivalence gate (static analysis out of scope, stated); step golden fixtures live in the platform repo under the version-bump-requires-new-fixtures review rule — the registry owner's obligation, documented as such. |
| 10 | Migration path (Document 5 §9): wrap with a manifest → into the DAG → push down the ladder → extract declared rules. Shipped as the how-to, not tooling. |
| 11 | Steps are IR and DAG citizens: `StepIR` nodes (ref, version, kind, determinism, `runtime_lock`, typed inputs/outputs) in a new `ProjectIR.steps` tuple (RFC 0003 amendment) and first-class `step.<ref>` DAG nodes (RFC 0005 amendment). Fingerprint coverage is the whole mechanism: any manifest change — `runtime_lock` included — shifts `project_fingerprint`; `plan()` sees an ordinary structural IR diff (no special-casing); the RFC 0014 hydration cache self-invalidates via `HydrationKey.spec_fingerprint`, no new key component. |
| 12 | pandas never joins bloomery's runtime dependencies: `bloomery/steps/contract.py` is emitted-code-facing and imports pandas lazily inside the generated wrapper's runtime path only; callers executing `python_model` steps install the `bloomery[steps]` extra (pandas and nothing else); compile-time use of the registry needs no pandas. |
| 13 | Implementation binding: `StepRegistry` gains `sql_bodies: Mapping[tuple[str, int], str]` (`sql_model` bodies, parsed at compile like `macro_bodies`); `StepManifest` gains `entrypoint: str` (`"package.module:function"`) for `python_model`, and the generated wrapper imports it at **run time**. The no-dynamic-loading rule is scoped to compile time — bloomery never imports or executes step code while compiling (manifests and SQL text only); runtime import of platform-owned code by the generated model is the normal SQLMesh execution path, and registry build (caller-side) verifies the entrypoint resolves. |
| 14 | `StepRegistry` snapshots its mappings into an immutable, canonically sorted internal form (tuple-of-pairs over a copied dict) at construction — mutation of caller dicts after construction cannot affect compilation; byte-identical compilation is guaranteed from the snapshot. |
| 15 | `StepIR` additionally carries the resolved parameters (canonically sorted `(name, value)` pairs, `Decimal`-as-str per canon-bytes), the recorded seed for seeded steps, and the input/output wiring (sorted pairs) — all fingerprint-covered, so a parameter or seed change is a `RESTATING` diff exactly like a `runtime_lock` change. |
| 16 | Multi-output emission resolved — **supersedes the draft §10 entry and its execute-exactly-once constraint** (recorded honestly: that constraint is dropped, not satisfied): each declared output gets its own generated wrapper model, each executing the step and returning its own output; safe by construction because nondeterministic steps are compile-refused and seeded steps re-execute with the same recorded seed (pure/seeded ⇒ identical results). `assert_step_contract` runs in every wrapper against **all** declared outputs, catching partial-output lies wherever the run starts. The N-executions-for-N-outputs cost is documented; a single-execution staging optimization is a demand-gated, named escape hatch — not built. |

## 12. Phasing

Lands as **M13**, after RFC 0016 (M12) — quality rules must exist before the escape
hatch they guard — and depending on shipped `plan()`: the `RESTATING` machinery
exists since M9, so Document 5's "build steps after the classifier" rule is already
satisfied (its M9.5 label corresponds to this milestone). Order within M13: manifest
models + `StepRegistry` + `UnknownStep`/determinism checks; the three emission kinds
with wrapper goldens; then the `runtime_lock`/`plan()` amendment. Done when all §8.7
adversarial steps are refused loudly, a `runtime_lock` bump alone produces a
`RESTATING` plan, and step goldens are green in the platform repo.
