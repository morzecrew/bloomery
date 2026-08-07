# API

The public API — everything importable from `bloomery`, kept in lockstep with the
package's `__all__`. Supporting types named in signatures (`Project`, `Catalog`,
`ProjectIR`, `EmittedArtifact`, naming policies) live in their subpackages and are
stable to import from there.

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

### `compile_project(project, *, target, dialect, naming=None, catalog=None) -> tuple[EmittedArtifact, ...]`

Compile a parsed project into target artifacts — the whole pipeline (resolve,
typecheck, guardrails, lower, emit) as one pure function. `target` is a `Target` or
the string name of a registered extension emitter; `dialect` is `"duckdb"`,
`"trino"`, or `"postgres"`; `naming` defaults to layer-based naming
(`silver.<entity>`, `gold.mart_<name>`). Same specs in, byte-identical artifacts out.
Each `EmittedArtifact` carries `path`, `content`, `kind`, and `checksum`.

### `Target`

The shipped emit targets: `Target.SQLMESH`, `Target.CUBE`, `Target.DBT`. A string
enum, so `target="sqlmesh"` also works.

## Analysis

### `resolve(project: Project, catalog: Catalog | None = None) -> Resolution`

Run reference validation, recipe validation, and reachability without emitting
anything. The `Resolution` carries `reachable_metrics`, `unreachable_metrics` (each
with its specific missing leaves), per-field `provenance` (direct / recipe / native),
and the deterministic topological order.

### `build_project_ir(project: Project, catalog: Catalog | None = None) -> ProjectIR`

Compile specs into the frozen intermediate representation without emitting — the
input to `project_fingerprint`, `plan`, and `MetricFlowPlanner.plan`. Runs the same
resolution, typecheck, and guardrail stages as `compile_project`, so a spec that
builds an IR is a spec that compiles.

### `project_fingerprint(ir: ProjectIR) -> str`

The `blm1:`-prefixed SHA-256 content hash of a project IR — the value stamped into
every emitted artifact's header. Stable within a bloomery version, deliberately not
across versions.

## Spec-diff planning

### `plan(old: ProjectIR | None, new: ProjectIR) -> Plan`

Diff two compiled IRs into a classified migration plan. `plan(None, new)` is the
initial deploy; `plan(ir, ir)` is empty. Raises `RenameTargetMissing` on a stale
`renamed_from` annotation and `ContractViolation` on an expand/contract breach; every
other change, breaking included, is classified and returned. See
[Evolve a spec safely](../how-to/evolve-a-spec.md).

### `Plan`

`changes` (sorted `Change` tuple), `backfill_scope` (`BackfillScope`), and
`downstream_impact` (affected metric names). Properties: `has_changes`, `breaking`.

### `Change`

One classified difference: `entity`, `subject` (`<kind>:<name>`), `change_class`,
human-readable `detail`, and compact `old`/`new` value reprs.

### `ChangeClass`

The closed classification vocabulary: `ADDITIVE`, `WIDENING`, `RENAME`, `RESTATING`,
`BREAKING`.

### `BackfillScope`

`entities` — the sorted entities whose stored rows a plan invalidates — and
`restates_history`, true when any RESTATING change is present.

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

One output column in bloomery names: `name`, logical `type`, `role`
(`"dimension"` or `"measure"`), optional `label`.

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
wherever it says something useful — the form the document had reached for the two
post-rewrite refusals, and a size sentinel (`>64 levels deep`, `>64 clauses`) for the two
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

## Extension points

### `register_transform(spec: TransformSpec) -> None`

Register an extension transform into the process-global overlay consulted after the
built-in whitelist. Name collisions raise `TransformRegistrationError`. See
[Transforms](transforms.md#custom-transforms).

### `register_emitter(emitter: TargetEmitter) -> None`

Register an extension target emitter; the emitter's `name` becomes a valid `target=`
string for `compile_project`. Collisions raise `EmitError`.

## Errors

### `BloomeryError`

The base of every error the package raises — `str(exc)` is the human message,
`exc.source_path` addresses the offending spec node, `exc.collected` holds individual
failures on batched aggregates. The full tree lives in [Errors](errors.md).
