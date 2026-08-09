# RFC 0017 — The step registry: referenced implementations

- **Status:** ✅ Complete
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
(tuple-of-pairs over a copied dict) at construction, and `StepManifest` — with every type
it nests (inputs, outputs, parameters) — is itself a frozen model, so the shallow snapshot
is sufficient: the copied structure blocks dict-level mutation, and frozen leaves block
value-level mutation. Together (and only together) they make compilation independent of
anything the caller does after construction; a snapshot over mutable manifests would not.

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
output. Re-execution across the output models is semantically safe **for correctly
declared steps**: nondeterministic steps are compile-refused and seeded steps re-execute
with the same recorded seed, so pure/seeded ⇒ identical results. **Residual risk, stated
honestly:** the determinism declaration is trusted at compile and caught *behaviorally*
(§6's backfill-equivalence gate), so a step misdeclared as pure can slip through — and
where exactly-once would still have produced one internally consistent result per run,
N independent executions can produce *disagreeing sibling outputs within a single run*
(e.g. a `customer_xref` that references canonical ids the `customer` execution never
minted), which a per-table gate does not detect. Accepted for v1 with the mitigation
named: a cross-output referential consistency audit between sibling step outputs is the
demand-gated companion of the staging optimization — either lands if misdeclaration is
observed in practice. *(Amended by D40: the audit is built. The staging
optimization is not.)* `assert_step_contract` runs in **every** wrapper against **all**
declared outputs — cheap, and it catches a partial-output lie wherever the run starts.
The cost — N executions for N outputs — is documented; a single-execution staging
optimization is a demand-gated, named escape hatch, not built.

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
- ~~Whether `sql_model` bodies take parameters via Jinja or sqlglot placeholder
  substitution~~ — **settled 2026-08-09 by D47: sqlglot placeholders.** Left open, it
  was not a choice pending a decision but a silent hole: nothing substituted, and
  nothing refused a body that expected it.

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
| 14 | `StepRegistry` snapshots its mappings into an immutable, canonically sorted internal form at construction, **and** `StepManifest` plus every nested type is frozen — the shallow snapshot blocks dict-level mutation, frozen leaves block value-level mutation; byte-identical compilation follows from the two together (a snapshot over mutable manifests would not suffice). |
| 15 | `StepIR` additionally carries the resolved parameters (canonically sorted `(name, value)` pairs, `Decimal`-as-str per canon-bytes), the recorded seed for seeded steps, and the input/output wiring (sorted pairs) — all fingerprint-covered, so a parameter or seed change is a `RESTATING` diff exactly like a `runtime_lock` change. |
| 16 | Multi-output emission resolved — **supersedes the draft §10 entry and its execute-exactly-once constraint** (recorded honestly: that constraint is dropped, not satisfied): each declared output gets its own generated wrapper model, each executing the step and returning its own output; safe **for correctly declared steps** — nondeterministic steps are compile-refused and seeded steps re-execute with the same recorded seed (pure/seeded ⇒ identical results); residual risk recorded: a *misdeclared* step slips the compile check and, under N executions, can produce disagreeing sibling outputs within one run (behavioral gates catch run-to-run, not intra-run, divergence) — accepted for v1, with a cross-output consistency audit named as the demand-gated mitigation. `assert_step_contract` runs in every wrapper against **all** declared outputs, catching partial-output lies wherever the run starts. The N-executions-for-N-outputs cost is documented; a single-execution staging optimization is a demand-gated, named escape hatch — not built. |

| 17 | *(2026-08-08, M13; scope only — D39 refuses all of them for now)* **Step-output quality rules are `expression` only.** §5.2's example shows one, and the other entity-level kind — `referential` — cannot be expressed here: it is identified by a `via` naming a relationship the entity model declares *between entities*, and a step output only becomes an entity as the step is lowered, so there is no relationship to name. It also carries no `name` for `applies_to` to key on. Widening this is an RFC amendment, not config (RFC 0016 D5's closed-catalogue discipline). |
| 18 | *(2026-08-08, M13)* **Three refusals the RFC implies without spelling.** (a) An output `key` naming a column the step does not `produce` is refused at manifest parse: `assert_step_contract` groups by that key, so the assertion would have nothing to run on. (b) A `sql_macro` declaring more than one output, or an output of more than one column, is refused: §5.1 says Tier 1 splices into a SELECT *as an expression*, and an expression is one value — such a manifest is a Tier 2 step wearing the wrong kind. (c) A seed on a `pure` step is refused: §5.5 requires a seed for `seeded` and says nothing about the converse, but silently ignoring a seed leaves an author believing something is pinned that is not, which is the same failure the tiers exist to prevent. |
| 19 | *(2026-08-08, M13)* **A Tier 1/2 body is parsed at lowering, not at emit.** §5.8 says bodies are parsed at compile; doing it during lowering rather than during emission makes an unparseable body a compile error naming the step, instead of a broken artifact an engine discovers later. It is also what makes the splice possible at all — an expression must be an AST before it can be substituted into a SELECT. The canonicalized body is carried on `StepIR` rather than read from the registry at emit, because the import contract bars emitters from the spec and registry layers (RFC 0008): a body the emitter needs arrives through the IR or not at all. |
| 20 | *(2026-08-08, M13)* **`StepParameterIR` carries the declared type beside the value.** D15 says parameters are stringified `(name, value)` pairs so canon bytes never meet a float — correct for the *fingerprint*, and insufficient for *emission*: the generated wrapper has to call the step body with a real `Decimal`, `int` or `str`, and only the declared type says which. Inferring it from how the digits look would make `"0.9"` and `"09"` a guessing game. Found by reading an emitted wrapper, where `threshold` was being passed as the string `"0.9"`. |
| 21 | *(2026-08-08, M13)* **`render_type` is promoted to the type layer, one spelling for three consumers.** The step manifest a wrapper embeds records declared types as text, and `contract.py` looks them up in a table. Emitting `repr(logical_type)` — `StringType()` — matched nothing in that table, so every type check silently passed: a mandatory assertion degraded to a no-op with every test green. The spelling `plan()` already had privately is now `bloomery.typing.render_type`, and `plan/diff.py` delegates to it, so the two cannot drift again. |
| 22 | *(2026-08-08, M13)* **§9's "dependency-light by construction" was untrue as laid out, and is partly repaired.** Measured: `import bloomery.steps.contract` cost ~400 ms and 1011 modules, pulling in metricflow, jinja2, sqlglot, pydantic and yaml — because importing a submodule executes its parent packages' `__init__` first, and bloomery's top-level one imports the whole compile surface. A package-wide lazy `__getattr__` (PEP 562) fixed it completely — 6.5 ms, 55 modules, no heavy dependencies — and was **reverted**: `plan` and `resolve` are both public functions *and* submodule names, so once the submodule is imported the module attribute shadows the function and `from bloomery import plan` returns a module. Import-order-dependent silent breakage is worse than a slow import. Kept: the collision-free half, a lazy `bloomery.steps`. The remaining cost is §8's named escape hatch (extract `contract.py` into a micro-package), still not built; recorded here so the claim in §9 is not read as satisfied. |
| 23 | *(2026-08-08, M13)* **`contract.py` imports no pandas at all — stronger than D12.** D12 budgets for a lazy import inside the runtime path. In fact every check is expressible against the dataframe protocol the step already returned (`.columns`, `.dtype`, `.isna()`, `.duplicated()`), so the checker works on whatever frame it is handed and never names the library that made it. Consequence, recorded rather than papered over: the `bloomery[steps]` extra D12 specifies (pandas and nothing else) is **not added**, because nothing in bloomery would import it — a step body gets its dataframes from SQLMesh, which depends on pandas already. An extra installing a dependency nothing requires is cruft; if a caller ever executes a `python_model` outside SQLMesh, that is when the extra earns its place. |
| 24 | *(2026-08-08, M13)* **Steps diff by `ref`, not by `ref@version`.** Keyed by version, upgrading `resolve_customers@3` to `@4` would read as one step removed and a different one added — losing the backfill precisely where a version bump matters most. Keyed by ref it is one RESTATING change carrying `@3 → @4`, and the step's output relations enter `backfill_scope`. The `step.<ref>` DAG node is keyed the same way and for the same reason: a version bump must not move the node, or the lineage the node exists to preserve breaks on every upgrade. Removing a step is BREAKING and names the relations nothing produces afterwards. |

| 25 | *(2026-08-08, M13 self-audit)* **The generated wrapper is an escaping boundary, and it leaked.** Parameter values were interpolated into Python source by hand, so an authored `label: 'ACME" + __import__("os").getcwd() + "'` emitted a live expression that parsed and ran — D3's promise ("a spec can never become an arbitrary-code-execution surface") broken by the one component that writes executable text. Every literal is now built with `repr()` over canonically sorted structures: parameter values, parameter *names*, input names and bound relations alike. The old `json.dumps`-then-patch-`true`/`false`/`null` helper went with it — it edited string *contents*, so a column named `id, null` reached the wrapper as `id, None` and a **correct** step failed its own contract at run time, with the wrapper still parsing and every `ast`-based test green. |
| 26 | *(2026-08-08, M13 self-audit)* **Refuse what is not built: `sql_macro` and step-output quality rules.** Tier 1 has no spec surface referencing a macro step, so a wired `sql_macro` bound an output and emitted nothing at all while the docs said its body was spliced into a SELECT. Quality rules on outputs parsed and were consumed by nothing — an author would write a rule, get no rule, and get no error, which is the worst possible failure for a feature whose job is catching bad data. Both are now named compile refusals. A Tier 2 step with no registry body is refused too: it previously emitted a `MODEL` with an empty `SELECT`, which is D19's own point turned inside out. |
| 27 | *(2026-08-08, M13 self-audit)* **A wrapper must declare its dependencies the way SQLMesh reads them.** The emitted model hardcoded `context.fetchdf("SELECT * FROM silver.customer_raw")`; SQLMesh infers a Python model's dependencies only from `context.table(...)`, so the step sat unordered in the DAG *and* the literal name resolved to the production view rather than the environment's snapshot — a dev backfill would silently read prod. Now `context.fetchdf(f"SELECT * FROM {context.table('…')}")`. This is §4's "backfillability preserved across steps" failing at the one place it is actually executed. |
| 28 | *(2026-08-08, M13 self-audit)* **Collisions are compared on the *emitted* relation, and entities count.** The duplicate check compared authored bindings, so `a.customer` and `b.customer` — different strings, one emitted model — both passed and produced two files at one path. A step output colliding with an **entity** of the same name was not checked at all. Both are refused now, and a step that failed another check still contributes its claims, because skipping it meant an author fixed a determinism error, re-ran, and only then learned two steps claim one relation: the second round-trip the batching exists to prevent. |
| 29 | *(2026-08-08, M13 self-audit)* **An unknown declared type is a contract violation, not a skip.** `_KIND_BY_TYPE` had no `decimal` entry and its absence did not fail — the lookup returned `None` and the check was skipped, so the RFC's own flagship column (`confidence: decimal(4,3)`) accepted a `datetime64` silently. Precisely the failure D21 records, one type short of it. `decimal` is added *and* an unrecognised base type now raises, so the next gap fails loudly instead of passing. |
| 30 | *(2026-08-08, M13 self-audit)* **Three smaller refusals and one correction.** (a) An input and a parameter sharing a name is refused at manifest parse: the wrapper calls `step(**inputs, **parameters)`, so it was a run-time `TypeError` decidable from the manifest alone; non-identifier names likewise. (b) Non-finite parameter values (`NaN`, `sNaN`) construct as `Decimal` and raise on *comparison*, so `InvalidOperation` escaped `compile_project` — a non-`BloomeryError` crossing the boundary, which RFC 0002 forbids. (c) Bound, binding and duplicate-relation failures raised `UnknownStep`, whose declared meaning is "the registry does not hold this `ref@version`"; they raise `StepError` now. (d) §5.2's own worked manifest writes `{type: decimal, default: 0.85}`, which the implementation rejected and the fixture corpus quietly worked around with `decimal(4,3)` — a bare `decimal` is now accepted for a *parameter*, which is a scalar knob rather than a stored column. |
| 31 | *(2026-08-08, M13 self-audit)* **Steps are refused on dbt and Cube rather than dropped, and the DAG edges were fiction.** `step_artifacts` is wired into the SQLMesh emitter only; the other two targets emitted no step artifacts and no error, silently withholding relations downstream models were typechecked against — now `UnsupportedByTarget` (RFC 0008 D3: fail loud, never approximate). Separately, step edges hung off a synthetic `<entity>.*` node that no other producer or consumer ever creates, so the "upstream reaches it in topological order" claim was false and the node only detected self-loops. Input edges now come from every field of the named entity, output edges from the step's produced columns. |

| 32 | *(2026-08-08, M13 re-audit)* **D25's injection fix was incomplete: the *output* binding was still raw.** D25 claimed every literal went through `repr()`; parameter values, parameter names and input names did, and the output relation did not — it was interpolated straight into `@model("…")`. An authored `outputs: {customer: 'x", print(…))\n@model("y'}` produced a wrapper that **parsed**, carried a second decorator and executed at model import; the same binding injected a `DROP TABLE` into a `sql_model` artifact, and the artifact *path* carried a newline. Fixed with two independent locks, because one lock that is believed to hold is how this reached a second audit: `RELATION_PATTERN` constrains bound relations at the spec layer, and the emitter escapes the relation and the output name regardless. Manifest output names are constrained to identifiers for the same reason — they reach `return outputs[…]` and the wrapper docstring. The lesson recorded rather than the fix alone: a component that writes executable text has exactly one escaping boundary, and *every* value crossing it must go through the same function, not the ones the author of the fix happened to think of. |
| 33 | *(2026-08-08, M13 re-audit)* **The D31 graph rewrite silently removed cross-step cycle detection — a regression the fix wave introduced.** Drawing input edges from real entity fields fixed the synthetic-node problem D31 describes and broke the case that actually matters: a step reading *another step's output* found no entity, drew no edge, and two steps in a mutual loop compiled clean. Before the rewrite the (wrong) wildcard node caught it by accident. Steps now resolve producer-of-relation first, so a step→step dependency is a real edge and a loop is `CircularDerivation: step.s → step.t → step.s`. This is the second time on this project that a fix wave introduced a defect its own audit had to find; the re-audit is the practice that catches it, not the care taken while fixing. |
| 34 | *(2026-08-08, M13 re-audit)* **Parameter values are type-checked at lowering, and the input relation goes through the naming policy.** The emitter rebuilds a real `int`/`Decimal`/`date` from the IR's text, so an unparseable value surfaced as a bare `ValueError` out of `int()` — a non-`BloomeryError` crossing the compile boundary that D30(b) had just been written to prevent — or, for the temporal constructors, as an exception at model *import*. Manifest **defaults** took the same path. Separately, D27 routed the wrapper's read through `context.table(...)` but passed the *authored* binding, so under a scoping naming policy the wrapper wrote `acme_silver.customer` and read plain `silver.customer_raw`: two relations, one of which may not exist. Both are now checked and routed where the corresponding output already was. |
| 35 | *(2026-08-08, M13 re-audit)* **Three smaller repairs, and a vacuous test replaced.** The dbt and Cube step guards were inserted *above* their `emit` docstrings, demoting each to a dead expression (`__doc__` was `None`). A body-parse failure dropped its relation claims — the same second-round-trip hole D28 closed elsewhere — and still raised `UnknownStep` for a step the registry *did* resolve. And `test_a_python_model_never_reaches_a_sql_harness` named `execution.materialize` in its docstring, never called it, and passed with the filter it existed to protect reverted; it now drives the real harness and asserts nothing was created. A test that names the thing it protects without exercising it is worse than no test, because it reads as coverage. |

| 36 | *(2026-08-08, M13; narrowed by D41)* **Step outputs are entities, as §5.8 always said — now actually.** Outputs previously lived only inside `StepIR`, so §5.8's "downstream mappings, marts, and metrics reference them like any silver entity" and §5.4's "downstream models are typechecked against `produces`" were both untrue: a mart over a step output was refused with *"mart base names entity 'customer', which no mapping lowers"*. `build_project_ir` now synthesizes one `EntityIR` per output. Three fields have no natural value and are **chosen**, recorded rather than left to be discovered: `source` names the relation the step itself writes (an entity's `source` is mandatory and a step has no bronze one — this is the honest reading, since that is where the rows come from as far as anything downstream can tell); `materialization`/`scd` are `FULL`/`TYPE1`, matching what the wrapper already declares, because an IR disagreeing with its own artifact is worse than an arbitrary-but-consistent choice; and each column's `expr` is the column referring to itself, which is what a downstream model selecting from the relation would emit anyway. |
| 37 | *(2026-08-08, M13)* **`EntityIR.produced_by` marks a step-written entity, and the emitter skips it.** The entity exists so the rest of the compiler can reference it; the relation is written by the step's generated wrapper. Without the marker the emitter's entity loop would emit a *second* model at the same path — precisely the two-writers-one-relation collision D28 refuses everywhere else, arrived at from the inside. |
| 38 | *(2026-08-08, M13)* **The plan double-report question, settled by measurement rather than by argument.** Synthesizing entities raised the worry that every step change would report twice. It does not, and the split is the useful one: *presence* changes report both (`step:resolve_customers` **and** `entity:customer` + its fields) because new relations genuinely did appear and a reader needs their columns before applying; a `runtime_lock` bump reports **only** the step, because the synthesized entity is byte-identical across it. `plan(ir, ir)` stays empty, so RFC 0007 D2's identity property survives the new entity kind. |
| 39 | *(2026-08-08, M13)* **Quality rules on step outputs stay refused, and synthesizing entities does not change that.** It was tempting to read D36 as unblocking them, since the rules now have an entity to attach to. They still cannot lower: RFC 0016's dispositions compile into a silver **SELECT** (`_quality_flags`, the routing `WHERE`, the coercible marker over transform chains), and a step-produced relation has no SELECT — the wrapper writes it in Python. The tractable subset would be `on_fail: fail`, which *would* lower to an audit over the relation rather than into its projection; `flag` and `quarantine` would not, and shipping a rule kind that works for one disposition and silently does nothing for the other two is worse than the refusal. So the shipped contract is the simple one — **every** quality rule on a step output is a compile error, whatever its `on_fail` — and the `fail`-only subset is named as the next increment, not built. |

| 40 | *(2026-08-08, M13; detection mechanism superseded by D43)* **The cross-output consistency audit is built, not demand-gated.** D16 named it as the mitigation for the one risk one-wrapper-per-output creates and left it to demand. The risk deserves better: N independent executions of a step *misdeclared* as `pure` can produce disagreeing siblings **within a single run** — a `customer_xref` referencing `canonical_id`s the `customer` execution never minted — and nothing else in the project can see that. Every behavioural gate compares run to run; `assert_step_contract` cannot help either, because each output is individually valid. It became more pressing once D36 let these outputs feed marts and metrics, since a disagreement now propagates into numbers. Detection is structural and needs no new spec surface: wherever one output carries another's declared `key`, the reference must resolve. *(Superseded by D43: inferring the relationship from matching key columns fabricates it from coincidence. References are **declared** — `StepOutput.references` — and an implementation must not raise an audit from an inferred match. The NULL-key exclusion and the single-output rule below both survive.)* NULL keys are excluded on RFC 0016's three-valued discipline — a row with no key value says nothing, and failing a blocking audit on it would punish the ordinary case. A single-output step emits nothing, because an audit with nothing to compare is noise that trains people to ignore the ones that matter. Executed against DuckDB with a seeded orphan rather than read: the audit returns the orphan and stays empty on a consistent run. |

| 41 | *(2026-08-08, M13 re-audit)* **D36 claimed more than shipped: metrics and `reconcile` still cannot reference a step output.** §5.8 names "downstream mappings, marts, and metrics"; marts work and metrics do not — metric resolution keys on *mappings*, and a step entity has none, so a measure over a step column is `unreachable metric … no mapped derivation path`. `reconcile` refuses them too, for the same reason. Both fail loud rather than silently, so this is a documentation defect and not a correctness one — but the RFC row is the authority (CLAUDE.md), and a row claiming more than the code does is the kind of drift the corpus exists to prevent. D36 is narrowed to marts and downstream models; metrics and reconcile over step outputs are the next increment, named like D39 names quality rules. |
| 42 | *(2026-08-08, M13 re-audit)* **The consistency audit was emitted and never ran, and the wrapper never loaded at all.** Two defects in one blind spot, both invisible to every test written for them. (a) SQLMesh loads a bare `AUDIT` as a **model** audit, executed only where a model's `audits` list names it — and nothing named it, so D40's blocking check was inert. The test that "proved" it extracted the SELECT and ran it straight against DuckDB, so SQLMesh was never in the loop. (b) Loading the project properly then showed the `python_model` wrapper does not load *at all*: SQLMesh serializes the module globals a model function references into a fresh environment, and a global holding a `Decimal` parameter fails to reconstruct there — `name 'Decimal' is not defined`, before anything runs. The wrapper had only ever been `ast.parse`d. Audits are now attached to the child output's model, and the wrapper binds every name inside its function so there is nothing to serialize. The lesson is the general one: a generated artifact is only verified by the tool that will consume it, and parsing it yourself proves the grammar, not the contract. |
| 43 | *(2026-08-08, M13 re-audit)* **References between sibling outputs are declared, never inferred.** D40 detected them structurally — one output carrying another's key columns. That fabricates relationships from coincidence: two outputs both keyed `id` earned a *mutual* pair of blocking audits asserting their id sets are identical, which fails every run on correct data and is the exact failure that teaches people to ignore audits. `StepOutput` gains `references: {column: sibling}`, validated against the sibling's single-column key. Inferring a relationship nobody declared is what RFC 0006 exists to refuse, and it does not become acceptable because the inference is cheap. Also fixed here: the audit read the *authored* relation while every other step path routes through the naming policy — D34's bug on the audit side, reopened because D34 shipped without a scoping-policy test — and audit names are now prefixed `step_`, with a general path-uniqueness guard over the whole artifact list, since RFC 0016's `<entity>_<rule>` audits share the namespace and two artifacts at one path compiled clean. |

| 44 | *(2026-08-09, M13 fourth audit)* **The consistency audit read its sibling through the naming policy, which this codebase had already learned not to do.** D43 routed both sides of the audit through `ctx.naming` to fix a real bug — and reintroduced the failure `lowering.py` states as doctrine (*"the audited entity is addressed through THIS_MODEL, never through the naming policy"*) and RFC 0016 D61 redesigned the conservation audit to avoid. SQLMesh substitutes physical snapshot tables only for relations in the audited model's `depends_on`, and sibling wrappers had no edge between them, so the audit resolved `silver.customer` to a virtual-layer view: **the plan failed on correct data** on a first deploy, gave a **false positive** on a staged one (comparing this plan's child against the *promoted* parent), and a **false negative** on the orphan it exists to catch. Fixed by declaring the referenced siblings — and the model's own reads, since `depends_on` replaces inference rather than extending it. Because that makes a reference a real DAG edge, mutual references are now refused at the manifest as a cycle. |
| 45 | *(2026-08-09, M13 fourth audit)* **`step_resolution` joins the e2e tier, which is the structural fix.** Three defects in a row lived in one blind spot: nothing loaded step artifacts through SQLMesh. The goldens pinned bytes, `ast.parse` proved grammar, and the execution tier ran the audit's SELECT with SQLMesh nowhere in the loop — so an audit that never ran, a wrapper that never loaded, and an audit that read the wrong table were all green everywhere. The e2e tier's own docstring had *already described* this hazard for RFC 0016's conservation audit; the fixture simply was not in it. It is now, with its platform step body written by the harness (step bodies are platform-repo territory, §6), and both directions verified through a real `plan(auto_apply=True)`: consistent data applies, a seeded orphan raises `NodeAuditsErrors`. The general lesson, stated because it has now cost four audits: **a generated artifact is verified only by the tool that consumes it.** |
| 46 | *(2026-08-09, M13 fourth audit)* **Generated locals are `_blm_`-prefixed, and a step's input must be a real entity.** Moving the wrapper's state inside `execute()` (D42) put it in the same scope as the imported entrypoint, so a step function named `parameters`, `manifest` or `Decimal` shadowed the local the next line needed — `Decimal` silently rebinding a value constructor to caller code being the worst of them. Separately, the fixture bound an input to a relation nothing produced; `context.table(...)` resolves *models*, so that compiled clean and failed at run time with "unable to find a table mapping". The fixture now maps `customer_raw` as an ordinary entity, which is also what a step input realistically is. |
| 47 | *(2026-08-09)* **§10's `sql_model` parameter question was not an open choice — it was an open hole.** The RFC left "Jinja or sqlglot placeholder substitution" to implementation and neither shipped: a Tier 2 body reading `:threshold` emitted `WHERE score > $threshold` **unsubstituted**, while the authored value sat in `StepIR.parameters` changing the fingerprint. So bumping the parameter restated the outputs and recomputed the same rows, and the engine met an unknown variable — an author wrote a parameter, got no parameter, and got no error, the exact failure D26 refused `sql_macro` and step-output quality rules to avoid. Settled as **sqlglot `:name` placeholders**, the spelling Tier 1 already uses, substituted as AST literal nodes so a value stays data wherever it lands (RFC 0013's injection boundary; RFC 0004 D7's SQLGlot-only rule). The declared type picks the literal — never the shape of the digits, which is D20's guessing game — and `date`/`timestamp` render as string literals the engine compares in the column's own type, the convention `_bound_literal` set for RFC 0016's range bounds (D57) rather than a `CAST` spelling invented here. Body and parameters must name the **same resolved** set: a placeholder nothing declares, a placeholder whose parameter has no default and no wiring, and a resolved parameter the body never mentions are each a compile refusal. The middle one is the case that made "declared" the wrong thing to check — found by probing edge cases after the first fix looked complete. `variant` is refused in a body: DuckDB, Postgres and Trino do not write a semi-structured literal alike, and emitting one of the three compiles everywhere and compares correctly in one — a per-dialect literal hook is the named escape hatch, not built. |

## 12. Phasing

Lands as **M13**, after RFC 0016 (M12) — quality rules must exist before the escape
hatch they guard — and depending on shipped `plan()`: the `RESTATING` machinery
exists since M9, so Document 5's "build steps after the classifier" rule is already
satisfied (its M9.5 label corresponds to this milestone). Order within M13: manifest
models + `StepRegistry` + `UnknownStep`/determinism checks; the three emission kinds
with wrapper goldens; then the `runtime_lock`/`plan()` amendment. Done when all §8.7
adversarial steps are refused loudly, a `runtime_lock` bump alone produces a
`RESTATING` plan, and step goldens are green in the platform repo.
