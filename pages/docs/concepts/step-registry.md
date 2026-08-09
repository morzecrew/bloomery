# Steps: referenced implementations

Some cleansing genuinely is code. Entity resolution across source systems,
fuzzy matching, ML scoring — none of it is expressible as a declarative
mapping, and pretending otherwise produces worse specs, not better ones.

bloomery's answer keeps the principle intact: **specs describe, specs
reference implementations, specs never contain implementations.** A step is
platform code, in git, reviewed as code, described by a versioned manifest,
and referenced from a spec by `use: ref@version`.

## The ladder

Use the lowest tier that works.

| Tier | Kind | Scope | What bloomery can do | Reach for it when |
|---|---|---|---|---|
| 0 | DSL transform | expression | typecheck fully | the whitelist covers it |
| 1 | `sql_macro` | expression | parse **and** typecheck | one gnarly expression |
| 2 | `sql_model` | table | parse, infer schema | multi-step SQL, windows, recursive CTEs |
| 3 | `python_model` | table | nothing — trust and verify | fuzzy matching, ML, genuinely not SQL |

Most "we need Python" requirements are Tier 1 or 2 on inspection — a
surprising number of Python steps are one expression wearing a dataframe.

Tier 3's costs are real and worth naming before you choose it: data leaves the
engine, the step becomes memory-bound, and column-level lineage is gone
(`lineage: coarse`). Tier 1 will cost nothing at run time at all — the macro body is spliced into
the model's SELECT, so the model stays one query and lineage sees straight
through it. **It is not wired yet:** there is no spec surface by which a
mapping references a macro step, so a wired `sql_macro` is a compile error
today rather than a splice that quietly does not happen.

## What a manifest declares

The manifest lives in the platform repo, beside the step body — never in
bloomery, never in a spec:

```yaml
ref: resolve_customers
version: 3
kind: python_model
entrypoint: platform_steps.resolve_customers:resolve
determinism: pure
runtime_lock: sha256:a91f…
inputs:
  raw: {grain: customer_source_row, requires: [source_system, source_id, email]}
outputs:
  customer:
    grain: customer
    key: [canonical_id]          # what the runtime assertion enforces
    produces:
      canonical_id: {type: string, required: true}
      confidence:   {type: decimal(4,3)}
parameters:
  threshold: {type: decimal(4,3), default: 0.85, min: 0, max: 1}
lineage: coarse
```

`grain` is prose for humans; `key` is the machine-readable half, and the
difference matters — a grain sentence cannot be checked, a key can.

## What a spec wires

Wiring, and nothing else:

```yaml
steps_version: 1
steps:
  - use: resolve_customers@3
    inputs:  {raw: silver.customer_raw}
    outputs: {customer: silver.customer, customer_xref: silver.customer_xref}
    parameters: {threshold: 0.9}
```

Quality rules on step outputs are described by RFC 0017 §5.2 but are **not
lowered yet** — declaring them is a compile error rather than a rule that is
accepted and never evaluated.

### How a parameter reaches a SQL body

A Tier 2 body refers to its parameters as sqlglot placeholders, the same
`:name` spelling Tier 1 uses:

```sql
SELECT canonical_id, confidence
FROM silver.candidates
WHERE confidence >= :threshold
```

Each placeholder is replaced by a **literal node**, not by text, so a value is
data wherever it lands — a parameter cannot carry SQL into the body. The
declared type picks the spelling: `int` and `decimal` become number literals,
`bool` a boolean, and `string`, `date` and `timestamp` string literals the
engine compares in the column's own type.

The body and the step's parameters must name the same set, and each mismatch
is a compile error rather than something an engine discovers:

| Situation | Why it is refused |
|---|---|
| `:x` that no parameter declares | it would reach the engine as an unknown variable |
| `:x` declared with no default and not wired | same — declaring a parameter is not giving it a value |
| a parameter the body never uses | its value is part of the step's identity, so changing it restates the outputs and recomputes identical rows |

A `variant` parameter cannot be substituted into a body: DuckDB, Postgres and
Trino do not write a semi-structured literal the same way. Pass a scalar and
cast in the body instead.

There is no field here that can hold a body, and none that can name a file to
load. That absence is the security property: a spec can no more load code than
a metric name can. The registry is assembled by the caller and passed in —
`compile_project(project, …, steps=registry)` — so bloomery never reads a step
file from disk, and there is no dynamic loading path to abuse.

## Trust at compile, verify at run time

bloomery cannot infer a Python function's output schema, so it trusts
`produces` at compile time: downstream models typecheck against it, the DAG
stays complete, and `plan()` computes backfills *across* the step.

Then the generated wrapper checks reality against the declaration on every
run — outputs present, none undeclared, exact column set, assignable types,
`required` columns null-free, declared grain unique over its key. That
assertion is non-optional and non-configurable by construction. There is no
flag to turn it off, because a claim that is checked is a commitment and a
claim that is not is a comment.

Each declared output becomes its own model, and every wrapper asserts *all*
declared outputs — so a step that lies about one of them is caught wherever
the run happens to start.

## Determinism is not negotiable

| Tier | Meaning | What bloomery does |
|---|---|---|
| `pure` | same inputs, same outputs | backfills freely |
| `seeded` | deterministic given a seed | the seed is **required** in the wiring, and recorded |
| `nondeterministic` | clock, network, unseeded RNG | **compile error** |

A nondeterministic step makes a backfill disagree with the original run, which
destroys the ability to restate — the one capability the whole architecture is
organized around. Refusing it is the load-bearing constraint, not caution.

The declaration is trusted, and caught *behaviorally* if it lies: a step
secretly reading `datetime.now()` passes the contract check and fails the
backfill-equivalence gate. That is why that gate stays merge-blocking.

## Why `runtime_lock` exists

A step's behaviour depends on its libraries. `rapidfuzz` changing a scorer
between minor versions silently changes entity-resolution output, and nothing
in any spec would show it.

`runtime_lock` — a hash of the pinned dependency set, computed at registry
build time — is part of the step's identity in the IR. So a dependency bump
changes the project fingerprint, `plan()` classifies it `RESTATING`, and the
step's outputs land in the backfill scope. Correct behaviour, and invisible
without the lock.

The same is true of a parameter change, a new seed, or rewired inputs: they
are all fields on the step's IR node, so they all restate. There is no
special-casing for steps anywhere in `plan()` — that is the whole design.

## Parameterize, never fork

Steps are platform code. A spec configures parameters; it never supplies a
body. When something is needed that the library cannot do, the step is
generalized into a parameterized form — never `resolve_customers_acme`.

A requirement that genuinely cannot generalize is a useful signal rather than
a problem: it is bespoke consulting, not product, and knowing that explicitly
beats discovering it later in a directory of near-identical step files.

## Migrating existing code

**Wrap, don't refactor.** Write a manifest for the script you already have,
register it as `@1`, declare `lineage: coarse`, and claim `pure` only after
the backfill-equivalence gate has *verified* it rather than because it seems
true.

**Then get it into the DAG.** Once `plan()` can see the step, backfills stop
being something a human remembers to run.

**Then push down the ladder.** Most SQL scripts collapse to Tier 2; a
surprising number of Python ones turn out to be Tier 1 expressions. Extract
declared rules — quality rules, transforms — as you go.

A version bump requires new fixtures. A `@4` reusing `@3`'s expected outputs is
a review failure: if the outputs did not change, it should not have been a
version bump.
