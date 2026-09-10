# RFC 0067 — Marts in the lineage graph

- **Status:** 📝 Draft — small, and blocking two written RFCs.
- **Scope:** A `mart` node kind in the dependency DAG, with edges from the metrics a
  mart carries and into the exposures that read it. One new node-id prefix, one new
  reserved entity name, two new edge shapes. No spec change, no IR change, no
  fingerprint movement, no SELECT change. Deliberately **not** per-column edges from
  entity fields into a mart — §5.3 says why that is a different RFC.
- **Related:** [`src/bloomery/resolve/graph.py`](../src/bloomery/resolve/graph.py),
  [`src/bloomery/ir/nodes.py`](../src/bloomery/ir/nodes.py) (`NODE_ID_PREFIXES`),
  [`src/bloomery/guardrails/lineage.py`](../src/bloomery/guardrails/lineage.py),
  [`src/bloomery/resolve/resolution.py`](../src/bloomery/resolve/resolution.py),
  RFC 0056 (exposures; retired at `38dd7a6`), RFC 0058 (rollups; retired at `efba2b6`),
  RFC 0062 (stable node identity), RFC 0064 (definition supersession).
- **Origin:** Executing RFC 0056 found that its own §5.2 — "upstream from an exposure
  reaches metrics, marts, entities and sources" — describes a graph that has never had
  mart nodes. RFC 0064 was written against the same belief.

---

## 1. Summary

The dependency DAG runs from source columns to metrics and, since RFC 0056, on to
exposures. The gold layer is missing from the middle of it: `bloomery lineage --node
metric.gross_revenue --direction downstream` names the metrics and dashboards a change
reaches and never names `mart_order_items`, the relation that will actually be rebuilt.

A `mart` node closes that. Its edges come from what the *authored* documents say — the
measures a mart declares, and the marts an exposure declares — so the graph stays a
product of the RESOLVE stage and `bloomery lineage` keeps answering on projects that do
not compile.

## 2. Motivation

**Two live RFCs are written against a mart sink that does not exist.** RFC 0064 §4 and
§5 both say "the exposures and marts downstream, from RFC 0056", and RFC 0056 delivered
only the exposures — its §5.2 claim about marts was never true of the code. RFC 0064's P3
reuses that sink directly. This is not a nice-to-have behind two other designs; it is a
premise both are standing on.

**An exposure's mart dependency points at nothing.** RFC 0056's grammar admits
`depends_on.marts`, and a mart-only exposure is therefore a node with no incoming edge:
`lineage --node exposure.finance_extract --direction upstream` returns the node and no
edges, for a consumer whose whole declaration is what it reads. That was logged as a
departure at execution (`logs/T-0038.md`) rather than designed.

**"What breaks if I change this" stops one layer short of what breaks.** A metric is a
definition; a mart is a table someone queries. The walk that exists today ends at the
definition.

## 3. Current state

Verified against the tree, and two of these decide the design.

- **`NodeKind` has six members** — `SOURCE_COLUMN`, `ENTITY_FIELD`, `CANONICAL_FIELD`,
  `METRIC`, `STEP`, `EXPOSURE` — and `NODE_ID_PREFIXES` five prefixes (an entity field's
  id is unprefixed). `_EDGE_SHAPES` is a closed frozenset of `(label, src kind, dst kind)`
  triples, read off the builders by an AST walk in
  `tests/unit/test_resolve/test_edge_vocabulary.py`.
- **The graph is built at RESOLVE, and marts are flattened at LOWER** — one stage later
  (`resolve/build.py`'s `pipeline`, `yield Stage.RESOLVE` then `yield Stage.LOWER`).
  `build_graph(project, catalog, metrics)` therefore holds the **authored** `MartSet`:
  `base`, an authored-order `flatten` chain, and `measures` — not the resolved
  `MartColumnIR` list.
- **`bloomery lineage` calls `resolve()` and never compiles** (`cli/__init__.py`
  `_lineage`, "reads the graph off the `Resolution` rather than rebuilding it,
  RFC 0031 D2"). It answers today on a project that a guardrail would refuse.
- **A mart's measures always resolve to declared metrics.** Measured over the corpus:
  every measure of `lines`, `order_items` and even the bloomery-owned `data_quality`
  mart (`quality_rows_evaluated` and its three siblings) is a member of `ir.metrics`.
  A `metric → mart` edge cannot dangle.
- **The quality mart's columns name no entity.** Every `MartColumnIR` of `data_quality`
  carries `source_entity="data_quality"`, which is not a declared entity — `is_quality_mart`
  exists because its base is not a silver entity. Any per-column edge rule must survive
  that; §5.3's rule does so by not existing.
- **Rollups are a separate collection** (`ProjectIR.rollups`, RFC 0058 row 14: never a
  measure owner, never a covering mart) and a rollup may not take a mart's name
  (RFC 0058 D10), so the two share one relation namespace already.
- **`dim_date` is not a mart.** It is `ProjectIR.date_dimension`, emitted as a gold model
  but absent from `ir.marts` and from the authored `marts:` document.
- **RFC 0062 gives no mart an `id:`.** `node_keys` returns id maps for `metric`,
  `canonical` and `step` only.

## 4. Goals / Non-goals

**Goals**

- A `mart` node in the DAG, reachable in both directions.
- `metric → mart` edges, so downstream from a metric names the relations it lands in.
- `mart → exposure` edges, so RFC 0056's `depends_on.marts` finally points at something.
- The `mart` prefix reserved as an entity name, like the other five.
- The graph stays a RESOLVE-stage product: no new stage, no new argument that only a
  compile can supply.

**Non-goals**

- **Per-column `entity_field → mart` edges.** They need the flattener's output, which
  the graph cannot see from where it is built — §5.3, and the reason this RFC is small.
- **A `dim_date` node.** It is not a mart and has no measures; giving it a node is a
  question about the calendar's place in lineage, not about the gold layer (§10).
- **Stable ids for marts.** RFC 0062's surface, not this one's (§8).
- **Changing `plan()`.** Its impact report reads the IR's own edges deliberately —
  "no external lineage" — and a graph walk there would be a second answer to one
  question (§8).

## 5. Design

### 5.1 The node

A sixth prefix, `mart`, and a sixth `NodeKind`:

```python
def mart_node(name: str) -> Node:
    """A gold relation, e.g. ``mart.order_items``."""

    return Node(kind=NodeKind.MART, name=f"mart.{name}")
```

`mart` joins `NODE_ID_PREFIXES` and gets a `_MINTS` row, so an entity named `mart` is
refused exactly as one named `metric` is — a mart id is `mart.<name>` and an entity
field is `<entity>.<field>`, so the two collide identically.

**Named for the relation, not for the authored key.** The mart's name is what
`ctx.naming.relation(...)` turns into `mart_order_items`; the node keeps the spec's
spelling, as every other node does.

### 5.2 The edges

Two shapes, both derivable from the authored documents:

```python
("measure",    NodeKind.METRIC, NodeKind.MART),
("depends_on", NodeKind.MART,   NodeKind.EXPOSURE),
```

**Direction is not a toss-up, and the graph's existing vocabulary settles it.** Every
edge here points dependency → dependent — `requires` from a canonical field into the
metric that reads it, `depends_on` from a metric into the exposure that reads it. Under
that reading the question is only: does a change to `gross_revenue` reach
`mart_order_items`? It does — the mart embeds the measure, so redefining the metric
restates the mart's column. The converse does not hold: a mart changing does not move a
metric's definition, it only changes where the metric can be served from, which is the
planner's concern and not lineage's. So `metric → mart`, labelled `measure`.

The `mart → exposure` edge reuses RFC 0056's `depends_on` label rather than minting a
second one, because it is the same relation from a second source: the exposure declared
it, in the same `depends_on:` block.

The DAG stays acyclic by construction — nothing points out of a mart but an exposure
edge, and nothing points out of an exposure at all.

### 5.3 What is deliberately absent, and why

A mart flattens entity columns, so `order_item.unit_price → mart.order_items` is a true
edge and this RFC does not draw it. Three facts make it a different piece of work:

1. **The pairs do not exist yet.** `MartColumnIR.source_entity` / `.source_column` are
   the flattener's output, produced at LOWER; the graph is built at RESOLVE (§3).
2. **Making the graph wait for LOWER costs `bloomery lineage` its best property.** It
   answers today on a project a guardrail would refuse — which is when a lineage question
   is most useful. A graph that needs a finished IR answers only for projects that
   already compile.
3. **The graph is a graph of declarations.** Every node in it is something a document
   names. A mart's column list is derived, and the flatten chain that derives it is
   transitive and prefixed; putting its output in the DAG puts a computed artifact among
   declared ones.

The cost is stated rather than hidden: a change to a mart **dimension** column that no
metric reads will not name the mart. See §9.

### Alternatives considered

**Per-column edges, with the graph moved after LOWER.** The most complete answer, and the
one this RFC would take if the graph had no other callers. It loses (2) above, and it
makes `Resolution` — which currently carries the graph its own reachability was computed
from — either incomplete or dependent on a later stage. Reopening it means reopening D2.

**Conservative entity-level edges: every field of every entity a mart reads.** Derivable
at RESOLVE from `base` plus each `via:` hop's relationship, and it would close the gap in
§9. Rejected because it is not conservative, it is wrong: `lineage --node
order.some_field --direction downstream` would name a mart that does not carry that
column. Overstating a dbt selector is safe; overstating a precision tool's answer is the
one thing it may not do.

**A `gold` node kind covering marts, rollups and `dim_date` together.** One kind for one
layer is tidy and merges three things with different declarations behind one name; the
prefix is published surface, so the merge would be hard to undo.

### 5.4 Rollups

A rollup becomes a `mart` node too, with a `mart → mart` edge from its parent labelled
`rollup`:

```python
("rollup", NodeKind.MART, NodeKind.MART),
```

One kind and one prefix for both, which RFC 0058 D10 makes safe: a rollup may not take a
mart's name, so the namespace cannot collide. Row 14 keeps a rollup out of every
*planner*-shaped walk — measure ownership, covering-mart search — and a lineage node is
neither. A reader asking what reads `order_items` wants `order_items_monthly` in the
answer.

## 6. Tests

- **Unit:** both edge shapes present in `_EDGE_SHAPES` and built by the AST walk; the
  reservation of `mart` as an entity name; a rollup's parent edge; the quality mart as an
  ordinary node with measure edges.
- **Both directions:** downstream from a metric reaching its marts, upstream from a
  mart reaching its measures' metrics and through them to source columns — the second
  is what makes the node worth having.
- **The exposure leg:** upstream from a **mart-only** exposure now returns edges. That
  case returns a node and nothing today, and it is the one RFC 0056 could not answer.
- **CLI:** `--format json` carrying a mart node, since the JSON is what a script reads.
- **Corpus:** `test_edge_vocabulary`'s two guards — the corpus is a subset of the
  declared shapes, and every declared shape is built — cover the new pair for free once
  a fixture exercises them. `ecom_basic` and `rollup_mart` already declare what is needed.
- **Not tested:** that a mart node appears for a project that fails a guardrail. It does,
  by construction, because the graph is built before the guardrail stage runs — asserting
  it would pin the stage order twice.

## 7. Docs

- `pages/docs/how-to/trace-lineage.md`: the sixth node kind in the table, and one line
  saying a mart's *columns* are not edges.
- `pages/docs/how-to/declare-an-exposure.md`: the mart-only upstream walk now answers;
  the sentence added by RFC 0056's execution saying it does not comes out.
- `CHANGELOG.md`.

## 8. Out of scope

- **Stable ids for marts (RFC 0062).** Without one, renaming a mart deletes a node and
  adds another — the exact problem 0062 exists to solve, and it currently covers metrics,
  canonical fields and steps. Naming it here so the gap is recorded, not filled.
- **`plan()` reading the graph.** `Plan.downstream_impact` and `affected_exposures` are
  computed from `MetricIR.depends_on` and the change table; two answers to "what does
  this reach" is worse than one, whichever is better.
- **Column-level attribution inside a mart.** RFC 0064 §8 already names this as needing
  identity below node level.
- **A node for the reject tables or the replay artifacts.** They are silver, and nothing
  has asked.

## 9. Risks

- **The dimension-column gap is real and will be met.** A mart flattens `order.status`;
  no metric reads it; a dashboard groups by it. Changing that column reaches the mart in
  fact and not in the graph. Mitigated by saying so in the docs rather than by pretending
  otherwise, and by §5.3's alternative being written down rather than re-derived.
- **Two `depends_on` sources into one exposure.** Metric and mart edges share a label, so
  an exposure naming both a metric and the mart serving it shows two edges that a reader
  may read as double-counting. They are two declarations, and both were authored.
- **A sixth reserved entity name.** Any project with an entity called `mart` stops
  compiling. Same class as RFC 0051's four and RFC 0056's fifth; the refusal names the
  fix.

## 10. Unresolved questions

- **Whether `dim_date` becomes a node.** It is emitted as a gold model, every
  role-playing mart reads it, and it is declared in the *catalog* rather than in
  `marts:`. A `date_dimension` prefix, a `mart` node for a thing that is not in
  `marts:`, or nothing — the answer probably depends on whether anyone asks a lineage
  question about the calendar.
- **Whether an exposure's `depends_on.marts` should admit a rollup.** RFC 0056 §10 asked
  whether that key was needed at all and execution refused a rollup named there with its
  own message. Once both are one node kind, refusing one of them needs a better reason
  than it has.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | The edge is `metric → mart`, labelled `measure` — dependency → dependent, like every other edge in this graph. A change to a metric restates the mart column that embeds it; a change to a mart moves no metric's definition. Reversing this inverts every downstream walk that reads the gold layer. |
| 2 | `LOCKED` | The graph stays a **RESOLVE**-stage product, built from authored documents. No mart edge may require the flattener's output. This is what keeps `bloomery lineage` able to answer on a project that does not compile — which is when the question is most worth asking — and reversing it moves the graph out of `Resolution`, whose reachability report is computed from it. |
| 3 | `LOCKED` | Follows from row 2, and stated separately because it is the thing an executor will be tempted to add: **no per-column `entity_field → mart` edge**. The consequence is stated in §9 and not mitigated: a mart dimension no metric reads is not reached by a downstream walk. |
| 4 | `LOCKED` | `mart` joins `NODE_ID_PREFIXES` and the entity-name reservation, with a `_MINTS` row. A rule that held for five prefixes of six would be learned as a list of exceptions, which is RFC 0051 D7's argument unchanged. |
| 5 | `ASSUMED` | A rollup is a `mart` node, with a `rollup`-labelled edge from its parent. RFC 0058 D10 refuses a rollup that takes a mart's name, so one namespace is safe; row 14 keeps rollups out of *planner* walks, and a lineage node is not one. |
| 6 | `ASSUMED` | The quality mart is a node like any other. Its measures are declared metrics (§3, measured), so its edges are ordinary; it has no column edges to lack, because row 3 gives no mart any. |
| 7 | `ASSUMED` | `plan()` is untouched. Its impact report reads the IR's own edges by design, and a graph walk beside it would be a second answer to one question. |
| 8 | `OPEN` | Whether `dim_date` gets a node, and under which prefix. §10 states the three candidates; whoever builds this decides and logs the decision, or defers it explicitly. |
| 9 | `OPEN` | Whether `depends_on.marts` should now admit a rollup. The refusal that exists was written when a rollup was not a node; if it stays, it needs its reason restated in the new world. |

## 12. Phasing

One phase, one PR. The node, both edge shapes, the rollup edge, the reservation, the
tests and the docs — there is no half of this worth landing alone, and the exposure edge
is the payoff rather than a follow-up.
