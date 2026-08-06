# `bloomery` — MetricFlow Planner Pivot

**Document 3 of 3.** Apply *after* the original package specification and
`bloomery-changes.md` have been executed through **M4** (spec models, IR, resolve, typecheck,
guardrails).

**Supersedes:** delta **D1** (`NativePlanner`) and the *lowering* half of **D4** (additivity).
**Amends:** D5, D6, D7, D8, D10.
**Leaves untouched:** everything in the original spec, plus D2, D3, D9, and the *policy* half
of D4.

> **Do not start this document until M4 is green.** Nothing in M1–M4 is affected by it, and
> nothing done there is thrown away.

> **Note (RFC corpus):** Preserved verbatim as source material alongside
> [`_original-smelter-spec.md`](_original-smelter-spec.md) and
> [`_bloomery-changes.md`](_bloomery-changes.md). Lands in the corpus as RFC 0013
> (MetricFlow backend) and RFC 0014 (hydration, superseding RFC 0012), plus amendments to
> RFCs 0001/0002/0003/0007/0008/0009/0011. Where RFCs diverge from this document, the RFCs
> win.

---

## 1. What changed and why

### 1.1 The finding

`bloomery-changes.md` D1 specified building a `NativePlanner` — a `MetricRequest → SQL`
compiler, estimated at 1.5–2.5k lines. That work is **no longer necessary**.

`metricflow` (Apache 2.0, PyPI, v0.211.0 at time of writing) can be driven **entirely as an
embedded library**: no dbt project on disk, no dbt adapter, no database connection, no
`dbt-core` dependency. This was verified empirically, not inferred from documentation.

The three facts that make it work, none of which are obvious from the README:

**(a) MetricFlow vendors the semantic interfaces.** The wheel ships
`metricflow_semantic_interfaces/` inside it. Core `Requires-Dist` is:

```
importlib-metadata, jinja2, jsonschema, more-itertools, pydantic,
python-dateutil, pyyaml, rapidfuzz, referencing, sqlglot, tabulate, typing-extensions
```

No `dbt-core`. No `dbt-semantic-interfaces`. No adapter. The dbt coupling described in the
project README refers to the `dbt-metricflow` *bundle*, which we do not use. Note it already
depends on **sqlglot**, same as us.

**(b) The manifest is a plain Pydantic object.** `PydanticSemanticManifest(semantic_models,
metrics, project_configuration, saved_queries)` is constructible in code and
`SemanticManifestLookup(manifest)` accepts it directly.

**(c) `SqlClient` is a Protocol and `explain()` never executes.** A stub providing only
`sql_engine_type` and `sql_plan_renderer`, raising `NotImplementedError` on `query` / `execute`
/ `dry_run`, is sufficient to render SQL. All seven renderers (duckdb, trino, postgres,
snowflake, bigquery, databricks, redshift) ship inside the package.

### 1.2 What we get for free

Things D1/D4 would have required us to write, now delivered by config:

| Capability | Evidence |
|---|---|
| **Non-additive ratios** recomputed from additive components | `MetricType.RATIO` emits `CAST(revenue AS DOUBLE) / CAST(NULLIF(order_count, 0) AS DOUBLE)` over a subquery that `SUM`s components at the requested grain — never averages pre-computed averages |
| **Semi-additive measures** | `non_additive_dimension(name=…, window_choice=MAX)` emits an `INNER JOIN` on `MAX(snapshot_date)` then `SUM` across other dimensions — the "last value over time, sum across warehouses" behaviour exactly |
| **Role-playing time dimensions** | `ordered_at` and `shipped_at` as separate dimensions on one flattened mart resolve to `order_item__shipped_at__month` etc. independently and correctly |
| **Time granularity handling** | `metric_time__{day,week,month,quarter,year}` plus per-dimension grains, with a declared time spine |
| **Refuse-don't-guess** | Unresolvable group-by raises `InvalidQueryException` naming the cause — *"No valid join paths exist from the measure to the group-by-item (fan-out join support is pending)"* — with ranked suggestions. This is MetricFlow's own policy, not something we bolt on. |
| **Cumulative / derived metrics** | `MetricType.CUMULATIVE`, `MetricType.DERIVED` with windows and `grain_to_date` |
| **Seven dialects** | renderers ship in-package |

### 1.3 Measured characteristics

Benchmarked on a synthetic manifest of **30 semantic models / 90 metrics / 145 KB JSON** —
roughly a realistic tenant:

| Operation | Time | Notes |
|---|---|---|
| `PydanticSemanticManifestTransformer.transform` | ~23 ms | build-time only; cache the result |
| `PydanticSemanticManifest.parse_raw` | ~15 ms | per hydration |
| `SemanticManifestLookup(...)` | ~13 ms | per hydration — builds the semantic graph |
| **Total cold hydration** | **~29 ms** | LRU-cacheable |
| `engine.explain(...)` | ~12 ms | per query |
| Resident memory per hydrated tenant | **~1.6 MB** | measured with `tracemalloc` over 5 instances |

For comparison, Cube's documented per-tenant footprint is 5–40 MB resident. 1.6 MB with a
29 ms cold-start is the number that settles the scaling question: an LRU of a few hundred
hydrated lookups is under a gigabyte, and a miss costs 29 ms.

### 1.4 What this does *not* replace

`bloomery` is needed **more** than before, not less. MetricFlow replaces exactly one module.

| Concern | MetricFlow |
|---|---|
| Bronze→silver mappings, transform whitelist, catalog recipes | nothing |
| Derivation resolution, reachability, unit/tax/currency guardrails | nothing |
| Grain guardrail at mart-definition time (D2 validation) | nothing |
| SQLMesh model emission, spec diff, expand/contract | nothing |
| Marts (D2), role-playing modelling (D3) | nothing — but these become *what we emit into* |
| Metric→SQL planning | **replaces D1** |
| Additivity *lowering* to SQL | **replaces D4's lowering** |

---

## 2. Reference implementation

This runs today against `metricflow==0.211.0`. Land it as `spikes/metricflow/` first, confirm
it works in the repo's own dependency environment, then build R1/R2 from it.

```python
from metricflow_semantic_interfaces.implementations.semantic_manifest import PydanticSemanticManifest
from metricflow_semantic_interfaces.implementations.semantic_model import PydanticSemanticModel
from metricflow_semantic_interfaces.implementations.node_relation import PydanticNodeRelation
from metricflow_semantic_interfaces.implementations.elements.measure import (
    PydanticMeasure, PydanticNonAdditiveDimensionParameters)
from metricflow_semantic_interfaces.implementations.elements.dimension import (
    PydanticDimension, PydanticDimensionTypeParams)
from metricflow_semantic_interfaces.implementations.elements.entity import PydanticEntity
from metricflow_semantic_interfaces.implementations.metric import (
    PydanticMetric, PydanticMetricTypeParams, PydanticMetricInputMeasure)
from metricflow_semantic_interfaces.implementations.project_configuration import PydanticProjectConfiguration
from metricflow_semantic_interfaces.implementations.time_spine import (
    PydanticTimeSpine, PydanticTimeSpinePrimaryColumn)
from metricflow_semantic_interfaces.type_enums import (
    AggregationType, DimensionType, EntityType, MetricType, TimeGranularity)
from metricflow_semantic_interfaces.transformations.semantic_manifest_transformer import (
    PydanticSemanticManifestTransformer)
from metricflow_semantics.model.semantic_manifest_lookup import SemanticManifestLookup
from metricflow.protocols.sql_client import SqlClient, SqlEngine
from metricflow.sql.render.duckdb_renderer import DuckDbSqlPlanRenderer
from metricflow.engine.metricflow_engine import MetricFlowEngine, MetricFlowQueryRequest


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


order_items = PydanticSemanticModel(
    name="order_items",
    node_relation=PydanticNodeRelation(alias="mart_order_items", schema_name="gold"),
    entities=[PydanticEntity(name="order_item", type=EntityType.PRIMARY, expr="line_id")],
    measures=[
        PydanticMeasure(name="revenue", agg=AggregationType.SUM, expr="net_revenue",
                        agg_time_dimension="ordered_at"),
        PydanticMeasure(name="order_count", agg=AggregationType.COUNT, expr="order_id",
                        agg_time_dimension="ordered_at"),
    ],
    dimensions=[
        PydanticDimension(name="ordered_at", type=DimensionType.TIME,
            type_params=PydanticDimensionTypeParams(time_granularity=TimeGranularity.DAY)),
        PydanticDimension(name="shipped_at", type=DimensionType.TIME,
            type_params=PydanticDimensionTypeParams(time_granularity=TimeGranularity.DAY)),
        PydanticDimension(name="carrier", type=DimensionType.CATEGORICAL),
    ],
)

manifest = PydanticSemanticManifest(
    semantic_models=[order_items],
    metrics=[
        PydanticMetric(name="revenue", type=MetricType.SIMPLE,
            type_params=PydanticMetricTypeParams(measure=PydanticMetricInputMeasure(name="revenue"))),
        PydanticMetric(name="order_count", type=MetricType.SIMPLE,
            type_params=PydanticMetricTypeParams(measure=PydanticMetricInputMeasure(name="order_count"))),
        PydanticMetric(name="avg_order_value", type=MetricType.RATIO,
            type_params=PydanticMetricTypeParams(
                numerator=PydanticMetricInputMeasure(name="revenue"),
                denominator=PydanticMetricInputMeasure(name="order_count"))),
    ],
    project_configuration=PydanticProjectConfiguration(time_spines=[
        PydanticTimeSpine(
            node_relation=PydanticNodeRelation(alias="dim_date", schema_name="gold"),
            primary_column=PydanticTimeSpinePrimaryColumn(
                name="date_day", time_granularity=TimeGranularity.DAY))
    ]),
)

manifest = PydanticSemanticManifestTransformer.transform(manifest)   # REQUIRED
engine = MetricFlowEngine(
    semantic_manifest_lookup=SemanticManifestLookup(manifest),
    sql_client=RenderOnlySqlClient(SqlEngine.DUCKDB, DuckDbSqlPlanRenderer()),
)

result = engine.explain(MetricFlowQueryRequest.create(
    metric_names=["revenue"],
    group_by_names=["order_item__shipped_at__month", "order_item__carrier"],
    where_constraints=["{{ Dimension('order_item__carrier') }} = 'DHL'"],
    order_by_names=["-revenue"],
    limit=5,
))
print(result.sql_statement.sql)
```

Produces:

```sql
SELECT order_item__shipped_at__month, order_item__carrier, SUM(revenue) AS revenue
FROM (
  SELECT DATE_TRUNC('month', shipped_at) AS order_item__shipped_at__month
       , carrier AS order_item__carrier
       , net_revenue AS revenue
  FROM gold.mart_order_items order_items_src_10000
) subq_2
WHERE order_item__carrier = 'DHL'
GROUP BY order_item__shipped_at__month, order_item__carrier
ORDER BY revenue DESC
LIMIT 5
```

**Gotchas discovered while building this** — each cost time, so they're recorded:

- `PydanticSemanticManifestTransformer.transform()` is **mandatory**. Without it the lookup
  builds but queries resolve incorrectly.
- `MetricFlowQueryRequest.create(...)` — the factory is `create`, not
  `create_with_random_request_id`.
- The SQL is at `explain_result.sql_statement.sql`, not `.rendered_sql.sql_query`.
- Group-by names are `{entity}__{dimension}` and `{entity}__{time_dim}__{grain}` — keyed on the
  **primary entity name**, not the semantic model name. A model named `orders` with primary
  entity `order` yields `order__carrier`, not `orders__carrier`.
- `project_configuration` with at least one time spine is required for any `metric_time__*`
  group-by.

---

## 3. Module-level plan

### 3.1 Repo reshape

```
bloomery/
  spec/                        unchanged
  ir/                          + serialization (D5, amended §R5)
  resolve/                     unchanged
  typing/                      unchanged
  guardrails/                  unchanged  (grain, unit, tax, additivity POLICY)
  transforms/                  unchanged
  marts/                       unchanged  (D2) — now the emission source for semantic models
  plan/                        unchanged  (spec diff)
  naming.py                    unchanged

  planner/                     RESHAPED
    request.py                 KEEP AS SPECIFIED — MetricRequest, FilterExpr, OrderSpec, TimeGrain
    result.py                  KEEP AS SPECIFIED — QueryPlan, ColumnDescriptor, Explanation
    coverage.py                NEW  (R3) — mart coverage precheck, runs BEFORE delegation
    names.py                   NEW  (R4) — bloomery names <-> MetricFlow dunder names
    filters.py                 NEW  (R6) — FilterExpr -> where_constraints, safely
    metricflow_planner.py      NEW  (R2) — the adapter
    explain.py                 REWRITTEN (R9) — from the dataflow plan
    ---- DELETE ----
    select.py                  (mart selection moved into coverage.py + delegated)
    build.py                   (SQLGlot assembly — MetricFlow does this)
    additivity.py              (lowering — MetricFlow does this; policy stays in guardrails/)
    policy.py                  (folded into filters.py, see R7)

  emit/
    base.py                    + Feature enum revision (R8)
    sqlmesh/                   unchanged
    dbt/                       unchanged
    cube/                      unchanged (still an emitter; still the equivalence oracle)
    metricflow/                NEW  (R1) — IR -> PydanticSemanticManifest

  runtime/                     NEW
    hydration.py               (R5) — LRU of SemanticManifestLookup keyed by fingerprint
    sql_client.py              RenderOnlySqlClient + dialect->renderer mapping
```

**If `planner/build.py`, `select.py`, `additivity.py` or `policy.py` already contain work:**
delete them. Do not attempt to keep a second implementation "just in case" — a second planner
that isn't exercised is a liability, and R7 (equivalence tests) already gives you a second
opinion via Cube. The only thing to salvage is any test fixtures they carried.

### 3.2 Dependencies

```toml
dependencies = [
  "pydantic>=2.9",
  "sqlglot>=25",
  "jinja2>=3.1",
  "metricflow==0.211.*",       # PIN TIGHTLY — see §6
]
```

`metricflow` brings `pydantic>=1.10,<3` and uses an internal `msi_pydantic_shim` for v1/v2
compatibility. Its manifest objects expose **v1-style** APIs (`.json()`, `.parse_raw()`,
`__fields__`). Bloomery's own models stay pydantic v2. **Verification task V1** covers proving
these coexist in the repo's real dependency set.

---

## R1 — `MetricFlowEmitter`: `ProjectIR` → `PydanticSemanticManifest`

The centrepiece. A pure function, same invariants as every other emitter: no I/O, deterministic,
tenant-agnostic.

```python
def emit_manifest(ir: ProjectIR, *, naming: NamingPolicy) -> PydanticSemanticManifest: ...
```

### Mapping table

| bloomery IR | MetricFlow |
|---|---|
| `MartSpec` | `PydanticSemanticModel` |
| `MartSpec.name` | `.name` |
| `NamingPolicy.relation(mart, Layer.GOLD)` → `(schema, table)` | `PydanticNodeRelation(schema_name=…, alias=…)` |
| mart's grain entity | `PydanticEntity(type=PRIMARY, expr=<key column>)` |
| flattened FK columns worth joining on | `PydanticEntity(type=FOREIGN, …)` |
| `DimensionRef(dim, role=None)`, categorical | `PydanticDimension(type=CATEGORICAL)` |
| `DimensionRef(dim, role="shipped")`, temporal | `PydanticDimension(name="shipped_at", type=TIME, type_params=…(time_granularity=DAY))` |
| measure, `Additivity.ADDITIVE` | `PydanticMeasure(agg=SUM/COUNT/…, expr=…, agg_time_dimension=…)` |
| measure, `Additivity.SEMI_ADDITIVE` + `SemiAdditivePolicy(over, rule)` | `PydanticMeasure(non_additive_dimension=PydanticNonAdditiveDimensionParameters(name=over.qualified, window_choice=MAX\|MIN, window_groupings=…))` |
| measure, `Additivity.NON_ADDITIVE` + `RatioSpec` | `PydanticMetric(type=RATIO, type_params=(numerator, denominator))` — **never a measure** |
| simple metric | `PydanticMetric(type=SIMPLE, type_params=(measure=…))` |
| expression metric over other metrics | `PydanticMetric(type=DERIVED, type_params=(expr, metrics))` |
| running/period-to-date metric | `PydanticMetric(type=CUMULATIVE, type_params=(window \| grain_to_date))` |
| catalog date dimension | `PydanticProjectConfiguration(time_spines=[PydanticTimeSpine(...)])` |
| metric `description` | `.description` — **carry it; it grounds the Query Agent** |

### Enum mappings

```
AggregationType : sum | min | max | count_distinct | sum_boolean | average
                  | percentile | median | count
MetricType      : simple | ratio | cumulative | derived | conversion
DimensionType   : categorical | time
EntityType      : primary | foreign | unique | natural
TimeGranularity : nanosecond … second | minute | hour | day | week | month | quarter | year
```

`SemiAdditivePolicy.rule` → `window_choice`: `last → MAX`, `first → MIN`. **`avg`, `max`, `min`
are not expressible** via `non_additive_dimension`; emit `UnsupportedByTarget` naming the rule.

### Rules

1. **A mart becomes exactly one semantic model.** Never emit a semantic model for a
   non-materialized entity — that would reintroduce query-time joins the mart design exists to
   prevent.
2. **Set `primary_entity`** on the semantic model when the mart's grain has no single natural
   key column. `PydanticSemanticModel` has both `entities` and a `primary_entity` field.
3. **Every measure needs `agg_time_dimension`.** If a mart has no time dimension, that's a
   `MartMissingTimeDimension` compile error — MetricFlow requires it and the failure is
   otherwise obscure.
4. **Emit the time spine from the catalog date dimension.** This resolves original spec open
   question #1: yes, bloomery owns the date dimension, because MetricFlow requires a declared
   time spine and the SQLMesh emitter has to build the table it points at. Both come from one
   catalog definition.
5. **Determinism:** sort `semantic_models`, `metrics`, `measures`, `dimensions`, `entities`
   lexicographically before construction. The manifest gets hashed and cached; ordering drift
   would silently defeat the cache.

### Golden files

Add `tests/golden/<fixture>/metricflow/manifest.json` for every fixture. Serialize with sorted
keys. Review diffs like source code.

---

## R2 — `MetricFlowPlanner`: the adapter

**`MetricRequest` and `QueryPlan` do not change.** They are our stable API — the Query Agent
and the serving layer bind to them, not to MetricFlow. This is what makes the choice reversible.

```python
class MetricFlowPlanner:
    def __init__(self, hydrator: ManifestHydrator, sql_clients: Mapping[str, SqlClient]): ...

    def plan(
        self, ir: ProjectIR, request: MetricRequest, *,
        dialect: str, policy: RowPolicy | None = None,
    ) -> QueryPlan:
        coverage.check(ir, request)                       # R3 — refuse before delegating
        lookup = self._hydrator.get(ir)                   # R5 — LRU by fingerprint
        engine = MetricFlowEngine(lookup, self._sql_clients[dialect])
        mf_req = MetricFlowQueryRequest.create(
            metric_names   = names.to_mf_metrics(request.metrics),
            group_by_names = names.to_mf_group_by(request.dimensions, request.time_grain),
            where_constraints = filters.to_where(request.filters, policy),   # R6
            order_by_names = names.to_mf_order(request.order_by),
            limit          = min(request.limit or DEFAULT_LIMIT, MAX_LIMIT),
        )
        try:
            result = engine.explain(mf_req)
        except InvalidQueryException as e:
            raise translate_mf_error(e) from e            # → bloomery error taxonomy
        return QueryPlan(
            sql         = result.sql_statement.sql,
            columns     = names.columns_from(result.query_spec),
            mart        = mart_of(result.dataflow_plan),
            warnings    = (),
            explanation = explain.from_dataflow(result),  # R9
            fingerprint = sha256(result.sql_statement.sql),
        )
```

Error translation is required, not optional. MetricFlow's `InvalidQueryException` message is
excellent but its *type* is theirs. Map to `UnknownMember`, `UnreachableAtGrain`,
`AmbiguousDimension` so callers never catch a MetricFlow class. That's the seam that lets the
backend be swapped.

Keep `MetricFlowEngine` construction cheap (~4 ms) but the `SemanticManifestLookup` cached —
the engine wraps the lookup, the lookup holds the graph.

---

## R3 — Mart coverage precheck (keep the refusal policy)

**This is the most important thing to preserve from D1.**

MetricFlow will happily plan a multi-hop join across semantic models. Our marts design says
that shouldn't happen — a cross-grain request should be *refused*, not silently answered with a
join we didn't intend. So we check first and delegate second.

```python
def check(ir: ProjectIR, request: MetricRequest) -> str:
    """Return the covering mart name, or raise. Runs before MetricFlow sees anything."""
```

Rules:

1. All requested measures must live on **one** mart. Otherwise `UnreachableAtGrain`, naming
   both grains and both marts:

   ```
   UnreachableAtGrain: metrics {shipping_cost, line_discount} live on different grains
     shipping_cost  → grain: order      (mart: gold.mart_orders)
     line_discount  → grain: order_item (mart: gold.mart_order_items)
     Summing across grains would double-count. Request them separately, or define a
     mart at the shared grain.
   ```
2. All requested dimensions must be flattened onto that mart.
3. On multiple candidates: cheapest by `cost_hint`, ties broken lexicographically.

Product rule this encodes, unchanged: *the system may not know the answer, but may not return a
wrong one without warning.*

---

## R4 — Name bridging

MetricFlow uses dunder names keyed on the **primary entity**:

```
{entity}__{dimension}                    order_item__carrier
{entity}__{time_dimension}__{grain}      order_item__shipped_at__month
metric_time__{grain}                     metric_time__month
-{metric}                                descending order
```

`planner/names.py` owns the bidirectional mapping. Requirements:

- `to_mf_group_by(DimensionRef)` → dunder name, using the mart's primary entity name.
- `columns_from(query_spec)` → `tuple[ColumnDescriptor, ...]` in **bloomery names**. Callers
  must never see `order_item__shipped_at__month`; they see `shipped_date` with
  `grain=month`.
- `DimensionRef.role` maps onto the flattened dimension name (`shipped_at`), consistent with
  what R1 emitted. R3 and R1 must agree — enforce with a property test asserting every
  dimension the emitter produces is round-trippable through `names`.
- `metric_time` is reserved. Reject a tenant dimension named `metric_time` at spec-validation
  time with a clear message.

---

## R5 — Hydration and caching (amends D5)

D5's design survives; the artifact changes.

```python
@dataclass(frozen=True)
class HydrationKey:
    spec_fingerprint: str
    bloomery_version: str
    metricflow_version: str      # NEW — a MetricFlow bump invalidates the cache

class ManifestHydrator(Protocol):
    def get(self, ir: ProjectIR) -> SemanticManifestLookup: ...
```

Two-level cache:

| Level | Content | Cost | Where |
|---|---|---|---|
| L2 | transformed manifest JSON (~145 KB) | 23 ms to build | Redis / control plane, keyed by `HydrationKey` |
| L1 | hydrated `SemanticManifestLookup` (~1.6 MB) | 29 ms from L2 | in-process LRU |

Store the manifest **post-`transform()`** so hydration is `parse_raw` + `SemanticManifestLookup`
only.

Revised budget: **the original 5 ms target is not achievable and is not needed.** Set the
ceiling at **50 ms cold hydration** and **10 ms warm** (L1 hit). Add
`tests/bench/test_hydration.py` asserting both, so a regression fails CI.

L1 sizing: at 1.6 MB per tenant, a 500-entry LRU is ~800 MB. Make the size configurable; expose
hit rate as a metric.

Serialization uses MetricFlow's own pydantic-v1-style `.json()` / `.parse_raw()`. Do **not**
pickle — not deterministic, not version-safe.

---

## R6 — Filters and injection safety ⚠️

MetricFlow's `where_constraints` take **Jinja-templated strings**:

```python
where_constraints=["{{ Dimension('order_item__carrier') }} = 'DHL'"]
```

That is a string-construction surface, and it is the single highest-risk part of this pivot.

**Rules — non-negotiable:**

1. `FilterExpr` values are **never** interpolated into the template as raw text. Build literals
   through a typed renderer that quotes and escapes per dialect, or use
   `render_bind_parameter_key`.
2. The dimension name inside `{{ Dimension(...) }}` must be produced by `names.py` from a
   validated `DimensionRef`. Never from user input, never from an LLM.
3. Values are validated against the dimension's declared type before rendering. A string value
   for a numeric dimension is a `FilterTypeMismatch`, not a cast.
4. `contains` / `like` operators escape wildcards.
5. **Fuzz test it.** Property-based: for adversarial `FilterExpr` values (`' OR 1=1 --`,
   `{{ Dimension('x') }}`, unicode quote variants, embedded newlines), assert the rendered SQL
   parses via `sqlglot` to a query whose predicate structure is unchanged and whose scanned
   relations are exactly the expected mart. This is a merge-blocking test.

---

## R7 — Row policy under MetricFlow

`RowPolicy` stays a value object (D9 unchanged). It is applied as an **additional
where-constraint**, always, prepended to user filters.

```python
def to_where(filters: tuple[FilterExpr, ...], policy: RowPolicy | None) -> tuple[str, ...]:
    out = []
    if policy is not None:
        out.append(policy.render(names))      # e.g. "{{ Dimension('order__tenant') }} = 'acme'"
    out.extend(render(f) for f in filters)
    return tuple(out)
```

The D1 test survives verbatim and stays merge-blocking — **assert on the parsed AST, not on a
substring**:

```python
def test_row_policy_survives_every_path(fixture_ir):
    for req in EXHAUSTIVE_REQUEST_MATRIX:      # limits, ordering, filters, all grains,
                                               # ratio metrics, semi-additive, cumulative
        plan = planner.plan(fixture_ir, req, dialect="duckdb",
                            policy=RowPolicy(dimension="tenant", op="eq", value="acme"))
        parsed = sqlglot.parse_one(plan.sql, dialect="duckdb")
        assert policy_predicate_present_in_every_scan(parsed)
```

Ratio and semi-additive metrics matter here specifically: both generate **multiple subqueries
over the mart** (the semi-additive case emits an `INNER JOIN` against a `MAX(...)` subquery).
The predicate must appear in every one of them. Verify against the real generated SQL before
trusting it — this is **verification task V4**.

---

## R8 — Capabilities (amends D6)

```python
class Feature(StrEnum):
    SEMI_ADDITIVE      = "semi_additive"
    NON_ADDITIVE       = "non_additive"
    CUMULATIVE         = "cumulative"          # NEW
    DERIVED_METRIC     = "derived_metric"      # NEW
    ROLE_PLAYING_DIM   = "role_playing_dim"
    MULTI_FACT         = "multi_fact"
    QUERY_TIME_JOIN    = "query_time_join"
    ROW_LEVEL_SECURITY = "row_level_security"
    VARIANT_COLUMN     = "variant_column"
    SCD_TYPE_2         = "scd_type_2"
```

| Target | Supports | Does not |
|---|---|---|
| `MetricFlowPlanner` | semi/non-additive, cumulative, derived, role-playing, RLS | `MULTI_FACT`; `QUERY_TIME_JOIN` **disabled by policy** (R3) |
| `SQLMeshEmitter` | SCD2, variant, all additivity | — |
| `CubeEmitter` | query-time join, multi-fact, RLS | semi-additive (verify empirically) |
| `DbtEmitter` | most | SCD2 native |

Note the nuance: MetricFlow *can* do query-time joins; we refuse them at R3. Document that in
the capability docstring as **a deliberate policy, not a limitation**, so nobody "fixes" it.

---

## R9 — Explanations from the dataflow plan (amends D8)

MetricFlow emits its plan as SQL comments:

```
-- Constrain Output with WHERE
-- Select: ['__revenue', 'order_item__carrier', 'order_item__shipped_at__month']
-- Aggregate Inputs for Simple Metrics
-- Compute Metrics via Expressions
-- Order By ['revenue'] Limit 5
```

Do **not** scrape comments. Build `Explanation` from the structured
`MetricFlowExplainResult.dataflow_plan` and `.query_spec`, which are typed objects. Comments
are a rendering detail and will change between versions.

Output shape is unchanged from D8 — translated back into bloomery names:

```
on_time_rate by carrier, month
  mart:     gold.mart_shipments (grain: shipment)
  measure:  on_time_rate = on_time_count / shipment_count
            [non-additive ratio → recomputed at the requested grain, not summed]
  filters:  shipped_date between 2026-01-01 and 2026-03-31
  policy:   applied
```

---

## R10 — Testing (amends D7)

### Keep unchanged

All fixtures from D7 — `role_playing_dates`, `semi_additive_inventory`, `non_additive_aov`,
`multi_mart_refusal`, `fanout_trap` — plus their hard-coded expected values:

```python
assert query(["inventory_balance"], filters=[jan_1_to_3]) == 90       # NOT 270
assert query(["inventory_balance"], filters=[jan_3])      == 130      # sum across warehouses
assert query(["average_order_value"])       == Decimal("2727.27")     # NOT 6000, NOT 12000
```

These now test *our mapping into MetricFlow* rather than our SQL generation. Equally valuable —
a wrong `window_choice` or a measure emitted where a ratio metric belonged fails here.

### Changed

| Layer | Change |
|---|---|
| **Golden** | Add `metricflow/manifest.json` per fixture. Emitted SQL goldens stay, but expect churn on MetricFlow bumps — treat a SQL golden diff on a version bump as *review*, not *failure*, provided execution tests still pass. |
| **Execution** | Unchanged and now the primary correctness gate — run the SQL, assert the number. |
| **Equivalence** | Now **three-way**: `MetricFlow ↔ Cube ↔ hand-written reference SQL` per golden request. Hand-written reference SQL for the ~15 hardest cases is cheap and is the tiebreaker when two engines disagree. |
| **Property** | New: every dimension `MetricFlowEmitter` produces must round-trip through `names.py` (R4). New: filter fuzzing (R6). |
| **Bench** | `test_hydration.py` asserting 50 ms cold / 10 ms warm. |
| **Removed** | Unit tests for `build.py`, `additivity.py` lowering, `select.py`. Salvage their fixtures. |

### New: version-drift canary

```python
def test_metricflow_api_surface():
    """Fails loudly when a MetricFlow upgrade moves something we depend on."""
    assert hasattr(MetricFlowQueryRequest, "create")
    assert hasattr(MetricFlowExplainResult, "sql_statement")
    assert hasattr(SemanticManifestLookup, "__init__")
    for attr in ("sql_engine_type", "sql_plan_renderer", "query", "execute",
                 "dry_run", "close", "render_bind_parameter_key"):
        assert attr in SqlClient.__dict__ or hasattr(SqlClient, attr)
```

We depend on internals that have no stability guarantee. This turns a silent breakage into an
obvious one.

---

## 6. Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| **We depend on non-public internals.** `metricflow_semantics.api.v0_1` contains only a saved-query resolver; there is no versioned embedder API. `MetricFlowEngine`, `SemanticManifestLookup`, `SqlClient` are internal surfaces. | **High** | Pin `metricflow==0.211.*`. API-surface canary test. Upgrade deliberately with goldens regenerated and reviewed. |
| **dbt Labs' roadmap.** MetricFlow serves the dbt Semantic Layer first. Embedded use is not a supported use case. | Medium | Apache 2.0 + vendored interfaces means a fork is viable. The `MetricRequest`/`QueryPlan` boundary (R2) means a swap is an adapter rewrite, not a platform migration. |
| **Semi-additive grouping defect.** Issue [#241](https://github.com/dbt-labs/metricflow/issues/241) reported that grouping *by* the non-additive dimension filters to the first/last value instead of returning the full series. Old, may be fixed. | **High if unfixed** — "balance by warehouse by month" is a query users will run | **Verification task V2**, before any of this is merged |
| **pydantic v1/v2 coexistence.** MetricFlow uses a v1 shim; bloomery is v2. | Medium | **Verification task V1** |
| **Jinja where-constraints.** String construction on the query path. | **High** | R6, fuzz-tested, merge-blocking |
| **SQL churn between versions** breaking goldens | Low | Execution tests are the real gate; goldens are review aids |
| **Hydration cost on larger models.** 30 models measured; some tenants will be bigger. | Medium | **Verification task V3** |

---

## 7. Verification tasks — do these first

Merge nothing until all four are answered. Budget: two to three days.

**V1 — Dependency coexistence.** Install `metricflow` alongside bloomery's existing deps in the
real environment. Confirm pydantic v2 models and MetricFlow's v1-shim models coexist without
import-order effects or metaclass conflicts. *Blocking: everything.*

**V2 — Semi-additive grouping.** Build `semi_additive_inventory`, run against DuckDB with real
rows, and assert **all three**:

```
balance, no time group-by, 3-day filter                → 90
balance by warehouse, single date                      → A=90, B=40
balance by month, 3 months                             → THREE ROWS, one per month
```

The third is the one issue #241 was about. If it fails: check for a fix upstream; otherwise
either post-process in the planner or handle semi-additive natively for the grouped case and
declare a partial capability. *Blocking: R1's semi-additive mapping.*

**V3 — Hydration at real scale.** Take the largest tenant model you can construct from the
first chunk of real data. Measure `parse_raw` + `SemanticManifestLookup` and resident memory.
If cold hydration exceeds ~150 ms, raise the L1 cache priority and consider pre-warming on
tenant login. *Blocking: R5 budget numbers.*

**V4 — Row policy in generated SQL.** Generate SQL for a ratio metric and a semi-additive
metric with a policy applied. Inspect the actual SQL — confirm the predicate lands in **every**
subquery, including the `MAX(...)` join subquery of the semi-additive plan. If MetricFlow
applies `where_constraints` only at the outer level, that is a **security defect** for us and
the policy must move into the semantic model's `sql` / node relation instead (a per-tenant
filtered relation). *Blocking: R7, and blocking any production use.*

> V4 is the one that could change the architecture. If where-constraints don't reach inner
> scans, the fix is to emit tenant-filtered node relations per tenant — which is a change to
> R1, not to the whole approach, but it must be known before building on top.

---

## 8. Milestones (supersedes D10)

| # | Scope | Done when |
|---|---|---|
| M1–M4 | *(unchanged, already complete)* | ✓ |
| **M4.5** | **Verification tasks V1–V4** | all four answered in writing |
| M5 | Marts (D2) + role-playing (D3) | mart validation rejects `fanout_trap` at compile time |
| **M6** | **R1 `MetricFlowEmitter`** | every fixture emits a manifest that `SemanticManifestLookup` accepts |
| **M7** | **R2 planner + R3 coverage + R4 names + R6 filters + R7 policy** | all D7 fixture assertions pass against DuckDB; filter fuzzing green; policy AST test green |
| **M8** | **R5 hydration + caching** | 50 ms cold / 10 ms warm, asserted in CI |
| M9 | `plan()` + change classification | `evolution_v1..v5` classified; contract violation caught |
| M10 | Trino dialect + Cube emitter (R8) | golden matrix green |
| M11 | E2E + three-way equivalence (R10) | SQLMesh replan is a no-op; MetricFlow ↔ Cube ↔ reference SQL agree |

M6+M7 replace the old M5. Net schedule effect: roughly a week saved, and the hardest correctness
work (additivity lowering) is now someone else's tested code.

---

## 9. What is explicitly not changing

Restated because it's easy to over-rotate on a pivot:

- **The five hard invariants.** No I/O, deterministic, tenant-agnostic, no framework
  dependency, total errors. The planner is still a pure function returning SQL text; it does
  not execute.
- **D9.** `grep -ri "tenant" bloomery/` still returns only `naming.py` docstrings. Keep it as a
  CI check.
- **D2, D3.** Marts and role-playing dimensions are unchanged and now more load-bearing —
  they are the emission source.
- **D4's policy half.** Compile-time refusal of a stored non-additive measure, and the
  `GrainViolation` check on mart definitions, stay in `guardrails/`. MetricFlow lowers
  additivity; it does not stop you from *modelling* it wrongly.
- **`MetricRequest` / `QueryPlan` / `ColumnDescriptor`.** The public contract. Unchanged, and
  the reason this decision is reversible.
- **The Cube emitter.** Still built, still the equivalence oracle, still the escape hatch for
  BI-tool SQL connectivity.
- **Refuse-don't-guess.** Now enforced twice — once by us at R3, once by MetricFlow's own
  resolver. Belt and braces is correct here.

---

## 10. Remaining open questions

1. ~~Does bloomery own the date dimension?~~ **Resolved: yes.** MetricFlow requires a declared
   time spine; the SQLMesh emitter builds the table it points at; both derive from one catalog
   definition.
2. Incremental strategy per entity — declared in the spec, or inferred from grain and partition
   key? Still open.
3. Quarantine tables: IR entities or emitter convention? Still open.
4. Identity resolution (xref/edge generation) — its own emitter concern; still out of scope
   through M11.
5. **New:** should `PydanticSavedQuery` be used for frequently-requested dashboard queries?
   MetricFlow supports saved queries and there's a dependency resolver in
   `metricflow_semantics.api.v0_1`. Possible caching win; defer until after M11 and real usage
   data.
