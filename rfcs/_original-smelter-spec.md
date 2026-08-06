# `smelter` — Entity-First Spec Compiler

**Implementation specification, v0.1**

> **Note (bloomery):** This is the original input specification, preserved verbatim as
> source material for the RFC series in this directory. The project was renamed
> **`bloomery`** (`smelter` is taken on PyPI). Where RFCs diverge from this document,
> the RFCs win.

> Alternative names: `crucible`, `mold`, `bloom`, `assay`. `smelter` is used throughout;
> rename before first commit if you prefer another.

---

## 0. Landscape check — why this doesn't exist yet

Searched PyPI and GitHub for a reusable entity-first YAML → SQL generator. Findings:

| Candidate | What it does | Why it doesn't fit |
|---|---|---|
| `datavault4dbt`, `AutomateDV` | YAML metadata → dbt Data Vault models | Hard-coded to Data Vault (hub/link/sat). Not entity-first. dbt-only. Jinja macros, not a Python library. |
| `turbovault4dbt` | Generates dbt models from DV templates | Same, plus tied to specific metadata repos (Erwin, dbt-Sources). |
| `dbt-codegen` | Macros that print boilerplate SQL | Scaffolding, not a compiler. No IR, no diff, no determinism guarantees. |
| `dbt-metricflow` / MetricFlow | Metric definitions → SQL | Metrics only, no entity/mapping layer, no bronze→silver. |
| Malloy | A modelling language compiling to SQL | A language, not a library. Can't embed a compile step in your control plane. |
| SQLMesh | Model definitions → plan/apply | The *target*, not the compiler. Consumes what we emit. |
| SqlDBM YAML export | Modelling tool → dbt YAML | Commercial, GUI-first, not embeddable. |

**Conclusion: build it.** The closest prior art is `datavault4dbt`'s metadata schema — read it
before finalising the DSL, it has years of iteration on problems you're about to meet.

---

## 1. Purpose and boundaries

### 1.1 What it is

A **pure function library** that turns declarative entity/mapping/metric specifications into
executable transformation code for a target framework.

```python
from smelter import compile_project, Target

artifacts = compile_project(project, target=Target.SQLMESH, dialect="trino")
# artifacts: tuple[EmittedArtifact, ...]  — filename + content + kind + checksum
```

### 1.2 Hard invariants

These are the reason the package exists as a separate thing. Violating any of them makes it
untestable and therefore worthless.

1. **No I/O.** No filesystem, no network, no database, no clock, no environment variables, no
   randomness. Input is data structures, output is data structures.
2. **Deterministic.** `compile(x) == compile(x)` byte-for-byte, across processes, across
   machines, across Python versions in the support matrix. Enforced by test, not by intent.
3. **No tenant awareness.** The compiler does not know what a tenant is. Tenant scoping is
   expressed as ordinary spec values (namespace names) supplied by the caller.
4. **No framework dependency.** No Forze, no Dagster, no Temporal, no cloud SDK.
5. **Total errors.** Every failure is a typed `SmelterError` with a source path
   (`entities.shipment.fields.weight_kg.transform[1]`). Never a bare `KeyError`.

### 1.3 Non-goals

- Executing SQL. It emits text; something else runs it.
- Reading catalogs or profiling data. Those are inputs, computed elsewhere.
- Orchestration, scheduling, backfill.
- LLM anything. Proposals are produced upstream and arrive as validated specs.
- Being a query engine. Gold serving is a different concern (see §9).

---

## 2. Dependencies

```toml
[project]
requires-python = ">=3.12"
dependencies = [
  "pydantic>=2.9",
  "sqlglot>=25",
  "jinja2>=3.1",       # emitter templates only, never for SQL construction
]

[project.optional-dependencies]
dbt     = []           # emitter is pure text; no dbt dep needed
test    = ["pytest", "pytest-snapshot", "hypothesis", "duckdb", "sqlmesh"]
engines = ["testcontainers[postgres,trino]"]
```

Deliberately small. If you find yourself adding a dependency, ask whether the feature belongs
in an adapter package (`smelter-iceberg`, `smelter-cube`) instead.

> **SQL is never built by string concatenation or Jinja.** Jinja renders the *envelope*
> (a SQLMesh `MODEL (...)` block, a dbt config header). The `SELECT` is constructed as a
> SQLGlot AST and rendered with `.sql(dialect=...)`. This is what makes multi-dialect support
> real rather than aspirational, and it makes the emitted SQL parseable in tests.

---

## 3. Domain model

### 3.1 The four spec kinds

```
Catalog     — domain knowledge. One per vertical. Written by you, not by tenants.
EntityModel — what this tenant's data means. One per tenant.
Mapping     — how a source becomes an entity. One per (tenant, source, entity).
MetricSet   — measures, grain, additivity. One per tenant.
```

The **Catalog** is the piece most implementations miss and it is what makes the rest
tractable. It holds canonical fields, derivation recipes, canonical relationships, and metric
templates — the domain graph, independent of any tenant. A tenant's EntityModel is *the
subgraph of the catalog that resolved against their actual data*, plus tenant-native
extensions the catalog never anticipated.

### 3.2 Catalog

```yaml
catalog_version: 3
vertical: ecom_retail

canonical_fields:
  unit_price:
    entity: order_item
    type: decimal(12,4)
    unit: currency
    tax_basis: net              # net | gross | unknown — see guardrails
    recipes:                    # ordered by reliability, first satisfiable wins
      - {id: direct,      requires: [unit_price]}
      - {id: from_total,  requires: [line_total, quantity], expr: "line_total / quantity"}
  discount:
    entity: order_item
    type: decimal(12,4)
    unit: currency
    recipes:
      - {id: direct,       requires: [discount]}
      - {id: from_prices,  requires: [list_price, sale_price], expr: "list_price - sale_price"}
      - {id: from_pct,     requires: [sale_price, discount_pct],
         expr: "sale_price * discount_pct"}

canonical_relationships:
  - {from: order_item, to: order,    via: order_id,    cardinality: many_to_one}
  - {from: order,      to: customer, via: customer_id, cardinality: many_to_one}

metric_templates:
  gross_revenue:
    requires: [unit_price, quantity]
    grain: order_item
    additivity: additive
    agg: sum
    expr: "unit_price * quantity"
  average_order_value:
    requires_metrics: [net_revenue, order_count]
    additivity: non_additive
    ratio: {numerator: net_revenue, denominator: order_count}
```

Two things carried deliberately:

- **`recipes` ordered by reliability.** Derivation is declarative and the resolver picks the
  first satisfiable recipe. A recipe is "an alternative path to a node in the graph."
- **`unit` and `tax_basis` on every monetary field.** These drive the guardrails in §5.4.
  A field without them is `unknown` and any arithmetic combining `unknown` with anything else
  is a compile error, not a warning.

### 3.3 EntityModel

```yaml
spec_version: 7
entities:
  order_item:
    grain: one row per line on an order
    key: [order_id, line_no]
    scd: type1
    partition_by: [days(order_date)]
    fields:
      order_id:   {type: string, required: true}
      line_no:    {type: int,    required: true}
      unit_price: {type: decimal(12,4), canonical: unit_price}
      quantity:   {type: int,    canonical: quantity}
      extensions: {type: variant}            # unmapped tail
relationships:
  - {name: item_of_order, from: order_item, to: order, via: {order_id: order_id},
     cardinality: many_to_one}
```

`canonical: unit_price` is the link back to the catalog. A field without it is tenant-native —
legal, but it participates in no catalog-derived metric.

### 3.4 Mapping

```yaml
mapping_version: 3
source: shopify__order_lines            # a bronze relation
target: order_item
key:
  order_id: {from: "$.order_id", transform: [to_string]}
  line_no:  {from: "$.index",    transform: [to_int]}
fields:
  unit_price:
    recipe: from_total                  # resolver chose this; recorded for reproducibility
    from: {line_total: "$.total", quantity: "$.qty"}
  quantity: {from: "$.qty", transform: [to_int]}
  order_date:
    from: "$.created_at"
    transform: [{parse_ts: "ISO8601"}, {to_utc: "Europe/Paris"}]
unmapped: ["$.note", "$.gift_wrap"]
on_unmapped_enum: quarantine
```

Note `recipe:` is **recorded, not inferred at compile time**. Resolution happens upstream
(that's where the LLM may participate); the compiler is handed a decided spec. This keeps the
compiler deterministic and makes the decision auditable.

### 3.5 Transform whitelist

A closed, versioned registry. This is the security and reviewability boundary — the set of
things a proposal can possibly say.

```python
@transform("parse_ts", arity=1)
def parse_ts(col: exp.Expression, fmt: str) -> exp.Expression: ...
```

Starter set: `trim upper lower to_string to_int to_decimal to_bool parse_ts parse_date to_utc
enum_map coalesce nullif split_part regex_extract strip_prefix strip_suffix multiply divide
round abs concat json_path`.

Rules: each transform declares input type → output type; the type checker (§5.3) verifies
chains; unknown transform name is a compile error naming the closest match.

---

## 4. Architecture — ports and adapters

The core is a pure pipeline over an IR. Everything variable is a port.

```
                         ┌─────────────────────────────┐
   Catalog ─┐            │          CORE               │
EntityModel ┼─► loader ─►│  parse → resolve → typecheck│ ──► IR (frozen, hashable)
   Mapping ─┤            │  → plan → lower             │
 MetricSet ─┘            └──────────────┬──────────────┘
                                        │
                       ┌────────────────┼────────────────┐
                       ▼                ▼                ▼
                TargetEmitter     DialectPort      NamingPolicy
                (port)            (port)           (port)
                       │                │                │
       ┌───────────────┼──────────┐     │        ┌───────┴────────┐
       ▼               ▼          ▼     ▼        ▼                ▼
  SQLMeshEmitter  DbtEmitter  CubeEmitter  SQLGlotDialect   DefaultNaming
                                            (duckdb/trino/     TenantPrefixNaming
                                             postgres/spark)
```

### 4.1 Ports

```python
class TargetEmitter(Protocol):
    """IR → framework-specific artifacts. Knows nothing about SQL dialects."""
    name: str
    def emit(self, ir: ProjectIR, ctx: EmitContext) -> tuple[EmittedArtifact, ...]: ...
    def capabilities(self) -> TargetCapabilities: ...

class DialectPort(Protocol):
    """SQL rendering + engine-specific type mapping. Wraps SQLGlot."""
    name: str
    def render(self, node: exp.Expression) -> str: ...
    def physical_type(self, t: LogicalType) -> str: ...
    def supports(self, feature: DialectFeature) -> bool: ...   # VARIANT, MERGE, SCD2 native

class NamingPolicy(Protocol):
    """Logical name → physical (namespace, relation). The only tenant-shaped seam."""
    def relation(self, entity: str, layer: Layer) -> tuple[str, str]: ...
```

`TargetCapabilities` matters: SQLMesh has native `SCD_TYPE_2_BY_KEY`; dbt needs a snapshot;
Cube has no concept of either. The core asks capabilities and either lowers differently or
raises `UnsupportedByTarget` with a specific message. **Never silently degrade.**

### 4.2 Why three ports and not one

Target and dialect vary independently — SQLMesh-on-Trino and dbt-on-Trino share dialect logic;
SQLMesh-on-DuckDB and SQLMesh-on-Trino share emitter logic. Collapsing them produces an
N×M explosion of near-duplicate templates. This split is the single most load-bearing design
decision in the package.

---

## 5. The compile pipeline

Six stages, each a pure function, each independently testable.

### 5.1 Parse

Pydantic models with `extra="forbid"`. Every model carries `source_path` for error messages.
Reject unknown keys loudly — a typo'd key that's silently ignored is the worst failure mode in
a config-driven system.

### 5.2 Resolve

Build the dependency DAG over canonical fields, entity fields, and metrics.

- Detect cycles → `CircularDerivation` naming the cycle.
- Verify every `requires` is either mapped, derivable, or explicitly marked unavailable.
- Compute the **reachable metric set**: metrics whose leaves all resolve. Everything else is
  reported as `unreachable` with the *specific missing leaf* — this is a product-facing
  output, not just a diagnostic ("you can't get margin because `cogs` is missing").
- Topologically sort for emission order. Sort ties **lexicographically** — this is the main
  determinism hazard.

### 5.3 Typecheck

Walk each transform chain: `str → parse_ts → timestamp → to_utc → timestamp` ✓.
Verify the terminal type is assignable to the declared field type. Decimal precision is
tracked and widening is explicit.

### 5.4 Guardrails

Refuse plausible-but-wrong arithmetic. These are compile errors, not warnings.

| Guardrail | Rule |
|---|---|
| **Unit coherence** | Operands of `+`/`-` must share `unit`. Currency + count is an error. |
| **Tax basis** | `net - gross` is an error. `unknown` in any arithmetic is an error. |
| **Currency** | Mixed currency codes require an explicit `convert` transform. |
| **Grain** | A derivation's operands must share a grain, or an explicit aggregation step must be present. This is the fan-out guard. |
| **Additivity** | A `non_additive` metric may not be materialised as a stored number; only its additive components may be. Emitting a stored `average_order_value` column is an error. |
| **Path conflict** | If a field has both a direct column and a satisfiable derivation, emit both plus a reconciliation audit; never pick one silently. |
| **Range sanity** | Optional per-field `assert:` clauses lowered into target-native audits. |

The grain and additivity guardrails are the highest-value part of this package. They catch the
class of bug where the formula is right, the data is right, and the answer is 3× wrong.

### 5.5 Plan (spec diff)

```python
def plan(old: ProjectIR | None, new: ProjectIR) -> Plan
```

Every change classified:

```python
class ChangeClass(StrEnum):
    ADDITIVE   = "additive"     # new optional column — metadata-only
    WIDENING   = "widening"     # decimal(10,2) → decimal(12,2)
    RENAME     = "rename"       # field-id preserved
    RESTATING  = "restating"    # same column, different meaning — backfill
    BREAKING   = "breaking"     # drop / narrow / grain change / key change
```

Plus `backfill_scope` (which entities, whether history changes) and `downstream_impact`
(which metrics depend on changed fields — computed from the DAG, no external lineage needed).

**The expand/contract rule is enforced here:** dropping or narrowing a field that a live
metric still references raises `ContractViolation`. Deprecation must come first.

### 5.6 Lower and emit

IR → target artifacts. The SELECT is a SQLGlot AST; the envelope is Jinja.

```python
@dataclass(frozen=True)
class EmittedArtifact:
    path: str            # "models/silver/order_item.sql"
    content: str
    kind: ArtifactKind   # MODEL | TEST | AUDIT | SEED | DOC | SEMANTIC
    checksum: str        # sha256 of content
```

---

## 6. Determinism

Not a nice-to-have — it's the property the whole architecture rests on.

**Rules:**
- All collections in the IR are ordered (`tuple`, not `set`; sorted `dict` keys on emission).
- Never iterate a `set`. Ban it in review; `ruff` custom rule if you can.
- `PYTHONHASHSEED` must not affect output — tested explicitly.
- No `datetime.now()`, no `uuid4()`. If an artifact needs a timestamp, it's an input parameter.
- Float formatting pinned; prefer `Decimal` throughout.
- `sqlglot` version pinned exactly, and the pin bump is a deliberate PR with regenerated
  snapshots.

**Test:**

```python
def test_determinism_across_processes(project):
    out = subprocess.run([sys.executable, "-c", SCRIPT], env={"PYTHONHASHSEED": "0"}, ...)
    out2 = subprocess.run([sys.executable, "-c", SCRIPT], env={"PYTHONHASHSEED": "1"}, ...)
    assert out.stdout == out2.stdout
```

Also expose `project_fingerprint(ir) -> str` — a content hash of the IR — so callers can cache
compilation results and detect "someone edited an applied spec."

---

## 7. Testing strategy

This is where the package earns its separateness. Six layers, fastest first.

### 7.1 Unit — pure, milliseconds

Parse errors, transform typing, DAG resolution, guardrail triggers, diff classification.
Target: 90%+ of test count, 100% of guardrail branches.

### 7.2 Snapshot / golden files

Every (fixture project × target × dialect) pair renders to a checked-in golden file.

```
tests/golden/
  ecom_basic/
    sqlmesh/duckdb/models/silver/order_item.sql
    sqlmesh/trino/models/silver/order_item.sql
    dbt/postgres/models/silver/order_item.sql
    cube/model/cubes/order_item.yml
```

`pytest --snapshot-update` regenerates. **Review golden diffs like source code** — an
unexplained diff means the compiler changed behaviour.

### 7.3 Property-based (Hypothesis)

Generate random valid projects and assert invariants that must hold for all inputs:

- Emitted SQL always parses under the target dialect (`sqlglot.parse_one` round-trips).
- Every column in the emitted SELECT appears in the entity's declared fields, and vice versa.
- `plan(ir, ir)` is always empty.
- `plan(a, b)` classifying nothing as BREAKING implies b's columns ⊇ a's referenced columns.
- Compiling twice yields identical bytes.

This layer finds the bugs snapshots can't, because it explores shapes you didn't think to write.

### 7.4 Execution tests — DuckDB, in-process

The core integration layer. Seed fixture data, compile, execute, assert results.

```python
def test_derivation_from_total(duckdb_conn, ecom_project):
    seed(duckdb_conn, "bronze.order_lines", [{"total": "30.00", "qty": 3}])
    for a in compile_project(ecom_project, Target.SQLMESH, dialect="duckdb"):
        duckdb_conn.execute(extract_select(a))
    assert fetch_one("SELECT unit_price FROM silver.order_item") == Decimal("10.00")
```

Include a **fan-out regression suite** — the shipping-cost-duplicated-across-line-items case,
asserted numerically. This is the bug class that motivated the grain guardrail; it deserves
executable proof.

### 7.5 Dialect matrix — testcontainers

The same fixture assertions, run against real engines. Slower, so nightly + pre-release rather
than per-commit.

| Engine | How | When |
|---|---|---|
| DuckDB | in-process | every commit |
| Postgres | testcontainers | every commit (it's fast) |
| Trino + Iceberg + MinIO | docker-compose | nightly |
| Spark | testcontainers | nightly |

Mark with `@pytest.mark.engine("trino")` and select in CI.

### 7.6 Target framework end-to-end

Prove the emitted artifacts are actually valid input to the target, not just valid SQL.

```python
def test_sqlmesh_accepts_output(tmp_path, ecom_project):
    write_artifacts(tmp_path, compile_project(ecom_project, Target.SQLMESH, dialect="duckdb"))
    ctx = sqlmesh.Context(paths=tmp_path)       # parses; raises on malformed MODEL blocks
    plan = ctx.plan(environment="test", auto_apply=True, no_prompts=True)
    assert not plan.has_changes                  # replan is a no-op — determinism, end to end
```

That last assertion is the strongest single test in the suite: it proves the compiler and
SQLMesh agree on what the models mean.

Do the equivalent for Cube (`cubejs` container loads the model, `/meta` returns expected
measures and dimensions) and dbt (`dbt parse`).

### 7.7 Fixture projects

Keep a small, curated set — these become your regression corpus and, later, the eval set for
LLM proposals:

| Fixture | Exercises |
|---|---|
| `minimal` | one entity, one mapping, direct fields |
| `ecom_basic` | catalog derivation, ratio metrics, date dimension |
| `fanout_trap` | order-grain measure joined to line grain |
| `semi_additive` | inventory balance over time |
| `messy_types` | string numerics, mixed date formats, dirty enums |
| `multi_source` | two sources → one entity, identity xref |
| `evolution_v1..v5` | expand/contract sequence for diff tests |

---

## 8. Public API

```python
# Loading (pure — you pass strings, not paths)
load_catalog(text: str) -> Catalog
load_project(sources: Mapping[str, str]) -> Project

# Compiling
compile_project(project: Project, *, target: Target, dialect: str,
                naming: NamingPolicy = DefaultNaming(),
                catalog: Catalog | None = None) -> tuple[EmittedArtifact, ...]

# Analysis (no emission)
resolve(project, catalog) -> Resolution      # reachable/unreachable metrics + reasons
plan(old_ir, new_ir) -> Plan
project_fingerprint(ir) -> str

# Extension
register_transform(spec: TransformSpec) -> None
register_emitter(emitter: TargetEmitter) -> None
```

Everything else is private. Keep the surface small; you'll want to refactor the IR.

---

## 9. Emitter notes

### SQLMesh (primary)

Emit `MODEL (...)` blocks with `kind`, `grain`, `partitioned_by`, `audits`. Prefer native
`SCD_TYPE_2_BY_KEY` over hand-rolled SCD.

Investigate **Python models** (`@model(is_sql=True)` returning a SQLGlot expression) as an
alternative to writing files: for a multi-tenant deployment that turns N×M generated files
into a registration call. Decide this in week one — it changes the emitter's shape.

### Cube (semantic/gold)

Emit `cubes:` and `views:` YAML with measures carrying `type` (sum/count/count_distinct/number)
and `meta.additivity` / `meta.grain` propagated from the IR. Non-additive metrics emit as
calculated measures over additive components, never as stored aggregates.

### dbt (compatibility)

Lower `SCD_TYPE_2` to a snapshot, `audits` to schema tests. Emit `UnsupportedByTarget` for
what doesn't map. Ship it to prove the port abstraction works — that's its real job.

---

## 10. Package layout

```
smelter/
  __init__.py            # public API only
  errors.py              # SmelterError hierarchy, source paths
  spec/                  # pydantic models: catalog, entity, mapping, metrics
  ir/                    # frozen IR + fingerprint
  resolve/               # DAG, recipes, reachability
  typing/                # logical types, transform signatures
  guardrails/            # unit, tax, grain, additivity, conflict
  transforms/            # the whitelist registry
  plan/                  # diff + change classification
  emit/
    base.py              # TargetEmitter, TargetCapabilities
    sqlmesh/  dbt/  cube/
  dialects/              # DialectPort impls over sqlglot
  naming.py
tests/
  unit/  golden/  property/  execution/  engines/  e2e/  fixtures/
```

---

## 11. Milestones

| # | Scope | Done when |
|---|---|---|
| M1 | Spec models, IR, fingerprint, errors | round-trips a fixture, fingerprint stable across processes |
| M2 | Resolve + typecheck, no catalog | `minimal` compiles to a SQLMesh DuckDB model that runs |
| M3 | Catalog + recipes + reachability | `ecom_basic` reports reachable/unreachable metrics correctly |
| M4 | Guardrails | `fanout_trap` and `semi_additive` fail closed with useful messages |
| M5 | `plan()` + change classification | `evolution_v1..v5` classified correctly; contract violation caught |
| M6 | Second dialect (Trino) + second target (Cube) | golden matrix green; port abstraction validated |
| M7 | E2E SQLMesh + Cube containers | `plan.has_changes == False` on replan |

M1–M4 is the useful core; M6 is where you find out whether the port design was right, so
don't defer it past M6 — a second target discovered late means an IR rewrite.

---

## 12. Open questions to settle early

1. **Files or Python models for SQLMesh?** Affects the emitter contract fundamentally.
2. **Where does identity resolution live?** Xref/edge generation is arguably a separate
   emitter concern; keeping it out of M1–M5 is probably right.
3. **Does the compiler own the date dimension?** It's a catalog-level artifact every tenant
   needs. Emitting it from the catalog is tempting and probably correct.
4. **Incremental strategy per entity** — declared in the spec, or inferred from grain and
   partition key? Inferring is nicer and harder to explain when it's wrong.
5. **How are quarantine tables modelled?** As entities in the IR, or as an emitter-level
   convention? IR is more honest but adds surface.
