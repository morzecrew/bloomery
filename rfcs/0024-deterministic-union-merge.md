# RFC 0024 — Deterministic union merge

- **Status:** 🚧 In progress — **P1 landed; P2 designed and demand-gated (D31).** The union,
  its compile-time checks, the collision audit, `_source`, the plan-classifier rows, the
  `multi_source` fixture and the docs pair are shipped — six departures recorded in
  [`logs/T-0004.md`](../logs/T-0004.md), drift count zero. This document stays for
  **P2** (§12): the quality system on a merged entity. P2's design is now settled rather
  than sketched — D32/D33 fix rule lowering, D34/D35 fix `dedupe:` — and its *code* waits
  for a project that needs it, on the same test RFC 0023 D6 applies to its own P2.
  **D30's dbt refusal lifted on 2026-08-20** — RFC 0026 gave that emitter a singular-test
  surface, so a merged entity now emits on both SQL targets. D30's row below stands
  unamended: it was correct when written, what changed is the emitter, and the record of
  why merged entities were SQLMesh-only for one release is the point of keeping it.
  Everything below describes the design as argued; the deviation log is what says where the
  code went another way. Original scoping follows.
- **P1 scope (as designed, D14):** the union, its checks, the collision audit and the `multi_source` fixture, with `dedupe:` and `quarantine:` refused on a merged entity (§5.6). D8, D10 and D11 are answered by D22–D24; D14–D21 record what reading the code turned up that §3 had not. **D26 answers D25** and **D28 answers D27**: the lowered expression moves to a per-source `SourceColumnIR` while `ColumnIR` keeps the schema (§5.7), and a `direct:` path is refused on a merged entity. The surface D26 moves is enumerated and closed — **three `ColumnIR` constructors and four lowering reads** — so P1 is specified and executable in the order §5.7 → §5.1–§5.6. **D29 widens D14's boundary to `opts_in`**: §5.6 traced the row identity soundly and then generalised past it, and rule lowering turns out to be per mapping behind neither block — so P1 refuses the quality system on a merged entity rather than only its two entity-level declarations. **D30 departs from D20**: the union needs no dbt capability, but its collision audit had no dbt surface, so a merged entity **was** refused on that target rather than shipped without the check that makes it correct — lifted 2026-08-20 by RFC 0026, as the status line above records; the tense is marked here because this bullet is P1's scope as designed and a live RFC stating a lifted refusal in the present tense reads as a contract.
- **Scope:** Allowing **more than one mapping to target one entity**, merged by a
  deterministic `UNION ALL`, when the mappings agree on the entity's key and cover its
  required fields. Covers the shape where two systems describe the same kind of thing in
  **one shared key space with disjoint key sets** — two shops on one platform, a
  region-sharded table, a post-migration merge. Deliberately does **not** cover overlapping
  keys, precedence between sources, or any matching: that is identity resolution, settled
  as a step by RFC 0021 and unchanged here. Touches `resolve/build.py` (the refusal it
  replaces), `emit/lower/silver.py` (the union), `guardrails/`, `plan/diff.py`. Adds one
  system column and one generated audit; no public signature changes.
- **Related:** [`src/bloomery/resolve/build.py#L845-L851`](../src/bloomery/resolve/build.py#L845-L851)
  (the refusal), [`tests/unit/test_resolve/test_build.py#L255`](../tests/unit/test_resolve/test_build.py#L255)
  (the test that pins it), [`src/bloomery/emit/lower/silver.py`](../src/bloomery/emit/lower/silver.py)
  (silver lowering, the fixed pipeline order, the system columns), RFC 0009 D4 (which named
  the `multi_source` fixture and never built it), RFC 0016 (dispositions, blocking audits,
  the fixed dedupe-before-rules order), RFC 0017 (steps — the Tier 3 escape hatch this
  replaces for the simple case), RFC 0021 (identity resolution as a step, permanently; and
  the reusable spec-kind test this design is measured against).
- **Origin:** Independently identified twice — as the one unbuilt item in RFC 0009's own
  fixture corpus, and as finding F3 of the external review of `main` @ `828fd5b`
  (2026-08-14).

---

## 1. Summary

An entity may currently be built from exactly one mapping. Two source systems holding
orders therefore produce `order_shopify` and `order_woo`, never `order` — so the entity
model, which the documentation positions as *what a tenant's data means*, stops short of
integrating anything.

This RFC allows several mappings to target one entity, merged by a `UNION ALL` in a fixed
lexicographic order, under compile-time conditions the compiler can actually check: same
key, required fields covered, agreeing types. What it cannot check — that the key sets are
disjoint — becomes a **generated blocking audit**, which is the same compile-time-shape /
run-time-data split the project already draws everywhere else.

Overlapping keys stay out. A key present in two sources is either a duplicate to refuse or
a match to resolve, and resolving it is identity resolution, which RFC 0021 settled as a
step. This RFC deliberately does not soften that.

## 2. Motivation

**The gap is in the layer the project is named for.** `EntityModel` is presented as the
integrated domain model, and today an entity is a view of one source relation with the
columns renamed. That is a mapping layer, not an integration layer.

**The workaround is disproportionate.** Reaching a union today means Tier 3: a manifest in
the platform's step registry, a Python model, a contract assertion, a wrapper per output —
and SQLMesh only, since dbt refuses `python_model` steps (RFC 0017 D52). All of that to
express `UNION ALL`, with no matching involved.

**The refusal already promises this.** [`resolve/build.py#L849`](../src/bloomery/resolve/build.py#L849)
raises with the words *"deterministic union merge lands with the multi_source milestone
(RFC 0009 D4)"*. RFC 0009 D4 defined the corpus as "exactly spec §7.7", `multi_source`
included — *"two sources → one entity via deterministic union merge"* — and RFC 0009 was
retired ✅ Complete with that fixture never built. The refusal message cites a promise, in
a retired document, that nothing is scheduled to keep.

**It passes the project's own test for deserving support.** RFC 0021 states the reusable
question — *can bloomery typecheck it, guardrail it, and diff it meaningfully?* — and this
scores yes three times:

- **typecheck** — every mapping must produce the entity's key and its required fields, at
  the declared types. That is the check the single-mapping path already performs, applied
  once per mapping.
- **guardrail** — an identical key is a compile-time refusal; disjointness is a generated
  blocking audit, in the vocabulary RFC 0016 already ships.
- **diff** — adding a source is `ADDITIVE`, removing one `RESTATING`, changing the key
  `BREAKING`. All three fall out of the existing classifier.

That is the material difference from identity resolution, where the answer to all three is
no — which is exactly why *that* is a step and this is not.

## 3. Current state

Verified against `main` @ `828fd5b` (2026-08-14).

- Mappings are grouped by target in
  [`resolve/build.py`](../src/bloomery/resolve/build.py) `_build_entities`, and a group of
  more than one raises `ResolutionError` at line 849. The grouping is already
  by-target-then-sorted, so the data structure the union needs is the one already built —
  the refusal sits where the merge would go.
- The refusal is pinned by
  [`test_multiple_mappings_per_entity_refuse_until_multi_source`](../tests/unit/test_resolve/test_build.py)
  (line 255). It is a deliberate, tested boundary, not an oversight.
- **No `multi_source` fixture exists.** `tests/fixtures/` holds 20 fixtures; the one RFC
  0009 D4 named is not among them.
- The silver pipeline order is fixed and documented — dedupe **before** rules
  (`pages/docs/concepts/data-quality.md`, "The pipeline order is fixed"). A union stage
  ahead of both is consistent with that ordering rather than a new axis.
- System columns already exist on silver relations (`_ingested_at`, `_load_id`,
  `_quality_flags`, `_quality_ok`), so adding one more is an established shape rather than
  a new concept.
- `unmapped:` already exists as an *explicit acknowledgement* that a source column is
  deliberately not mapped ([`guardrails/quality.py#L238`](../src/bloomery/guardrails/quality.py#L238)).
  The same instinct — silence is not consent — drives §5.2's treatment of absent fields.

## 4. Goals / Non-goals

**Goals**

- Several mappings into one entity, with a deterministic emitted artifact.
- Compile-time refusal of every disagreement the compiler can see: key, required-field
  coverage, type.
- A run-time refusal of the one thing it cannot see: a key in two sources.
- Fall out of the existing plan classifier — no new change class.

**Non-goals**

- **Matching of any kind.** No fuzzy comparison, no blocking keys, no thresholds. RFC 0021
  settled that as a step, permanently, and nothing here reopens it.
- **Precedence between sources on an overlapping key.** "Billing wins over CRM" is a
  merge policy, and a merge policy is business logic bloomery cannot typecheck. Overlap is
  refused; a project that needs it wires a step.
- **Cross-source deduplication semantics.** `dedupe:` applies to the merged relation with
  its existing meaning; it does not gain a source-aware mode.
- **A new spec kind.** Multi-source is a property of a *set of mappings*, expressed by
  their existing `target:`. Nothing new to author.

## 5. Design

### 5.1 What a project writes

Nothing new. Two mappings name the same `target:`:

```yaml
# mapping_shopify.yaml
mapping_version: 1
source: shopify__orders
target: order
key: {order_id: {from: "$.id", transform: [to_string]}}
fields:
  customer_id: {from: "$.customer.id", transform: [to_string]}
  placed_at:   {from: "$.created_at", transform: [to_timestamp]}
```

```yaml
# mapping_woo.yaml
mapping_version: 1
source: woo__orders
target: order          # same entity
key: {order_id: {from: "$.number", transform: [to_string]}}
fields:
  customer_id: {from: "$.billing.customer", transform: [to_string]}
  placed_at:   {from: "$.date_created",     transform: [to_timestamp]}
```

The absence of new syntax is the design: an entity built from two mappings differs from one
built from one only in how many documents point at it.

### 5.2 What the compiler checks

Batched with the other resolution errors, so an author sees every disagreement at once:

1. **Identical key columns.** Every mapping must produce the entity's full declared key.
   A mapping producing a partial key is refused — a union on a partial key has no meaning.
2. **Required-field coverage.** Every mapping must produce every field declared
   `required: true`. A required field NULL for one source's rows is a broken contract, and
   NULL-filling it silently is the failure mode this check exists to prevent.

   **This is coverage, not non-nullity, and the difference is load-bearing.** `required:
   true` is a schema declaration; the runtime null check is a separate mechanism —
   `assert: {not_null: true}`, which lowers to an audit
   ([`guardrails/asserts.py#L132-L133`](../src/bloomery/guardrails/asserts.py#L132-L133)).
   So this check proves every mapping *declares* the field, and proves nothing about what
   its source path returns per row. A mapping whose `$.customer.id` is absent in half the
   payloads passes it and writes NULLs into a required column. That asymmetry exists today
   for single-mapping entities and is not created here — but a merge makes it materially
   worse, because one bad source silently poisons a column the other sources fill
   correctly, and the entity looks internally inconsistent rather than externally broken.
   Whether the union stage emits a generated `IS NULL` audit over required columns is D11.
3. **Optional fields may be absent, but not silently.** A field a mapping does not produce
   is `NULL` for that mapping's rows. This is legitimate — one system has no loyalty tier —
   and it is also exactly what a typo in a field name looks like. It therefore requires the
   same acknowledgement `unmapped:` already demands elsewhere; the exact spelling is `OPEN`
   (D8).
4. **Type agreement** falls out of the existing per-mapping typecheck: each mapping's chain
   is checked against the entity's declared field type as it is today, so two mappings
   disagreeing about a type both fail against the declaration rather than against each
   other.

### 5.3 What is emitted

One silver model, a `UNION ALL` of one projection per mapping, ordered **lexicographically
by source name**:

```sql
SELECT ..., 'shopify__orders' AS _source FROM bronze.shopify__orders
UNION ALL
SELECT ..., 'woo__orders'     AS _source FROM bronze.woo__orders
```

**Two mappings may not name the same `source:` for one target.** Lexicographic ordering
needs a total order, and two branches reading one relation tie — which would leave branch
order undefined, `_source` ambiguous between them, and the collision audit unable to name
which branch it means. `(target, source)` is therefore unique, refused at compile time
alongside the checks above. A project genuinely reading one relation twice (two disjoint
row sets from one table) expresses that as one mapping with a filter, which is a shape
`quality:` already covers; if a real consumer needs the two-mapping form, the fix is a
declared per-mapping identity, not a tie-break the author cannot see.

Two things about determinism, which are different and both required:

- **Artifact determinism** — the emitted SQL text must be byte-identical across processes.
  The lexicographic source order provides branch order; **column order is already
  canonical** and not newly relied upon here — projections are emitted sorted today, as any
  existing golden shows (`silver/order_item.sql` projects `line_no, order_date, order_id,
  quantity, unit_price` against a declaration order of `order_id, line_no, unit_price,
  quantity, order_date`). Reordering fields in a mapping therefore cannot move bytes, and
  the union inherits that. This is the invariant RFC 0003 protects and the one that matters
  here.
- **Row order** is *not* claimed. `UNION ALL` is a bag; no downstream model may depend on
  which source's rows come first. Where an order is needed — `dedupe`'s
  `keep: latest_by` — it comes from the declared ordering columns, as it does today.
  Stating this explicitly because "deterministic union" invites the wrong reading.

`_source` carries the mapping's source name. It is not decoration: the collision audit in
§5.4 reports *which* sources collided, and without provenance the report is "this key is
duplicated somewhere", which is not actionable on a five-source entity.

The union is the **first** stage: union, then dedupe, then rules. That places it ahead of
the documented dedupe-before-rules order rather than beside it, and follows the same
argument — a rule evaluated per-source would judge a row that the merged relation does not
contain.

### 5.4 What is refused at run time

The compiler has no data, so it cannot know the key sets are disjoint. A generated audit
does — reading the **union output, before dedupe**:

```sql
SELECT order_id, line_no, COUNT(DISTINCT _source) AS sources
FROM <the union stage>          -- NOT silver.order, which is post-dedupe
GROUP BY order_id, line_no
HAVING COUNT(DISTINCT _source) > 1
```

Two things this shape pins, both of which an earlier draft got wrong:

**It groups by every declared key column, generated from the entity's `key:`.** The
single-column form above is one instance, not the spec — a composite key grouped by its
first column alone merges distinct keys and blocks valid data, which is a false refusal on
a blocking audit and therefore the worst possible failure of this check.

**It reads the union stage, not `silver.order`.** `silver.order` is post-dedupe, and dedupe
is precisely the operation that collapses rows sharing an entity key — so an audit reading
it would see one surviving row where two sources collided and report nothing. The check has
to run on the relation *before* the stage that hides what it looks for. The collision test
in §6 is written for exactly that case: two sources colliding on a key that `dedupe:` would
have collapsed.

Blocking, `on_fail: fail`, and **not configurable to a weaker disposition**. A key in two
sources means one of two things, and both are refusals: either the sources genuinely
duplicate a row, or they share a key space by accident. Flagging it would let a
double-counted entity into the warehouse marked suspect, and the whole point of the union
being *deterministic* is that the merged relation is a faithful set union.

The message names the escape hatch, so the refusal routes rather than merely blocks:

```
Key 'order_id' appears in more than one source of entity 'order'. A union merge
requires disjoint key sets (RFC 0024). Sources that overlap need a match rather
than a merge — wire an identity-resolution step (RFC 0017).
```

`COUNT(DISTINCT _source) > 1` deliberately does **not** fire on a key duplicated *within*
one source: that is ordinary duplication, and `dedupe:` already owns it.

### 5.5 How it diffs

No new change class:

| Change | Class | Why |
| --- | --- | --- |
| A mapping added to an entity that already had one | `ADDITIVE` ×2 | New rows, **and** the `_source` column appears. A field added is already `ADDITIVE` ([`plan/diff.py#L358-L364`](../src/bloomery/plan/diff.py#L358-L364)) |
| A mapping added to an already-merged entity | `ADDITIVE` | New rows only; `_source` is already present |
| A mapping removed, two or more remaining | `RESTATING` | Same columns, fewer rows — the relation must be rebuilt |
| A mapping removed, leaving one | `RESTATING` + column dropped | `_source` goes with the merge; dropping a column a metric references is the existing `ContractViolation` |
| A mapping's key expression changed | `BREAKING` | Redefines what a row *is* — the existing rule at [`plan/diff.py#L218`](../src/bloomery/plan/diff.py#L218) |

**`_source` exists only on merged entities**, which is what makes the first row two changes
rather than one. An earlier draft claimed a mapping addition causes "no column change";
that was wrong, and it matters more than the class does — the class is `ADDITIVE` either
way, so the error would have survived into implementation as a comment nobody re-derived.

The alternative — emitting `_source` on *every* mapped entity so the column set never
depends on mapping count — is rejected: it churns every golden in the corpus for a column
that is a constant in the single-source case, and puts a bloomery-invented column in every
relation forever to spare one classified change. The transition showing up in `plan()` is
the better outcome anyway: it is exactly the kind of schema move an operator should see
before it lands, and a silent uniform column is how it would have been hidden.

The two removal rows are the ones worth verifying during implementation. The second is the
sharp one: dropping back to a single mapping removes `_source`, and if anything downstream
reads it the existing contract check must fire.

### 5.6 The quality-system boundary

An earlier draft of this document designed the union and said nothing about RFC 0016's
machinery. Reading the code showed the two meet in more places than §3 recorded, and in one
of them the meeting is a **blocking audit that would refuse valid data**.

**The row identity is per source, and a blocking audit assumes it is per entity.** The
generated metadata audit is, verbatim:

```sql
SELECT *, COUNT(*) OVER (PARTITION BY _source_row_id) AS _row_id_count FROM @this_model
```

`_source_row_id` is bronze's row identity (RFC 0016 D21), unique *within a source relation*.
On a merged entity `@this_model` is the union, so two sources whose row ids are ordinary
per-table sequences collide on the first run — and the audit is blocking. That is a false
refusal on correct data, which D13 already names as the worst failure available to a
generated audit. It fires whenever the entity declares `dedupe:` **or** `quarantine:`, since
that pair is the audit's emission condition.

**The reject table is one per entity by a decision that assumed one mapping.**
`emit/lower/silver.py` records it: *"one per entity, never per mapping (RFC 0016 §5.6, D10):
per-mapping tables multiply into the small-file problem and make replay N-way."* A merged
entity is N-way by construction, and `source_relation`, `mapping` and `mapping_version` are
compile-time literals off the single mapping. `reject_id` survives — it is already a digest
of `(source_relation, row identity)`, so the pair was designed for this — but **replay
re-runs *the* current mapping**, and making it branch per source is precisely the N-way
replay D10 rejected.

**So P1 draws the boundary at the two block-level declarations**, and the boundary is exact
rather than approximate: every use of the row identity in the silver lowering sits behind
one of them — the reject projection, the conservation audit, the dedupe sort key, and the
replay merge. The `on_fail: fail` audit path (`emit/lower/predicates.py:audit_predicate`)
references it **zero** times.

A merged entity in P1 may therefore still carry field rules and row rules with `on_fail:
flag` and `on_fail: fail`, `assert:` clauses, `references:` and `coverage:` checks. What it
may not carry is `dedupe:` or `quarantine:`, refused at compile time with a message naming
the reason. This matches RFC 0016's own framing — joining the quality system is per entity
and explicit — rather than inventing a new kind of exclusion.

> **Correction (execution, D29).** The first sentence of that paragraph is wrong, and the
> error is a consequence reaching further than the argument that produced it. This section
> establishes its boundary by tracing **the row identity**, and that trace is sound; it then
> generalises to the whole quality system, which the code does not support. Rule *lowering*
> is per mapping and sits behind neither block — `lower_quality` takes one `Mapping`,
> `opts_in` reads that mapping's field-level `quality:` blocks and also selects the
> `TRY_CAST` shape, and the generated `coercible`/`enum` rules embed one mapping's source
> paths and transform chain into a rule evaluated over the merged relation. So the P1
> boundary is `opts_in`, not `dedupe:`/`quarantine:`. `assert:`, `references:` and
> `coverage:` do survive: they are lowered from the entity model and the draft IR, never
> from a mapping. D29 carries the argument and the measurements; the sentence is left
> standing rather than rewritten, because what it claimed is the thing D29 has to be read
> against.

**What that costs, stated rather than discovered later.** With `dedupe:` refused, nothing
between the union and the model output collapses rows, so §5.4's collision audit can read
the model directly and D13's careful distinction — read the union stage, *not* `silver.x` —
becomes untestable in P1: the test it names ("a collision `dedupe:` would have collapsed")
cannot be written, because no collapse exists. D13 is not weakened, it is unexercised, and
it returns with the P2 that restores `dedupe:`. Shipping a simpler audit that resembles the
designed one without saying so is the failure this paragraph exists to prevent.

### 5.7 Where the lowered expression lives (answers D25)

A union needs one projection per source per column, and `ColumnIR` carries exactly one
`expr`. The shape that fixes it is not invented here — **the seam already exists**, in the
signature of the function that builds the node:

```python
def _column_ir(name, field, declared, expr, catalog, *, recipe_id=None) -> ColumnIR:
```

Everything `_column_ir` derives from `field` and `catalog` is **entity-scoped**: `name`,
`type` (the entity's *declared* type), `canonical`, `unit`, `tax_basis`, `required`,
`description`, and `renamed_from` — which is declared on the EntityModel `Field`
(`spec/entity.py:58`), not on a mapping. Exactly two arguments come from the mapping:
`expr` and `recipe_id`.

So the split is along a line the code already draws, and the schema half is *provably*
identical across mappings rather than merely expected to be — it is computed from the
entity model, which every mapping targets. §5.2 rule 4's type agreement is the same fact
seen from the other side: each mapping's chain is checked against the declaration, so two
mappings cannot disagree about a column's type without both failing first.

**The shape.** `ColumnIR` sheds the two mapping-derived fields; a new column-grained node
carries them per source:

```python
class ColumnIR:            # EntityIR.columns — the merged schema
    name, type, canonical, unit, tax_basis, renamed_from, required, description

class SourceColumnIR:      # SourceIR.columns — one projection, per source
    name, expr, recipe_id
```

**Not on `SourceFieldIR`**, which is the tempting shortcut and is wrong: that node is
*path*-grained — a recipe field mapping produces one `SourceFieldIR` per required path and
a single column — so hanging `expr` there would duplicate one expression across a recipe's
paths and leave no single place to read it from. `SourceIR` gains a second collection
rather than overloading the first, and the two answer different questions: `fields` is what
the reject payload and replay read, `columns` is what the SELECT projects.

**Where it lands in the builder**, which is why this is cheap: `_build_entity` already
appends to `columns` and `source_fields` in one loop, side by side. `_column_ir` splits into
a schema constructor and a projection constructor called from the same place, and the union
is then a `UNION ALL` over `SourceIR.columns` in `sources` order.

**`_column_ir` is not the only site that builds a lowering, and D27 is the one it misses.**
`guardrails/conflict.py:_shadow` constructs a `ColumnIR` carrying a lowered `expr` *after*
the builder has run — the `<field>__direct` shadow the guardrail stage merges into an
entity — so the split has a second constructor to feed, and a merged entity raises a
question about how many shadows a `direct:` path produces. See D27.

### Alternatives considered

**Leave it to a Tier 3 step (the status quo).** It works today and is the honest current
answer. Rejected as the *permanent* answer because the cost is disproportionate to `UNION
ALL` — a registry entry, a Python model, a runtime contract, SQLMesh only — and because the
question RFC 0021 poses returns "yes, yes, yes" here where it returns "no" for identity
resolution. A step is the right home for what bloomery cannot check; this is not that.

**A new `union:` spec kind, or a `sources:` list on the entity.** More explicit, and a
reader would see at a glance that an entity is merged. Rejected because it duplicates
information already carried by `target:` and creates two ways to say where an entity comes
from — with the failure mode that they can disagree.

**Allow overlapping keys with a declared precedence** (`priority: [billing, crm]`).
Tempting, and it is what most tools do. Rejected: a precedence rule is business logic
bloomery can neither typecheck nor guardrail — it cannot tell a correct priority from an
inverted one, and the wrong one silently prefers stale rows. Refusing overlap keeps the
merge inside what the compiler can defend, and the step remains for the rest.

**Emit `UNION` (distinct) rather than `UNION ALL`.** It would make the collision audit
unnecessary for exact duplicates. Rejected because it hides them: two sources agreeing on
every column of one key is still a fact the operator should see, and `DISTINCT` over a wide
relation is an expensive way to be silent.

## 6. Tests

- **`multi_source`** — the fixture RFC 0009 D4 named, built at last: two sources, one
  shared key space, disjoint key sets. Golden, execution and e2e, matching the tiers the
  `identity_resolution` fixture runs.
- **A collision variant** seeded so the audit fires, asserted as a *blocking* failure
  rather than a flag. This is the case that must be verified red — a union whose collision
  audit silently passes is worse than no union. The seed must be a collision **`dedupe:`
  would have collapsed**, which is the only version of this test that distinguishes D13's
  audit placement from an audit reading `silver.<entity>`.
  > **Scope (execution, D14).** The second sentence of that seed requirement cannot be met
  > in P1 and is deferred with `dedupe:` itself. With no dedupe on a merged entity nothing
  > collapses rows between the union and the model output, so there is no collision a
  > reader could hide — the audit reads the model and the distinction D13 draws is
  > unexercised rather than weakened. The collision test still runs, verified red; what
  > waits for P2 is the *placement* half of it.
- **A composite-key fixture.** The single-column example in §5.4 passes with a partial-key
  audit; only a composite key catches a generated `GROUP BY` that dropped a component.
- Compile-time refusals: partial key, missing required field, and two mappings naming one
  source (D12). Each with the source path of the offending mapping, not the entity. The
  "unacknowledged absent field" case is gone with D22 — there is no acknowledgement, and
  the typo it would have caught is already a `MissingReference`.
- The D14 boundary as D29 widens it: a merged entity that joins the quality system at all is
  refused — `dedupe:`, `quarantine:`, an entity-level `quality:` block, and a field-level
  `quality:` block on any of its mappings, each asserted separately, since `opts_in` is a
  disjunction and a test of one leg proves nothing about the others. Plus a merged entity
  mixing a mapped source with a step output (D21), and `scd: type2` with more than one
  mapping (D23). Each of these is a shape that compiles today for one mapping, so each needs
  a test proving the refusal arrives only when a second one does. And the converse, which is
  what keeps the refusal from being a wider one wearing D29's name: `assert:`,
  `references:` and `coverage:` on a merged entity all compile.
- **Determinism**: the two mappings declared in both orders in the project must produce
  byte-identical artifacts. This is the assertion that pins D3, and it belongs in the
  existing cross-`PYTHONHASHSEED` harness.
- The plan classifier over `multi_source` with a source added and removed, asserting the
  §5.5 table.
- Sabotage: removing the lexicographic sort must break the determinism test; weakening the
  audit to `flag` must break the collision test.

## 7. Docs

- A how-to on merging sources, paired with `resolve-identities.md` and **cross-linking in
  both directions**. The pair is the point: one page for "same key space, disjoint keys",
  one for "different key spaces, needs matching", each naming the other. Today the second
  exists alone and reads as the answer to both.
- `pages/docs/concepts/` — the entity model as an integration layer, which is what this
  makes true.
- The `_source` column and the collision audit in the reference, beside the other system
  columns.

## 8. Out of scope

- **Overlapping keys with precedence.** §4 and the alternatives above; the escape hatch is
  a step, and D5's refusal message names it.
- **Sources with different key spaces** — identity resolution, RFC 0021, unchanged.
- **Per-source quality rules.** Rules apply to the merged relation. A rule that must fire
  on one source only is expressible as an expression over `_source`, which is why that
  column being real matters; a per-source rule *syntax* is not built.
- **Union of entities that are not both mapped from bronze** — e.g. merging a step output
  with a mapped source. Coherent, and it needs the step-output entity synthesis (RFC 0017
  D36) to interact with union ordering. Named, not designed.
- **Schema evolution across sources** — one source gaining a column the others lack is
  handled by §5.2 rule 3 (NULL, acknowledged); a *migration* between source shapes is
  `plan()`'s job and unchanged.

## 9. Risks

- **Read as identity resolution.** The most likely misreading, and it would undo RFC 0021's
  settlement. Mitigated by the refusal message naming the step, by the docs pair in §7, and
  by the collision audit being non-negotiable — a merge that cannot be talked into
  tolerating overlap cannot be mistaken for a matcher.
- **Silent NULL fill hides a typo.** A misspelled field name looks exactly like a field one
  source genuinely lacks. §5.2 rule 3 requires acknowledgement for that reason; if D8 lands
  as "no acknowledgement needed", this risk is accepted rather than mitigated, and the
  decision row should say so.
  > **Correction (execution, D22).** This risk does not exist. A mapping naming a field the
  > entity model does not declare is already refused today — `MissingReference: mapping maps
  > unknown field 'loyalty_teir' of entity 'order'`, measured on this tree against the
  > single-mapping path. A misspelling is therefore a compile error, not a silent NULL, and
  > the only thing an acknowledgement could mark is a *correctly spelled* field a source
  > deliberately lacks — the legitimate case, not the dangerous one. Corrected in place
  > rather than left standing: this is a claim about how the compiler behaves, not a
  > decision, and preserving a false one would make the decision table argue from it.
- **The disjointness guarantee is run-time.** Compilation cannot establish it, so a project
  can pass every compile-time check and fail on first run. That is the correct split and it
  is the same one `dedupe` and `referential` already live with — but the docs must not
  describe the union as *verified* disjoint.
- **`_source` becomes load-bearing for users.** Once it exists, projects will filter on it,
  and it becomes a compatibility surface. Accepted: it is a system column like
  `_quality_flags`, and the stability policy already covers those.

## 10. Unresolved questions

- **What does an absent optional field require?** §5.2 rule 3 says acknowledgement and D8
  leaves the spelling open. Reusing `unmapped:` is the obvious move but its current meaning
  is source-column-shaped, not entity-field-shaped, so the reuse may be a pun rather than a
  fit.
- **Is `_source` the mapping's `source:` or the mapping document's name?** They differ when
  two mappings read one source relation. The source relation is the more useful provenance;
  the document name is the more useful diagnostic.
- **Should the collision audit be emitted when the entity has only one mapping?** Emitting
  it unconditionally makes the artifact set uniform and costs a scan; emitting it only for
  merged entities makes the artifact set depend on mapping count. §5.4 assumes the latter.
- **How does this interact with `scd: type2`?** A merged historical entity has versions per
  source, and the collision audit as written would fire on every key with two versions from
  different sources. Probably the audit must read the current version only — which needs
  the validity columns RFC 0023 §5.3 proposes and does not build. **Refusing the
  combination until then is the likely answer**, and it is not designed here.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | Several mappings may target one entity; they are merged with `UNION ALL`. This replaces the refusal at `resolve/build.py:849` and keeps the promise its message makes. Consequence: `EntityIR` gains a set of source mappings where it had one, and every consumer reading "the mapping" of an entity must be revisited. |
| 2 | `LOCKED` | **No new syntax.** Multi-source is expressed by two mappings naming one `target:`. A `sources:` list or a `union:` kind would duplicate what `target:` already says, with the failure mode that the two can disagree. |
| 3 | `LOCKED` | Mappings are unioned in **lexicographic order of source name**, so the emitted artifact is byte-identical across processes. Row order is explicitly **not** claimed — `UNION ALL` is a bag, and nothing downstream may depend on source order. |
| 4 | `LOCKED` | Every mapping must produce the entity's **full declared key** and **every required field**. A partial key makes the union meaningless; a NULL-filled required field is a broken contract silently created by the merge. |
| 5 | `LOCKED` | A key appearing in more than one source is refused by a generated **blocking** audit (`on_fail: fail`), not configurable to `flag` or `quarantine`. Overlap is either duplication or a shared key space by accident, and both are refusals. The message names the identity-resolution step as the escape hatch. Consequence: bloomery's union is for disjoint key sets, permanently — matching stays a step, and RFC 0021 is not reopened. |
| 6 | `LOCKED` | The union is the **first** silver stage: union → dedupe → rules. A rule evaluated per source would judge rows the merged relation does not contain, which is the same argument that fixed dedupe-before-rules in RFC 0016. |
| 7 | `ASSUMED` | A `_source` system column carries provenance. It is load-bearing rather than diagnostic: the collision audit reports which sources collided, and without it the report is unactionable on a multi-source entity. |
| 8 | `OPEN` | Whether an optional field a mapping does not produce needs explicit acknowledgement, and in what spelling. Silence is indistinguishable from a typo, which argues for acknowledgement; `unmapped:` is the nearest existing mechanism but is source-column-shaped. Whoever builds it decides and logs it. |
| 9 | `ASSUMED` | Change classification needs no new class — but adding a mapping to a single-source entity is **two** `ADDITIVE` changes, rows and the `_source` column, not one. `_source` exists only on merged entities (D7), so the column set does depend on mapping count; emitting it everywhere to avoid that would churn every golden in the corpus for a constant. Verify the removal rows during implementation: dropping to one mapping removes `_source`, and anything reading it must trip the existing contract check. |
| 10 | `OPEN` | `scd: type2` combined with multi-source. The collision audit would misfire across versions, and fixing it needs validity columns nothing models (RFC 0023 §5.3). Refusing the combination is the expected answer; whoever builds this decides and logs it. |
| 11 | `OPEN` | Whether the union stage emits a generated `IS NULL` audit over `required: true` columns. D4's coverage check proves each mapping *declares* the field and proves nothing about what its source path returns per row — `required:` is a schema declaration, and the runtime null check is the separate `assert: {not_null: true}` mechanism. The asymmetry predates this RFC; a merge makes it worse, because one bad source poisons a column the others fill correctly. Whoever builds this decides, and the decision is either the audit or an explicit statement that `required:` means coverage only. |
| 12 | `LOCKED` | `(target, source)` is **unique**: two mappings for one entity may not read the same source relation. Lexicographic ordering needs a total order and two branches on one relation tie, which would leave branch order undefined, `_source` ambiguous, and the collision audit unable to name a branch. Consequence: reading one relation twice is expressed as one mapping with a filter, not two mappings. |
| 13 | `LOCKED` | The collision audit reads the **union output, before dedupe**, and groups by **every** declared key column. Reading `silver.order` would let dedupe collapse the colliding rows before the audit counts them — the audit would be checking the one relation guaranteed not to contain what it looks for. Grouping by a partial key would merge distinct composite keys and block valid data, which on a blocking audit is the worst failure available. |
| 14 | `LOCKED` | **P1 refuses `dedupe:` and `quarantine:` on a merged entity** (§5.6). The boundary is drawn at those two block-level declarations because it is exact, not approximate: every use of the per-source row identity in the silver lowering sits behind one of them — the reject projection, the conservation audit, the dedupe sort key, the replay merge — and the `on_fail: fail` audit path references it zero times. A merged entity may still carry field and row rules (`flag`/`fail`), `assert:`, `references:` and `coverage:`. Consequence: P1 ships the union to entities with no dedupe and no quarantine, which is the shape the `multi_source` fixture needs, and the two blocks return in P2. |
| 15 | `ASSUMED` | **Discovery: the metadata audit would refuse valid data on a merged entity.** It is `COUNT(*) OVER (PARTITION BY _source_row_id) > 1` over `@this_model`, and `_source_row_id` is unique per *source relation* (RFC 0016 D21), so two sources with ordinary per-table row sequences collide on the first run — a **blocking false refusal**, the failure D13 names as the worst available. The one-word fix (`PARTITION BY _source, _source_row_id`) is deliberately not taken in P1: it makes the audit body depend on mapping count, which is the same "does the artifact shape vary" question as D7 and belongs with the reject-table decision in P2 rather than scattered ahead of it. |
| 16 | `LOCKED` | **RFC 0016 D10 is not reopened here.** That decision chose one reject table per entity *on the ground that per-mapping tables make replay N-way*, and a merged entity is N-way by construction. `reject_id` itself survives — it is already a digest of `(source_relation, row identity)`, so the pair was designed for exactly this — but replay re-runs *the* current mapping, and branching it per source is the thing D10 refused. N-way replay gets its own RFC, argued against D10 directly, rather than being decided inside a feature branch. |
| 17 | `ASSUMED` | **`bloomery_ir_version` 5 → 6.** `EntityIR` gains its source tuple, and the canonical encoder writes each dataclass's field names and count, so every fingerprint moves whether or not a project merges anything. Stated because it is exactly what went unstated at v4, where the bump was missed and only the encoder's own strictness kept it honest. `plan()` refuses to diff a v5 IR against a v6 one. |
| 18 | `LOCKED` | **`_source` joins `RESERVED_MEMBER_NAMES`.** Every other generated column is reserved — `_quality_flags`, `_quality_ok`, `_load_id`, `_ingested_at`, `_source_row_id`, `has_quality_flags` — and a generated column that is not is one an author can collide with. Reserved unconditionally, not only on merged entities: a name that is legal until a second mapping arrives is a trap laid for the change that adds one. |
| 19 | `ASSUMED` | **The quality mart accounts per entity, not per source.** Its mapping identity is `f"{source.relation}->{entity.name}"`, which has no single value on a merged entity. Per entity, because the mart's row is "one rule evaluation on this entity" and the rules run on the merged relation (D6) — a per-source split would report rule counts against a population the rule never saw. Provenance is still reachable: `_source` is a real column, so a per-source view is a filter rather than a schema. |
| 20 | `ASSUMED` | **dbt emits one `source()` per mapping**, and the model body unions them. Nothing about the union needs a dbt capability it lacks, so refusing it there — as dbt is refused for `python_model` steps, mart assertions and reject tables — would be a limitation invented rather than found. |
| 21 | `LOCKED` | **A merged entity may not mix a mapped source with a step-produced output**, refused explicitly rather than left to fail somewhere downstream. §8 already puts it out of scope; this is the refusal that makes the scope real, since a step output entity carries `produced_by` and no mapping at all, and the union has nothing to order it by. |
| 22 | `ASSUMED` | **Answers D8 (`OPEN`) — no acknowledgement, and §9's premise for wanting one is false.** A mapping naming a field the entity model does not declare is *already* refused: `MissingReference: mapping maps unknown field 'loyalty_teir' of entity 'order'`, measured on this tree against the existing single-mapping path. So a misspelling is a compile error rather than a silent NULL, and the only thing an acknowledgement could mark is a correctly-spelled field a source deliberately lacks — the legitimate case. Adding a key for that would also strain D2's "no new syntax", to flag the one shape the RFC agrees is fine. §9's risk row is corrected in place. |
| 23 | `ASSUMED` | **Answers D10 (`OPEN`) — `scd: type2` plus multi-source is refused.** The expected answer, and D14 makes it cheap: the collision audit would fire on every key holding versions from two sources, and distinguishing a version from a collision needs the validity columns RFC 0023 §5.3 proposes and does not build. Refused with a message naming that dependency, so the refusal routes rather than merely blocks. |
| 24 | `ASSUMED` | **Answers D11 (`OPEN`) — `required:` means coverage, and the runtime null check stays `assert: {not_null: true}`.** No generated `IS NULL` audit. D11 framed the choice as the audit or an explicit statement; this is the statement. Generating one for merged entities only would make a third thing depend on mapping count, and the authored mechanism already exists, is documented, and lowers to the same audit a generated one would emit. §7's how-to says to use it on required fields of a merged entity, which is where a reader meets the asymmetry. |
| 25 | `OPEN` | **Where per-source column expressions live — the IR restructure D1 understates, found by building.** D1 says `EntityIR` "gains a set of source mappings where it had one", which reads as a one-field change. It is not: `ColumnIR` carries **one** `expr: SqlExpr`, lowered from *the* mapping's field (`resolve/build.py:_column`), and a union needs one projection per source per column — different source paths and different transform chains. No arrangement of `EntityIR.sources` alone can express that, so the union cannot be emitted until this is settled. Three shapes, none free: **(a)** `SourceIR` gains `columns`, and `EntityIR.columns` becomes the merged *schema* (name, type, canonical, unit, tax_basis, required) with `expr`/`recipe_id` moving per-source — correct, and it touches the IR's central node plus 37 `.columns` read sites outside marts, `plan/diff.py:338`'s `column.expr.sql`, and the guardrails that walk derivations; **(b)** keep `expr` on `EntityIR.columns` as the first source's — a lie on every merged entity and exactly the silent-wrong-answer this project refuses; **(c)** `ColumnIR.exprs` as a tuple index-coupled to `sources` — no new node, and a coupling nothing enforces. **Lean (a).** Whoever takes this decides and logs it *before* writing the union, because it decides what P1 costs. |
| 26 | `ASSUMED` | **Answers D25 (`OPEN`) — option (a), and D25's blast-radius figure was wrong by an order of magnitude.** The lowered expression moves to a new column-grained `SourceColumnIR` on `SourceIR`; `ColumnIR` keeps the schema (§5.7). D25 said "37 `.columns` read sites" and estimated the cost from that; measured, **exactly 8 sites read a `ColumnIR` lowering field, in 3 files** — `plan/diff.py` (`renamed_from` ×4, `recipe_id`, `expr.sql`) and `emit/lower/silver.py` (`expr.ast()` ×2). Four of those eight are `renamed_from`, which D25 mis-assigned to the lowering half and which is declared on the EntityModel `Field`, so it does not move at all. The 37 was a count of `.columns` readers, and `.columns` readers are overwhelmingly *schema* readers — they survive untouched, which is the whole point of the split. **Real cost: two constructors where there was one, and four call sites.** The golden churn stands regardless — the IR shape moves and D17 bumps the version. |
| 27 | `OPEN` | **The `direct:` shadow column builds a lowering outside the builder, and on a merged entity it is not one column.** `guardrails/conflict.py:_shadow` constructs a `ColumnIR` with a lowered `expr` — the `<field>__direct` extraction that the reconcile audit compares a recipe-derived value against — and the guardrail stage merges it into the entity after `_build_entity` has finished. Under D26's split that constructor has to produce a schema column *and* a projection, which is mechanical. What is not mechanical: **the direct extraction reads a source payload**, so a merged entity needs one shadow projection per source, and D14 does not refuse the combination — `direct:` is a catalog-recipe property, unrelated to `dedupe:`/`quarantine:`. Three options: emit one shadow projection per source and keep the audit comparing the merged column (probably right, and it is the same fan-out the union already does); refuse `direct:` on a merged entity in P1 (cheap, and it narrows a capability for a reason unrelated to it); or refuse the whole path-conflict amendment there (worse — it removes a check rather than scoping it). Decide before writing the split, not during: the shadow is built from a `Derivation`, which is per entity and not yet per source. |
| 28 | `LOCKED` | **Answers D27 — a `direct:` path is refused on a merged entity in P1.** `direct:` is a field of `RecipeFieldMapping`, so it is per mapping, and two mappings may record *different recipes* for one column — `recipe_id` is in the lowering half for exactly that reason. A merged entity can therefore have a direct path on one source and none on another, which leaves the `<field>__direct` shadow NULL for the second source's rows. That is not a gap to fill: a NULL shadow is indistinguishable from a genuinely NULL direct value, so the reconcile audit either reports a false disagreement or silently skips rows it was built to check — and a check that quietly stops checking is worse than one that is absent. **The cost of refusing is measured, not assumed: `direct:` appears once in the entire corpus** (`tests/fixtures/path_conflict/mapping.yaml`), so no project shape loses anything. P2 chooses between one shadow projection per source with a null-safe audit, and a coverage rule in D4's shape (if any mapping records a direct path, all must); this RFC does not pick, because the choice is about what a reconcile check *means* across sources and that deserves the argument. Consequence for D26: `_shadow` only ever runs on a single-source entity, so the split feeds it the same way it feeds `_column_ir` and nothing about it becomes N-way. |
| 29 | `LOCKED` | **§5.6's consequence was wider than its argument — P1 refuses the whole quality system on a merged entity, not only `dedupe:` and `quarantine:`.** D14's *reason* survives measurement: every use of `_source_row_id` in the silver lowering does sit behind one of those two blocks. Its *consequence* — "a merged entity may therefore still carry field rules and row rules" — does not follow, because the row identity is not the only per-mapping coupling. **The rule lowering itself is per mapping, and sits behind neither block**: `lower_quality(entity, mapping, …)` takes one `Mapping` (`resolve/build.py`), so `mappings[0]` would silently win; `opts_in(entity, mapping)` is true when *that mapping's* fields carry `quality:`, so two mappings can disagree about whether the entity joined the system at all — and that same predicate selects `_try_cast_shape`, so opt-in reaches column lowering; a generated `coercible` rule carries `field_sources(mapping, column)`, *that mapping's* raw JSONPaths, which the extract projects per branch, so source B's branch would have to read source A's `$.a.b` off a relation that need not have it, for a rule evaluated once over the merged relation; generated `enum` spellings come from the mapping's transform chain the same way; and `check_quality`'s `by_target` dict keeps the **last** mapping per target, so every per-mapping quality guardrail would check one of N. The boundary D14 wanted — exact rather than approximate — is therefore `opts_in`, one predicate that already exists and already decides this. **`assert:`, `references:` and `coverage:` survive**, measured rather than assumed: `lower_asserts` reads the entity model and the draft IR and never a mapping, and the relationship-driven checks are entity-model-shaped. Consequence: P1 ships the union to entities outside the quality system, which is the shape the `multi_source` fixture needs, and P2 restores the system to a merged entity as one piece rather than in two unrelated halves. *Added by execution 2026-08-16 — see logs/T-0004.md (V-001, attempt 1).* |
| 30 | `ASSUMED` | **Departs from D20 — the dbt target refuses a merged entity in P1**. D20's claim about the *union* holds and shipped: the `UNION ALL` is the same shared SELECT both targets render, and the dbt emitter does emit one `source()` per mapping. What D20 did not account for is that the merge's correctness condition is a **blocking audit** (D5), and this emitter has no artifact for one: its whole test surface is `schema.yml` entries covering `not_null`, `accepted_values` and a single expression test, and it emits no singular-test path at all. A generated `GROUP BY <key> HAVING COUNT(DISTINCT _source) > 1` is none of those. Emitting the union without it produces a model that compiles here, runs anywhere, and double-counts an entity in silence — the degradation RFC 0008 D3 refuses. **RFC 0016 §5.4's target-coverage sentence deliberately was not stretched to cover this**: it authorizes dbt's partiality for the *quality* artifacts, and a rule an author chose to make blocking is not the same thing as the one check a feature cannot be correct without. Consequence: merged entities are SQLMesh-only until the dbt emitter grows a singular-test surface, which is its own change and not P2's. D20's row is left standing — what it predicted is the thing this has to be read against. *Added by execution 2026-08-16 — see logs/T-0004.md (V-002, attempt 1).* |
| 31 | `LOCKED` | **P2 is demand-gated: the design lands now, the code waits for a named consumer.** RFC 0023 D6 applies this test to its own P2 and this document did not, which left §12 reading as a queue rather than a boundary. The asymmetry has no justification — P1's refusals are honest, tested, and route to the shipped workaround, so nothing is broken while P2 is unbuilt, and P2a's cost falls on RFC 0016's rule catalogue, which every entity reads, merged or not. What is **not** deferred is the design: D29's couplings were measured against this tree while P1's context was live, and that context is the asset that decays — the prose does not. So D32–D35 are settled here and §12's P2a–P2c are specified; implementation begins when a project needs quality rules on a merged entity, and not before. Consequence: the two refusal messages stop saying "until P2 restores it". A promise in an error message is one a user plans around, and this decision makes P2 a phase rather than a date. |
| 32 | `LOCKED` | **A rule's per-mapping dependency is projected as a branch-local column; the rule stays entity-grained (P2a).** The mechanism is not invented here — `coercible` already reads projected `_src_<rule>_<n>` aliases (`quality/predicates.py:source_alias`) rather than inline JSONPaths, because the raw paths live one level down in the extract SELECT, and P1 turned that projection site into `_branch_select`. So a fact only one branch knows already has a way to reach a rule the merged relation evaluates once. **D6 is not violated, and the reading that says it is — that projecting a verdict per branch just *is* "a rule evaluated per source" — mistakes what D6 argues.** D6 argues from the *row population* — "a rule evaluated per source would judge rows the merged relation does not contain" — and the union is `ALL`, so a branch-projected **scalar** verdict judges exactly the rows the union contains. Dedupe runs after the union and may drop a row; that row's flag is then unused, which is not a wrong answer. **The boundary is `WINDOWED_KINDS`** (`quality/predicates.py`, currently `{unique}`): a windowed verdict depends on the population and so may not be computed per branch — and it does not need to be, since its inputs are the produced column values, which D26's split already makes mapping-invariant. Consequence: `coercible` sheds its per-source alias set for one branch-computed boolean ("every source path *this branch* read was non-null"), which collapses the arity problem at the level where arity is known; `in_enum` takes the same shape rather than a second mechanism, its admissible set being the branch's own `enum_map` chain. **The tempting wrong fix is recorded so it is not re-proposed:** NULL-filling a missing `_src_` alias to make the arities agree renders `is_not_null` false, the conjunction never fires, and the rule silently stops checking on that branch — the failure D28 refuses by name, a check that quietly stops checking being worse than one that is absent. |
| 33 | `LOCKED` | **Every mapping of an entity opts into the quality system, or none does; disagreement is refused (P2a).** `opts_in(entity, mapping)` is a disjunction over one mapping's field-level `quality:` blocks, so two mappings can disagree about whether the entity joined the system at all — and the same predicate selects `_try_cast_shape`, so the disagreement reaches column lowering and not only rule generation. This is not the "where is it computed" question D32 answers; it is two contradictory statements by an author, and the honest response to those is a refusal naming both source paths. It also settles a **fourth** per-mapping coupling D29 did not enumerate: `_repair_bodies` (`resolve/build.py`) reads `mapping.fields[<column>].quality[].repair`, so two mappings may name different repair recipes for one column. Under agreement that is the same refusal rather than a fifth case — and the spliced body itself is invariant, since it reads the *produced* column, not a source path. Consequence: `lower_quality` may go on taking one `Mapping`. Agreement is what makes any of them the same answer, and the refusal — not a merge rule — is what makes that safe. |
| 34 | `LOCKED` | **Artifact shape varies with mapping count; `_source` stays merged-only (P2b).** The question D7 and D15 both defer, answered once for the provenance column, the metadata audit body and the collision audit together. The metadata audit becomes `PARTITION BY _source, _source_row_id` on a merged entity and stays `PARTITION BY _source_row_id` elsewhere. **The cost is a new precedent, stated here rather than discovered later:** until now the *set* of emitted artifacts varied with a spec, never a generated **body**. The alternative — `_source` on every entity, one uniform audit body, mapping count invisible in the artifacts — buys a reader the property that a merged entity looks like any other, and costs a corpus-wide golden re-stamp plus a constant column on every single-source silver model, which is precisely what D9 declined to pay on measured grounds. Continuing that decision is cheaper than reversing it, and reversing it buys nothing but uniformity. **A third option is named only to close it:** making `_source_row_id` globally unique in bronze would dissolve the question, and it does so by relocating the problem into RFC 0016 D21's ingestion contract and breaking every table already landed under it. |
| 35 | `LOCKED` | **`_source` joins the dedupe sort key, immediately ahead of `_source_row_id` (P2b).** `dedupe_sort_columns` ends in the row identity, and its totality argument is "no two rows can compare equal *given the D21 metadata contract*" — an identity unique per **source relation**. On a merged entity two rows from different sources sharing an entity key therefore compare equal and the survivor is undefined. That shape is what D5's collision audit refuses, but an audit runs *after* the model materialises, so the window is real and the totality argument would be leaning on a blocking check in a different artifact. Adding `_source` restores it structurally and locally, for one extra sort term on merged entities only (D34). It is the same defense-in-depth already pinned into that exact column by `NULLS LAST`, against an illegally-null identity the audit also catches. Consequence: where two rows would have compared equal, the survivor is the lexicographically-later source — arbitrary as business logic, deterministic as an artifact, and reachable only in the run the collision audit then stops. |

## 12. Phasing

**P1 — §5.1–§5.7.** The IR split (§5.7), the union, the compile-time checks, the collision
audit, `_source`, the plan-classifier rows, and the `multi_source` fixture — with `dedupe:`
and `quarantine:` refused on a merged entity (D14).

**Take the IR split first, on its own.** `ColumnIR` shedding two fields into
`SourceColumnIR` is a pure refactor while every entity still has one source: same emitted
**SQL**, same behaviour, with only the `fingerprint:` header moving — one version bump, and
the whole golden corpus re-stamped once. (An earlier line here said "same emitted bytes",
which contradicts the re-fingerprint in the same sentence.)
Landing it before the union means the diff that adds multi-source is about multi-source,
and the corpus churn is not sitting on top of it — which is the difference between a
reviewable change and a large one. It is *not* release-gating: the refusal
it replaces is honest, tested, and names its own limitation, so shipping 0.1 without this
costs nothing but capability.

An earlier version of this section said "the whole of §5" and called the design "one
coherent unit". Reading the code found that it is not: the union is one unit and the union
*combined with the quality system* is another, and the second has a blocking audit in it
that would refuse valid data (D15). Splitting them is what makes P1 executable in one pass.

**P2 — the quality system on a merged entity. Demand-gated (D31).** The design below is
settled; the code is not scheduled, and the trigger is a project that needs quality rules on
a merged entity. Splitting the phase in three is what makes the gate mean anything: P2c is
blocked on a document that does not exist, and burying that inside one phase would let "P2"
name work of three different readinesses.

**P2a — rule lowering becomes mapping-invariant.** An earlier version of this section said
P2 "starts with rule lowering, which has to become per source or be proven
mapping-invariant"; D32 and D33 say which, and it is neither of those two. A per-mapping
*dependency* becomes a branch-local projection the entity-grained rule reads (D32), and a
per-mapping *disagreement* becomes a refusal (D33) — so the rule set is invariant because
the compiler makes it so, not because it was proven to be. Then D29's refusal narrows back
to D14's boundary, `dedupe:` and `quarantine:`, and §6's converse tests invert. Two carried
items land with it, both from the deviation log: **V-003**, because a rule over `_source` is
the referent D9's contract half had none of; and **V-006**, because `quality_mart.py`'s
raising `_sole_source` accessor fires on the first merged rule, so D19's answer has to be
implemented rather than deferred behind a guard.

**P2b — `dedupe:`.** D34 answers the artifact-shape question D7 and D15 both left, and D35
the sort key. The third piece is forced rather than chosen: with dedupe between the union and
the model output, D13's placement becomes load-bearing, and the collision audit moves from
reading the model to reading the union stage. That is also what makes §6's deferred seed
writable at last — a collision `dedupe:` *would have collapsed* — and it is the only test
that proves the audit moved rather than this document merely saying so.

**P2c — `quarantine:`.** Blocked on an RFC that is not written. The reject table's
`source_relation`, `mapping` and `mapping_version` are compile-time literals off one mapping
(`quality/reject.py`), and RFC 0016 D10 chose one table per entity *because* per-mapping
tables make replay N-way. D16 is `LOCKED` that reopening it gets its own document, argued
against D10 directly. So P2c is gated twice — on D31's consumer and on that RFC — and
starting it before both is exactly how D16's argument would end up as a paragraph inside a
feature branch, which is the thing D16 refuses.

**Not P2 — the dbt target.** D30 makes merged entities SQLMesh-only, and lifting that needs
a singular-test surface in an emitter whose whole test vocabulary is `schema.yml` entries.
It is independent of everything above, needs no IR change, and is the one item here a
shipped user meets today — so it is its own RFC under its own gate, not P2's tail.

Sequenced **after** RFC 0023 P1 if both are taken: D23 needs an answer for `scd: type2`, and
RFC 0023's refusals make the SCD2-and-mart combination illegal anyway, which narrows this
one's surface to a decision rather than a design.

> **Settled (execution).** RFC 0023 P1 landed, and D23 took the answer this paragraph
> anticipated: `scd: type2` with more than one mapping is refused. The sequencing constraint
> is discharged, not pending.
