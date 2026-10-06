# Lineage

Walk a node's lineage in the spec's dependency graph: upstream to the source columns that
feed a metric, or downstream to everything a column change would reach, through metrics
and marts to the declared exposures. It reads no data and touches no warehouse. It
describes what the documents connect, at one instant.

## The three questions

- **Where does this number come from?** Walk `upstream` from a metric. You get the chain
  back to source columns, and each edge label says how: a direct mapping, a recipe by id,
  a macro by ref and version.
- **What breaks if I change this column?** Walk `downstream` from a source column before
  the edit. `plan()` tells you what changed *after* an edit (see
  [plan-a-change](plan-a-change.md)); this tells you what an edit would reach.
- **Why is this metric unreachable, in full?** `SpecEvidence.unreachable` names the missing
  leaves; the upstream walk shows the structure they sit in.

## From the command line

```console
$ bloomery lineage specs/ --node metric.average_order_value
$ bloomery lineage specs/ --node source.shopify__order_lines.$.qty --direction downstream
$ bloomery lineage specs/ --node metric.gross_revenue --direction both --format json
```

```text
metric.average_order_value  (upstream)
  canonical.quantity                   --requires-->           metric.gross_revenue
  canonical.unit_price                 --requires-->           metric.gross_revenue
  metric.gross_revenue                 --requires_metrics-->   metric.average_order_value
  metric.order_count                   --requires_metrics-->   metric.average_order_value
  order_item.quantity                  --canonical-->          canonical.quantity
  order_item.unit_price                --canonical-->          canonical.unit_price
  source.shopify__order_lines.$.qty    --direct-->             order_item.quantity
  source.shopify__order_lines.$.total  --recipe:from_total-->  order_item.unit_price
```

`--direction` is `upstream` (default), `downstream` or `both`. `--format json` emits the
value the Python call returns. `--catalog` names the catalog when it is not
`catalog.yaml` in the directory.

## From Python

```python
from bloomery import Direction, Node, NodeKind, lineage, load_catalog, load_project, resolve

resolution = resolve(load_project(sources), load_catalog(catalog_text))

walk = lineage(
    resolution.graph,
    Node(kind=NodeKind.METRIC, name="metric.gross_revenue"),
    Direction.UPSTREAM,
    max_depth=None,
)
for edge in walk.edges:
    print(f"{edge.src.name} --{edge.label}--> {edge.dst.name}")
print("truncated:", walk.truncated)
```

`resolve()` builds the graph without compiling, so the walk answers on a project that does
not yet compile.

## Naming a node

A node id is the spelling a `CircularDerivation` message uses. Every kind but one carries
its kind as a prefix:

| Kind | Spelled |
|---|---|
| Source column | `source.<relation>.<json-path>` |
| Canonical field | `canonical.<field>` |
| Metric | `metric.<name>` |
| Step | `step.<ref>` |
| Mart (and rollup) | `mart.<name>` |
| Exposure | `exposure.<name>` |
| Entity field | `<entity>.<field>`, **no prefix** |

A mistyped id is refused with a suggestion:

```text
no node named 'metric.gross_revenu' in this project's dependency graph. did you mean: metric.gross_revenue
```

## Identity: `id:`

`metric.<name>` makes the name the identity, so a rename deletes one node and adds
another. Give a metric, canonical field or step an `id:` and the name becomes a label:

```yaml fragment
metrics:
  gross_revenue:
    id: mtr_7f3a9c        # minted once, never edited
```

The node is then `metric.mtr_7f3a9c` whatever the metric is called. The value is opaque,
compared and never parsed.

- **Write-once.** Editing an `id:` is a delete and an add; the compiler cannot tell.
- **Unique per kind.** Two nodes minting the same id, or an id equal to another node's
  name, are refused when the document is read. A copied spec file is the usual cause.
- **Optional.** A project with no `id:` gets exactly the ids and artifacts it always had.

Ask by the id, read the name: `--node metric.mtr_7f3a9c` prints `metric.gross_revenue`, and
`--format json` keeps ids in `nodes` with a `labels` object mapping each to its readable
spelling. A did-you-mean suggests the id, because a suggestion is for retyping.

The ids pay across versions: a renamed metric is one `RENAME` in `plan()` instead of a
delete and an add, and a [timeline](history-and-reproduction.md) keeps one node across the
boundary.

## What comes back

`Lineage` holds `root`, `direction`, `nodes`, `edges` and `truncated`. It is a **sub-DAG,
not a list of paths**: each node appears once in `nodes` however many ways it is reached,
and every connection appears in `edges`. Path enumeration is exponential in the graph's
width; walk the sub-DAG yourself if you need paths, with a budget.

**An empty answer is an answer.** A source column has no upstream; a metric no derived
metric, mart or exposure reads has no downstream. Both return a one-node `Lineage`
containing the root:

```text
metric.order_count  (upstream)
  no upstream lineage — this node is a leaf in that direction
```

## Bounding the walk

`--max-depth N` (Python: `max_depth=N`) stops `N` edges out; the root is depth 0. A bounded
result sets `truncated`, and the command line says so:

```console
$ bloomery lineage specs/ --node metric.average_order_value --max-depth 1
```

```text
  truncated: --max-depth stopped the walk; there is more beyond this
```

`--max-depth 0` on a node with lineage says the walk stopped before its first edge, which
is not the leaf message. On a genuine leaf it is not truncated: nothing was cut.

## What is not in the graph

- **Mart columns flattened from entities.** A metric a mart carries as a measure draws an
  edge; an entity column the mart flattens (a dimension such as `order.status`) does not,
  because flattening runs after the graph is built. `plan()` still reports it as a mart change.
- **Column lineage through SQL.** A recipe body or a step is opaque; the edge says
  `recipe:from_total` fed `order_item.unit_price`, not which expression used which input.
- **Runtime lineage.** What actually ran is dbt's or SQLMesh's record, not this one.
- **Correctness.** A clean chain says the spec is wired as written; whether a column holds
  what it claims is for [quality-rules](quality-rules.md).

Exposures are the graph's sinks and carry no SQL; only dbt emits an artifact for one, and
declaring one restricts no target.

Documentation: [trace lineage](https://morzecrew.github.io/bloomery/latest/how-to/trace-lineage/).
