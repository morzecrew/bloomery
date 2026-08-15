# RFC 0024 — Deterministic union merge

- **Status:** 📝 Draft — **P1 scoped by D14**: the union, its checks, the collision audit and the `multi_source` fixture, with `dedupe:` and `quarantine:` refused on a merged entity (§5.6). D8, D10 and D11 are answered by D22–D24; D14–D21 record what reading the code turned up that §3 had not. **D25 is the blocker**: `ColumnIR` carries one lowered expression per column and a union needs one per source, so the IR restructure D1 describes as one field is a change to the IR's central node. That shape is `OPEN` and P1 cannot start until it is chosen.
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

**What that costs, stated rather than discovered later.** With `dedupe:` refused, nothing
between the union and the model output collapses rows, so §5.4's collision audit can read
the model directly and D13's careful distinction — read the union stage, *not* `silver.x` —
becomes untestable in P1: the test it names ("a collision `dedupe:` would have collapsed")
cannot be written, because no collapse exists. D13 is not weakened, it is unexercised, and
it returns with the P2 that restores `dedupe:`. Shipping a simpler audit that resembles the
designed one without saying so is the failure this paragraph exists to prevent.

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
- The D14 boundary: `dedupe:` and `quarantine:` on a merged entity are each refused, and a
  merged entity mixing a mapped source with a step output (D21), and `scd: type2` with more
  than one mapping (D23). Each of these is a shape that compiles today for one mapping, so
  each needs a test proving the refusal arrives only when a second one does.
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

## 12. Phasing

**P1 — §5.1–§5.5 and §5.6's boundary.** The union, the compile-time checks, the collision
audit, `_source`, the plan-classifier rows, and the `multi_source` fixture — with `dedupe:`
and `quarantine:` refused on a merged entity (D14). It is *not* release-gating: the refusal
it replaces is honest, tested, and names its own limitation, so shipping 0.1 without this
costs nothing but capability.

An earlier version of this section said "the whole of §5" and called the design "one
coherent unit". Reading the code found that it is not: the union is one unit and the union
*combined with the quality system* is another, and the second has a blocking audit in it
that would refuse valid data (D15). Splitting them is what makes P1 executable in one pass.

**P2 — the quality system on a merged entity.** `dedupe:` first, which needs only the
metadata audit's partition widened and the "does artifact shape vary with mapping count"
question answered once for D7 and D15 together. `quarantine:` after, and only behind the
N-way replay RFC that D16 defers — that one reopens RFC 0016 D10 and deserves its own
argument rather than a paragraph here.

Sequenced **after** RFC 0023 P1 if both are taken: D23 needs an answer for `scd: type2`, and
RFC 0023's refusals make the SCD2-and-mart combination illegal anyway, which narrows this
one's surface to a decision rather than a design.
