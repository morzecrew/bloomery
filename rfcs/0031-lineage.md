# RFC 0031 — Lineage

- **Status:** 📝 Draft — design proposed, not scheduled. The trigger is a consumer that
  needs to answer "where does this number come from" or "what breaks if I change this
  column": an impact check before a source migration, a debugging session over a wrong
  metric, or a catalogue UI. Nothing in the compiler needs it.
- **Scope:** A **traversal** over the dependency DAG `resolve()` already builds, exposed
  as a value. New module `resolve/lineage.py`, three new names on `bloomery.__all__`
  (`Graph`, `Edge`, `Lineage`), one new field on
  [`Resolution`](../src/bloomery/resolve/resolution.py), and one new CLI subcommand. **No
  change to how the graph is built**, no new node kinds, no new edges, no change to
  reachability, ordering, refusals or emitted artifacts. The blast radius is additive: the
  structure is already correct, already deterministic and already discarded, and this
  document is about giving it a reader.
- **Related:**
  - [`src/bloomery/resolve/graph.py`](../src/bloomery/resolve/graph.py) — the DAG, its five
    node kinds and its edge labels
  - [`src/bloomery/resolve/reach.py`](../src/bloomery/resolve/reach.py) — the one traversal
    that exists today, and the shape this generalises
  - [`src/bloomery/resolve/resolution.py`](../src/bloomery/resolve/resolution.py) —
    `Resolution`, `FieldProvenance`, `_field_provenance`
  - RFC 0005 — the single dependency DAG (D1), unreachable metrics as results (D3), the
    resolve stage's product (D6)
  - RFC 0030 — the unresolved-work report; its D8 restores field-level `provenance` to
    `SpecEvidence`, and §5.2 below draws the boundary between that and this
  - RFC 0022 — `SpecEvidence`, `Stage`, and D5's stage-first rule

---

## 1. Summary

`resolve()` builds a complete dependency DAG on every call — source columns, entity
fields, canonical fields, metrics and steps, with labelled edges — uses it for cycle
detection, availability and reachability, and then throws away everything except its
topological order. `Graph`, `Edge` and `build_graph` are not exported; a caller holding a
`Resolution` gets `topo_order: tuple[Node, ...]`, which is every node in dependency order
**with no edges**, so the one question the structure exists to answer cannot be asked of
it.

This RFC adds `lineage(graph, node, direction)`, returning the **reachable sub-DAG** —
nodes and labelled edges — rather than enumerated paths, plus a `Lineage` value, a
`Resolution.graph` field, and a `bloomery lineage` subcommand. It adds no traversal the
compiler needs; every consumer is external.

## 2. Motivation

**The graph is already correct and nobody can read it.** Confirmed against the current
tree:

- `bloomery.__all__` exports `Node` and `NodeKind` — the two types you would use to *name*
  a position in the graph — and does **not** export `Graph`, `Edge` or `build_graph`. So
  the public surface hands out coordinates for a space it does not hand out.
- `Resolution.topo_order` is `tuple[Node, ...]`. A caller can see that
  `source.shopify__order_lines.$.total` precedes `metric.gross_revenue` and cannot see
  whether one has anything to do with the other.
- Measured on the fixture corpus: `ecom_basic` is 21 nodes and 16 edges; `identity_resolution`
  is 22 nodes and 21 edges. These are small, complete, and rebuilt on every `resolve()`.

**Three questions have no answer today, and each has a real caller.**

1. *Where does this metric come from?* A wrong number is debugged by walking back to the
   source columns that feed it. Today that walk is done by hand across mapping documents
   and the catalog.
2. *What breaks if I change this source column?* A source migration wants the blast radius
   before it starts. `plan()` answers what changed *after* an edit; nothing answers what
   *would*.
3. *Why is this metric unreachable, in full?* `compute_reachability` already answers a
   restricted form — `missing` names unavailable leaves and `via` names the blocked
   metrics between here and them (RFC 0005 D3). That is a real traversal, and it is
   **negative-only**: it exists for blocked metrics, names only blocked intermediates, and
   goes silent the moment the metric is reachable. The general form is the same walk
   without the filter.

**The cost is low precisely because the hard parts are done.** Cycle detection runs before
any of this, on the same graph, and raises — so a traversal cannot fail to terminate and
does not need a visited-set for correctness, only for efficiency. Determinism is already
guaranteed by construction: `Graph.nodes` is sorted by name and `Graph.edges` by
`(src, dst, label)` (RFC 0003 §5.3). There is no new correctness argument to make. This is
the good-candidate property — the design work is choosing the **shape of the answer**, not
building the structure.

## 3. Current state

Verified against the tree, not from memory.

**The graph.** `build_graph(project, catalog, metrics) -> Graph` in
[`resolve/graph.py`](../src/bloomery/resolve/graph.py). `Graph` is
`(nodes: tuple[Node, ...], edges: tuple[Edge, ...])`, both explicitly sorted. `Node` is
`(kind: NodeKind, name: str)` where `name` is a kind-prefixed dotted id pinned by tests
because it reaches `CircularDerivation` messages. Five kinds: `SOURCE_COLUMN`,
`ENTITY_FIELD`, `CANONICAL_FIELD`, `METRIC`, `STEP`. `Edge` is `(src, dst, label)`,
pointing **dependency → dependent**.

**The edge-label vocabulary is wider than the code says.** `Edge.label`'s comment reads
`"direct" | "recipe:<id>" | "requires" | "requires_metrics" | "canonical"`. Compiling all
22 loadable fixtures and collecting every label actually emitted gives:

```
canonical, direct, recipe:<id>, requires, requires_metrics, step_input, step_output
```

`step_input` and `step_output` arrived with RFC 0017's `STEP` node and the comment was not
extended. This is a stale comment rather than a defect — no code switches on the list — but
lineage **is** the first reader that must handle every label, so §5.3 enumerates them and
§6 pins the enumeration against the corpus. Fixing the comment is part of this change.

**The traversals that exist.** `toposort(graph)` in `resolve/order.py`;
`available_canonicals(graph)` in `resolve/reach.py`, a single filter over `canonical`
edges; and `compute_reachability`'s memoised `blockage()`, which is a genuine recursive
walk over `requires_metrics` — the closest thing to lineage in the tree, and negative-only
as §2 describes.

**Provenance is computed twice, from two sources, and they agree.**
`_field_provenance(project)` in `resolve/resolution.py` walks the **project's mappings**,
not the graph, and produces one `FieldProvenance` per `(entity, field)` with kind
`DIRECT | NATIVE | RECIPE`. The graph encodes the same fact in its edges: a `recipe:<id>`
incoming label is `RECIPE`, an outgoing `canonical` edge is `DIRECT`, and its absence is
`NATIVE`. Measured across the corpus: **146 entries, 146 agreements, 0 mismatches.** They
are two accounts of one fact that happen to match today, which §5.2 and §9 treat as a risk
to pin rather than a duplication to remove here.

**Cycles raise first.** `resolve()` runs `toposort` before reachability, so everything
downstream of it — including anything this RFC adds — runs on an acyclic, reference-clean
graph. That is what makes the traversal's termination argument free.

**No lineage surface exists.** `bloomery explain` is the *metric query planner* — it emits
SQL and a query explanation for a `MetricRequest` — and has nothing to do with the
dependency DAG. `bloomery resolve` prints `SpecEvidence`, which carries reachability and
refusals and, under RFC 0030 D8, will carry field-level `provenance`. Neither carries an
edge.

## 4. Goals / Non-goals

**Goals**

- Answer "what does X depend on" and "what depends on X" for any node in the DAG, with the
  **labels** that say *how* — a lineage without labels is connectivity, and connectivity
  does not distinguish a direct mapping from a recipe.
- Return a value, not a rendering. The same discipline as RFC 0030: the report is data, and
  the CLI is one consumer of it.
- Stay a pure function over a graph that is already built. No I/O, no new inputs, no
  ambient nondeterminism, sorted tuples out (RFC 0003).
- Make the existing `Graph` and `Edge` types public, since a traversal that returns a
  sub-DAG is unusable if its return type is private.

**Non-goals**

- **Not column-level lineage inside SQL.** A recipe body is arbitrary SQL and a step is an
  opaque implementation; parsing either to find which input column reached which output
  column is a different project with a different failure mode. The graph's granularity is
  the granularity of the answer. Named in §8 as the escape hatch.
- **Not runtime or data lineage.** This is lineage of the *spec*, computed without touching
  a warehouse. What actually ran is the engine's business — SQLMesh and dbt both keep their
  own.
- **Not a replacement for `plan()`.** `plan()` compares two compiled projects and
  classifies what changed; lineage says what is connected in one. "What would break" and
  "what did change" are different questions and both are worth having.
- **Not a visualisation.** No DOT, no Mermaid, no HTML. A caller with the sub-DAG can
  render it however it likes; shipping one renderer means owning its taste forever.

## 5. Design

### 5.1 The traversal returns a sub-DAG, not paths

```python
class Direction(StrEnum):
    UPSTREAM = "upstream"      # follow edges dependent -> dependency
    DOWNSTREAM = "downstream"  # follow edges dependency -> dependent
    BOTH = "both"


@dataclass(frozen=True, slots=True)
class Lineage:
    """The sub-DAG reachable from ``root`` in ``direction`` (RFC 0031 D1)."""

    root: Node
    direction: Direction
    nodes: tuple[Node, ...]   # sorted by name; includes root
    edges: tuple[Edge, ...]   # sorted by (src.name, dst.name, label)
    truncated: bool = False   # True iff max_depth cut the walk short


def lineage(
    graph: Graph,
    root: Node,
    direction: Direction = Direction.UPSTREAM,
    *,
    max_depth: int | None = None,
) -> Lineage: ...
```

**The load-bearing choice is sub-DAG over paths.** A DAG's path count is exponential in
its width: a metric requiring three canonical fields, each mapped from four mappings, has
64 root-to-leaf paths through twelve edges. Returning paths makes the output size a
property the caller cannot predict from the graph size; returning the reachable sub-DAG
bounds it by the graph itself — at worst every node and every edge, which for the measured
corpus is 21 nodes and 16 edges. A caller that genuinely wants paths enumerates them from
the sub-DAG under its own budget, which is where a budget belongs.

`truncated` exists because `max_depth` is the one way this can return a *partial* answer,
and a partial answer that does not say so is the failure RFC 0022 D5 is about: an empty
result must never be readable as "nothing found" when it means "we stopped looking".

**Termination is free and stated anyway.** Cycles raise in `toposort` before this can run,
so the walk terminates on graph structure alone; the visited set is there for complexity,
not correctness. Stating it matters because a future caller may want lineage on a graph
that has *not* been through `resolve()` — see D5.

### 5.2 The boundary with RFC 0030's `provenance`

RFC 0030 D8 restores `provenance: tuple[FieldProvenance, ...]` to `SpecEvidence`: one
record per `(entity, field)` saying whether it is `DIRECT`, `NATIVE` or `RECIPE`, with the
recipe id. That is **one hop, every field, flat**. This RFC is **many hops, one node,
walked**. They are not the same product and neither subsumes the other:

- A chooser deciding what to record next wants the flat table — it asks "which fields have
  no recipe", never "walk me back from this metric".
- A debugger wants the walk — it has one wrong number and needs the chain, not a census.

**They stay separate, and a test pins that they agree** (§6). The alternative — deriving
`_field_provenance` from the graph and deleting the second account — is the right long-term
shape and is **out of scope here** (§8): RFC 0030 D8 is a live, ungraded-by-this-document
decision, and re-deciding another RFC's row from inside this one is exactly what the
corpus's amendment rules forbid. What this RFC does instead is make the duplication
*visible and checked*, so whoever unifies them later starts from a green test rather than
from an assumption.

### 5.3 Every label is handled, and the vocabulary is closed here

The traversal does not switch on labels — it follows edges — but it **carries** them, and
§3 showed the documented list is short by two. This RFC closes the vocabulary in one place:

| Label | From → To | Means |
| --- | --- | --- |
| `direct` | source column → entity field | a mapped field, no recipe |
| `recipe:<id>` | source column → entity field | a validated catalog recipe, id recorded |
| `canonical` | entity field → canonical field | the field links to a catalog canonical |
| `requires` | canonical field → metric | a metric's leaf requirement |
| `requires_metrics` | metric → metric | a metric composed of metrics |
| `step_input` | entity field → step | a step's declared input |
| `step_output` | step → entity field | a step's declared output |

`Edge.label`'s comment is corrected to match, and §6 pins the list against the fixture
corpus so the next label to arrive fails a test instead of a reader.

### 5.4 `Resolution` carries the graph

```python
@dataclass(frozen=True, slots=True)
class Resolution:
    reachable_metrics: tuple[str, ...]
    unreachable_metrics: tuple[UnreachableMetric, ...]
    provenance: tuple[FieldProvenance, ...]
    topo_order: tuple[Node, ...]
    graph: Graph                          # new
```

The graph is built on every `resolve()` today and discarded. Keeping it is a field
assignment, not a computation, and it is what makes `lineage()` reachable from the public
API without a second `build_graph` call that could — with a different catalog argument —
build a *different* graph than the one the reachability answer came from.

`topo_order` stays. It is derivable from `graph` but it is a **published** field with
callers, and RFC 0005 D6 names it as part of the resolve stage's product; deriving it away
is a breaking change for a benefit this RFC does not need.

### 5.5 CLI

```
bloomery lineage <node-id> [--direction upstream|downstream|both] [--max-depth N]
                           [--format text|json] [-d DIR] [--catalog PATH]
```

`<node-id>` is the canonical dotted id — `metric.gross_revenue`,
`source.shopify__order_lines.$.total`, `order_item.unit_price`. These ids are already
pinned by tests because they appear in `CircularDerivation` messages, so the CLI is
naming things the user has already seen in an error.

An id that names no node is a refusal that **lists the near misses** rather than exiting
with "not found": the ids are long, dotted and easy to mistype, and the graph is right
there to search. An id naming a node with no lineage in the requested direction is an
empty result and **not** an error — a source column has no upstream, and that is an answer.

Text format renders the sub-DAG as an indented tree from the root, with each child's edge
label. JSON emits the `Lineage` value through `serialize.as_json_value`, like every other
command.

### Alternatives considered

**Return enumerated paths.** Reads better for a shallow graph and is what a user asking
"where does this come from" pictures. Rejected on output size: exponential in graph width,
with no bound the caller can compute in advance. The sub-DAG is a superset of the
information and linear in the graph.

**Put lineage on `SpecEvidence` instead of `Resolution`.** `SpecEvidence` is the
"everything knowable without touching data" product (RFC 0022 D1) and is where a
spec-author-facing report belongs. Rejected because lineage is *per node* and
`SpecEvidence` is *per project*: putting it there means either computing every node's
lineage eagerly — quadratic, and thrown away — or putting a lazy accessor on a frozen value
type, which stops it being a value. `Resolution.graph` gives the caller what it needs to
ask its own question.

**Expose `build_graph` and no traversal.** Cheapest possible change: make the graph public
and let callers walk it. Rejected because it exports a data structure and a hand-walk
obligation, and every caller then writes the same visited-set, the same direction handling
and the same determinism bug — sets iterating into output is precisely what RFC 0003 bans.
One correct traversal in the library is the smaller total surface.

**Derive `_field_provenance` from the graph in this RFC.** Removes the duplication §3
measured. Rejected as scope: it re-decides RFC 0030 D8 from inside another document. §8
names it as the follow-up.

## 6. Tests

- **Traversal correctness, unit.** Hand-built graphs: a diamond (one node reachable by two
  paths appears once in `nodes`, twice in `edges`), a chain, a disconnected node, a root
  that is a leaf, `BOTH` over a node with lineage on each side.
- **`max_depth` and `truncated`.** Every truncated result sets the flag; an untruncated one
  never does. Asserted red first — a `truncated` that is always `False` passes a weak test
  and is exactly the degradation this flag exists to prevent.
- **Determinism.** Same graph, repeated calls, and across processes with `PYTHONHASHSEED`
  varied: byte-identical `nodes` and `edges` order. This is the standing corpus rule
  (RFC 0003) and the traversal's visited set is the obvious place to break it.
- **The label vocabulary is complete.** Compile every loadable fixture, collect
  `{e.label.split(":")[0] for e in graph.edges}`, assert equality with the closed set in
  §5.3. Measured today: the seven labels listed, from 22 fixtures. A new label fails this
  test, which is the intent — the failure names the table that needs a row.
- **Graph and `_field_provenance` agree.** For every fixture and every `FieldProvenance`:
  `RECIPE` iff the field's incoming edges include a `recipe:` label, `DIRECT` iff it has an
  outgoing `canonical` edge, `NATIVE` iff it does not. Measured today across the corpus:
  **146 entries, 0 mismatches.** This is the test §5.2 promises, and it is what makes the
  eventual unification a refactor rather than a rediscovery.
- **Reachability agrees with lineage.** For every unreachable metric, its `missing` leaves
  are exactly the unavailable canonical fields in its upstream lineage. Two implementations
  of one relationship, so this is a `reading-isnt-proof` battery rather than a spot check —
  and if they ever disagree, one of them is wrong about the graph both read.
- **CLI.** A known id in each direction; an unknown id refuses and names near misses; a
  source column's upstream is empty and exits `0`.
- **Not tested:** that the rendered tree is pretty. Text output is asserted for content —
  the nodes and labels present — not for layout, which would pin whitespace and buy nothing.

## 7. Docs

- A **how-to** — "Trace where a metric comes from" — in `pages/docs/how-to/`, built around
  the three §2 questions, since every one of them is a task rather than a concept.
- A **reference** entry for `lineage()`, `Lineage`, `Direction`, and the closed label table
  from §5.3. The label table is the part a reader will come back to.
- `stability.md` gains the three new `__all__` names. `Graph` and `Edge` becoming public is
  an **additive** surface change and a changelog entry: they exist today and move from
  private to published, which binds their shape to SemVer from that point on. That is the
  real cost of this RFC and it should be stated as a cost, not buried as a convenience.
- The docs must **not** claim column-level lineage. A reader who sees `recipe:from_total`
  on an edge will reasonably ask which column inside that recipe fed the result, and the
  honest answer is that bloomery does not parse recipe bodies for this (§4, §8).

## 8. Out of scope

- **Column-level lineage through recipe bodies and steps.** Would need SQL parsing of
  arbitrary recipe expressions and a contract steps do not offer. What would change it: a
  recipe grammar narrow enough to analyse, which is its own RFC.
- **Unifying `_field_provenance` with the graph.** The duplication is measured (§3) and
  pinned by a test (§6); removing it re-decides RFC 0030 D8 and belongs in whichever
  document owns that row after 0030 lands.
- **Lineage across projects.** `plan()` takes two projects; nothing here does. A cross-project
  question is a `plan()` question.
- **Caching.** Every graph in the corpus is under 25 nodes. If a project arrives where the
  traversal is measurably slow, memoising `blockage()` is the precedent to follow — but
  building a cache against no measurement is the thing this project's determinism rules
  make most expensive to get wrong.
- **A `--format dot` renderer.** Named as the escape hatch: if two consumers ask, the
  `Lineage` value has everything a renderer needs and it can ship without touching this
  design.

## 9. Risks

- **Making `Graph` and `Edge` public binds them.** They are internal today and can change
  freely; after this they are `__all__` members under `stability.md`'s SemVer rule. The
  mitigation is that both are frozen two- and three-field dataclasses that have not changed
  shape since RFC 0005, and `Node`/`NodeKind` are *already* public — so the surface is
  being completed rather than opened.
- **Lineage read as an authority on data.** A user shown a clean upstream chain may conclude
  the numbers are right. Lineage says what the spec connects, and nothing about whether the
  source column holds what it claims — the quality system answers that. Mitigated in §7's
  wording and by naming the boundary in the reference page, accepted as residual.
- **The `truncated` flag ignored.** `max_depth` is a convenience and a truncated sub-DAG
  read as complete is a wrong answer that looks right. Mitigated by defaulting `max_depth`
  to `None`, so the flag can only be `True` if the caller asked for a bound.
- **A new edge label silently outside the table.** The §6 completeness test is the mitigation
  and it fails closed. This is the same hole RFC 0029's conformance battery had per-branch
  (see [`logs/T-0002.md`](../logs/T-0002.md) D-005): a guard keyed by one dimension misses a
  second. Here the key is the label itself, which is the dimension that matters.
- **`Resolution` grows a field.** It is a frozen dataclass with positional construction in
  tests. Adding `graph` last with no default is a source break for any caller constructing
  one by hand; giving it a default hides a missing graph. Chosen: **no default**, and the
  break is a changelog line — a `Resolution` without its graph is not a thing this design
  wants to exist.

## 10. Unresolved questions

- **Does `BOTH` return one sub-DAG or two?** A single merged sub-DAG is simpler to type and
  loses the fact that a node was reached upstream rather than downstream — which matters
  for rendering, since a tree drawn from a merged DAG has no root direction. Settled by the
  first renderer; D4 delegates it.
- **Should `lineage()` accept a node *name* as well as a `Node`?** The CLI must accept a
  string and the library takes a `Node`. Whether the string form belongs in the library or
  stays a CLI concern is genuinely open; the risk of putting it in the library is a second,
  looser way to name a node.
- **Does anything want lineage on an unresolved graph?** The termination argument depends on
  cycles having raised. D5 states the precondition; whether a caller ever wants to violate
  it — to *see* a cycle rather than be refused by it — is unknown and would need a cycle-safe
  walk.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | **`lineage()` returns the reachable sub-DAG, never enumerated paths.** Path count is exponential in graph width; sub-DAG size is bounded by the graph, which is what makes the return type's size predictable from an input the caller already holds. A caller wanting paths enumerates them from the sub-DAG under its own budget. Consequence: the common "show me the chain" rendering is the caller's fold over the sub-DAG rather than a library product, and any future path API must carry a budget parameter rather than inheriting this one's silence. |
| 2 | `LOCKED` | **`Graph` and `Edge` join `bloomery.__all__`, and `Resolution` gains `graph` with no default.** A traversal returning a sub-DAG is unusable if its return type is private, and `Node`/`NodeKind` are already public — the surface is being completed. No default on the field because a `Resolution` without its graph is not a state this design wants representable. Consequence: both types are bound by `stability.md`'s SemVer rule from this point, and hand-constructed `Resolution`s in tests break loudly rather than silently carrying an empty graph. |
| 3 | `LOCKED` | **`truncated` is set iff `max_depth` cut the walk short, and `max_depth` defaults to `None`.** A partial answer that cannot say it is partial is the failure RFC 0022 D5 names; defaulting to unbounded means the flag can only be `True` when the caller asked for a bound, so no default path can produce a silent partial. |
| 4 | `OPEN` | **Whether `Direction.BOTH` returns one merged sub-DAG or an upstream/downstream pair.** Merged is simpler to type and loses which side a node came from, which the first renderer will need to draw a root. Settled by whoever builds that renderer; the executor decides and logs it. |
| 5 | `ASSUMED` | **`lineage()` requires an acyclic graph and states it as a precondition rather than checking it.** `resolve()` raises on cycles before anything downstream runs, so every graph reaching this is acyclic; a re-check would be a branch no caller can execute — and this project has already shipped one of those knowingly (see [`logs/T-0003.md`](../logs/T-0003.md) D-014). Depart from this if a caller turns up that wants to walk a cyclic graph in order to *see* the cycle. |
| 6 | `ASSUMED` | **The edge-label vocabulary is closed at seven and pinned by a corpus test.** Measured across 22 fixtures. `Edge.label`'s comment is corrected in the same change, since it is short by the two labels RFC 0017 added. Depart if a label turns out to be constructed dynamically anywhere, which would make the closed set a lie rather than a contract. |
| 7 | `ASSUMED` | **`_field_provenance` stays as it is, and a test pins that it agrees with the graph.** Measured: 146 entries, 0 mismatches. Unifying them is right and re-decides RFC 0030 D8 from inside this document, which the corpus's amendment rules forbid. Consequence: two accounts of one fact ship deliberately, with the check that makes the eventual unification a refactor instead of a rediscovery. |
| 8 | `OPEN` | **Whether `lineage()` accepts a node name as well as a `Node`.** The CLI must resolve a string either way; the question is whether that resolution is a library function or stays a CLI concern. The risk of the library form is a second, looser way to name a node. |

## 12. Phasing

**P1 — the value and the traversal.** `resolve/lineage.py`, `Lineage`, `Direction`,
`Resolution.graph`, the three `__all__` additions, the corrected label comment, and every
§6 test except the CLI ones. This is the whole design; it is one PR.

**P2 — the CLI and the docs.** `bloomery lineage`, its near-miss refusal, the text
renderer, the how-to and the reference entry. Separable because P1 is a complete, testable
library capability and the renderer is where D4's open question gets answered — splitting
them means the answer is informed by a real consumer rather than guessed at design time.

Neither phase is demand-gated: the trigger named in the status line is the whole
justification, and if no such consumer exists the RFC should stay Draft rather than ship a
surface nobody asked for.
