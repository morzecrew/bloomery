# RFC 0024 P1 — deviation log

Append-only. Every departure from RFC 0024's decision table taken while executing P1,
classified by whether it could have been known before code existed.

Retired with the RFC when P1 lands; the rows worth keeping become decision rows first
(D29 already did).

| Class | Meaning |
| --- | --- |
| `discovery` | Only building it revealed this. The RFC was right to be silent. |
| `spec-gap` | The RFC was silent, or pitched at the wrong altitude. |
| `drift` | The RFC covered it and it was built otherwise anyway — **a defect**. |

**`drift` count: 0.**

---

## Deviations

### V-001 — D14's boundary is one predicate wider than it says

- **Touches:** D14 (`LOCKED`), §5.6
- **RFC said:** P1 refuses `dedupe:` and `quarantine:` on a merged entity, and the
  boundary is "exact, not approximate"; a merged entity "may therefore still carry field
  rules and row rules".
- **Built:** P1 refuses `opts_in` — any quality opt-in at all.
- **Because:** D14's argument traces the per-source *row identity* and holds. Its
  consequence does not follow: rule **lowering** is per mapping and sits behind neither
  block. `lower_quality` takes one `Mapping`; `opts_in` reads that mapping's field-level
  `quality:` blocks and also selects the `TRY_CAST` column shape; a generated `coercible`
  rule carries `field_sources(mapping, column)` — one mapping's raw JSONPaths — into a
  rule the merged relation evaluates once, where the other branch's bronze relation need
  not have the column it names; `check_quality`'s `by_target` dict kept the **last**
  mapping of N.
- **Class:** `spec-gap` — knowable by reading `quality/lower.py` at design time, and §5.6
  did read the silver lowering. It traced one mechanism and generalised past it.
- **Consequence:** P1 ships the union to entities outside the quality system. P2 now
  starts with rule lowering rather than with `dedupe:`.
- **Resolution:** halted per the `LOCKED` rule, surfaced, and settled by the author.
  Landed as **D29**, appended; D14's row is untouched.

### V-002 — D20 is wrong: dbt refuses a merged entity

- **Touches:** D20 (`ASSUMED`)
- **RFC said:** "dbt emits one `source()` per mapping, and the model body unions them.
  Nothing about the union needs a dbt capability it lacks, so refusing it there would be a
  limitation invented rather than found."
- **Built:** the `source()` half, exactly as D20 says. The merged **entity** is refused,
  with a message naming the audit and routing to SQLMesh.
- **Because:** the `UNION ALL` needs no capability dbt lacks — it is the same shared
  SELECT. The *merge* needs the collision audit, and the dbt emitter has no artifact for
  it: its whole test surface is `schema.yml` entries covering `not_null`,
  `accepted_values` and one expression test, and it emits no singular-test path at all. D5
  makes the audit blocking and not configurable, so it is the merge's correctness
  condition, not a feature of it. Emitting the union without it is a model that compiles,
  runs, and double-counts an entity in silence — the degradation RFC 0008 D3 refuses.
- **Class:** `discovery` — D20 reasoned about the union and was right about the union. The
  missing surface is a property of this emitter, visible only by looking for somewhere to
  put the audit.
- **Consequence:** merged entities are SQLMesh-only in P1. RFC 0016 §5.4's target-coverage
  sentence was *not* stretched to cover this: it authorizes dbt's partiality for the
  quality artifacts, and a rule an author chose to make blocking is not the same as the one
  check a feature cannot be correct without.
- **Resolution:** landed as **D30**, appended; D20's row is untouched, so what it
  predicted survives as the thing D30 has to be read against.

### V-003 — `_source` is an emitted column, not a `ColumnIR`

- **Touches:** D9 (`ASSUMED`), D18 (`LOCKED`)
- **RFC said:** adding a mapping to a single-source entity is "**two** `ADDITIVE` changes,
  rows and the `_source` column"; and "dropping to one mapping removes `_source`, and
  anything reading it must trip the existing contract check".
- **Built:** one `ADDITIVE` change at the entity subject whose detail names both the source
  added and the arriving `_source` column; symmetrically, the removal names the dropped
  column. `_source` is emitted per branch, like `_quality_flags`, and is not an
  `EntityIR.columns` member.
- **Because:** D9's purpose is that the schema move "shows up in `plan()` ... exactly the
  kind of change an operator should see before it lands". It does. Its second half has
  nothing to protect: the only mechanism that could hold a reference to `_source` is a
  quality rule over it (§8), and **D29 refuses rules on a merged entity outright**. Making
  it a real `ColumnIR` to satisfy a contract check with no possible referent would put a
  bloomery-invented column into the mart flattener, the metric reference surface and dbt's
  `schema.yml` for nothing. D18's reservation is unaffected and was implemented as written.
- **Class:** `discovery` — the requirement became void because of a decision (D29) that did
  not exist when D9 was written.
- **Consequence:** the contract half of D9 returns with P2, when rules on a merged entity
  make a reader for `_source` possible again.

### V-004 — D21's refusal already exists, under RFC 0017

- **Touches:** D21 (`LOCKED`)
- **RFC said:** a merged entity may not mix a mapped source with a step output, "refused
  explicitly rather than left to fail somewhere downstream".
- **Built:** a test pinning the existing refusal. No new check.
- **Because:** `resolve/steps.py:_check_duplicate_relations` already refuses any relation
  with two writers, and it seeds from `project.entity_model.entities` — every declared
  entity, mapped or not. So a mapping and a step output cannot both claim one name,
  merged or not, and the combination D21 describes is unreachable. A second refusal of the
  same shape would be a branch that can never execute.
- **Class:** `discovery` — the RFC asked for a refusal that exists under a different name
  and a stronger argument (RFC 0017 §5.8 D8: two writers, one path, last run wins).
- **Consequence:** none. The scope §8 draws is real; the code enforcing it is elsewhere.

### V-005 — the required-field check is scoped to merged entities

- **Touches:** D4 (`LOCKED`), §5.2 rule 2
- **RFC said:** "Every mapping must produce the entity's full declared key and every
  required field."
- **Built:** the required-field half fires **only** when an entity has more than one
  mapping. (The full-key half needed no code: `resolve/refs.py` already enforces it per
  mapping, and therefore per branch.)
- **Because:** applying it to single-mapping entities would refuse projects that compile
  today, which is a compatibility break RFC 0024 does not authorize and §12 does not
  budget. §5.2 rule 2 itself says the coverage asymmetry "exists today for single-mapping
  entities and is not created here" — and gives the reason the *merge* is different: one
  bad source silently poisons a column the others fill correctly.
- **Class:** `spec-gap` — D4 states the rule without scoping it, and the scope is
  load-bearing.
- **Proposed row:** required-field coverage is a merge check; widening it to every entity
  is its own change, with its own migration note.

### V-006 — the quality mart's mapping identity was not re-decided

- **Touches:** D19 (`ASSUMED`)
- **RFC said:** "The quality mart accounts per entity, not per source", because
  `f"{source.relation}->{entity.name}"` has no single value on a merged entity.
- **Built:** unchanged, reached through an accessor that raises if the entity has more than
  one source.
- **Because:** D29 removes the question instead of answering it. A merged entity joins no
  quality rule, contributes no evaluation, and never reaches the mart — so the identity is
  a fact of one mapping rather than a choice among branches. Spelled as a raising accessor
  so it stops being true loudly when P2 restores the rules.
- **Class:** `discovery` — void for the same reason as V-003.

---

## Not deviations, recorded because they look like ones

- **§5.2's four checks became two.** Full-key coverage is enforced today by
  `resolve/refs.py` for every mapping; type agreement is the existing per-mapping typecheck
  against the entity *declaration*, which §5.7 already argues. Both hold for a merge
  without new code.
- **The collision audit reads the model, not a separate union stage.** §5.6 states this
  outcome explicitly: with `dedupe:` refused there is no stage between the union and the
  model output, so the model *is* the union output. D13 is unexercised in P1, not
  weakened, and returns with `dedupe:`.
- **`bloomery_ir_version` 5 → 6.** D17, implemented in the earlier IR-split commit.
