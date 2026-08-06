# RFC 0009 — Testing strategy and fixture corpus

- **Status:** 📝 Draft
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
  RFC 0012 (hydration benchmark §5.9).
- **Origin:** Tier structure from the original spec §7; house conventions from the sibling
  project `forze` (`tests/README.md`, strict markers, unit-mirrors-src, coverage floors).

---

## 1. Summary

Seven tiers, fastest first: unit, golden snapshots, Hypothesis properties, in-process
DuckDB execution, testcontainers engine matrix, target-framework e2e, and planner
equivalence (native vs Cube, §5.8) — all exercising one shared corpus of fourteen YAML
fixture projects loaded through the public `load_project`/`load_catalog` API; outside
the tiers, `tests/bench/` runs the scheduled hydration benchmark (§5.9, RFC 0012).
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
  benchmark, the `CompiledSemantic` hydration ceiling (§5.9, RFC 0012); broader perf
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
  equivalence/  # tier 7 — native planner vs Cube on golden requests (§5.8)
  bench/        # perf lane — hydration benchmark (§5.9, RFC 0012), scheduled
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
| 2 golden | per-commit | Every (fixture × target × dialect) cell byte-compared against checked-in files; `pytest --snapshot-update` regenerates (§5.4). |
| 3 property | per-commit | Hypothesis over random *valid* projects (invalid inputs are unit-tier explicit cases); invariants §5.5. |
| 4 execution | per-commit | In-process DuckDB: seed bronze rows, execute every compiled SELECT, assert numeric results with `Decimal` (never float — RFC 0003 D5). Houses the fan-out regression suite (spec §7.4): shipping-cost-duplicated-across-line-items, asserted numerically against `fanout_trap` — plus the hard-coded additivity assertions (§5.10). |
| 5 engines | postgres per-commit; trino+iceberg+minio (compose), spark nightly | Tier-4 assertions against real engines via testcontainers; `@pytest.mark.engine("trino")` etc.; deselected by default. |
| 6 e2e | nightly | Artifacts are valid *input to the target*, not just valid SQL: `sqlmesh.Context` parses them, applies a plan, and a replan asserts `plan.has_changes == False` — the strongest single test in the suite (compiler and SQLMesh agree on what the models mean). Equivalents: `dbt parse`; a cube container's `/meta` returns the expected measures/dimensions. |
| 7 equivalence | nightly | Native planner vs Cube (§5.8): every request in `golden_requests.yaml` executed both ways; result frames equal within `atol=0.01`. Refusals must match or carry a reviewed justification in `known_divergences.yaml`. |

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
| `semi_additive_inventory` | **new** — 100/80/90 over three days → 90, never 270; warehouses A 90 + B 40 on one day → 130 |
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
  planner/duckdb/revenue_by_month.sql
```

The `planner/` cells pin the native planner's rendered SQL per (fixture × dialect) for
the requests in `golden_requests.yaml` (§5.8) — `QueryPlan` rendering gets the same
review bar as emitted models.

Contract: **golden diffs are reviewed like source code** — an unexplained golden diff
fails review; it means the compiler changed behaviour whether or not a test broke. The one
sanctioned mass-regeneration is a `sqlglot` pin bump, done in a dedicated PR (RFC 0003 D2)
so the rendering delta is reviewable in isolation.

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

### 5.7 Coverage

`fail_under = 80` overall, branch coverage on, per-package floors ratcheting upward as
packages mature (the forze `[tool.coverage_floors]` pattern — a thin new package cannot
hide behind the well-covered core). One floor is pinned from day one:
**`bloomery/guardrails/` requires 100% branch coverage** — every refusal path is the
product; an untested guardrail branch is an unshipped guardrail.

### 5.8 Equivalence tier — native planner vs Cube

The strongest correctness evidence available: two independent implementations agreeing
([`_bloomery-changes.md`](_bloomery-changes.md) D7).

```text
tests/equivalence/
  test_native_vs_cube.py
  golden_requests.yaml          # ~40 MetricRequests across the fixture corpus
  known_divergences.yaml        # reviewed exceptions, each with a written justification
```

Every request in `golden_requests.yaml` is planned by the native planner (RFC 0011) and
executed on DuckDB, and issued to a Cube container built from the Cube emitter's output;
the two result frames must be equal within `atol=0.01`
(`assert_frame_equal(..., check_like=True)`). Tests are `engine("cube")`-marked and run
nightly — they need containers. Requests the native planner refuses with
`UnreachableAtGrain` must be *either* refused by Cube too *or* listed in the reviewed
`known_divergences.yaml` with a written justification — a silent divergence is a bug in
one of the two implementations.

### 5.9 Benchmark lane — `tests/bench/`

`tests/bench/test_hydration.py` asserts RFC 0012's hydration ceiling: `loads` of a
realistic `CompiledSemantic` under 5 ms, so a regression fails the lane instead of
surfacing as production latency. Marked `perf`, excluded from `just test`, run as a
scheduled CI job. The only benchmark in v0.1 (§4).

### 5.10 Planner test obligations (RFC 0011)

Three obligations from the planner RFC land in the tiers here and are mandatory, not
aspirational:

- **`test_row_policy_survives_every_path`** — the named mandatory pre-merge test: for an
  exhaustive request matrix (limits, ordering, filters, all grains), the parsed AST of
  every plan's SQL contains the `RowPolicy` predicate in every scan. Asserted on the
  **parsed AST**, never a substring — a string check passes on a commented-out
  predicate.
- **Planner determinism** — property-tier invariant: planning the same `MetricRequest`
  twice against the same IR yields an identical `QueryPlan` (SQL bytes, columns,
  fingerprint) — the planner-side companion of §5.6.
- **Additivity numerics** — D4's three hard-coded assertions live in the execution
  suite, against `semi_additive_inventory` and `non_additive_aov`: inventory over
  1–3 Jan is 90 (never 270); warehouses A 90 + B 40 on one day sum to 130; AOV is
  2727.27 (never 6000 or 12000). Hard-coded on purpose — they are the exact failure
  modes that make a BI product untrustworthy.

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

## 12. Phasing

Tiers land with their milestones (_bloomery-changes.md D10): M1 ships the layout,
markers, `minimal` fixture, and the determinism and tenant guards; M2 the first goldens
and execution tests; M3–M4 grow the corpus (`ecom_basic`, `fanout_trap`,
`semi_additive_inventory`, `messy_types`) with their guardrails; M5 adds the planner
fixtures (`role_playing_dates`, `non_additive_aov`, `multi_mart_refusal`) with their
execution tests and the planner obligations (§5.10); M6 the hydration benchmark (§5.9);
M7 `evolution_v1..v5` for `plan()`; M8 fills the golden matrix (second target, second
dialect) and `multi_source`, turning on the engine lanes; M9 turns on the e2e lanes and
the equivalence tier (§5.8).
