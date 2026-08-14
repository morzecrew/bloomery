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
(`lineage: coarse`). Tier 1 costs nothing at run time at all — the macro body is spliced into the
model's query, so the model stays one query and lineage sees straight through
it.

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

### Quality rules on an output

A step output takes RFC 0016 `expression` rules, and `applies_to` says which
output each judges — an entity's `quality:` has one relation to mean, a step
has several:

```yaml
steps_version: 1
steps:
  - use: resolve_customers@3
    outputs: {customer: silver.customer}
    quality:
      - {rule: expression, name: confident, expr: "confidence >= 0.8", on_fail: fail}
    applies_to: {confident: customer}
```

**`on_fail: fail` only.** It lowers to a blocking audit over the relation, so
a run whose step produced a violating row stops. `flag` and `quarantine` are
compile errors: both work by rewriting the silver `SELECT` — adding to
`_quality_flags`, routing rows into the reject table — and a step-produced
relation has no `SELECT` to rewrite, because its wrapper writes the rows in
Python. A rule kind that worked for one disposition and silently did nothing
for the other two would be worse than the refusal.

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

### Linking an output to canonical fields

A mart can read a step output as soon as it exists. A **metric** needs one
more thing: it resolves against canonical fields, and something has to say
which canonical field a produced column *is*.

```yaml
steps_version: 1
steps:
  - use: resolve_customers@3
    outputs: {customer: silver.customer}
    canonical:
      customer:
        confidence: match_confidence
```

The link lives on the wiring rather than in the manifest, because canonical
names are your spec's vocabulary — a manifest naming them could not be reused
by a project that spells them differently, which is the fork "parameterize,
never fork" exists to prevent.

It is never inferred from a matching column name. A column called
`confidence` is not assumed to be the canonical `confidence`: guessing a link
nobody declared is exactly what the compiler refuses elsewhere, and it does
not become acceptable because the guess is cheap.

With the link declared, nothing else is special. The column becomes available,
metrics over it are reachable, and a `reconcile:` check may name the step's
relation on either side.

There is no field here that can hold a body, and none that can name a file to
load. That absence is the security property: a spec can no more load code than
a metric name can. The registry is assembled by the caller and passed in —
`compile_project(project, …, steps=registry)` — so bloomery never reads a step
file from disk, and there is no dynamic loading path to abuse.

## Using a macro (Tier 1)

A macro is referenced from the mapping that uses it, never wired in the
`steps:` document — it writes no relation, so it has no output to bind there,
and one wiring per step ref would make a macro usable in exactly one mapping.

Its manifest declares a **signature**: what it accepts, and (through
`produces`) what it returns.

```yaml
ref: extract_domain
version: 1
kind: sql_macro
determinism: pure
runtime_lock: sha256:beef…
accepts:
  email: string
outputs:
  value: {grain: row, key: [v], produces: {v: {type: string}}}
```

The body lives in the registry the caller assembles, as one expression whose
`:name` placeholders are exactly what the manifest declares:

```sql
SPLIT_PART(:email, '@', 2)
```

### Two ways to call it

**As a field**, binding each accepted column to a source path — the shape to
reach for when a macro takes more than one column:

```yaml
fields:
  email_domain:
    step: extract_domain@1
    from: {email: "$.email"}
```

**As a chain link**, so whitelist transforms and the macro compose on one
field. The running value fills the macro's single accepted column, so this
shape needs a macro that accepts exactly one:

```yaml
fields:
  email_domain:
    from: "$.email"
    transform: [lower, {step: extract_domain@1}, trim]
```

### What is checked

Because the signature is declared rather than guessed from the body, a chain
is typechecked *around* the macro: the transforms before it against what it
accepts, the transforms after it from what it produces. A macro is therefore
no weaker than a Tier 0 transform, which declares the same two things.

| Situation | Why it is refused |
|---|---|
| the body refers to something the manifest does not declare | the signature would be decoration, and a call site could not know what to supply |
| a call site binds something the macro does not accept | the path would be read for nothing — a typo is otherwise silent |
| a call site omits something it accepts | the placeholder would reach the engine unfilled |
| a two-column macro used as a chain link | a chain carries one running value, so an argument would be dropped |
| a macro declaring anything but `determinism: pure` | it is re-evaluated on every backfill by construction |

A genuinely polymorphic macro has to pick a type. That is the same constraint
a Tier 0 transform carries through its input domain, and the same trade:
a declared type is what makes the check possible at all.

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

The assertion is bloomery's own, imported by the generated wrapper:

```python
from bloomery.steps import assert_step_contract as _blm_assert
```

That path is **public API**, and unusually so: the importer is code bloomery wrote into
*your* repository, so renaming the module would break every wrapper generated before the
rename, at run time, with nothing at compile time to warn you. It is declared in
`bloomery.steps.__all__` and covered by the stability policy like any other export. The
older `bloomery.steps.contract` path keeps working.

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

## Before adding a spec kind, ask this

The registry exists so the answer can be "make it a step". The test:

> **Can bloomery typecheck it, guardrail it, and diff it meaningfully?** If not, it is a
> step.

A concept bloomery cannot verify is a concept where a spec kind gives *weaker* guarantees
than a step, because a step at least carries a declared, runtime-enforced output contract.
Identity resolution is the worked case — blocking keys, similarity functions and
thresholds are none of them typecheckable, and `runtime_lock` makes upgrading the matching
library a restating change that backfills the outputs, which a declarative similarity
function could never do. See [Resolve identities across systems](../how-to/resolve-identities.md).

This is what keeps the library smaller than the problem it solves. A spec kind is a
permanent surface: it has to parse, typecheck, guardrail, diff, emit on three targets and
survive every future version. A step is a manifest.

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
