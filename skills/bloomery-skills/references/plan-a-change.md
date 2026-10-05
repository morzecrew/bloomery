# Plan a change

Before a spec change ships, diff the compiled project as deployed against the project as
edited, and read what it breaks, what it backfills, what it replays and which metrics and
consumers feel it. The differ is pure and offline: two IRs in, a `Plan` out.

## Diff two versions

From the command line, both directories are compiled and diffed:

```console
$ bloomery plan deployed/ proposed/
$ bloomery plan deployed/ proposed/ --catalog catalog.yaml --format json
```

```text
Changes (2, 0 breaking)
  additive  field:discount    field added
  widening  field:unit_price  type widened

Backfill scope
  (none)

Downstream metrics
  gross_revenue
```

The breaking count is the number to decide on; the rest is context. `--format json` emits
the same value `plan()` returns when it is given both sides' `node_labels` (see
[Renames](#renames)); the bare call below reports a metric or step rename as a drop plus an
add. Exit code `1` means a refusal (one of the two raises
below, or a side that does not compile), not "there are breaking changes".

From Python:

```python
from bloomery import build_project_ir, load_project, plan

old_ir = build_project_ir(load_project(old_sources), catalog=catalog)
new_ir = build_project_ir(load_project(new_sources), catalog=catalog)

migration = plan(old_ir, new_ir)
for change in migration.changes:
    print(change.change_class.value, change.subject, change.detail)
```

`plan(None, new_ir)` is the initial deploy, everything additive; `plan(ir, ir)` is empty.
Both IRs must come from the same bloomery version, or `PlanError` asks you to recompile
both sides.

## The five change classes

Every difference maps to exactly one `ChangeClass`:

| Class | Meaning | Example |
|---|---|---|
| `ADDITIVE` | nothing existing moves | a new optional column; a new metric |
| `WIDENING` | type widened along the assignability lattice | `decimal(10,2)` → `decimal(12,4)` |
| `RENAME` | identity preserved by a declaration | a field's `renamed_from:`; a metric with the same `id:` on both sides |
| `RESTATING` | same shape, different meaning | `unit_price` moves from recipe `direct` to `from_total` |
| `BREAKING` | drop, narrow, grain, key or SCD change | a metric removed; `scd: type1` → `type2` |

BREAKING changes are **classified and returned, never raised**: the differ informs, the
caller decides. Metadata-only changes (`partition_by`, `cost_hint`, audits) are ADDITIVE.

## Renames

Without a declaration a rename is a drop plus an add: one BREAKING, one ADDITIVE. Annotate
the new field name once, in the entity model:

```yaml fragment
qty: {type: int, canonical: quantity, renamed_from: quantity}
```

The annotation is one-shot: land it, apply the migration, remove it in the next version. A
stale one, whose old name is not in the old IR, raises `RenameTargetMissing`.

A **metric** or step renames through its `id:`, minted once and kept on both sides:

```yaml fragment
metrics:
  revenue_gross:            # was gross_revenue
    id: mtr_7f3a9c          # unchanged, and that is the whole declaration
```

`bloomery plan` reads the ids itself. From Python, hand them over beside the IRs, each side
with its own catalog:

```python
from bloomery import build_project_ir, load_catalog, load_project, node_labels, plan

old_project, old_catalog = load_project(old_sources), load_catalog(old_catalog_text)
new_project, new_catalog = load_project(new_sources), load_catalog(new_catalog_text)

migration = plan(
    build_project_ir(old_project, catalog=old_catalog),
    build_project_ir(new_project, catalog=new_catalog),
    old_labels=node_labels(old_project, old_catalog),
    new_labels=node_labels(new_project, new_catalog),
)
```

A rename restates nothing, so there is no backfill. What it breaks is everything that
spells the old name. The report lists what in the project cited it (metrics, marts,
rollups, exposures) under "what cited the old name"; dashboards, saved queries and runbooks
outside the project are not in that list and need their own search. An `id:`
minted only on the new side is a delete and an add. A renamed **canonical field** always
reads as a drop plus an add.

## Expand, then contract

The one rule the differ enforces: a contraction may not land while something still reads
the contracted surface. Dropping or narrowing a field a reachable metric references raises
`ContractViolation`, naming the field and the metrics. Ship it in three versions:

1. **Deprecate**: remove or migrate the referencing metrics (itself a visible BREAKING change).
2. **Apply**: deploy it; nothing reads the field any more.
3. **Drop**: drop or narrow the field, now ordinary BREAKING with no violation.

The reference edges are the IR's own metric dependencies, so an indirect reference through
a derived metric is caught too.

## What else a plan answers

| Attribute | What it says |
|---|---|
| `has_changes`, `breaking` | the gate conditions |
| `backfill_scope.entities` | entities whose stored rows the change invalidates, recompute from bronze |
| `backfill_scope.restates_history` | true when any RESTATING change is present |
| `replay_scope.entities` | entities whose `<entity>__reject` rows the change can free, parents first |
| `downstream_impact` | metric names any change reaches |
| `affected_exposures` | declared consumers those changes reach, through metrics or marts |

A replay is distinct from a backfill: it re-runs the current mapping over quarantined rows
that sit in the reject table, not in bronze's window. It is populated only where the old
disposition was `quarantine` and the rule is now gone, now `flag`, or relaxed. A tightened
rule needs a backfill and an empty replay. Run the entities in the order given.

```python
gate = migration.breaking or migration.backfill_scope.restates_history
print("backfill:", migration.backfill_scope.entities)
print("replay:", migration.replay_scope.entities)
print("tell:", migration.affected_exposures)
```

A practical CI gate fails the merge on a non-empty `breaking` or on `restates_history`,
unless the change carries an explicit approval. The classes are the vocabulary; the policy
is yours.

## The target's refresh

bloomery executes nothing; the plan tells you what to run.

- **dbt.** Every incremental model and reject table carries `on_schema_change='fail'`, so a
  field added, dropped or renamed on an incremental entity fails the next run with "schema
  out of sync". `bloomery plan` prints the rebuild beside each such change; the class stays
  what it was, because the refresh is a cost on dbt, not a change in meaning:

  ```bash
  dbt build --full-refresh -s order_line order_line__reject
  ```

  A full refresh loses resolved reject rows. Replay runs as the emitted
  `replay_<entity>` macro, which refuses when `vars.bloomery_fingerprint` differs from the
  compile that wrote it. See [emit-dbt](emit-dbt.md).
- **SQLMesh.** `sqlmesh plan` sees the changed model fingerprints and rebuilds what
  changed; replay is the emitted `replay/<entity>.sql`. See [emit-sqlmesh](emit-sqlmesh.md).

Compile the new version into a clean directory before running either.

## Before you ship

1. `bloomery check proposed/` exits `0`.
2. `bloomery plan deployed/ proposed/`: read breaking, backfill, replay, downstream.
3. Any `ContractViolation`: split the change into deprecate, apply, drop.
4. Schedule the backfill, replay and refresh the plan names, in its order.
5. Tell the owners of `affected_exposures`.

Documentation: [evolve a spec](https://morzecrew.github.io/bloomery/latest/how-to/evolve-a-spec/).
