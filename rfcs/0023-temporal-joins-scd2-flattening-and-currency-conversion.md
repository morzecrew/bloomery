# RFC 0023 — Temporal joins: SCD2 flattening and currency conversion

- **Status:** 🚧 In progress — **P1 landed** (both refusals, §5.1/§5.2); P2 unscheduled.
  Per §9 the document stays rather than being retired: deleting the shipped half would
  leave the refusals with no recorded reason. Execution departures are D12–D17.
- **Scope:** Two constructs that compile clean today and cannot be correct at run time,
  because both need a join against a **validity interval** and bloomery models none.
  Flattening a `scd: type2` entity into a mart emits an equality join on the business key,
  which multiplies the base grain by the number of versions; `convert` emits a
  `CONVERT_CURRENCY(...)` call no dialect implements. **Phase 1 refuses both** — one new
  guardrail, one emit-time refusal — and is the whole of what this RFC schedules.
  **Phase 2 designs the as-of join** that would let either be accepted, plus the FX rate
  relation currency needs, and is deliberately unscheduled. Touches `guardrails/`,
  `transforms/_builtins.py`, `emit/lower/marts.py`; Phase 2 would additionally touch
  `spec/`, `ir/` and the catalog. No public signature changes in Phase 1.
- **Related:** [`src/bloomery/emit/lower/marts.py`](../src/bloomery/emit/lower/marts.py)
  (the join construction), [`src/bloomery/spec/entity.py#L74`](../src/bloomery/spec/entity.py#L74)
  (`scd`), [`src/bloomery/guardrails/grain.py`](../src/bloomery/guardrails/grain.py)
  (`FanoutRisk`, the guardrail this one sits beside),
  [`src/bloomery/transforms/_builtins.py`](../src/bloomery/transforms/_builtins.py)
  (`convert`), [`src/bloomery/guardrails/arithmetic.py`](../src/bloomery/guardrails/arithmetic.py)
  (the `CONVERT_CURRENCY` marker), RFC 0006 (guardrails — refusing plausible-but-wrong
  arithmetic), RFC 0008 (`DialectPort`, `Feature`, `UnsupportedByTarget`), RFC 0010
  (marts, flattening, fan-out refusal), RFC 0016 (`unknown_member` — the disposition
  Phase 2 reuses).
- **Origin:** External review of `main` @ `828fd5b`, 2026-08-14 (findings F1 and F2).
  Both reproduced before this RFC was written; see §3.

---

## 1. Summary

Two constructs promise more than the compiler can deliver, and both fail the same way:
they need a join against a validity interval, and bloomery has no way to express one.

**Flattening a historical dimension.** A mart flattening an entity declared `scd: type2`
emits `LEFT JOIN silver.x ON base.k = x.k` — no validity predicate. The relation is
physically `SCD_TYPE_2_BY_COLUMN`, one row per version per key, so every base row fans out
to the number of versions. Every guardrail stays green because `FanoutRisk` reads the
*declared* cardinality, which is a claim about the domain, not about the table.

**`convert`.** The transform emits `CONVERT_CURRENCY(col, 'USD')`, a function no dialect
implements. The currency guardrail then treats that marker as sufficient grounds to permit
mixed-currency arithmetic it would otherwise refuse.

Phase 1 refuses both, and is the whole of what this RFC schedules: a new `HistoricalFanout`
guardrail (with the symmetric check on a mart's `base`), and `convert` raising
`UnsupportedByTarget`. Neither is a workaround for a missing feature — each is the correct
answer until the feature exists, and each is cheap now and a breaking change after 0.1.

Phase 2 designs the as-of join both would need, and is **deliberately unscheduled**. It is
written down here because designing them separately would produce two mechanisms for one
problem.

## 2. Motivation

The project's introduction opens on exactly this defect:

> an order-level shipping cost joined to line items and summed three times over […]
> The formula was right, the data was right, and the answer was 3× wrong.

An SCD2 flatten is that defect, reached from a spec the compiler accepted. It is *worse*
here than in a hand-written dbt project, and the reason is the promise: an engineer writing
the join by hand has a chance of remembering `valid_to IS NULL`, and no tool told them the
query was checked. Here the join is generated, the spec looks right, the compiler said yes,
and every page of documentation says plausible-but-wrong is refused. **A promise of refusal
makes an unrefused defect more expensive than no promise at all** — it converts a bug the
user might have looked for into one they were told not to.

`convert` is the milder shape of the same thing. It does not produce a wrong number; it
produces a run-time failure in the one place the architecture promises there will not be
one — after the compiler said the spec was good. By the project's own scale a refusal beats
a wrong number, so this is the lesser defect; but a refusal *at run time* is the wrong
refusal, and the compiler already has everything it needs to give the right one.

Both are cheap to close now and expensive to close later: after 0.1, refusing a construct
that previously compiled is a breaking change, and the stability policy will owe users a
migration for a construct that never worked.

## 3. Current state

Verified against `main` @ `828fd5b` (2026-08-14). Every claim below was reproduced.

### SCD2

- `scd: type1 | type2` is declared per entity at
  [`spec/entity.py#L74`](../src/bloomery/spec/entity.py#L74), reaching the IR as `SCDKind`
  ([`ir/nodes.py#L114`](../src/bloomery/ir/nodes.py#L114),
  [`#L477`](../src/bloomery/ir/nodes.py#L477)).
- Both emitters honour it: SQLMesh writes
  `SCD_TYPE_2_BY_COLUMN (unique_key (…), columns *)`
  ([`emit/sqlmesh/__init__.py#L283-L286`](../src/bloomery/emit/sqlmesh/__init__.py#L283-L286)), dbt a
  check-strategy snapshot ([`emit/dbt/__init__.py#L437`](../src/bloomery/emit/dbt/__init__.py#L437),
  [`#L511`](../src/bloomery/emit/dbt/__init__.py#L511),
  [`#L688`](../src/bloomery/emit/dbt/__init__.py#L688)).
  So the relation genuinely holds one row per version per key.
- **`scd` is read in exactly one place outside the emitters and the plan diff:**
  [`emit/lower/quality_mart.py#L157`](../src/bloomery/emit/lower/quality_mart.py#L157). Nothing
  in `marts/`, nothing in `guardrails/`.
- The join is built from the relationship's columns and nothing else,
  [`emit/lower/marts.py#L91-L104`](../src/bloomery/emit/lower/marts.py#L91-L104).
- **Reproduction.** Taking `ecom_basic` and adding one line — `scd: type2` on the flattened
  `order` entity — compiles clean and emits:

  ```sql
  FROM silver.order_item AS order_item
  LEFT JOIN silver."order" AS order_
    ON order_item.order_id = order_.order_id
  ```

  while the same compile emits `silver.order` as
  `MODEL (name silver.order, kind SCD_TYPE_2_BY_COLUMN (unique_key (order_id), columns *))`.
  `gross_revenue` is `additive`, the mart's grain equals the measure's grain, and every
  guardrail passes.

- **The corpus cannot catch this.** Two fixtures declare `scd: type2` —
  `scd2_customers` and `evolution_v5` — and **neither has a `marts.yaml`**. The
  combination has never been compiled. This is the same blind-spot shape as the M18
  defects: not an untested branch, an untested *combination*.

### Currency

- `convert` is a registered transform returning
  `exp.Anonymous(this="CONVERT_CURRENCY", …)`
  ([`transforms/_builtins.py#L381-L387`](../src/bloomery/transforms/_builtins.py#L381-L387)).
- `grep -rn CONVERT_CURRENCY src/ tests/` returns **four** occurrences: the definition, the
  guardrail marker at
  [`guardrails/arithmetic.py#L46`](../src/bloomery/guardrails/arithmetic.py#L46), and two unit
  tests asserting that string renders. No dialect port mentions it.
- The marker is load-bearing in the wrong direction: it is what lets mixed-currency
  arithmetic past `CurrencyMismatch`. So the currency guardrail's escape hatch is a token
  that guarantees a run-time failure.

### What Phase 1 would break

Nothing in the corpus. No fixture flattens or bases a mart on a `type2` entity, and no
fixture uses `convert`. Both refusals are additive against the shipped fixture set — which
is *also* the finding: the corpus contains no case either refusal would fire on, so the
tests for them are new fixtures, not new assertions on old ones.

## 4. Goals / Non-goals

**Goals**

- Make both constructs fail at compile time, with a named reason and a source path, before
  0.1 makes the refusal a breaking change.
- Keep the two refusals **narrow**: refuse the *combination*, never the feature. `scd:
  type2` stays fully supported as a silver model; `convert` stays a registered transform
  whose typecheck is unchanged.
- Write down the as-of join design once, covering both consumers, so the two are not
  designed twice or designed incompatibly.

**Non-goals**

- **Building the as-of join.** Phase 2 is design-only and unscheduled; see §12.
- **Inferring an as-of anchor.** RFC 0021 closed inference under "bloomery derives
  defaults; it does not infer intent", and a date to join history on is intent.
- **Making `convert` work by approximation.** A rate table the compiler invents, or a
  single-rate constant, is the "plausible wrong number" the project exists to refuse.
- **Point-in-time correctness for metrics.** This RFC is about a *join*. Whether a metric
  can request "as it was on date D" is a planner question, not a lowering one.

## 5. Design

### 5.1 Phase 1 — `HistoricalFanout`

A new `GuardrailError` subclass, sitting beside `FanoutRisk` in
[`guardrails/grain.py`](../src/bloomery/guardrails/grain.py) — same stage, same batching,
adjacent reason:

```
HistoricalFanout: mart 'order_items' flattens 'order' through 'item_of_order',
  and 'order' is scd: type2 — the join matches every version of each key, so
  each base row is multiplied by that key's version count. The declared
  cardinality (many_to_one) is a claim about the domain; the relation holds one
  row per version.
  Declare the entity scd: type1, or flatten a type1 current-view entity built
  from it.
  source: marts.yaml: marts.order_items.flatten[0]
```

The check is symmetric and fires in two places:

1. **`flatten`** — the shape above. Any flattened entity with `scd is SCDKind.TYPE2`.
2. **`base`** — a mart whose base entity is `type2`. There is no fan-out here (nothing to
   multiply), but the mart's declared `grain:` says one row per entity while the relation
   holds one row per entity per version, so every measure over it counts versions.
   `order_count` returns the number of *revisions*. That is a grain lie, and refusing it is
   the same call `GrainMismatch` already makes elsewhere.

`FanoutRisk` is deliberately **not** reused. Its message explains a declared-cardinality
mismatch, and pointing it at a physical-history problem would make one error mean two
things — the reader would check the relationship's `cardinality:`, find it correct, and be
stuck.

### 5.2 Phase 1 — `convert` refuses

`convert` raises `UnsupportedByTarget` when it reaches emission, in all three dialects. No
new error class: this is exactly what `UnsupportedByTarget` is for, and a dialect that later
implements the join clears it by declaring a `Feature`, which is the mechanism RFC 0008
already provides.

The refusal is at **emit**, not parse, on purpose: `convert` remains a legal transform with
a valid typecheck, and the day a target can lower it, nothing in the spec layer changes.
The message names the reason rather than the symptom:

```
UnsupportedByTarget: transform 'convert' has no lowering on any shipped dialect
  — currency conversion is a join against a dated rate table, and bloomery
  models no rate relation (RFC 0023 §5.4). The emitted CONVERT_CURRENCY(...)
  call exists in no engine.
  source: mapping_crm.yaml: fields.amount_usd.transform[1]
```

**The currency guardrail's marker goes with it.** `_CONVERT_MARKER` is what permits
mixed-currency arithmetic; once `convert` cannot be emitted, the marker can only appear in
a spec that will be refused anyway. Removing it restores `CurrencyMismatch` to meaning "you
cannot add EUR to USD", full stop — which is the honest state until conversion exists.

### 5.3 Phase 2 — the as-of join

Both consumers need one construct: join a fact row to the version of a dimension that was
current at a given instant.

```sql
FROM silver.order_item AS order_item
LEFT JOIN silver."order" AS order_
  ON  order_item.order_id = order_.order_id
LEFT JOIN silver.customer AS customer_
  ON  order_.customer_id      =  customer_.customer_id
  AND order_item.order_date  >=  customer_.valid_from
  AND order_item.order_date  <   COALESCE(customer_.valid_to, TIMESTAMP '9999-12-31')
```

The full chain is shown because the shape matters: the fact is `order_item`, the anchor
date is on the fact, and the foreign key is on `order_` — a dimension reached through
*another* flattened join. A two-hop flatten is the common case, not the exception, and it is
what makes "which date is the anchor" a question rather than an obvious answer.

Three things must be modeled that are not modeled today:

**The validity columns.** `EntityIR` would carry the names of the interval columns for a
`type2` entity. They are currently invented by the *target* — SQLMesh's
`SCD_TYPE_2_BY_COLUMN` names them, dbt's snapshot names them differently — so bloomery does
not know them, which is precisely why no predicate can be emitted. Naming them in the IR
makes the two targets agree on a fact they currently each own privately.

**The anchor.** Which date the join is *as of*. It must be declared, never inferred (§4).
The natural home is the `flatten` entry, beside the `via:` it qualifies:

```yaml
flatten:
  - {via: order_of_customer, prefix: customer_, as_of: order_date}
```

**The miss.** A fact row whose anchor precedes every version of its key matches nothing. The
disposition vocabulary already has the right answer — `unknown_member` (RFC 0016) — and
reusing it means no new concept and no new NULL semantics.

### 5.4 Phase 2 — currency as a declared relation

A rate is a dated fact, so conversion is the as-of join again with a different right-hand
side. Rates are reference data, which makes them a **catalog** concern:

```yaml
fx_rates:
  relation: silver.fx_rate
  from: from_ccy
  to: to_ccy
  rate: rate
  valid_from: valid_from
  valid_to: valid_to      # required — see below
```

**The interval needs both ends, declared.** An earlier draft of this section named only
`valid_from`, which does not define an interval: a fact row then matches every rate at or
before its anchor, and the join multiplies rather than converting — the same fan-out this
RFC's other half refuses. The alternative is deriving the upper bound with
`LEAD(valid_from) OVER (PARTITION BY from_ccy, to_ccy ORDER BY valid_from)`, which is
attractive because it cannot disagree with itself, and rejected for two reasons: it makes
every conversion a window function over the whole rate table, and it silently extends the
newest rate to infinity, so a stale feed converts at last week's rate instead of failing.
A declared `valid_to` lets the miss be a miss, which D9's `unknown_member` disposition
then handles.

This forces a grammar change `convert` cannot avoid: `convert(x, 'USD')` carries no date,
and a rate without a date is under-determined. Whatever the final spelling, the transform
must name its anchor. **That is the argument for refusing now rather than "finishing"
`convert` later**: the current signature is not merely unimplemented, it is incomplete, and
shipping it would pin a grammar that cannot express the feature.

### Alternatives considered

**Emit the validity predicate silently, guessing the anchor.** The obvious guess is the
mart's declared date role. It is right often enough to be dangerous: when it is wrong, the
answer is a plausible number computed against the wrong version of history, which is the
exact failure class this project refuses. Rejected because a wrong join is worse than a
refused one, and the anchor is intent.

**Filter to the current version (`valid_to IS NULL`) automatically.** Cheap, and correct for
the common "current attributes" case. Rejected as a *default*: it silently converts a
historical dimension into a current-view one, so a mart whose whole purpose is
point-in-time attribution returns today's segment for a two-year-old order — with no
diagnostic, because the row count would look right. It stays available as something the
author writes explicitly (a `type1` current-view entity), which is what the refusal message
recommends.

**Implement `CONVERT_CURRENCY` as a per-dialect UDF the emitted project defines.** bloomery
already emits a macro for dbt rather than depending on `dbt_utils` (RFC 0008 D18), so there
is precedent for shipping the implementation. Rejected because the missing piece is not the
function, it is the *rate data*: a UDF would still need a table bloomery does not model,
and would place a hand-applied artifact in the operator's contract to no benefit.

## 6. Tests

Phase 1:

- **A new fixture per refusal**, since the corpus has no case either fires on: a mart
  flattening a `type2` dimension, and a mart based on one. Both assert the refusal with its
  source path — and each *without* the `type2` line must compile, so the test discriminates
  the combination rather than the fixture.
- The existing `scd2_customers` fixture **gains a `marts.yaml`** as the base-side case. It
  is the fixture whose name promises this coverage and does not currently provide it.
- A `convert`-carrying mapping asserting `UnsupportedByTarget` on all three dialects, and a
  currency-guardrail test showing `CurrencyMismatch` now fires where the marker used to
  suppress it.
- Sabotage: removing either refusal must fail a test. The SCD2 one is the load-bearing case
  — it is the only thing standing between a green compile and a 3× number.

Phase 2 tests are not specified here; the design is not scheduled.

## 7. Docs

- `pages/docs/concepts/marts.md` (or wherever flattening is explained): historical
  dimensions cannot be flattened, why, and the current-view entity as the shipped answer.
- The transform reference marks `convert` **unimplemented and refused**, with the rate-table
  reason. Today it is listed among 22 working transforms with nothing distinguishing it.
- `pages/docs/reference/errors.md` gains `HistoricalFanout`.
- **No page may describe the as-of join as available.** Phase 2 is design, and a docs page
  describing an unbuilt feature is the defect this RFC's own §3 found in another form.

## 8. Out of scope

- **`scd: type2` entities as a silver target.** Fully supported and unchanged; only the
  mart-level combination is refused.
- **Point-in-time metric requests** ("revenue by segment as of Q1") — a planner-contract
  question (RFC 0011), reachable only once the join exists.
- **Bitemporal modelling** (valid time *and* transaction time). SCD2 gives one interval;
  two is a different data model and would need its own RFC.
- **Rate sourcing** — where FX rates come from, at what frequency, from which provider. The
  catalog declares a relation; filling it is the platform's job, exactly as with every other
  source.

## 9. Risks

- **Phase 1 reads as a feature removal.** Nothing that worked stops working — the construct
  never produced a correct answer — but a user with an SCD2 flatten in a spec that
  "compiled fine" will experience a new refusal as a regression. Mitigated by landing before
  0.1, and by a message that names the wrong number rather than citing a policy.
- **Refusing `convert` looks like scope reduction.** It is the opposite: it removes a
  promise that could not be kept. The transform reference must say "refused because
  unimplemented", not "removed".
- **Phase 2 stays unbuilt and this RFC becomes the second, drifting account** the corpus
  policy exists to prevent. Mitigated by the retirement rule: if Phase 1 lands and Phase 2 is
  never scheduled, the RFC stays 🚧 rather than being retired — deleting the shipped half
  would leave the refusals with no recorded reason.
- **The anchor question gets settled by implementation.** If Phase 2 is ever picked up, the
  `as_of:` spelling in §5.3 is illustrative. It is graded `OPEN` below for that reason.

## 10. Unresolved questions

- **Does the `base` refusal need an escape hatch?** A mart deliberately over all versions
  of a dimension is a coherent thing to want, and D2 refuses it outright. If a real consumer
  asks, the answer is likely a mart-level declaration that the grain includes the version —
  which needs the validity columns from §5.3 and so is Phase 2 anyway.
- **Where does the anchor live** — on the `flatten` entry, on the mart, or on the
  relationship? §5.3 proposes the flatten entry because that is the join being qualified;
  a mart-level default would be less repetitive and more ambiguous with two historical
  dimensions.
- **Should `convert` be removed from the transform whitelist entirely** rather than refused
  at emit? Removal is cleaner but changes the exported JSON Schema's transform enum, which
  is a spec-surface change; refusal keeps the surface stable. §5.2 chooses refusal; a
  reviewer may reasonably prefer removal.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | Flattening an entity with `scd: type2` into a mart is **refused** at compile time, not silently emitted and not silently filtered to the current version. The join has no validity predicate and the relation has one row per version, so the emitted mart multiplies the base grain while every guardrail passes. Consequence: the only shipped way to use a historical dimension in a mart is a `type1` current-view entity built from it, until §5.3 exists. |
| 2 | `LOCKED` | A mart whose **`base`** is `scd: type2` is refused on the same account. There is no fan-out, but the declared `grain:` claims one row per entity while the relation holds one per version, so every measure counts revisions. Refusing both sides keeps "a mart's grain is what it says" true without exception. |
| 3 | `ASSUMED` | The refusal is a new `GuardrailError` subclass, `HistoricalFanout`, rather than a reuse of `FanoutRisk`. Reusing it would make one error mean both "your declared cardinality is wrong" and "your relation is historical", and the first reading sends the reader to a `cardinality:` that is correct. |
| 4 | `LOCKED` | `convert` raises `UnsupportedByTarget` at **emit**, on all three dialects. It stays a registered transform with an unchanged typecheck, so the spec surface does not move and a future dialect clears the refusal by declaring a `Feature` — the mechanism RFC 0008 already provides. |
| 5 | `LOCKED` | `_CONVERT_MARKER` is removed from the currency guardrail with D4. It is the token that permits mixed-currency arithmetic; leaving it would keep a compile-time "yes" whose only outcome is a run-time failure. Consequence: `CurrencyMismatch` becomes unconditional until §5.4 ships. |
| 6 | `LOCKED` | Phase 2 (as-of join, FX relation) is **design-only and unscheduled**. Recording it here rather than in two future RFCs is the point: both consumers need one construct, and designing them apart would produce two. |
| 7 | `ASSUMED` | A `type2` entity's validity-interval column names belong on `EntityIR`. Today each target names them privately, which is the mechanical reason no predicate can be emitted; naming them in the IR is what makes the two targets agree. |
| 8 | `OPEN` | The as-of anchor's spelling and location. §5.3 proposes `as_of:` on the `flatten` entry; a mart-level default and a relationship-level declaration are both defensible. Whoever builds Phase 2 decides and logs it. It must be **declared** either way — inference is closed by RFC 0021. |
| 9 | `ASSUMED` | A fact row whose anchor matches no version takes the existing `unknown_member` disposition (RFC 0016) rather than a new one. |
| 10 | `OPEN` | Whether `convert` is refused (D4) or removed from the transform whitelist outright. Removal is cleaner and changes the exported JSON Schema's transform enum — a spec-surface change this RFC declines to make on a construct that may return. |
| 11 | `LOCKED` | The FX rate relation declares **both** interval ends (`valid_from` and `valid_to`), never `valid_from` alone. One end is not an interval: a fact row would match every rate at or before its anchor and the conversion would fan out. Deriving the upper bound with `LEAD(valid_from)` is rejected — it makes every conversion a window function over the whole rate table, and it extends the newest rate to infinity, so a stale feed converts at last week's rate instead of failing. Consequence: a gap in the rate table is a *miss*, taking D9's `unknown_member` disposition, rather than silently resolving to a neighbour. |
| 12 | `ASSUMED` | **Departure (spec-gap).** `HistoricalFanout` is raised in `marts/flatten.py`, not `guardrails/grain.py` as §5.1 places it. `FanoutRisk` is *declared* in `errors.py` and *raised* in the flattener; `grain.py`'s own docstring says the mart-level leaves "run where marts are lowered", so the RFC's placement named a file the sibling it cites is not in. Behaviour is unchanged — both leaves batch into the same guardrail aggregate. §5.1's prose is left as written. |
| 13 | `ASSUMED` | **Departure (spec-gap).** `scd2_customers` does **not** gain a `marts.yaml` (§6). It is the only golden coverage of the SCD2 silver lowering — SQLMesh's `SCD_TYPE_2_BY_COLUMN` and dbt's check-strategy snapshot — across five tiers, and §8 leaves that fully supported; any mart in that fixture is necessarily based on its one type2 entity, so following §6 would have deleted the coverage this refusal is defined against. A new fixture `scd2_mart_refusal` carries both sides instead, in **one** document rather than one per refusal: the property §6 asks for is that a single line is the whole difference, and two fixtures would let an unrelated difference stand in for it. |
| 14 | `ASSUMED` | **Departure (spec-gap).** The `convert` refusal is **unconditional**, not gated on a declared capability. D4 says a future dialect clears it "by declaring a `Feature` — the mechanism RFC 0008 already provides", but `SQLGlotDialect.features` defaults to `frozenset(DialectFeature)`: a flag for a capability *nothing* has would be claimed by default by all three shipped dialects and by every dialect added later, so declaring one now would encode the opposite of the fact. The escape hatch is added when a dialect can actually clear it; until then the refusal states what is true — no lowering exists anywhere. |
| 15 | `ASSUMED` | **Answers D10 (`OPEN`).** `convert` is **refused**, not removed from the whitelist. Removal is cleaner but changes the exported JSON Schema's transform enum — a spec-surface change on a construct that may return, and one that would make a spec still carrying the step fail as an *unknown transform* rather than as the thing it is. The refusal message can say why; an enum rejection cannot. |
| 16 | `ASSUMED` | **Departure (spec-gap).** The scope header says "No public signature changes in Phase 1", and P1 adds two public names: `bloomery.errors.HistoricalFanout` and `bloomery.transforms.CONVERT_MARKER`. The stability reference makes `bloomery.__all__` **and each subpackage's `__all__`** the SemVer contract, so both count. The first is unavoidable — a new `GuardrailError` subclass callers catch has to be importable — which makes the scope line wrong rather than the implementation. The second is a choice: the marker is shared so the transform that *builds* it and the emit check that *refuses* on it cannot spell it differently, since a refusal looking for a name nothing produces passes every project including the ones it exists to stop. Both are additive; nothing is removed or renamed. |
| 17 | `ASSUMED` | **Departure (discovery).** The `convert` refusal's `source_path` is `entity_model: entities.<entity>.fields.<column>`, not the mapping path §5.2's illustrative message shows. By emit the transform chain no longer exists: the marker sits in a lowered `ColumnIR.expr`, and the mapping's step index is not recoverable from it. Refusing earlier, where the path *is* known, would contradict D4's `LOCKED` "at **emit**". |

## 12. Phasing

**P1 — the two refusals (§5.1, §5.2).** Small, self-contained, no new concepts, and
**should land before 0.1**: after the release, refusing a construct that previously compiled
is a breaking change under the stability policy, and bloomery would owe a migration path for
a construct that never produced a correct answer. Before the release it is a bug fix.

**P2 — the as-of join (§5.3, §5.4).** Unscheduled and demand-gated. The trigger is a named
consumer who needs point-in-time attribution or currency conversion; the cost is
IR-and-spec surface plus a new lowering shape on both targets, and it is not small. Until
then, D1's refusal message names the shipped workaround, which is what makes P2's absence a
boundary rather than a gap.
