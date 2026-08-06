# `bloomery` — Implementation Changes & Additions

**Audience:** the engineer/agent implementing `bloomery`
**Supersedes:** relevant sections of the original package specification
**Status:** design decisions settled; implement as written unless a stated assumption breaks

> **Note (RFC corpus):** Preserved verbatim as source material, like
> [`_original-smelter-spec.md`](_original-smelter-spec.md). This document was written
> against the *original* spec; where the RFC series had already settled an open question
> it re-lists (incremental strategy — RFC 0002 D7; quarantine — RFC 0008 D7; date
> dimension — RFC 0008 D6), the RFC decisions stand. Its new scope lands as RFCs
> 0010 (marts + role-playing), 0011 (native planner), 0012 (compiled semantic), plus
> amendments to RFCs 0002/0003/0006/0008/0009. Where RFCs diverge from this document,
> the RFCs win.

---

## 0. What changed and why

The original spec treated `bloomery` as a **spec → transformation-code compiler**: YAML in,
SQLMesh/dbt models out. That's still the core, but one decision has been made since that
expands the package's responsibility:

> **`bloomery` also owns query planning.** It compiles `MetricRequest → SQL` at request time,
> in-process, as a first-class target alongside the file emitters.

### Why

We evaluated depending on an external semantic layer (Cube, Boring Semantic Layer) for the
gold/serving side. Both were rejected as load-bearing dependencies:

- **Cube** carries per-tenant resident memory (single-digit to dozens of MB per tenant for
  compile/SQL/result caches) and a throughput ceiling of ~1–10 rps per API node. At hundreds of
  tenants with distinct dynamic models, that forces a sharded API + sharded refresh-worker
  topology we would have to build and operate. Tenant isolation there is a configuration
  property, not a structural one.
- **BSL** is the right *shape* (a library, explicit definitions, no service) but cannot currently
  join the same dimension table twice under different foreign keys — role-playing dimensions
  (`order_date` / `ship_date`, `bill_to` / `ship_to`) break it, and those are unavoidable in
  our domain.

Cube remains a **supported emit target** (escape hatch, plus its SQL API gives Excel/Tableau
connectivity we can't cheaply replicate). It is not on the critical path.

### The constraint that makes this tractable

We control the physical layer, so we constrain it:

> **Gold is one wide, pre-joined mart per (grain × subject area). Dimensions are flattened in
> at build time. There are no query-time joins on the common path.**

| Classic semantic-layer problem | Under wide marts |
|---|---|
| Fan-out on many-to-one joins | **impossible** — no join at query time |
| Role-playing dimensions | flattened to distinct columns at build time |
| Symmetric aggregates | not needed |
| Multi-fact root selection | separate marts; cross-mart requests are refused, not guessed |
| Pre-aggregation / caching tier | the mart *is* the pre-aggregation |
| Planner complexity | `SELECT dims, AGG(measures) FROM mart WHERE … GROUP BY dims` |

The planner therefore drops from "distributed join planning" to "assemble a GROUP BY." That is
roughly **1.5–2.5k lines including tests**, and it is worth owning because it removes the only
irreversible external dependency from the path of every number a user sees.

### What stays exactly as specified

Everything in §1.2 of the original spec — the hard invariants — is unchanged and now matters
more, not less:

1. **No I/O.** No filesystem, network, database, clock, environment, or randomness.
2. **Deterministic.** Byte-identical output across processes and `PYTHONHASHSEED` values.
3. **No tenant awareness.** `bloomery` does not know what a tenant is.
4. **No framework dependency.** No Forze, no orchestrator, no cloud SDK.
5. **Total errors.** Typed `BloomeryError` with a source path, never a bare `KeyError`.

The planner is a pure function too: `(IR, MetricRequest, DialectPort, RowPolicy) → QueryPlan`.
It returns SQL text. It does not execute anything.

---

## 1. Package structure — updated

```
bloomery/
  __init__.py            # public API only
  errors.py
  spec/                  # pydantic models: catalog, entity, mapping, metrics, MARTS  ← D2
  ir/                    # frozen IR + fingerprint + SERIALIZATION                     ← D5
  resolve/               # DAG, recipes, reachability
  typing/                # logical types, transform signatures
  guardrails/            # unit, tax, grain, additivity, conflict
  transforms/            # whitelist registry
  marts/                 # NEW — mart definition, flattening, selection               ← D2
  planner/               # NEW — MetricRequest → QueryPlan                            ← D1
    request.py           #   MetricRequest, FilterExpr, OrderSpec, TimeGrain
    select.py            #   mart selection
    build.py             #   SQLGlot AST assembly
    additivity.py        #   additive / semi-additive / non-additive lowering         ← D4
    policy.py            #   RowPolicy injection
    explain.py           #   human-readable provenance                                ← D8
  plan/                  # spec diff + change classification (unchanged)
  emit/
    base.py              # TargetEmitter, TargetCapabilities (EXTENDED)               ← D6
    sqlmesh/  dbt/  cube/
  dialects/
  naming.py
tests/
  unit/ golden/ property/ execution/ engines/ e2e/ equivalence/ fixtures/             ← D7
```

Two new top-level packages (`marts/`, `planner/`), one extended (`emit/base.py`), one gaining
responsibility (`ir/` must serialize).

---

## D1 — `NativePlanner`: `MetricRequest` → SQL  ⚠️ critical

**Why it's separate from `TargetEmitter`:** emitters produce artifacts ahead of time and are
called once per spec version. The planner answers at request time and is called thousands of
times per second. Different lifecycle, different performance envelope, different port.

### Types

```python
# bloomery/planner/request.py

class TimeGrain(StrEnum):
    HOUR = "hour"; DAY = "day"; WEEK = "week"
    MONTH = "month"; QUARTER = "quarter"; YEAR = "year"

@dataclass(frozen=True)
class FilterExpr:
    dimension: str                  # may be role-qualified: "shipped_date"
    op: Literal["eq","ne","in","not_in","gt","gte","lt","lte","between","contains","is_null"]
    values: tuple[JsonScalar, ...]

@dataclass(frozen=True)
class OrderSpec:
    field: str                      # a requested metric or dimension, not arbitrary SQL
    direction: Literal["asc","desc"] = "asc"

@dataclass(frozen=True)
class MetricRequest:
    metrics: tuple[str, ...]
    dimensions: tuple[str, ...] = ()
    filters: tuple[FilterExpr, ...] = ()
    time_grain: TimeGrain | None = None
    order_by: tuple[OrderSpec, ...] = ()
    limit: int | None = None
```

`MetricRequest` is a **static shape with dynamic content**. This is what the Query Agent emits —
it never writes SQL. A malformed request fails validation; it does not execute.

### Output

```python
@dataclass(frozen=True)
class ColumnDescriptor:
    name: str
    type: LogicalType
    role: Literal["dimension", "measure"]
    label: str | None = None

@dataclass(frozen=True)
class QueryPlan:
    sql: str
    columns: tuple[ColumnDescriptor, ...]
    mart: str
    warnings: tuple[str, ...]
    explanation: Explanation          # see D8
    fingerprint: str                  # sha256(sql) — cache key for results
```

`columns` is the self-describing envelope: the caller gets typed metadata without knowing the
row shape in advance. Never return bare rows without it.

### Port

```python
class Planner(Protocol):
    def plan(
        self,
        ir: ProjectIR,
        request: MetricRequest,
        *,
        dialect: DialectPort,
        policy: RowPolicy | None = None,
    ) -> QueryPlan: ...
```

### Algorithm

```
1. VALIDATE   every metric and dimension exists in the IR
              → UnknownMember(name, did_you_mean=...)
2. SELECT     find marts whose grain covers all requested measures AND
              expose all requested dimensions
              0 candidates → UnreachableAtGrain (see below)
              1 candidate  → use it
              N candidates → cheapest by declared cost hint, ties broken
                             lexicographically (determinism)
3. LOWER      each measure through its additivity policy (D4)
4. BUILD      SQLGlot AST: SELECT dims + aggregated measures
                           FROM mart
                           WHERE filters AND policy_predicate
                           GROUP BY dims
                           ORDER BY / LIMIT
5. RENDER     dialect.render(ast)
6. EXPLAIN    build Explanation from the decisions above
```

### Hard rules

- **Never join at plan time.** If a request needs data from two marts, raise
  `UnreachableAtGrain` naming the specific conflict:

  ```
  UnreachableAtGrain: metrics {shipping_cost, line_discount} live on different grains
    shipping_cost   → grain: order      (mart: gold.mart_orders)
    line_discount   → grain: order_item (mart: gold.mart_order_items)
    Summing across grains would double-count. Request them separately,
    or define a mart at the shared grain.
  ```

  This is intentional. Refusing with a reason is correct behaviour; a plausible wrong number
  is not. The product requirement is *"the system may not know the answer, but may not return
  a wrong one without warning."*

- **Row policy is injected into the AST**, never appended as a string, never templated.

- **`order_by` fields must appear in `metrics` or `dimensions`.** No arbitrary expressions —
  that's an injection surface.

- **`limit` is clamped** to a configurable ceiling (default 50 000).

### Test that must exist before merge

```python
def test_row_policy_survives_every_path(fixture_ir):
    for req in EXHAUSTIVE_REQUEST_MATRIX:      # limits, ordering, filters, all grains
        plan = planner.plan(fixture_ir, req, dialect=DUCKDB,
                            policy=RowPolicy(predicate="tenant_id = 'acme'"))
        parsed = sqlglot.parse_one(plan.sql, dialect="duckdb")
        assert policy_predicate_present_in_every_scan(parsed)
```

Assert on the **parsed AST**, not on a substring of the SQL text. A string check passes on
`-- tenant_id = 'acme'`.

---

## D2 — Marts as a first-class IR concept  ⚠️ critical

Everything in D1 depends on marts being modelled, not conventional. This is the change to make
first, because it touches the spec schema.

### Spec

```yaml
marts:
  order_items:
    grain: order_item                 # must match an entity grain in the IR
    base: order_item
    flatten:
      - {via: item_of_order,      prefix: order_}
      - {via: order_of_customer,  prefix: customer_}
      - {via: item_of_product,    prefix: product_}
      - {date: order_date, role: ordered}   # → ordered_day, ordered_month, ordered_quarter…
      - {date: ship_date,  role: shipped}
    measures: [gross_revenue, discount, net_revenue, quantity]
    partition_by: [days(ordered_day)]
    cost_hint: 3                      # relative scan cost; used for tie-breaking only

  orders:
    grain: order
    base: order
    flatten:
      - {via: order_of_customer, prefix: customer_}
      - {date: order_date, role: ordered}
    measures: [order_count, shipping_cost, order_discount]
    partition_by: [days(ordered_day)]
```

### Two consumers, one definition

```
MartSpec ──► SQLMeshEmitter   → the model that BUILDS the mart (joins + flattening)
         └─► NativePlanner    → the catalogue it SELECTS from (no joins)
```

This is the payoff of the shared IR: the thing that builds the table and the thing that queries
it cannot disagree about its grain or its columns, because they read the same object.

### Validation rules

- Every measure listed must have a grain **equal to or coarser than** the mart's grain.
  A measure at coarser grain (shipping cost on an order-grain mart, requested on an item-grain
  mart) is a `GrainViolation` — this is the fan-out guard, moved to compile time.
- Every `flatten` path must be a declared relationship with `many_to_one` or `one_to_one`
  cardinality. A `one_to_many` flatten is a `FanoutRisk` error.
- Column-name collisions after prefixing are an error, not an auto-rename.

### Test

`fixtures/fanout_trap` must now fail at **compile** time with `GrainViolation`, where previously
it failed at execution time with a wrong number. Keep the execution-level assertion too — it
documents *why* the compile error exists.

---

## D3 — Role-playing dimensions in the IR  🔴 high

The concept that breaks naive semantic layers. Model it once, lower it three ways.

```python
@dataclass(frozen=True)
class DimensionRef:
    dimension: str                # "date"
    role: str | None = None       # "ordered" | "shipped" | None

    @property
    def qualified(self) -> str:
        return f"{self.role}_{self.dimension}" if self.role else self.dimension
```

Lowerings:

| Consumer | How it lowers |
|---|---|
| Mart builder | joins `dim_date` once per role, aliased, flattening `ordered_month`, `shipped_month`, … |
| Native planner | reads the flattened columns — no join, so the problem doesn't exist |
| Cube emitter | emits aliased join paths per role |

Every dimension reference in `MetricRequest`, `FilterExpr`, and `OrderSpec` is parsed into a
`DimensionRef`. An unqualified reference to a dimension that has multiple roles is an error
naming the available roles:

```
AmbiguousDimension: 'date' has roles [ordered, shipped]. Use 'ordered_date' or 'shipped_date'.
```

New fixture: `role_playing_dates` — orders with `order_date` and `ship_date`, asserting that
grouping by each gives different, correct results. This is the exact case that breaks BSL.

---

## D4 — Additivity as a typed policy  🔴 high

```python
class Additivity(StrEnum):
    ADDITIVE = "additive"
    SEMI_ADDITIVE = "semi_additive"
    NON_ADDITIVE = "non_additive"

@dataclass(frozen=True)
class SemiAdditivePolicy:
    over: DimensionRef                                       # usually a date
    rule: Literal["last", "first", "avg", "max", "min"]
    # sums normally over every other dimension

@dataclass(frozen=True)
class RatioSpec:
    numerator: str                                           # additive measure name
    denominator: str
```

### Lowering rules — implement exactly

**Additive.** `SUM(expr)` at whatever grain was requested. Trivial.

**Semi-additive.** Sum across every dimension *except* `over`; apply `rule` along `over`.

```sql
-- inventory_balance, semi_additive over shipped_date, rule=last
SELECT warehouse,
       SUM(balance) AS inventory_balance
FROM   gold.mart_inventory_daily
WHERE  day = (SELECT MAX(day) FROM gold.mart_inventory_daily WHERE <same filters>)
GROUP BY warehouse
```

When `over` is itself a requested dimension at a coarser grain, apply the rule *within* each
bucket (last day of each month), then sum across other dimensions.

**Non-additive.** Never stored, never summed. Always recomputed from additive components at
the requested grain:

```sql
-- average_order_value = net_revenue / order_count
SELECT store,
       SUM(net_revenue) / NULLIF(SUM(order_count), 0) AS average_order_value
FROM   gold.mart_orders
GROUP BY store
```

Emitting a stored `average_order_value` column is a **compile error**. If a spec declares a
non-additive measure without a `RatioSpec` or an equivalent recipe, that's
`NonAdditiveWithoutComponents`.

### Required execution-suite assertions

```python
# semi-additive over time
# 1 Jan: 100, 2 Jan: 80, 3 Jan: 90
assert query(metrics=["inventory_balance"], filters=[jan_1_to_3]) == 90     # NOT 270

# semi-additive across other dimensions on one date
# warehouse A 90, warehouse B 40 on 3 Jan
assert query(metrics=["inventory_balance"], filters=[jan_3]) == 130          # correct to sum

# non-additive
# store A: 10 orders / 100 000 ; store B: 100 orders / 200 000
assert query(metrics=["average_order_value"]) == Decimal("2727.27")          # NOT 6000, NOT 12000
```

Hard-code these numbers in the tests. They're from the domain analysis and they're the exact
failure modes that make a BI product untrustworthy.

---

## D5 — Serializable compiled artifacts  🔴 high

**This is the change that decides whether the platform reaches thousands of tenants.**

Cube's scaling ceiling comes from keeping every tenant's compiled model resident in memory.
If our compiled artifact is cheap to serialize and rehydrate, per-tenant state becomes a
per-request LRU instead of resident memory, and the ceiling moves by an order of magnitude.

```python
@dataclass(frozen=True)
class CompiledSemantic:
    """Everything the planner needs, and nothing else. No source specs, no catalog."""
    marts: tuple[CompiledMart, ...]
    measures: Mapping[str, CompiledMeasure]
    dimensions: Mapping[str, CompiledDimension]
    fingerprint: str
    bloomery_version: str

def compile_semantic(ir: ProjectIR) -> CompiledSemantic: ...
def dumps(cs: CompiledSemantic) -> bytes: ...
def loads(data: bytes) -> CompiledSemantic: ...
```

Requirements:

- `loads(dumps(cs)) == cs` — structural equality, property-tested.
- `dumps` output is **deterministic** for a given `CompiledSemantic`.
- Cache key is `sha256(spec_fingerprint + bloomery_version + "semantic")`.
- Version mismatch on `loads` raises `IncompatibleArtifact` — never attempts a migration.
- **Benchmark:** `loads` under **5 ms** for a realistic model (~30 entities, ~60 measures,
  ~8 marts). Add `tests/bench/test_hydration.py` with an asserted ceiling so a regression fails CI.

Prefer msgpack or plain JSON over pickle — pickle isn't safe across versions and isn't
deterministic. `CompiledSemantic` should be deliberately narrow: strip anything the planner
doesn't read, because size drives hydration time.

---

## D6 — Extended `TargetCapabilities`  🟡 medium

```python
class Feature(StrEnum):
    SEMI_ADDITIVE     = "semi_additive"
    NON_ADDITIVE      = "non_additive"
    ROLE_PLAYING_DIM  = "role_playing_dim"
    MULTI_FACT        = "multi_fact"
    QUERY_TIME_JOIN   = "query_time_join"
    ROW_LEVEL_SECURITY= "row_level_security"
    VARIANT_COLUMN    = "variant_column"
    SCD_TYPE_2        = "scd_type_2"

@dataclass(frozen=True)
class TargetCapabilities:
    supported: frozenset[Feature]
```

Declared support:

| Target | Notably supports | Notably does not |
|---|---|---|
| `NativePlanner` | semi/non-additive, role-playing, RLS | `QUERY_TIME_JOIN`, `MULTI_FACT` |
| `SQLMeshEmitter` | SCD2, variant, all additivity | — |
| `CubeEmitter` | query-time join, multi-fact, RLS | (verify semi-additive support empirically) |
| `DbtEmitter` | most | SCD2 native (lowers to snapshot) |

`NativePlanner` declaring `QUERY_TIME_JOIN = False` is a **feature, not a gap** — it is the
property that makes fan-out structurally impossible. Document it that way in the docstring so
nobody "fixes" it later.

Unsupported combination → `UnsupportedByTarget` at compile time with a specific message.
**Never degrade silently.**

---

## D7 — Planner-equivalence tests  🔴 high

The strongest correctness evidence available: two independent implementations agreeing.

```
tests/equivalence/
  test_native_vs_cube.py
  golden_requests.yaml          # ~40 MetricRequests across all fixtures
```

```python
@pytest.mark.engine("cube")
@pytest.mark.parametrize("req", load_golden_requests())
def test_native_matches_cube(req, duckdb_conn, cube_container, fixture_ir):
    native = execute(duckdb_conn, planner.plan(fixture_ir, req, dialect=DUCKDB).sql)
    viacube = cube_query(cube_container, req)
    assert_frame_equal(native, viacube, check_like=True, atol=Decimal("0.01"))
```

Runs nightly (needs containers). When they disagree, one has a bug — and you find out before a
customer does. Requests that the native planner refuses with `UnreachableAtGrain` are asserted
to be *either* refused by Cube too *or* explicitly listed in a reviewed
`known_divergences.yaml` with a written justification.

### Full fixture list (updated)

| Fixture | Exercises |
|---|---|
| `minimal` | one entity, one mapping, direct fields |
| `ecom_basic` | catalog derivation, ratio metrics, date dimension |
| `fanout_trap` | order-grain measure on an item-grain mart → compile error |
| `role_playing_dates` | **new** — `ordered_*` vs `shipped_*` give different correct results |
| `semi_additive_inventory` | **new** — 100/80/90 → 90; A90 + B40 → 130 |
| `non_additive_aov` | **new** — 2727.27, never 6000 or 12000 |
| `multi_mart_refusal` | **new** — cross-grain request refused with a named conflict |
| `messy_types` | string numerics, mixed date formats, dirty enums |
| `multi_source` | two sources → one entity, identity xref |
| `evolution_v1..v5` | expand/contract sequence for diff tests |

---

## D8 — Structured explanations  🟡 medium

Generated from the plan, deterministically. Never from an LLM.

```python
@dataclass(frozen=True)
class Explanation:
    mart: str
    grain: str
    measures: tuple[MeasureExplanation, ...]   # name, expr, additivity, how it was lowered
    filters: tuple[str, ...]                   # human-readable
    policy_applied: bool
    def render(self) -> str: ...
```

```
on_time_rate by carrier, month
  mart:     gold.mart_shipments (grain: shipment)
  measure:  on_time_rate = on_time_count / shipment_count
            [non-additive ratio → recomputed at the requested grain, not summed]
  filters:  ordered_month between 2026-01 and 2026-03
  policy:   applied
```

Two consumers: the Query Agent attaches it to every answer as provenance (a product
requirement — every number ships with how it was computed), and it's the best debugging tool
you'll have when a number looks wrong.

---

## D9 — Tenant-agnosticism, reaffirmed

Unchanged from the original spec, but easy to erode now that the planner exists.

- `NamingPolicy` remains the only tenant-shaped seam, and it takes a **string**.
- `RowPolicy` is a value object holding a predicate — not a tenant identity, not a session,
  not a security context.
- The planner takes `RowPolicy` as a parameter; it never resolves one.

**Test:** `grep -ri "tenant" bloomery/` should return only `naming.py` docstrings. Make it a
CI check. `bloomery` must remain something you could open-source with no multi-tenancy showing
through — that constraint is precisely what keeps it testable without infrastructure.

---

## D10 — Milestones, reordered

| # | Scope | Done when |
|---|---|---|
| M1 | Spec models, IR, fingerprint, errors | round-trips a fixture; fingerprint stable across processes |
| M2 | Resolve + typecheck, no catalog | `minimal` compiles to a SQLMesh DuckDB model that runs |
| M3 | Catalog + recipes + reachability | `ecom_basic` reports reachable/unreachable metrics with reasons |
| M4 | Guardrails | `fanout_trap`, `semi_additive_inventory` fail closed with useful messages |
| **M5** | **Marts (D2) + role-playing (D3) + NativePlanner (D1) + additivity (D4)** | all new fixtures pass execution tests against DuckDB |
| **M6** | **Serialization + hydration benchmark (D5)** | `loads` under 5 ms, asserted in CI |
| M7 | `plan()` + change classification | `evolution_v1..v5` classified correctly; contract violation caught |
| M8 | Second dialect (Trino) + Cube emitter (D6) | golden matrix green; port abstraction validated |
| M9 | E2E: SQLMesh replan no-op + planner equivalence (D7) | `plan.has_changes == False`; native matches Cube on golden requests |

**Why M5 moved up:** the planner is now on the critical path to a shippable product, and
building it early surfaces IR design problems — grain typing, mart selection, role-playing
resolution — while the IR is still cheap to change. Diff/plan (M7) matters for *evolution*,
which is a month-two problem.

**Why M8 must not slip further:** a second target is what validates the port design. Discovering
the emitter abstraction is wrong at M9 means an IR rewrite.

---

## 11. Assumptions to verify early

If any of these breaks, come back before continuing — several deltas depend on them.

1. **Wide marts are affordable.** Storage and rebuild time for a fully flattened
   50M-row × 40-column mart on Iceberg. If rebuild is hours rather than minutes, incremental
   mart strategy needs designing before M5.
2. **DuckDB-over-Iceberg latency.** p95 under ~500 ms on a realistic dashboard query set against
   that mart. If not, a caching tier re-enters scope and D5's importance grows further.
3. **Hydration budget.** `loads` under 5 ms. If it lands at 50 ms, the per-request LRU model
   doesn't work and the compiled artifact needs slimming.
4. **SQLMesh Python models.** Whether `@model(is_sql=True)` returning a SQLGlot expression lets
   us register models programmatically rather than writing N×M files. Decide in week one —
   it changes the emitter's shape, not just its output.

---

## 12. Open questions (unchanged, still open)

1. Does `bloomery` own the date dimension? It's catalog-level and every tenant needs it.
   Emitting it from the catalog is tempting and probably correct.
2. Incremental strategy per entity — declared in the spec, or inferred from grain and partition
   key? Inferring is nicer and harder to explain when it's wrong.
3. Quarantine tables: IR entities, or an emitter-level convention? IR is more honest, adds surface.
4. Where does identity resolution (xref/edge generation) live? Probably its own emitter concern;
   keeping it out of M1–M7 is likely right.
