# RFC 0009 — Testing strategy and fixture corpus

- **Status:** 🚧 In progress — shipped 2026-08-07: tiers 1–4 (unit / golden matrix /
  Hypothesis / DuckDB execution), the determinism and tenant-agnosticism guards, the
  Postgres engine tier, the hydration bench lane, and the local SQLMesh replan no-op
  e2e (`tests/e2e/test_sqlmesh_replan.py` — this RFC's strongest single test, no
  containers needed); remaining: Trino/Spark engine containers, the Cube container
  e2e, dbt parse, and the three-way equivalence suite (nightly tier).
- **Scope:** The whole test suite: seven tiers (unit, golden, property, execution, engine
  matrix, target e2e, planner equivalence), the `tests/` layout and marker taxonomy, the
  shared fixture corpus, the golden-file review contract, the determinism and
  tenant-agnosticism guards, the `tests/bench/` lane, and coverage gates. Covers *how
  the package is verified*, not what any stage computes — stage RFCs 0002–0008 and
  0010–0012 name their tests; this RFC pins where they live, how they run, and the
  cross-cutting invariants.
  New trees: `tests/*`; config in `pyproject.toml` only. No `src/` changes.
- **Related:** [`rfcs/_original-smelter-spec.md`](_original-smelter-spec.md) §6, §7;
  [`rfcs/_bloomery-changes.md`](_bloomery-changes.md) D4, D7, D9, D10;
  RFC 0002 (spec layer the fixtures load through), RFC 0003 §5.6 (determinism tests housed
  here), RFC 0007 (`plan()` invariants), RFC 0008 (emitters the goldens pin), RFC 0010
  (marts/role-playing the new fixtures exercise), RFC 0011 (planner obligations §5.10),
  RFC 0012 (hydration benchmark §5.9);
  [`rfcs/_bloomery-metricflow-pivot.md`](_bloomery-metricflow-pivot.md) R10, §8;
  RFC 0013 (MetricFlow backend — the planner under test), RFC 0014 (hydration,
  supersedes RFC 0012's budgets).
- **Origin:** Tier structure from the original spec §7; house conventions from the sibling
  project `forze` (`tests/README.md`, strict markers, unit-mirrors-src, coverage floors).

---

## 1. Summary

Seven tiers, fastest first: unit, golden snapshots, Hypothesis properties, in-process
DuckDB execution, testcontainers engine matrix, target-framework e2e, and planner
equivalence (three-way: MetricFlow ↔ Cube ↔ reference SQL, §5.8) — all exercising one
shared corpus of fourteen YAML fixture projects loaded through the public
`load_project`/`load_catalog` API; outside
the tiers, `tests/bench/` runs the scheduled hydration benchmark (§5.9, RFC 0014).
`just test` runs tiers 1–4 per commit; engines, e2e, and equivalence are opt-in markers,
nightly. Golden diffs are reviewed like source code; determinism and tenant-agnosticism
are proven by named guard tests, not by convention.

## 2. Motivation

The package's hard invariants — purity, determinism, total errors (spec §1.2) — are only
worth claiming if enforced mechanically. The bug class that motivated the project (fan-out:
formula right, data right, answer 3× wrong — spec §5.4, §7.4) is invisible to snapshots and
only provable by executing compiled SQL against seeded data. The determinism contract
(RFC 0003) fails *intermittently* when violated — exactly the failure mode a per-commit
subprocess test with perturbed `PYTHONHASHSEED` catches. Testing "is where the package
earns its separateness" (spec §7); this RFC makes that a checkable structure.

## 3. Current state

Greenfield: `tests/` is empty scaffolding. The forze suite (its `tests/README.md` and
`[tool.pytest.ini_options]`) establishes the house conventions adopted here:
`--strict-markers --strict-config`, `tests/unit` mirroring `src`, `tests/support/` for
shared fixtures, a `tests/README.md` tier table, `fail_under=80` with per-package floors.
Stage RFCs 0002–0008 and 0010–0012 each carry a §6 naming their tests; those land in the
trees here.

## 4. Goals / Non-goals

**Goals**

- One layout and marker taxonomy every stage RFC's tests slot into without debate.
- A fixture corpus that is simultaneously regression suite, doc example set, and (later)
  LLM-proposal eval set — one artifact, three audiences.
- Per-commit feedback in seconds (tiers 1–3), minutes (tier 4); heavyweight tiers behind
  markers so they never slow the inner loop.
- Guardrail branches at 100% coverage — the guardrails are the product (spec §5.4).

**Non-goals**

- Testing SQLGlot itself — beyond "parses and round-trips", dialect rendering correctness
  is SQLGlot's job; ours is feeding it deterministic ASTs.
- Performance benchmarks beyond hydration — `tests/bench/` ships exactly one asserted
  benchmark, the manifest-hydration ceiling (§5.9, RFC 0014); broader perf
  suites wait until compilation cost is observed to matter.
- Data-quality testing of tenant data — the compiler emits audits; targets run them.

## 5. Design

### 5.1 Layout and markers

```text
tests/
  unit/         # tier 1 — mirrors src/bloomery (test_spec/, test_ir/, test_guardrails/, …)
  golden/       # tier 2 — checked-in artifacts per (fixture × target × dialect)
  property/     # tier 3 — Hypothesis suites
  execution/    # tier 4 — DuckDB in-process, incl. fan-out regression suite
  engines/      # tier 5 — testcontainers matrix
  e2e/          # tier 6 — sqlmesh / dbt / cube acceptance
  equivalence/  # tier 7 — three-way: MetricFlow ↔ Cube ↔ reference SQL (§5.8)
  bench/        # perf lane — hydration benchmark (§5.9, RFC 0014), scheduled
  fixtures/     # the corpus (§5.3) — YAML spec files only, no Python
  support/      # shared helpers: strategies.py, seeding, artifact/SQL extraction
  README.md     # tier table + how to run each (the forze pattern)
```

Markers, declared in `pyproject.toml` under `--strict-markers`/`--strict-config`: `unit`,
`property`, `execution`, `engine(<name>)`, `e2e`, `perf`. Default selection (`just test`)
excludes `engine`/`e2e`/`perf` — tiers 1–4 run; tier 5 is selected per-engine in CI
(`-m 'engine("postgres")'` per-commit; trino/spark nightly); tier 6 is `-m e2e`, nightly;
tier 7 rides the `engine("cube")` marker, nightly (§5.8); `tests/bench/` is `-m perf`,
a scheduled job (§5.9). `tests/unit` mirrors `src/bloomery` module-for-module, so a
failing test names its module.

### 5.2 Tier contracts

| Tier | Cadence | Contract |
| --- | --- | --- |
| 1 unit | per-commit | Pure, milliseconds. Parse errors (type + `source_path` asserted, RFC 0002), transform typing, DAG resolution, guardrail triggers, diff classification. 90%+ of test count; 100% of guardrail branches (§5.7). |
| 2 golden | per-commit | Every (fixture × target × dialect) cell byte-compared against checked-in files, plus a `metricflow/manifest.json` per fixture; `pytest --snapshot-update` regenerates (§5.4 — note the planner-SQL vs compiler-artifact doctrine split). |
| 3 property | per-commit | Hypothesis over random *valid* projects (invalid inputs are unit-tier explicit cases); invariants §5.5. |
| 4 execution | per-commit | In-process DuckDB: seed bronze rows, execute every compiled SELECT, assert numeric results with `Decimal` (never float — RFC 0003 D5). Houses the fan-out regression suite (spec §7.4): shipping-cost-duplicated-across-line-items, asserted numerically against `fanout_trap` — plus the hard-coded additivity assertions (§5.10). |
| 5 engines | postgres + trino nightly (see D21 on the connector and on `spark`) | Tier-4 assertions against real engines via testcontainers; `@pytest.mark.engine("trino")` etc.; deselected by default. |
| 6 e2e | nightly | Artifacts are valid *input to the target*, not just valid SQL: `sqlmesh.Context` parses them, applies a plan, and a replan asserts `plan.has_changes == False` — the strongest single test in the suite (compiler and SQLMesh agree on what the models mean). Equivalents: `dbt parse`; a cube container's `/meta` returns the expected measures/dimensions (built — D24, which also issues a query, since parsing a model and running its measure expression are different claims). |
| 7 equivalence | nightly (built — D24; corpus smaller than the ~40 below, deliberately) | Three-way (§5.8): MetricFlow ↔ Cube on every request in `golden_requests.yaml`, result frames equal within `atol=0.01`; hand-written reference SQL for the ~15 hardest requests is the tiebreaker when the engines disagree. Refusals must match or carry a reviewed justification in `known_divergences.yaml`. |

> **Amended 2026-08-10 (D21–D23):** three corrections this tier's construction forced.
> **Trino** uses the `memory` connector, not `iceberg+minio` — bloomery emits SELECTs and
> models and never storage-format DDL, so an object store and a table format would be
> three more moving parts serving no assertion. **`spark` is struck**: RFC 0008 ships
> three dialects — DuckDB, Postgres, Trino — and there is no Spark dialect for a Spark
> cell to exercise, so the word promised a matrix column that could never have had a
> test in it. **dbt's cell is `dbt parse`, and that is now a deliberate limit rather
> than a shorthand**: `dbt build` on the emitted project fails, for a reason that is
> bloomery's (D22).
>
> **Amended 2026-08-11 (D25):** dbt's cell is `parse` + `compile` + `build`. D22's
> limit is lifted — RFC 0008 D20 took both of its candidate fixes — and the middle
> word is not redundant: `parse` does not resolve test macros, so it accepts a test
> named `utter_nonsense_not_a_test` in silence (RFC 0008 D19).

### 5.3 Fixture corpus

The spec §7.7 set, extended by the planner fixtures of
[`_bloomery-changes.md`](_bloomery-changes.md) D7, as YAML documents under
`tests/fixtures/<name>/`, loaded only through the public `load_project`/`load_catalog`
API — fixtures double as the doc examples and, later, the LLM-proposal eval set, so they
must exercise the surface callers use.

| Fixture | Exercises |
| --- | --- |
| `minimal` | one entity, one mapping, direct fields — the smoke floor for every tier |
| `ecom_basic` | catalog derivation (recipes), ratio metrics, date dimension |
| `fanout_trap` | order-grain measure on an item-grain mart — compile-time `GrainViolation` (RFC 0006), with the execution-level wrong-sum proof kept |
| `role_playing_dates` | **new** — `ordered_*` vs `shipped_*` roles give different, correct results (RFC 0010) |
| `semi_additive_inventory` | **new** — warehouse A balances 100/80/90 over Jan 1–3 → A-scoped 3-day answer **90**, never 270; warehouse B 40 on Jan 3 → global Jan-3 answer A 90 + B 40 = **130** (which is also the *unscoped* 3-day answer — the global MAX date is Jan 3); by-month over three months → **three rows** (seed erratum, V2 — see §5.10) |
| `non_additive_aov` | **new** — AOV recomputed from additive components: 2727.27, never 6000 or 12000 |
| `multi_mart_refusal` | **new** — cross-grain request refused with a named conflict (`UnreachableAtGrain`, RFC 0011) |
| `messy_types` | string numerics, mixed date formats, dirty enums — transform chains |
| `multi_source` | two sources → one entity via deterministic union merge |
| `evolution_v1..v5` | expand/contract sequence for `plan()` classification + `ContractViolation` |

`semi_additive_inventory` is the former `semi_additive` fixture, renamed and extended
with the numeric ledger that §5.10's assertions hard-code — continuity, not a new
fixture family.

`multi_source` is deliberately scoped to deterministic two-source union merge — identity
xref is out of scope for v0.1 (spec open question #2; the fixture must not smuggle it in).

### 5.4 Golden workflow

Tree for one cell of `ecom_basic`:

```text
tests/golden/ecom_basic/
  sqlmesh/duckdb/models/silver/order_item.sql
  sqlmesh/trino/models/silver/order_item.sql
  dbt/postgres/models/silver/order_item.sql
  cube/model/cubes/order_item.yml
  metricflow/manifest.json
  planner/duckdb/revenue_by_month.sql
```

Every fixture adds `metricflow/manifest.json` — the emitted semantic manifest (RFC 0013
R1), serialized as sorted-keys JSON so diffs stay local and reviewable. The `planner/`
cells pin the planner's rendered SQL per (fixture × dialect) for
the requests in `golden_requests.yaml` (§5.8) — `QueryPlan` rendering gets the same
review bar as emitted models.

Contract: **golden diffs are reviewed like source code** — an unexplained golden diff
fails review; it means the compiler changed behaviour whether or not a test broke. The one
sanctioned mass-regeneration is a `sqlglot` pin bump, done in a dedicated PR (RFC 0003 D2)
so the rendering delta is reviewable in isolation.

**Doctrine split (pivot R10):** the unexplained-diff-fails rule applies in full to
compiler-emitted goldens — `sqlmesh/`, `dbt/`, `cube/`, and `metricflow/manifest.json`.
For `planner/` SQL goldens, MetricFlow generates the SQL and its rendering churns across
versions, so on a MetricFlow version bump a planner-SQL golden diff is a **review aid,
not a failure**, provided the execution tests (tier 4) still pass — execution tests are
the primary correctness gate for planner SQL. Outside a version bump, an unexplained
planner-SQL diff still fails review. MetricFlow pin bumps regenerate planner goldens in a
dedicated PR, same as `sqlglot` bumps.

### 5.5 Property invariants

Every invariant must hold for *all* generated projects:

```python
@given(projects())
def test_emitted_sql_parses_under_dialect(project, target, dialect):
    ...  # every artifact's SELECT round-trips through sqlglot.parse_one(dialect=dialect)

@given(projects())
def test_select_columns_match_entity_fields(project):
    ...  # emitted SELECT columns == declared entity fields, both directions

@given(projects())
def test_self_plan_is_empty_and_compile_is_stable(project):
    ...  # plan(ir, ir) == empty; compile twice → identical bytes (fresh objects)
```

Plus: `plan(a, b)` classifying nothing as BREAKING implies b's columns ⊇ a's referenced
columns. This tier finds what goldens can't — shapes nobody thought to write down.

Two pivot-mandated invariants, both **merge-blocking**:

```python
@given(projects())
def test_metricflow_names_round_trip(project):
    ...  # every dimension the MetricFlow emitter produces round-trips through
         # planner/names.py — dunder name out, bloomery name back (pivot R4;
         # keeps R1 emission and R3/R4 planning in agreement)

@given(adversarial_filter_values())
def test_filter_fuzz(expr):
    ...  # adversarial FilterExpr values (' OR 1=1 --, {{ Dimension('x') }},
         # unicode quote variants, embedded newlines) → the rendered SQL parses
         # via sqlglot with predicate structure unchanged and the scanned
         # relations exactly the expected mart (pivot R6)
```

### 5.6 Guard tests: determinism and tenant-agnosticism

RFC 0003 §5.6's enforcement lives in `tests/unit/test_determinism_guard.py` — a named
guard test per house convention: compile the same fixture in two subprocesses with
`PYTHONHASHSEED=0` and `=1`; artifact bytes and `project_fingerprint` must be identical.
It runs in tier 1 (per-commit) despite spawning subprocesses — the cheapest proof of the
package's most load-bearing property.

The tenant-agnosticism check ([`_bloomery-changes.md`](_bloomery-changes.md) D9) is the
second named guard, alongside it: `grep -ri tenant src/bloomery/` must return only
`naming.py` docstrings. It runs as a CI quality gate and as a unit-tier guard test
(`tests/unit/test_tenant_guard.py`) so `just test` catches it locally — the package must
remain something you could open-source with no multi-tenancy showing through.

The third named guard is the **version-drift canary**
(`tests/unit/test_metricflow_api_surface.py`, pivot R10): it asserts the MetricFlow
internal surfaces the backend depends on still exist — `MetricFlowQueryRequest.create`,
`MetricFlowExplainResult.sql_statement`, `SemanticManifestLookup`, and every `SqlClient`
protocol member. MetricFlow offers no stability guarantee for embedded use; the canary
turns a silent breakage on a version bump into a loud, named failure. Runs per-commit in
tier 1 alongside the determinism and tenant guards.

### 5.7 Coverage

`fail_under = 80` overall, branch coverage on, per-package floors ratcheting upward as
packages mature (the forze `[tool.coverage_floors]` pattern — a thin new package cannot
hide behind the well-covered core). One floor is pinned from day one:
**`bloomery/guardrails/` requires 100% branch coverage** — every refusal path is the
product; an untested guardrail branch is an unshipped guardrail.

### 5.8 Equivalence tier — three-way: MetricFlow ↔ Cube ↔ reference SQL

The strongest correctness evidence available: independent implementations agreeing
([`_bloomery-changes.md`](_bloomery-changes.md) D7, amended by the pivot R10 to
three-way).

```text
tests/equivalence/
  test_three_way.py
  golden_requests.yaml          # ~40 MetricRequests across the fixture corpus
  reference_sql/                # hand-written SQL for the ~15 hardest requests
  known_divergences.yaml        # reviewed exceptions, each with a written justification
```

Every request in `golden_requests.yaml` is planned by the MetricFlow-backed planner
(RFC 0011 contract, RFC 0013 backend) and
executed on DuckDB, and issued to a Cube container built from the Cube emitter's output;
the two result frames must be equal within `atol=0.01`
(`assert_frame_equal(..., check_like=True)`). For the ~15 hardest requests —
semi-additive, ratio, cumulative, role-played grains — a hand-written reference SQL file
in `reference_sql/` is executed as the third leg: **when the two engines disagree, the
reference SQL is the tiebreaker** that says which one is wrong. Tests are
`engine("cube")`-marked and run
nightly — they need containers. Requests the planner refuses with
`UnreachableAtGrain` must be *either* refused by Cube too *or* listed in the reviewed
`known_divergences.yaml` with a written justification — a silent divergence is a bug in
one of the implementations.

### 5.9 Benchmark lane — `tests/bench/`

`tests/bench/test_hydration.py` asserts RFC 0014's hydration ceilings — **50 ms cold**
(manifest `parse_raw` + `SemanticManifestLookup`) and **10 ms warm** (L1 cache hit) —
so a regression fails the lane instead of surfacing as production latency. These
supersede RFC 0012's 5 ms `CompiledSemantic` target, which is neither achievable nor
needed under the MetricFlow backend. Marked `perf`, excluded from `just test`, run as a
scheduled CI job. The only benchmark in v0.1 (§4).

### 5.10 Planner test obligations (RFCs 0011/0013)

Three obligations from the planner RFC land in the tiers here and are mandatory, not
aspirational:

- **`test_row_policy_survives_every_path`** — the named mandatory pre-merge test: for an
  exhaustive request matrix (limits, ordering, filters, all grains), the parsed AST of
  every plan's SQL contains the `RowPolicy` predicate in every scan. Asserted on the
  **parsed AST**, never a substring — a string check passes on a commented-out
  predicate. Assert "predicate in **every scan**", never a fixed subquery count: the
  optimizer may collapse a ratio's component subqueries into one shared scan (verified
  in V4 — the predicate reaches every scan pre-aggregation; RFC 0013 §5.9).
- **Planner determinism** — property-tier invariant: planning the same `MetricRequest`
  twice against the same IR yields an identical `QueryPlan` (SQL bytes, columns,
  fingerprint) — the planner-side companion of §5.6.
- **Additivity numerics** — D4's three hard-coded assertions live in the execution
  suite, against `semi_additive_inventory` and `non_additive_aov`: inventory over
  1–3 Jan **scoped to warehouse A** is 90 (never 270); warehouses A 90 + B 40 on Jan 3
  sum to 130 — which is also the **unscoped** 1–3 Jan answer, since the global MAX date
  in the window is Jan 3 (V2 seed erratum: with B=40 present on Jan 3, "unscoped 3-day
  → 90" and "Jan 3 → 130" are unsatisfiable on one seed; the paired assertions above
  are the satisfiable form, both verified against executed DuckDB); by-month over
  three months returns three rows. DuckDB returns month-grain rows as `TIMESTAMP`s
  (`DATE_TRUNC('month', DATE)` → `TIMESTAMP`) — the test helper normalizes before
  comparing. AOV is 2727.27 (never 6000 or 12000). Hard-coded on purpose — they are
  the exact failure modes that make a BI product untrustworthy. Under the MetricFlow backend these
  assertions test *our mapping into MetricFlow* (RFC 0013 R1) rather than our own SQL
  generation — a wrong `window_choice` or a measure emitted where a ratio metric belongs
  fails here. There is no lowering, SQLGlot-build, or mart-selection module of ours to
  unit-test; the coverage precheck's 0/1/N selection and refusals are unit-tested, and
  lowering semantics are proven at the execution tier.

## 6. Tests

This RFC *is* the test plan; its own verification is structural: `tests/README.md` matches
the tier table here, `just test` selects exactly tiers 1–4, strict markers make the
taxonomy self-enforcing, and CI runs engine/e2e lanes on the stated cadence.

## 7. Docs

`tests/README.md` — tier table, marker list, and a run recipe per tier (`just test`,
`just test -m 'engine("postgres")'`, `pytest --snapshot-update`, nightly lanes), mirroring
the forze README shape. Docs pages use the fixture corpus as their examples; fixture edits
move goldens and eval baselines, so they get the same review bar.

## 8. Out of scope

- **Identity xref in `multi_source`** — deferred with the feature (spec open question #2);
  the fixture grows an xref variant when it lands.
- **LLM-proposal evaluation harness** — the corpus is *designed* to serve it, but the
  harness lives upstream in the control plane, not in this suite.
- **Mutation testing** — the 100% guardrail branch floor plus execution tests cover the
  same risk at far lower CI cost; revisit if a guardrail bug ever escapes both.

## 9. Risks

- *Golden churn fatigue* — reviewers rubber-stamp frequent diffs. Mitigation: small corpus
  (fourteen fixtures); goldens stable-sorted (RFC 0003 §5.5 rule 5) so diffs stay local.
- *Hypothesis flakiness in CI* — derandomized CI profile with printed seed; a nightly
  randomized profile explores; every found failure is pinned as a unit-tier regression.
- *Nightly-only container lanes rot* — postgres stays per-commit as the canary that
  container plumbing works; nightly failures are treated as per-commit failures.
- *DuckDB-first execution under-tests dialect differences* — accepted: tier 5 exists for
  this, and per-commit trino/postgres goldens keep rendering honest.

## 10. Unresolved questions

- None blocking. Implementation is free to settle `--snapshot-update` mechanics
  (pytest-snapshot vs a ~30-line conftest) and exact CI lane wiring, as long as the marker
  taxonomy and default selection match §5.1.

## 11. Decisions

| # | Decision |
| --- | --- |
| 1 | Six tiers, fastest first (unit, golden, property, execution, engines, e2e); unit is 90%+ of test count and covers 100% of guardrail branches. `just test` = tiers 1–4; engines/e2e are opt-in markers (postgres per-commit; trino/spark/e2e nightly). |
| 2 | Layout is `tests/{unit,golden,property,execution,engines,e2e,fixtures,support}/` with `tests/unit` mirroring `src/bloomery`; `tests/README.md` documents the tiers (forze convention). |
| 3 | Markers `unit, property, execution, engine(<name>), e2e, perf` under `--strict-markers`/`--strict-config` in `pyproject.toml`; an undeclared marker is a collection error. |
| 4 | The fixture corpus is exactly spec §7.7 (`minimal`, `ecom_basic`, `fanout_trap`, `semi_additive`, `messy_types`, `multi_source`, `evolution_v1..v5`), stored as YAML under `tests/fixtures/<name>/`, loaded only via public `load_project`/`load_catalog`. Consequence: the corpus is also the doc example set and future LLM-eval set — fixture edits carry corpus-level review weight. `multi_source` covers deterministic two-source union merge only; identity xref is out of scope for v0.1. |
| 5 | Goldens are checked in per (fixture × target × dialect), regenerated via `pytest --snapshot-update`, and reviewed like source code — an unexplained golden diff fails review. sqlglot pin bumps regenerate goldens in a dedicated PR (RFC 0003 D2). |
| 6 | Property tier generates only valid projects (strategies in `tests/support/strategies.py`); invariants: SQL parses under target dialect, SELECT columns ⇔ entity fields, `plan(ir, ir)` empty, no-BREAKING plan ⇒ column superset, compile twice ⇒ identical bytes. |
| 7 | Execution tier is in-process DuckDB with `Decimal` assertions and houses the fan-out regression suite (spec §7.4) as executable proof of the grain guardrail. |
| 8 | The RFC 0003 §5.6 determinism test is the named guard `tests/unit/test_determinism_guard.py`, run per-commit in tier 1. |
| 9 | Coverage: branch on, `fail_under=80` overall, per-package floors ratcheting up (forze pattern); `bloomery/guardrails/` is floored at 100% branch from day one. |
| 10 | The strongest acceptance test is SQLMesh replan-is-a-no-op (`plan.has_changes == False`); dbt (`dbt parse`) and cube (`/meta`) get equivalents. |
| 11 | Tier 7, planner equivalence (_bloomery-changes.md D7): `tests/equivalence/` holds `test_native_vs_cube.py` and `golden_requests.yaml` (~40 `MetricRequest`s across the fixtures); `engine("cube")`-marked, nightly; native and Cube result frames must be equal within `atol=0.01`. Requests the native planner refuses with `UnreachableAtGrain` must be refused by Cube too or listed in a reviewed `known_divergences.yaml` with a written justification. |
| 12 | The corpus grows to fourteen fixtures (D7): `role_playing_dates`, `semi_additive_inventory` (the former `semi_additive`, renamed and extended), `non_additive_aov`, and `multi_mart_refusal` join the spec §7.7 set; `fanout_trap` now proves the compile-time `GrainViolation` (RFC 0006) and keeps its execution-level wrong-sum proof. |
| 13 | `tests/bench/` ships the hydration benchmark (RFC 0012): `loads` under 5 ms asserted, `perf`-marked, run as a scheduled job — the only benchmark in v0.1. |
| 14 | Tenant-agnosticism is a named guard alongside the determinism guard (D9): `grep -ri tenant src/bloomery/` returns only `naming.py` docstrings, enforced as a CI quality gate and a unit-tier guard test. |
| 15 | **Three-way equivalence (pivot R10, amends D11):** tier 7 is MetricFlow ↔ Cube ↔ hand-written reference SQL. Reference SQL in `tests/equivalence/reference_sql/` for the ~15 hardest golden requests is the tiebreaker when the two engines disagree; the `known_divergences.yaml` rule is unchanged. |
| 16 | **Golden-doctrine split (pivot R10, amends D5):** compiler-emitted goldens (`sqlmesh/`, `dbt/`, `cube/`, `metricflow/manifest.json`) keep the strict unexplained-diff-fails rule. Planner-SQL golden diffs on a MetricFlow version bump are review aids, not failures, provided execution tests pass — execution tests are the primary correctness gate for planner SQL. Every fixture gains a sorted-keys `metricflow/manifest.json` golden (RFC 0013 R1). |
| 17 | Two new **merge-blocking** property invariants (pivot R4/R6): every dimension the MetricFlow emitter produces round-trips through `planner/names.py`; adversarial `FilterExpr` values render to SQL that parses with unchanged predicate structure and exactly the expected scanned relations. |
| 18 | **Version-drift canary (pivot R10):** `tests/unit/test_metricflow_api_surface.py` is a third named guard beside the determinism and tenant guards — it pins the MetricFlow internal API surface the backend depends on, turning a silent breakage on a version bump into a loud failure. Per-commit, tier 1. |
| 19 | **Bench budgets revised (RFC 0014, supersedes D13's 5 ms):** `tests/bench/test_hydration.py` asserts 50 ms cold / 10 ms warm hydration; still `perf`-marked, scheduled, and the only benchmark in v0.1. |
| 20 | **Semi-additive fixture seed erratum (V2, 2026-08-07 — [`spikes/metricflow/VERIFICATION.md`](../spikes/metricflow/VERIFICATION.md)):** the pivot's paired assertions ("unscoped Jan 1–3 → 90" and "Jan 3 → A 90 + B 40 = 130") are unsatisfiable on one seed — with B=40 on Jan 3 the global MAX date is Jan 3, so the unscoped 3-day answer is 130. `semi_additive_inventory` keeps 100/80/90 as **warehouse-A** balances (A-scoped 3-day → 90), B=40 on Jan 3 (global Jan-3 and unscoped 3-day → 130), and asserts by-month over three months → three rows (issue #241 fixed in metricflow 0.211.0). Month-grain DuckDB results are `TIMESTAMP`s — normalized in the test helper. §5.3/§5.10 amended accordingly; the row-policy AST test asserts "predicate in every scan", not a fixed subquery count. |
| 21 | *(2026-08-10)* **The Trino engine tier is built, on the memory connector, and `spark` is struck from §5.2.** Trino was the engine bloomery made the most claims about and executed the least: three decisions — D83's reject-table constructions, D86's `normalize`/`charset`, D89's mart-assertion body shapes — were each verified against `trinodb/trino:483` **by hand**, through `docker exec`, because the repository carried no Trino client. A hand-verification is a claim with a date on it, not a test, and all three are now a permanent tier (`trino` + `testcontainers[trino]` in the `engines` group). The strongest assertion is the one D75 said was impossible: the `<entity>__reject` model *materializes*, and its `reject_id` is compared against the canon-bytes digest computed here in Python rather than against Trino agreeing with itself — cross-engine *agreement* being the property that identity actually needs, since a replay run on one engine must find the row another quarantined. Sabotage-verified: dropping the `LOWER` from Trino's `TO_HEX` makes the digest disagree in case alone, which the tier catches and which no rendering test could. **The connector is `memory`, diverging from §5.2's `trino+iceberg+minio (compose)` sketch**: bloomery emits SELECTs and models and never storage-format DDL, so an object store and a table format would be three more moving parts serving no assertion in this tier — recorded rather than silently simplified. **`spark` is struck from the same row.** RFC 0008 ships DuckDB, Postgres and Trino; there is no Spark dialect, so a Spark cell had nothing to exercise and the word promised a matrix column that could never have contained a test. It returns if and when a Spark dialect does. |
| 22 | *(2026-08-10)* **`dbt parse` is built, and building it found that `dbt build` cannot pass.** §5.2 names dbt's tier-6 cell in three words, and the tier now runs `dbt parse` over every fixture the dbt target compiles plus a Tier 2 step project — closing the claim RFC 0017 D52 explicitly left open, that the emitted step model is a file dbt accepts. It carries its own control: one model's `config()` is deliberately malformed and dbt must refuse it, so the nine passes above it are not a parser that accepts anything. **The finding.** `dbt build` on the same project fails, and not because of the tier: bloomery's dbt models reference their inputs by **literal relation name** (`FROM silver.order_item`) rather than through `{{ ref(...) }}` or `{{ source(...) }}`. So dbt has no dependency edges between bloomery's models — it cannot order them — and it materializes each into the profile's target schema while the `FROM` clause names `silver`. Both halves have to be true for a build to work, and neither is. Two candidate fixes, **neither built**, because this is RFC 0008's decision about how deep the dbt target goes rather than a testing-tier patch: rewrite silver/gold references to `ref()` and bronze to `source()` (a real DAG, but `ref()` resolves through dbt's own schema config, so the naming policy stops owning the namespace); or emit per-directory `+schema` config in `dbt_project.yml` (relations line up, ordering still absent). Recorded here because the limitation was **unwritten anywhere** until this tier was built — RFC 0008 calls dbt "the compatibility target, minimal but honest", and this is the part that was not written down. |
| 25 | *(2026-08-11)* **D22 is closed, and the tier that found it now builds.** RFC 0008 D20 took **both** of D22's candidates — the "or" between them was wrong, since `+schema` alone leaves ordering absent and `ref()` alone costs the naming policy its namespaces, and each repairs the other's cost. §5.2's dbt cell is now `parse` + `compile` + `build`: parse for "dbt loads this at all" (with the malformed-`config()` control), compile because parse does **not** resolve test macros (RFC 0008 D19), and build for D22 itself. Sources are seeded **empty**, read off the emitted models rather than hand-listed, each column taking the type of the nearest enclosing `CAST` — the model's own statement of what it expects to read, and necessary because an all-`VARCHAR` seed makes DuckDB refuse `CAST(total / qty AS DECIMAL)` before the build has said anything about references. Zero rows is deliberate and the limit is stated: resolution, ordering and placement fail identically on an empty warehouse, and arithmetic belongs to the execution and equivalence tiers rather than being restated here. |
| 23 | *(2026-08-10)* **An empty engine/e2e lane is a nightly failure, not a tolerance.** The CI step swallowed pytest's exit code 5 with the comment "tiers land with M7". They landed: 39 tests collect under `engine or e2e` across postgres, trino, the SQLMesh replan and `dbt parse`. With the suites written, an empty collection can only mean an import or collection error — and tolerating it means exactly the failure mode that matters most in a nightly lane nobody watches: a broken import turning the whole thing green. The tolerance is removed. |
| 24 | *(2026-08-10)* **The Cube container and the three-way equivalence tier are built; `QueryPlan.columns` does not name the columns the SQL returns.** §5.2's last tier-6 cell and §5.8's tier-7 both need Cube alive, so one harness pairs it with the Postgres holding the mart it describes — on one network, with the table created from `MartIR` through the Postgres dialect port rather than a hand-written column list, since a third statement of the schema would be free to drift from the two that matter. **Cube loads what bloomery emits**, and the load-bearing assertion is the `meta:` block: RFC 0008 §5.1 says the emitted `additivity`/`grain`/`semi_additive` is what a consumer audits Cube's behaviour against, which is only true if it survives to the API — no golden can show that, and dropping it from the emitter fails the test that names it. The tier does not stop at `/meta`: it issues a query, because parsing a model and running its measure expression are different claims. **Equivalence** points both engines at one relation by construction — Cube's `sql_table` and the planner's SQL name the same `gold.mart_<name>` under the naming policy — so a difference can only come from the query rather than from two seeding routines kept in step. The corpus is smaller than §5.8's "~40 requests", visibly and deliberately: the *classes* buy the coverage (an additive measure at three grains, an ungrouped request, a ratio recomputed per group, a multi-metric request), each costs a Cube round trip in a nightly lane, and growing it is adding YAML entries. The reference SQL runs on **every** request that declares one rather than only after a disagreement — §5.8 calls it the tiebreaker, and a tiebreaker nobody has ever checked cannot break a tie. `known_divergences.yaml` ships **empty**, with its required shape asserted, because §5.8 holds that a silent divergence is a bug in one of the implementations and a pre-populated file would let the first real one hide among plausible neighbours. The ratio fixture seeds groups of **unequal size** on purpose: a ratio averaged from stored per-row values agrees with a ratio of summed components on equal-sized groups and only on those, so equal groups would let the wrong arithmetic pass. Sabotage-verified — a wrong Cube measure expression fails ten of the fifteen. **The finding.** `QueryPlan.columns` is RFC 0011's "self-describing envelope", but its dimension descriptors carry the *requested* name (`ordered_month`) while the SQL MetricFlow generates aliases them its own way (`order_item__ordered_day__month`). Positional binding works and is what every consumer in this repo does; binding by name silently finds nothing. Two ways to close it, **neither built** — wrap the generated SQL in an outer SELECT aliasing to the requested names (RFC 0013's call, since MetricFlow owns the aliasing), or state in RFC 0011 that the envelope is positional and `name` is the request's word rather than the frame's. Recorded because it was written down nowhere. **One harness trap, recorded because it cost a wrong diagnosis:** Postgres logs "database system is ready to accept connections" *twice* — once on the unix socket while `initdb` runs its scripts, then again for real — so a container waiting on the first occurrence connects during the init shutdown and fails with "server closed the connection unexpectedly". It is a race, so it failed intermittently and read as container-memory pressure; the fix is the `PostgresContainer` class the other engine tiers already use, not fewer containers. |
| 26 | *(2026-08-12)* **The engine/e2e lane runs on pull requests that touch what it covers, and the cost premise it was skipped on was wrong.** D21–D25 built tiers 5–7 and left them `force_full` only — nightly, `workflow_dispatch`, release — on the reading that Docker-backed means expensive per-commit. **Measured rather than assumed:** 199s on run 31534974983, against a Python test matrix taking 203–325s in the same run. The lane finishes *inside* the existing critical path and adds no wall-clock to a PR at all. What the skip actually cost was visible on the PR that measured it: it changed the Postgres `TRY_CAST` guard (D93) and rewrote how every dbt model names its inputs (RFC 0008 D20), and CI would have exercised neither until the following night — the tiers built precisely to catch that class of change were the ones not running on it. Now triggered by a path filter over the dialect ports, the emitters and the two tiers' own suites, since nothing outside those can move its verdict. **Two exclusions, both deliberate and both the same asymmetry.** Fork pull requests keep the nightly path: secrets are unavailable to them, so their pulls go out anonymous against the runner IP's shared Docker Hub budget and the lane would fail for reasons no test changed. And it stays **out of `required-ci`** — advisory on a PR, blocking nightly — because a rate limit or a container that will not start must not block a merge. That is a weaker gate than D23 made the nightly lane, and the difference is the point: D23 could remove a tolerance because a scheduled run has no one waiting on it. |

## 12. Phasing

Tiers land with the pivot's milestone table
([`_bloomery-metricflow-pivot.md`](_bloomery-metricflow-pivot.md) §8, superseding
`_bloomery-changes.md` D10): M1 ships the layout, markers, `minimal` fixture, and the
determinism and tenant guards; M2 the first goldens and execution tests; M3–M4 grow the
corpus (`ecom_basic`, `fanout_trap`, `semi_additive_inventory`, `messy_types`) with
their guardrails; M4.5 answers verification tasks V1–V4 in writing before any pivot code
merges; M5 adds `role_playing_dates` with marts and role-playing; M6 the MetricFlow
emitter goldens — every fixture emits a `metricflow/manifest.json` that
`SemanticManifestLookup` accepts — plus the API-surface canary (§5.6); M7 the remaining
planner fixtures (`non_additive_aov`, `multi_mart_refusal`) with their execution tests
and the planner obligations (§5.10) — coverage precheck, names round-trip, filter fuzz,
and policy fixtures all green; M8 the hydration benchmark (§5.9, 50 ms cold / 10 ms
warm); M9 `evolution_v1..v5` for `plan()` and plan-diff classification; M10 fills the
golden matrix (Trino dialect, Cube emitter) and `multi_source`, turning on the engine
lanes; M11 turns on the e2e lanes and the three-way equivalence tier (§5.8).
