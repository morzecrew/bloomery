# RFC 0016 — Data quality: declarative cleansing, dispositions, quarantine

- **Status:** ✅ Complete — shipped 2026-08-08 (wave M12). Landed: the
  `quality:`/`dedupe:`/`quarantine:`/`reconcile:` spec sub-schemas with the closed
  rule catalogue and portable regex
  subset; `bloomery/quality/` lowering the rules to dialect-neutral predicates under
  the three-valued discipline (D19), the `_quality_flags`/`failed_rules` physical
  contract (D23), and the dedupe total order (D20); ten compile-time guardrail checks
  (the five named `errors.py` leaves plus five bare `GuardrailError` refusals);
  SQLMesh emission of the dedupe `QUALIFY`, the two-way entity/reject split, the
  `<entity>__reject` model, the D21 metadata audit, per-`fail`-rule blocking audits,
  the per-entity conservation audit and the replay `MERGE` artifact (dbt raises
  `UnsupportedByTarget` for reject/replay); `_quality_flags`/`_quality_ok` on every
  silver model and `has_quality_flags` on marts; `gold.mart_data_quality` as an
  ordinary mart; `Plan.replay_scope`; `DialectFeature.ARRAY` and
  `DialectFeature.TRY_CAST`; `Mapping.on_unmapped_enum` retired and
  `bloomery_ir_version` bumped to 2; the dirty-data corpus with its execution,
  conservation-property, replay and chaos tiers. **Divergences from the design as
  drafted are D24–D31**, appended dated below: implicit `coercible` is opt-in per
  entity (D24), the D21 audit additionally asserts `_ingested_at` is castable to
  timestamp (D25, implemented per D31), two recorded corpus gaps (D26, D28),
  `referential` onto the entity itself is refused (D27), the conservation audit's
  shape and its one skipped case (D29), and Postgres cannot host quality-carrying
  entities at all (D30) — including dedupe-only ones (D31). **D32–D66 are the
  self-audit fix waves**, appended dated below (rows 40–44 deliberately absent —
  see the numbering note): lowering corrections (D32–D39), guardrail widenings
  (D45–D48), plan-diff corrections (D49–D52, D58–D60), the portable-regex
  allowlist (D53–D57), and the wave that hardened the *test suite* where it was
  proved unable to detect a regression (D61–D66). **D67–D71 are the re-audit of
  those waves**: the population D32's own fix stopped covering (D67), a mart count
  that came out NULL rather than zero on an empty run (D68), the replay loser with
  no stated reason (D69), the two clocks in `last_seen` (D70), and a generated rule
  name displaced by an authored one (D71).
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
    REPAIR     = "repair"      # recipe rewrites the value; resolves to `fallback`
```

Explicit per rule, never a global default. **There is deliberately no `DROP`**:
silently discarding rows is the fastest way for a BI product to lose trust
permanently, and it is the disposition everyone reaches for first. `QUARANTINE` is
`DROP` plus recoverability — which matters because most quarantined rows return after
a spec fix (enum widening is the normal path, not the exception). Wanting rows gone
means quarantine plus a retention policy (§5.6): a deletion with a paper trail.

> **Amended 2026-08-10 (D87):** `REPAIR` joined the vocabulary. It was deferred out of
> v1 (D17) pending a repair-recipe contract, and RFC 0017's step registry is one: a
> recipe is a registered Tier 1 `sql_macro`, named `ref@version`, with a declared
> signature, a `runtime_lock` and a determinism tier. That also settles §10's *inline vs
> catalog-referenced* question, and not by preference — D1 holds that specs reference
> implementations and never contain them.
>
> It is the one member that is not a disposition on its own. A repair rule carries a
> `fallback` for the row its recipe did **not** fix, and `disposition()` resolves
> `repair` to that fallback, so severity, routing and precedence never see it. A
> repaired row simply stops violating its rule.
>
> ```yaml
> - rule: charset
>   forbid: [U+200B, U+FFFD]
>   on_fail: repair
>   repair: {via: strip_invisible@1, fallback: quarantine}
> ```
>
> Refused where there is no repairable value in hand: `coercible` fires *because* the
> projection is already NULL, so the recipe would be handed the NULL rather than the
> text that failed to cast; `unique` is a property of a population; a row rule names no
> column. Fixing a value *before* it is coerced is a different job with its own shape —
> a Tier 1 macro spliced into the mapping (RFC 0017 D50), which runs before any rule
> sees the value.

### 5.2 Coercion failure is a rule; the `assert:` boundary

Transform chains change from produce-or-raise to produce a value or a **coercion
failure marker** (`TRY_CAST`-shaped lowering per dialect); the implicit,
always-present, overridable `coercible` rule (default `quarantine`) disposes of it.
One mechanism, one reject table, one disposition vocabulary — unifying
`on_unmapped_enum`, transform failures, and explicit rules:

> **Amended 2026-08-08 (D24):** "always present" shipped as **opt-in per entity**.
> An entity joins the quality system when it declares `quality:`, `quarantine:`, or
> any field-level `quality:` — `dedupe:` alone does not — and only then does the
> implicit `coercible` rule exist. Read the paragraph above as scoped to
> quality-carrying entities.

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
    key: [order_id, line_no]           # dedupe partitions by the entity key; replay merges by it
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
`in_enum`, `in_set`, `unique`. `unique` is evaluated **per partition slice** in both
full and incremental runs — the partition is the scope unit in either mode; for an
unpartitioned FULL entity the slice is the whole table, again in both modes.
Cross-partition duplicates are out of scope for `unique` in **every** mode — identity
duplicates are key-based dedupe's job, and a late-arriving duplicate key lands on
`dedupe`, not `unique`. Full/incremental equivalence holds *because* the scope unit is
identical in both modes, not despite it.
Sampling is rejected per Document 5 §11.3 — a probabilistic result in an otherwise exact
system.
> **Amended 2026-08-08 (D53–D56):** the sentence above overstates two things and
> under-specifies a third. (1) The subset is a closed **allowlist**, not "no lookaround,
> no named groups" — a denylist accepted backreferences, atomic groups, possessive
> quantifiers and `\A`/`\Z`, every one of which *aborts* on RE2 (D53). (2) "Anchored" is
> an obligation on the author, enforced at parse: an unanchored pattern is a
> `SpecParseError` (D54). (3) "Compile-time validated against every target dialect via
> sqlglot" is not a thing sqlglot can do — bloomery never executes SQL, so no compile-time
> render proves an engine accepts a regex. The dialect check is a *surface and transport*
> check; the portability claim is carried by the allowlist (D55), and the dialects checked
> are the shipped ports, not whatever the process has registered (D56).
>
> **Amended 2026-08-08 (D71):** rule names come from two places — generation (a
> field rule's column and kind, an implicit `coercible`'s column, a `referential`'s
> relationship) and an author (an `expression` rule's `name:`) — and they share one
> namespace. An authored name equal to one generation issues is a **compile-time
> `GuardrailError`** naming both, because either arbitration is wrong: renaming the
> generated rule moves the key of a quality-mart time series (§5.8) under an edit
> that never touched the field, and renaming the authored one contradicts what a
> human wrote. Generated names are assigned in their own pass first, so they are a
> function of the mapping alone.
>
> **Amended 2026-08-08 (D62):** `in_set`'s members carry their declared **type** into the
> IR. `values` admits `int` beside `str` while `QualityRuleIR.params` is a sorted tuple of
> strings, so `str(value)` erased the difference and an integer member rendered as a string
> literal — coerced by DuckDB and Postgres, refused by Trino. `in_enum` is unaffected: its
> set is an `enum_map` chain's targets, which are text by construction.
>
> **Amended 2026-08-10 (D86):** the catalogue gains **`normalize`** and **`charset`**, the
> two rules D26 recorded as missing.
>
> `{rule: normalize, form: nfc}` fires when the value is not already in the named Unicode
> normal form — `NORMALIZE(col, NFC) <> col`, the dialect-neutral node, rewritten to
> `NFC_NORMALIZE` on DuckDB. One form, because Postgres and Trino spell all four and
> DuckDB has only this one: admitting `nfkc` would ship a rule that compiles everywhere
> and runs on two engines out of three. A rule and never a transform — normalizing
> silently would rewrite what a source delivered, which D1 forbids.
>
> `{rule: charset, allow: […]}` / `{rule: charset, forbid: […]}` declares the admissible
> characters as `U+` codepoints and inclusive ranges, exactly one side, lowering through
> `TRANSLATE(col, members, '')`: `LENGTH(…) > 0` for `allow` (something survived
> deletion), `LENGTH(…) < LENGTH(col)` for `forbid` (the value shrank). Codepoints rather
> than characters because every character the rule exists to catch is invisible, and a
> literal one in a YAML file is unreadable in review. Both readings stay `UNKNOWN` on a
> null (D19), and neither is expressible as a `pattern`: the portable subset forbids
> precisely the codepoint-class constructs this would need — but a literal *set* is not a
> regex at all.
>
> **The confusables table is deliberately not built.** D26 offered "a Unicode normal form
> and/or a confusables table"; the table is versioned Unicode data, and embedding it would
> make a row's disposition depend on which Unicode revision the compiler happened to ship
> — an ambient input by another name (RFC 0003). `charset`'s `allow` reading is *stronger*
> for the case that motivated it: an allow-list of the script a column is actually written
> in catches a Cyrillic homoglyph, a fullwidth digit and an Arabic-Indic digit alike, none
> of which any denylist enumerates completely.

`tie_break` is mandatory under `keep: latest_by` — its absence is the compile error
`DedupeTieBreakMissing`: two rows sharing a timestamp
otherwise make the winner arbitrary — a nondeterministic model violates the core
invariant (RFC 0003) and makes backfills disagree with original runs.
> **Amended 2026-08-08 (D38):** `reconcile.on_fail` is not a mart label. `fail` emits a
> **blocking** audit — §5.3 nominates reconcile as the pipeline-stopping gate ("a
> pipeline-stopping orphan gate, where genuinely wanted, is expressed as a `reconcile`
> check instead"), and that sentence is only true if the value blocks. `flag` stays
> non-blocking for the reason below. `quarantine` also lowers non-blocking: a reconcile
> compares aggregates and routes no row, so the value has nothing to divert — refusing
> it belongs to the spec surface, where `on_fail` is typed.

`referential.on_missing` ∈ `{unknown_member, quarantine, flag}`; `unknown_member`
keeps aggregates *correct*: "Dropping orphan rows makes revenue quietly lower than
the source system's. Routing them to a reserved `Unknown` member keeps the total
right and makes the problem visible **in the dashboard**, which is where someone will
actually notice it." `fail` is deliberately **not** a referential disposition: orphans
are an expected, recoverable data condition — exactly what `quarantine` and
`unknown_member` exist for — and a pipeline that stops on every orphan punishes the
normal case; a pipeline-stopping orphan gate, where genuinely wanted, is expressed as a
`reconcile` check instead. `reconcile` emits its own model plus a non-blocking audit — the
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

> **Amended 2026-08-08 (D25):** the forcing reaches *mapped fields* only. The usual
> `dedupe.field` is `_ingested_at`, which is ingestion metadata rather than a mapped
> field, so no `coercible` rule is generated for it and the D21 audit checks only a
> null or duplicated `_source_row_id` — an uncastable `_ingested_at` leaves dedupe
> ordering silently undefined. The decided contract: the D21 blocking audit **also**
> asserts `_ingested_at` is castable to timestamp. Not yet implemented; the gap is
> held open by a strict-`xfail` execution test (`keys.csv::uncastable_ingested_at`).
>
> **Amended 2026-08-08 (D31):** implemented. The audit's `WHERE` now carries
> `OR (_ingested_at IS NOT NULL AND TRY_CAST(_ingested_at AS TIMESTAMP) IS NULL)`
> beside the null and duplicate checks, and `keys.csv::uncastable_ingested_at` is a
> passing assertion rather than an `xfail`. The audit therefore needs
> `DialectFeature.TRY_CAST` on its own account, which extends D30's refusal to
> dedupe-only entities.

| Spec | Generated |
|---|---|
| `dedupe` | `QUALIFY ROW_NUMBER() OVER (PARTITION BY key ORDER BY field DESC NULLS LAST, tie_break… DESC NULLS LAST, _source_row_id DESC NULLS LAST) = 1` |
| `on_fail: flag` | predicate evaluated into `_quality_flags` — all flag rules in **one** array-construct pass, never N scans |
| `on_fail: quarantine` | predicate drives a two-way split into entity / reject |
| `on_fail: fail` | SQLMesh **blocking** audit on the model |
| `referential: unknown_member` | `LEFT JOIN` + `CASE WHEN ref.<pk> IS NULL AND fk IS NOT NULL THEN '__unknown__' ELSE fk END` + reserved dimension row |
| `referential: quarantine` | same `LEFT JOIN` probe; the orphaned *dependent* row diverts to its own `<entity>__reject`, the referential rule name recorded in `failed_rules` |
| `referential: flag` | same `LEFT JOIN` probe; the referential rule name lands in `_quality_flags` (the single flag-construct pass) |
| `reconcile` | separate model + non-blocking audit |

**The dedupe order is total.** After `field` DESC and the `tie_break` columns, the final
sort key is the stable source-row identity `_source_row_id` (§5.6's ingestion metadata
contract), so the winner is unique by construction — no two rows can compare equal. Null
ordering is pinned: `NULLS LAST` for the recency field and every tie-break column — a null
recency loses to any non-null one.

> **Amended 2026-08-08 (D32):** the `fail` audit reads the **pre-route population**
> (the staged extract), not `@this_model`. Routing is stage 6 and an audit runs after
> the model is built, so an audit over the entity sees only the rows the split *kept* —
> a row failing a blocking rule **and** a quarantine rule landed in the reject table
> with the run carrying on, inverting the severity order this very section pins. Every
> `fail` rule lowers through the same `violation` predicate its other dispositions use;
> the audit body stays inside D29's two-relation scope limit, because `referential` —
> the one kind that reads a sibling — cannot carry `fail` (D6). And `failed_rules` /
> `_quality_flags` both record FAIL-disposition rule names.
>
> **Amended 2026-08-08 (D67):** the row above is **incomplete**. Moving off
> `@this_model` stopped covering the rows *already in the entity* — which is where a
> **replayed** row lands, and a replayed row's bronze source has aged out of the
> incremental window by construction (§5.7). The audit body is therefore the *union*
> of the two populations: the pre-route staged extract (D32's gain) and
> `@this_model`, the latter read through the recorded `_quality_flags` verdict. Two
> relations still, so D29 holds. Replay deliberately does not filter `fail` rules out
> of its MERGE — that would be quarantine outranking fail, which is the inversion
> D32 exists to prevent — so the row lands and the audit stops the next run.

> **Amended 2026-08-08 (D33):** a rule whose violation predicate is a **window
> function** (`unique`, the only one in the v1 catalogue) is computed once as a
> projected column above the dedupe `QUALIFY` and referenced by name from every other
> position. SQL forbids a window in a `WHERE` clause, in an aggregate's argument, and in
> a foreign `QUALIFY` — and the lowering reads a violation predicate from all three, so
> only `unique/flag` produced executable SQL before.

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
`normalize`, `charset`, `expression`, and `referential` alike: a NULL fk is not an orphan — it is `not_null`'s
business. This is also why the referential lowering is the `CASE` above, not Document 5's
bare `COALESCE(fk, '__unknown__')` — that sketch was wrong, mapping a NULL fk to the
unknown member; only a non-null fk with no referenced row is an orphan (correction
recorded, decision 19).

**`unknown_member` requires a string-typed fk in v1.** The reserved member is the
*string* `'__unknown__'` — there is nowhere sound to put it in a non-string key.
Declaring `on_missing: unknown_member` on a non-string fk is a compile-time
`GuardrailError` naming the alternatives: use `quarantine` or `flag`, or map the key to
string. Typed per-key sentinels are explicitly rejected — a sentinel like `-1` colliding
with a legal key value is exactly the silent wrongness this project refuses.

> **Amended 2026-08-08 (D27):** every `referential` lowering above is a `LEFT JOIN`
> *inside the dependent entity's own model*, so a rule whose relationship points back
> at that same entity is unexecutable — a model cannot join the table it is being
> built from. Declaring one is a compile-time `GuardrailError` naming the two
> alternatives: model the referenced side as a separate entity built from the same
> source, or express the check as a `reconcile:` block, which runs silver→mart against
> finished tables. Self-referencing *data* (a parent-order fk) is still expressible —
> it is the single-entity *shape* that is refused.

> **Amended 2026-08-08 (D46):** D27's check compared only the relationship's `to` side,
> which let a rule name a relationship declared *between two other entities* — the join
> then reads `via`'s from-columns off an extract that never projects them. The
> relationship's `from` side must be the declaring entity; `to` must not be.
>
> **Amended 2026-08-08 (D48):** `unknown_member` on a **composite**-key relationship is
> refused too. The rewrite is one `CASE` over one column, so a two-column fk produced a
> half-sentinel key matching no reserved row — and the string-fk check, reading only the
> first `via` column by sort order, missed a non-string second one entirely.
>
> **Amended 2026-08-08 (D45):** a `via` naming no declared relationship is likewise a
> compile-time refusal. Resolution never inspects `entity.quality`, so it used to be a
> raw `KeyError` from the lowering rather than a batched `GuardrailError`.

`QUALIFY` is DuckDB-native; Postgres and any engine without it get the equivalent
`ROW_NUMBER`-in-a-subquery lowering through the shared dialect-neutral AST — one AST,
per-dialect legal rendering, the same doctrine as RFC 0008. Target coverage:
**SQLMesh** emits the full quality set (split models, reject tables, replay merge,
quality mart); **dbt** initially raises `UnsupportedByTarget` for the reject/replay
artifacts (honest port-proof scope); **Cube/MetricFlow** consume the quality mart like
any mart.

> **Amended 2026-08-08 (D30):** dialect coverage is narrower than target coverage.
> The `coercible` lowering needs a real NULL-on-failure cast, which is
> `DialectFeature.TRY_CAST`; Postgres has none (sqlglot renders `TRY_CAST` as a plain
> `CAST`, which aborts the run instead of marking the row), so **Postgres cannot host
> a quality-carrying entity at all** — compiling one raises `UnsupportedByTarget`.
> DuckDB and Trino carry the feature. Consequence for §6's dialect matrix: there is no
> Postgres dirty-corpus tier to add until either sqlglot renders a real `TRY_CAST` or
> the lowering grows a `CASE`-based fallback per type. The fallback is named as the
> escape hatch, not built — it is a per-type regex/`CASE` cascade whose semantics must
> be proven equal to `TRY_CAST`'s on the corpus before it is worth the surface.

> **Amended 2026-08-08 (D58):** the sentence above scopes dbt's refusal to the
> reject/replay artifacts; the emitter also refuses a `reconcile:` block, and that
> refusal is authorized here rather than retracted. A reconcile check lowers to a
> model **and** a non-blocking audit (§5.3): dbt lowers neither in this wave, and the
> test surface it does emit (`schema.yml` data tests) blocks the build on failure, so
> mapping the audit onto one would turn "report the disagreement" into "fail the
> build" — the silent severity upgrade RFC 0008 D3 forbids. dbt's coverage of the
> quality system therefore reads in full: the flag-only surface (`_quality_flags` is
> the *same* shared SELECT both targets render), and nothing else.

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
  reject_id       STRING,     -- sha256 over the canonical (source_relation, _source_row_id) pair; stable, idempotent replay
  source_relation STRING,     -- the bronze relation identity — with _source_row_id, reject_id is recomputable from the row itself
  mapping         STRING,
  mapping_version INT,
  failed_rules    ARRAY<STRING>,  -- same D23 physical contract as _quality_flags: array under DialectFeature.ARRAY, else the lexicographic comma-delimited string
  key_values      VARIANT,    -- best-effort; null if the key itself failed
  raw             VARIANT,    -- the bronze payload
  _load_id        STRING,     -- attribute, not identity: the latest load observing this row
  _ingested_at    TIMESTAMP,
  _source_row_id  STRING,     -- stable per-source-row identity (ingestion metadata contract)
  first_seen      TIMESTAMP,
  last_seen       TIMESTAMP,
  resolved_at     TIMESTAMP,  -- set on successful replay; never deleted by replay
  last_evaluated_at TIMESTAMP -- when replay last read this row; read by nothing (D88)
)
```

**Ingestion metadata contract.** Entities using `quarantine` or `dedupe` require the bronze
ingestion metadata columns `_load_id`, `_ingested_at`, and `_source_row_id` — a stable
per-source-row identity supplied by the ingestion layer, **NOT NULL and unique per source
row**. Column absence is the compile error `IngestionMetadataMissing`, a `GuardrailError`
leaf declared in `errors.py` per RFC 0002 D3 (§5.9); the NOT NULL/uniqueness properties are
data facts no compiler can check, so the lowering emits a generated **blocking audit** on
the metadata columns — a null or duplicated `_source_row_id` stops the run rather than
silently corrupting dedupe order or `reject_id`. `reject_id` is the sha256 over the
**length-prefixed utf-8 pair** (`source_relation`, `_source_row_id`) — canonical
serialization per the RFC 0003 canon-bytes doctrine. `_load_id` is deliberately **not**
part of the identity — this supersedes the triple this RFC itself first proposed (D21):
re-deliveries of the same source row across loads must land on the **same** reject row,
which is precisely what `first_seen`/`last_seen` exist to track; a per-load identity
would mint a new reject row per retry and violate replay idempotence. A re-delivery
updates `last_seen`, `_load_id`, and `failed_rules` on the existing row; `_load_id`
remains as an attribute recording the latest observing load.

> **Amended 2026-08-08 (D36):** `first_seen`/`last_seen` are both written as the row's
> `_ingested_at`; what separates them is the **merge**. The reject model declares a
> `when_matched` clause keeping the existing `first_seen` while every other column takes
> the arriving value. They were a `MIN`/`MAX` window over `PARTITION BY _source_row_id`,
> which is a singleton by construction (D21 makes the identity unique, and dedupe has
> already run) — so both were the identity and `first_seen` tracked the newest delivery.
> Replay also gained the statement §5.6's sentence always required: a third MERGE
> re-stamping `failed_rules`/`last_seen` on the rows that still fail, from the very same
> evaluation the candidates come from.

> **Amended 2026-08-08 (D69):** the third MERGE re-derives `failed_rules` for every
> still-unresolved row, and for a candidate that now **passes everything** and merely
> lost its entity key the honest re-derivation is *empty* — `resolved_at IS NULL,
> failed_rules = []`, "quarantined for these reasons: none". Such a row now carries
> the reserved entry `(superseded)`, recorded exactly when it passes routing; read
> with the statement's own `resolved_at IS NULL` filter that says "admitted by every
> rule and still not in the entity, because another row won its key". It stays
> unresolved: a superseded reject is the replay-side analogue of a deduped row.
>
> **Amended 2026-08-08 (D70):** `last_seen` is the **latest delivery's
> `_ingested_at`** and nothing else. The third MERGE used to advance it to the
> engine's `CURRENT_TIMESTAMP`, which put two clocks in one column and — since
> retention measures unresolved rows *from* `last_seen` — made an unresolved reject
> immortal for as long as replay kept running. The re-evaluation is recorded by
> `failed_rules`, which is the clause this section names first; the sentence below
> about `last_seen` updating on re-evaluation is superseded.
>
> **Amended 2026-08-10 (D88):** the escape hatch D70 named is built.
> `last_evaluated_at` is the **engine's** clock — when replay last read this row —
> stamped on *both* replay branches, so it is true for a resolved row as well as for
> one that still fails. It is safe to advance for exactly one reason, and the reason is
> the whole design: **retention never reads it.** Unresolved rows still age from
> `last_seen`, resolved ones from `resolved_at`. The reject model projects it NULL,
> because a model query may not read a clock without breaking §6's gates, which also
> makes it the second column (beside `first_seen`) that a re-delivery's `when_matched`
> must **preserve** rather than overwrite — otherwise a row forgets it was ever
> replayed because the source delivered it again.

> **Amended 2026-08-08 (D37):** D22's "multiple rejects resolving to one key are ordered
> the same way" is applied to the **replay source**, not only to the candidate-versus-
> incumbent comparison inside the MERGE. Two reject rows on one entity key both matched
> the `ON` clause and both merged, leaving the entity holding two rows at a grain it
> declares as one; the `MERGE`'s `WHEN MATCHED` cannot arbitrate that, because it never
> compares candidate against candidate.

`raw` holds source payloads — quarantine tables hold PII. When any rule carries a
`quarantine` disposition, the entity **must** declare a `quarantine:` block with
`retention:`; absence is a compile error (`QuarantineRetentionMissing`), not a default — "this is the sort of thing
that is trivial now and a legal problem in eighteen months." Optional `redact:`
JSONPath list applies to `raw` — and identically to `key_values` — at **write** time.
Redaction and replay can contradict each other, so the compiler arbitrates: `redact:`
paths must not intersect any path the entity's mappings read (`from` paths, recipe
aliases included) — you cannot both require a field and destroy it at write time. An
intersecting redact is the compile error `RedactionConflict` (a `GuardrailError` leaf in
`errors.py` per RFC 0002 D3; §5.9), naming both sides; the author chooses: stop mapping
the field, or don't redact it.
`retention:` governs the whole reject row, and it deletes **all** reject rows on
expiry — unresolved rows measured from `last_seen`, resolved rows from `resolved_at`.
"Never deleted by replay" means exactly that *replay* never deletes: retention is the
only deleter, and resolved rows do not accrete into indefinite PII retention. Replay
re-runs the current mapping
against `raw` for unresolved rows, merging passers into the entity by key and
updating `failed_rules`/`last_seen` on the rest. **Replay merges by the same dedupe
ordering as the pipeline**: a replayed candidate wins or loses against an incumbent row by
the dedupe total order (recency field, tie-breaks, `_source_row_id`), and multiple rejects
resolving to one entity key are ordered the same way. The per-entity replay batch is one
atomic MERGE — transactionality belongs to the executing engine; bloomery emits the
artifact. Idempotence follows from the total order and is defined over **semantic
state** — winners merged, `resolved_at` transitions — excluding the observability
columns: re-running replay re-derives identical merges and resolves nothing new;
`last_seen` updates only when a row is actually re-evaluated, which is an event worth
recording, not an idempotence violation. A replayed row lives in the entity from then on; its reject row is
retained purely as audit history — `resolved_at` set, never deleted by replay
(retention still applies, measured from `resolved_at`; above) — and drops out of
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

> **Amended 2026-08-08 (D51):** "**both** directions" is only true if the diff reads the
> disposition the author *wrote*. `referential`'s `unknown_member` routes like `flag`,
> so collapsing it made `unknown_member ⇄ flag` produce no change at all — while the
> emitted SQL gains or loses its `'__unknown__'` CASE and every stored fk restates.
>
> **Amended 2026-08-08 (D52):** the paragraph's own "not just a backfill" cuts both
> ways: `replay_scope` names an entity only where quarantined rows can actually come
> back — the rule removed, its disposition now `flag`, or its parameters relaxed. A
> tightening (a narrowed bound, `quarantine → fail`) backfills and does **not** replay.

### 5.8 The quality mart

Every rule evaluation emits a row into `gold.mart_data_quality(entity, mapping, rule,
disposition, rows_evaluated, rows_failed, rows_quarantined, rows_deduped, run_id,
run_date)` — an **ordinary semantic model** (`run_date` is its time dimension per
RFC 0010 D9: measure-carrying marts declare a date role; `MartMissingTimeDimension`,
RFC 0013 D3), so quarantine rate is a plain `MetricRequest`, and a rising rate is
a *semantic* drift signal structural detection misses (prices arriving in cents
change no schema). Reject tables are **not** exposed through `MetricRequest` — raw
payloads, different retention; a separate, deliberately narrow operator surface.
> **Amended 2026-08-08 (D34):** the schema is flat, its counts are **not one grain**.
> `rows_failed` is a fact about a rule; `rows_evaluated`, `rows_quarantined` and
> `rows_deduped` are facts about the entity's population. Repeating the latter on every
> rule row fans them out — `SUM(rows_evaluated)` returned the population times the rule
> count, and the quarantine rate was wrong by that factor *and* again in its numerator
> (a row tripping two quarantine rules is one diverted row). Each entity therefore emits
> one **accounting row** carrying the population counts, under the reserved
> `rule`/`disposition` value `(entity)` — parenthesised so no D23-conformant authored
> name can collide — and rule rows carry zero in those columns. Every measure is then
> additive at every group-by, which is the only reading under which "a plain
> `MetricRequest`" holds. The price, recorded: `rows_evaluated` cannot be sliced by
> rule, because it was never a per-rule number.

> **Amended 2026-08-08 (D68):** every count is `COALESCE(SUM(…), 0)`. `SUM` over an
> **empty** partition is NULL, not 0, so an entity with rules whose source delivered
> nothing this run published mart rows whose every measure was NULL —
> `rows_quarantined`, the numerator D34 exists to make correct, among them. A NULL
> measure does not read as a small number: it drops out of the `SUM` behind the
> quarantine rate, which then answers over a population smaller than it names.

> **Amended 2026-08-08 (D35):** `rows_deduped` is `bronze − the rows that survived the
> dedupe QUALIFY`, both measured over this run — never the residual
> `bronze − (entity + unresolved rejects)`. The entity is rebuilt in full while the
> reject table is `INCREMENTAL_BY_UNIQUE_KEY` and accumulates, so the residual form went
> **negative** as soon as bronze's window moved past a still-unresolved reject. A count
> that can be negative is not a count.

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
(§5.3), `DedupeDispositionConflict` (§5.4), `IngestionMetadataMissing` (§5.6),
`RedactionConflict` (§5.6) — are guardrails by this table's
definition: `GuardrailError` leaves declared in `errors.py` per RFC 0002 D3.

## 6. Tests (RFC 0009 amendment)

- **Dirty-data corpus** — `tests/fixtures/dirty/` (numerics, dates, enums, keys,
  refs, unicode, extremes), grown from redacted production incidents: every incident
  adds a row; the regression suite that makes cleansing changes safe.

  > **Amended 2026-08-08 (D26, D28):** two families depart from "every row is
  > asserted", both recorded rather than hidden. `unicode.csv`'s `flag` marks encode
  > "contains an invisible or deceptive character", which no v1 rule expresses — the
  > portable regex subset (D5) forbids exactly the codepoint-class constructs that
  > separating NFC from NFD from emoji would need. That family asserts the class
  > invariant §5.1 actually promises (**flagged, never dropped**) plus whatever a
  > declared rule decides; expressing the rest needs a future `normalize`/`confusables`
  > rule, demand-gated, not built (D26). And no corpus row casts cleanly and *then*
  > violates a declared bound, so `range` fires on nothing — closing that needs a
  > castable-but-out-of-bounds specimen, and the suite asserts the absence rather than
  > hiding it (D28).
  >
  > **Amended 2026-08-10 (D85):** the `range` half is closed. `keys.csv` carries the
  > adjacent pair `amount_at_range_min` / `amount_below_range_min` — one ulp apart,
  > opposite dispositions — so the rule now diverts a row in the corpus *and* the
  > inclusive edge of the bound is pinned. One departure remains, the `unicode` one.
  >
  > **Amended 2026-08-10 (D86):** and then that one too, down to **two rows**. The
  > `normalize` and `charset` rules decide twenty of `unicode.csv`'s twenty-two
  > specimens, so the family is now asserted row by row like every other. The two
  > exceptions are named and argued for in the suite rather than skipped in bulk:
  > `zero_width_joiner` (U+200D is required by `emoji_zwj_sequence` and forbidden here —
  > same codepoint, opposite verdicts, and what separates them is context) and
  > `combining_mark_alone` (a well-formed, NFC-stable value holding no forbidden
  > character; what is wrong with it is *where* the mark sits). No rule that tests
  > membership or normal form can reach either.
  >
  > **Amended 2026-08-08 (D65):** the corpus states *values*; a disposition is stated by
  > the **policy** that judges them, and one entity states one policy per rule.
  > `refs.csv` is therefore judged twice — `dirty_ref` under the documented default
  > (`unknown_member`) and `dirty_ref_routed` under `quarantine`/`flag`, which also
  > carries the corpus's only `on_fail: fail` rule. Without the second entity the corpus,
  > and so the chaos battery built on it, had no specimen for D18's precedence or for any
  > blocking path at all.
- **Unit** — the rule × disposition lowering matrix, covered **exhaustively** via
  `product(ALL_RULES, ALL_DISPOSITIONS)`: a missing pair is exactly the gap that ships.
  `referential` contributes its own axis — one row per `on_missing` disposition
  (`unknown_member`, `quarantine`, `flag`), each asserting its §5.4 lowering.

  > **Amended 2026-08-08 (D63):** "covered" means **executed in the position that
  > disposition puts the verdict in** — the flag construct, the routing `WHERE` and the
  > conservation aggregate, the blocking audit body — not rendered and re-parsed. The
  > shipped matrix asserted `parse_one(f"SELECT 1 WHERE {rendered}") is not None`, which
  > `product` made look exhaustive while `violation()` ignored `on_fail` entirely, and
  > which `parse_one` satisfied for a window-in-`WHERE` — the exact artifact D33 fixed.
  > `referential` at `fail` is the one unrepresentable cell (D6) and is asserted as a
  > parse refusal.
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

  > **Amended 2026-08-08 (D29):** the emitted per-entity audit reads exactly two
  > relations — the bronze source and `@this_model` — because SQLMesh does not rewrite
  > model references inside an `AUDIT` body, so a body naming a sibling silver entity
  > would resolve against whatever that name means outside the plan. It is therefore
  > **skipped** for the one shape an audit body cannot express: `referential` with
  > `on_missing: quarantine`, whose routing predicate reads a sibling entity. The skip
  > is asserted in a unit test rather than silently dropped, and the conservation
  > *property* still covers that shape.
  >
  > **Amended 2026-08-08 (D61):** the emitted audit asserts **one** leg, not two. Its
  > second disjunct, `surviving_rows > bronze_rows`, compared a CTE against the very
  > relation that CTE filters and so could never fire — coverage in appearance only.
  > `bronze_rows` remains a projected column so a reported violation is legible; the
  > deduped leg is carried by the property tier and by the mart's `rows_deduped` (D35).
- **Merge gates** — idempotence and backfill equivalence (full refresh ≡ incremental
  history): the executable determinism invariant; catches nondeterministic tie-breaks
  and order-dependent rules.
- **Replay** — enum widening: `plan()` reports `replay_scope`, replay drains the
  reject table, and a second replay re-derives identical semantic state — the test
  asserts semantic-state equality (winners, `resolved_at`), observability timestamps
  excluded (§5.6).

  > **Amended 2026-08-08 (D49):** "enum widening" has **two** shapes and the tier
  > asserted only one. Adding an `enum_map` target changes a rule param; adding a new
  > *spelling* for an existing target does not, yet admits raw values the narrow spec
  > quarantined just the same. The second shape reported `replay_scope = ()` while rows
  > sat in the reject table, and no test said so. Both shapes are now asserted, and the
  > rule's params carry the chain's spellings beside its targets.
- **Dialect matrix emphasis** — cleansing is where dialects diverge most (regex
  flavours, `ROW_NUMBER` null ordering, decimal rounding, array construction,
  empty-string-vs-null); tier 5 runs the execution assertions per engine.

  > **Amended 2026-08-08 (D30):** the matrix has one engine for cleansing, not three.
  > Postgres lacks `DialectFeature.TRY_CAST` and so cannot host a quality-carrying
  > entity at all, and the Trino engine tier is RFC 0009's outstanding work — the
  > dirty-corpus tier runs on DuckDB, and the two flag lowerings' set-equality (D23)
  > is asserted at the unit/golden level instead.
- **Quarterly chaos meta-test** — mutate the lowering (invert a comparison, drop a
  stage, swap a disposition); at least one test must fail per mutation, or the dirty
  corpus has a hole.

  > **Amended 2026-08-08 (D64):** the battery a mutation must get past is **every**
  > quality suite, not a subset of them. `test_quality_precedence` was outside it for a
  > wave, and it is the only module that reads a *mart* — so a mutation to
  > `has_quality_flags` survived the whole battery while a golden caught it, which is
  > precisely the detection §12's budgeted golden churn cannot be relied on for. The
  > mutation list gains `quality_flags_polarity`.

## 7. Docs

A concept page on the disposition model (stating plainly why `drop` does not exist);
reference pages for the rule catalogue and `quarantine:` block; the
`assert:`-vs-`quality:` boundary ("alert me" vs "act on the row") and the §5.9 table.
§5.6's PII framing is worded as an obligation, not an option.

## 8. Out of scope

- ~~**Repair**~~ — landed in D87; RFC 0017's step registry supplied the recipe
  contract it was gated on.
- ~~**Mart-level quality rules**~~ — landed as mart **assertions** (D89), not as quality
  rules: a mart row has no source identity, so no disposition applies to it.
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

- ~~**Repair**~~ (deferred 2026-08-08 — decision 17; **settled 2026-08-10, D87**): the
  recipe is a registered Tier 1 `sql_macro`, which answers *inline vs catalog-referenced*
  in favour of referenced. The review constraint (credit: cubic) is met by
  `_quality_repairs`, a column distinct from `_quality_flags`, so `has_quality_flags`
  keeps meaning "currently suspect" and a repaired row is simply clean. Still open, and
  deliberately: repairs are visible in silver and **not** in `gold.mart_data_quality`,
  which has no `rows_repaired` measure — adding one changes the mart schema, and no
  demand has asked for it yet.
- ~~**A `normalize`/`confusables` rule**~~ (added 2026-08-08, D26; **settled 2026-08-10,
  D86**): built as `normalize` + `charset`. The confusables *table* was deliberately not
  built — versioned Unicode data would make a row's disposition depend on the compiler's
  Unicode revision — and `charset`'s allow-list reading covers the homoglyph case more
  completely than a denylist could. Two `unicode.csv` rows remain undecidable and are
  named in the suite: a zero-width joiner (legitimate inside an emoji sequence, not
  outside one — a fact about *context*) and a combining mark with no base (a fact about
  *position*). Neither is a gap a bigger character set would close; both would need a
  rule that reads a value's structure rather than its members.
- ~~Mart-level rules ("no month has zero revenue") — reconcile-shaped or new surface?~~
  (**settled 2026-08-10, D89**): **neither.** A `reconcile` compares two sides and a
  quality rule disposes of a row; this does neither. `assert:` on a mart declares an
  aggregate bound, optionally grouped, and lowers to an audit on the mart model. Still
  open, and narrower than the original question: an assertion sees only the groups that
  **exist**, so a month with no rows at all is invisible to it unless the aggregate is
  `count`. Detecting an absent period needs a join against the date spine — a coverage
  check with a different dependency, demand-gated like everything else here.
- Sampling for `pattern` on huge partitions — **lean no**: a probabilistic result in
  an otherwise exact system (for `unique` it is rejected outright — D5, Document 5
  §11.3).
- ~~Cross-entity rules ("every customer has ≥1 order") — probably reconcile-style.~~
  (**settled 2026-08-10, D90**): **not** reconcile-style. A `reconcile` compares two
  *values*; this asserts *existence*, and there is no right-hand value on the referenced
  entity to compare against. It is a `coverage:` check on a declared relationship,
  lowering to an audit on the **dependent** side. Still open and narrower: the check
  counts rows that exist, so it says nothing about a referenced row that was itself
  quarantined — a customer held back by its own rules looks absent to it, which is
  correct for "has an order" and would be wrong for a check phrased "exists".
- Step output concurrency — settled in RFC 0017 (two steps, one output: compile error).

## 11. Decisions

| # | Decision |
| --- | --- |
| 1 | The governing principle: **specs describe, specs reference implementations, specs never contain implementations.** Bronze gets no cleansing (replay source); gold gets none (rebuildable). |
| 2 | `OnFail = flag \| quarantine \| fail` (v1 — `repair` deferred, decision 17; landed in D87), explicit per rule, never a global default. Deliberately no `drop`: quarantine is drop plus recoverability; deletion happens via retention policy, with a paper trail. |
| 3 | Coercion failure is a rule: transform chains lower to failure-marker form (`TRY_CAST`-style per dialect); the implicit, overridable `coercible` rule (default `quarantine`) disposes of it. Retires `Mapping.on_unmapped_enum` (RFC 0002 amendment — absorbed into `in_enum`/`coercible`) and supersedes RFC 0008 D7's never-implemented emitter convention with the modeled reject table. |
| 4 | `assert:` clauses (RFC 0006 D8) remain as compile-to-audit, non-row-routing checks ("alert me"); `quality:` rules are the row-disposition system ("act on the row"). A field may carry both; docs state when to use which. |
| 5 | Closed field-rule catalogue: `coercible`, `not_null`, `range`, `length`, `pattern` (portable regex subset, compile-time validated per target dialect via sqlglot), `in_enum`, `in_set`, `normalize` and `charset` (added by D86, which closed D26), `unique` (evaluated per partition slice in both full and incremental modes — the partition is the scope unit either way; cross-partition duplicates out of scope in every mode, dedupe's job; sampling rejected per Document 5 §11.3). New rules are RFC amendments, not config. |
| 6 | Entity-level `dedupe` requires `tie_break` under `keep: latest_by` (nondeterministic winners violate the core invariant); dedupe-referenced fields' `coercible` is forced to `fail`. Row rules `expression` and `referential` (`on_missing ∈ {unknown_member, quarantine, flag}` — `fail` deliberately excluded: orphans are an expected, recoverable data condition; a pipeline-stopping orphan gate is a `reconcile` check; `unknown_member` keeps aggregates correct via a reserved member row and requires a string-typed fk in v1 — the reserved member is the string `'__unknown__'`; a non-string fk with `unknown_member` is a compile-time `GuardrailError` naming the alternatives, typed per-key sentinels rejected); `reconcile` blocks emit model + non-blocking audit. |
| 7 | Fixed pipeline order — extract → transform → dedupe → field rules → row rules → route — never configurable. Dedupe before rules: validating first silently replaces a corrupt latest row with a stale clean one — data loss disguised as data quality. |
| 8 | Lowering per §5.4's table: `QUALIFY ROW_NUMBER` dedupe over the pinned total order, all flag rules in one `_quality_flags` array pass, two-way entity/reject split, blocking audit for `fail`. |
| 9 | Silver gains `_quality_flags`/`_quality_ok`; marts gain `has_quality_flags` (RFC 0010 amendment). Array capability is `DialectFeature.ARRAY` — an engine property, deliberately diverging from Document 5's `TargetCapabilities` placement; dialects without it lower to a delimited string. |
| 10 | One `<entity>__reject` table per entity with the §5.6 schema (stable sha256 `reject_id` for idempotent replay). Retention is **required** whenever any quarantine disposition exists — missing retention is a compile error; retention deletes **all** reject rows on expiry (unresolved measured from `last_seen`, resolved from `resolved_at`) and is the only deleter — replay never deletes. `redact:` paths apply at write time and must not intersect any path the entity's mappings read (`from` paths, recipe aliases included) — an intersecting redact is the compile error `RedactionConflict`. Bloomery emits the reject/replay artifacts and never executes them. |
| 11 | RFC 0007 amendment (dated when implemented): quality rule add/remove/change, disposition changes in both directions, and dedupe changes classify `RESTATING`; `Plan` gains `replay_scope` alongside `backfill_scope` — `quarantine → flag` needs replay, not just backfill. |
| 12 | `gold.mart_data_quality` is an ordinary semantic model (`run_date` as time dimension); quarantine rate is a `MetricRequest`. Reject tables are never exposed through `MetricRequest`. Deliberate divergence: no `tenant_id` column (Document 5 §7.5 has one) — hard invariant #3 and the tenant guard forbid it; `NamingPolicy` namespaces are the only tenant seam. |
| 13 | The guardrail boundary (§5.9) is normative: guardrail = the model is wrong, compile time; quality rule = the data is wrong, run time. Nothing decidable from the spec alone enters `quality/`. |
| 14 | Testing per §6 (RFC 0009 amendment): dirty corpus, exhaustive rule×disposition matrix, quarantine-contents assertions, the conservation-law property doubled as a runtime audit, idempotence + backfill-equivalence merge gates, replay tests, dialect-matrix emphasis, quarterly chaos meta-test. |
| 15 | A mart's `base` must be a silver entity, never a reject table — a mart over `<entity>__reject` is a compile error. Mart rowcounts legitimately differ from bronze (quarantined rows never reach marts); the conservation audit is what makes the difference explainable. |
| 16 | New compile errors: `QuarantineRetentionMissing` (quarantine disposition without `retention:`), `DedupeTieBreakMissing` (`keep: latest_by` without `tie_break`), `DedupeDispositionConflict` (user-declared weaker disposition on a dedupe-referenced field where `coercible` is forced to `fail`) — all `GuardrailError` leaves declared in `errors.py` per RFC 0002 D3. |
| 17 | *(closed by D87)* **Repair deferred out of v1** (amends rows 2 and 8 as originally drafted): dispositions v1 = `flag \| quarantine \| fail`; `repair` moves to §10, demand-gated on a repair-recipe contract. Constraint recorded from review (credit: cubic): when repair lands it must carry a **distinct marker** separating "repaired, now correct" from "currently flagged bad", so `has_quality_flags` keeps meaning "currently suspect". |
| 18 | Disposition precedence for a row failing multiple rules — severity order `fail > quarantine > flag`: any failing `fail` rule stops the run (blocking audit); else any failing `quarantine` rule diverts the row, with **all** failed rule names recorded in the reject's `failed_rules` (flag-level failures included); else flags accumulate in `_quality_flags`. Deterministic for every combination — no compile-time rejection of rule/disposition combinations needed. |
| 19 | Three-valued logic: each rule defines a violation predicate and fires only when it is definitively TRUE — NULL-involved comparisons evaluating to SQL `UNKNOWN` do **not** fire (`not_null`/`coercible` own nulls; declare them if nulls are invalid). Applies to `range`/`length`/`pattern`/`in_enum`/`in_set`/`expression`/`referential` — a NULL fk is not an orphan. Corrects Document 5's referential lowering: the bare `COALESCE(fk, '__unknown__')` sketch was wrong (it maps a NULL fk to the unknown member); the lowering is `CASE WHEN ref.<pk> IS NULL AND fk IS NOT NULL THEN '__unknown__' ELSE fk END`. |
| 20 | Dedupe is a total order: after `field` DESC and the `tie_break` columns, the final sort key is the stable source-row identity `_source_row_id` — the winner is unique by construction *given the metadata contract* (D21): `_source_row_id` is declared **NOT NULL and unique per source row**, an ingestion-layer obligation enforced at run time by a generated blocking audit on the metadata columns (a data property, not compile-checkable). Null ordering pinned: `NULLS LAST` on **every** sort key including `_source_row_id` (defense in depth — DESC defaults to NULLS FIRST on several engines, so an illegally-null identity must still lose, never win). |
| 21 | Ingestion metadata contract: entities using `quarantine` or `dedupe` require bronze `_load_id`, `_ingested_at`, `_source_row_id` (a stable per-source-row identity supplied by the ingestion layer, **NOT NULL and unique per source row** — data properties no compiler can check, so the lowering emits a generated **blocking audit** on the metadata columns: a null or duplicated `_source_row_id` stops the run); column absence is the new compile error `IngestionMetadataMissing` (`GuardrailError` leaf, `errors.py` per RFC 0002 D3). `reject_id` = sha256 over the length-prefixed utf-8 **pair** (`source_relation`, `_source_row_id`) — canonical serialization per the RFC 0003 canon-bytes doctrine. This supersedes the triple this row first carried (this round's own earlier decision): `_load_id` is removed from the identity and becomes an attribute (the latest observing load) — re-deliveries of the same source row across loads must land on the **same** reject row (that is what `first_seen`/`last_seen` track); a per-load identity would mint a new row per retry and violate replay idempotence. A re-delivery updates `last_seen`/`_load_id`/`failed_rules` on the existing row. |
| 22 | Replay merge semantics: replay applies the **same dedupe ordering** as the pipeline — a replayed candidate merges by entity key and wins/loses against an incumbent by the dedupe total order (recency, tie-breaks, `_source_row_id`); multiple rejects resolving to one key are ordered the same way. The per-entity replay batch is one atomic MERGE (transactionality is the executing engine's; bloomery emits the artifact); idempotence follows from the total order — re-running replay re-derives the same winners — and is defined over **semantic state** (winners merged, `resolved_at` transitions), observability columns excluded: `last_seen` updates only when a row is actually re-evaluated. |
| 23 | `_quality_flags` **and** `failed_rules` share one physical contract: rule names identifier-constrained at parse (no escaping in any lowering); the column is never NULL (empty array / empty delimited string per `DialectFeature.ARRAY`); delimited fallback joins with `,` in lexicographic rule-name order; `_quality_ok` generated per shape; flag-set equality across lowerings asserted in the dialect-matrix tier. The reject table's `failed_rules` lowers by exactly this contract — array where `DialectFeature.ARRAY`, else the lexicographic comma-delimited string. |
| 24 | *(2026-08-08, M12)* **The implicit `coercible` rule is opt-in per entity**, diverging from §5.2's "implicit, always present". An entity joins the quality system by declaring `quality:`, `quarantine:`, or any field-level `quality:`; `dedupe:` alone does not. Rationale: applying it universally gives every field in every existing project a `quarantine` disposition, which makes every project fail `QuarantineRetentionMissing` on its next compile — a break §12 budgets for `_quality_flags`'s schema churn but not for a hard compile refusal. Consequence: a project that wants coercion routing must opt in explicitly, and an entity with no quality surface keeps the shipped produce-or-raise transform lowering. |
| 25 | *(2026-08-08, M12)* **The ingestion-metadata columns carry no `coercible` rule, and the D21 audit must close the gap.** D6 forces `coercible` to `fail` on any field the dedupe order reads, but `_ingested_at`/`_load_id`/`_source_row_id` are ingestion metadata, not mapped fields — no rule is generated for them, and the D21 blocking audit asserts only that `_source_row_id` is non-null and unique. An uncastable `_ingested_at` therefore survives with dedupe ordering silently undefined. **Decided contract:** the D21 audit additionally asserts `_ingested_at` is castable to timestamp, blocking the run when it is not. Unimplemented as of M12 and held open by a strict-`xfail` execution test (`keys.csv::uncastable_ingested_at`) rather than a comment. |
| 26 | *(2026-08-08, M12; closed by D86)* **`unicode.csv`'s flag expectations are not expressible in v1.** They encode "contains an invisible or deceptive character"; the portable regex subset (D5) has no lookaround, no named groups and no property classes, so it cannot separate NFC from NFD, a homoglyph from its Latin twin, or an astral emoji from a ZWJ sequence. The corpus rows are asserted for the class invariant the disposition model actually promises — **flagged, never dropped** (D2) — plus whatever a declared rule (`length`, `pattern`) decides. Expressing the rest needs a new rule shape: a `normalize`/`confusables` rule taking a Unicode normal form and/or a confusables table, evaluated outside the regex engine. Demand-gated, not built — new rules are RFC amendments, not config (D5). |
| 27 | *(2026-08-08, M12)* **`referential` on a self-relationship is refused at compile time.** The lowering is a `LEFT JOIN` inside the dependent entity's own model (§5.4), so a rule whose relationship's `to` side is the declaring entity is unexecutable — a model cannot join the table it is being built from, and the emitted SQL would either fail or resolve against a stale previous version and answer the wrong question. It is a `GuardrailError` (bare, per §5.9's five-named-leaves rule) naming both alternatives: model the referenced side as a separate entity built from the same source, or express the check as a `reconcile:` block, which runs silver→mart against finished tables. Self-referencing *data* stays expressible; the single-entity *shape* does not. |
| 28 | *(2026-08-08, M12; closed by D85)* **The corpus has no `range` specimen** — a recorded gap, not a rule defect. Every out-of-bounds row it carries is also uncastable, so `coercible` reaches the value first and `range` evaluates over the resulting NULL, staying `UNKNOWN` and never firing (D19). Closing it needs a row that casts cleanly and *then* violates a declared bound. The suite asserts the absence explicitly (zero rows failed, zero diverted) rather than leaving a rule that silently covers nothing, so the day a specimen lands the assertion is what changes. |
| 29 | *(2026-08-08, M12)* **Conservation audit shape.** The emitted per-entity audit reads exactly two relations — the bronze source and `@this_model` — because SQLMesh does not rewrite model references inside an `AUDIT` body, so a body naming a sibling silver entity would resolve against whatever that name means outside the plan. It is therefore **skipped** for the one shape an audit body cannot express: `referential` with `on_missing: quarantine`, whose routing predicate reads a sibling entity. The skip is asserted in a unit test rather than silently dropped, and §6's conservation *property* still covers that shape. |
| 30 | *(2026-08-08, M12; closed by D84)* **Postgres cannot host quality-carrying entities.** `coercible` needs a real NULL-on-failure cast (`DialectFeature.TRY_CAST`); sqlglot renders `TRY_CAST` on Postgres as a plain `CAST`, which aborts the run instead of marking the row, so the dialect declares the feature gap and compiling a quality-carrying entity for it raises `UnsupportedByTarget` — loud, never a silent degradation into an aborted run. Consequence for §6's dialect matrix: there is no Postgres dirty-corpus tier to add until either sqlglot renders a real `TRY_CAST` or the lowering grows a per-type `CASE`-based fallback whose semantics are proven equal to `TRY_CAST`'s on the corpus. Named as the escape hatch, not built. |
| 31 | *(2026-08-08, M12)* **D25's contract is implemented; the strict `xfail` is closed.** The D21 blocking audit now reports a third condition beside the null and duplicate `_source_row_id` checks: `_ingested_at IS NOT NULL AND TRY_CAST(_ingested_at AS TIMESTAMP) IS NULL` — *present but uncastable*, built as a SQLGlot AST through the dialect port like every other term of the audit. `keys.csv::uncastable_ingested_at` (`key_018`) is now an ordinary passing execution assertion, paired with a non-trigger probe of two rows differing only in whether `_ingested_at` parses, so the check cannot go vacuous. Consequence for D30: the metadata audit needs `DialectFeature.TRY_CAST` **independently** of any `coercible` rule, and under D24 a *dedupe-only* entity carries no rules at all — so the audit lowering restates the refusal instead of relying on the coercible-rule one, and a dedupe-only entity compiled for Postgres is now `UnsupportedByTarget` as well. That is the edge of D30's sentence, reached, not a widening of it. |
| 32 | *(2026-08-08, M12 fix)* **A `fail` rule's audit reads the pre-route population.** Routing is stage 6 and an audit runs after the model is built, so an audit over `@this_model` sees only the rows the split kept — a row failing a `fail` rule *and* a `quarantine` rule was diverted and the run carried on, inverting D18's severity order. The body is a query over the staged extract (the same rows the routing predicate is evaluated over), which stays inside D29's two-relation scope limit because `referential` cannot carry `fail` (D6). Consequences: every kind lowers through the same `violation` predicate (retiring a `coercible`-at-`fail` special case that had silently redefined the rule as `not_null`), and FAIL-disposition rule names are recorded in **both** `failed_rules` and `_quality_flags`, so the quality mart's `rows_failed` is no longer structurally zero for the rules whose firing matters most. |
| 33 | *(2026-08-08, M12 fix)* **A window-valued violation predicate is projected once and referenced by name.** SQL allows a window function only where a projection is being built; the lowering reads a violation predicate from a `WHERE` (routing), an audit body, and an aggregate's argument (the conservation count). `unique` — the only windowed kind in the v1 catalogue (D5) — is therefore computed as a column above the dedupe `QUALIFY` (rules run after dedupe, D7) and read back from there. Before this only `unique/flag` produced executable SQL; the other two dispositions emitted a binder error. `WINDOWED_KINDS` carries the declaration, and a unit test pins it against the predicates themselves so a future rule that grows a window cannot ship unnoticed. |
| 34 | *(2026-08-08, M12 fix)* **The quality mart carries an entity accounting row.** §5.8's schema is flat but its counts are not one grain: `rows_failed` describes a rule, while `rows_evaluated`/`rows_quarantined`/`rows_deduped` describe the entity's population. Repeating the latter per rule fanned them out — `SUM(rows_evaluated)` returned the population times the rule count — and the quarantine rate was wrong by that factor and again in its numerator (two quarantine rules firing on one row divert one row). Each entity emits one row under the reserved `rule`/`disposition` value `(entity)`, parenthesised so no D23-conformant authored name can collide; rule rows carry zero in the population columns. Every measure is additive at every group-by, which is the only reading under which D12's "a plain `MetricRequest`" holds. Recorded price: `rows_evaluated` cannot be sliced by rule, because it was never a per-rule number. A reconcile check is a rule row by the same rule — its own row count is a count of keys, not of the left entity's rows. |
| 35 | *(2026-08-08, M12 fix)* **`rows_deduped` is measured at the dedupe stage, not as a residual.** `bronze − the rows that survived the QUALIFY`, both scalar subqueries over this run. The residual form `bronze − (entity + unresolved rejects)` went negative the moment bronze's incremental window moved past a row still sitting in the reject table, because the entity is rebuilt in full while the reject table accumulates. A count that can be negative is not a count. |
| 36 | *(2026-08-08, M12 fix)* **`first_seen` is preserved by the merge, and replay re-stamps the rows that still fail.** Both timestamps are written as the row's `_ingested_at`; the reject model's `when_matched` clause keeps the existing `first_seen` while every other column takes the arriving value, which is what D21's "a re-delivery updates `last_seen`, `_load_id`, and `failed_rules` on the existing row" actually requires. They had been a `MIN`/`MAX` window over `PARTITION BY _source_row_id` — a singleton partition by construction, so both were the identity and a re-delivery moved `first_seen` forward. §5.6's "updating `failed_rules`/`last_seen` on the rest" gained the statement it never had: a third MERGE in the replay artifact, re-deriving `failed_rules` from the same evaluation the candidates come from and advancing `last_seen`. |
| 37 | *(2026-08-08, M12 fix)* **D22's ordering applies to the replay *source*.** Two unresolved rejects resolving to one entity key both matched the MERGE's `ON` clause and both merged, leaving the entity holding two rows at a declared one-row-per-key grain and doubling every mart measure over it. The `WHEN MATCHED` comparison cannot prevent that — it arbitrates candidate against incumbent, never candidate against candidate — so the dedupe total order is applied to the candidate set first. Its no-`dedupe:` form is the final sort key alone (D20). |
| 38 | *(2026-08-08, M12 fix)* **`reconcile.on_fail` is not a label.** All three values emitted the same non-blocking audit while the quality mart reported `disposition = 'fail'`. `fail` now emits a **blocking** audit — §5.3 nominates reconcile as the pipeline-stopping gate, and that sentence is only true if the value blocks; `flag` stays non-blocking so a disagreement does not withhold the comparison table; `quarantine` lowers non-blocking because a reconcile routes no row, and refusing the value belongs to the spec surface where `on_fail` is typed. |
| 39 | *(2026-08-08, M12 fix)* **Compilation must not depend on whether the target framework is imported.** Importing `sqlmesh` extends SQLGlot globally, including how some node types render, so a lowering that emits one of those nodes makes the artifact bytes a function of the calling process — an RFC 0003 break invisible to every existing guard (the hash-seed pair imports neither framework; the goldens only meet sqlmesh in the e2e lane). The reject model's `when_matched` clause is therefore built from per-assignment renders and envelope text rather than from an `exp.Whens`, and a subprocess guard compares the quality fixtures compiled with and without `sqlmesh` imported. |
| 45 | *(2026-08-08, M12 fix)* **A `referential` rule whose `via` names no relationship is a guardrail refusal.** Resolution (RFC 0005) validates the `relationships:` block itself and never inspects `entity.quality`, so a typo'd `via` reached the lowering's relationship lookup and came out as a raw `KeyError` — not a `BloomeryError`, never batched into the stage's single aggregate (RFC 0002 D3), and naming a compiler internal instead of the typo. The refusal is a bare `GuardrailError` naming both the unknown relationship and the declared ones. Consequence for the lowering: it may not assume the lookup is total, because the guardrail stage runs *after* the draft is built — an unresolvable rule lowers to nothing and the stage refuses before anything is emitted. |
| 46 | *(2026-08-08, M12 fix)* **A `referential` rule's relationship must run *from* the declaring entity.** The lowering reads `via`'s from-columns off *this* entity's extract (§5.4), so a rule naming a relationship declared between two other entities emits a `LEFT JOIN` whose `ON` clause references columns the model never projects — a run-time binder failure from a spec that compiled clean. D27 refused the same class of unexecutable join by comparing only the relationship's `to` side, which let a `cust → cust` self relationship borrowed by an unrelated entity slip past the very check written for it. The check now compares both sides: `from` must be the declaring entity, and `to` must not be (D27, unchanged). |
| 47 | *(2026-08-08, M12 fix)* **`dedupe.field`/`tie_break` must name a column the entity declares.** They lower straight into `ORDER BY <column> DESC NULLS LAST` (§5.4), so a typo compiled clean and failed at run time in the engine's binder — the exact class of failure the guardrail stage exists to move to compile time. Legal targets are the entity's fields and key **plus** the three ingestion-metadata columns (D21): `_ingested_at` is the usual `dedupe.field` and no mapping declares it as a field, so restricting to mapped fields would refuse the documented spelling. |
| 48 | *(2026-08-08, M12 fix)* **`unknown_member` on a composite-key relationship is refused.** §5.4 requires a string-typed fk because the reserved member is the string `'__unknown__'`; the shipped check read only the *first* `via` column by sort order, so a two-column fk with a non-string second column escaped the type refusal entirely, and the rewrite — one `CASE` over one column — produced a half-sentinel key like `('__unknown__', 47)` matching no reserved row. That is worse than either the refusal or the orphan it was meant to tame. Composite `unknown_member` is therefore refused outright, which is also what makes the type check total: an accepted rule has exactly one `via` column and it is checked. `quarantine` and `flag` stay available on composite relationships — they route a row rather than rewriting a key. A typed multi-column sentinel is rejected for D6's reason, one level up. |
| 49 | *(2026-08-08, M12 fix)* **`in_enum`'s rule identity carries the chain's source spellings, not only its `enum_map` targets.** `enum_map` passes an *unmapped* value through untouched, so the raw values `in_enum` admits are the mapped spellings **plus** the targets. A widening therefore has two shapes — a new target, or a new spelling for an existing target (`PAYED → paid`) — and only the first changed a rule param, so `plan()` reported `replay_scope = ()` for the second while rows sat in the reject table on that rule's account. §6's replay test used only the shape that worked, so the gap was untested. The lowering now emits `spelling_NNNN` params beside `value_NNNN`. The pairing is deliberately *not* carried: re-pointing `a → x` to `a → y` when both are already targets changes the column's value — which the column diff reports — but changes nothing about which raw values this rule admits. |
| 50 | *(2026-08-08, M12 fix)* **Generated rule names are collision-free and independent of authored order.** Two facts had to be *made* true. Suffixing appended `_{n}` without checking the result was free, so two `a_range_min` rules and an authored `expression` rule legally named `a_range_min_2` produced two rules under one name — one unreadable `failed_rules` entry and one quality-mart row computing the union of both rules' failures; the suffix now counts up until the candidate is actually unused. And `quality_sort_key` omitted `on_fail`, so two rules differing only in disposition sorted equal, the stable sort fell through to authored order, and swapping two YAML lines compiled the same spec to two different IRs (RFC 0003). `on_fail` joins the key as its last component, breaking only ties nothing else could break. |
| 51 | *(2026-08-08, M12 fix)* **A disposition is diffed as the author wrote it, not as it routes.** `disposition()` answers a routing question and correctly maps `unknown_member` onto `FLAG` — the row is kept either way — but `plan()` asks a different question, and the collapse made `unknown_member ⇄ flag` invisible: zero changes, `has_changes` False, no backfill, while the emitted SQL gains or loses its `'__unknown__'` CASE and every stored fk restates. D11 requires disposition changes classified in **both** directions, so the diff compares the authored label (`on_missing` for `referential`, `on_fail` otherwise). Replay follows D52 from the routing disposition: `unknown_member → quarantine` starts diverting, so there is nothing yet to replay; `quarantine → unknown_member`/`flag` stops diverting, so the diverted rows replay. |
| 52 | *(2026-08-08, M12 fix)* **`replay_scope` names an entity only where quarantined rows can come back.** The shipped rule fired on *any* change to a formerly-quarantining rule, which named the entity for `quarantine → fail` and for a **narrowed** bound — contradicting §5.7's own "a tightening needs a backfill and no replay", and, under `fail`, feeding a replay runner rows that trip the new blocking audit and halt the pipeline. Replay now requires the old disposition to have been `quarantine` **and** one of: the rule is gone; its disposition is now `flag` (`unknown_member` included, D19); or its parameters relaxed. Relaxation is decided from the params where they are ordered (`range`/`length` bounds) or a set (`in_enum`/`in_set` membership, D49's two families together); where they are not — an unorderable `pattern` regex, an `expression` — it is **undecidable**, and the undecidable case reports the replay: a no-op MERGE is cheaper than a row stranded in quarantine, which is what §5.6's "drop plus recoverability" forbids. |
| 53 | *(2026-08-08, M12 fix)* **The portable regex subset is an allowlist, closed by construction.** It had been a seven-prefix denylist plus `re.compile`, which accepts every construct nobody listed — verified on DuckDB: a backreference (`(a)\1`), an atomic group (`(?>abc)`), a possessive quantifier (`a*+`) and `\A\d+\Z` all parsed clean and *aborted the run*, while `[[:alpha:]]` and `(?i)` were accepted with divergent meaning. The scanner now names what it accepts — literals, `.`, character classes with ranges and negation, `\d`/`\w`/`\s` and their negations, the anchors `^`/`$`, the quantifiers `* + ? {n} {n,} {n,m}`, alternation, and non-capturing groups `(?:…)` — and refuses everything else *by name*, including anything unrecognized. Refused with reasons: capturing groups (a rule is a boolean match and captures nothing, and numbered groups are what backreferences read — write `(?:…)`), backreferences, atomic groups, possessive and lazy quantifiers, lookaround, named groups, inline flags, comments and conditionals, POSIX classes/collating elements/equivalence classes (locale-defined on Postgres, fixed on RE2), `\A`/`\Z`/`\b`/`\G`, property and character-code escapes, and `\D`/`\W`/`\S` *inside* a bracket expression (an error in ARE, legal in RE2). Two divergences are accepted and stated rather than pretended away: `.` excludes newline on RE2 and includes it on ARE; `\d`/`\w`/`\s` are ASCII on RE2 and locale-defined on ARE. Loosening a refusal later is backward-compatible; tightening one is not (RFC 0010 §9), so the subset starts small. |
| 54 | *(2026-08-08, M12 fix)* **Anchoring is the author's, enforced at parse.** §5.3 called `pattern` "anchored" and nothing enforced it, so `[0-9]{5}` matched `abc12345xyz` — every SQL regex predicate is a substring match. The alternative was anchoring implicitly at lowering; author-written anchors win because the spec then says what it means (a reader of the YAML sees the whole-value match), because an implicit rewrite would silently change the meaning of a pattern an author deliberately wrote unanchored, and because the refusal is decidable from the spec alone, which puts it at parse (D13). Every **top-level alternative** must carry its own pair — `^a$|^b$`, never `^a|b$` — and `^`/`$` elsewhere (inside a group, mid-alternative) is a refusal, not a silent no-op. |
| 55 | *(2026-08-08, M12 fix)* **`pattern`'s per-dialect check is a surface-and-transport check; it cannot be a semantics check.** §5.3's "compile-time validated against every target dialect via sqlglot" describes something sqlglot cannot do: bloomery never executes SQL (D10), and rendering a `REGEXP_LIKE` then re-parsing it proves only that the *literal* travelled — it returned "expressible" for every construct in D53's abort list, and even for a dialect with no regex operator at all. What the check actually answers, and now says it answers: does the dialect declare `DialectFeature.REGEXP_EXTRACT`, and does SQLGlot resolve the dialect and carry the pattern text into SQL unchanged. The portability claim itself is carried by D53's allowlist — static, stated, and per-flavour (RE2 vs POSIX ARE) — plus the execution tier, which pairs each refused construct with the DuckDB abort that justifies refusing it. |
| 56 | *(2026-08-08, M12 fix)* **The dialects a `pattern` is checked against are the shipped ports, never the registry.** `registered_dialects()` is process-global and mutable, so an extension dialect registered by an unrelated import could decide whether an existing project compiles — the ambient dependency RFC 0003 exists to forbid, and one no golden would catch. The checked set is the constant `PATTERN_TARGET_DIALECTS = (duckdb, postgres, trino)`, overridable by an explicit argument the caller supplies. Recorded consequence: an extension dialect is no longer checked at compile time. Checking it would mean plumbing a dialect set into `build_project_ir`, which is dialect-free by construction and right to be — a project is portable or it is not, and the guardrail stage has no target. Named as the escape hatch, not built. |
| 57 | *(2026-08-08, M12 fix)* **`range` bounds are exact or refused.** `min`/`max` typed `int | Decimal | str` accepted any string: `min: "nan"` emitted `amount < nan` (never TRUE on some engines, always TRUE on others — RFC 0015 D5 refuses the same spelling in filters) and `min: "1e10"` emitted a double literal, which `predicates.py`'s own docstring says cannot happen (RFC 0003 D5 bans floats from every emission path). A `str` bound must now be an exact decimal literal (optional sign, digits, optional fraction — no exponent) or an ISO date/timestamp, which is what the string carrier exists for; anything else, non-finite spellings included, is a `SpecParseError` at parse, where shape and grammar belong (D13). The check is on the *rendered* text, because the IR carries `str(bound)` — that is also what catches a YAML float like `1.0e30` arriving as `Decimal('1E+30')`. |
| 58 | *(2026-08-08, M12 fix)* **dbt's refusal of `reconcile:` is authorized scope, not a widened one.** §5.4's target-coverage sentence granted the dbt emitter one refusal — "the reject/replay artifacts" — and `_refuse_reconcile` shipped a second one under it, which is code contradicting an accepted RFC. The refusal is right and is granted here rather than removed: a reconcile check lowers to a model **and** a *non-blocking* audit (§5.3); dbt lowers neither in this wave, and the test surface it does emit (`schema.yml` data tests) blocks the build on failure, so approximating the audit with one would turn "report the disagreement" into "fail the build" — RFC 0008 D3's silent degradation, in the direction that halts a pipeline over a tolerance the author declared non-fatal. §5.4 carries the matching amendment and the `UnsupportedByTarget` message cites this row, so the scope a compile refuses on is checkable against the decision that grants it. The price, stated: dbt is a strictly smaller target in one more named way, and a project with a `reconcile:` block compiles for `sqlmesh` only. |
| 59 | *(2026-08-08, M12 fix)* **A `redact:` swap is a widening *and* a narrowing, and both are reported.** `_quarantine_changes` computed the two sets and then branched `if widened … elif narrowed`, so `redact: ["$.a"] → ["$.b"]` reported only the destructive half: the caller was told payload is being destroyed and never told that `$.a` — a path the reject table had been scrubbing — is now written into `raw` in the clear. The un-redaction is a PII-governance fact (§5.6) and the one a data-protection reviewer most needs, so the `elif` made the report say *less* the more the author changed in one edit. Independent `if`s now: widening RESTATING (payload destroyed going forward, still no backfill and no replay, since neither restores what the write path removes), narrowing ADDITIVE. |
| 60 | *(2026-08-08, M12 fix)* **The differ reads `mapping_version:` and `unmapped:` — the reject table's own stored schema.** Compiling a fixture twice with each changed moves exactly one artifact, `<entity>__reject` (`1 AS mapping_version` → `2`; a bronze column appearing in `raw`'s `JSON_OBJECT`), while `plan()` returned zero changes both times — a spec edit that restates a stored table and reports nothing. Classified rather than recorded as a blindness, because both readings are forced. `mapping_version` is ADDITIVE: it is a provenance stamp, and a stored reject row still correctly names the version that rejected it (the merge re-stamps only rows it re-observes, beside `last_seen` — D36). The `raw` payload mirrors `redact:` exactly — widened ADDITIVE, narrowed RESTATING with no backfill and no replay, since neither restores a column the write path no longer projects. Two consequences, both deliberate: the payload is compared at **top-level bronze column** granularity, the granularity `raw` is keyed at (`$.a.b` → `$.a.c` is no change, and a path moving between `fields:` and `unmapped:` is no change), so the diff never reports an edit that emits an identical model; and both facts report only where a reject table exists on **both** sides of the change, because without a `quarantine:` block no reject model is emitted and neither field reaches an artifact — D52's "a scope nobody can act on", applied to changes. |

| 61 | *(2026-08-08, M12 fix)* **The conservation audit asserts one leg, because the other could not fail.** The emitted body carried `entity_rows + diverted_rows <> surviving_rows OR surviving_rows > bronze_rows`, the second disjunct standing for "dedupe removes rows, it never invents any". It is a tautology: `_survivors` *is* the bronze relation with the dedupe `QUALIFY` over it, so the two counts are taken over the same rows and one is a filter of the other — no spec, no data and no lowering bug can make it fire. A check that cannot fail is worse than a missing one, because it reads as coverage; a reviewer counting the law's legs finds two and only one is doing anything. The disjunct is removed and `bronze_rows` stays a **projected** column: an audit reports its violating rows, and `deduped = bronze_rows − surviving_rows` is what makes a reported violation legible. §6's third leg is therefore carried by the property tier and by the quality mart's `rows_deduped` (D35), which is where a count that can be wrong actually lives. |
| 62 | *(2026-08-08, M12 fix)* **An `in_set` member's declared type rides in the IR beside its text.** `InSetRule.values` is `tuple[str | int, ...]` and `QualityRuleIR.params` is a sorted tuple of strings (RFC 0003), so `str(value)` erased the distinction and every member rendered as a string literal: `values: [1, 2]` on an integer column emitted `tier NOT IN ('1', '2')`, which DuckDB and Postgres coerce and answer correctly and **Trino refuses outright**. One spec, one engine answering and another failing, is the portability defect §5.3's closed catalogue exists to prevent, and it was invisible because the dirty corpus's `in_set` members are text. Aligned `numeric_NNNN` params now carry each member's declared type, read by the `in_set` builder alone: `in_enum`'s admissible set comes from an `enum_map` chain, which maps text to text, so it is textual by construction and unchanged. The params are emitted **only** when the set actually holds an integer, so an all-string set's IR bytes — and every existing golden — are byte-identical to before. |
| 63 | *(2026-08-08, M12 fix)* **§6's rule × disposition matrix is executed in position, not parsed.** The shipped matrix rendered `violation(rule)` and asserted `parse_one(f"SELECT 1 WHERE {rendered}") is not None`, which failed as a test twice over. The disposition axis was **inert** — `violation()` never reads `on_fail`, so thirty parametrizations carried ten distinct assertions — and the assertion admitted SQL no engine runs: `parse_one` accepts a window function inside a `WHERE` clause, which is exactly the artifact D33 was written to fix. The suite that §6 nominates as the one that catches a missing pair could not have caught the pair that shipped broken. A pair is now built the way the emitter builds it — the windowed verdict projected once, the routing split through the shared `routing_predicate`, the flag collection through `flags_expression` — and **run against DuckDB**, over a two-row specimen per kind so neither a predicate that never fires nor one that always fires can pass. To make that binding rather than a restatement, `verdict()` and `routing_predicate()` move into `quality/predicates.py` and the emitter calls them: a matrix that re-derived the two-line window rule would go on passing through the regression it exists to catch. The one unrepresentable cell, `referential` at `fail` (D6), is asserted as a **parse refusal** — `ReferentialRule` declares no `on_fail` and `SpecModel` forbids unknown keys — so the missing cell is a decision with a test rather than a hole. |
| 64 | *(2026-08-08, M12 fix)* **`has_quality_flags`'s polarity is asserted behaviourally, and the chaos battery contains every quality suite.** Setting the mart dimension to a constant `FALSE` was caught by one thing only: golden byte-comparison. Execution, e2e, property and conservation tiers all stayed green, and §12 budgets golden regeneration by the wave — so an inverted quality dimension could ship inside churn a reviewer was told to expect. Two causes, both fixed. The dimension lives on a **mart**, and no suite in the chaos battery read one; the battery now includes `test_quality_precedence`, which does. And no assertion anywhere read TRUE for a flagged row: the only one that existed read `[("A", False), ("B", False)]` on a fixture where every row a rule fires on is also diverted, so the dimension was constant on live data by construction. The precedence fixture gains a mart over `q_line`, whose one blocking-rule row is kept rather than diverted, and both directions are asserted — through the mart and through the `MetricRequest` §5.5 promises ("revenue excluding flagged rows"). `quality_flags_polarity` joins the §6 mutation list; verified surviving the old five-module battery and killed by the new six-module one. |
| 65 | *(2026-08-08, M12 fix)* **The dirty corpus judges `refs.csv` twice, because a disposition is not a property a corpus can state once.** `on_fail: fail` appeared **zero** times in the corpus and every `referential` rule sat at `on_missing: unknown_member`, so D18's precedence, `referential: quarantine`, `referential: flag` and every blocking path had no specimen — and since the corpus *is* the chaos meta-test's battery, a mutation to any of them was undetectable there however plausible. The fix is a second entity, `dirty_ref_routed`, over the same bronze relation: the same orphans, judged at `quarantine` and at `flag`, plus the corpus's only `on_fail: fail` rule, declared on the one row whose synthesized payload is uncastable so it is **diverted by `coercible` and reported by the blocking audit at once** — D18's severity order and D32's pre-route audit scope, on live data rather than on a synthetic IR. A second entity rather than a second rule on `dirty_ref`, because a rule has one disposition: asserting what `quarantine` does to an orphan means routing that orphan, which the `unknown_member` entity cannot simultaneously be keeping. Recorded consequence: `dirty_ref_routed` routes on a `referential` rule, so it emits **no** conservation audit (D29) — the skip is now a property of a fixture that builds rather than of a hand-made IR. |
| 66 | *(2026-08-08, M12 fix)* **The `unknown_member` rewrite reads its `via` column through an accessor that refuses a composite.** `unknown_member_case` read `indexed_params(rule, "via")[0]` and the emitter's projection rewrite read `params_of(rule)["via_0000"]` — both taking the first column by sort order and ignoring the rest. D48 makes that total for every spec that compiles, but nothing in the code said so, so a future widening of the guardrail would silently reopen the half-sentinel bug D48 was written to close (`('__unknown__', 47)`, matching no reserved row). Both sites now call `sole_via_column`, which raises citing D48 when it sees anything but one column. The invariant is a *dependency on a guardrail*, and the point of spelling it is that a dependency which is invisible cannot be re-checked when the thing it depends on moves. |
| 67 | *(2026-08-08, M12 fix)* **A `fail` rule's audit covers two populations, not one.** D32 moved the body off `@this_model` and onto the pre-route staged extract, which fixed the precedence inversion and, in the same move, stopped covering the rows *already in the entity*. That population is not empty and is not reachable from bronze: a **replayed** row is merged in from the reject table, and its bronze source has aged out of the incremental window by construction — that is the entire premise of `replay_scope` (§5.7). Reproduced end to end: after a widening plus a replay, a row sat in silver whose own `_quality_flags` recorded the blocking rule firing while that rule's audit reported **zero** violating rows — a model contradicting its own data, which is worse than an unchecked population because it reads as coverage. The body is now `pre-route extract UNION @this_model`, exactly two relations, inside D29's limit (`referential` cannot carry `fail`, D6). `UNION` rather than `UNION ALL`: the ordinary violator is in both populations and reporting it twice says nothing extra. The entity leg reads the **recorded** verdict — `_quality_flags` carries FAIL names since D32 — rather than re-deriving the predicate over model columns, which is forced: over the model the coercion marker's source conjuncts are gone and `coercible` would silently re-define itself as `not_null`, the very special case D32 retired. Recorded price: the leg covers rows evaluated under the *current* spec, and a rule added or renamed classifies RESTATING (D11), whose backfill is what re-derives the flags. Replay deliberately does **not** filter `fail` rules out of its MERGE — refusing to merge them would be quarantine outranking fail again, the inversion D32 exists to prevent; the row lands, and the audit is what stops the next run. |
| 68 | *(2026-08-08, M12 fix)* **A quality-mart count is 0 on an empty partition, not NULL.** `SUM(CASE WHEN … THEN 1 ELSE 0 END)` answers 0 for a partition that has rows and matches none of them, and **NULL** for one with no rows at all — `SUM` over zero rows has nothing to sum, which the helper's own docstring denied. An entity with rules whose source delivered nothing this run (a first plan, a partition ahead of the data, an ordinary Tuesday) therefore published mart rows whose every measure was NULL, `rows_quarantined` among them — the numerator D34 exists to make correct. A NULL measure does not read as a small number: it drops out of the `SUM` behind `quality_quarantine_rate`, so the rate answers over a population smaller than the one it names. `COALESCE(…, 0)` around every count, and the docstring made true. |
| 69 | *(2026-08-08, M12 fix)* **A replay loser says why it is still out.** D22's `_one_winner_per_key` keeps one candidate per entity key and the MERGE keeps the better of candidate and incumbent, so a candidate that now **passes every rule** can be left behind by either. D36's third statement then re-derives `failed_rules` for every still-unresolved row, and for that row the honest re-derivation is *empty*: `resolved_at IS NULL, failed_rules = []` reads as "quarantined for these reasons: none", on a row that will lose the contest for as long as it exists and can only leave by retention. The re-evaluation now records the reserved entry `(superseded)` — parenthesised for D34's reason, since rule names are `[a-z0-9_]+` at parse and at generation (D23), so no authored or generated name can collide with it. It is recorded exactly when the row passes routing, which, read together with the statement's own `resolved_at IS NULL` filter, has one meaning: admitted by every rule and still not in the entity, so another row won its key. The alternative — keeping the stale `failed_rules` — was rejected as a lie: those rules no longer fire, and a reject row that names rules the current spec acquits is exactly the ageing account D36 closed. The row stays **unresolved**: a superseded reject is the replay-side analogue of a deduped row, and resolving it would claim into the conservation accounting that *this* bronze row reached the entity, when a different one did. |
| 70 | *(2026-08-08, M12 fix; escape hatch built by D88)* **`last_seen` is one clock — the data's.** It was written as the row's `_ingested_at` (the reject model, D36) and advanced to `CURRENT_TIMESTAMP` by replay's re-evaluation stamp: two meanings in one column, so no reader could say what a value in it was. §5.6 states both halves and settles neither, so the decision is made here. `last_seen` is **the latest delivery's `_ingested_at`** — when the source last delivered this row — and replay's third statement no longer touches it. The deciding argument is retention: §5.6 measures unresolved reject rows *from* `last_seen`, so a column a replay run advances makes an unresolved row immortal for as long as replay keeps running — §9's "quarantine as a PII lake" with its stated mitigation removed. The engine-clock reading cannot instead be pushed onto the write path either: the reject model is a MODEL query, and a clock call there breaks §6's idempotence and backfill-equivalence gates. What is lost, stated: the reject table no longer records *when* a row was last re-evaluated. What records it is `failed_rules`, re-derived from that evaluation — the clause §5.6 names first. A separate `last_evaluated_at` column is the escape hatch if that loss ever bites; it is named, not built, because it is a schema addition and §5.6's schema is this RFC's. This also strengthens D22: replay's third statement is now byte-for-byte idempotent, so the "observability columns excluded" caveat covers `resolved_at`'s timestamp alone. *(D88 built the escape hatch and re-widened that caveat to two columns — the statement stamps `last_evaluated_at`, so it is idempotent over semantic state again rather than byte-for-byte.)* |
| 71 | *(2026-08-08, M12 fix)* **An authored rule name may not be one generation already issues.** D50 made generated names order-independent; they were not **name**-independent. An authored `expression` rule called `status_in_set` sorted ahead of the field's own generated `status_in_set` and took it, pushing the generated rule to `status_in_set_2` — so an edit to the entity's `quality:` block silently renamed a rule declared on a *field*. That name is the key of a time series: the `rule` dimension of `gold.mart_data_quality` (§5.8) and an entry in every reject row's `failed_rules` (D23). `plan()` is honest about the move — a removal, an addition and a replay — which is precisely the problem: none of that happened to the rule, which goes on firing on the same rows under a name nothing in the spec spells. Refused at compile as a bare `GuardrailError` naming both the claimed name and every name generation owns on that entity, because both arbitrations are wrong: renaming the generated rule moves a series key, renaming the authored one contradicts what a human wrote. Making generated names collision-proof *by construction* was rejected as the primary fix — the only free namespace inside D23's `[a-z0-9_]+` is a prefix nobody would want in a mart dimension — but the structural half is kept anyway: name assignment reserves the generated names in their own pass first, so a generated name is a function of the mapping alone and a future suffix cannot defeat the refusal from underneath. |

| 72 | *(2026-08-08, PR #7 review)* **A quality predicate derived from a transform chain must be derived from the chain's *final* value, and the compiler refuses where it cannot prove that.** Two rules read the chain and both read it at the wrong point. `in_enum`'s admissible set is the `enum_map` targets and spellings (D49) while the predicate tests the column's final value, so a step *after* the `enum_map` moves that value off the set: `{enum_map: [paid, paid]}` then `upper` quarantined **every correctly-mapped row** — executed on DuckDB the entity came out empty and all three rows sat in the reject table, the worst failure this feature has. Lowering targets through the remaining chain is not available to a compiler that executes nothing (`regex_extract`, `split_part` and the `strip_*` family are only evaluable by running SQL — RFC 0003), so the chain is refused at compile instead, naming the offending step. A further `enum_map` may follow: the union of both steps' targets contains every reachable final value, so the set can only be too generous, and too generous never withholds a good row. No fixture could have caught it — every `enum_map` in the corpus happens to be the last step. |
| 73 | *(2026-08-08, PR #7 review)* **`nullifies` is a declared property of a transform, not a name list in the quality lowering.** `coercible` infers a cause ("the cast failed") from an effect ("the value vanished"), which is sound only while nothing in the chain nulls a value on purpose. `{nullif: 'N/A'}` says a sentinel means missing, and the row was quarantined for obeying the mapping it was given — with `coercible` never authored, because D24's opt-in is per *entity* and the implicit rule is generated for every mapped field. `TransformSpec` gains `nullifies`; `nullif` and `json_path` carry it, and so do `split_part` and `regex_extract` on the portable reading (`''` on DuckDB, NULL on Trino — a divergence must not be resolved by whichever engine happens to run). The implicit rule is skipped on such a chain and an **authored** one is refused, because a rule a human wrote and a rule the compiler inferred do not deserve the same treatment. Declared on the transform so the next one added must decide, rather than reintroducing the false positive silently. |
| 74 | *(2026-08-08, PR #7 review)* **The replay MERGE expresses the D20 order, it does not re-derive it.** The MERGE compared row constructors, `(a, b) > (c, d)`, which reads like the same question `dedupe_order` asks and is not: SQL row comparison orders NULL as the *largest* value, the inverse of `DESC NULLS LAST`. Both directions broke on a nullable `dedupe.field`/`tie_break` — a candidate that ranked first was not merged (and its reject row was then stamped D69's `(superseded)`, asserting another row won its key, which is false), and a candidate whose sort value was NULL **evicted** a non-null incumbent, silently restating the entity against what D20 says the order is. Replaced by the per-column NULL-aware comparison the order actually means. Not refused instead: D20 specifies nullable sort columns explicitly, so refusing them would contradict the RFC. Asserted exhaustively over a NULL-bearing domain against `ORDER BY … DESC NULLS LAST` on DuckDB — 81 pairs, no disagreements — rather than re-derived by eye; the old unit test asserted the row-constructor *text*, pinning the bug. |
| 75 | *(2026-08-08, PR #7 review; closed by D83)* **Trino cannot host a reject table today, and says so at emit.** Both constructions `<entity>__reject` is built from are ones Trino rejects, verified against `trinodb/trino:483` rather than reasoned about: `SHA256` takes `varbinary` there and returns `varbinary`, so `reject_id` over text fails to plan, and the positional `JSON_OBJECT('k', v)` that builds `raw`/`key_values` is not the spelling Trino parses (it wants `KEY 'k' VALUE v`). D30 read "DuckDB and Trino carry the feature" — true of `TRY_CAST`, which is all D30 tested. Declared as two `DialectFeature`s rather than one, so each can be lifted on its own once the rendering is split per dialect, and gated on `entity.quarantine` so a Trino project with quality rules but no reject table still compiles. Emitting SQL the engine refuses is worse than refusing to emit it: the refusal names the dialect where the author can act on it. The portable spellings are known (`LOWER(TO_HEX(SHA256(TO_UTF8(...))))`, `JSON_OBJECT(KEY … VALUE …)`) but are **not** interchangeable — applied on DuckDB the first hex-encodes an already-hex digest — so the fix is a per-dialect hook, not a shared AST, and it is deferred with its own engine-tier gate. |
| 76 | *(2026-08-08, PR #7 review)* **Three resolution refusals the reconcile and referential surfaces were missing.** (a) A reconcile side may name only a **mapped** entity: `build_project_ir` builds one silver entity per mapping, so a declared-but-unmapped one has no relation to read, and resolving against the declared set left the emitter to discover it as an unbatched `EmitError` after the guardrail stage had reported clean. (b) A side's `by` may not repeat a column — each becomes an output column of the derived relation and a grain column of the model, so a repeat emits two columns of one name and a join PostgreSQL reads as ambiguous; the existing checks missed it because the unknown-column check works over a set and the key-agreement check sorts both sides, so the same repeat on both sides passed. (c) At most one `referential` rule per relationship on an entity: each lowers to a LEFT JOIN aliased `_ref_<relationship>` (D45's family), so two put two joins under one alias and DuckDB rejects the model outright. Rule-unique aliases were rejected as the repair — they would emit two identical joins and let one orphan carry two dispositions at once, which is not a thing a row can obey. This makes `ref_alias`'s one-probe-per-relationship invariant true by construction, the D48 pattern. |
| 77 | *(2026-08-08, PR #7 review)* **A recipe's `direct:` path is a path the mapping reads.** The path-conflict guardrail (RFC 0006 D7) lowers it to a real `<field>__direct` column, and replay re-runs the current mapping against `raw` (D10) — but the path was in neither `_read_paths` nor the entity's `SourceIR.fields`, so it never entered the reject payload at all. Every replayed row rebuilt `net_price__direct` from a key that is not in `raw`: NULL for all of them, fed straight to the reconcile audit whose only job is to compare it. Both halves are needed and neither is sufficient — recording the path makes the payload complete, and only then does adding it to `_read_paths` give `RedactionConflict` something real to refuse. The reviewer who raised this named only the redaction half; the payload half is the larger bug underneath it. |
| 78 | *(2026-08-08, PR #7 review)* **`data_quality` is a reserved *mart* name, not only a reserved metric namespace.** D12 reserved the five metric names and stopped there. `is_quality_mart` matches by name, so an authored mart called `data_quality` is taken for the synthesized one: SQLMesh emitted the quality mart twice at one path and the author's mart — its base, its grain, its measures — vanished with no diagnostic, while Cube wrote two different files to one path and the last writer won. Checked unconditionally, for D12's own reason: a name reserved only sometimes is a name nobody can rely on, and adding one `quality:` block later must not break an unrelated mart. `attach_quality_mart` is deliberately **not** made idempotent as a guard against this — it has one call site, the last statement of `build_project_ir` over a freshly built IR, and a branch no production path can take would mask this refusal rather than add to it. |
| 79 | *(2026-08-08, PR #7 review)* **Removing a `quarantine:` block is BREAKING, and set relaxation is decided from membership params only.** Two `plan()` defects, both reported as the wrong class. (a) Dropping the block was read as a retention edit to `""` and classified ADDITIVE, *"policy only"* — but the `<entity>__reject` model stops being emitted and every unresolved row in it goes with it. D2 buys quarantine over drop *for* recoverability and §5.6 names retention as the only deleter; this deletes reject rows by removing the table. The `replay_scope` stays beside it: with the BREAKING change present it stops being a dangling instruction and becomes "drain this before you apply". (b) D62's `numeric_NNNN` markers carry the strings `"true"`/`"false"` as *values*, and `_relaxed` flattened every param value into one set — so narrowing a set containing the literal `"false"` left the flattened set unchanged and reported a tightening as a relaxation. D62's claim that the markers are "read by the `in_set` builder alone" was false when written. Fixed with an allowlist of membership families per kind, not a `numeric_`-prefix denylist: a denylist lets the next param family rejoin the membership set silently. |

| 80 | *(2026-08-08, PR #7 review, self-audit of the fixes)* **The dedupe order outranks the nulling-chain skip, and a key column has a chain too.** D73's skip, applied uniformly, deleted the one `coercible` rule §5.4/D6 *forces*: on a column the dedupe order reads, an uncastable sort value leaves the order undefined, so the rule is FAIL-disposition and load-bearing rather than a convenience. The skip removed it and its blocking audit with no diagnostic, and `_check_dedupe_disposition` (which demands `on_fail: fail` there) plus D73's own refusal of an authored `coercible` on such a chain left the author refused coming and going — a false positive traded for a silently nondeterministic entity, which is the worse of the two. Dedupe-order columns are now exempt from both halves. Separately, `nullifying_steps` read `mapped_fields`' `None` for a key column as "no chain", but `KeyField` carries a `transform`: the key kept the exact false positive D73 removes, in its worst form, since a key has no `quality:` surface to declare the rule away and no guardrail could refuse it either. The key chain is now looked up. Also fixed here: `to_string` after `enum_map` is the identity on a string and was over-refused by D72; and an `in_enum` on a chain with **no** `enum_map` lowered to `NOT col IN ()` — invalid SQL everywhere and a rule rejecting every row — now refused in the same check, which is its natural home. |

| 81 | *(2026-08-08, follow-up to PR #7)* **Replay asks whether the new rule admits something the old one rejected — not whether the rule relaxed.** D52 phrased the third replay clause as "its parameters relaxed", and the implementation answered exactly that: a superset test for sets, floor-dropped **and** ceiling-rose for bounds. The two questions agree on a pure widening and a pure narrowing and part company on a **swap**, which is both at once. `in_set ["a"] → ["b"]` is not a superset of its old membership and `range 0..10 → 5..20` widens neither end, so both reported no `replay_scope` — while every row quarantined on `b`, and every row quarantined at 15, had become admissible under the new rule and stayed in the reject table with nothing naming it. That is §5.6's "drop plus recoverability" failing in the one direction D52's own tie-break says it must not: a scope with nothing to drain costs a no-op MERGE, a missing one strands rows until a human notices. Fixed by asking the narrower question directly — set difference rather than superset, floor-dropped **or** ceiling-rose — and the function is renamed `_admits_previously_rejected` so the next reader cannot mistake it for a relaxation test again. Rows the change *newly* rejects are deliberately not its concern: they are in the entity, and the RESTATING classification already backfills them out. Found while fixing D79, reported on the PR rather than folded into it, and fixed here because it is a distinct defect with its own decision. |

| 82 | *(2026-08-08, PR #8 review)* **Range bounds are ordered in their own carrier, temporal included.** D57 admits an ISO date or timestamp as a `range` bound — that is what the string carrier is *for* — but the replay decision parsed every bound as `Decimal`, so every temporal bound raised and the pair was reported undecidable. Undecidable means "replay" (D52's conservative direction), so a pure temporal **tightening** scheduled a MERGE that can free nothing, and under `quarantine → fail` that is worse than noise: it is the "feeding a replay runner rows that trip the new blocking audit" case `_replay`'s own docstring says must not happen. The `# pragma: no cover — the spec layer parses these first` sitting on that branch was false the moment D57 landed, and hid it from the coverage gate. Bounds now parse through the same `EXACT_DECIMAL` grammar the spec layer validated them against — promoted to public rather than restated, since two spellings of one grammar is how they drift — and compare only when like-typed. Text comparison was rejected as the shortcut it looks like: ISO strings are not lexicographically ordered (`2020-01-01T05:00:00+06:00` sorts *after* `…T00:00:00Z` and is the earlier instant), and an aware/naive pair has no common instant at all, so that pair stays honestly undecidable. Both reviewers on PR #8 reported this; the fix and its tests cover the direction neither named — a shifted temporal interval, D81's swap in the temporal carrier. |

| 83 | *(2026-08-10)* **The reject table's two constructions are spelled by the dialect port, and Trino hosts it. D75 is closed — and Postgres turned out to be wrong in the same place, silently.** D75 recorded the two gaps and refused Trino at emit; the fix it named — a per-dialect hook rather than a shared AST — is built. `DialectPort` gains `text_sha256` and `json_object`, because a construction that differs per engine belongs to the port that knows the engine (RFC 0008 D1), not to a lowering that is supposed to be dialect-neutral. Trino: `LOWER(TO_HEX(SHA256(TO_UTF8(…))))` and the standard keyword `JSON_OBJECT`. **The finding that was not in D75:** Postgres declared support for *both* features and has neither. Its `sha256` takes and returns `bytea`, so the plain spelling did not fail — it silently yielded bytes where every other engine yields a hex string, which would have made `reject_id` disagree across engines while looking like it worked; and it has no positional `json_object` at all (`function pg_catalog.json_object(unknown, integer, …) does not exist` — the SQL/JSON one arrived in 16 taking `KEY … VALUE` only, and the positional builder has always been `json_build_object`). D75's own sentence — "the one construction SQLGlot renders verbatim on every shipped dialect… holds for DuckDB and Postgres but not Trino" — was therefore half wrong, and it read as verified because the *other* half had been. It held only because Postgres never reached emission: D30 refuses a quality-carrying entity there for the unrelated `TRY_CAST` reason, so the reject table was never built for it. Postgres now has correct spellings that stay unreachable until D30 lifts, asserted at the port rather than through a compile so they cannot rot in the meantime. Verified by **executing the emitted model**, not the expressions: the full `__reject` SELECT runs on `trinodb/trino:483` and returns a `reject_id` byte-identical to the Python canon-bytes digest — cross-engine *agreement* being the property `reject_id` actually needs. The feature flags stay in the vocabulary: a fourth dialect may still lack either, and the refusal they drive is still the right answer for one that does. |

| 84 | *(2026-08-10)* **Postgres hosts quality-carrying entities: `TRY_CAST` is a guard around Postgres' own input parser, not a regex. D30 is closed.** D30 named the escape hatch as "a per-type `CASE`-based fallback whose semantics are proven equal to `TRY_CAST`'s on the corpus", and a per-type regex is what that sounded like. It is the wrong build: a regex is an *approximation* of the parser, and it would have to be kept in step with it forever. `pg_input_is_valid` (Postgres 16+) is the parser, so `CASE WHEN pg_input_is_valid(x, 't') THEN CAST(x AS t) END` accepts exactly what `CAST` accepts and yields NULL exactly where `CAST` raises — equal **by construction** rather than by a proof that decays. Measured anyway, because a claim that is checked is a commitment: over a 57-value adversarial corpus × 5 types, 284 of 285 cases identical to plain `CAST` modulo NULL-on-error. The rewrite lives in the dialect's `render`, so the IR keeps the dialect-neutral `TryCast` node it already had. **The 285th case is the finding.** Postgres accepts `now`/`today`/`tomorrow`/`yesterday` as datetime input and resolves them to the *transaction timestamp*, so a bronze cell spelling `now` coerces to a different value on every run — a backfill disagreeing with the run it replaces, which RFC 0003 exists to prevent, arriving green and unrestatable. The temporal guard excludes them, which is the one place it is deliberately **stricter** than `CAST`: such a cell becomes a coercion failure the `coercible` rule disposes of, a quarantined row rather than a silently unstable one. It also moves Postgres *toward* DuckDB, which rejects `now` outright. Verified by execution, not rendering — rendering was never the hard part, and D30's whole point was that a plain `CAST` renders beautifully and aborts the run: the quality-carrying fixture materializes on postgres 16 with the clean row kept and one specimen per failure mode quarantined, `now` among them, and the tier is now a permanent engine test. Two harness traps recorded because both nearly produced a wrong answer: a *constant* subquery is folded at plan time, so the `CASE`'s other branch evaluates and raises — the guard is only safe over a column, which is what a bronze relation always is; and psycopg reports its own inability to represent `infinity` as an error indistinguishable from a SQL one, which made three engine-accepted values look rejected. **Not closed:** cast *semantics* still differ across engines — DuckDB coerces `'1.5'` to an int and Postgres does not — so the same spec quarantines different rows on different engines. That is inherent to running on different engines, predates this change, and is recorded here rather than implied to be fixed. |

| 85 | *(2026-08-10)* **The corpus has a `range` specimen, and it is a pair. D28 is closed.** D28 recorded that no corpus row casts cleanly and *then* violates a declared bound, so `range` was lowered, matrixed, and reported in the quality mart while diverting nothing anywhere in the corpus. The scope of that gap is narrower than the sentence sounds and worth stating exactly: `range` *was* live at execution, in the `quality_precedence` fixture at `on_fail: fail`, where it blocks a run rather than diverting a row. What had no specimen was the **quarantine** side — the two-way split, the reject row, the conservation accounting — which is the side the rest of this RFC is built around. `keys.csv` gains a **pair**, not a row, because one row cannot pin a bound: `amount_at_range_min` (`0.000000000`) and `amount_below_range_min` (`-0.000000001`) are one ulp apart with opposite dispositions, so `min` lowering to `col <= min` instead of `col < min` becomes a test failure rather than a silently over-eager quarantine. A chaos mutation that drops the `min` bound entirely was written and then **removed**: measured against the pre-D28 corpus it was already caught by `test_quality_precedence`, so it detects nothing the battery could not already see, and a mutation that adds no detection inflates the battery without strengthening it. Recorded because the measurement contradicted the reason for adding it. |

| 86 | *(2026-08-10)* **The catalogue gains `normalize` and `charset`, and the confusables table is deliberately not among them. D26 is closed.** D26 offered "a Unicode normal form **and/or** a confusables table"; only the first half is built as offered. `normalize` is `NORMALIZE(col, NFC) <> col` — the dialect-neutral node, rewritten to `NFC_NORMALIZE` inside DuckDB's `render` because DuckDB has that function and no `NORMALIZE`, while SQLGlot's duckdb generator renders one verbatim (the D83 shape: renders everywhere, defined in two places out of three). One form only: Postgres and Trino spell all four, DuckDB spells one, and a rule that compiles everywhere and runs on two engines out of three is what RFC 0008 D3 exists to refuse. It is a **rule and never a transform** — normalizing silently would rewrite what a source delivered, which D1 forbids. **The table is refused on determinism grounds:** UTS#39 confusables is versioned Unicode data, so embedding it would make a row's disposition depend on which Unicode revision the compiler shipped — an ambient input by another name (RFC 0003), and one that would move dispositions under a dependency bump nobody read as a semantic change. `charset` declares the admissible characters instead, as `U+` codepoints and inclusive ranges, exactly one of `allow:`/`forbid:`, lowering through a single `TRANSLATE(col, members, '')` read two ways. Codepoints rather than characters because every character the rule exists to catch is invisible: a literal one in YAML is unreadable in review and indistinguishable from a space in a diff. The `allow` reading turns out to be *stronger* than the table would have been for the case that motivated it — an allow-list of the script a column is written in catches a Cyrillic homoglyph, a fullwidth digit and an Arabic-Indic digit alike, none of which any denylist enumerates completely. Three declaration refusals, all decidable from the spec alone and so `GuardrailError`s: a backwards range, a range crossing the surrogate block (checked on the *span*, not the endpoints — the block is 2048 wide, so an endpoint-only check would leave the real refusal to arrive from `MAX_CHARSET_SIZE`, a constant that has nothing to do with surrogates and could grow), and a set past that cap, which exists because the members become a string literal in every row's predicate and in the IR fingerprint. `TRANSLATE` carries **no** `DialectFeature`: all three engines spell it identically and its delete-when-shorter behaviour was executed on each rather than assumed; a feature flag earns its place where the *port* has to differ, which is why `normalize` has one and this does not. Verified by execution on postgres 16 as a permanent engine tier and on `trinodb/trino:483` by hand (no Trino client dependency yet — RFC 0009's outstanding work), both agreeing with DuckDB on every specimen including the null. **Found on the way:** the §6 matrix rendered through `node.sql(dialect="duckdb")` rather than through the port, so it executed SQL the emitter never emits. Here that surfaced as a failure — DuckDB has no `NORMALIZE` at all — but the failure is incidental to the direction of this particular rewrite. A port rewrite that produces something the *direct* render also accepts would have diverged silently, with the matrix green on SQL no artifact contains. It is routed through the port now. |

| 87 | *(2026-08-10)* **`repair` lands, its recipe is a registered `sql_macro`, and its marker is its own column. D17 is closed.** D17 gated the disposition on a repair-recipe contract and left §10 asking *inline vs catalog-referenced*. RFC 0017's step registry answers both at once: a recipe is `ref@version` into the registry — declared signature, `runtime_lock`, determinism tier, trust-then-verify — and D1 already holds that specs reference implementations and never contain them, so an inline recipe would have been a second, weaker copy of all of it reachable only from here. **The lowering.** The recipe is spliced at IR build, where the registry lives, and travels as SQL in the rule's params the way an `expression` rule's body does — so emission needs no registry, and a version or `runtime_lock` bump lands in the IR where the fingerprint and `plan()` see it (measured: a body change classifies RESTATING and puts the entity in `replay_scope`, because the kind's params define neither an ordered interval nor a membership set and D52's undecidable-means-replay applies). The rewrite happens at the **extract** level, inside the column's own projection: `CASE WHEN <violation over the raw expression> THEN <recipe> ELSE <raw> END`. That placement is what makes every other rule see the repaired value with no extra nesting, and it forces both halves to be rewritten to read the column's expression rather than its name, since the column is being defined in the same `SELECT`. **The marker.** `_quality_repairs` is a separate column, which was cubic's condition in review and is the right one: a rule is recorded there when its recipe *ran and worked* — it fired over the value as delivered and no longer fires over the value that replaced it. `_quality_flags` stays empty for a repaired row, so `has_quality_flags` keeps meaning **currently suspect** and no mart already asking that question changes its answer. Unlike the two universal columns it is emitted only where a repair rule exists: §12 budgeted the silver-schema churn once, and a third column empty for every project not using the feature is not worth re-opening every golden and fingerprint for. **`fallback` is required**, for the same reason `on_fail` is (D2): a recipe that ran and failed leaves the rule violated and the row is disposed of exactly as if no repair had been declared — the alternative, a still-broken value landing in silver marked as fixed, is the `drop` this RFC refuses wearing a friendlier name. **Refusals**, each a property of the declaration alone: `repair` on `coercible` (it fires *because* the projection is already NULL, so the recipe would be handed the NULL rather than the text that failed to cast — fixing a value before coercion is a Tier 1 macro in the mapping, and the message says so), on `unique` (a property of a population; no rewrite of one row makes a duplicate unique), on a row rule (no column to rewrite), two repair rules on one column (both rewrite the same projection, so which value survives would depend on authoring order and the second recipe would judge a value the first had changed), a recipe accepting more than one column (a rule has no `from:` map, and inventing one would make a rule a second mapping surface), and a column the dedupe order reads (dedupe runs *before* the field rules per D7, so the winner would be chosen on the value as delivered and then have that value rewritten underneath it — D6's reasoning exactly). Verified by executing the emitted pipeline over three rows — one the recipe fixes, one it cannot, one it must not touch — and by sabotage: disabling the recipe, and dropping the "did it run" conjunct from the marker, each fail the assertion that names them. **Not built:** `gold.mart_data_quality` gains no `rows_repaired`, so repairs are observable in silver and not in the quality mart. Recorded rather than implied — adding a measure changes the mart schema, and no demand has asked for it. |

| 88 | *(2026-08-10)* **`last_evaluated_at` is built, and it is safe to advance because retention never reads it.** D70 settled `last_seen` as the data's clock and named this column as the escape hatch for what that cost — the reject table stopped recording *when* a row was last re-evaluated. Built now as a schema addition to §5.6, which is what D70 said made it the RFC's to decide. **Stamped on both replay branches**, not only the still-failing one: a resolved row was re-evaluated too, and a column that stopped at the last *unsuccessful* look would read as a stale lie the moment a later run resolved the row. The two statements are disjoint by `resolved_at IS NULL`, so a row is stamped exactly once per run; on the resolving branch it is a second `CURRENT_TIMESTAMP` beside `resolved_at` rather than a copy of it, so the two may differ by however long the statement takes on an engine that does not pin a transaction clock — stated rather than papered over, because a reader comparing them will notice. **The safety property is a negative one:** nothing reads this column. Unresolved reject rows still age from `last_seen` and resolved ones from `resolved_at`, so the immortality D70 refused cannot come back through the new column. **The merge half is the part that is easy to miss.** The reject *model* projects it NULL — a model query may not read a clock without breaking §6's idempotence and backfill-equivalence gates — and that model is the source of the `INCREMENTAL_BY_UNIQUE_KEY` merge, so the default overwrite would erase the stamp on every re-delivery: a row would forget it had ever been replayed because the source delivered it again. It therefore joins `first_seen` in the preserved set, which until now had exactly one member and read like a special case rather than a rule. Both mechanisms sabotage-verified against DuckDB: dropping the resolving branch's stamp and dropping the column from the preserved set each fail the test that names them. **Consequence for D22:** replay's third statement is no longer byte-for-byte idempotent — it now writes a clock — so the "observability columns excluded" caveat covers `resolved_at` and `last_evaluated_at` rather than the former alone. That is the caveat's original shape; D70's narrowing of it was a side effect of the loss this row restores. |

| 89 | *(2026-08-10)* **Mart-level checks are assertions, not quality rules. §10's open question is settled by the disposition model.** §8 deferred them as "blurs into reconciliation" and §10 asked "reconcile-shaped or new surface?" — the answer is neither, and what decides it is not taste. §5.9 draws the boundary at what a verdict *does*: a quality rule disposes of a **row**. A mart row is derived — no `_source_row_id`, no bronze payload, no reject table, no replay — so there is nothing to quarantine, nothing to repair, and nothing to bring back; and a `reconcile` compares *two sides*, which "no month has zero revenue" is not. What is left is D4's other half, "alert me", so `assert:` on a mart declares `{measure, agg, by, min/max, on_fail}` and lowers to an audit the mart model names. `quarantine` and `repair` are absent from its `on_fail` rather than lowered to something weaker, so an author who wanted routing learns it at the surface instead of from a mart that silently only alerts; `fail`/`flag` map to blocking/non-blocking exactly as `reconcile.on_fail` does (D38). The aggregate vocabulary is deliberately the *same tuple* the reconcile grammar uses — both compute one number over a column so a human can be told it is wrong, and two lists that mean the same thing drift. Bounds ride in `params` as text through the D57 carrier, for the same reason. **Resolution is against the flattened column set**, not the base entity's: `ordered_month` exists only because a `date:` step made it, and it is precisely the column §10's example groups by. **The body** is `SELECT <by…>, <agg>(<measure>) FROM @this_model [GROUP BY <by…>] HAVING <bound comparison>` — the value beside the group, because a failure a human must open the warehouse to understand gets ignored. A bare `HAVING` with no `GROUP BY` is the whole-mart form; both shapes were executed on DuckDB, postgres 16 and `trinodb/trino:483` rather than read out of three manuals, and all three agree. **What it cannot see, stated rather than implied:** D19 reaches the mart, so every aggregate but `count` is NULL over an empty group and the assertion stays silent — which is also why an assertion cannot notice a month that is *entirely missing*: no row means no group at all. `count` is the exception and is the one shape that catches an empty mart. Closing the missing-period case needs a join against the date spine, a coverage check with its own dependency, and it is named here rather than half-built. **dbt and Cube refuse a project carrying one**, sharing `refuse_steps`' message shape: neither has the audit form, and compiling clean while the declared gate does not exist is the failure D83 caught in the dialect ports. **Cost recorded:** `MartIR` gains a field, and the canonical encoder covers each node's field *names and count*, so every fingerprint in the corpus moves — the churn §12 budgets, spent deliberately. The fixture carrying the demonstration is `quality_precedence` rather than `ecom_basic`, because an assertion makes a project uncompilable for two targets and `ecom_basic` is the fixture those targets' goldens are built on. |

| 90 | *(2026-08-10)* **Cross-entity checks are `coverage:` on a relationship, and the audit hangs off the *dependent* side. §10's last open question is settled.** §10 guessed "probably reconcile-style"; it is not, and the reason is structural rather than stylistic. A `reconcile` compares two **values** and alerts beyond a tolerance — there is no right-hand value on the referenced entity to compare against, and `right: 1` is neither a shape the closed grammar admits nor one it should grow. This asserts **existence**: every row of a relationship's referenced entity has at least `min` rows referencing it. That makes it the mirror of `referential`, which asks whether every *dependent* row has a parent, and both read the same two relations through the same `via` pairs — which is why it is declared on the **relationship** rather than on either entity. **Why an audit, when a disposition would have been meaningful.** Unlike a mart row (D89), a childless customer is a real silver row with a source identity, a reject table and a replay path, so routing it is not nonsense. It is still an audit, for a reason that only shows up in the DAG: routing would need the *referenced* entity's model to read the *dependent* one, while the dependent one already reads the referenced one through this very relationship — so the pair that most wants this check (an FK one way, a coverage check the other) is exactly the pair whose models would form a cycle. Attaching the audit to the dependent side instead adds **no edge the relationship did not already imply**. `on_fail` is `fail`/`flag` only; `quarantine` and `repair` are absent from the surface rather than lowered to something weaker. **Two emission details that are each a trap closed.** The body counts a *dependent* column, never `COUNT(*)`: a `LEFT JOIN` still produces one output row for an unmatched left row, so `COUNT(*)` answers 1 for a customer with no orders at all and the check would pass on precisely the rows it exists to find. And the dependent side is `@this_model` rather than a named relation — the macro is the one reference SQLMesh rewrites inside an AUDIT body (D29), so naming the relation resolved to the virtual layer *and* put the model into its own `depends_on`, which is how the first cut emitted it. The referenced side is a sibling and is declared in `depends_on`, the trap D40 closed for step audits. Verified by a real SQLMesh plan on a fixture added to the e2e tier for it: the comment above `step_resolution` there argues that nothing else loads SQLMesh and that the gap hid three defects in a row, and this is the same shape — an audit body joining a sibling, with a `depends_on` that exists only because of the audit. dbt refuses the project (its tests are predicates, with no grouped cross-relation form); Cube is not asked, because it builds nothing (RFC 0017 D52). **Cost:** `ProjectIR` gains a field, so every fingerprint moves. **Not closed:** the check counts rows that *reached* silver, so a referenced row quarantined by its own rules reads as absent — right for "has an order", wrong for a check somebody phrases as "exists", and named here rather than discovered. |

> **Numbering note (2026-08-08).** Rows **40–44 do not exist**. Two self-audit fix
> waves ran concurrently, each reserved a block for the other, and neither used the
> reserved one — so the gap is an artifact of parallel authorship, not a removed or
> withheld decision. The table is append-only (a reversed decision gets a new row
> citing the one it reverses), so the numbers stand as issued rather than being
> compacted: renumbering would invalidate every `D<n>` citation already written into
> the code, tests and docs, which is a worse failure than a visible hole.


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
