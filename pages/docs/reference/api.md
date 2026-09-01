# API

The public API — everything importable from `bloomery`, kept in lockstep with the
package's `__all__`.

The list is **closed over its own signatures**: any type named in a public signature is
exported from `bloomery` too, so `Project`, `Catalog`, `ProjectIR`, `EmittedArtifact` and
the naming policies are importable from the root rather than only from their subpackages.
The subpackage paths keep working. See [Stability](stability.md) for what each surface
promises.

## Loading

### `load_catalog(text: str) -> Catalog`

Parse a catalog document from YAML text. Pure — strings in, model out; all I/O belongs
to the caller. Raises `SpecParseError` on YAML, shape, or kind failures.

### `load_project(sources: Mapping[str, str]) -> Project`

Parse a project from named YAML documents. Keys are document names (used as
source-path prefixes in errors), values are YAML text. Each document self-identifies
via its version key; documents are processed in sorted-name order, and all failures
across all documents are batched into a single `SpecParseError`.

## Compiling

### `compile_project(project, *, target, dialect, naming=None, catalog=None, steps=EMPTY_REGISTRY) -> tuple[EmittedArtifact, ...]`

Compile a parsed project into target artifacts — the whole pipeline (resolve,
typecheck, guardrails, lower, emit) as one pure function. `target` is a `Target` or
the string name of a registered extension emitter; `dialect` is `"duckdb"`,
`"trino"`, or `"postgres"`; `naming` defaults to layer-based naming
(`silver.<entity>`, `gold.mart_<name>`). Same specs in, byte-identical artifacts out.
Each `EmittedArtifact` carries `path`, `content`, `kind`, and `checksum`.

`steps` is a `StepRegistry` — the manifests behind whatever the project's
`steps_version` document wires. It is a *caller-assembled* argument rather than a spec
document because bloomery reads no step files: a project that wires a step and compiles
without its registry is refused, not silently compiled without it. A project wiring no
steps needs nothing here.

### `Target`

The shipped emit targets: `Target.SQLMESH`, `Target.CUBE`, `Target.DBT`. A string
enum, so `target="sqlmesh"` also works.

## Analysis

### `resolve(project: Project, catalog: Catalog | None = None) -> Resolution`

Run reference validation, recipe validation, and reachability without emitting
anything. The `Resolution` carries `reachable_metrics`, `unreachable_metrics` (each
with its specific missing leaves), per-field `provenance` (direct / recipe / native),
the deterministic topological order, and the dependency `graph` those three were
computed from.

### `lineage(graph, root, direction=Direction.UPSTREAM, *, max_depth=None) -> Lineage`

Walk a `Resolution.graph` from one node and return the **reachable sub-DAG** — the
nodes and the labelled edges, never enumerated paths, whose count is exponential in
the graph's width. `Direction.UPSTREAM` answers "what is this built from",
`Direction.DOWNSTREAM` answers "what would break if this moved", and
`Direction.BOTH` merges the two — its `nodes` and `edges` are the union of what the two
walks reached, so every edge carried is one a walk actually traversed. That matters where
an ancestor of the root also connects directly to a descendant of it: the bypass edge is
real lineage, but it is not the root's, and inducing over the merged node set would carry
it.

The root is at depth 0, so `max_depth=N` carries every node within distance `N` and
only edges whose both endpoints are carried; `truncated` says whether the bound cut
the walk short. A root with no lineage in that direction is a one-node result rather
than an error — a source column has no upstream, and that is an answer. A negative
`max_depth` raises `ValueError`.

Requires an acyclic graph, which `resolve()` guarantees: it raises `CircularDerivation`
before returning.

Each edge carries a **label** saying how one node feeds the next. The vocabulary is closed:

| Label | From → To | Means |
| --- | --- | --- |
| `direct` | source column → entity field | a mapped field, no recipe |
| `recipe:<id>` | source column → entity field | a validated catalog recipe, id recorded |
| `step:<ref@version>` | source column → entity field | a field computed by a Tier 1 `sql_macro` |
| `canonical` | entity field → canonical field | the field links to a catalog canonical |
| `requires` | canonical field → metric | a metric's leaf requirement |
| `requires_metrics` | metric → metric | a metric composed of metrics |
| `step_input` | entity field → step | a step reading a mapped entity, whole |
| `step_input` | step → step | a step reading another step's output |
| `step_output` | step → entity field | a step's declared output |

The two parameterised labels carry a suffix after the `:` — a recipe id, or a macro's
`ref@version`. Split on the colon to compare *families*.

### `build_project_ir(project, catalog=None, *, steps=EMPTY_REGISTRY) -> ProjectIR`

Compile specs into the frozen intermediate representation without emitting — the
input to `project_fingerprint`, `plan`, and `MetricFlowPlanner.plan`. Runs the same
resolution, typecheck, and guardrail stages as `compile_project`, so a spec that
builds an IR is a spec that compiles — and takes `steps` for the same reason and on
the same terms.

### `project_fingerprint(ir: ProjectIR) -> str`

The `blm1:`-prefixed SHA-256 content hash of a project IR — the value stamped into
every emitted artifact's header. Stable within a bloomery version, deliberately not
across versions.

### `evaluate(project, *, catalog=None, steps=EMPTY_REGISTRY) -> SpecEvidence`

Everything knowable about a spec without touching data, as one frozen value: what is
reachable, what is not and which leaf is missing, what was refused and where, and the
shape of every mart. **Never raises for a spec-level refusal** — refusals are the
return value, and whatever analysis completed before them comes back alongside.

`InvariantViolated` and every programming error still propagate. See
[Assess a spec](../how-to/evaluate-a-spec.md) and
[Close an open decision](../how-to/close-an-open-decision.md).

### `SpecEvidence`

`stage_reached`, `reachable`, `unreachable`, `refusals`, `marts`, `entities`,
`unresolved`, `provenance`, `fingerprint`. **Read `stage_reached` first**: every tuple is
empty both when there was nothing to find and when the stage that finds it never ran, and
those mean opposite things. `fingerprint` is `None` unless `stage_reached is
Stage.COMPLETE`.

### `OpenDecision`

`canonical`, `gap`, `entity`, `field`, `options`, `blocks` — one decision the spec leaves
open, and the edit that would close it. `blocks` names the metrics waiting on it and is
never empty: a canonical field nothing requires is not work. See
[Close an open decision](../how-to/close-an-open-decision.md).

`options` are **the recipes the catalog declares** for that field, in the order the
catalog declares them. They are not suggestions, not candidates, and not ranked — bloomery
validates a recorded choice and never makes one, including where there is exactly one
option. Catalog order is authored information (recipes are ordered by reliability), so
re-sorting it destroys something rather than normalizing it.

An entry appears only where it can name **one** edit. A canonical field belonging to an
entity that several mappings build is left out, because such an entity's columns are per
mapping and no single document is the edit; the metric blocked on it is still in
`unreachable`.

### `Gap`

`UNLINKED` — no entity field carries `canonical: <name>`, so the edit is an entity-model
one. `UNMAPPED` — a field carries the link and no mapping produces it, so the edit is a
mapping field and it is where a recipe id is recorded. The two report identically without
this field, and they are the two different edits.

### `RecipeOption`

`id`, `requires`, `expr`. `requires` names the **alias slots** a mapping's `from:` must
bind to source paths — never canonical fields — so recipes do not compose and a chooser's
loop cannot grow work by doing it. `expr` is `None` for an identity over a single
requirement.

### `FieldProvenance`

`entity`, `field`, `provenance` (`DIRECT` / `RECIPE` / `NATIVE`), `recipe_id` — set iff
the provenance is `RECIPE`. On `SpecEvidence.provenance` and on `Resolution.provenance`:
what a spec has already decided, and what it decided.

### `Stage`

`RESOLVE`, `TYPECHECK`, `LOWER`, `GUARDRAILS`, `COMPLETE` — the stage analysis stopped
at. Treat it as an **open** enum: compare against `COMPLETE` and read everything else
as "analysis stopped early", so a stage added later does not break the comparison.

### `MartSummary`

`name`, `grain`, `measures`, `dimensions` (role-qualified), `materialization` — a mart's
shape, projected from the IR rather than recomputed.

### `UnreachableMetric`

`name`, `missing`, `via`. `missing` names the specific *leaves* — the canonical fields
nothing maps — because the fix is always a mapping. `via` names the metrics between this
one and those leaves, when it is blocked through another metric rather than on its own.

## Spec-diff planning

### `plan(old: ProjectIR | None, new: ProjectIR) -> Plan`

Diff two compiled IRs into a classified migration plan. `plan(None, new)` is the
initial deploy; `plan(ir, ir)` is empty. Raises `RenameTargetMissing` on a stale
`renamed_from` annotation and `ContractViolation` on an expand/contract breach; every
other change, breaking included, is classified and returned. See
[Evolve a spec safely](../how-to/evolve-a-spec.md).

### `Plan`

`changes` (sorted `Change` tuple), `backfill_scope` (`BackfillScope`), `replay_scope`
(`ReplayScope`), and `downstream_impact` (affected metric names). Properties:
`has_changes`, `breaking`.

### `Change`

One classified difference: `entity`, `subject` (`<kind>:<name>`), `change_class`,
human-readable `detail`, and compact `old`/`new` value reprs.

### `ChangeClass`

The closed classification vocabulary: `ADDITIVE`, `WIDENING`, `RENAME`, `RESTATING`,
`BREAKING`.

### `BackfillScope`

`entities` — the sorted entities whose stored rows a plan invalidates — and
`restates_history`, true when any RESTATING change is present.

### `ReplayScope`

`entities` — the sorted entities whose `<entity>__reject` tables a plan invalidates.
Distinct from `BackfillScope` because the two name different storage: a backfill
recomputes an entity from bronze, while a replay re-runs the current mapping against
rows that are not in bronze's incremental window at all. Populated only where a change
can actually free rows: the **old** disposition was `quarantine`, and the rule is now
gone, now disposes as `flag`, or has relaxed parameters. A tightening — a narrowed
bound, or `quarantine → fail` — needs a backfill and no replay: every quarantined row
still fails the rule, so replaying it drains nothing. Where relaxation is undecidable
from the parameters (a `pattern` regex, an `expression`), the replay is reported.
bloomery emits the replay merge artifact; executing it is the caller's. See [Add quality
rules](../how-to/add-quality-rules.md).

## Request-time planning

### `MetricFlowPlanner(hydrator, max_limit=50_000, default_limit=None, *, naming=None)`

The planner port backed by an embedded, render-only MetricFlow. `naming` must match
the policy the artifacts were emitted with.

**`.plan(ir, request, *, dialect, policy=None) -> QueryPlan`** — validate the request,
check mart coverage, and render SQL; nothing is executed. Refusals raise the planner
error taxonomy (`UnknownMember`, `UnreachableAtGrain`, `AmbiguousDimension`,
`InvalidRequest`, `FilterTypeMismatch`, and the `UnsupportedFilter` family). See
[Plan a metric request](../how-to/plan-a-metric-request.md).

### `MetricRequest(metrics, dimensions=(), filters=(), time_grain=None, order_by=(), limit=None)`

A structured metric request. Construction enforces the structural rules (at least one
metric, no duplicates, order over requested members only, `limit >= 1`). `filters` is
CNF: a tuple of clauses (implicit AND), each a `Predicate` or one `AnyOf` group.

### `Predicate(dimension, op, values=())`

One typed single-dimension filter (RFC 0015). `op` is an `Op` member; value arity is
checked per operator (`is_null` takes exactly one bool; `like`/`ilike` take one or
more patterns). Floats are accepted and normalized to `Decimal(str(value))` at
construction; non-finite numerics raise `InvalidLiteral`.

### `AnyOf(predicates)`

One disjunction group — OR across its predicates, AND with every other clause.
Exactly one level: members are `Predicate` only, and may span different dimensions.

### `Op`

The closed filter-operator vocabulary: `EQ`, `NE`, `GT`, `GTE`, `LT`, `LTE`, `IN`,
`NOT_IN`, `IS_NULL`, `LIKE`, `ILIKE`. A string enum, so `op="eq"` also works.
`like`/`ilike` operands are SQL `LIKE` patterns — caller-owned wildcards with `\` as
the escape character; nothing is auto-wrapped.

### `OrderSpec(field, direction="asc")`

One ordering term over a requested metric or dimension — never arbitrary SQL. Carries
no nulls placement (non-default placements are refused at the JSON front door).

### `TimeGrain`

Requestable grains: `HOUR`, `DAY`, `WEEK`, `MONTH`, `QUARTER`, `YEAR`. Applies to
every date-role dimension in the request; `HOUR` is refused at coverage (marts carry
day–year buckets).

### `RowPolicy(dimension, op, value)`

A row-level scoping filter — dimension, `Op`, scalar or scalar tuple — rendered
through the same escaping pipeline as user filters (via `as_clause()`) and prepended
to them, reaching every scan. A policy is one predicate; range policies compose into
the request filters instead. Deciding whose policy applies is upstream work.

### `QueryPlan`

The planner's product: `sql`, `columns` (tuple of `ColumnDescriptor`), `mart`,
`warnings`, `explanation` (with `.render()`), and `fingerprint` (`sha256(sql)`).

### `ColumnDescriptor`

One output column, carrying both names it has:

- `name` — what you asked for, in bloomery's vocabulary (`ordered_month`).
- `sql_alias` — what the emitted SQL actually projects (`order__ordered_day__month`).
- `type` — the logical type.
- `role` — `"dimension"` or `"measure"`.
- `label` — optional description.

Constructed by keyword only — `sql_alias` sits second rather than last, so a positional
call would misassign every field after the first.

**Bind result rows by `sql_alias`, display `name`.** For a measure the two agree; for a
dimension they do not, because MetricFlow qualifies the column by entity and suffixes a
date role with its grain. Positional binding — `columns[i]` against projection `i` — works
and always did.

### `bloomery.planner.parse_filter_json(payload, *, clause_cap=64) -> tuple[Clause, ...]`

The public JSON front door for the Mongo-flavoured filter grammar (`$and`/`$or`/
`$not`, field maps `{field: scalar | {op: value} | [array]}`, spellings `$eq $neq $gt
$gte $lt $lte $in $nin $null $like $ilike`). Normalizes before refusing — De Morgan
push-down, complement inversion, CNF distribution with the clause cap enforced during
distribution — and refuses only with `UnsupportedFilter` leaves carrying stable
`.reason` codes.

Two failure classes, deliberately distinct. A construct the vocabulary reviewed and
declined — a set relation, a hierarchy operator, `$regex`, an over-cap CNF expansion, a
non-invertible negation — raises `UnsupportedFilter` with a `.reason` from
`KNOWN_UNSUPPORTED`. Refusals fire wherever the parser reaches them: operator refusals,
non-finite literals, and the nesting-depth cap during tree construction;
`UnsupportedNegation` and the CNF clause cap after the rewrite. `.normalized` is set
wherever it says something useful — the form the document had reached for
`UnsupportedNegation`, a size sentinel (`>64 levels deep`, `>64 clauses`) for the two
caps. A *malformed* document — a non-mapping payload, a
field map of the wrong shape, an unknown `$op`, an operand of the wrong type — raises
`InvalidRequest`: it never reaches the closed list, because malformed input is a schema
error, not a reviewed gap. The same split holds for `parse_sort_json` and
`parse_page_json`: only a well-formed placement or a well-formed non-zero offset reaches
`UnsupportedSortNulls`/`UnsupportedPagination`; anything else is `InvalidRequest`.

### `bloomery.planner.parse_sort_json(payload) -> tuple[OrderSpec, ...]`

Sort documents (`{field: "asc" | "desc" | {"dir": …, "nulls": …}}`) to order terms. A
`nulls` equal to the canonical default (`first` for asc, `last` for desc) is dropped; a
well-formed non-default placement raises `UnsupportedSortNulls`. A *present* `nulls` key
must hold exactly `"first"` or `"last"` — a wrong type, an explicit `null`, or an unknown
word is `InvalidRequest`; omitting the key is the canonical default.

### `bloomery.planner.parse_page_json(payload) -> int | None`

Pagination documents (`{"limit": …, "offset": …}`) to the request limit. Non-zero
offsets and cursor keys (`after`/`before`) raise `UnsupportedPagination`; a malformed
payload — a non-mapping document, an unknown key, a non-int `limit`/`offset` — raises
`InvalidRequest`.

### `bloomery.planner.KNOWN_UNSUPPORTED: frozenset[str]`

The closed refusal list: exactly the `.reason` codes the three parse functions can
raise, drift-guarded by test. Adapters assert their refusal handling covers this set.

### `LruManifestHydrator(naming, *, max_entries=500, fetch_l2=None, prewarm=False)`

The default in-process manifest cache behind the planner: an LRU of hydrated semantic
manifests keyed by `HydrationKey`. On a miss it consults the caller-injected
`fetch_l2` callable (your storage, your I/O), falling back to rebuilding from the IR.
`hits`/`misses`/`hit_rate` are plain counters to poll into your metrics system.
**`.get(ir)`** returns the hydrated lookup for a project.

### `HydrationKey`

The cache key covering all three invalidation axes: `spec_fingerprint`,
`bloomery_version`, `metricflow_version`. A spec edit or a version bump changes the
key, so stale entries are a miss, never an error.

### Thread safety

The advice elsewhere in these docs — build the planner once and reuse it — means, in a
web service, shared across threads. The contract that makes that sound:

- **`MetricFlowPlanner` is safe to share.** Its instance state is set at construction
  and only read afterwards; `plan()` takes everything else as arguments. Concurrent
  `plan()` calls on one shared planner are exercised by test
  (`tests/unit/test_runtime/test_hydration.py`) and return identical plans.
- **`LruManifestHydrator` is safe to share.** The cache is `functools.lru_cache`,
  whose internal state is lock-protected in CPython, and a manifest is hydrated as a
  pure function of `(key, ir)` — the cross-thread cache-poisoning bug that motivated
  that shape is regression-tested.
- **A cold miss is not deduplicated.** Threads missing the same key concurrently each
  hydrate (and each call `fetch_l2`) — pinned by test, forced rather than raced for.
  The results are identical, so this costs duplicate work on a cold key, never wrong
  answers.
  If your `fetch_l2` is expensive, put single-flight deduplication inside it; bloomery
  will not call your I/O under a lock it owns.
- **`fetch_l2` must be thread-safe.** It is caller-owned I/O, invoked concurrently
  and never serialized by bloomery.

What is *not* promised: mutating a `NamingPolicy` or registering transforms
(`register_transform`) while other threads compile or plan. Registration is
process-global and intended for import time.

## Schema export

### `spec_json_schema(kind: SpecKind) -> JsonDict`

The JSON Schema for one spec kind, generated from the Pydantic model so it cannot drift
from the parser. Deterministic (sorted keys), addressable (`$schema` plus a
version-carrying `$id`), and faithful to the *authored* shape rather than the parsed
one. See [JSON Schema](json-schema.md).

### `all_spec_schemas() -> Mapping[SpecKind, JsonDict]`

Every kind's schema, in `SpecKind` order — six standalone documents, not a bundle.

### `SpecKind`

The six loadable kinds: `CATALOG`, `ENTITY_MODEL`, `MAPPING`, `MARTS`, `METRICS`,
`STEPS`. A string enum, so `spec_json_schema("metrics")` also works.

### `JsonDict`

One JSON Schema document — `dict[str, object]`. A schema is produced to be serialized,
not indexed.

## Extension points

### `register_transform(spec: TransformSpec) -> None`

Register an extension transform into the process-global overlay consulted after the
built-in whitelist. Name collisions raise `TransformRegistrationError`. See
[Transforms](transforms.md#custom-transforms).

### `register_emitter(emitter: TargetEmitter) -> None`

Register an extension target emitter; the emitter's `name` becomes a valid `target=`
string for `compile_project`. Collisions raise `EmitError`.

## Supporting types

Signature closure puts every type named above in the root namespace, so none of them needs
a deep import:

| Group | Names |
| --- | --- |
| Specs and IR | `Project`, `Catalog`, `ProjectIR`, `UnreachableMetric` |
| Compilation | `EmittedArtifact`, `ArtifactKind`, `TargetEmitter`, `NamingPolicy`, `DefaultNaming` |
| Analysis | `Resolution`, `FieldProvenance`, `Provenance`, `Node`, `NodeKind`, `Graph`, `Edge`, `Lineage`, `Direction`, `OpenDecision`, `Gap`, `RecipeOption` |
| Planner | `Clause`, `Scalar`, `Explanation`, `MeasureExplanation`, `ColumnRole`, `OrderDirection` |
| Steps | `StepRegistry`, `StepManifest`, `EMPTY_REGISTRY` |
| Transforms and types | `TransformSpec`, `ArgKind`, `Builder`, `OutputType`, `LogicalType` |
| Schema export | `SpecKind`, `JsonDict` |
| Fix suggestions | `MartCoverage`, `MeasureRef` |

`Project`, `Catalog` and `ProjectIR` are **handles**: you receive one and pass it back.
Their fields are internal and change freely — read `Resolution` or `QueryPlan` instead.

## Errors

### `BloomeryError`

The base of every error the package raises — `str(exc)` is the human message,
`exc.source_path` addresses the offending spec node, `exc.collected` holds individual
failures on batched aggregates. The full tree lives in [Errors](errors.md).

Five refusals also carry a structured fix suggestion — `UnknownMember.did_you_mean`,
`UnreachableAtGrain.covering_marts`, `GrainViolation.offending_measures`,
`UnknownStep.available_versions`, `UnsupportedFilter.nearest_supported` — each exposing a
value bloomery already computed on its way to writing the message. The two payload types
`MartCoverage` and `MeasureRef` are exported from the root. See
[Errors](errors.md#fix-suggestions).

## Command line

`bloomery compile|plan|resolve|explain|schema|fingerprint` is a thin argument shell over
exactly the functions above — no logic of its own, no execution, no state. It is the only
part of the package that touches a filesystem, and nothing in the library imports it. See
[Use the CLI](../how-to/use-the-cli.md).
