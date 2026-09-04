# RFC 0055 — Ownership, classification and grants

- **Status:** 📝 Draft — the first of the platform-metadata split, and the only one of
  the five with a design question rather than a scheduling one.
- **Scope:** Three annotations on spec nodes — who owns a thing, what class of data it
  holds, and who may read the relation it becomes — and one rule about where each may be
  authored. All three travel to a *metadata slot* each target already has, and none of
  them changes a SELECT. Includes the one member of the platform-metadata list that is a
  **refusal** rather than a gap: dbt seeds.
- **Related:** [`src/bloomery/spec/entity.py`](../src/bloomery/spec/entity.py),
  [`src/bloomery/spec/quality.py`](../src/bloomery/spec/quality.py) (`quarantine.redact`,
  the only PII-adjacent concept that exists today),
  [`src/bloomery/emit/dbt/__init__.py`](../src/bloomery/emit/dbt/__init__.py)
  (`_schema_artifact`, `_project_artifact`),
  [`src/bloomery/emit/cube/__init__.py`](../src/bloomery/emit/cube/__init__.py),
  [`tests/unit/test_tenant_guard.py`](../tests/unit/test_tenant_guard.py) — which
  constrains this RFC in a way the ceiling list did not know about.
- **Origin:** The ceiling review's third item, "platform-metadata surface is absent: no
  seeds, exposures, freshness/SLA, PII tagging, ownership, grants, aggregate marts,
  multi-project refs". That line is unschedulable as written — it contains a design
  question, a blocked item, a target-specific one, a large one and a duplicate — and this
  is the split's first document.

---

## 1. Summary

A bloomery spec says what an entity *is* and says nothing about who is responsible for it
or who may read it. Three annotations close that, and they are one RFC because they are
one mechanism: a value authored on a spec node, carried through the IR unchanged, and
written into whichever metadata slot the target has. No SELECT changes; no guardrail
gains a rule about data.

They are also one RFC because their **failure modes** are shared. Each is a claim about
the world that bloomery cannot check — an owner who has left, a column marked `public`
that is not, a role that does not exist — so each must be emitted as a declaration and
never as an enforcement, and the docs have to say which is which.

`grants` is the one with a consequence: an emitted `+grants` block *is* enforcement, on
the engine, applied by the framework. That makes it the only member of this trio where
being wrong changes who can read data, and §5.3 treats it accordingly.

## 2. Motivation

**The metadata slots already exist and are empty.** dbt's `schema.yml` takes `meta:`,
`description:`, `tags:` and `+grants`; Cube's cubes and measures take `meta`, `title`,
`description` and `public`; SQLMesh's `MODEL` block takes `owner`, `description`,
`tags` and `grants`. bloomery emits into all three files today and writes none of these
keys, so a team adopting it loses metadata it had.

**`redact:` is the shape of the gap.** RFC 0016 gave `quarantine:` a `redact:` list —
JSONPaths whose values are removed from `raw` and `key_values` before a reject row is
written, because a reject table is "a PII lake with a 90-day memory". That is a real
classification concept, and it is scoped to *one artifact*. Nothing says the same column
is sensitive in the silver relation, the mart, or the Cube view, so a spec can redact a
path in the reject table and publish it in gold, with nothing to notice.

**Ownership is what a refusal message cannot name.** Every refusal bloomery raises
carries a `source_path` — `entity_model: entities.order.fields.total.type` — which says
where the problem is and not who to tell. In a repository with one author that is the
same thing; at the size where a spec compiler earns its keep it is not.

**There is a guard here the ceiling list did not know it was arguing with.**
`tests/unit/test_tenant_guard.py` enforces that the word *tenant* may appear only in
`naming.py` docstrings — the package must open-source with no multi-tenancy showing
through. Row-level access policy is expressible without that word and column-level
`public: false` certainly is, but any design here has to be written so the guard stays
true, and that constraint is stated once, in §5.4, rather than discovered per phase.

## 3. Current state

Verified against the tree.

| Slot | Target writes it | bloomery fills it |
|---|---|---|
| dbt `models/schema.yml` `meta:` / `description:` / `tags:` | yes | **no** |
| dbt `dbt_project.yml` `+grants` | yes | **no** |
| Cube `meta` / `title` / `description` / `public` | yes | **no** |
| SQLMesh `MODEL (owner …, description …, tags …)` | yes | **no** |
| SQLMesh `grants` | yes | **no** |
| `quarantine.redact` (reject rows only) | n/a | **yes** |

- **No `owner` anywhere.** `coverage_owner` in the lowering is unrelated — it names the
  relation a coverage check reads, not a person.
- **No classification anywhere.** `redact:` is the nearest thing and is a per-path rule
  on one artifact, not a property of a column.
- **No grants anywhere**, and no concept of a role. `bloomery explain --policy` takes a
  row-scoping filter, which is a *query* argument the caller supplies and is explicitly
  "not an identity" — it is not a grant and does not become one.
- **Seeds: bloomery reads no files.** RFC 0003 forbids filesystem access during
  compilation; a seed is a CSV of *data*, and the only way to emit one is for the data to
  be in the spec. §4 makes that a non-goal rather than a gap.

## 4. Goals / Non-goals

**Goals**

- One `owner` per entity, mart and metric, emitted into every target's owner slot.
- A column-level classification vocabulary, emitted as target metadata, and reconciled
  with `quarantine.redact` so one column cannot be sensitive in one artifact and not in
  another.
- `grants` on an entity or mart, emitted for the targets that apply them, refused for
  the targets that do not.
- Every one of the three documented as a **declaration bloomery does not verify**, in the
  same paragraph that introduces it.

**Non-goals**

- **Seeds.** A seed is data in the repository. bloomery reads no files at compile
  (RFC 0003) and a spec carrying rows would make the spec a data file, which is the one
  thing the entity/mapping/metric split exists to avoid. This is a stated refusal, with a
  test pinning the refusal message, not a backlog item.
- **Enforcing anything.** An `owner` is not paged, a classification does not mask a
  column, and a grant is applied by the framework or not at all.
- **Multi-tenancy.** See §5.4 and the guard it names.
- **A role registry.** `grants` names roles as strings; bloomery has no notion of who
  they are, and inventing one would be a second identity system beside the caller's.

## 5. Design

### 5.1 `owner`

A string on `entities.<name>`, `marts.<name>` and `metrics.<name>`. Emitted as SQLMesh's
`owner`, dbt's `meta.owner` (dbt has no first-class owner field — `meta` is where the
ecosystem puts one), and Cube's `meta.owner`.

Not validated as an email, a handle or a team name: every project spells this
differently, and a format rule would refuse spellings that are correct for their reader.
It is a string that travels.

**Inheritance is the question worth deciding.** A mart over an entity may take the
entity's owner, or require its own, or leave the field absent. §11 D2 proposes *absent*
— a mart with no declared owner has none, and the absence is visible — because inheriting
silently makes an owner that was never written look like one that was.

### 5.2 Classification

A `classification:` on a field, from a **closed vocabulary**. The vocabulary is the
design question this RFC exists to settle: an open string is a tag that means whatever
the writer meant, and a closed one is a claim the compiler can act on.

Proposed: `public`, `internal`, `pii`, `secret`. Four is enough to route, and the
routing is what makes it more than a tag:

- `pii` and `secret` on a mapped field whose source path is **not** in
  `quarantine.redact` is a **refusal**. That is the reconciliation §2 asks for: today a
  spec can redact a path from the reject table and publish the same column in gold, and
  nothing notices. The refusal names both places.
- `secret` on a field a mart projects is a refusal. A mart is the published surface.
- `public`/`internal` route to metadata only.

Cube's `public: false` is the one target-native consumer: a `pii` or `secret` column
becomes a member with `public: false`, which removes it from Cube's API surface without
removing it from the relation.

### 5.3 `grants`

`grants: {select: [role_a, role_b]}` on an entity or mart. SQLMesh takes `grants` in the
`MODEL` block; dbt takes `+grants` per-model config. Both *apply* them — this is the
member of the trio that changes who can read data.

Two rules follow from that, and they are the reason this is not simply a fourth metadata
key:

- **Grants are emitted only where the framework applies them.** Cube gets nothing: it
  reads relations it does not own, so a `grants` block there would be a claim with no
  mechanism behind it. Refused rather than dropped.
- **An empty list is not an absent block.** `grants: {select: []}` means "no role may
  select", which is a statement; no `grants:` block means bloomery says nothing and the
  warehouse's existing grants stand. Emitting the first as the second would revoke
  nothing while looking like it did.

### 5.4 What the tenancy guard requires

`tests/unit/test_tenant_guard.py` refuses the word *tenant* outside `naming.py`
docstrings. Nothing in §5.1–§5.3 needs it: an owner is a person, a classification is a
property of a column, and a grant names a role. The guard is stated here so that a later
reader adding "and per-tenant grants" meets it in the design rather than in CI.

Row-level access — the `accessPolicy` half of the ceiling list's Cube item — is **not
here**. It is a filter over rows, not an annotation on a node, and it belongs with
whatever RFC takes Cube's policy surface.

## 6. Tests

- **Golden per target**, one fixture carrying all three annotations, so the three
  metadata slots are pinned as bytes.
- **Refusal census:** the `pii`-without-`redact` refusal, the `secret`-in-a-mart refusal,
  the Cube `grants` refusal, and the seeds refusal — four new messages, each with its
  `source_path`.
- **A unit test that the SELECTs do not move.** Every existing golden stays
  byte-identical when the annotations are absent, which is the claim "this changes no
  SQL" stated as a test rather than as a sentence.
- **e2e:** `dbt parse` over a project carrying `+grants` and `meta`, because a malformed
  `schema.yml` is a project dbt refuses to load and no golden sees that.

## 7. Docs

- A how-to: annotating a spec, and the sentence that none of it is enforced by bloomery.
- `pages/docs/reference/errors.md`: the four refusals.
- `pages/docs/concepts/data-quality.md`: the `redact:` ↔ `classification:` link, since
  today's page describes `redact:` as a reject-table concern and it stops being only that.

## 8. Out of scope

- **Seeds** (§4), refused.
- **Exposures**, **freshness**, **rollup marts** and **multi-project references** — the
  other four members of the ceiling item, each its own RFC.
- **Cube `accessPolicy`** (§5.4).
- Any form of secret *value* in a spec. Classification names a column; it never carries
  one.

## 9. Risks

- **A closed vocabulary is a guess.** Four values may be three too few for a regulated
  shop and two too many for a startup. The mitigation is that the vocabulary is closed
  *and small*, so widening it later is additive; an open string could never be narrowed.
- **`pii` without `redact` may refuse projects that are correct.** An entity with no
  `quarantine:` block has no reject table and therefore nothing to redact from, so the
  refusal must be conditional on quarantine existing. Stating it here because the obvious
  implementation refuses a spec that is fine.
- **`grants` diverges between frameworks.** dbt's `+grants` is declarative and applied on
  every run; SQLMesh's is applied at creation. A project that compiles for both will have
  the same block mean two slightly different lifecycles, and the docs must say so rather
  than claiming parity.
- **Metadata is where scope creep lives.** Every ecosystem has a favourite key. The rule
  that keeps this bounded is §4's: an annotation is in scope only if a target has a slot
  for it *and* bloomery can state it without reading the world.

## 10. Unresolved questions

- Whether `classification` belongs on a **field** or on a **mapping path**. The field is
  where a reader looks; the path is what `redact:` already keys on, and a merged entity
  has one field with several paths.
- Whether `owner` should also reach the MetricFlow manifest, which has an `owners` list
  on a semantic model. Probably yes; deferred because the manifest's shape is RFC 0013's.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | The three annotations change no SELECT. They reach metadata slots only, and an existing golden's SQL is byte-identical with them absent — asserted, not assumed. |
| 2 | `ASSUMED` | `owner` does not inherit. A mart with no declared owner has none; silent inheritance makes an owner nobody wrote look like one somebody did. |
| 3 | `LOCKED` | `classification` is a **closed** vocabulary. An open string is a tag that cannot be routed, and the routing — the `redact` reconciliation and Cube's `public: false` — is the whole reason this is not a `meta` passthrough. |
| 4 | `LOCKED` | `pii`/`secret` on a mapped field whose path is not redacted is a refusal **when the entity quarantines**, and silent otherwise. An entity with no reject table has nothing to redact from, and refusing it would refuse a correct spec. |
| 5 | `LOCKED` | `grants` is refused for Cube. Cube reads relations it does not own, so emitting grants there would be a claim with no mechanism — the silent degradation RFC 0008 D3 exists to prevent. |
| 6 | `LOCKED` | `grants: {select: []}` and an absent `grants:` block are different. The first says no role may select; the second says bloomery has no opinion and the warehouse's grants stand. |
| 7 | `ASSUMED` | Seeds are refused permanently, with a message naming RFC 0003 rather than a wave. A seed is data in the repository, and the only way to emit one is to put rows in a spec. |
| 8 | `ASSUMED` | No spelling rule on `owner`. Every project spells this differently and a format check would refuse spellings correct for their reader. |

## 12. Phasing

Four commits, and the order is by blast radius:

1. **`owner`** — one spec key, three metadata slots, no refusals. Additive everywhere.
2. **`classification`**, metadata only — the vocabulary, the IR field, and Cube's
   `public: false`. Still no refusals.
3. **The two refusals** — `pii` without `redact`, `secret` in a mart. Breaking for specs
   that were silently inconsistent, which is the point.
4. **`grants`**, with the Cube refusal and the seeds refusal beside it.
