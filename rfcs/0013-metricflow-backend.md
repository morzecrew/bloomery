# RFC 0013 — MetricFlow backend: manifest emitter and planner adapter

- **Status:** ✅ Complete — shipped 2026-08-07 (M6–M7, hydration consumed per
  RFC 0014 at M8): `emit_manifest`, `MetricFlowPlanner` with coverage precheck,
  `names.py`, fuzz-tested filters, the row-policy AST tests, and the version-drift
  canary — R1–R9 all landed; the R10 three-way equivalence oracle is deliberately
  RFC 0009's nightly containerized tier and is tracked there (🚧), not here — this
  RFC's own design surface is fully shipped. M4.5 verification (V1–V4) ALL PASS
  (2026-08-07): [`spikes/metricflow/VERIFICATION.md`](../spikes/metricflow/VERIFICATION.md).
  Amended 2026-08-07 for the one discovered upstream nondeterminism (ratio
  `input_measures` via a builtin set in MetricFlow's `transform()` — re-sorted
  post-transform; §5.2 amendment, D15).
- **Scope:** Replaces the hand-written lowering half of RFC 0011 with an embedded MetricFlow
  backend: a new emitter `bloomery/emit/metricflow/` (IR → `PydanticSemanticManifest`), the
  reshaped `bloomery/planner/` (coverage precheck, name bridging, filter rendering, the
  `MetricFlowPlanner` adapter, dataflow-plan explanations), and
  `bloomery/runtime/sql_client.py` (`RenderOnlySqlClient`, dialect→renderer map). **No
  contract changes:** `MetricRequest`/`QueryPlan`/`ColumnDescriptor`/`Explanation` and the
  refusal policy of RFC 0011 survive verbatim — only what stands behind them changes.
  Reverses RFC 0008 D6 (date dimension). Does not cover manifest hydration/caching — that is
  RFC 0014 (superseding RFC 0012).
- **Related:** [`rfcs/_bloomery-metricflow-pivot.md`](_bloomery-metricflow-pivot.md) (source,
  R1–R10, §6–§7); RFC 0011 (the contract this backend implements), RFC 0010 (marts — the
  emission source), RFC 0008 (ports; D6 reversed here), RFC 0006 (additivity *policy* stays
  in guardrails), RFC 0009 (equivalence, amended three-way), RFC 0002 (error taxonomy),
  RFC 0001 (dependencies, requires-python), RFC 0014 (hydration).
  [MetricFlow](https://github.com/dbt-labs/metricflow), Apache 2.0.
- **Origin:** Empirical spike (pivot doc §2) proving `metricflow==0.211.0` runs as an
  embedded render-only library; lands in-repo as `spikes/metricflow/` before R1/R2.

---

## 1. Summary

MetricFlow is embedded as a render-only planning library behind RFC 0011's unchanged
`Planner` port. A pure emitter maps `ProjectIR` marts to a `PydanticSemanticManifest`;
`MetricFlowPlanner` runs the mart-coverage precheck (refusal policy first), translates the
request into MetricFlow names, calls `engine.explain()` — which never executes — and
translates the result back into a `QueryPlan` in bloomery names with a structured
`Explanation`. RFC 0011's SQLGlot assembly, additivity lowering, and standalone mart
selection are superseded and deleted. Nothing merges until verification tasks V1–V4 (§10)
are answered in writing.

## 2. Motivation

RFC 0011 D3/D5 specified hand-writing additivity lowering and SQL assembly — the hardest
correctness work in the package, ~1.5–2.5k lines. A spike proved that unnecessary:
`metricflow` plans ratio recomputation, semi-additive windows, role-played time dimensions,
granularity, cumulative/derived metrics, and ships seven dialect renderers — driven entirely
in-process, with no dbt project, no adapter, no dbt-core, no database connection. Three
verified facts make it work, none obvious from the README: **(a)** the wheel vendors
`metricflow_semantic_interfaces/` — core requires jinja2/pydantic/sqlglot etc., not dbt;
**(b)** the manifest is a plain Pydantic object constructible in code and accepted by
`SemanticManifestLookup` directly; **(c)** `SqlClient` is a Protocol and `explain()` never
executes — a stub raising `NotImplementedError` on `query`/`execute`/`dry_run` renders SQL.

Measured on a realistic tenant (30 semantic models / 90 metrics / 145 KB JSON): **~29 ms
cold hydration**, **~1.6 MB resident per hydrated tenant**, ~12 ms per `explain()`. Cube's
documented per-tenant footprint is 5–40 MB resident — 1.6 MB at 29 ms settles the scaling
question RFC 0011 §2 raised against external layers, without giving up in-process purity.

## 3. Current state

RFC 0011 is Draft; its `bloomery/planner/` would hold `request.py`, `select.py`, `build.py`,
`additivity.py`, `policy.py`, `explain.py`. M1–M4 (spec, IR, resolve, typecheck, guardrails)
are untouched and must be green first. RFC 0010's `MartIR`/`DimensionRef` become the
emission source for semantic models. The additivity *policy* half (compile-time refusal of
stored non-additive measures, `GrainViolation`) stays in `guardrails/` per RFC 0006 —
MetricFlow lowers additivity, it does not stop wrong modelling. The pivot doc §2 reference
implementation runs today against `metricflow==0.211.0` and records the gotchas: mandatory
`PydanticSemanticManifestTransformer.transform()` — verified: skipping it fails **loudly**
(`MetricFlowInternalError: A simple metric is missing 'metric_aggregation_params'` at
`explain()` time), not by silent misresolution as the pivot doc feared; factory is
`MetricFlowQueryRequest.create`;
SQL at `explain_result.sql_statement.sql`; group-by names keyed on the primary *entity*, not
the model name; a time spine required for any `metric_time__*`.

## 4. Goals / Non-goals

**Goals**

- `emit_manifest(ir, *, naming) -> PydanticSemanticManifest`: pure, deterministic,
  tenant-agnostic, golden-tested per fixture.
- `MetricFlowPlanner` satisfying RFC 0011's `Planner` port with identical types and refusal
  semantics; MetricFlow types never cross the port boundary.
- Fuzz-proven injection safety for the Jinja `where_constraints` surface — the highest-risk
  part of this pivot.
- A version-drift canary, since we depend on internals with no stability guarantee.

**Non-goals**

- Execution — unchanged from RFC 0011; `RenderOnlySqlClient` makes it impossible by
  construction.
- Hydration/caching of `SemanticManifestLookup` — RFC 0014's subject; this RFC consumes a
  `ManifestHydrator` protocol and defines nothing behind it.
- Multi-hop join planning — MetricFlow can; we refuse first (§5.4). Policy, not limitation.
- The Cube emitter — unchanged (RFC 0008); still built, still the equivalence oracle.

## 5. Design

### 5.1 What is superseded, and the boundary that makes it reversible

RFC 0011's algorithm steps 3–4 (additivity lowering, SQLGlot assembly) and mart selection as
its own module are superseded. The planner package reshapes to:

```
bloomery/planner/
  request.py             KEEP — MetricRequest, FilterExpr, OrderSpec, TimeGrain (RFC 0011 D2)
  result.py              KEEP — QueryPlan, ColumnDescriptor, Explanation
  coverage.py            NEW  — mart coverage precheck, runs BEFORE delegation (§5.4)
  names.py               NEW  — bloomery names <-> MetricFlow dunder names (§5.5)
  filters.py             NEW  — FilterExpr -> where_constraints, safely (§5.6, §5.7)
  metricflow_planner.py  NEW  — the adapter (§5.3)
  explain.py             REWRITTEN — from the dataflow plan (§5.8)
  ---- DELETE ----
  select.py              (selection folded into coverage.py + delegated)
  build.py               (SQLGlot assembly — MetricFlow does this)
  additivity.py          (lowering — MetricFlow; policy stays in guardrails/, RFC 0006)
  policy.py              (folded into filters.py)
bloomery/emit/metricflow/       NEW — emit_manifest (§5.2)
bloomery/runtime/sql_client.py  NEW — RenderOnlySqlClient + dialect->renderer map (§5.3)
```

If the DELETE-list modules already contain work, delete it — no second implementation kept
"just in case"; an unexercised planner is a liability, and the Cube equivalence suite is the
second opinion. Salvage only their test fixtures.

The seam: **`MetricRequest`/`QueryPlan`/`ColumnDescriptor`/`Explanation` do not change.**
The Query Agent and serving layer bind to them, never to MetricFlow. Exceptions are
translated at the adapter (`InvalidQueryException` → `UnknownMember` / `UnreachableAtGrain`
/ `AmbiguousDimension`, RFC 0002 taxonomy) so callers never catch a MetricFlow class. That
seam is what makes the backend swappable — reversal is an adapter rewrite, not a platform
migration.

`metricflow==0.211.*` (pinned tightly) becomes a **runtime** dependency. It brings
`pydantic>=1.10,<3` via an internal v1/v2 shim; its manifest objects expose v1-style APIs
(`.json()`, `.parse_raw()`) while bloomery's models stay pydantic v2 — V1 (§10) proves
coexistence. If MetricFlow's supported Python range is narrower than bloomery's
`>=3.12,<3.15`, `requires-python` narrows to match and RFC 0001 is amended — V1 answers
this too.

### 5.2 `emit_manifest` — IR → `PydanticSemanticManifest`

```python
def emit_manifest(ir: ProjectIR, *, naming: NamingPolicy) -> PydanticSemanticManifest: ...
```

Pure, deterministic, tenant-agnostic — the same invariants as every emitter (RFC 0008):

| bloomery IR | MetricFlow |
|---|---|
| `MartSpec` | `PydanticSemanticModel` |
| `MartSpec.name` | `.name` |
| `NamingPolicy.relation(mart, Layer.GOLD)` | `PydanticNodeRelation(schema_name=…, alias=…)` |
| mart's grain entity | `PydanticEntity(type=PRIMARY, expr=<key column>)` |
| flattened FK columns worth joining on | `PydanticEntity(type=FOREIGN, …)` |
| `DimensionRef(dim, role=None)`, categorical | `PydanticDimension(type=CATEGORICAL)` |
| `DimensionRef(dim, role="shipped")`, temporal | `PydanticDimension(name="shipped_at", type=TIME, type_params=…(time_granularity=DAY))` |
| measure, `Additivity.ADDITIVE` | `PydanticMeasure(agg=SUM/COUNT/…, expr=…, agg_time_dimension=…)` |
| measure, `SEMI_ADDITIVE` + `SemiAdditivePolicy(over, rule)` | `PydanticMeasure(non_additive_dimension=PydanticNonAdditiveDimensionParameters(name=over.qualified, window_choice=MAX\|MIN, window_groupings=…))` |
| measure, `NON_ADDITIVE` + `RatioSpec` | `PydanticMetric(type=RATIO, type_params=(numerator, denominator))` — **never a measure** |
| simple metric | `PydanticMetric(type=SIMPLE, type_params=(measure=…))` |
| expression metric over metrics | `PydanticMetric(type=DERIVED, type_params=(expr, metrics))` |
| running / period-to-date metric | `PydanticMetric(type=CUMULATIVE, type_params=(window \| grain_to_date))` |
| catalog date dimension | `PydanticProjectConfiguration(time_spines=[PydanticTimeSpine(...)])` |
| metric `description` | `.description` — carried; it grounds the Query Agent |

Enum surfaces: `AggregationType` (sum, min, max, count_distinct, sum_boolean, average,
percentile, median, count); `MetricType` (simple, ratio, cumulative, derived, conversion);
`DimensionType` (categorical, time); `EntityType` (primary, foreign, unique, natural);
`TimeGranularity` (nanosecond…second, minute, hour, day, week, month, quarter, year).
`SemiAdditivePolicy.rule` maps `last → MAX`, `first → MIN`; **`avg`/`max`/`min` are not
expressible** via `non_additive_dimension` — `UnsupportedByTarget` naming the rule
(RFC 0008 D3 fail-loud).

Rules: **(1)** one mart = exactly one semantic model, and never a semantic model for a
non-materialized entity — that would reintroduce the query-time joins the mart design
(RFC 0010) exists to prevent; set `primary_entity` when the grain has no single natural key
column. **(2)** every measure carries `agg_time_dimension`; a martless time dimension is
`MartMissingTimeDimension`, a new `GuardrailError` leaf (RFC 0006 stage, declared per
RFC 0002 D3) — MetricFlow requires it and its own failure is obscure. **(3)** determinism:
`semantic_models`, `metrics`, `measures`, `dimensions`, `entities` all sorted
lexicographically before construction — the manifest is hashed and cached (RFC 0014);
ordering drift would silently defeat the cache. **(4)** the time spine comes from the
catalog date dimension:

**The date dimension is resolved — bloomery owns it.** MetricFlow requires a declared time
spine for any `metric_time__*` group-by. The catalog defines the date dimension **once**;
the SQLMesh emitter builds `gold.dim_date` from it, and `emit_manifest` points
`PydanticTimeSpine` at that same relation. **This reverses RFC 0008 D6** ("date dimension
not emitted in v0.1, demand-gated") — the demand arrived; RFC 0008 is amended in parallel.
One definition, two emissions, no drift.

> **Amendment (2026-08-07, discovered during M6).** Rule (3)'s "all collections sorted
> before construction" is necessary but not sufficient: MetricFlow's **own**
> `PydanticSemanticManifestTransformer.transform()` reintroduces nondeterminism — its
> `AddInputMetricMeasuresRule` collects each metric's `input_measures` through a builtin
> `set`, so their order is hash-seed dependent, surfaced by any RATIO metric (two input
> measures). Since the emitter returns the *post-transform* manifest (what RFC 0014 D3
> caches and RFC 0009 golden-byte-compares), `emit_manifest` re-sorts
> `metric.type_params.input_measures` by measure name **after** `transform()`
> ([`emit/metricflow/__init__.py`](../src/bloomery/emit/metricflow/__init__.py)) —
> otherwise ordering drift would flake goldens and silently defeat the hydration cache.
> Recorded as D15.

### 5.3 The adapter and the render-only client

`bloomery/runtime/sql_client.py`:

```python
class RenderOnlySqlClient(SqlClient):
    """Renders SQL. Cannot connect to anything, by construction."""
    def __init__(self, engine: SqlEngine, renderer): self._e, self._r = engine, renderer
    @property
    def sql_engine_type(self): return self._e
    @property
    def sql_plan_renderer(self): return self._r
    def query(self, *a, **k):   raise NotImplementedError("render-only")
    def execute(self, *a, **k): raise NotImplementedError("render-only")
    def dry_run(self, *a, **k): raise NotImplementedError("render-only")
    def close(self): pass
    def render_bind_parameter_key(self, key): return f"${key}"
```

plus a dialect-name → renderer mapping (all seven renderers — duckdb, trino, postgres,
snowflake, bigquery, databricks, redshift — ship in-package).
`bloomery/planner/metricflow_planner.py`:

```python
class MetricFlowPlanner:
    def __init__(self, hydrator: ManifestHydrator, sql_clients: Mapping[str, SqlClient]): ...

    def plan(self, ir, request, *, dialect: str, policy: RowPolicy | None = None) -> QueryPlan:
        coverage.check(ir, request)                        # §5.4 — refuse before delegating
        lookup = self._hydrator.get(ir)                    # RFC 0014 — LRU by fingerprint
        engine = MetricFlowEngine(lookup, self._sql_clients[dialect])   # cheap (~4 ms)
        mf_req = MetricFlowQueryRequest.create(
            metric_names      = names.to_mf_metrics(request.metrics),
            group_by_names    = names.to_mf_group_by(request.dimensions, request.time_grain),
            where_constraints = filters.to_where(request.filters, policy),   # §5.6, §5.7
            order_by_names    = names.to_mf_order(request.order_by),
            limit             = min(request.limit or DEFAULT_LIMIT, MAX_LIMIT),
        )
        try:
            result = engine.explain(mf_req)                # never executes
        except InvalidQueryException as e:
            raise translate_mf_error(e) from e             # → bloomery taxonomy, §5.1
        return QueryPlan(
            sql=result.sql_statement.sql,
            columns=names.columns_from(result.query_spec),
            mart=mart_of(result.dataflow_plan), warnings=(),
            explanation=explain.from_dataflow(result),     # §5.8
            fingerprint=sha256(result.sql_statement.sql),
        )
```

### 5.4 Coverage precheck — the refusal policy, preserved

The most important carry-over from RFC 0011. MetricFlow will happily plan a multi-hop join
across semantic models; our marts design says a cross-grain request is *refused*, not
silently answered. So `coverage.check(ir, request) -> str` runs before MetricFlow sees
anything: **(1)** all requested measures on **one** mart, else `UnreachableAtGrain` with
RFC 0011 §5.3's exact per-metric grain/mart message ("Summing across grains would
double-count. Request them separately, or define a mart at the shared grain."); **(2)** all
requested dimensions flattened onto it; **(3)** multiple candidates → cheapest `cost_hint`,
ties lexicographic (RFC 0010 D8). Refuse-don't-guess is now enforced twice — us at
coverage, MetricFlow's own resolver second. Belt and braces. The planner's `Feature` set
(RFC 0008 vocabulary, gaining `CUMULATIVE`/`DERIVED_METRIC`) documents `QUERY_TIME_JOIN` as
**disabled by policy, not a limitation**, so nobody "fixes" it.

### 5.5 Name bridging

MetricFlow uses dunder names keyed on the **primary entity** — a gotcha: a model named
`orders` with primary entity `order` yields `order__carrier`, not `orders__carrier`.
`planner/names.py` owns the bidirectional mapping: `{entity}__{dim}`,
`{entity}__{time_dim}__{grain}`, `metric_time__{grain}`, `-{metric}` for descending order.
Callers never see dunder names — `columns_from(query_spec)` returns `ColumnDescriptor`s in
bloomery names (`shipped_date` with `grain=month`, never `order_item__shipped_at__month`).
`DimensionRef.role` maps onto the flattened dimension name consistently with §5.2 — the
emitter and the bridge must agree, enforced by a property test: every dimension the emitter
produces round-trips through `names.py`. `metric_time` is reserved; a tenant dimension so
named is rejected at spec-validation time with a clear message.

### 5.6 Filters — the highest-risk surface

MetricFlow's `where_constraints` are **Jinja-templated strings**
(`"{{ Dimension('order_item__carrier') }} = 'DHL'"`) — string construction on the query
path. Non-negotiable: **(1)** `FilterExpr` values are never interpolated raw — literals go
through a typed per-dialect renderer that quotes and escapes, or through
`render_bind_parameter_key`; **(2)** the dimension name inside `{{ Dimension(...) }}` comes
only from a validated `DimensionRef` via `names.py` — never from user input, never from an
LLM; **(3)** values are type-checked against the dimension's declared type before rendering
— a string for a numeric dimension is `FilterTypeMismatch` (new `PlannerError` leaf), not a
cast; **(4)** `contains`/`like` escape wildcards; **(5)** an adversarial property-based
fuzz test (`' OR 1=1 --`, `{{ Dimension('x') }}`, unicode quote variants, embedded
newlines) asserts via sqlglot that the parsed SQL's predicate structure is unchanged and
the scanned relations are exactly the expected mart. **Merge-blocking.**

### 5.7 Row policy

`RowPolicy` stays a value object (RFC 0011 D7 tenant-agnosticism unchanged), applied as an
additional where-constraint always **prepended** to user filters in `filters.to_where`.
RFC 0011 D10's row-policy-survives-every-path test survives verbatim and stays
merge-blocking — asserted on the parsed AST (predicate present in every table scan), never
a substring — now explicitly covering ratio, semi-additive, and cumulative requests, which
generate **multiple subqueries** over the mart (the semi-additive plan emits an
`INNER JOIN` against a `MAX(...)` subquery); the predicate must appear in every scan.
**V4** (§10) verifies MetricFlow actually pushes where-constraints into inner scans; if it
does not, that is a **security defect** for us, and the escape hatch — named, not built —
is tenant-filtered node relations emitted per tenant: a change to §5.2, not to the approach.
*(V4 answered PASS, 2026-08-07: the predicate reaches every scan pre-aggregation — both
semi-additive branches and the ratio plan; note the AST test must assert "predicate present
in **every** scan", not "in both component subqueries" — under the default optimization
level the ratio collapses to one shared scan. See §5.9.)*

### 5.8 Explanations

Built from the **structured** `MetricFlowExplainResult.dataflow_plan` and `.query_spec` —
typed objects — never scraped from the SQL comments MetricFlow also emits (comments are a
rendering detail and change between versions). Output shape unchanged from RFC 0011 §5.6,
translated back into bloomery names via `names.py`; `render()` output locked by goldens.

### 5.9 Verified implementation notes (M4.5 amendment, 2026-08-07)

Facts established by the verification spike
([`spikes/metricflow/VERIFICATION.md`](../spikes/metricflow/VERIFICATION.md)), binding for
R1–R10 implementation:

- **(a) MSI-internal circular import.**
  `metricflow_semantic_interfaces.implementations.node_relation` must **not** be the first
  `metricflow_semantic_interfaces` import — as the first MSI import it raises
  `ImportError: cannot import name 'NodeRelation' from partially initialized module`
  (circular import via `protocols`). `emit/metricflow` must order its imports so a module
  that finishes `metricflow_semantic_interfaces.protocols` loads first (e.g.
  `…implementations.semantic_manifest`), with a comment saying why.
- **(b) Top-level shim module.** The metricflow wheel installs a **top-level**
  `msi_pydantic_shim.py` at site-packages root — global-namespace pollution to account for
  in deptry/vulture configuration (RFC 0001).
- **(c) Escape-hatch shape.** `PydanticNodeRelation` has **no `sql` field** (only `alias`,
  `schema_name`, `database`, `relation_name`) — the §5.7/§8 escape hatch, if ever needed,
  is a **per-tenant filtered VIEW name** (verified working end-to-end), never an inline SQL
  body.
- **(d) Row-policy AST test wording.** The §5.7 test asserts "predicate present in
  **every** scan", not "in both component subqueries" — the optimizer may collapse a ratio
  to one shared scan (verified: the predicate reaches every scan pre-aggregation in both
  semi-additive branches and in the ratio plan).

## 6. Tests

- **Golden:** `tests/golden/<fixture>/metricflow/manifest.json` per fixture, serialized
  with sorted keys, reviewed like source. Emitted-SQL goldens stay, but a SQL diff on a
  MetricFlow version bump is *review*, not *failure*, provided execution tests pass —
  execution tests are the real gate.
- **Execution (primary correctness gate):** the RFC 0009/0011 fixture numerics survive
  unchanged — inventory 90 not 270; 130 across warehouses; AOV 2727.27 never 6000/12000 —
  now testing **our mapping into MetricFlow** (a wrong `window_choice`, or a measure
  emitted where a ratio metric belonged, fails here).
- **Equivalence:** now **three-way** — MetricFlow ↔ Cube ↔ hand-written reference SQL for
  the ~15 hardest cases (the tiebreaker when two engines disagree); RFC 0009 amended.
- **Property:** emitter-dimension ↔ `names.py` round-trip (§5.5); filter fuzzing (§5.6)
  and policy-AST (§5.7), both merge-blocking.
- **Canary:** `test_metricflow_api_surface` asserts the internals we depend on
  (`MetricFlowQueryRequest.create`, `MetricFlowExplainResult.sql_statement`,
  `SemanticManifestLookup`, the `SqlClient` members) still exist — turning silent breakage
  into loud.
- **Removed:** unit tests for `build.py`/`additivity.py` lowering/`select.py`; fixtures
  salvaged.

## 7. Docs

RFC 0011 §7 pages update in place: the refusal explanation gains the twice-enforced
framing; a new explanation page covers the render-only embedding (what MetricFlow does and
does not replace, pivot doc §1.4) with the honesty caveat that we sit on unsupported
internals; the `QUERY_TIME_JOIN` capability docstring wording ("deliberate policy, not
limitation") is load-bearing.

## 8. Out of scope

- **Hydration and caching** (`runtime/hydration.py`, `HydrationKey`, L1/L2 cache, budgets)
  — RFC 0014, superseding RFC 0012. This RFC only consumes `ManifestHydrator`.
- **`PydanticSavedQuery` for hot dashboard queries** — possible caching win; deferred until
  after M11 and real usage data.
- **Per-tenant filtered node relations** — the V4 escape hatch, built only if V4 fails.
  *(V4 passed; stays unbuilt. If ever needed its shape is known — a per-tenant filtered
  view name, not an inline SQL body: `PydanticNodeRelation` has no `sql` field, §5.9.)*

## 9. Risks

- **We depend on non-public internals** (`MetricFlowEngine`, `SemanticManifestLookup`,
  `SqlClient`; `metricflow_semantics.api.v0_1` holds only a saved-query resolver — no
  versioned embedder API exists). *High.* Pin `metricflow==0.211.*`; canary test; upgrades
  are deliberate PRs with goldens regenerated and reviewed.
- **dbt Labs' roadmap** serves the dbt Semantic Layer; embedded use is unsupported.
  *Medium.* Apache 2.0 + vendored interfaces make a fork viable; the
  `MetricRequest`/`QueryPlan` boundary makes a swap an adapter rewrite.
- **Semi-additive grouping defect** — issue #241 reported grouping *by* the non-additive
  dimension filters to first/last instead of the full series; old, may be fixed. *High if
  unfixed* — "balance by warehouse by month" is a query users will run. Gated on V2.
  **RETIRED (V2 PASS, 2026-08-07): fixed in 0.211.0** — by-month grouping returns one
  last-value row per month (three rows over three months, verified against executed
  DuckDB). The version-drift canary stays: the fix is verified only at this pin.
- **pydantic v1-shim/v2 coexistence.** *Medium.* Gated on V1. **Verified clear (V1 PASS,
  2026-08-07):** joint resolution and coexistence confirmed on Python 3.12/3.13/3.14 in
  both import orders, no metaclass conflicts, no `requires-python` change.
- **Jinja where-constraints** — string construction on the query path. *High.* §5.6,
  fuzz-tested, merge-blocking.
- **SQL churn between MetricFlow versions** breaking goldens. *Low.* Execution tests are
  the real gate; goldens are review aids (§6 doctrine).
- **Hydration cost on larger models** — 30 models measured; some tenants are bigger.
  *Medium.* Gated on V3; budgets live in RFC 0014.

## 10. Unresolved questions

Verification tasks V1–V4 form milestone **M4.5 — merge nothing until all four are answered
in writing** (budget two–three days; the reference implementation lands as
`spikes/metricflow/` first): **V1** dependency coexistence in the real environment
(pydantic v1-shim/v2, import order, metaclasses — and MetricFlow's supported Python range
vs `>=3.12,<3.15`, deciding the RFC 0001 amendment); **V2** semi-additive grouping against
DuckDB with real rows, including the issue-#241 three-row by-month case; **V3** hydration
at real tenant scale (informs RFC 0014's budgets); **V4** row policy present in every inner
scan of ratio/semi-additive SQL (blocking any production use; failure triggers §5.7's
escape hatch). Implementation-settled: the exact `translate_mf_error` classification table;
which flattened FK columns are "worth" FOREIGN entities.

**Answered (2026-08-07): V1–V4 ALL PASS** —
[`spikes/metricflow/VERIFICATION.md`](../spikes/metricflow/VERIFICATION.md) is the written
record; the M4.5 gate is cleared (facts folded into §3, §5.7, §5.9, §9, D14).

## 11. Decisions

| # | Decision |
| --- | --- |
| 1 | RFC 0011's hand-written lowering (algorithm steps 3–4: additivity lowering + SQLGlot assembly) and mart selection as its own module are **superseded**: MetricFlow (Apache 2.0, `metricflow==0.211.*` pinned tightly) is embedded as a render-only library — no dbt project, no adapter, no dbt-core, no execution. Verified: vendored semantic interfaces in the wheel; plain-Pydantic manifest constructible in code; `SqlClient` is a Protocol and `explain()` never executes (`RenderOnlySqlClient` raises `NotImplementedError` on query/execute/dry_run). Motivating numbers: ~29 ms cold hydration, ~1.6 MB/tenant vs Cube's 5–40 MB. |
| 2 | `MetricRequest`/`QueryPlan`/`ColumnDescriptor`/`Explanation` (RFC 0011) do **not** change — the stable API the Query Agent binds to. MetricFlow types never cross that boundary; errors are translated (`InvalidQueryException` → `UnknownMember`/`UnreachableAtGrain`/`AmbiguousDimension`). This seam is what makes the backend swappable. |
| 3 | `emit_manifest(ir, *, naming) -> PydanticSemanticManifest` is a pure deterministic emitter. One mart = exactly one semantic model; never a semantic model for a non-materialized entity (would reintroduce query-time joins). Every measure carries `agg_time_dimension`; a martless time dimension is `MartMissingTimeDimension` (new `GuardrailError` leaf). All collections sorted lexicographically before construction — the manifest is hashed/cached. Full IR→MetricFlow mapping and enum tables per §5.2. |
| 4 | `SemiAdditivePolicy.rule` maps `last → MAX`, `first → MIN`; `avg`/`max`/`min` are not expressible via `non_additive_dimension` → `UnsupportedByTarget` naming the rule. |
| 5 | **Reverses RFC 0008 D6:** bloomery owns the date dimension. MetricFlow requires a declared time spine; the catalog defines the date dimension once; the SQLMesh emitter builds `gold.dim_date` and `PydanticTimeSpine` points at it. RFC 0008 amended in parallel. |
| 6 | Mart-coverage precheck runs **before** delegation and preserves the refusal policy: all measures on one mart (else `UnreachableAtGrain` with RFC 0011's exact per-metric grain/mart message), all dimensions flattened onto it, multi-candidate → `cost_hint` then lexicographic. MetricFlow could plan multi-hop joins; we refuse first — refuse-don't-guess enforced twice (coverage, then MetricFlow's resolver). Belt and braces. |
| 7 | `planner/names.py` owns the bidirectional bloomery↔dunder mapping (`{entity}__{dim}`, `{entity}__{time_dim}__{grain}`, `metric_time__{grain}`, `-metric` for desc), keyed on the **primary entity** name (not the semantic model name). Callers never see dunder names. `metric_time` is reserved, rejected at spec validation. Property test: every emitter-produced dimension round-trips through `names.py`. |
| 8 | Filters (Jinja `where_constraints`) are the highest-risk surface: values never interpolated raw — typed per-dialect literal renderer or bind parameters; dimension names only from validated `DimensionRef`s via `names.py`; values type-checked against the dimension (`FilterTypeMismatch`); `contains`/`like` escape wildcards. Adversarial fuzz property test (injection strings, template syntax, unicode quotes, newlines) asserts parsed-SQL predicate structure unchanged and scanned relations exactly the expected mart — **merge-blocking**. |
| 9 | `RowPolicy` stays a value object, applied as an additional where-constraint always prepended to user filters. The row-policy-survives-every-path AST test survives verbatim and stays merge-blocking, now explicitly covering ratio/semi-additive/cumulative requests (multiple subqueries — the predicate must appear in every scan). V4 verifies MetricFlow pushes constraints into inner scans; if not, that is a security defect and the escape hatch is per-tenant filtered node relations (a change to D3's emitter, not the approach). |
| 10 | Explanations are built from the structured `MetricFlowExplainResult.dataflow_plan`/`query_spec`, never scraped from SQL comments; output shape unchanged from RFC 0011, translated to bloomery names. |
| 11 | Version-drift canary `test_metricflow_api_surface` is mandatory — we depend on internals with no stability guarantee; upgrades are deliberate PRs with goldens regenerated. |
| 12 | V1–V4 form milestone M4.5: merge nothing until all four are answered in writing; the reference implementation lands as `spikes/metricflow/` first. `metricflow` becomes a **runtime** dependency; if its supported Python range is narrower than `>=3.12,<3.15`, `requires-python` narrows to match (RFC 0001 amended) — V1 answers this. |
| 13 | Planner-package DELETE list (`select.py`, `build.py`, `additivity.py`, `policy.py`): if they contain work, delete it — no second implementation kept "just in case"; salvage only fixtures. The Cube equivalence suite is the second opinion. |
| 14 | **M4.5 complete (2026-08-07): V1–V4 all answered PASS** ([`spikes/metricflow/VERIFICATION.md`](../spikes/metricflow/VERIFICATION.md)) — V1: joint resolution succeeds on Python 3.12/3.13/3.14, no `requires-python` change, v1-shim/v2 coexistence clean in both import orders; V2: issue #241 fixed in 0.211.0 (by-month returns the full series); V3: cold hydration 10.5 ms median, 1.54 MB/lookup (RFC 0014 budgets confirmed); V4: row-policy predicate in every scan pre-aggregation, escape hatch unneeded. `metricflow==0.211.*` is **confirmed** as the runtime pin — it resolves jointly with the sqlmesh dev tooling (sqlmesh 0.236.1, sqlglot stays `>=30.8,<31` resolving 30.8.0). Design cleared for implementation (M6+). |
| 15 | *(Appended 2026-08-07, M6.)* Post-`transform()` re-sort of `input_measures`: MetricFlow's `AddInputMetricMeasuresRule` collects a metric's `input_measures` through a builtin `set` (hash-seed-dependent order, surfaced by RATIO metrics), so `emit_manifest` sorts `metric.type_params.input_measures` by measure name after `transform()` — the transformed manifest is hashed, cached (RFC 0014 D5), and golden-byte-compared (R1); without the re-sort, ordering drift would flake goldens and silently defeat the cache. The determinism guarantee is therefore ours, applied *after* the upstream transform, not assumed of it. |
| 16 | *(Appended 2026-08-07, M14 — RFC 0015.)* §5.6/R6 rendering is now per-`Clause`: one `where_constraints` entry per clause, an `AnyOf` disjunction group **always** parenthesized (`policy AND a OR b` leaks every row matching `b`), policy first via `RowPolicy.as_clause()`. `like`/`ilike` operands are SQL `LIKE` patterns (caller-owned wildcards, fixed `ESCAPE '\'`; the shipped `contains` auto-`%…%` wrapping is removed); `ilike` lowers dialect-neutrally as `LOWER(x) LIKE LOWER(pattern)` (Trino has no `ILIKE`). All D8 safety rules — names only via `names.py`, typed literals, quote doubling, NUL refusal, `FilterTypeMismatch` never a cast — are unchanged and remain merge-blocking; the non-finite refusal re-homes from `FilterTypeMismatch` to `InvalidLiteral`. |

## 12. Phasing

M4.5 (V1–V4, gate for everything) → M6: `emit_manifest`, done when every fixture emits a
manifest `SemanticManifestLookup` accepts → M7: adapter + coverage + names + filters +
policy, done when all fixture numerics pass on DuckDB and the fuzz and policy-AST tests are
green → hydration/caching as RFC 0014 (M8) → three-way equivalence at M11 (RFC 0009).
M6+M7 replace the old M5 planner work; net effect is roughly a week saved, with the hardest
correctness work (additivity lowering) now someone else's tested code.
