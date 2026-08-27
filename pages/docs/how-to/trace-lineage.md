# Trace where a metric comes from

`lineage()` walks the dependency graph `resolve()` already builds and hands back the part
of it your node touches — the source columns that feed a metric, or everything a column
change would reach.

```python
from bloomery import Direction, Node, NodeKind, lineage, load_catalog, load_project, resolve

resolution = resolve(load_project(sources), load_catalog(catalog_text))

walk = lineage(
    resolution.graph,
    Node(kind=NodeKind.METRIC, name="metric.gross_revenue"),
    Direction.UPSTREAM,
)
for edge in walk.edges:
    print(f"{edge.src.name} --{edge.label}--> {edge.dst.name}")
```

It reads no data, opens no connection, and touches no warehouse. This is lineage of the
**spec** — what your documents connect to what.

## The three questions it answers

**Where does this number come from?** Walk `UPSTREAM` from a metric and you get the chain
back to the source columns, with the label on each edge saying *how* — a direct mapping, a
catalog recipe by id, a macro by ref and version.

**What breaks if I change this column?** Walk `DOWNSTREAM` from a source column before a
migration and you have the blast radius. `plan()` tells you what changed *after* an edit;
this tells you what an edit would reach.

**Why is this metric unreachable, in full?** `SpecEvidence.unreachable` names the missing
leaves. The upstream walk shows the whole structure they sit in.

## From the command line

```console
$ bloomery lineage specs/ --node metric.average_order_value
metric.average_order_value  (upstream)
  canonical.quantity                   --requires-->           metric.gross_revenue
  canonical.unit_price                 --requires-->           metric.gross_revenue
  metric.gross_revenue                 --requires_metrics-->   metric.average_order_value
  metric.order_count                   --requires_metrics-->   metric.average_order_value
  order_item.quantity                  --canonical-->          canonical.quantity
  order_item.unit_price                --canonical-->          canonical.unit_price
  source.shopify__order_lines.$.qty    --direct-->             order_item.quantity
  source.shopify__order_lines.$.qty    --recipe:from_total-->  order_item.unit_price
  source.shopify__order_lines.$.total  --recipe:from_total-->  order_item.unit_price
```

`--direction downstream` walks the other way, `--direction both` merges the two, and
`--format json` emits the same value the Python call returns.

## Naming a node

A node id is the name you have already seen in a `CircularDerivation` message. Four of the
five kinds carry their kind as a prefix:

| Kind | Spelled |
| --- | --- |
| Source column | `source.<relation>.<json-path>` |
| Canonical field | `canonical.<field>` |
| Metric | `metric.<name>` |
| Step | `step.<ref>` |
| Entity field | `<entity>.<field>` — **no prefix** |

Entity fields are the exception, so `order_item.unit_price` is a whole id rather than a
suffix. Mistype one and the refusal suggests the spelling it thinks you meant:

```console
$ bloomery lineage specs/ --node metric.gross_revenu
no node named 'metric.gross_revenu' in this project's dependency graph. did you mean: metric.gross_revenue
```

## It returns a sub-DAG, not paths

`Lineage.nodes` carries each node **once**, however many ways it is reachable, and
`Lineage.edges` carries every connection between them. A node fed by two sources appears
once in `nodes` and twice in `edges`.

That is deliberate. Enumerating root-to-leaf *paths* is exponential in the graph's width —
a metric over three canonical fields, each mapped from four sources, has 64 paths through
twelve edges — so the size of the answer would not be something you could predict from the
size of your project. The sub-DAG is bounded by the graph. If you want paths, walk the
sub-DAG yourself, where you can put a budget on it.

The command line prints an edge list for the same reason: a tree cannot draw a DAG without
either repeating a shared node or dropping one of its edges.

## An empty answer is an answer

A source column has no upstream. A metric nobody composes has no downstream. Neither is an
error, and both come back as a one-node `Lineage` rather than a raise — `nodes` always
contains the root.

```console
$ bloomery lineage specs/ --node metric.order_count
metric.order_count  (upstream)
  no upstream lineage — this node is a leaf in that direction
```

`metric.order_count` is `agg: count` with no `requires:`, so it genuinely depends on no
canonical field. Nothing is missing.

## Bounding the walk

`--max-depth N` stops the walk `N` edges out; the root is depth 0. A bounded result sets
`truncated` and the command line says so, because a partial answer that cannot say it is
partial is worse than no answer:

```console
$ bloomery lineage specs/ --node metric.average_order_value --max-depth 1
metric.average_order_value  (upstream)
  metric.gross_revenue  --requires_metrics-->  metric.average_order_value
  metric.order_count    --requires_metrics-->  metric.average_order_value

  truncated: --max-depth stopped the walk; there is more beyond this
```

Bounding to nothing and finding nothing are different facts: `--max-depth 0` on a leaf is
**not** truncated, because there was nothing to cut.

## What it does not do

**It is not column-level lineage through SQL.** A catalog recipe's body is arbitrary SQL
and a step is an opaque implementation. The edge says `recipe:from_total` fed
`order_item.unit_price`; it does not say which expression inside that recipe used which
input. bloomery does not parse recipe bodies for this, and a page that implied otherwise
would be promising an analysis it does not run.

**It is not runtime lineage.** This is what your specs connect, not what actually ran.
SQLMesh and dbt both keep their own record of that.

**It is not a claim about correctness.** A clean chain from source to metric says the
spec is wired the way you wrote it. Whether the source column holds what it claims is the
[quality system](add-quality-rules.md)'s question.
