# Evolve a spec safely

Before shipping a spec change, you want to know what it breaks, what it backfills, and
which metrics feel it — so run `plan()` over the old and new compiled IRs and read the
classified diff. The differ is pure and offline: two IRs in, a `Plan` out, no lineage
service consulted.

## Diff two versions

Compile both versions (typically: the specs deployed now, and the edited specs under
review) and diff them:

```python
from bloomery import build_project_ir, load_project, plan

old_ir = build_project_ir(load_project(old_sources), catalog=catalog)
new_ir = build_project_ir(load_project(new_sources), catalog=catalog)

migration = plan(old_ir, new_ir)
for change in migration.changes:
    print(change.change_class.value, change.subject, change.detail)
```

`plan(None, new_ir)` is the initial deploy — everything additive; `plan(ir, ir)` is
always the empty plan. `migration.has_changes` and `migration.breaking` give you the
gate conditions for CI.

## The five change classes

Every diffable difference maps to exactly one `ChangeClass`:

| Class | Meaning | One-line example |
|---|---|---|
| `ADDITIVE` | Nothing existing moves | A new optional `discount` column; a new metric |
| `WIDENING` | Type widened per the assignability lattice | `unit_price: decimal(10,2)` → `decimal(12,4)` |
| `RENAME` | Identity preserved via explicit annotation | `quantity` → `qty` with `renamed_from: quantity` |
| `RESTATING` | Same shape, different meaning | `unit_price` switches recipe from `direct` to `from_total` — history must be recomputed |
| `BREAKING` | Drop / narrow / grain / key / SCD change | A metric removed; `scd: type1` → `type2` |

BREAKING changes are **classified and returned, never raised** — the differ informs,
the caller decides. Only two situations raise instead (below).

Run against a version that widens a type, adds a column, and renames another, the diff
reads:

```text
additive   field:discount    field added  (None -> decimal(12,4), optional)
rename     field:qty         renamed from 'quantity'  (quantity -> qty)
widening   field:unit_price  type widened  (decimal(10,2), optional -> decimal(12,4), optional)
```

## Rename with `renamed_from`

Without an annotation, a rename is indistinguishable from a drop plus an add — one
BREAKING and one ADDITIVE change. To preserve column identity, annotate the new name
once:

```yaml
qty: {type: int, canonical: quantity, renamed_from: quantity}
```

The annotation is one-shot: land it, apply the migration, then remove it in the next
version. A stale annotation — one whose old name never existed in the old IR — raises
`RenameTargetMissing`, because it can no longer mean anything.

## The expand/contract refusal

The one semantic rule the differ enforces is that a **contraction may not land while
something still reads the contracted surface**. Dropping or narrowing a field that a
reachable metric still references raises `ContractViolation`:

```text
ContractViolation: expand/contract violation (RFC 0007 D5):
  - field 'order_item.unit_price' is dropped but still referenced by metric(s)
    gross_revenue — expand/contract: land the metric's removal (deprecation) in a
    prior version, then drop or narrow the field
```

The workflow it enforces is the standard three-step:

1. **Deprecate** — ship a version that removes (or migrates) the referencing metrics.
   That removal is itself a BREAKING change, classified and visible in its plan.
2. **Apply** — deploy it; nothing reads the field any more.
3. **Drop** — ship the version that drops or narrows the field. Now it classifies as
   ordinary BREAKING, with no violation.

Reference edges come from the IR's own metric dependencies — the same graph that
computes reachability — so the refusal cannot miss an indirect reference through a
derived metric.

## Backfill scope and downstream impact

Beyond the change list, a `Plan` answers two operational questions:

- `backfill_scope.entities` — which entities' stored rows the change invalidates,
  sorted; `backfill_scope.restates_history` is `True` when any RESTATING change is
  present, i.e. historical numbers change meaning even though no rows need rewriting.
- `downstream_impact` — the metric names affected by any change, computed from the
  IR's dependency edges. In the diff above it is `('gross_revenue',)`: the metric
  reads the widened `unit_price`, so its consumers should know.

A practical CI gate: fail the merge when `migration.breaking` is non-empty or
`restates_history` is true, unless the change carries an explicit approval. The change
classes give you the vocabulary; the policy is yours.

## Notes

- Both IRs must come from the same bloomery version — diffing across
  `bloomery_ir_version`s raises `PlanError` asking you to recompile both sides.
- Metadata-only changes (`partition_by`, `cost_hint`, audits) classify as ADDITIVE:
  they change layout or checks, never what a stored number means.
- The full worked v1→v5 evolution sequence lives in the repository under
  [`tests/fixtures/evolution_v1/`](https://github.com/morzecrew/bloomery/tree/main/tests/fixtures)
  through `evolution_v5/`.
