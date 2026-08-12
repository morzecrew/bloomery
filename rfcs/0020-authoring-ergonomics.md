# RFC 0020 — Authoring ergonomics: schema export, CLI, fix suggestions

- **Status:** 📝 Draft
- **Scope:** Three additions that make the library holdable without writing Python:
  a **JSON Schema export** for the six spec kinds (`bloomery.schema`), a **thin CLI**
  (`bloomery compile|plan|resolve|explain|schema|fingerprint`) that is a pure argument
  shell over the public API, and **machine-readable fix suggestions** on the four
  highest-frequency refusals. The CLI is the only component in the package permitted to
  touch the filesystem; the library's no-I/O invariant is unchanged and newly enforced by
  the layering that separates them.
- **Related:** [RFC 0002](0002-spec-layer-and-errors.md) (strict frozen Pydantic specs,
  batched errors with source paths), [RFC 0005](0005-resolution.md) (`Resolution`,
  reachability with specific missing leaves),
  [RFC 0015](0015-query-vocabulary.md) (`KNOWN_UNSUPPORTED`, the closed refusal list —
  the precedent for machine-readable reasons),
  [RFC 0018](0018-public-surface-and-stability.md) (**blocking**: the CLI is a shell over
  that surface), [RFC 0019](0019-lowering-decomposition.md) (the purity guard the CLI must
  be carved out of), [RFC 0022](0022-spec-evidence.md) (`bloomery resolve` becomes a thin
  wrapper over `evaluate()` once it lands).
- **Adoption audit:** [`_adoption-audit-0018-0022.md`](_adoption-audit-0018-0022.md) —
  one of the two cited precedents for §5.4 turned out to be prose rather than a field.

---

## 1. Summary

Bloomery is currently reachable only from Python. That is correct for a library whose
first consumer is platform code, and it is the binding constraint on three other things:
spec authoring has no editor support, the single most useful thing the library knows
(which metrics are reachable, and which leaf is missing for the ones that are not) needs
a script to ask, and a proposal loop's safety argument rests on a schema that exists only
as Pydantic classes.

`bloomery.schema` exports JSON Schema per spec kind — a day's work over
`model_json_schema()` that unlocks editor completion, form validation, docs generation,
and **constrained generation** for machine-authored specs.

`bloomery.cli` adds six commands, each a pure function over a directory plus flags. No
execution, no state, no credentials, no config file.

Four refusal types gain a `suggestion` field carrying a machine-readable next action,
extending the one real precedent (`UnsupportedFilter.reason`) rather than the one the
draft assumed.

## 2. Motivation

**The schema export is the highest-leverage item in this RFC and the reason it is
sequenced first.** The proposal loop's entire safety argument (RFC 0017's framing,
generalized) is that a machine emits a *validatable artifact from a finite space*. Today
that finiteness lives in Pydantic classes reachable only from Python — so a proposer must
either be trusted to emit valid YAML and be corrected after the fact, or the schema must
be transcribed by hand into whatever the proposer speaks. A JSON Schema turns the
constraint from a prompt instruction into a structural one: constrained decoding where
available, and a pre-validation gate that costs nothing before bloomery is invoked at all.

The same artifact serves three other consumers for free — `yaml.schemas` in an editor
gives completion and inline errors to a human author, a control plane validating a web
form no longer duplicates the schema in TypeScript, and reference docs stop being able to
drift from the models.

**The CLI's argument is narrower but real.** `bloomery resolve` — "which metrics can I
compute, and for the ones I cannot, which specific leaf is missing" — is the most useful
question the library answers and currently requires writing a script. That is a poor trade
for a data engineer evaluating whether the spec they just wrote does what they meant.

**Fix suggestions** matter because of who reads the errors. A human reads a message; a
proposal loop reads a *structure*. `UnsupportedFilter.reason` already proves the pattern
and `KNOWN_UNSUPPORTED` already proves that stable machine-readable reason codes are the
house style. Extending both to the errors a proposer will hit constantly closes the loop:
a refusal becomes feedback for the next proposal rather than a dead end.

## 3. Current state

Verified against `main` @ `3da72c5` (2026-08-12):

- **No CLI.** `pyproject.toml` declares no `[project.scripts]` and no entry points. Usage
  is `examples/quickstart/run.py` — a script that reads YAML files and calls
  `compile_project`.
- **No schema export.** `model_json_schema` appears nowhere in `src/`. The spec kinds are
  strict frozen Pydantic models (RFC 0002), so the schema is one call away and simply is
  not exposed.
- **`errors.py`** — 506 LOC, a total hierarchy with source paths and batched reporting.
  `UnsupportedFilter` carries a `.reason` attribute, from the drift-guarded
  `KNOWN_UNSUPPORTED` (RFC 0015 D9). **`UnknownMember` does *not* carry `did_you_mean`** —
  its docstring says "the message carries a `did_you_mean` closest match", but no such
  attribute exists, so the closest match is rendered into prose and discarded. That makes
  `UnsupportedFilter.reason` the only existing structured-suggestion precedent, and
  `UnknownMember` a *fifth* candidate for §5.4 rather than a model for it.
- **`resolve()`** returns `Resolution` with reachable metrics, unreachable metrics, and
  the specific missing leaf per unreachable metric (RFC 0005) — root-exported, and
  reachable only from Python.
- **The no-I/O invariant** is total across `src/`: `load_project` takes
  `Mapping[str, str]`, never paths.
- **Six loadable kinds:** `catalog` (via `load_catalog`) plus the five `load_project`
  dispatches on — `entity_model`, `mapping`, `metrics`, `marts`, `steps`.

## 4. Goals / Non-goals

**Goals**

- A JSON Schema per spec kind, generated from the models so it cannot drift.
- Every question the library can answer, askable without writing Python.
- Refusals that a machine can act on, not only a human read.
- The no-I/O invariant preserved *and made structurally obvious* by where the filesystem
  access lives.

**Non-goals**

- **Executing anything.** `bloomery explain` prints SQL; `bloomery run` never exists.
  Execution belongs to the consumer, and its absence is what keeps the test suite
  infrastructure-free.
- A config file, a profile, credentials, or connection settings. Every command is
  arguments in, stdout or a directory out.
- A language server, editor plugin, or TUI. The JSON Schema is what an editor consumes;
  bloomery ships no editor integration.
- Scaffolding (`bloomery init`, `bloomery new entity`). Templates encode opinions about
  project layout that this library deliberately does not hold.
- Watch mode, incremental compilation, or a daemon. All imply state.

## 5. Design

### 5.1 `bloomery.schema` — JSON Schema export

```python
# bloomery/schema.py  (new, public)

class SpecKind(StrEnum):
    CATALOG = "catalog"; ENTITY_MODEL = "entity_model"; MAPPING = "mapping"
    METRICS = "metrics"; MARTS = "marts"; STEPS = "steps"

def spec_json_schema(kind: SpecKind) -> JsonDict: ...
def all_spec_schemas() -> Mapping[SpecKind, JsonDict]: ...
```

Six members, matching the six loadable kinds (§3). `SpecKind` is **new** — it does not
exist today, in `bloomery.spec` or anywhere else.

Three properties it must have, none of them free from `model_json_schema()` alone:

**Deterministic.** Sorted keys, stable `$defs` ordering, no memory addresses in
descriptions. The same determinism discipline as every other bloomery output, for the same
reason — the schemas are golden-tested, and a nondeterministic golden is noise.

**Self-describing about the closed sets.** The transform whitelist, the quality rule
catalogue, `Op`, `LogicalType`, `OnFail`, `Additivity`, and the `<kind>_version` key are
all closed enumerations, and each must appear in the schema as an `enum` rather than as a
free string. This is the property that makes constrained generation work: a proposer
choosing from an enum cannot invent a transform, and the refusals that would otherwise
catch the invention never fire.

The version key is a particularly good fit once RFC 0018 D7 pins each kind to
`Literal[1]`: the schema then carries `"enum": [1]`, and a proposer cannot emit a version
bloomery would misread.

**Versioned with the spec.** Each schema carries `$id` including the document version, so
a consumer can pin.

Docstrings become `description` fields, so the schema is also the reference documentation —
which is what stops it drifting.

### 5.2 `bloomery.cli` — six commands

```
bloomery compile     <dir> --target sqlmesh --dialect duckdb [--catalog F] [--steps F] --out <dir>
bloomery plan        <old-dir> <new-dir> [--format table|json]
bloomery resolve     <dir> [--format table|json]
bloomery explain     <dir> --metrics revenue,order_count --by carrier [--where JSON] [--limit N]
bloomery schema      [--kind entity_model] [--out <dir>]
bloomery fingerprint <dir>
```

Every command is `read files → call public API → write stdout or a directory`. Exit codes:
`0` success, `1` refusal (a `BloomeryError` — a *correct* outcome, and the distinction
matters for scripting), `2` usage error.

`--format json` on `plan`, `resolve` and `explain` emits the same structures the Python
API returns, so the CLI is scriptable and is not a second, lossier surface.

**`bloomery resolve` is the command that justifies the rest:**

```
$ bloomery resolve specs/

Reachable (7)
  gross_revenue           order_item
  order_count             order
  ...

Unreachable (2)
  margin                  missing: cogs        (no mapping, no satisfiable recipe)
  margin_pct              missing: cogs        (via margin)
```

That output is the answer to "did the spec I just wrote do what I meant," and it presently
requires a script.

### 5.3 The CLI is the only module that touches the filesystem

```
bloomery/
  cli/
    __init__.py     argument parsing, exit codes
    io.py           THE ONLY module in the package that reads or writes files
    render.py       table formatting for human output
  schema.py         pure
  ...               pure
```

RFC 0019's purity guard bans `os`, `pathlib` and friends across `src/`. `bloomery/cli/`
is added to its allowlist — **as a named carve-out with a stated reason**, not as a hole.
An import-linter contract enforces the direction: `bloomery/cli/` may import the library;
no library module may import `bloomery/cli/`.

That layering is what keeps the invariant honest under a feature that appears to violate
it. The shell reads paths; the library still only ever sees strings.

Packaging: `[project.scripts] bloomery = "bloomery.cli:main"`, argument parsing on the
standard library (`argparse`), **no new runtime dependency**. Table rendering is
hand-rolled; a dependency on `rich` or `typer` would be a real cost for cosmetics, and
`tabulate` is already present transitively via metricflow but is not depended on directly.

### 5.4 Fix suggestions on refusals

Following `UnsupportedFilter.reason`, the one structured precedent that exists:

| Error | New field | Content |
|---|---|---|
| `UnreachableAtGrain` | `covering_marts: tuple[str, ...]` | Marts that *would* cover the request, if any, plus per-metric grain so the caller sees the conflict |
| `GrainViolation` | `offending_measures: tuple[MeasureRef, ...]` | Which measure is at odds with the mart grain, and its own grain |
| `UnsupportedFilter` | `nearest_supported: Op \| None` | The closest supported operator, where one exists (`regex` → `like`) |
| `UnknownStep` | `available_versions: tuple[int, ...]` | Versions of that `ref` present in the registry |
| `UnknownMember` | `did_you_mean: str \| None` | The closest match — **computed today and discarded into the message.** Its docstring has promised this field since RFC 0011; the field is what makes the docstring true. |

All are **additive optional fields on existing errors**, so no message changes and nothing
regresses. The rendered message may incorporate them; the structured field is the point.

The audience is the proposal loop. A refusal carrying "here is the nearest thing that
would have worked" is feedback for the next iteration; a refusal carrying only prose
requires the proposer to re-derive the answer bloomery already computed. Bloomery does the
computation anyway — `UnreachableAtGrain` already knows which marts it rejected, and
`UnknownMember` already computes its closest match — and the suggestion is exposing a
value that is currently discarded.

Both fields are omitted, never fabricated: `covering_marts` empty means genuinely none.

## 6. Tests

Per RFC 0009 tiers.

| Tier | Test |
|---|---|
| Golden | One JSON Schema golden per spec kind. Schema changes become reviewable diffs. |
| Unit | Every closed set (transforms, quality rules, `Op`, `LogicalType`, `OnFail`, `Additivity`, `<kind>_version`) appears as an `enum`, not a free string — the property constrained generation depends on. |
| Unit | Schema generation is deterministic across `PYTHONHASHSEED` (the existing subprocess harness). |
| Property | Every fixture project validates against its kind's schema — the schema and the parser agree. |
| Property | A mutated fixture rejected by the parser is also rejected by the schema, for the mutation classes the schema can express (unknown key, wrong type, out-of-enum). Divergences are recorded, not silently tolerated. |
| Unit | Each CLI command over each fixture: exit code, and `--format json` round-tripping to the same structure the Python API returns. |
| Unit | Refusal exit code is `1`, distinct from usage error `2`. |
| Lint | `bloomery/cli/` is the only path in the purity allowlist for filesystem access; no library module imports it (planted-violation tested, per RFC 0019 decision 4). |
| Unit | Each of the five suggestion fields populates on a fixture that triggers it, and is empty rather than fabricated when there is genuinely nothing to suggest. |
| Unit | `UnknownMember.did_you_mean` exists as an attribute, not only in the docstring — the specific defect §3 found. |
| Docs | The quickstart example is expressible as CLI invocations. |

The parser/schema agreement property is the one worth building carefully. Two validators
over one grammar drift, and the drift shows up as a proposer emitting something the schema
accepts and the parser refuses — which reads to a user as bloomery being arbitrary.

## 7. Docs

- New `pages/docs/how-to/use-the-cli.md` — the six commands, exit codes, `--format json`.
- New `pages/docs/reference/json-schema.md` — the export, `$id` versioning, the enum
  guarantee, and an editor-setup snippet (`yaml.schemas`).
- `pages/docs/get-started/quickstart.md` — CLI path alongside the Python path.
- `pages/docs/reference/errors.md` — the five suggestion fields.
- Schemas published as build artifacts alongside the docs, so `$ref` by URL works.

## 8. Out of scope

- Execution of any kind. No `bloomery run`, no engine connection, ever.
- Config files, profiles, credentials.
- Language server, editor plugin, TUI, watch mode, daemon.
- Scaffolding commands.
- `bloomery evaluate` — it lands with RFC 0022, at which point `bloomery resolve` becomes
  a thin wrapper over it.
- Rewriting existing error *messages*. Only additive structured fields.

## 9. Risks

| Risk | Mitigation |
|---|---|
| The CLI accretes toward a platform (`run`, `--profile`, `--connection`) | §8 states the refusals; the purity allowlist is one named directory; adding execution would require importing an engine, which the RFC 0019 guard blocks in `src/`. The pressure is real and the guard is structural. |
| JSON Schema cannot express every Pydantic validator, so the two validators diverge | §6's mutation property measures the gap rather than assuming it away. Divergences are recorded in this RFC's amendments; the schema is a *pre*-filter, never the authority. |
| Schema goldens churn on every Pydantic upgrade | Pydantic is already pinned (`>=2.9`); the goldens make churn visible, which is the point. A schema diff on a dependency bump is reviewed like any other. |
| Six commands is more surface than needed | Each maps to exactly one public function and adds no logic. `compile`, `plan`, `resolve` and `schema` are the load-bearing four; `explain` and `fingerprint` are one-liners over `MetricFlowPlanner.plan` and `project_fingerprint`. |
| Suggestion fields become a second, weaker error contract | They are optional and additive; the primary contract stays `.reason` and the message. Nothing may *only* be discoverable through a suggestion. |

## 10. Unresolved questions

1. Should `all_spec_schemas()` emit one bundled schema with `$defs` cross-references, or
   six standalone documents? Bundled is better for a single editor mapping; standalone is
   better for `$ref` by URL. Leaning: both, since the bundle is a mechanical join.
2. Does `bloomery explain` need `--policy` to exercise `RowPolicy` from the CLI? It would
   make the row-policy behaviour inspectable without Python, which has debugging value —
   but it also puts a tenant-shaped concept on the CLI surface, and bloomery is
   tenant-agnostic. Leaning: yes with a neutral spelling (`--policy 'region eq EU'`), since
   `RowPolicy` is already a public tenant-agnostic type.
3. Should the JSON Schemas be published to Schema Store? It would give editor completion
   with zero user configuration. Deferred until the spec schema is stable (RFC 0018 §5.5).
4. Should `bloomery plan --format json` be the same JSON the platform's ledger stores?
   Aligning them would let the CLI produce a ledger-ready artifact; it would also couple a
   library output shape to a platform concern. Leaning: no — the platform maps it.

## 11. Decisions

| # | Decision |
| --- | --- |
| 1 | **The JSON Schema export ships first and is the highest-leverage item.** It is a day's work over `model_json_schema()` and serves four consumers at once — editor completion, control-plane form validation, drift-free reference docs, and constrained generation for machine-authored specs. The last is the one that changes a proposal loop's safety argument from a prompt instruction into a structural constraint. |
| 2 | **Every closed set appears in the schema as an `enum`**, never a free string: transforms, quality rules, `Op`, `LogicalType`, `OnFail`, `Additivity`, document versions. This is the property constrained generation depends on — a proposer choosing from an enum cannot invent a transform, so the refusal that would catch the invention never fires. Unit-tested per set. |
| 3 | **Schema export is deterministic and golden-tested**, on the same discipline as every other bloomery output: sorted keys, stable `$defs` order, no addresses in descriptions. A nondeterministic golden is noise, and these goldens are how schema changes become reviewable. |
| 4 | **Six CLI commands, each a pure shell over one public function**, adding no logic of their own. Exit codes distinguish refusal (`1`) from usage error (`2`), because a refusal is a *correct* outcome and scripts must be able to tell. `--format json` returns the same structures the Python API does, so the CLI is not a second lossier surface. |
| 5 | **`bloomery/cli/io.py` is the only module in the package permitted to touch the filesystem**, added to RFC 0019's purity allowlist as a named carve-out with a stated reason, and enforced one-directional by import-linter: the CLI may import the library, no library module may import the CLI. The shell reads paths; the library still only ever sees strings, so the no-I/O invariant is preserved *and made structurally obvious* rather than merely asserted. |
| 6 | **No new runtime dependency.** `argparse` from the standard library, hand-rolled table rendering. A dependency on `rich`/`typer` would be a real cost for cosmetics in a library whose dependency discipline is one of its properties. |
| 7 | **Five refusals gain optional structured suggestion fields** (§5.4), additive. The draft cited two existing precedents; only one is real. `UnsupportedFilter.reason` is an attribute; **`UnknownMember.did_you_mean` is not** — its docstring has promised the field since RFC 0011 while the closest match is computed and thrown into prose. So `UnknownMember` joins the list as a fifth entry rather than serving as the model for it, and the field is what finally makes its own docstring true. Each field exposes a value bloomery **already computes and currently discards**. Fields are omitted, never fabricated. |
| 8 | **Suggestions never become a second error contract**: they are optional, and nothing may be discoverable *only* through a suggestion. The primary contract stays `.reason` plus the message. |
| 9 | **No execution, ever.** `explain` prints; `run` does not exist. This is what keeps the test suite infrastructure-free and the library a compiler. Config files, profiles, credentials, watch mode, daemons and scaffolding are refused for the same reason — each implies state or an opinion the library does not hold. |
| 10 | **A property test measures schema/parser agreement** rather than assuming it: every fixture validates against its schema, and mutations the parser rejects are checked against the schema too, with divergences recorded as amendments. The schema is a pre-filter, never the authority — two validators over one grammar drift, and undetected drift reads to a user as arbitrariness. |

## 12. Phasing

Design locked by this RFC; implementation lands as wave **M17**, after RFC 0018's M15
(decision 4 makes the CLI a shell over the closed surface — without signature closure the
CLI would need deep imports and would itself widen the API). Independent of RFC 0019, but
sequencing after M16 is preferable so the purity allowlist has one owner rather than two
concurrent editors.

Within the wave, in dependency order: **schema export** (decisions 1–3, independently
useful and unblocked), then **suggestion fields** (decisions 7–8, additive and testable
alone), then the **CLI** (decisions 4–6, which consumes both — `bloomery resolve` renders
suggestions, `bloomery schema` emits the export).

When RFC 0022 lands, `bloomery resolve` is re-pointed at `evaluate()` and gains its
refusal reporting; that re-pointing is an amendment to this RFC, not a new command.
