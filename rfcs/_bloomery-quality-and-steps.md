# `bloomery` — Data Quality & the Step Registry

**Document 5.** Two related additions: declarative cleansing rules, and a registry for the logic
that cannot be declared. They ship together because the escape hatch is only safe if quality
rules apply at its boundary.

**Amends:** `spec/` (new sub-schemas), `guardrails/` (clarified boundary), `plan/` (new change
class), D2 marts (quality columns), D7 fixtures.
**Adds:** `bloomery/quality/`, `bloomery/steps/`, and a `StepRegistry` compile input.
**Milestones:** inserts **M5.5** (quality) and **M9.5** (steps). Rationale in §10.

> **Note (RFC corpus):** Preserved verbatim as source material alongside the four earlier
> input documents. Lands in the corpus as RFC 0016 (data quality) and RFC 0017 (step
> registry). Where RFCs diverge from this document, the RFCs win.

---

## 1. The problem and the principle

Everything specified so far is *structural*: what an entity is, where a field comes from, how a
metric is computed. None of it says what to do when `unit_price` arrives as `"12,50 €"`, when
the same order appears three times, or when 4% of order lines point at an order that doesn't
exist.

Two failure modes to avoid, and they pull in opposite directions:

**Cleansing lives outside the spec.** Hand-written SQL beside the generated models. It drifts
from the spec, isn't versioned with it, and — worst — `plan()` cannot see it, so a cleansing
change silently fails to trigger the backfill it requires.

**Cleansing lives *inside* the spec as code.** A Python body in a YAML field. This is the alpha's
failure mode returning: unreviewable (nobody diffs a code blob in config), undeterminable, and
untestable in isolation.

The resolution is a single principle, applied throughout:

> **Specs describe. Specs reference implementations. Specs never contain implementations.**

Declarative rules cover the large majority. What they can't cover becomes a **registered step** —
platform code, in git, reviewed as code, referenced from the spec by name and version, and wired
into the same DAG so lineage, diffing, and backfill all still work.

---

## 2. Where cleansing belongs

"Cleansing" bundles eight distinct concerns with different homes. Getting the layer wrong is the
most common structural mistake here.

| Concern | Layer | Mechanism |
|---|---|---|
| Type coercion (`"12,50"` → decimal) | bronze→silver | transform whitelist *(exists)* |
| Normalization (trim, case, enum, unit, tz) | bronze→silver | transform whitelist *(exists)* |
| Coercion failure handling | bronze→silver | implicit `coercible` rule (§3.2) |
| Deduplication | bronze→silver | `dedupe` block |
| Null / range / pattern violations | bronze→silver | field rules |
| Cross-field consistency | silver | row rules |
| Referential integrity | silver→mart | join policy |
| Reconciliation against source totals | silver→mart | reconcile model |
| Entity resolution, fuzzy matching | its own node | **registered step** (§6) |

**Bronze gets nothing.** It is the replay source; cleansing it destroys the ability to reprocess
under a corrected spec.

**Gold gets nothing.** Gold is `REBUILDABLE`. Cleansing there means a rebuild produces different
data than the original, which breaks the one property that makes gold disposable.

---

## 3. The disposition model

### 3.1 Four outcomes, and the one that's missing

Detection is easy. The architectural decision is what happens to a failing row, and it must be
explicit per rule — never a global default.

```python
class OnFail(StrEnum):
    REPAIR     = "repair"      # deterministic fix applied; recorded in _quality_flags
    FLAG       = "flag"        # row passes unchanged; recorded in _quality_flags
    QUARANTINE = "quarantine"  # row diverted to <entity>__reject; replayable
    FAIL       = "fail"        # blocking audit; the run stops
```

**There is deliberately no `DROP`.** Silently discarding rows is the fastest way for a BI product
to lose trust permanently, and it is the disposition everyone reaches for first. `QUARANTINE` is
`DROP` plus recoverability, and recoverability matters because most quarantined rows return after
a spec fix — the enum-widening case from the drift walkthrough is the normal path, not the
exception.

If a spec author genuinely wants rows gone, they quarantine and set a retention policy (§5.4).
That is a deletion with a paper trail.

### 3.2 Coercion failure is a rule, not a special case

The transform chain currently produces a value or raises. Change it to produce a value or a
**coercion failure marker**, then let the implicit `coercible` rule dispose of it:

```yaml
fields:
  unit_price:
    from: "$.Price"
    transform: [to_decimal]
    # implicit, always present, overridable:
    # quality: [{rule: coercible, on_fail: quarantine}]
```

This unifies three things that were separate: `on_unmapped_enum: quarantine` from the mapping
schema, transform failures, and explicit rules. One mechanism, one quarantine table, one
disposition vocabulary.

Default is `quarantine`. A field may override to `flag` (accept the null, mark the row) or
`fail` (a coercion failure here means the pipeline is broken).

---

## 4. Spec schema

### 4.1 Field-level

```yaml
# mappings/shopify.orders.yaml
fields:
  unit_price:
    from: "$.Price"
    transform: [to_decimal]
    quality:
      - {rule: coercible,  on_fail: quarantine}
      - {rule: not_null,   on_fail: quarantine}
      - {rule: range, min: 0,          on_fail: quarantine}
      - {rule: range, max: 1000000,    on_fail: flag}
  email:
    from: "$.Email"
    transform: [trim, lower]
    quality:
      - {rule: pattern, regex: "^[^@]+@[^@]+\\.[^@]+$", on_fail: flag}
  status:
    from: "$.Stat"
    transform: [{enum_map: {...}}]
    quality:
      - {rule: in_enum, on_fail: quarantine}   # values outside the entity's enum
```

Rule catalogue, closed set:

| Rule | Parameters | Notes |
|---|---|---|
| `coercible` | — | implicit; transform chain succeeded |
| `not_null` | — | after transforms |
| `range` | `min`, `max` (either) | numeric, date, timestamp |
| `length` | `min`, `max` | strings |
| `pattern` | `regex` | anchored; dialect-portable subset only |
| `in_enum` | — | against the entity field's declared enum |
| `in_set` | `values` | ad-hoc allowlist |
| `unique` | — | across the mart partition; expensive, see §5.5 |

### 4.2 Entity-level

```yaml
entities:
  order_item:
    key: [order_id, line_no]

    dedupe:
      keep: latest_by
      field: _ingested_at
      tie_break: [_load_id]        # required: makes the winner deterministic

    quality:
      - rule: expression
        name: discount_not_exceeding_gross
        expr: "discount <= unit_price * quantity"
        on_fail: flag
      - rule: referential
        via: item_of_order
        on_missing: unknown_member  # unknown_member | quarantine | flag
```

`tie_break` is mandatory when `keep: latest_by`. Without it, two rows sharing a timestamp make
the winner arbitrary and the model non-deterministic — which violates the framework's core
invariant and produces a backfill that disagrees with the original run.

### 4.3 Reconciliation

```yaml
reconcile:
  - name: order_total_matches_lines
    left:  "sum(order_item.line_total) by order_id"
    right: "order.total_amount"
    tolerance: "0.01"
    on_fail: flag
```

Emits its own model plus a non-blocking audit. This is the check that catches a *correct formula
over wrong data* — the class of error no field rule finds.

---

## 5. Lowering

### 5.1 Fixed pipeline order

Declared once, never per-field, never configurable:

```
1. extract        JSON path from bronze
2. transform      cast + normalize; may yield a coercion failure marker
3. dedupe         key + recency + tie-break
4. field rules    coercible, not_null, range, length, pattern, in_enum, in_set
5. row rules      expression, referential
6. route          partition into <entity> and <entity>__reject
```

**Dedupe sits at 3, before the rules, deliberately.** The alternative — rules first, dedupe over
survivors — means a corrupt latest row is silently replaced by a stale-but-clean older one. That
is data loss disguised as data quality: the dashboard shows an old value with no indication it's
old. Deduping on identity first, then validating the winner, surfaces the problem instead.

Consequence: fields referenced by `dedupe.field` and `dedupe.tie_break` have their `coercible`
rule forced to `fail` regardless of declared disposition, because an uncastable recency field
makes dedupe ordering undefined. Compile-time check, clear error message.

### 5.2 Rule → SQL

| Spec | Generated |
|---|---|
| `dedupe` | `QUALIFY ROW_NUMBER() OVER (PARTITION BY key ORDER BY field DESC, tie_break DESC) = 1` |
| `on_fail: repair` | `CASE` expression in the SELECT + flag appended |
| `on_fail: flag` | predicate evaluated into `_quality_flags` array |
| `on_fail: quarantine` | predicate drives a two-way split into entity / reject |
| `on_fail: fail` | SQLMesh **blocking** audit on the model |
| `referential: unknown_member` | `LEFT JOIN` + `COALESCE(fk, '__unknown__')` + reserved dimension row |
| `reconcile` | separate model + non-blocking audit |

`unknown_member` deserves emphasis: it is the option that keeps aggregates *correct*. Dropping
orphan rows makes revenue quietly lower than the source system's. Routing them to a reserved
`Unknown` member keeps the total right and makes the problem visible **in the dashboard**, which
is where someone will actually notice it.

### 5.3 Columns added to every silver entity

```sql
_quality_flags   ARRAY<STRING>   -- rule names that fired with disposition flag/repair
_quality_ok      BOOLEAN         -- cardinality(_quality_flags) = 0; generated, for cheap filtering
```

And on marts (D2), flattened for analyst use:

```sql
has_quality_flags  BOOLEAN
```

Making it a mart dimension means "revenue excluding flagged rows" is an ordinary `MetricRequest`,
not a bespoke query. Dialects without an array type declare
`Feature.ARRAY_COLUMN = False` and lower `_quality_flags` to a delimited string; the capability
check belongs in `TargetCapabilities` (D6).

### 5.4 The quarantine table

**One per entity, not per mapping.** Per-mapping tables multiply into the small-file problem and
make replay N-way.

```sql
CREATE TABLE <ns>.<entity>__reject (
  reject_id      STRING,          -- sha256(source, load_id, source_row_id) — stable, for idempotent replay
  mapping        STRING,          -- which mapping produced it
  mapping_version INT,
  failed_rules   ARRAY<STRING>,
  key_values     VARIANT,         -- best-effort; may be null if the key itself failed
  raw            VARIANT,         -- the bronze payload
  _load_id       STRING,
  _ingested_at   TIMESTAMP,
  first_seen     TIMESTAMP,
  last_seen      TIMESTAMP,
  resolved_at    TIMESTAMP        -- set on successful replay; never deleted by replay
)
```

**Replay** re-runs the current mapping against `raw` for unresolved rows. Rows that now pass are
merged into the entity by key; rows that still fail get `failed_rules` and `last_seen` updated.
Must be idempotent — running replay twice merges the same rows and changes nothing.

⚠️ **`raw` holds source payloads, which means quarantine tables hold PII.** They are not covered
by any retention rule the spec currently expresses. Add one, required at the entity level:

```yaml
quarantine:
  retention: 90d
  redact: ["$.ssn", "$.card_number"]   # dropped from raw at write time, not at read time
```

A quarantine table with no declared retention should be a compile error, not a default. This is
the sort of thing that is trivial now and a legal problem in eighteen months.

### 5.5 Cost notes

- `flag` rules evaluate their predicate for **every row**, every run. Cheap individually, not
  free in aggregate. Emit them as a single `ARRAY_CONSTRUCT_COMPACT` of `CASE`s rather than N
  separate passes.
- `unique` requires a window over the partition. Document it as expensive; consider restricting
  it to the incremental window rather than the whole table.
- `pattern` regex flavours diverge across engines. Restrict to a portable subset (character
  classes, anchors, quantifiers; no lookaround, no named groups) and **validate at compile time**
  against each target dialect via SQLGlot. A regex that works on DuckDB and silently means
  something else on Trino is exactly the kind of bug this project exists to prevent.

---

## 6. The step registry

### 6.1 The four-tier ladder

Rule: **use the lowest tier that works.**

| Tier | Kind | Scope | Bloomery can | Use when |
|---|---|---|---|---|
| 0 | DSL transform | expression | typecheck fully | whitelist covers it |
| 1 | `sql_macro` | expression | **parse and typecheck** | one gnarly expression |
| 2 | `sql_model` | table | parse, infer schema | multi-step SQL, windows, recursive CTEs |
| 3 | `python_model` | table | **nothing — trust + verify** | fuzzy matching, ML, genuinely not SQL |

Tier 1 is free at runtime: the macro body is a SQL expression with named parameters, bloomery
parses it with SQLGlot and splices it into the generated SELECT. The model stays one query and
column-level lineage sees straight through. Most "we need Python" requirements turn out to be
Tier 1 or 2 on inspection.

Tier 3 means data leaves the engine, becomes memory-bound, and loses column-level lineage. Real
cost — pay it deliberately.

### 6.2 Step manifest

Two files, in the **platform** repo, not in bloomery and not in tenant specs.

```yaml
# steps/resolve_customers/manifest.yaml
ref: resolve_customers
version: 3
kind: python_model                 # sql_macro | sql_model | python_model
determinism: pure                  # pure | seeded | nondeterministic
runtime_lock: sha256:a91f…         # hash of the pinned dependency set (§6.6)

inputs:
  raw:
    grain: customer_source_row
    requires: [source_system, source_id, email, name]

outputs:
  customer:
    grain: customer
    produces:
      canonical_id: {type: string, required: true}
      email:        {type: string}
      name:         {type: string}
      confidence:   {type: decimal(4,3)}
  customer_xref:
    grain: xref
    produces:
      canonical_id: {type: string, required: true}
      source_system: {type: string, required: true}
      source_id:    {type: string, required: true}
      confidence:   {type: decimal(4,3)}
      method:       {type: string}

parameters:
  blocking_key: {type: string,  default: "email_domain"}
  threshold:    {type: decimal, default: 0.85, min: 0, max: 1}

lineage: coarse                    # coarse | column
```

```python
# steps/resolve_customers/impl.py
@step("resolve_customers", version=3)
def resolve(raw: pd.DataFrame, *, blocking_key: str, threshold: Decimal
            ) -> dict[str, pd.DataFrame]:
    ...
```

Tenant spec wires it and nothing more:

```yaml
steps:
  - use: resolve_customers@3
    inputs:  {raw: silver.customer_raw}
    outputs: {customer: silver.customer, customer_xref: silver.customer_xref}
    parameters: {threshold: 0.9}
    quality:
      - {rule: expression, expr: "confidence >= 0.8", on_fail: flag, applies_to: customer_xref}
```

### 6.3 Purity: the registry is a compile input

Bloomery must not read step files from disk — that would break invariant #1.

```python
@dataclass(frozen=True)
class StepRegistry:
    steps: Mapping[tuple[str, int], StepManifest]   # (ref, version) -> manifest
    macro_bodies: Mapping[tuple[str, int], str]     # sql_macro bodies, for parsing

def compile_project(project, *, target, dialect, naming, catalog=None,
                    steps: StepRegistry = EMPTY_REGISTRY) -> tuple[EmittedArtifact, ...]: ...
```

The caller assembles it. A spec referencing `resolve_customers@3` when the registry has only
`@2` is `UnknownStep`, at compile time, naming available versions. A spec referencing a step
absent entirely is `UnknownStep` too — **there is no dynamic loading path**, which is what keeps
tenant specs from becoming an arbitrary-code-execution surface.

### 6.4 Trust the declaration, verify at runtime

Bloomery cannot infer a Python function's output schema, so:

- **At compile time**, it trusts `outputs.*.produces` and typechecks downstream models against
  it. The DAG stays complete and `plan()` still computes backfills across the step.
- **At run time**, the generated wrapper asserts reality matches the declaration.

```python
# generated wrapper, python_model
@model("silver.customer", kind="FULL", columns={...from manifest...})
def execute(context, **kwargs):
    raw = context.fetchdf("SELECT * FROM silver.customer_raw")
    out = resolve(raw, blocking_key="email_domain", threshold=Decimal("0.9"))
    assert_step_contract(out, MANIFEST)     # ← generated, not optional
    return out["customer"]
```

`assert_step_contract` checks, in order: every declared output is present; no undeclared outputs;
column set matches exactly; types are assignable; `required: true` columns have no nulls; and the
declared grain holds (a uniqueness check on the grain key).

**The runtime assertion is not optional and not configurable.** Without it, `produces` decays
into stale documentation within a quarter — the same reasoning as `CompiledPlan.reads` in the
Forze contract: a claim that is checked is a commitment, a claim that isn't is a comment.

### 6.5 Determinism tiers

| Tier | Meaning | Bloomery behaviour |
|---|---|---|
| `pure` | same inputs → byte-identical outputs | backfillable freely |
| `seeded` | deterministic given an explicit seed | seed **required** in the spec; recorded in the ledger |
| `nondeterministic` | reads the clock, network, or unseeded RNG | **compile error** |

A `nondeterministic` step makes backfills disagree with original runs, which destroys the ability
to restate — the one capability the whole architecture is organised around. Refusing it is not
conservatism; it is the load-bearing constraint.

### 6.6 Runtime pinning

A step's behaviour depends on its libraries. `rapidfuzz` changing a scorer between minor versions
silently changes entity resolution outputs, and nothing in the spec would show it.

`runtime_lock` is a hash of the step-runtime dependency set, computed at registry build time and
**included in the step's identity**. A dependency bump therefore changes the step fingerprint,
which classifies as `RESTATING` (§7), which triggers a backfill. That is the correct behaviour
and it is invisible without the lock.

### 6.7 Multi-tenant rule: parameterize, never fork

**Steps are platform code. A tenant configures parameters; a tenant never supplies a body.**

When a tenant needs something the library can't do, generalize the step into a parameterized
form. Do not write `resolve_customers_acme`. Forking gives you N copies of the same logic, no way
to ship a fix, and — if bodies ever came from tenant data — a sandboxing problem.

If a requirement genuinely cannot generalize, that is a useful signal: it's bespoke consulting,
not product. Knowing that explicitly is better than discovering it through a directory of
near-identical step files.

This produces the same compounding loop as catalog recipes: tenant 1 needs custom matching → a
parameterized step is written → tenant 2 sets `threshold: 0.9` and reuses it. The library grows;
the bespoke surface shrinks.

---

## 7. Interaction with existing machinery

### 7.1 Guardrails vs quality rules — the boundary

Easy to conflate, and conflating them produces a spec where nobody knows what fails when.

| | Guardrails (`guardrails/`) | Quality rules (`quality/`) |
|---|---|---|
| When | compile time | run time |
| Input | the spec | the data |
| Failure | `BloomeryError`, nothing is emitted | a disposition per row |
| Example | "summing an order-grain measure on an item-grain mart" | "this row's discount exceeds its gross" |

**A guardrail says the model is wrong. A quality rule says the data is wrong.** Nothing that can
be decided from the spec alone belongs in `quality/`.

### 7.2 `plan()` and change classification

New change class:

```python
class ChangeClass(StrEnum):
    ADDITIVE   = "additive"
    WIDENING   = "widening"
    RENAME     = "rename"
    RESTATING  = "restating"     # ← quality rules and step versions land here
    BREAKING   = "breaking"
```

Anything below changes historical output and therefore requires a backfill:

- adding, removing, or changing any quality rule
- changing a disposition (`flag` → `quarantine` is restating in both directions)
- changing `dedupe.keep`, `field`, or `tie_break`
- a step version bump, **including a `runtime_lock` change**

This is the entire payoff of keeping cleansing in the spec rather than beside it: the backfill is
computed, not remembered.

One nuance to implement: a `quarantine → flag` relaxation also needs a **quarantine replay**, not
just a backfill, since the affected rows are sitting in the reject table rather than in bronze's
incremental window. `Plan` gains a `replay_scope` alongside `backfill_scope`.

### 7.3 Marts (D2)

- `has_quality_flags` flattened in, as §5.3.
- A mart's `base` must be a silver entity, never a reject table.
- Rows that were quarantined never reach a mart, so mart row counts legitimately differ from
  bronze. The conservation audit (§8.4) is what makes that difference explainable rather than
  alarming.

### 7.4 MetricFlow / serving

The quality mart (§7.5) is emitted as an ordinary semantic model, so quarantine rate is a metric
like any other. Reject tables themselves are **not** exposed through `MetricRequest` — they hold
raw payloads and are governed by different retention. They get a separate, deliberately narrow
operator surface.

### 7.5 The quality mart

Every rule evaluation emits a row:

```sql
gold.mart_data_quality(
  tenant_id, entity, mapping, rule, disposition,
  rows_evaluated, rows_failed, rows_quarantined, rows_deduped,
  run_id, run_date
)
```

Three things fall out:

1. Queryable through the same semantic layer — "quarantine rate by source, last 30 days" is an
   ordinary `MetricRequest`.
2. Tenant-visible. Their data problems, surfaced. That's a feature, not an admission.
3. **A rising quarantine rate is a drift signal.** It feeds the proposal loop exactly as a schema
   hash change does — and it catches *semantic* drift, which structural detection misses
   entirely. A source that starts sending prices in cents instead of euros changes no schema.

---

## 8. Testing

The section that matters most. Cleansing bugs are silent by nature: the pipeline is green, the
numbers are wrong.

### 8.1 The dirty-data corpus

A curated, versioned artifact — the single highest-value asset in this document.

```
tests/fixtures/dirty/
  numerics.csv       "12,50"  "1 234.56"  "€12.50"  "(45.00)"  "1.2e3"  ""  "NULL"  "-0"
  dates.csv          "31/12/2025"  "2025-12-31T00:00:00+03:00"  "20251231"  "0000-00-00"
  enums.csv          "paid"  "PAID"  " paid "  "payed"  "1"  ""  "authorized"
  keys.csv           duplicates, near-duplicates, whitespace variants, case variants, nulls
  refs.csv           orphan FKs, self-references, FKs to quarantined parents
  unicode.csv        RTL marks, zero-width joiners, homoglyph digits, NFC vs NFD
  extremes.csv       max/min decimal, NaN, Infinity, epoch 0, year 9999
```

Grow it from real tenant data (redacted). Every production incident adds a row. It becomes the
regression suite that makes cleansing changes safe.

### 8.2 Unit — rule lowering

Per rule × per disposition: assert the emitted AST shape. Fast, exhaustive, no engine.

```python
@pytest.mark.parametrize("rule,disp", product(ALL_RULES, ALL_DISPOSITIONS))
def test_every_rule_disposition_pair_lowers(rule, disp):
    plan = lower_quality(rule, disp, dialect=DUCKDB)
    assert plan.ast is not None
    assert sqlglot.parse_one(plan.sql, "duckdb")     # always parses
```

The `product()` is the point: the combinatorial matrix is small enough to cover exhaustively, and
a missing pair is exactly the kind of gap that ships.

### 8.3 Execution — the primary gate

Seed dirty fixtures, run the generated models, assert both the surviving rows **and** the
quarantine contents.

```python
def test_uncastable_price_is_quarantined(duckdb, ecom_project):
    seed("bronze.orders", [
        {"id": 1, "Price": "12.50"},
        {"id": 2, "Price": "not a number"},
        {"id": 3, "Price": ""},
    ])
    run_models(ecom_project)
    assert rows("silver.order_item") == [{"order_id": "1", "unit_price": Decimal("12.50")}]
    rejects = rows("silver.order_item__reject")
    assert {r["reject_id"] for r in rejects} == {reject_id(2), reject_id(3)}
    assert all("coercible" in r["failed_rules"] for r in rejects)
```

Assert on quarantine contents, not just on survivors. A test that only checks what passed cannot
tell "correctly quarantined" from "silently dropped."

### 8.4 Property — the conservation law

The single best invariant available here:

```python
@given(dirty_batches())
def test_no_row_is_ever_unaccounted_for(batch):
    seed("bronze.orders", batch)
    run_models(project)
    assert len(batch) == (
        count("silver.order_item")
        + count("silver.order_item__reject")
        + deduped_count_from_quality_mart()
    )
```

Every bronze row ends in exactly one of three places. If this holds, rows cannot vanish — which
is the failure mode that destroys trust and the one hardest to notice. Emit it as a **runtime
audit** too, not only a test: the same check on every production run.

### 8.5 Idempotence and backfill equivalence

```python
def test_second_run_changes_nothing(duckdb, project):
    seed(...); run_models(project); snap1 = snapshot_all()
    run_models(project);            snap2 = snapshot_all()
    assert snap1 == snap2

def test_backfill_reproduces_incremental(duckdb, project):
    for day in days: seed_day(day); run_models(project)
    incremental = snapshot_all()
    truncate_all(); seed_all(days); run_models(project, full_refresh=True)
    assert incremental == snapshot_all()
```

The second is the one that catches non-deterministic dedupe tie-breaks, clock reads inside steps,
and order-dependent rules. Make it a merge gate — it is the executable form of the determinism
invariant.

### 8.6 Quarantine replay

```python
def test_replay_after_enum_widening(duckdb, project):
    seed_with_unknown_enum_value()
    run_models(project)
    assert count("silver.order__reject") == 312

    widened = widen_enum(project, "status", add="authorized")
    plan = compute_plan(project, widened)
    assert plan.replay_scope.entities == {"order"}      # plan knows replay is needed

    run_models(widened); replay(widened)
    assert count("silver.order__reject", unresolved=True) == 0
    assert count("silver.order") == 312 + baseline
    replay(widened)                                     # idempotence
    assert count("silver.order") == 312 + baseline
```

### 8.7 Step contract violations

Adversarial fake steps that lie about their outputs. Every one must fail loudly at run time.

| Fake step | Expected |
|---|---|
| returns an extra column | `StepContractViolation: undeclared column` |
| omits a declared column | `StepContractViolation: missing column` |
| returns wrong type | `StepContractViolation: type mismatch` |
| nulls in a `required` column | `StepContractViolation: null in required` |
| duplicate grain keys | `StepContractViolation: grain not unique` |
| returns an undeclared output table | `StepContractViolation: undeclared output` |
| reads `datetime.now()` | caught by 8.5's backfill test |

The last one is why 8.5 is a gate: static analysis of step bodies is out of scope, so
non-determinism is caught behaviourally.

### 8.8 Step golden fixtures — in the platform repo

Each step ships input and expected-output CSVs, versioned with the step:

```
steps/resolve_customers/
  manifest.yaml  impl.py
  fixtures/v3/  input_raw.csv  expected_customer.csv  expected_customer_xref.csv
```

Runnable with no tenant, no catalog, no bloomery. The step registry gets its own independent test
suite, which is the whole reason for the manifest boundary.

Version bumps require new fixtures — a `@4` reusing `@3`'s expected outputs is a review failure,
because if the outputs are unchanged it should not have been a version bump.

### 8.9 Dialect matrix

Run 8.3's assertions on DuckDB (every commit), Postgres (every commit), Trino and Spark
(nightly). Cleansing is where dialects diverge most: regex flavours, null ordering in
`ROW_NUMBER`, decimal rounding, array construction, empty-string-vs-null. A rule that quarantines
different rows on Trino than on DuckDB is a correctness bug the golden SQL tests will not catch.

### 8.10 Chaos meta-test

Once a quarter, mutate the lowering (invert a comparison, drop a rule from the pipeline, swap a
disposition) and confirm at least one test fails for each mutation. If a mutation survives, the
suite has a hole. This is the only way to know whether the dirty corpus is still adequate as the
rule set grows.

---

## 9. Migrating existing scripts

If a pile of cleansing SQL or Python already exists:

1. **Wrap, don't refactor.** Add a manifest, register as `@1`, `lineage: coarse`,
   `determinism: pure` — and *verify* that claim with 8.5 rather than assuming it.
2. **Get it into the DAG.** The immediate win is that `plan()` can see it and backfills stop
   being manual.
3. **Then push down the ladder.** Most SQL scripts collapse to Tier 2 immediately; a surprising
   number of Python ones are Tier 1 expressions wearing a dataframe.
4. **Extract rules as you go.** Every `WHERE x IS NOT NULL` inside a script that becomes a
   declared `not_null` rule is one more thing `plan()` understands and the quality mart reports.

---

## 10. Milestones

Inserted rather than renumbered, so existing references stay valid.

| # | Scope | Done when |
|---|---|---|
| M5 | Marts + role-playing *(existing)* | ✓ |
| **M5.5** | **Quality rules: schema, lowering, quarantine, replay, quality mart** | dirty corpus passes 8.3; conservation property (8.4) green; backfill equivalence (8.5) green |
| M6 | `MetricFlowEmitter` *(existing)* | ✓ |
| M7 | Planner + coverage + filters + policy *(existing)* | ✓ |
| M8 | Hydration + caching *(existing)* | ✓ |
| M9 | `plan()` + change classification *(existing)* | now also classifies `RESTATING` for quality changes, with `replay_scope` |
| **M9.5** | **Step registry: manifest, `StepRegistry` input, three kinds, runtime assertion** | all 8.7 adversarial steps refused; step goldens green in the platform repo |
| M10 | Trino dialect + Cube emitter *(existing)* | ✓ |
| M11 | E2E + three-way equivalence *(existing)* | ✓ |

**Why quality lands at M5.5:** marts are built from silver, so silver must be clean before mart
semantics can be trusted. Also, `_quality_flags` changes the silver schema — cheaper before the
MetricFlow emitter binds to it than after.

**Why steps land at M9.5:** a step version bump is a `RESTATING` change, so the classifier must
exist first. Building steps before M9 means the backfill behaviour is untestable.

---

## 11. Open questions

1. **Repair recipes** — should `on_fail: repair` reference the catalog's recipe library (so a
   repair learned for one tenant is reused), or stay inline per rule? The recipe route is
   consistent with the derivation design and probably right, but it couples quality to the
   catalog earlier than necessary.
2. **Quality rules on mart outputs** — currently silver-only. A mart-level assertion ("no month
   has zero revenue") is useful but blurs the line with reconciliation. Defer until there's a
   real case.
3. **Sampling for expensive rules** — should `unique` and `pattern` support
   `sample: 0.01` for very large partitions? Adds a probabilistic result to a system that is
   otherwise exact. Lean no.
4. **Cross-entity rules** — "every customer has at least one order" spans entities and doesn't
   fit the field/row/entity taxonomy. Probably a reconcile-style construct rather than a rule.
5. **Step concurrency** — can two steps write the same output table? Currently no, implicitly.
   Make it explicit as a compile-time check.
