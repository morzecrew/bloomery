# RFC 0060 — Replay on a historical entity

- **Status:** 📝 Draft — the design behind a refusal that already shipped. Not scheduled;
  this document exists so "refused" reads as "not yet, and here is the shape" rather than
  as "never".
- **Scope:** How a quarantined row is admitted into an entity whose history the *target
  framework* maintains — `scd: type2`. One question, three candidate answers, and the
  measurement that rules the current one out. No change to flag-only quality, to type 1
  entities, or to any artifact either target emits today.
- **Related:** [`src/bloomery/resolve/build.py`](../src/bloomery/resolve/build.py)
  (`_snapshot_quarantine`, the refusal this replaces),
  [`src/bloomery/emit/lower/silver.py`](../src/bloomery/emit/lower/silver.py)
  (`replay_statements`),
  [`src/bloomery/emit/dbt/__init__.py`](../src/bloomery/emit/dbt/__init__.py)
  (`_snapshot_artifact`, `_reject_artifacts`),
  [`src/bloomery/emit/sqlmesh/__init__.py`](../src/bloomery/emit/sqlmesh/__init__.py)
  (`_kind_clause`'s `SCD_TYPE_2_BY_COLUMN` branch),
  RFC 0016 (data quality: §5.6 reject and replay), RFC 0023 (SCD2 flattening; retired at
  `aeca6f1`), RFC 0008 (targets; retired at `7ba117b`).
- **Origin:** `logs/T-0016.md` D-083. The RFC 0052 self-audit asked whether a quarantining
  SCD2 entity emitted the same artifact set on both targets. It does, and both are wrong.

---

## 1. Summary

Replay's first statement is a `MERGE` that admits a re-evaluated row into the entity,
projecting the entity's own columns (RFC 0016 §5.6). That is correct for a relation
bloomery's own SELECT defines, and wrong for one the framework maintains: a type 2
relation also carries a validity interval, and on dbt a snapshot identity, that the merge
does not name.

It does not fail. It inserts a version with those columns NULL and reports success, so the
row is present, queryable, and invisible to every as-of join — which is the only reason a
type 2 relation exists. The pair is refused today for exactly that reason.

The fix is not to fill the missing columns. It is to stop writing past the framework: a
recovered row should reach the entity **through whatever produces the entity's versions**,
so the framework does the versioning it owns. §5 states three ways to do that and ranks
them; the RFC is unscheduled because choosing needs a measurement none of them has yet.

## 2. Motivation

**The combination is not exotic.** A slowly-changing dimension read from a dirty source is
the ordinary case — a customer table with a segment that changes and an email that
sometimes fails to parse. Today an author must choose between keeping history and being
able to recover a diverted row, and nothing explains why those are alternatives.

**The refusal is a stop-gap and reads like a position.** `_snapshot_quarantine`'s message
says what to give up and not what it would take to give up neither. A refusal with no
design behind it is indistinguishable from a decision that the combination is wrong, and
it is not wrong — it is unbuilt.

**The hole is older than the refusal.** SQLMesh has emitted this merge against
`SCD_TYPE_2_BY_COLUMN` since RFC 0016, and no fixture ever combined the two, so nothing
observed it. RFC 0052 gave dbt a replay macro, the audit compared the two targets'
artifact sets for such an entity, and found them identical and identically broken.

## 3. Current state

Verified against the tree, and by running the merge.

| | The entity relation | Who maintains its versions | What replay's merge names |
|---|---|---|---|
| SQLMesh, `scd: type1` | a `FULL`/incremental model | bloomery's SELECT | every column — correct |
| dbt, `scd: type1` | a `table`/`incremental` model | bloomery's SELECT | every column — correct |
| SQLMesh, `scd: type2` | `SCD_TYPE_2_BY_COLUMN` | **SQLMesh** | the entity columns only |
| dbt, `scd: type2` | `snapshots/<entity>_snapshot.sql` | **dbt** | the entity columns only |

**The measurement.** A dbt project with a quarantining type 2 entity, built and then sent
the replay merge with one admissible row:

```
before: [('c1', '5486545f…', 2026-09-04 18:27:51, None)]
after:  [('c1', Decimal('10.00'), '5486545f…', 2026-09-04 18:27:51, None),
         ('c2', Decimal('99.99'), None,        None,                 None)]
```

`dbt_scd_id`, `valid_from` and `valid_to` are NULL on the admitted row, and the statement
reported success. `valid_from IS NULL` fails every `BETWEEN`/`>=` an as-of join writes, so
the row is skipped; `dbt_scd_id IS NULL` is a snapshot identity dbt's next run does not
recognise.

**Why the obvious fix is not available.** `dbt_scd_id` is a hash dbt computes over the
unique key and the strategy's check columns, in its own macros. Writing bloomery's guess of
it makes this compiler an implementation of another framework's bookkeeping, which is the
coupling `emit/lower/` exists to prevent — and a guess that is wrong produces duplicate
versions rather than an error. `valid_from`/`valid_to` *could* be filled and should not be
independently: a version interval invented by a merge is a history nobody declared, and the
two frameworks disagree about what the interval of a back-filled version even means.

## 4. Goals / Non-goals

**Goals**

- A quarantining `scd: type2` entity compiles, and its replay admits a recovered row as a
  **version the framework wrote**.
- The route is the same on both targets, or the difference is one decision row rather than
  two lowerings.
- `_snapshot_quarantine` is deleted, not narrowed.
- Proven by execution: the recovered row is visible to an as-of join at the grain the
  entity declares. A row that lands is not the claim; a row an as-of join *finds* is.

**Non-goals**

- **Computing `dbt_scd_id` or any framework's bookkeeping** (§3).
- **A bloomery-maintained SCD2.** Both targets have a native mechanism and RFC 0008 D3's
  rule is to adapt to it, not to replace it.
- **Changing replay for type 1 entities.** It is correct there and every fixture proves it.
- **Retention or redaction changes.** A recovered row's reject entry is history exactly as
  it is today.

## 5. Design

Three candidates. None is chosen, because choosing needs §6's measurement.

### 5.1 Union the recovered rows into the entity's source

The entity's SELECT gains a second arm reading a bloomery-owned `<entity>__replayed`
relation, which replay writes instead of merging into the entity. The framework then sees
the row in its source query and versions it on the next run, with its own bookkeeping.

**For:** the framework does the versioning, which is the whole requirement. It works
identically on both targets, because both build the entity from a query bloomery wrote.

**Against:** a new relation with a lifecycle — when is a row removed from it? Never is
wrong (it re-enters forever); on the next run is wrong (the run may not happen). And it
changes `entity_select` for a shape that most projects do not have, which is a cost paid
by every reader of that function.

### 5.2 Replay writes to bronze

The recovered row is written back to the bronze relation as a new delivery, and the
ordinary pipeline admits it. Nothing about the entity changes.

**For:** no new relation, no change to any SELECT, and the row arrives through the path
every other row arrives through — so the versioning, the audits and the conservation law
all hold by construction.

**Against:** bloomery would be writing to a relation it declares itself not to own. Bronze
is the caller's landing zone; a compiler emitting a statement that inserts into it is a
different posture from emitting one that reads it, and the retention and idempotence rules
of that write belong to whoever owns the ingestion.

### 5.3 Refuse permanently, and say so

Keep `_snapshot_quarantine` and close this RFC as rejected.

**For:** the two features genuinely pull apart — a diverted row has no version, and a
version is what a type 2 relation stores.

**Against:** §2's ordinary case has no answer, and "keep history" versus "recover a bad
row" is not a trade-off any user asked for.

**Current lean: §5.2, then §5.1.** §5.2 is smaller and its objection is about posture
rather than correctness, which is the kind of objection a decision row can settle. §5.1 is
correct and expensive. §5.3 is the honest fallback if §6 shows both fail.

## 6. Tests

The measurement that has to come first, before any of §5 is built: **does a row admitted
into a framework-maintained type 2 relation, by any route, become visible to an as-of
join at the entity's grain?** That is the property the current merge fails, and it is the
only one worth building against.

Then, per candidate: an execution-tier test that quarantines a row, recovers it, runs the
target's own history mechanism, and asserts the as-of join finds it with an interval that
starts where the recovery says it does — on both targets, since the two frameworks
version differently and a design that works on one is half a design.

## 7. Docs

`pages/docs/concepts/data-quality.md` carries the refusal today, as a warning block with a
live provocation behind it. Whichever candidate lands replaces that block; if §5.3 wins,
the block stays and gains the reason.

## 8. Out of scope

- Everything until §6's measurement exists.
- SCD2 on a merged entity, which is refused separately and for an unrelated reason
  (RFC 0024 D23: the collision audit cannot tell a version from a collision).
- `on_fail: quarantine` on a step output, refused on every target for a third unrelated
  reason.

## 9. Risks

- **§5.2 makes bloomery a writer.** Emitting a statement that inserts into bronze is a
  posture change, and the package's whole claim is that it emits text a caller runs. The
  text is still the caller's to run — but "run this and it will write to your landing
  zone" is a sentence this project has never written, and it should be written
  deliberately or not at all.
- **§5.1's staging relation is a lifecycle nobody owns.** The failure mode is a row that
  re-enters the entity on every run forever, which looks exactly like a working feature.
- **A partial fix is worse than the refusal.** Admitting the row without the framework's
  interval is what the current code does; any candidate that lands half-built reproduces
  the defect this RFC exists to remove, with a test suite that says it is fixed.

## 10. Unresolved questions

- What the recovered version's `valid_from` should *mean*: the original delivery's
  `_ingested_at`, the moment of recovery, or the framework's own run time. All three are
  defensible and they produce different histories, so it is a decision rather than a
  detail.
- Whether a recovered row should version the entity at all, or replace the interval it
  would have had — i.e. whether replay is a correction to history or an addition to it.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | bloomery does not compute any framework's SCD bookkeeping. `dbt_scd_id` is dbt's hash over its own strategy; a guess that is wrong produces duplicate versions rather than an error, and being right makes this compiler an implementation of dbt's internals. |
| 2 | `LOCKED` | A recovered row reaches the entity **through whatever produces the entity's versions**, so the framework versions it. Writing past the framework is what the shipped defect did, and it reported success. |
| 3 | `LOCKED` | The acceptance test is an as-of join *finding* the recovered row, never a row being present in the relation. Present-and-invisible is the exact failure this RFC exists to remove, and a row-count assertion cannot tell the two apart. |
| 4 | `ASSUMED` | Replay for `scd: type1` entities does not change. It is correct there, every fixture exercises it, and a shared rewrite would put the branch nobody needs in the path everybody takes. |
| 5 | `OPEN` | Which of §5.1, §5.2 and §5.3. The lean is §5.2 then §5.1; §6's measurement decides, and it has not been run. |
| 6 | `OPEN` | What a recovered version's `valid_from` means (§10). Three defensible answers producing three different histories. |

## 12. Phasing

None until §6's first measurement is run. That measurement is a spike — one entity, one
recovered row, one as-of join, on both targets — and it is what makes D5 answerable. Only
then is there a phase to write.
