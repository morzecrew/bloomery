# RFC 0035 — The reject table on a merged entity

- **Status:** 🚧 In progress — **shipped; retired one change from now.** Every decision
  below is implemented. The row stays live because a retirement must name a commit the
  mainline can reach ([`RETIRED.md`](RETIRED.md) argues why) and this document was born
  on the branch that executes it, so no such commit exists yet.
- **Scope:** `quarantine:` on an entity built from more than one mapping: what the
  `<entity>__reject` table holds, and how replay re-runs the right mapping against each
  reject row. RFC 0024 D16 (`LOCKED`) says reopening RFC 0016 D10 — one reject table per
  entity, chosen *because* per-mapping tables make replay N-way — "gets its own RFC, argued
  against D10 directly, rather than being decided inside a feature branch". **This is that
  document.** It argues that D10's conclusion survives and its stated ground does not
  transfer: the table stays one per entity, and replay becomes N branches of one statement
  rather than N statements over N tables. Touches `emit/lower/silver.py` (the reject
  projection and the replay extract), `quality/reject.py` (nothing structural — the schema
  is unchanged), and the resolver refusal RFC 0024 P1 put in `resolve/build.py`. **No schema
  change, no IR change, no public signature change.**
- **Related:** RFC 0016 D10 (one reject table per entity), D21 (the ingestion-metadata
  contract that makes `_source_row_id` unique per *source relation*), D22 (the replay
  statements), D88 (`last_evaluated_at`); RFC 0024 D5/D13 (the collision audit), D14/D29
  (the P1 refusals), D16 (the lock this document answers), D34 (artifact shape varies with
  mapping count);
  [`src/bloomery/emit/lower/silver.py`](../src/bloomery/emit/lower/silver.py)
  (`_sole_source`, `reject_select`, `_branch_select`, `replay_statements`),
  [`src/bloomery/quality/reject.py`](../src/bloomery/quality/reject.py) (`reject_id`,
  `REJECT_COLUMNS`).
- **Origin:** RFC 0024 §12 gates P2c twice — on a named consumer for P2 as a whole (D31),
  and on this document. The consumer arrived: the lakehouse example's own pitch is dirty
  bronze, and union merge without cleaning composes with none of it.

---

## 1. Summary

A merged entity may declare `quarantine:`. The reject table stays **one per entity**, as
RFC 0016 D10 decided; what changes is that its three provenance literals —
`source_relation`, `mapping`, `mapping_version` — move from being computed once off *the*
mapping to being projected per union branch, which is where they were always true. Replay
then reads the one table N times inside one `UNION ALL`, each branch filtered to the rows
its own mapping produced, and merges the result exactly as it does today.

D10's ground was that per-mapping reject tables "multiply into the small-file problem and
make replay N-way". Both halves are about **tables**. Nothing here adds a table.

## 2. Motivation

**`quarantine:` is the block that makes the quality system worth having, and it is the one
a merged entity cannot declare.** RFC 0024 P1 refuses it, and the refusal is honest — the
reject projection really is built from one mapping's literals. But the shape it refuses is
the shape the project's own example corpus is built to demonstrate: the lakehouse example
sells dirty bronze landing as text and being cleaned on the way to silver, and a union
merge that cannot be cleaned composes with none of that. A user who merges two shops'
orders and wants coercion failures routed rather than flagged is told to keep one mapping
per entity — which is the entity-model gap RFC 0024 exists to close, handed back one layer
down.

**The refusal also costs a check, not only a capability.** With `quarantine:` refused, the
conservation audit — RFC 0016 §6's accounting law, carried onto production runs — is not
emitted for a merged entity, because it has no reject table to account against. So the one
entity shape where rows come from several places is the shape with no runtime statement
that rows are conserved.

## 3. Current state (the pre-P2c baseline)

Verified against the tree **as it was when this document was written** — every "is"
below is now a "was", and deliberately not rewritten: this section is the argument's
premise, and a premise edited to match its conclusion stops being evidence.
`reject_select` no longer calls `_sole_source` and replay filters each branch by
`source_relation`, because §5 happened.

**The reject projection is per entity and reads one mapping.**
`reject_select` (`emit/lower/silver.py`) opens with

```python
origin = _sole_source(entity, "the reject table")
```

and `_sole_source` raises `EmitError` when `len(entity.sources) != 1`. Three projections
read it — `exp.Literal.string(origin.relation)` as `source_relation`,
`f"{origin.relation}->{entity.name}"` as `mapping`, `origin.mapping_version` as
`mapping_version` — and a fourth, `reject_id`, takes `origin.relation` as its first
argument.

**`reject_id` is already keyed by the pair this needs.** `quality/reject.py`:

```python
def reject_id(source_relation: str, row_id: Expression, digest) -> Expression:
    """A SHA-256 hex digest over the canon bytes of ``(source_relation, _source_row_id)``."""
```

RFC 0024 D16 says as much in its own text — "`reject_id` itself survives — it is already a
digest of `(source_relation, row identity)`, so the pair was designed for exactly this".
The digest takes a Python `str`, so per branch it is still a **compile-time literal**; what
it is not is a literal for the whole model.

**Replay already unions per source, and every branch reads every row.**
`_extract_select(entity, ctx, from_payload=True)` builds one `_branch_select` per
`entity.sources` entry with `from_payload=True`, which rewrites each branch's bronze column
references into `JSON_EXTRACT_SCALAR(raw, '$.<column>')` and filters `resolved_at IS NULL`.
On a single-source entity that is exactly right. On a merged one it is silently wrong:
branch A's extraction would run over branch B's reject rows, whose `raw` payload has B's
column names in it — so a mapping would be applied to rows it never produced, and the
result would be NULL-shaped rather than an error.

**That is the whole of the N-way problem**, and it is one predicate wide.

## 4. Goals / Non-goals

**Goals**

- `quarantine:` on a merged entity, with the same reject schema, the same `reject_id`, the
  same retention and the same three replay statements.
- Replay applies **each row's own mapping** to that row.
- The conservation audit returns to merged entities, since it is emitted with the reject
  table.

**Non-goals**

- **Not a second table, and not a per-mapping one.** D10 stands; §5.1 is the argument.
- **Not overlapping keys.** RFC 0024 D5 refuses them with a blocking audit and RFC 0021 owns
  matching. A reject row is a row that did not enter the entity; nothing here changes which
  rows do.
- **Not the dbt target.** dbt emits no reject model at all (RFC 0016 §5.4), merged or not.
- **Not retention policy.** Unresolved rows age from `last_seen` and resolved ones from
  `resolved_at`, unchanged.

## 5. Design

### 5.1 Why D10 survives being reopened

D10 chose one reject table per entity, and RFC 0024 D16 locked the reopening. Read D10's
ground precisely:

> per-mapping tables multiply into the small-file problem and make replay N-way

Two costs, both **of the table count**. The small-file problem is a property of how many
relations exist; "replay N-way" in that sentence means N reject relations to read, N merges
to run, and N retention policies to age — because that is what the alternative D10 was
comparing against proposed.

This document proposes none of that. The table count stays exactly one. What becomes N is
the number of **branches inside the replay statement's extract**, which is the same
structure RFC 0024 already emits for the forward pipeline — `_extract_select` is a
`UNION ALL` over branches today, and replay reuses it. So the honest statement is not that
D10 is overturned; it is that **D10 was answering a different question**, and its answer is
still the right one. What P2c needs is orthogonal to it.

There is one real consequence D10 did not foresee, and it is worth stating rather than
discovering: with rows from several sources in one table, `reject_id`'s uniqueness now
depends on the `(source_relation, _source_row_id)` pair rather than on the row identity
alone. That is what the pair was for, and RFC 0016 D21's contract — the identity is unique
*within a source relation* — is exactly the assumption the pair repairs. Had `reject_id`
been a digest of the row identity alone, this document would be arguing for a schema change
instead, and D10 would be genuinely in the way.

### 5.2 The provenance literals move down one level

`source_relation`, `mapping` and `mapping_version` are true **of a branch**, not of a model.
They move into `_branch_select`, projected under their final names, and `reject_select`
reads them off the extract subquery the way it already reads `_source_row_id` and
`_ingested_at`:

```python
# _branch_select, when the entity has a reject table
projections.append(exp.alias_(exp.Literal.string(origin.relation), "source_relation"))
projections.append(exp.alias_(exp.Literal.string(f"{origin.relation}->{entity.name}"), "mapping"))
projections.append(exp.alias_(exp.Literal.number(origin.mapping_version), "mapping_version"))
projections.append(exp.alias_(reject_id(origin.relation, row_id, ctx.dialect.text_sha256), "reject_id"))
```

`reject_id` moves with them for one reason that is not symmetry: its first argument is the
branch's relation name, so computing it above the union would need a relation name the
union has erased. Computing it in the branch keeps it a literal `CONCAT` over a
compile-time string, which is what it is today.

**This projection is conditional on the reject table existing**, not on mapping count. A
merged entity without `quarantine:` projects none of it, and a single-source entity with
`quarantine:` projects all four — the same columns it projects today, one level lower.
That is a **narrowing** of RFC 0024 D34's precedent rather than a widening of it: D34 made a
generated audit *body* vary with mapping count; this varies with a spec block, which is the
ordinary case the artifact set has always had.

### 5.3 Replay branches on `source_relation`

`_branch_select(..., from_payload=True)` gains one conjunct:

```sql
WHERE resolved_at IS NULL AND source_relation = '<this branch's relation>'
```

on a merged entity, and keeps the bare `resolved_at IS NULL` on a single-source one, where
the filter would be a constant `TRUE` over the only rows there are.

That is the entire N-way fix. Each branch applies its own mapping's extraction to its own
mapping's rows; the union is a bag of re-derived candidates exactly as before;
`_one_winner_per_key` and `_candidate_wins` are untouched, because they compare candidates
by the dedupe order, which RFC 0024 D35 has already made total on a merged entity by adding
`_source` ahead of `_source_row_id`.

**`raw` needs no schema agreement between branches** and this is worth pinning, because it
looks like it should. The payload is a JSON object of one branch's `_payload_columns`, and
it is read back by the same branch's rewritten expressions. Two sources with entirely
disjoint bronze column names replay correctly, because no expression ever reads a payload it
did not write.

### 5.4 What is refused, still

- **`_sole_source` does not go away.** The quality mart keeps it (RFC 0024 D19 and its
  execution note in `logs/T-0004.md` V-006 both point at that accessor), and it stays the
  right spelling for any surface that genuinely has no merged form. What changes is that the
  reject table stops being such a surface.
- **A merged entity still may not mix a mapped source with a step output** (RFC 0024 D21),
  and `(target, source)` is still unique (D12) — so a branch's `source_relation` literal
  identifies exactly one branch, which is what §5.3's filter requires. Without D12 this
  design would not work: two branches on one relation would each claim the other's rows.

### Alternatives considered

**A per-mapping reject table.** What D10 refused, and refusing it again is not a formality:
it costs a relation per mapping per entity, N retention policies, N merges, and it splits
one entity's account of "why rows are missing" across N places for an operator debugging a
row count. It also does not become simpler on a merged entity — the branch filter this
design adds is replaced by a branch *relation*, which is more machinery, not less.

**A `raw` payload carrying its own column namespace** (prefixing keys by source, so one
extraction could read any payload). It removes §5.3's filter and replaces it with a rewrite
of every replay expression plus a payload format change that invalidates every reject row
already landed. The filter is one predicate; this is a migration.

**Refusing `quarantine:` permanently on merged entities and routing to a step.** The status
quo generalized. It keeps the compiler simpler and hands the user the exact gap RFC 0024
was written to close, one layer down. Rejected on the same ground RFC 0024 §2 rejects the
entity-renaming workaround.

## 6. Tests

- **Unit** — the four provenance projections appear once per branch and carry that branch's
  relation; the replay extract carries one `source_relation = …` conjunct per branch; a
  single-source entity's emitted reject SELECT is **unchanged** except for the level the
  literals are projected at (the golden corpus is the assertion).
- **Golden** — the `multi_source` fixture gains `quarantine:`, so the reject model, the
  replay statements, the conservation audit and the ingestion-metadata audit all enter the
  corpus for a merged entity.
- **Execution (DuckDB)** — two sources, one with a coercion failure, one clean: the failing
  row lands in the reject table with its **own** `source_relation`; a replay after the
  source is corrected admits it and stamps `resolved_at`; the row from the other source is
  untouched by either. This is the test that fails on today's code by silently re-deriving
  NULLs rather than by raising, which is why it is named here rather than left to the tier's
  general coverage.
- **Engine (Postgres, Trino)** — the same case, because `reject_id`'s digest is
  dialect-specific (RFC 0016 D83) and the point of the pair is cross-dialect agreement.
- **Conservation** — rows in the entity plus rows in the reject table equal rows in the
  union, on a merged entity. RFC 0016 §6's law, now over a bag of two branches.

## 7. Docs

`pages/docs/concepts/data-quality.md` states the reject table is one per entity; it stays
true and gains the sentence that a merged entity's rows carry their own `source_relation`.
The merged-entity how-to loses the paragraph that says cleaning is unavailable. No migration
note is owed: nothing that compiled before compiles differently.

## 8. Out of scope

- **The dbt reject model.** RFC 0016 §5.4 names it as out of scope for that emitter; this
  document does not change which targets emit what.
- **RFC 0024 P2a and P2b.** Rule lowering and `dedupe:` on a merged entity are designed in
  RFC 0024 D32–D35 and are that document's to land. P2c is sequenced after them because a
  reject table needs rules to route rows into it; the dependency is one-way.

## 9. Risks

- **A stale reject row whose source was removed.** Drop a mapping from a merged entity and
  its reject rows have no branch to replay them: they stay unresolved and age out by
  retention. That is the correct behaviour — the rows describe data the project no longer
  reads — but it is invisible, so §7's doc sentence says it. Accepted, not mitigated.
- **`source_relation` is now load-bearing rather than diagnostic.** It was a record of where
  a row came from; it becomes the predicate replay selects on. A hand-edited reject table
  can therefore misroute a row. Reject tables are compiler-owned, and `reject_id` would
  disagree with a hand-edited relation anyway, so this is stated rather than guarded.
- **Reading this as reopening D10.** It is not, and §5.1 exists so that a reader who arrives
  through D16's lock finds the argument rather than an assertion.

## 10. Unresolved questions

None. The one question that would be open — whether the payload format has to change —
§5.3 answers with the no-shared-namespace argument, and it is a fact about how the payload
is written and read rather than a choice.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | **RFC 0016 D10 stands: one reject table per entity, merged or not.** Its stated ground — per-mapping tables multiply into the small-file problem and make replay N-way — is a statement about the number of *relations*, and this design adds none. D10 answered a different question and its answer is still right. Consequence: RFC 0024 D16's lock is discharged by keeping the decision, not by overturning it, and any future proposal for a per-mapping table argues against D10 as it always had to. |
| 2 | `LOCKED` | **`source_relation`, `mapping`, `mapping_version` and `reject_id` are projected per union branch.** They are true of a branch and were only ever true of a model because there was one branch. `reject_id` moves with them out of necessity rather than symmetry: its first argument is the branch's relation name, which the union erases. Consequence: `reject_select` reads four more columns off the extract subquery and reads no `SourceIR` at all. |
| 3 | `LOCKED` | **Replay filters each branch to `source_relation = '<branch>'`.** Without it a mapping's extraction runs over another mapping's payload and returns NULLs rather than raising — a silent wrong answer, which is the failure class this project refuses. The filter is sound because `(target, source)` is unique (RFC 0024 D12), so the literal names exactly one branch. |
| 4 | `ASSUMED` | **The `raw` payload format does not change.** Each branch writes its own `_payload_columns` and reads them back through its own rewritten expressions, so two sources with disjoint bronze column names need no shared namespace. Believed rather than locked because it rests on `_from_payload` rewriting only unqualified column references, which is a property of one function. |
| 5 | `ASSUMED` | **The provenance projections are conditional on the reject table, not on mapping count.** A single-source entity with `quarantine:` projects the same four columns it projects today, one level lower; a merged entity without `quarantine:` projects none. This deliberately does *not* extend RFC 0024 D34's mapping-count precedent — varying with a spec block is the ordinary case, and keeping the two kinds of variance distinct is what stops D34 from reading as licence. |
| 6 | `LOCKED` | **`_sole_source` stays.** The quality mart still has no merged form (RFC 0024 D19), and the accessor's raising spelling is what made this whole area fail loudly rather than silently when P2 arrived. What changes is one caller, not the mechanism. |
| 7 | `ASSUMED` | **A reject row whose mapping was removed is unreplayable and ages out by retention.** No new refusal and no migration: the rows describe data the project no longer reads. Documented rather than guarded, because a guard would have to refuse dropping a mapping from an entity that has reject rows, which is a run-time fact the compiler does not have. |

## 12. Phasing

**One phase, and it is RFC 0024 P2c.** This document exists to unblock that phase, not to
schedule work of its own; the code lands in the change that lands P2c, after P2a (rule
lowering) and P2b (`dedupe:`), because a reject table needs rules to route rows into it.

Retire this document in the change that lands P2c, per `rfcs/INDEX.md`.
