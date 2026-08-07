# RFC 0016 — Data quality: declarative cleansing, dispositions, quarantine

- **Status:** 📝 Draft
- **Scope:** Run-time data quality as declarative spec surface: the `quality:` /
  `dedupe:` / `quarantine:` / `reconcile:` sub-schemas, the `OnFail` disposition
  model, the closed rule catalogue, the fixed pipeline order and its lowering, the
  replayable `<entity>__reject` table, `_quality_flags` on silver /
  `has_quality_flags` on marts, and the `gold.mart_data_quality` mart. New package:
  `bloomery/quality/`. Amends shipped RFCs: 0002 (`on_unmapped_enum` retired), 0006
  (the `assert:`-vs-`quality:` boundary), 0007 (`RESTATING`; `Plan.replay_scope`),
  0008 (D7 superseded; `DialectFeature.ARRAY`), 0009 (dirty corpus, conservation
  law), 0010 (`has_quality_flags`). Logic that cannot be declared is RFC 0017's
  (shipped as a pair: quality rules apply at the escape hatch's edge). Compile-time
  model validation stays in `guardrails/` (§5.9); bloomery never executes — replay
  *execution* is the caller's runtime concern.
- **Related:** [`rfcs/_bloomery-quality-and-steps.md`](_bloomery-quality-and-steps.md)
  (Document 5); RFCs 0002, 0006, 0007, 0008, 0009, 0010, 0017;
  [`src/bloomery/spec/mapping.py`](../src/bloomery/spec/mapping.py),
  [`src/bloomery/spec/entity.py`](../src/bloomery/spec/entity.py),
  [`src/bloomery/plan/model.py`](../src/bloomery/plan/model.py),
  [`src/bloomery/dialects/base.py`](../src/bloomery/dialects/base.py).
- **Origin:** Document 5, written for an M5.5 slot that predates M5–M11 shipping;
  re-landed as wave M12 (§12).

---

## 1. Summary

Cleansing becomes spec surface under one principle: **specs describe, specs reference
implementations, specs never contain implementations.** A closed rule catalogue
attaches to mappings and entities; every rule carries an explicit disposition —
`flag | quarantine | fail`, never a global default, deliberately no `drop`, and no
`repair` in v1 (deferred, §10).
Coercion failure becomes the implicit `coercible` rule, retiring
`Mapping.on_unmapped_enum` and RFC 0008 D7 in one move. Failing rows route to one
replayable `<entity>__reject` table per entity with mandatory retention; flags flow
through silver into a `has_quality_flags` mart dimension; every rule evaluation feeds
an ordinary semantic mart. Bronze gets nothing (it is the replay source); gold gets
nothing (it is rebuildable — cleansing there breaks the one property that makes gold
disposable). Quality changes classify `RESTATING`; `plan()` gains a `replay_scope`.

## 2. Motivation

Everything shipped through M11 is *structural* — nothing says what happens when
`unit_price` arrives as `"12,50 €"`, the same order appears three times, or 4% of
order lines point at a missing order. Both obvious homes fail: cleansing SQL beside
the generated models drifts and `plan()` cannot see it, so a cleansing change
silently skips the backfill it requires; cleansing *inside* the spec as code blobs is
unreviewable, undeterminable, untestable. Today the only quality-shaped surface is
`Mapping.on_unmapped_enum` — a one-value `Literal["quarantine"]` no emitter
implements — and RFC 0006 D8's audit-only `assert:` clauses, which alert but never
route a row. The missing piece is a disposition system, in the spec, so the backfill
is computed, not remembered.

## 3. Current state

Verified against the code (the source document predates M5–M11):

- `Mapping.on_unmapped_enum: Literal["quarantine"]`
  ([`spec/mapping.py`](../src/bloomery/spec/mapping.py) ~line 122) is spec-only;
  `enum_map` passes unmapped values through, deferring to "an emitter concern
  (RFC 0008 D7)" — but `grep -rn quarantine src/bloomery/emit/` returns nothing.
  D7's `<entity>__quarantine` artifact was declared, never shipped; this RFC
  supersedes a paper convention.
- `AssertClause` on `Field.assert_` ([`spec/entity.py`](../src/bloomery/spec/entity.py))
  lowers to `AuditIR` (RFC 0006 D8) — audit-only, non-row-routing; the ancestor this
  design reconciles with, not replaces (§5.3).
- `Plan` ([`plan/model.py`](../src/bloomery/plan/model.py)) has `backfill_scope`, no
  replay concept; `RESTATING` ships since M9.
- `DialectFeature` ([`dialects/base.py`](../src/bloomery/dialects/base.py)) has four
  members, no array capability; nor does the target-side `Feature` enum.
- The MetricFlow emitter (RFC 0013) and planner are bound to the current silver/mart
  schemas — §5.5's additions re-open them (§12).

## 4. Goals / Non-goals

**Goals:** every cleansing decision declared, versioned, diffable, and visible to
`plan()`; explicit per-rule dispositions with no row ever silently discarded; one
replayable, PII-governed quarantine surface per entity; quality observability through
the ordinary semantic layer.

**Non-goals:** compile-time model validation (that is `guardrails/`, §5.9 — nothing
decidable from the spec alone belongs in `quality/`); executing replay or retention
(bloomery emits models and merge artifacts; the caller runs them); imperative
cleansing logic (RFC 0017); cleansing bronze or gold (§1).

## 5. Design

### 5.1 The disposition model

Layer placement follows Document 5 §2 with one correction: coercion/normalization and
everything through row rules live bronze→silver; reconcile checks run silver→mart;
entity resolution is its own DAG node — a registered step (RFC 0017). `referential` is
**silver, not silver→mart** — Document 5's layer-table row is corrected to "silver
(reads sibling silver entities)": it runs at the bronze→silver row-rule stage (§5.4
stage 5) of the *dependent* entity's model, reading the referenced **silver** entity —
topological ordering (RFC 0005) guarantees the referenced entity is built first — and
its quarantined rows land in the dependent entity's own `__reject`.

```python
class OnFail(StrEnum):
    FLAG       = "flag"        # row passes unchanged; recorded in _quality_flags
    QUARANTINE = "quarantine"  # row diverted to <entity>__reject; replayable
    FAIL       = "fail"        # blocking audit; the run stops
```

Explicit per rule, never a global default. There is no `REPAIR` in v1 — deferred to §10,
demand-gated on a repair-recipe contract (decision 17). **There is deliberately no `DROP`**:
silently discarding rows is the fastest way for a BI product to lose trust
permanently, and it is the disposition everyone reaches for first. `QUARANTINE` is
`DROP` plus recoverability — which matters because most quarantined rows return after
a spec fix (enum widening is the normal path, not the exception). Wanting rows gone
means quarantine plus a retention policy (§5.6): a deletion with a paper trail.

### 5.2 Coercion failure is a rule; the `assert:` boundary

Transform chains change from produce-or-raise to produce a value or a **coercion
failure marker** (`TRY_CAST`-shaped lowering per dialect); the implicit,
always-present, overridable `coercible` rule (default `quarantine`) disposes of it.
One mechanism, one reject table, one disposition vocabulary — unifying
`on_unmapped_enum`, transform failures, and explicit rules:

- **RFC 0002 amendment:** `Mapping.on_unmapped_enum` is retired, absorbed into
  `in_enum`/`coercible` (an unmapped enum value simply fails `in_enum`). Removed
  pre-0.1, no migration owed.
- **RFC 0008 amendment:** D7 (quarantine as emitter convention, tagged "revisit if a
  second policy consumer appears") is superseded by the modeled reject table (§5.6).
  The second consumer appeared; it is this RFC.
- **RFC 0006 reconciliation:** `assert:` clauses **remain** as compile-to-audit,
  non-row-routing checks. The boundary: `assert:` is "alert me" — an audit that
  observes; `quality:` is "act on the row" — the disposition system that routes. A
  field may carry both; the docs must state when to use which.

### 5.3 Spec schema

```yaml
fields:                                # mapping-level field rules
  unit_price:
    from: "$.Price"
    transform: [to_decimal]
    quality:
      - {rule: coercible,  on_fail: quarantine}   # implicit; shown for the override
      - {rule: range, min: 0,       on_fail: quarantine}
      - {rule: range, max: 1000000, on_fail: flag}

entities:                              # entity-level
  order_item:
    dedupe: {keep: latest_by, field: _ingested_at, tie_break: [_load_id]}
    quarantine: {retention: 90d}       # required — quarantine dispositions exist above, so
                                       # omitting this is QuarantineRetentionMissing (§5.6)
    quality:
      - {rule: expression, name: discount_not_exceeding_gross,
         expr: "discount <= unit_price * quantity", on_fail: flag}
      - {rule: referential, via: item_of_order, on_missing: unknown_member}

reconcile:
  - {name: order_total_matches_lines, left: "sum(order_item.line_total) by order_id",
     right: "order.total_amount", tolerance: "0.01", on_fail: flag}
```

Closed field-rule catalogue: `coercible` (implicit), `not_null`, `range`, `length`,
`pattern` (anchored; a **portable regex subset** — character classes, anchors,
quantifiers; no lookaround, no named groups — compile-time validated against every
target dialect via sqlglot, because a regex that works on DuckDB and silently means
something else on Trino is exactly the bug this project exists to prevent),
`in_enum`, `in_set`, `unique`. `unique` evaluates within the model's **incremental
processing scope**: for incremental materializations, the partition slice(s) being
(re)computed in the batch; for full materializations, the whole table. Cross-window
duplicates are explicitly **not** detected by `unique` — that is key-based dedupe's job,
and a late-arriving duplicate key lands on `dedupe`, not `unique`. Backfill/incremental
equivalence holds because the same per-partition evaluation applies in both modes.
Sampling is rejected per Document 5 §11.3 — a probabilistic result in an otherwise exact
system.

`tie_break` is mandatory under `keep: latest_by` — its absence is the compile error
`DedupeTieBreakMissing`: two rows sharing a timestamp
otherwise make the winner arbitrary — a nondeterministic model violates the core
invariant (RFC 0003) and makes backfills disagree with original runs.
`referential.on_missing` ∈ `{unknown_member, quarantine, flag}`; `unknown_member`
keeps aggregates *correct*: "Dropping orphan rows makes revenue quietly lower than
the source system's. Routing them to a reserved `Unknown` member keeps the total
right and makes the problem visible **in the dashboard**, which is where someone will
actually notice it." `reconcile` emits its own model plus a non-blocking audit — the
check that catches a *correct formula over wrong data*.

### 5.4 Fixed pipeline order and lowering

Declared once, never per-field, never configurable:

```
1. extract → 2. transform → 3. dedupe → 4. field rules → 5. row rules → 6. route
```

**Dedupe sits before the rules deliberately.** The alternative — rules first, dedupe
over survivors — "means a corrupt latest row is silently replaced by a
stale-but-clean older one. That is data loss disguised as data quality: the dashboard
shows an old value with no indication it's old." Consequence: fields named by
`dedupe.field`/`tie_break` have `coercible` **forced to `fail`** regardless of
declared disposition — an uncastable recency field makes dedupe ordering undefined;
a user-declared weaker disposition on such a field is the compile error
`DedupeDispositionConflict`.

| Spec | Generated |
|---|---|
| `dedupe` | `QUALIFY ROW_NUMBER() OVER (PARTITION BY key ORDER BY field DESC NULLS LAST, tie_break… DESC NULLS LAST, _source_row_id DESC) = 1` |
| `on_fail: flag` | predicate evaluated into `_quality_flags` — all flag rules in **one** array-construct pass, never N scans |
| `on_fail: quarantine` | predicate drives a two-way split into entity / reject |
| `on_fail: fail` | SQLMesh **blocking** audit on the model |
| `referential: unknown_member` | `LEFT JOIN` + `CASE WHEN ref.<pk> IS NULL AND fk IS NOT NULL THEN '__unknown__' ELSE fk END` + reserved dimension row |
| `reconcile` | separate model + non-blocking audit |

**The dedupe order is total.** After `field` DESC and the `tie_break` columns, the final
sort key is the stable source-row identity `_source_row_id` (§5.6's ingestion metadata
contract), so the winner is unique by construction — no two rows can compare equal. Null
ordering is pinned: `NULLS LAST` for the recency field and every tie-break column — a null
recency loses to any non-null one.

**Disposition precedence.** A row can fail several rules carrying different dispositions;
severity order is `fail > quarantine > flag`. Any failing `fail` rule stops the run (the
blocking audit); otherwise any failing `quarantine` rule diverts the row to the reject
table — with **all** failed rule names recorded in the reject's `failed_rules`, its
flag-level failures included; otherwise flags accumulate in `_quality_flags`. The outcome
is deterministic for every combination, so no compile-time rejection of rule/disposition
combinations is needed.

**Three-valued logic.** Each rule defines a *violation predicate*, and a rule fires only
when that predicate is definitively TRUE: a NULL-involved comparison evaluating to SQL
`UNKNOWN` does **not** fire. Nulls are owned by `not_null` and `coercible` — declare those
if nulls are invalid. This applies to `range`, `length`, `pattern`, `in_enum`, `in_set`,
`expression`, and `referential` alike: a NULL fk is not an orphan — it is `not_null`'s
business. This is also why the referential lowering is the `CASE` above, not Document 5's
bare `COALESCE(fk, '__unknown__')` — that sketch was wrong, mapping a NULL fk to the
unknown member; only a non-null fk with no referenced row is an orphan (correction
recorded, decision 19).

`QUALIFY` is DuckDB-native; Postgres and any engine without it get the equivalent
`ROW_NUMBER`-in-a-subquery lowering through the shared dialect-neutral AST — one AST,
per-dialect legal rendering, the same doctrine as RFC 0008. Target coverage:
**SQLMesh** emits the full quality set (split models, reject tables, replay merge,
quality mart); **dbt** initially raises `UnsupportedByTarget` for the reject/replay
artifacts (honest port-proof scope); **Cube/MetricFlow** consume the quality mart like
any mart.

### 5.5 Schema additions and the array capability

Every silver entity gains `_quality_flags ARRAY<STRING>` and `_quality_ok BOOLEAN`
(generated, `cardinality(_quality_flags) = 0`); marts (RFC 0010 amendment) flatten in
`has_quality_flags BOOLEAN` as an ordinary dimension — "revenue excluding flagged
rows" becomes a plain `MetricRequest`. **Deliberate divergence from Document 5
§5.3:** the doc places the array capability in `TargetCapabilities`; array support is
an *engine* property (SQLMesh-on-DuckDB and dbt-on-DuckDB share it — the RFC 0008 D1
split), so it lands as `DialectFeature.ARRAY`; dialects without it lower
`_quality_flags` to a delimited string. The physical contract is pinned per shape so
the two lowerings agree observably: rule names are identifier-constrained at spec
parse (`[a-z0-9_]+`, so no escaping is ever needed in either form); `_quality_flags`
is **never NULL** — a clean row carries the empty array (array dialects: DuckDB
`STRING[]`, Postgres `TEXT[]`, Trino `ARRAY(VARCHAR)`) or the empty string (delimited
fallback, joined with `,` in lexicographic rule-name order for deterministic bytes);
`_quality_ok` is generated per shape as `cardinality(_quality_flags) = 0` /
`_quality_flags = ''`. Equality of the two lowerings' flag *sets* is asserted in the
dialect-matrix execution tier (§6). Two mart rules follow: a mart's `base` must be
a silver entity — never a reject table; a mart declared over `<entity>__reject` is a
compile error. And mart rowcounts legitimately differ from bronze — quarantined rows
never reach marts; the conservation audit (§6) is what makes that difference
explainable rather than alarming.

### 5.6 Quarantine: one reject table per entity

One `<entity>__reject` per entity, never per mapping (per-mapping tables multiply
into the small-file problem and make replay N-way):

```sql
CREATE TABLE <ns>.<entity>__reject (
  reject_id       STRING,     -- sha256 over the canonical (source, _load_id, _source_row_id) triple; stable, idempotent replay
  mapping         STRING,
  mapping_version INT,
  failed_rules    ARRAY<STRING>,
  key_values      VARIANT,    -- best-effort; null if the key itself failed
  raw             VARIANT,    -- the bronze payload
  _load_id        STRING,
  _ingested_at    TIMESTAMP,
  _source_row_id  STRING,     -- stable per-source-row identity (ingestion metadata contract)
  first_seen      TIMESTAMP,
  last_seen       TIMESTAMP,
  resolved_at     TIMESTAMP   -- set on successful replay; never deleted by replay
)
```

**Ingestion metadata contract.** Entities using `quarantine` or `dedupe` require the bronze
ingestion metadata columns `_load_id`, `_ingested_at`, and `_source_row_id` — a stable
per-source-row identity supplied by the ingestion layer. Their absence is the compile error
`IngestionMetadataMissing`, a `GuardrailError` leaf declared in `errors.py` per RFC 0002 D3
(§5.9). `reject_id` is the sha256 over the **length-prefixed utf-8 triple** (source
relation, `_load_id`, `_source_row_id`) — canonical serialization per the RFC 0003
canon-bytes doctrine — so it is stable across retries by construction.

`raw` holds source payloads — quarantine tables hold PII. When any rule carries a
`quarantine` disposition, the entity **must** declare a `quarantine:` block with
`retention:`; absence is a compile error (`QuarantineRetentionMissing`), not a default — "this is the sort of thing
that is trivial now and a legal problem in eighteen months." Optional `redact:`
JSONPath list applies to `raw` — and identically to `key_values` — at **write** time;
`retention:` governs the whole reject row. Replay re-runs the current mapping
against `raw` for unresolved rows, merging passers into the entity by key and
updating `failed_rules`/`last_seen` on the rest. **Replay merges by the same dedupe
ordering as the pipeline**: a replayed candidate wins or loses against an incumbent row by
the dedupe total order (recency field, tie-breaks, `_source_row_id`), and multiple rejects
resolving to one entity key are ordered the same way. The per-entity replay batch is one
atomic MERGE — transactionality belongs to the executing engine; bloomery emits the
artifact. Idempotence follows from the total order: re-running replay re-derives the same
winners, so running it twice changes nothing. A replayed row lives in the entity from then on; its reject row is
retained purely as audit history — `resolved_at` set, never deleted — and drops out of
the conservation accounting, which counts only unresolved rejects
(`resolved_at IS NULL`; §6). Bloomery emits the reject model and replay merge artifact;
**executing** replay is the caller's runtime concern — the package never executes
(hard invariant).

### 5.7 `plan()` integration (RFC 0007 amendment)

Adding, removing, or changing any quality rule; changing a disposition (**both**
directions); changing `dedupe.keep`/`field`/`tie_break` — all classify **RESTATING**.
Nuance: a `quarantine → flag` relaxation needs a **quarantine replay**, not just a
backfill — the affected rows sit in the reject table, not in bronze's incremental
window. `Plan` gains `replay_scope: ReplayScope` alongside `backfill_scope`. The
RFC 0007 decision table gets its append-only row dated when this ships. This is the
entire payoff of keeping cleansing in the spec: the backfill is computed, not
remembered.

### 5.8 The quality mart

Every rule evaluation emits a row into `gold.mart_data_quality(entity, mapping, rule,
disposition, rows_evaluated, rows_failed, rows_quarantined, rows_deduped, run_id,
run_date)` — an **ordinary semantic model** (`run_date` is its time dimension per
RFC 0010 D9: measure-carrying marts declare a date role; `MartMissingTimeDimension`,
RFC 0013 D3), so quarantine rate is a plain `MetricRequest`, and a rising rate is
a *semantic* drift signal structural detection misses (prices arriving in cents
change no schema). Reject tables are **not** exposed through `MetricRequest` — raw
payloads, different retention; a separate, deliberately narrow operator surface.
**Deliberate divergence from Document 5 §7.5:** the doc's schema includes
`tenant_id`, which violates hard invariant #3 and the tenant guard (RFC 0009 D14).
Bloomery emits the mart **without** a tenant column: namespace scoping via
`NamingPolicy` is the only tenant-shaped seam; a caller wanting per-tenant rollup
gets it from their naming/namespace layout, as for every other table.

### 5.9 Guardrails vs quality — the boundary

Verbatim from Document 5 §7.1, because conflating them produces a spec where nobody
knows what fails when:

| | Guardrails (`guardrails/`) | Quality rules (`quality/`) |
|---|---|---|
| When | compile time | run time |
| Input | the spec | the data |
| Failure | `BloomeryError`, nothing is emitted | a disposition per row |
| Example | "summing an order-grain measure on an item-grain mart" | "this row's discount exceeds its gross" |

**A guardrail says the model is wrong. A quality rule says the data is wrong.**
Nothing that can be decided from the spec alone belongs in `quality/`. The compile
errors this RFC adds — `QuarantineRetentionMissing` (§5.6), `DedupeTieBreakMissing`
(§5.3), `DedupeDispositionConflict` (§5.4), `IngestionMetadataMissing` (§5.6) — are guardrails by this table's
definition: `GuardrailError` leaves declared in `errors.py` per RFC 0002 D3.

## 6. Tests (RFC 0009 amendment)

- **Dirty-data corpus** — `tests/fixtures/dirty/` (numerics, dates, enums, keys,
  refs, unicode, extremes), grown from redacted production incidents: every incident
  adds a row; the regression suite that makes cleansing changes safe.
- **Unit** — the rule × disposition lowering matrix, covered **exhaustively** via
  `product(ALL_RULES, ALL_DISPOSITIONS)`: a missing pair is exactly the gap that ships.
- **Three-valued logic** — per-rule tests assert the §5.4 semantics: NULL-involved
  comparisons evaluating to SQL `UNKNOWN` do **not** fire for
  `range`/`length`/`pattern`/`in_enum`/`in_set`/`expression`/`referential` (a NULL fk is
  not an orphan); `not_null` and `coercible` are the rules that own nulls.
- **Execution** — seed dirty fixtures, run the models, assert survivors **and
  quarantine contents** (`reject_id`, `failed_rules`): a test that only checks what
  passed cannot tell "correctly quarantined" from "silently dropped".
- **Property: the conservation law** — every bronze row lands in exactly one of
  entity / unresolved reject (`resolved_at IS NULL`) / deduped-count; if it holds,
  rows cannot vanish. Resolved reject rows are audit history, excluded from the
  accounting — a replayed row counts once, in the entity, never twice. Also emitted
  as a **runtime audit** on every production run, not only a test.
- **Merge gates** — idempotence and backfill equivalence (full refresh ≡ incremental
  history): the executable determinism invariant; catches nondeterministic tie-breaks
  and order-dependent rules.
- **Replay** — enum widening: `plan()` reports `replay_scope`, replay drains the
  reject table, second replay is a no-op.
- **Dialect matrix emphasis** — cleansing is where dialects diverge most (regex
  flavours, `ROW_NUMBER` null ordering, decimal rounding, array construction,
  empty-string-vs-null); tier 5 runs the execution assertions per engine.
- **Quarterly chaos meta-test** — mutate the lowering (invert a comparison, drop a
  stage, swap a disposition); at least one test must fail per mutation, or the dirty
  corpus has a hole.

## 7. Docs

A concept page on the disposition model (stating plainly why `drop` does not exist);
reference pages for the rule catalogue and `quarantine:` block; the
`assert:`-vs-`quality:` boundary ("alert me" vs "act on the row") and the §5.9 table.
§5.6's PII framing is worded as an obligation, not an option.

## 8. Out of scope

- **Repair** — the disposition itself is deferred out of v1, demand-gated on a
  repair-recipe contract (§10, decision 17).
- **Mart-level quality rules** — blurs into reconciliation; deferred until a real case.
- **Retention/redaction execution** — bloomery emits schema and policy; deletion jobs
  are the caller's.

## 9. Risks

- *Flag-rule cost creep* — mitigated by the single-pass array construction (§5.4).
- *`unknown_member` rows read as corruption* — the reserved member is documented and
  the quality mart names the producing rule.
- *Schema-change blast radius* (§12) — `_quality_flags` re-opens every silver golden,
  manifest, and fingerprint. Accepted and recorded, not hidden.
- *Quarantine as a PII lake* — mitigated structurally: retention is a compile
  requirement, redaction happens at write time.

## 10. Unresolved questions

- **Repair** (deferred out of v1 — decision 17): the disposition returns only
  demand-gated on a repair-recipe contract; inline vs catalog-referenced recipes is part
  of that contract question. Constraint discovered in review (credit: cubic): when repair
  lands it must carry a **distinct marker** separating "repaired, now correct" from
  "currently flagged bad", so `has_quality_flags` keeps meaning "currently suspect".
- Mart-level rules ("no month has zero revenue") — reconcile-shaped or new surface?
- Sampling for `pattern` on huge partitions — **lean no**: a probabilistic result in
  an otherwise exact system (for `unique` it is rejected outright — D5, Document 5
  §11.3).
- Cross-entity rules ("every customer has ≥1 order") — probably reconcile-style.
- Step output concurrency — settled in RFC 0017 (two steps, one output: compile error).

## 11. Decisions

| # | Decision |
| --- | --- |
| 1 | The governing principle: **specs describe, specs reference implementations, specs never contain implementations.** Bronze gets no cleansing (replay source); gold gets none (rebuildable). |
| 2 | `OnFail = flag \| quarantine \| fail` (v1 — `repair` deferred, decision 17), explicit per rule, never a global default. Deliberately no `drop`: quarantine is drop plus recoverability; deletion happens via retention policy, with a paper trail. |
| 3 | Coercion failure is a rule: transform chains lower to failure-marker form (`TRY_CAST`-style per dialect); the implicit, overridable `coercible` rule (default `quarantine`) disposes of it. Retires `Mapping.on_unmapped_enum` (RFC 0002 amendment — absorbed into `in_enum`/`coercible`) and supersedes RFC 0008 D7's never-implemented emitter convention with the modeled reject table. |
| 4 | `assert:` clauses (RFC 0006 D8) remain as compile-to-audit, non-row-routing checks ("alert me"); `quality:` rules are the row-disposition system ("act on the row"). A field may carry both; docs state when to use which. |
| 5 | Closed field-rule catalogue: `coercible`, `not_null`, `range`, `length`, `pattern` (portable regex subset, compile-time validated per target dialect via sqlglot), `in_enum`, `in_set`, `unique` (restricted to the incremental window; full-partition uniqueness explicitly out of scope, sampling rejected per Document 5 §11.3). New rules are RFC amendments, not config. |
| 6 | Entity-level `dedupe` requires `tie_break` under `keep: latest_by` (nondeterministic winners violate the core invariant); dedupe-referenced fields' `coercible` is forced to `fail`. Row rules `expression` and `referential` (`on_missing ∈ {unknown_member, quarantine, flag}`; `unknown_member` keeps aggregates correct via a reserved member row); `reconcile` blocks emit model + non-blocking audit. |
| 7 | Fixed pipeline order — extract → transform → dedupe → field rules → row rules → route — never configurable. Dedupe before rules: validating first silently replaces a corrupt latest row with a stale clean one — data loss disguised as data quality. |
| 8 | Lowering per §5.4's table: `QUALIFY ROW_NUMBER` dedupe over the pinned total order, all flag rules in one `_quality_flags` array pass, two-way entity/reject split, blocking audit for `fail`. |
| 9 | Silver gains `_quality_flags`/`_quality_ok`; marts gain `has_quality_flags` (RFC 0010 amendment). Array capability is `DialectFeature.ARRAY` — an engine property, deliberately diverging from Document 5's `TargetCapabilities` placement; dialects without it lower to a delimited string. |
| 10 | One `<entity>__reject` table per entity with the §5.6 schema (stable sha256 `reject_id` for idempotent replay). Retention is **required** whenever any quarantine disposition exists — missing retention is a compile error; `redact:` paths apply at write time. Bloomery emits the reject/replay artifacts and never executes them. |
| 11 | RFC 0007 amendment (dated when implemented): quality rule add/remove/change, disposition changes in both directions, and dedupe changes classify `RESTATING`; `Plan` gains `replay_scope` alongside `backfill_scope` — `quarantine → flag` needs replay, not just backfill. |
| 12 | `gold.mart_data_quality` is an ordinary semantic model (`run_date` as time dimension); quarantine rate is a `MetricRequest`. Reject tables are never exposed through `MetricRequest`. Deliberate divergence: no `tenant_id` column (Document 5 §7.5 has one) — hard invariant #3 and the tenant guard forbid it; `NamingPolicy` namespaces are the only tenant seam. |
| 13 | The guardrail boundary (§5.9) is normative: guardrail = the model is wrong, compile time; quality rule = the data is wrong, run time. Nothing decidable from the spec alone enters `quality/`. |
| 14 | Testing per §6 (RFC 0009 amendment): dirty corpus, exhaustive rule×disposition matrix, quarantine-contents assertions, the conservation-law property doubled as a runtime audit, idempotence + backfill-equivalence merge gates, replay tests, dialect-matrix emphasis, quarterly chaos meta-test. |
| 15 | A mart's `base` must be a silver entity, never a reject table — a mart over `<entity>__reject` is a compile error. Mart rowcounts legitimately differ from bronze (quarantined rows never reach marts); the conservation audit is what makes the difference explainable. |
| 16 | New compile errors: `QuarantineRetentionMissing` (quarantine disposition without `retention:`), `DedupeTieBreakMissing` (`keep: latest_by` without `tie_break`), `DedupeDispositionConflict` (user-declared weaker disposition on a dedupe-referenced field where `coercible` is forced to `fail`) — all `GuardrailError` leaves declared in `errors.py` per RFC 0002 D3. |
| 17 | **Repair deferred out of v1** (amends rows 2 and 8 as originally drafted): dispositions v1 = `flag \| quarantine \| fail`; `repair` moves to §10, demand-gated on a repair-recipe contract. Constraint recorded from review (credit: cubic): when repair lands it must carry a **distinct marker** separating "repaired, now correct" from "currently flagged bad", so `has_quality_flags` keeps meaning "currently suspect". |
| 18 | Disposition precedence for a row failing multiple rules — severity order `fail > quarantine > flag`: any failing `fail` rule stops the run (blocking audit); else any failing `quarantine` rule diverts the row, with **all** failed rule names recorded in the reject's `failed_rules` (flag-level failures included); else flags accumulate in `_quality_flags`. Deterministic for every combination — no compile-time rejection of rule/disposition combinations needed. |
| 19 | Three-valued logic: each rule defines a violation predicate and fires only when it is definitively TRUE — NULL-involved comparisons evaluating to SQL `UNKNOWN` do **not** fire (`not_null`/`coercible` own nulls; declare them if nulls are invalid). Applies to `range`/`length`/`pattern`/`in_enum`/`in_set`/`expression`/`referential` — a NULL fk is not an orphan. Corrects Document 5's referential lowering: the bare `COALESCE(fk, '__unknown__')` sketch was wrong (it maps a NULL fk to the unknown member); the lowering is `CASE WHEN ref.<pk> IS NULL AND fk IS NOT NULL THEN '__unknown__' ELSE fk END`. |
| 20 | Dedupe is a total order: after `field` DESC and the `tie_break` columns, the final sort key is the stable source-row identity `_source_row_id` — the winner is unique by construction. Null ordering pinned: `NULLS LAST` for the recency field and every tie-break column (a null recency loses). |
| 21 | Ingestion metadata contract: entities using `quarantine` or `dedupe` require bronze `_load_id`, `_ingested_at`, `_source_row_id` (a stable per-source-row identity supplied by the ingestion layer); absence is the new compile error `IngestionMetadataMissing` (`GuardrailError` leaf, `errors.py` per RFC 0002 D3). `reject_id` = sha256 over the length-prefixed utf-8 triple (source relation, `_load_id`, `_source_row_id`) — canonical serialization per the RFC 0003 canon-bytes doctrine; stable across retries by construction. |
| 22 | Replay merge semantics: replay applies the **same dedupe ordering** as the pipeline — a replayed candidate merges by entity key and wins/loses against an incumbent by the dedupe total order (recency, tie-breaks, `_source_row_id`); multiple rejects resolving to one key are ordered the same way. The per-entity replay batch is one atomic MERGE (transactionality is the executing engine's; bloomery emits the artifact); idempotence follows from the total order — re-running replay re-derives the same winners. |
| 23 | `_quality_flags` physical contract: rule names identifier-constrained at parse (no escaping in any lowering); the column is never NULL (empty array / empty delimited string per `DialectFeature.ARRAY`); delimited fallback joins with `,` in lexicographic rule-name order; `_quality_ok` generated per shape; flag-set equality across lowerings asserted in the dialect-matrix tier. |

## 12. Phasing

Lands as **M12**, the first post-M11 wave (RFC 0017 follows as M13). Document 5
slotted this at M5.5 precisely because `_quality_flags` changes the silver schema —
"cheaper before the MetricFlow emitter binds to it than after." That warning came
true: M6–M11 shipped first, so landing now regenerates every silver golden,
`metricflow/manifest.json`, and fingerprint, and re-binds the MetricFlow emitter and
planner to the widened schemas — accepted cost, recorded so nobody reads the golden
churn as a regression. Order within M12: spec sub-schemas + lowering + reject
emission; then replay artifacts and `replay_scope`; the quality mart last. Done when
the dirty corpus passes the execution tier, the conservation property is green, and
backfill equivalence holds as a merge gate.
