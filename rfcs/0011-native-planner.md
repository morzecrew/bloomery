# RFC 0011 — Native planner: MetricRequest → QueryPlan

- **Status:** ✅ Complete as contract — shipped 2026-08-07 (M7): the
  request/`QueryPlan` contract, refusal policy, `RowPolicy` semantics, `Explanation`
  shape, and error taxonomy all ship verbatim behind `MetricFlowPlanner`
  (`bloomery/planner/`); the native SQL assembly, additivity lowering, and
  mart-selection internals (§algorithm steps 2–4) remain superseded by
  [RFC 0013](0013-metricflow-backend.md) per the MetricFlow pivot
  ([`_bloomery-metricflow-pivot.md`](_bloomery-metricflow-pivot.md)) — this RFC
  stays the binding behavior spec, not the implementation.
- **Scope:** The in-process query planner (`bloomery/planner/` — `request.py`, `select.py`,
  `build.py`, `additivity.py`, `policy.py`, `explain.py`): the `Planner` port, the
  `MetricRequest`/`QueryPlan` request/response types, the six-step planning algorithm,
  additivity lowering, role-played dimension resolution, `RowPolicy` injection, and the
  deterministic `Explanation`. The planner is a fourth port beside RFC 0008's three — it
  answers at request time, thousands of times per second, where emitters run once per spec
  version. Does not cover mart modelling (RFC 0010), the serializable `CompiledSemantic`
  artifact the planner will hydrate from (RFC 0012), or execution — the planner returns SQL
  text and never runs it. The shipped backend behind the `Planner` port is now the
  MetricFlow adapter (RFC 0013, `MetricFlowPlanner`); this RFC defines the stable planner
  contract — request/response types, refusals, policy — that makes that backend choice
  reversible.
- **Related:** [`rfcs/_bloomery-changes.md`](_bloomery-changes.md) D1, D3, D4, D8, D9;
  RFC 0003 (IR, `SqlExpr`), RFC 0004 (types, difflib suggestions), RFC 0006 (additivity
  guardrail — compile-time half of this RFC's request-time half), RFC 0008 (`DialectPort`),
  RFC 0009 (execution/equivalence suites), RFC 0010 (marts, `DimensionRef`), RFC 0012
  (`CompiledSemantic`).

---

## 1. Summary

A pure-function planner: `plan(ir, request, *, dialect, policy=None) -> QueryPlan`. It
validates a `MetricRequest` against the IR, selects exactly one mart, lowers each measure
through its additivity policy, assembles a SQLGlot AST (`SELECT dims, AGG(measures) FROM
mart WHERE filters AND policy GROUP BY dims`), renders via `DialectPort`, and attaches a
deterministic `Explanation`. It never joins, never executes, and refuses — with a named
reason — anything it cannot answer correctly.

## 2. Motivation

External semantic layers were evaluated and rejected as load-bearing dependencies
(`_bloomery-changes.md` §0): Cube carries per-tenant resident memory and a ~1–10 rps/node
ceiling; BSL cannot join one dimension table twice under different foreign keys, which
role-playing dates make unavoidable. Because gold is one wide, pre-joined mart per
(grain × subject area) with dimensions flattened at build time (RFC 0010), the planner
collapses from distributed join planning to "assemble a GROUP BY" — ~1.5–2.5k lines
including tests — and owning it removes the only irreversible external dependency from the
path of every number a user sees. Cube remains a supported emit target (RFC 0008), off the
critical path.

## 3. Current state

Greenfield. RFC 0003 fixes the IR and `SqlExpr`; RFC 0008 fixes `DialectPort` and the
three existing ports; RFC 0006 D6 already enforces the compile-time additivity half
(non-additive metrics never stored). RFC 0010 supplies `MartSpec`/`DimensionRef` and the
mart catalogue the planner selects from. Source material is `_bloomery-changes.md` D1
(planner), D3 (role-playing, consumer side), D4 (additivity lowering), D8 (explanations),
D9 (tenant-agnosticism); this RFC is their design lock.

## 4. Goals / Non-goals

**Goals**

- A `Planner` Protocol as the fourth port, with `NativePlanner` as the shipped adapter.
- Total request-time errors: every malformed or unanswerable request fails validation
  with a typed `PlannerError`; nothing executes, nothing degrades silently.
- Row-level policy injection that provably survives every query shape.
- Every plan self-describing: typed column envelope, warnings, provenance, cache key.

**Non-goals**

- Query execution or result caching — the caller's job; `QueryPlan.fingerprint` is the
  cache key, the planner never sees a connection.
- Query-time joins or multi-fact resolution — structurally excluded, not deferred (§5.3).
- Policy resolution — the planner takes a `RowPolicy` value; deciding whose policy applies
  is upstream identity work the package must not know about (D9, hard invariant #3).
- Compiling marts — RFC 0010; the planner only reads them.

## 5. Design

### 5.1 The fourth port

Emitters produce artifacts ahead of time, once per spec version; the planner answers at
request time, thousands of times per second. Different lifecycle, different performance
envelope, different port — folding it into `TargetEmitter` was rejected because the
`emit()` contract (artifact tuples, `EmitContext`) fits neither the call rate nor the
return shape.

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

Pure function: SQL text plus metadata out, no I/O, no clock, no execution.
`NativePlanner(max_limit=50_000)` is the concrete adapter; `max_limit` is the limit
ceiling (§5.3). The planner will accept `ProjectIR | CompiledSemantic` — the hydrated
artifact of RFC 0012 is "everything the planner needs and nothing else"; the final
signature call is deferred to RFC 0012 (§10).

### 5.2 Request and response types

All frozen dataclasses (`bloomery/planner/request.py`), verbatim from D1:

```python
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

`MetricRequest` is a **static shape with dynamic content** — this is what an upstream
Query Agent emits; it never writes SQL. A malformed request fails validation; it does not
execute.

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
    explanation: Explanation          # §5.6
    fingerprint: str                  # sha256(sql) — result cache key
```

`columns` is the self-describing envelope: the caller gets typed metadata without knowing
the row shape in advance. Never return bare rows without it.

### 5.3 Algorithm and refusals

*(Steps 2–4 superseded by RFC 0013 — retained as the specification of required behavior;
MetricFlow now produces the SQL, and these semantics are enforced via the R1 mapping +
execution tests rather than hand-written lowering. Step 2's mart selection survives as
the coverage precheck (RFC 0013 R3), which runs before any request is delegated to
MetricFlow — refusal before delegation. The refusal messages, hard rules, and error
taxonomy below remain binding.)*

Six steps, in order:

```
1. VALIDATE   every metric and dimension exists → UnknownMember(name, did_you_mean=…)
2. SELECT     marts covering all measures AND exposing all dimensions (select.py)
              0 → UnreachableAtGrain; 1 → use it;
              N → lowest cost_hint, ties lexicographic by mart name (determinism)
3. LOWER      each measure through its additivity policy (§5.4, additivity.py)
4. BUILD      SQLGlot AST: SELECT dims + aggregated measures FROM mart
              WHERE filters AND policy_predicate GROUP BY dims ORDER BY / LIMIT (build.py)
5. RENDER     dialect.render(ast)   — RFC 0008 DialectPort
6. EXPLAIN    Explanation from the decisions above (explain.py)
```

`did_you_mean` uses `difflib.get_close_matches` over the sorted member list, consistent
with RFC 0004 D4. Hard rules:

- **Never join at plan time.** A request needing two marts raises `UnreachableAtGrain`
  naming the per-metric conflict exactly:

  ```
  UnreachableAtGrain: metrics {shipping_cost, line_discount} live on different grains
    shipping_cost   → grain: order      (mart: gold.mart_orders)
    line_discount   → grain: order_item (mart: gold.mart_order_items)
    Summing across grains would double-count. Request them separately,
    or define a mart at the shared grain.
  ```

  Refusing with a reason is correct behaviour; a plausible wrong number is not. The
  product requirement is *"the system may not know the answer, but may not return a wrong
  one without warning."*
- **`RowPolicy` is injected into the AST** (`policy.py`): the predicate string is parsed
  via sqlglot and conjoined into the WHERE clause — never string-appended, never
  templated.
- **`order_by` fields must appear in `metrics` or `dimensions`** — no arbitrary
  expressions; that's an injection surface. Violation → `InvalidRequest`.
- **`limit` is clamped** to the `NativePlanner(max_limit=50_000)` ceiling; clamping
  appends a warning to `QueryPlan.warnings`.

Errors: `PlannerError(BloomeryError)` with leaves `UnknownMember`, `UnreachableAtGrain`,
`AmbiguousDimension`, `InvalidRequest` (bad op/order_by/limit shapes) — all declared in
`bloomery/errors.py` per RFC 0002 D3. Planner errors are **not batched** — a deliberate
deviation from the compile-time batching doctrine (RFC 0002 D6): the caller is
interactive and fixes one request at a time, and validation is the first step, so most
failures are singular anyway. First failure wins.

### 5.4 Additivity lowering (D4 — implement exactly)

*(Superseded by RFC 0013 — retained as the specification of required behavior; MetricFlow
now produces the SQL, and these semantics are enforced via the R1 mapping + execution
tests rather than hand-written lowering.)*

**Additive** → `SUM(expr)` at whatever grain was requested.

**Semi-additive** (`SemiAdditivePolicy(over: DimensionRef, rule: last|first|avg|max|min)`)
→ sum across every dimension *except* `over`; apply `rule` along `over`:

```sql
-- inventory_balance, semi_additive over shipped_date, rule=last
SELECT warehouse,
       SUM(balance) AS inventory_balance
FROM   gold.mart_inventory_daily
WHERE  day = (SELECT MAX(day) FROM gold.mart_inventory_daily WHERE <same filters>)
GROUP BY warehouse
```

When `over` is itself requested at a coarser time grain, apply the rule *within* each
bucket (last day of each month), then sum across the other dimensions.

**Non-additive** → never stored, never summed; always recomputed from additive components
at the requested grain (`RatioSpec(numerator, denominator)`):

```sql
-- average_order_value = net_revenue / order_count
SELECT store,
       SUM(net_revenue) / NULLIF(SUM(order_count), 0) AS average_order_value
FROM   gold.mart_orders
GROUP BY store
```

A non-additive measure without a `RatioSpec` or equivalent recipe is
`NonAdditiveWithoutComponents` — a resolution/guardrail-stage error (RFC 0006's
compile-time refusal), so the planner never meets one. This is the request-time half of
RFC 0006 D6's defense-in-depth: guardrails refuse storing the wrong number; the planner
refuses computing it.

### 5.5 Role-played dimensions (D3, consumer side)

Every dimension reference in `MetricRequest`, `FilterExpr`, and `OrderSpec` is parsed
into a `DimensionRef` (defined in the IR, RFC 0010). An unqualified reference to a
dimension with multiple roles is an error naming the available roles:

```
AmbiguousDimension: 'date' has roles [ordered, shipped]. Use 'ordered_date' or 'shipped_date'.
```

Because the planner reads flattened mart columns (`ordered_month`, `shipped_month`) and
performs no joins, role-playing "just works" here — the problem that breaks BSL does not
exist on this path.

### 5.6 Explanation (D8)

Generated deterministically from the plan, never from an LLM:

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

Product requirement: every number ships with how it was computed — the Query Agent
attaches this as provenance, and it is the first debugging tool when a number looks wrong.

### 5.7 Tenant-agnosticism (D9)

`RowPolicy` is a value object holding a predicate string parsed as SQL — not a tenant
identity, not a session, not a security context. The planner takes it as a parameter and
never resolves one. The word "tenant" may appear only in `naming.py` docstrings; a CI
grep check enforces this (`grep -ri "tenant" src/bloomery/` allowlisting `naming.py`),
added to the `just quality` gate (RFC 0001 D4).

## 6. Tests

- **Mandatory pre-merge:** `test_row_policy_survives_every_path` — for every request in
  an exhaustive matrix (limits, ordering, filters, all grains), plan with
  `RowPolicy(predicate="tenant_id = 'acme'")`, parse the SQL, and assert the policy
  predicate is present in **every table scan of the parsed AST** — never a SQL substring
  check: "a string check passes on `-- tenant_id = 'acme'`" (D1).
- **Execution suite** (RFC 0009 fixtures `semi_additive_inventory`, `non_additive_aov`),
  hard-coded assertions per D4: inventory 100/80/90 over Jan 1–3 → **90, not 270**;
  warehouses A 90 + B 40 on Jan 3 → **130** (summing across non-`over` dims is correct);
  AOV over 10 orders/100 000 + 100 orders/200 000 → **2727.27, never 6000 or 12000**.
- **Equivalence:** RFC 0009's amended scope — now three-way, MetricFlow ↔ Cube ↔
  hand-written reference SQL (RFC 0009 §5.8), nightly; planner refusals must be refused
  by Cube too or listed in a reviewed `known_divergences.yaml`.
- **Unit:** validation suggestions, coverage-precheck 0/1/N selection with tie-breaks,
  clamping warning, every `PlannerError` leaf. *(Unit tests of our own lowering and
  SQLGlot build are superseded by RFC 0013 — those modules are not built; the lowering
  semantics of §5.4 are asserted by execution tests against MetricFlow-generated SQL.)*
- **Property:** planner SQL always parses under the requested dialect;
  `plan(ir, req)` called twice → identical `QueryPlan` (determinism, RFC 0003).

## 7. Docs

How-to `pages/how-to/plan-queries.md`; explanation page on why refusal beats a plausible
wrong number (seeded from §5.3's `UnreachableAtGrain` example); reference for
`MetricRequest`/`QueryPlan`/`Explanation`. The no-join property must be documented as a
feature, not a gap, so nobody "fixes" it.

## 8. Out of scope

- **Result caching / execution** — callers own connections; `fingerprint` is the designed
  hook.
- **Cross-mart stitching in the caller** (issuing two plans and joining client-side) —
  legitimate, but it happens above the port; the planner's refusal message names it.
- **Cost-based mart selection beyond `cost_hint`** — statistics require I/O; the static
  hint plus lexicographic ties keeps planning pure and deterministic.

## 9. Risks

- *`UnreachableAtGrain` read as a planner deficiency* → pressure to add joins. Mitigation:
  the error message names the remedy (a mart at the shared grain), and docs frame no-join
  as the structural fan-out guarantee.
- *Policy predicate parse failures at request time* (bad predicate string) — surfaced as
  `InvalidRequest` naming the predicate, never silently dropped (dropping a row policy
  fails open).
- *Per-request IR traversal too slow at thousands of rps* — hydration caching is the
  designed answer (RFC 0012's `CompiledSemantic`, budgets revised by RFC 0014 to 50 ms
  cold / 10 ms warm); the port signature already anticipates it.

## 10. Unresolved questions

- Exact input type: `plan()` accepts `ProjectIR | CompiledSemantic`; whether v0.1 ships
  both or `CompiledSemantic` only is RFC 0012's call.
- `MeasureExplanation`'s exact fields — implementation settles; `render()` output is
  locked by golden tests once written.

## 11. Decisions

| # | Decision |
| --- | --- |
| 1 | The planner is a **fourth port**, separate from `TargetEmitter`: request-time, called thousands of times/sec vs once per spec version — different lifecycle, different envelope. `Planner.plan(ir, request, *, dialect, policy=None) -> QueryPlan`, a pure function returning SQL text + metadata, executing nothing. |
| 2 | Request/response types verbatim from D1: `TimeGrain`, `FilterExpr`, `OrderSpec`, `MetricRequest` (static shape, dynamic content — what the Query Agent emits; malformed requests fail validation, never execute); `ColumnDescriptor`, `QueryPlan` (sql, self-describing `columns` envelope, mart, warnings, explanation, `fingerprint = sha256(sql)`). All frozen dataclasses. |
| 3 | Six-step algorithm: validate (`UnknownMember` with `did_you_mean` via difflib, RFC 0004 D4) → mart selection (0 → `UnreachableAtGrain` naming the per-metric grain/mart conflict; 1 → use; N → lowest `cost_hint`, ties lexicographic by mart name) → additivity lowering → SQLGlot AST build → `dialect.render` → `Explanation`. |
| 4 | Hard rules: never join at plan time (refusal with reason beats a plausible wrong number); `RowPolicy` predicate parsed via sqlglot into the WHERE conjunction of the AST, never string-appended; `order_by` fields must be requested metrics/dimensions (injection surface); `limit` clamped to `NativePlanner(max_limit=50_000)`, clamping adds a `QueryPlan.warnings` entry. |
| 5 | Additivity lowering per D4 exactly: additive → SUM at requested grain; semi-additive (`SemiAdditivePolicy(over, rule ∈ last/first/avg/max/min)`) → sum across every dimension except `over`, rule along `over` (coarser requested grain: rule within each bucket, then sum); non-additive → never stored/summed, recomputed from additive components (`RatioSpec` → `SUM(num)/NULLIF(SUM(den),0)`); missing components = `NonAdditiveWithoutComponents` at resolution/guardrail stage (RFC 0006 defense-in-depth). |
| 6 | Every dimension reference in `MetricRequest`/`FilterExpr`/`OrderSpec` parses into a `DimensionRef` (RFC 0010); unqualified reference to a multi-role dimension → `AmbiguousDimension` naming the roles. The planner reads flattened mart columns — no joins, so role-playing needs no planner logic. |
| 7 | `RowPolicy` is a value object holding a SQL predicate — not a tenant identity/session/security context; the planner never resolves policies (D9). "tenant" may appear only in `naming.py` docstrings, enforced by a CI grep added to `just quality` (RFC 0001 D4). |
| 8 | `Explanation` is deterministic, generated from the plan, never from an LLM; dataclass + `render()` per D8. Product requirement: every number ships with how it was computed. |
| 9 | Errors: `PlannerError(BloomeryError)` with leaves `UnknownMember`, `UnreachableAtGrain`, `AmbiguousDimension`, `InvalidRequest`, all declared in `bloomery/errors.py` (RFC 0002 D3). Planner errors are **not batched** — deviation from compile-time batching, justified: the interactive caller fixes one request, and validation-first means failures are mostly singular. |
| 10 | Mandatory pre-merge test: row-policy-survives-every-path, asserted on the **parsed AST** (predicate present in every table scan), never on a SQL substring — "a string check passes on `-- tenant_id = 'acme'`" (D1). |
| 11 | **Supersession split (MetricFlow pivot):** the request/`QueryPlan` contract, refusal policy, `RowPolicy` semantics, `Explanation` shape, and error taxonomy (D1–D2, D4, D6–D10) remain binding on the backend; the native SQL assembly, additivity lowering, and mart-selection internals (D3 steps 2–4, D5) are superseded by RFC 0013. Mart selection survives as the coverage precheck (RFC 0013 R3) — refusal before delegation. |
| 12 | Additivity lowering correctness (§5.4's semantics — 90-not-270, 130 across warehouses, 2727.27) is now asserted by **execution tests against MetricFlow-generated SQL** (RFC 0009 §5.10), not by unit tests of our own lowering code — no such code exists under RFC 0013. |
| 13 | *(Appended 2026-08-07, M14 — RFC 0015.)* D2's request/filter types are superseded by RFC 0015's query vocabulary: `FilterExpr` is renamed `Predicate` with the closed `Op` set (`between`/`contains` removed; `like`/`ilike` added; `is_null` takes exactly one bool), filters are CNF (`Clause = Predicate \| AnyOf`, implicit AND, one disjunction level), `Scalar` widens with the string carrier and the non-finite guard, and `RowPolicy.as_filter()` renames to `as_clause()`. The rest of this contract — `QueryPlan`, refusal policy, `Explanation` shape, D4/D6–D10 — is untouched. |

## 12. Phasing

Per the pivot's milestone table (`_bloomery-metricflow-pivot.md` §8): verification tasks
V1–V4 land at M4.5, the MetricFlow emitter (RFC 0013 R1) at M6, and the planner ships at
**M7** — `MetricFlowPlanner` plus the coverage precheck, name bridging, filter rendering,
and row policy, with every fixture assertion green against DuckDB, filter fuzzing green,
and the policy AST test green. Hydration and caching (RFC 0014) land at M8 and slot into
the already-shaped `plan()` input; the three-way equivalence suite lands at M11, after
the Cube emitter (M10).
