# History and reproduction

A number moved and nobody can say why. Half the answer is in the warehouse; the other half
is in the specs as they stood. Two tools answer the spec half: **reproduce** a past
artifact set from the text as it stood, and **trace** one definition across a series of
versions. Neither reads data, opens a connection or touches a warehouse.

## The store is yours

bloomery compiles the spec text you hand it and has no notion of when it was written.
There is deliberately no `--as-of` and no history adapter: fetching the text as it stood is
your step, because only you know where specs live.

```console
$ git -C . show 'main@{2026-03-01}:specs/metrics.yaml'
```

```sql
SELECT name, body FROM spec_versions
 WHERE valid_from <= '2026-03-01' AND (valid_until IS NULL OR valid_until > '2026-03-01');
```

This answers what your store *said* the definitions were on that date. A change made on
the 3rd and committed on the 5th reads as the 5th. Prefer an effective date if the store
keeps one; otherwise report the result "as recorded".

## Reproduce a past artifact set

Everything after the fetch is an ordinary compile. `load_project` takes a mapping of
document name to YAML text; keep the name equal to the filename stem, since it prefixes
every error message.

```python
from bloomery import build_project_ir, compile_project, load_catalog, load_project, project_fingerprint

project = load_project(sources)  # {"metrics": "...", "entity_model": "...", ...}
catalog = load_catalog(catalog_text) if catalog_text else None

ir = build_project_ir(project, catalog)
artifacts = compile_project(project, target="sqlmesh", dialect="duckdb", catalog=catalog)

print(project_fingerprint(ir))
for artifact in artifacts:
    print(artifact.path)
```

A project with a `steps:` document needs the step registry that was in force, passed as
`steps=registry`; without it the compile refuses (*"no step 'resolve_customers' is
registered, and the registry is empty"*). A project with `imports:` needs the upstream IRs
that were in force, passed as `upstream={alias: ir}` to both calls; without them it refuses
with `UnknownUpstream`. Reproducing means reproducing the manifests and the upstreams too.

From the command line, a fetched directory fingerprints the same way, unless it imports:
`bloomery fingerprint` takes no `--upstream`, so an importing project fingerprints from
Python.

```console
$ bloomery fingerprint march/          # reads march/catalog.yaml if present
```

**Compare.** Matching fingerprints mean the project IR did not move: look for the cause in
the data and in what ran the artifacts (target, dialect, deployment). Differing ones mean
the IR moved. The fingerprint covers each upstream's fingerprint too, so it also moves on an
upstream-only change, which `plan()` does not report: `plan()` lists this project's own
changes. Give it the earlier IR first:

```python
from bloomery import build_project_ir, load_project, plan

earlier = build_project_ir(load_project(march_sources), catalog)
later = build_project_ir(load_project(june_sources), catalog)
report = plan(earlier, later)  # old first, new second; nothing checks the order
for change in report.changes:
    print(change.change_class.value, change.subject)
```

The same compile inputs (specs, catalog, target, dialect, step registry, upstream IRs) and
the same bloomery reproduce the same bytes on any machine. A fingerprint compared across
bloomery versions is meaningless, not merely noisy. And March's definitions run against
today's data: this is not time travel for the warehouse.

## Trace one definition over time

`timeline()` takes the versions in order and reports which carried the node, between which
adjacent pairs something moved, and what moved.

```python
from bloomery import SpecVersion, load_catalog, load_project, timeline

history = [
    SpecVersion(
        label=label,
        project=load_project(sources),
        catalog=load_catalog(catalog_text) if catalog_text else None,
    )
    for label, sources, catalog_text in versions  # oldest first
]

walk = timeline(history, "metric.gross_revenue")
for entry in walk.entries:
    print(entry.label, "present" if entry.present else "absent")
for change in walk.changes:
    print(f"{change.before} -> {change.after}  {change.node}  reaches {change.reaches}")
    for delta in change.facets:
        print(f"    {delta.facet}: {delta.field}  {delta.old} -> {delta.new}")
```

The same from directories; the label is the directory string as typed:

```console
$ bloomery timeline q1/ q2/ q3/ --node metric.gross_revenue
$ bloomery timeline history/*/ --node metric.gross_revenue --format json
```

The command passes no step registry and no upstream IRs, and reads directories only: a
project wiring `steps:` or `imports:`, or a history held in git revisions or a table, needs
the Python form, with `SpecVersion(..., steps=registry, upstream={alias: ir})` per version.
Without the upstreams an importing version refuses with `UnknownUpstream`.

**bloomery never sorts the history.** Order is positional; a reversed history gives a
reversed timeline and no complaint. Every version is compiled, so start coarse (one per
month) and narrow around the boundary you find. It does not interpolate: March and June
answer "between these two", never "April".

## Reading a timeline

- `entries`: one row per version supplied, present or absent; an absence keeps its place.
- `changes`: one row per adjacent pair in which a definition in the node's upstream closure
  differs. It is empty only when nothing in that closure moved, and then that is the answer.
  A gap (deleted, then added) produces no change.
- `change.node`: the node that moved, often not the one asked about. The walk covers the
  node's **upstream closure**, so a metric whose own text never moved still reports the
  field beneath it whose recipe changed.
- `change.reaches`: exposures and marts downstream of the moved node, transitively, as the
  **later** version's graph sees them: who is affected now.
- `change.facets`: never empty, one row per facet that moved; `old`/`new` are `None` where
  a value has no short spelling (a filter, a column list).

| Facet | What moved |
|---|---|
| `grain` | grain, key, dimensions a rollup keeps |
| `filter` | a metric's declared filter |
| `unit` | type, unit, tax basis, currency |
| `inputs` | fields read, a mart's measures, a step's relations |
| `body` | an expression or a recipe |
| `additivity` | aggregate, additivity class, window, ratio |
| `quality` | quality rules, dedupe, quarantine, asserts, `required` |
| `storage` | materialization, partitioning |
| `runtime` | a step's version, determinism, runtime lock, seed |
| `metadata` | something read by people and no number depends on |

A facet says a tracked property moved, never whether the number became wrong. It reads no
rows, so it cannot attribute a moved number to a moved definition.

## Renames across history

The node id is the name unless the node has an `id:`. Without one, a rename reads as a
delete and an add: two nodes, two timelines. With the same `id:` on both sides, one node
crosses the boundary and that pair's `matched_by` is `id`. Nothing matches by shape.

```yaml fragment
metrics:
  gross_revenue:
    id: mtr_7f3a9c        # minted once, never edited
```

The node is found at the first entry that carries the spelling asked for. Ask by **name**
to span an `id:` adopted partway through; ask by **id** and the versions before it existed
read absent. If the id predates the whole window, ask `metric.mtr_7f3a9c`. See
[lineage](lineage.md) for node spellings.

## Labels

Labels are yours and bloomery compares them for nothing. When you keep enough to want an
order, spell them `2026-03-01T00:00:00Z`: UTC, no offset, no fraction. Only that form
sorts lexicographically into chronological order; `2026-03-01T00:00:00-01:00` sorts before
`...Z` and is an hour later.

Documentation: [reproduce a past artifact set](https://morzecrew.github.io/bloomery/latest/how-to/reproduce-a-past-artifact-set/),
[trace a definition over time](https://morzecrew.github.io/bloomery/latest/how-to/trace-a-definition-over-time/).
