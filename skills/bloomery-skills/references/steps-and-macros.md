# Steps and macros

Wire platform-owned code into a project: pick the tier on the ladder, write the manifest,
wire it in a `steps:` document or call a macro from a mapping, give a SQL body its
parameters, stay under the nesting limit, and understand `runtime_lock`.

## The principle

**Specs describe, specs reference implementations, specs never contain implementations.**
A step is platform code in git, reviewed as code, described by a versioned manifest, and
referenced as `use: ref@version`. No spec field can hold a body or name a file to load, and
bloomery reads no step file from disk: the caller assembles a `StepRegistry` and passes it
to `compile_project`. That absence is the security property.

## The ladder

Use the lowest tier that works.

| Tier | Kind | Scope | bloomery can | Reach for it when |
|---|---|---|---|---|
| 0 | transform | expression | typecheck fully | the whitelist covers it |
| 1 | `sql_macro` | expression | parse and typecheck | one gnarly expression |
| 2 | `sql_model` | table | parse, infer schema | multi-step SQL, windows, recursive CTEs |
| 3 | `python_model` | table | nothing: trust, then verify at run time | fuzzy matching, ML |

Most "we need Python" is Tier 1 or 2 on inspection. Tier 3 moves data out of the engine,
is memory-bound and loses column lineage (`lineage: coarse`), and only SQLMesh runs it; dbt
refuses a Tier 3 project. A Tier 1 macro is spliced into the model's query and costs nothing.

## The manifest

Lives beside the step body in the platform repository, never in a spec.

```yaml fragment
ref: dedupe_sessions
version: 2
kind: sql_model
determinism: pure
runtime_lock: sha256:4c1e
inputs:
  events: {grain: event, requires: [session_id, event_at]}
outputs:
  session:
    grain: session
    key: [session_id]
    produces:
      session_id: {type: string, required: true}
      started_at: {type: timestamp}
      event_count: {type: int}
parameters:
  min_events: {type: int, default: 1, min: 1, max: 1000}
lineage: column
```

- `key` is the checkable half of `grain`; the generated contract enforces it.
- An input's `requires` is a lower bound: when the wiring binds an entity or another step's
  output, each required column must exist there, or `StepError`.
- `determinism`: `pure` backfills freely; `seeded` requires a `seed:` in the wiring;
  `nondeterministic` is a compile error.

## Wiring a table step

```yaml spec=steps
steps_version: 1
steps:
  - use: dedupe_sessions@2
    inputs: {events: silver.event}
    outputs: {session: silver.session}
    parameters: {min_events: 2}
    canonical:
      session: {event_count: session_events}
    quality:
      - {name: has_events, rule: expression, expr: "event_count > 0", on_fail: flag}
    applies_to: {has_events: session}
```

| Key | Meaning |
|---|---|
| `use` | `ref@version`; one wiring per `ref` |
| `outputs` | every declared output bound to a relation (≥ 1) |
| `inputs` | declared inputs bound to relations |
| `parameters` | values within the manifest's bounds |
| `seed` | required for `seeded`, refused otherwise |
| `canonical` | output → {column: canonical field}; never inferred from a name, and without it metrics over the output are unreachable |
| `quality` / `applies_to` | `expression` rules only, each naming its output |

Dispositions by tier: `fail` lowers to a blocking audit on both table tiers; `flag` adds
`_quality_flags` / `_quality_ok` on a `sql_model` and is refused on a `python_model`;
`quarantine` is refused on both (route rows in a downstream mapped entity instead).

Each declared output becomes its own model and is synthesized as an entity, so marts can be
based on it.

## A SQL body and its parameters

A Tier 2 body uses `:name` placeholders for its parameters, and reads its inputs by the
relations the wiring binds: the body is emitted as written, so `FROM` names the bound
relation, not the input's name. Each placeholder is replaced by a literal node, never text,
so a parameter cannot carry SQL.

```sql
SELECT session_id, MIN(event_at) AS started_at, COUNT(*) AS event_count
FROM silver.event
GROUP BY session_id
HAVING COUNT(*) >= :min_events
```

A `sql_model` body's placeholders and its resolved parameters must be the same set: an
undeclared `:x`, a declared parameter with no default and no wiring, and a parameter the
body never uses are each compile errors. A `variant` parameter cannot be substituted; pass
a scalar and cast. A `sql_macro` body's placeholders are its `accepts` names instead (below).

## Macros (Tier 1)

A macro writes no relation, so it is never wired in `steps:`; a mapping calls it. Its
manifest declares a signature: `accepts` and, through `produces`, the returned type.

```yaml fragment
ref: extract_domain
version: 1
kind: sql_macro
determinism: pure
runtime_lock: sha256:beef
accepts:
  email: string
outputs:
  value: {grain: row, key: [v], produces: {v: {type: string}}}
```

Body: `SPLIT_PART(:email, '@', 2)`. Two ways to call it:

```yaml fragment
fields:
  email_domain:
    step: extract_domain@1
    from: {email: "$.email"}
  email_domain_clean:
    from: "$.email"
    transform: [lower, {step: extract_domain@1}, trim]
```

As a chain link the running value fills the single accepted column, so only a one-argument
macro can be a link. Refused: a body naming something undeclared, a call binding a column
the macro does not accept or omitting one it does, and any macro not `determinism: pure`.

## The nesting limit

Authored SQL may nest at most **32 levels** deep in its parsed tree: a macro body, a
`sql_model` body, an expression, and the composition of macros along one chain. Deeper text
is refused with "past the 32 authored SQL may nest. Fix: flatten the expression", because
every later stage re-parses it deeper in the stack.

## `runtime_lock`

A hash of the step's pinned dependency set, computed when the registry is built, and part
of the step's identity in the IR. A library bump that silently changes a scorer therefore
changes the fingerprint, `plan()` classifies it `RESTATING`, and the outputs land in the
backfill scope. A parameter change, a new seed and rewired inputs restate the same way.

## Compiling with a registry

The CLI cannot wire steps; compile from Python.

```python
import yaml

from bloomery import StepManifest, StepRegistry, Target, compile_project

manifest = StepManifest.model_validate(yaml.safe_load(manifest_text))
registry = StepRegistry(
    steps={("dedupe_sessions", 2): manifest},
    sql_bodies={("dedupe_sessions", 2): body_text},
)
artifacts = compile_project(project, target=Target.SQLMESH, dialect="duckdb", catalog=catalog, steps=registry)
```

Keys must equal the manifest's own `ref` and `version`, or `StepError`. A `use:` the
registry lacks is `UnknownStep`. Tier 3 wrappers import `bloomery.steps.assert_step_contract`
and assert the declared contract (columns, types, required, key uniqueness) on every run,
with no flag to disable it.

## Parameterize, never fork

A tenant needing different behaviour changes parameters; nobody writes
`resolve_customers_acme`. When migrating existing code: wrap it as `@1` with
`lineage: coarse`, get it into the DAG, then push it down the ladder.

## Published pages

- [Steps: referenced implementations](https://morzecrew.github.io/bloomery/latest/concepts/step-registry/)
- [Spec schemas: StepSet](https://morzecrew.github.io/bloomery/latest/reference/spec-schemas/)
