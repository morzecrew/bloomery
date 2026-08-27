# M4.5 — MetricFlow verification spike (V1–V4), answered in writing

Gate for RFC 0013 (pivot doc §7). Run on 2026-08-07.

**The scripts have been retired.** They were exploratory code no gate ran and
nothing imported, and the one piece of logic that outlived them — the row-policy
AST audit — was copied into `tests/support/planning.py`, where a tier runs it.
This document is the record; `git log --diff-filter=D -- spikes/` finds the
commit that retired them and `git show <commit>^:spikes/metricflow/spike.py`
prints one back. Same doctrine as a landed RFC.

They ran against an environment kept outside the repo, so the repo
`.venv`/`uv.lock` stayed untouched:

```sh
uv init --bare --python 3.14 mf-spike && cd mf-spike
# requires-python widened to ">=3.12,<3.15" to mirror the repo
uv add --editable /path/to/bloomery
uv add "metricflow==0.211.*" duckdb "sqlmesh>=0.150" "pydantic>=2.9"
uv run --project <mf-spike-dir> python spikes/metricflow/spike.py     # etc.
```

---

## V1 — Dependency coexistence

**Joint resolution: SUCCEEDS.** `bloomery` (editable) + `metricflow==0.211.*` + `duckdb`
+ `sqlmesh>=0.150` + `pydantic>=2.9` resolve and install together with uv on
**Python 3.12.13, 3.13.5, and 3.14.6** (all three synced and smoke-tested; 3.14 is the
newest in our range and works).

Resolved set (identical across the three Pythons):

| package | resolved | constraint that bound it |
|---|---|---|
| metricflow | **0.211.0** | our pin (`0.211.*` exists on PyPI; latest release) |
| pydantic | **2.13.4** | metricflow allows `>=1.10,<3.0`; ours `>=2.9` |
| sqlglot | **30.8.0** | sqlmesh 0.236.1 requires `sqlglot~=30.8.0`; metricflow only `>=20.0.0` (no upper) |
| sqlmesh | 0.236.1 | dev-group `>=0.150` |
| duckdb | 1.5.5 | — |
| jinja2 | 3.1.6 | metricflow `>=3.1.6,<3.7`; ours `>=3.1` |

- **Python range:** metricflow 0.211.0 declares `requires-python >=3.10,<3.15` — the upper
  bound is **identical** to bloomery's `>=3.12,<3.15`. **No `requires-python` narrowing is
  needed; RFC 0001's range stands.**
- **sqlglot:** metricflow's `sqlglot>=20.0.0` (no cap) intersects trivially with our
  `>=30.8.0,<31` and sqlmesh's `~=30.8.0`. No clash.
- **pydantic:** metricflow's `<3.0,>=1.10` admits our v2 line; its vendored
  `metricflow_semantic_interfaces` routes every model through `msi_pydantic_shim`, which
  under an installed pydantic 2.x imports from **`pydantic.v1`**. Manifest objects are
  `pydantic.v1.BaseModel` instances, bloomery specs are `pydantic.BaseModel` (v2) — two
  distinct class hierarchies/metaclasses, no conflict. Verified empirically in **both
  import orders** (bloomery-first then MetricFlow, and vice versa): v2 `model_dump`/
  `model_validate` and v1-style `.json()`/`.parse_raw()` both work, manifests round-trip,
  `explain()` renders (scratchpad scripts `v1_order_a.py` / `v1_order_b.py`).
- **One real import-order effect found (internal to MetricFlow, not pydantic-related):**
  importing `metricflow_semantic_interfaces.implementations.node_relation` as the *first*
  MSI import raises `ImportError: cannot import name 'NodeRelation' from partially
  initialized module` (circular import via `protocols`). Workaround: import any module
  that finishes `metricflow_semantic_interfaces.protocols` first (e.g.
  `…implementations.semantic_manifest`, as the reference implementation does). R1's
  emitter module should order its imports accordingly — worth a comment there.
- **Namespace note:** the metricflow wheel installs a **top-level** module
  `msi_pydantic_shim.py` at site-packages root. Harmless, but it is global-namespace
  pollution to be aware of (e.g. deptry/vulture scans, name collisions).
- Every one of the 26 import paths / class names in the pivot doc §2 exists exactly as
  written in 0.211.0. `MetricFlowQueryRequest.create` exists;
  `explain(...) -> MetricFlowExplainResult`; SQL at `result.sql_statement.sql`. One
  pivot-doc claim is off in a favourable direction: **skipping `transform()` does not
  "resolve incorrectly" silently — it fails loudly** with
  `MetricFlowInternalError: A simple metric is missing 'metric_aggregation_params'` at
  `explain()` time (0.211.0 behaviour).

**ANSWER: PASS.** metricflow==0.211.0 co-installs with the full real constraint set
(sqlglot 30.8.0 under sqlmesh's `~=30.8.0`, pydantic 2.13.4) on Python 3.12/3.13/3.14; no
metaclass or import-order conflicts between our v2 models and the v1 shim (one internal MSI
circular-import gotcha, workaround known). Recommended pyproject change: add
`metricflow==0.211.*` to **`[project].dependencies` (runtime)** — no separate extra/group
needed since joint resolution with the dev group succeeds; keep `sqlglot>=30.8.0,<31` and
`pydantic>=2.9` as-is; `requires-python` unchanged.

---

## Reference implementation (`spike.py`)

Reproduces pivot §2 against the installed 0.211.0. Confirmed: manifest constructible in
code; `PydanticSemanticManifestTransformer.transform()` mandatory (loud
`MetricFlowInternalError` without it); `RenderOnlySqlClient` (Protocol stub, no connection)
renders SQL; output matches the pivot's shape exactly — same subquery structure, WHERE
placement, GROUP BY/ORDER BY/LIMIT — with one cosmetic addition: a trailing
`-- Write to DataTable` plan comment. **No API discrepancies against the pivot doc.**

---

## V2 — Semi-additive grouping (issue #241 gate)

Manifest: measure `balance` (SUM) with
`non_additive_dimension(name="snapshot_date", window_choice=MAX)`, categorical
`warehouse`, time spine. Executed against in-process DuckDB (`v2_semi_additive.py`), seed:
A: Jan 1=100, Jan 2=80, Jan 3=90; B: Jan 3=40; A: Feb 10=85, Feb 20=75, Mar 5=65,
Mar 15=95.

| case | result | got |
|---|---|---|
| (a) balance, Jan 1–3 filter, no time group-by, scoped to warehouse A | **PASS** | 90 (not the naive 270) |
| (a-global) same filter, unscoped | **PASS** | 130 (A=90+B=40 on the MAX date; not the naive 310) |
| (b) balance by warehouse, Jan 3 | **PASS** | A=90, B=40 |
| (b-total) balance, Jan 3, no group-by | **PASS** | 130 |
| (c) balance by month, Jan–Mar (`inventory__snapshot_date__month`) | **PASS** | **THREE rows**: Jan=130, Feb=75, Mar=95 |
| (c') same via `metric_time__month` | **PASS** | three rows, same values |

**Issue #241 is fixed in 0.211.0.** The generated plan's `MAX()` join subquery is grouped
by the queried grain (`GROUP BY DATE_TRUNC('month', snapshot_date)` inside the
`MAX(snapshot_date__day)` branch — plan comment: `-- Join on MAX(snapshot_date) … grouping
by snapshot_date`), so grouping *by* the non-additive dimension returns the full series,
one last-value row per period. No workaround or partial-capability fallback needed.

Two fixture errata, binding for RFC 0009/0013 fixtures:

1. **The pivot's paired assertions are unsatisfiable on one seed.** With B=40 seeded on
   Jan 3, the unscoped "Jan 1–3 filter → 90" and "Jan 3 → 130" cannot both hold: global
   `MAX(snapshot_date)` over Jan 1–3 lands on Jan 3, where A+B = **130**. The "90"
   expectation is correct only scoped to warehouse A (or with B absent from the seed). The
   D7 fixture must pick one: either seed B on a date outside the 3-day window, or assert
   130 for the unscoped query and 90 for the A-scoped one (this spike asserts both
   variants explicitly).
2. DuckDB's `DATE_TRUNC('month', DATE)` returns `TIMESTAMP` — execution-test expectations
   for month-grain rows must compare against datetimes, not dates.

**ANSWER: PASS.** All three cases green against executed DuckDB results; the #241 defect
is absent in 0.211.0; RFC 0013 §9's "high if unfixed" risk is retired. Fixture seeds need
the erratum above applied.

---

## V3 — Hydration at scale

Synthetic manifest: 30 semantic models / 90 metrics / 90 measures / 180 dimensions,
`.json()` payload **144.9 KB** (pivot claimed 145 KB — matches). Median of 25 runs,
`time.perf_counter`, Python 3.14.6 (`v3_hydration.py`):

| operation | measured | pivot claim | RFC 0014 budget |
|---|---|---|---|
| `transform()` | **14.5 ms** | 23 ms | build-time only |
| `parse_raw()` | **5.7 ms** | 15 ms | — |
| `SemanticManifestLookup()` | **4.5 ms** | 13 ms | — |
| **cold hydration (parse_raw + lookup)** | **10.5 ms** | ~29 ms | **50 ms — PASS (×4.7 headroom)** |
| `engine.explain()` (simple query, warm) | **2.5 ms** | ~12 ms | — |
| first `explain()` on a fresh lookup | 8.5 ms | — | lookup is partially lazy: ~6 ms of graph work deferred to the first query; cold-path worst case ≈ 19 ms, still well under 50 ms |
| tracemalloc, 5 hydrated lookups | **1.54 MB / lookup** | ~1.6 MB | confirms L1 sizing (500-entry LRU ≈ 770 MB) |

Warm path (L1 hit) is a dict lookup — the 10 ms warm budget is trivially met; the per-query
cost that follows a warm hit is the 2.5 ms `explain()`.

**ANSWER: PASS.** All measurements at or better than the pivot's numbers on this machine;
RFC 0014's 50 ms cold / 10 ms warm budgets are achievable with ≥4× headroom (even counting
the lazy first-explain tail). Caveat: this is a 30-model synthetic; a tenant several times
larger extrapolates to roughly linear growth (~35 ms cold at 100 models) — still inside
budget, but RFC 0014's bench test should include a 3× size point.

---

## V4 — Row policy in generated SQL

`where_constraints=["{{ Dimension('<entity>__tenant_key') }} = 'acme'"]` applied to (a) the
RATIO metric `avg_order_value` and (b) the semi-additive `inventory_balance` (grouped by
month, and ungrouped). SQL parsed with sqlglot; per physical scan of the mart relation the
audit requires the tenant predicate at or below the first aggregation over that scan
(`v4_row_policy.py`).

| query | scans of mart | predicate per scan | verdict |
|---|---|---|---|
| (a) ratio by carrier | 1 | 1/1 protected — single shared scan feeds both `SUM(revenue)` and `SUM(order_count)`; `WHERE order_item__tenant_key = 'acme'` sits between the scan projection and the aggregation | **PASS** |
| (b) semi-additive by month | 2 | 2/2 — the fact branch **and** the `MAX(snapshot_date__day)` join branch each carry `WHERE inventory__tenant_key = 'acme'` before their aggregation | **PASS** |
| (b') semi-additive ungrouped | 2 | 2/2 — same placement | **PASS** |

MetricFlow pushes where-constraints into the source-read subquery of **every** branch that
scans the mart — the semi-additive MAX is computed over already-tenant-filtered rows, so
the pivot's feared security defect (outer-level-only filtering leaking another tenant's
max-date rows) **does not occur** in 0.211.0. Note for RFC 0013 §5.7's test wording: under
the default optimization level the ratio plan renders **one** shared scan, not two
component subqueries — the policy-AST test must assert "predicate in every scan", not
"exactly two subqueries".

Escape hatch probed anyway: `PydanticNodeRelation` has **no `sql` body field** (fields:
`alias`, `schema_name`, `database`, `relation_name`), so a tenant-filtered node relation
cannot be an inline subquery — it must be a **per-tenant filtered view/table name**.
Demonstrated executable: a manifest pointing at
`CREATE VIEW gold.mart_inventory_acme AS SELECT … WHERE tenant_key = 'acme'` is accepted
and returns correct by-month results. Not needed, but the fallback works and its shape is
now known.

**ANSWER: PASS.** The row-policy predicate reaches every scan of the mart, pre-aggregation,
in ratio and semi-additive plans (grouped and ungrouped); no security defect; R7's
where-constraint design is safe to build on. The RFC 0013 §5.7 escape hatch stays unbuilt;
if ever needed it is a view-name swap, not a `sql` field.

---

## Recommended RFC amendments

1. **RFC 0013 §Status / §10:** V1–V4 all answered PASS → M4.5 gate cleared; move the four
   unresolved questions to answered with the facts above.
2. **RFC 0013 §3 / pivot §2 gotchas:** amend "without transform() … queries resolve
   incorrectly" → in 0.211.0 the failure is **loud**
   (`MetricFlowInternalError: missing metric_aggregation_params` at `explain()`); add the
   MSI circular-import gotcha (`implementations.node_relation` must not be the first MSI
   import) and the top-level `msi_pydantic_shim` module note; note the extra
   `-- Write to DataTable` plan comment in rendered SQL.
3. **RFC 0013 §5.7 / D9 and pivot R7:** reword the policy-AST test from "both component
   subqueries of the ratio" to "every scan of the mart relation" — the default
   optimization level collapses the ratio to a single shared scan.
4. **RFC 0013 §8/§5.7 escape hatch:** record that `PydanticNodeRelation` has no `sql`
   field; the (unneeded) fallback is a per-tenant **view name**.
5. **RFC 0013 §9 risks:** retire "semi-additive grouping defect (#241)" — fixed in
   0.211.0; keep the version-drift canary since the fix is only verified at this pin.
6. **RFC 0014 (hydration):** replace the pivot's provisional numbers with measured ones
   (cold 10.5 ms, +~6 ms lazy first-explain, 1.54 MB/tenant, payload 144.9 KB at 30
   models); keep 50 ms/10 ms budgets (≥4× headroom); add a 3× tenant-size point to
   `tests/bench/test_hydration.py`; note `SemanticManifestLookup` laziness — pre-warm
   should issue one throwaway `explain()` if first-query latency matters.
7. **RFC 0001 (dependencies):** add `metricflow==0.211.*` to `[project].dependencies`
   (runtime, tightly pinned per RFC 0013 D1). **No `requires-python` change** — metricflow
   0.211.0 is `>=3.10,<3.15`, same upper bound as ours; classifiers stay 3.12/3.13/3.14.
   Record new transitive runtime deps (jsonschema, more-itertools, rapidfuzz, referencing,
   tabulate, python-dateutil, importlib-metadata) and the top-level `msi_pydantic_shim`
   module for deptry configuration.
8. **RFC 0009 / D7 fixtures (`semi_additive_inventory`):** apply the V2 errata — the
   unscoped 3-day-filter assertion must expect 130 (or the seed must keep warehouse B out
   of the window) since "90" only holds scoped to warehouse A; month-grain DuckDB results
   are `TIMESTAMP`s.
