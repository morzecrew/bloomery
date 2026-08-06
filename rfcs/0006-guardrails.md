# RFC 0006 — Guardrails: refusing plausible-but-wrong arithmetic

- **Status:** 📝 Draft
- **Scope:** The guardrail stage (`bloomery/guardrails/`) — the compile-time checks that
  refuse arithmetic that parses, typechecks, and produces a number that is wrong: unit
  coherence, tax basis, currency, grain (fan-out), additivity, path conflict, and range
  sanity. Covers the checks' rules, the metadata they run on, the batched
  `GuardrailError` shape, and the one guardrail that emits instead of raising (path
  conflict). Does not cover how `unit`/`tax_basis`/grain reach the IR (resolution —
  RFC 0005; IR shape — RFC 0003), transform typing (RFC 0004), how `AuditIR` becomes
  target-native audits (RFC 0008), mart structure itself (RFC 0010), or the planner's
  query-time additivity lowering (RFC 0011).
- **Related:** [`rfcs/_original-smelter-spec.md`](_original-smelter-spec.md) §3.2, §5.4,
  §7.4; [`rfcs/_bloomery-changes.md`](_bloomery-changes.md) D2, D4, D10; RFC 0002 §5.4
  (error hierarchy, batching doctrine), RFC 0003 (`ColumnIR` metadata fields,
  `AuditIR`), RFC 0008 (emitter-side refusal), RFC 0009 (`fanout_trap`,
  `semi_additive_inventory` fixtures), RFC 0010 (mart structure the mart-level checks
  run on), RFC 0011 (query-time additivity lowering).

---

## 1. Summary

Seven guardrails run as stage four of the pipeline, after typecheck, as a pure function
over the draft `ProjectIR`. Six raise; all violations across the whole project are
collected and raised as a single `GuardrailError` aggregate, each violation a typed leaf
(`UnitMismatch`, `TaxBasisMismatch`, `CurrencyMismatch`, `GrainMismatch`,
`AdditivityViolation`, `AssertLoweringError`, plus the mart-level `GrainViolation` and
`FanoutRisk` and the additivity leaf `NonAdditiveWithoutComponents`) with a source path. The seventh — path
conflict — never raises: it amends the IR to emit both candidate columns plus a
reconciliation audit, because there the silent choice is the failure, not the data.

## 2. Motivation

The guardrails target the bug class where the formula is right, the data is right, and
the answer is 3× wrong: an order-grain shipping cost joined to line grain and summed; a
net price subtracted from a gross cost; an average materialized as a stored number and
then re-averaged. These bugs pass every syntactic and type check, survive code review,
and surface as a finance discrepancy months later. The original spec (§5.4) calls the
grain and additivity guards the highest-value part of the package; this RFC makes all
seven refusals precise enough to implement and test to 100% branch coverage (spec §7.1).

## 3. Current state

Greenfield. RFC 0003 already reserves the carrier fields: `ColumnIR.unit`,
`ColumnIR.tax_basis`, `ColumnIR.recipe_id`, `EntityIR.audits: tuple[AuditIR, ...]`, and
`MetricIR.additivity`. RFC 0002 §5.4 declares `GuardrailError` in the hierarchy and
records that the guardrail stage batches.

## 4. Goals / Non-goals

**Goals**

- All seven guardrails from spec §5.4 in v0.1, as compile **errors** — never warnings,
  never config-downgradeable.
- Batched reporting: one raise listing every violation in the project, each with a
  source path, so authors fix a spec in one round-trip.
- Path-conflict handling that preserves both answers and makes the disagreement
  measurable instead of picking a winner.

**Non-goals**

- Runtime data checks — `assert:` clauses become `AuditIR` and run in the target
  engine (RFC 0008); the guardrail stage only validates them statically.
- Inferring `unit`/`tax_basis` from names or values — metadata comes from the catalog
  or it is `unknown`. Inference would make the refusals probabilistic.
- A severity/suppression knob. A knob makes "error" negotiable and the guardrails exist
  precisely because these errors get waved through.

## 5. Design

### 5.1 Stage shape

```python
def check_guardrails(draft: ProjectIR) -> ProjectIR:
    """Stage 4. Pure. Returns the IR amended only by path-conflict handling (§5.5);
    raises one aggregated GuardrailError if any violation is found."""
```

Everything the checks need is already on the draft IR: column metadata propagated at
resolve, entity grains, relationships with cardinality, metric additivity, and lowered
expressions (`SqlExpr`, RFC 0003 §5.2). The checks walk each `ColumnIR.expr` and
`MetricIR.expr` AST; at every `+`/`-` (and, for currency, any arithmetic) node they
resolve leaf column references to their metadata and apply the rules below.

Error shape, consistent with RFC 0002 §5.4:

```python
class GuardrailError(BloomeryError):
    violations: tuple[GuardrailError, ...] = ()   # non-empty on the raised aggregate

class UnitMismatch(GuardrailError): ...
class TaxBasisMismatch(GuardrailError): ...
class CurrencyMismatch(GuardrailError): ...
class GrainMismatch(GuardrailError): ...
class AdditivityViolation(GuardrailError): ...
class AssertLoweringError(GuardrailError): ...
class GrainViolation(GuardrailError): ...             # mart-level fan-out guard (§5.3)
class FanoutRisk(GuardrailError): ...                 # mart-level fan-out guard (§5.3)
class NonAdditiveWithoutComponents(GuardrailError): ...  # additivity (§5.4)
```

Leaf instances are constructed as values and collected across the whole project; if any
exist, the stage raises the base `GuardrailError` whose `violations` are sorted by
`(source_path, type name)` (RFC 0003 determinism) and whose message lists every one.
This matches RFC 0002 D6's batching doctrine: one round-trip per stage.

### 5.2 Metadata provenance: unit, tax basis, currency

`unit` and `tax_basis` originate **only** on catalog canonical fields (spec §3.2) and
propagate to entity columns through the `canonical:` link at resolve (RFC 0005). A
tenant-native monetary column — no `canonical:` link — has no metadata and is treated
as `unknown`. The rules:

- **Unit coherence** (`UnitMismatch`): operands of `+`/`-` must share `unit`.
  Currency + count is an error. `unknown` in any `+`/`-` is an error — unknown poisons
  additive arithmetic rather than silently passing (spec §3.2). Multiplication and
  division are exempt (currency × count is how extensive quantities work).
- **Tax basis** (`TaxBasisMismatch`): `net` and `gross` may not meet in `+`/`-`;
  `unknown` in any `+`/`-` with a monetary operand is likewise an error. Multiplying by
  a dimensionless factor preserves basis.
- **Currency** (`CurrencyMismatch`): canonical fields may carry an ISO-4217
  `currency:` code. Two operands with *distinct declared* codes require an explicit
  `convert` transform in the chain. Unlike tax basis, an absent code is compatible with
  anything: single-currency tenants are the common case and forcing declaration
  everywhere would train authors to paste a constant, destroying the signal. Declared ≠
  declared is the bug worth refusing.

### 5.3 Grain — the fan-out guard

Every operand of a derivation resolves to a column of some entity, each entity has a
grain, and relationships carry cardinality (RFC 0003). The rule: **all operands of a
derivation must share the derivation's grain, or the expression must contain an
explicit aggregation step over the finer grain.** An operand reached through a
`many_to_one` relationship sits at a coarser grain; joined down without aggregation it
is duplicated once per fine-grained row, and any downstream `SUM` overstates it. There
is no "distribute evenly" auto-fix — allocation is a modelling decision the author must
write as an explicit expression.

**Mart-level checks (compile time).** With marts as IR objects (RFC 0010,
[`_bloomery-changes.md`](_bloomery-changes.md) D2), the fan-out guard also runs where
fan-out would actually be built: over each mart definition. Two leaves:

- `GrainViolation` — a measure whose grain is **coarser** than the mart's grain listed
  in that finer-grain mart's `measures` (order-grain `shipping_cost` on an item-grain
  mart). Flattened in at build time it is duplicated once per fine-grain row and every
  downstream `SUM` overstates it — the same arithmetic this section refuses in
  derivations, caught at the declaration site.
- `FanoutRisk` — a `flatten:` step whose `via:` relationship is not `many_to_one` or
  `one_to_one`. A `one_to_many` flatten multiplies the mart's own rows.

Both are `GuardrailError` leaves, batched with the rest (§5.1). Mart structure
(`grain`, `flatten:`, `measures`) is defined in RFC 0010; this stage only checks it.

The `fanout_trap` fixture (RFC 0009) therefore now fails at **compile** time with
`GrainViolation`, where previously the wrong number appeared only at execution. The
execution-level assertion is kept — per D2, "it documents *why* the compile error
exists": the unguarded shipping-cost SQL (spec §7.4) still runs against DuckDB to show
the 3×-wrong sum the guard refuses.

### 5.4 Additivity

Checked at IR build over `MetricIR.additivity`:

- A `non_additive` metric (e.g. a ratio) may **never** be materialized as a stored
  number — not as an entity column, not as a stored aggregate. Only its additive
  components may be stored; the ratio is a calculated measure at query time.
- A `semi_additive` metric may only be aggregated over dimensions *other than* its
  `over:` dimension (RFC 0002 §5.5). The bare `over:` annotation is replaced by
  `SemiAdditivePolicy(over, rule)` with `rule ∈ {last, first, avg, max, min}`
  ([`_bloomery-changes.md`](_bloomery-changes.md) D4); the guard checks the same
  invariant against `policy.over`, while the query-time lowering of `rule` is
  RFC 0011's. A metric that sums an inventory balance across time is an
  `AdditivityViolation`; the `semi_additive_inventory` fixture (RFC 0009) covers it.
- A `non_additive` metric declared without a `RatioSpec` (or an equivalent additive
  decomposition) is a `NonAdditiveWithoutComponents` error: with nothing additive to
  recompute from at query time, the metric could only ever be answered by storing
  it — which the first rule forbids.

Defense in depth: the IR-level check is authoritative, but emitters (RFC 0008)
additionally refuse to render a stored non-additive measure and propagate
`meta.additivity` into Cube output. Two independent refusals because this is the
failure mode that silently corrupts every dashboard built on the stored number.

### 5.5 Path conflict — the guardrail that does not raise

When a field has both a direct source column and a satisfiable recorded derivation
(spec §5.4), any silent choice is wrong: the two can disagree, and whichever the
compiler picks, the discrepancy becomes invisible. So the compiler emits **both**:

- the derived column under the field's name (the recipe is the recorded, auditable
  decision — RFC 0002's doctrine that resolution is decided upstream);
- a `<name>__direct` shadow column carrying the direct value;
- an `AuditIR(kind=RECONCILE)` comparing them, lowered to a target-native audit
  artifact that surfaces row-level disagreement.

This is still a guardrail — the invariant is "never pick one silently" — but the
correct refusal is refusing the *silence*, not the spec: both paths are individually
valid, so there is nothing for the author to fix at compile time. Raising here was
considered and rejected: it would force authors to delete information (the direct
column or the recipe) to make the error go away, which is strictly worse than
measuring the disagreement.

### 5.6 Range sanity

Optional per-field `assert:` clauses — `min`, `max`, `not_null`, `enum` membership,
`regex` — lower into `AuditIR` entries (RFC 0003) that emitters render as
target-native audits (RFC 0008). The guardrail stage validates only that each clause is
**well-typed against the field's `LogicalType`** (RFC 0004): `min`/`max` require a
numeric or temporal field, `regex` a string field, `enum` members must be castable to
the field type. An ill-typed clause is an `AssertLoweringError` — batched with the
rest, because a range assertion that can never run is a silent hole in the audit net.

### 5.7 Worked examples

Four violations and their exact messages (message format: leaf class, document-prefixed
source path per RFC 0002 §5.3, then the finding and the fix):

**Fan-out (spec §7.4).** `order_item.landed_cost = unit_price + shipping_cost`, where
`shipping_cost` lives on `order`, reached via `item_of_order` (`many_to_one`):

```
GrainMismatch at entity_model: entities.order_item.fields.landed_cost
  '+' combines 'unit_price' (grain: one row per line on an order) with
  'shipping_cost' from entity 'order' (grain: one row per order), reached via
  relationship 'item_of_order' (many_to_one) with no aggregation step.
  Joined to line grain, shipping_cost is duplicated once per line; any SUM over
  landed_cost overstates shipping by the line count.
  Fix: add an explicit aggregation/allocation over 'order_item', or declare the
  derivation on entity 'order'.
```

**Mart-level fan-out (D2).** `marts.order_items` (grain: `order_item`) lists
`shipping_cost` (grain: `order`) in its `measures`:

```
GrainViolation at entity_model: marts.order_items.measures.shipping_cost
  measure 'shipping_cost' has grain 'order' (one row per order), coarser than the
  mart's grain 'order_item' (one row per line on an order). Flattened into the mart
  it is duplicated once per line; any SUM overstates shipping by the line count.
  Fix: remove it from this mart's measures, or serve it from an order-grain mart
  (e.g. marts.orders).
```

**Unknown tax basis.** `order_item.margin = unit_price - supplier_cost`, where
`supplier_cost` has no `canonical:` link:

```
TaxBasisMismatch at entity_model: entities.order_item.fields.margin
  '-' combines 'unit_price' (tax_basis: net) with 'supplier_cost'
  (tax_basis: unknown — the field has no canonical: link, so no metadata
  propagates). Arithmetic combining unknown with any basis is refused.
  Fix: link 'supplier_cost' to a catalog canonical field carrying tax_basis,
  or add the field to the catalog.
```

**Stored non-additive metric.** A `MetricSet` materializes `average_order_value`:

```
AdditivityViolation at metrics: metrics.average_order_value
  metric is non_additive (ratio: net_revenue / order_count) and may not be
  materialized as a stored number — a stored average re-aggregates wrongly.
  Fix: store the additive components (net_revenue, order_count) and emit the
  ratio as a calculated measure; the Cube emitter does this automatically.
```

## 6. Tests

- Unit: 100% of guardrail branches (spec §7.1) — every rule's trigger and its nearest
  non-trigger (shared unit passes; declared-vs-absent currency passes; aggregated
  coarse operand passes), asserting leaf type, source path, and batching (two seeded
  violations → one aggregate carrying both, sorted).
- Execution (RFC 0009): `fanout_trap` now fails closed at compile time
  (`GrainViolation`), and its execution-level assertion is kept — the unguarded SQL is
  executed against DuckDB to show the 3×-wrong sum the compile error exists to prevent;
  `semi_additive_inventory` covers the `over:` rule; a path-conflict fixture executes
  both columns and the reconciliation audit.
- Property: guardrail output is deterministic — same draft IR twice yields
  byte-identical aggregate messages (violation ordering is load-bearing).

## 7. Docs

Explanation page `pages/explanation/guardrails.md`: one section per guardrail with the
failing spec, the exact error, and the fix — the worked examples above are the seed.
Must state plainly that guardrails cannot be downgraded to warnings, and why path
conflict produces two columns instead of an error (readers will file that as a bug
otherwise).

## 8. Out of scope

- **Cross-entity unit algebra** (deriving that currency/count is a valid `ratio` unit
  for division results) — v0.1 checks `+`/`-` coherence only; derived-unit inference
  can be added to the same walk if `ratio`-typed canonical fields appear in practice.
- **Configurable reconciliation tolerance** for path-conflict audits — v0.1 emits exact
  comparison; tolerance is an `AuditIR` parameter to add when a real catalog needs it.

## 9. Risks

- *False positives on legitimate coarse-grain arithmetic* (e.g. intentional per-line
  allocation) forcing verbose explicit aggregations. Accepted: the explicit expression
  is the audit trail; verbosity is the price of the guarantee, and the error message
  names the fix.
- *Path-conflict shadow columns read as clutter* and get manually dropped, silently
  restoring the single-path world. Mitigation: the reconciliation audit is emitted
  unconditionally with the shadow — removing one without the other is visible in
  `plan()` (RFC 0007) as a BREAKING drop.
- *`unknown`-poisons rule frustrates early adoption* (unmapped monetary fields refuse
  arithmetic). Accepted deliberately: the frustration is the feature — it forces
  catalog linkage exactly where money math happens.

## 10. Unresolved questions

- None blocking. Implementation is free to settle the AST-walk mechanics (visitor vs.
  pattern match on `exp` node types) and the exact `RECONCILE` audit SQL shape, as long
  as messages and batching semantics match this RFC.

## 11. Decisions

| # | Decision |
| --- | --- |
| 1 | All seven spec-§5.4 guardrails ship in v0.1 as compile errors — never warnings, no severity/suppression knob. A knob makes "error" negotiable, which defeats the stage's purpose. |
| 2 | Violations are batched project-wide: leaf errors (`UnitMismatch`, `TaxBasisMismatch`, `CurrencyMismatch`, `GrainMismatch`, `AdditivityViolation`, `AssertLoweringError`) are collected and raised as one `GuardrailError` aggregate, sorted by `(source_path, type)`. Matches RFC 0002 D6. |
| 3 | `unit`/`tax_basis` originate only on catalog canonical fields and propagate via `canonical:`; a monetary operand without metadata is `unknown`, and `unknown` in any `+`/`-` is an error. No inference from names or values, ever. |
| 4 | Currency codes are checked only when both operands declare one; distinct declared codes require an explicit `convert` transform. Absent codes are compatible — opt-in, unlike tax basis, so single-currency tenants aren't trained to paste constants. |
| 5 | Grain guard: derivation operands must share the derivation's grain or the expression must contain an explicit aggregation over the finer grain. No automatic allocation. `fanout_trap` (RFC 0009) is the numeric proof. |
| 6 | Additivity: `non_additive` metrics are never materialized as stored numbers (components only); `semi_additive` metrics aggregate only over dimensions other than their `over:` dimension. Enforced at IR build **and** re-refused by emitters (RFC 0008) — defense in depth. |
| 7 | Path conflict does not raise (`PathConflict` is not an error class): the compiler emits the derived column, a `<name>__direct` shadow, and a `RECONCILE` `AuditIR`. The forbidden thing is the silent choice; both paths are valid, so the refusal targets the silence, not the spec. |
| 8 | Range sanity: the guardrail stage validates `assert:` clauses for well-typedness against the field's `LogicalType` only (`AssertLoweringError`); lowering to target-native audits happens via `AuditIR` at emit (RFC 0003/0008). |
| 9 | `check_guardrails(draft: ProjectIR) -> ProjectIR` is pure; its only amendment is path-conflict handling (shadow column + audit). All other guardrails are read-only checks. |
| 10 | Mart-level fan-out guard runs at compile time (_bloomery-changes.md D2, RFC 0010): `GrainViolation` (a measure whose grain is coarser than the mart's grain listed in a finer-grain mart's `measures`) and `FanoutRisk` (a `flatten:` step whose `via:` relationship is not `many_to_one`/`one_to_one`) are `GuardrailError` leaves, batched like the rest. `fanout_trap` now fails at compile time; its execution assertion is kept because it documents why the compile error exists. |
| 11 | Additivity extends with `NonAdditiveWithoutComponents` (a `non_additive` metric declared without a `RatioSpec` or equivalent additive decomposition — nothing to recompute from); `SemiAdditivePolicy(over, rule)` with `rule ∈ {last, first, avg, max, min}` replaces the bare `over:` annotation (_bloomery-changes.md D4). The query-time lowering of `rule` is RFC 0011's, not this stage's. |

## 12. Phasing

Ships in M4 (_bloomery-changes.md D10): "done when `fanout_trap`,
`semi_additive_inventory` fail closed with useful messages" —
`semi_additive_inventory` joins `fanout_trap` as the acceptance fixture. Metadata
carriers land earlier (M1, RFC 0003; propagation M3, RFC 0005), as do the mart spec
models the mart-level checks read (M1 spec layer, RFC 0010); emitter-side additivity
refusal lands with the M2/M8 emitters (RFC 0008).
