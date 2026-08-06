# RFC 0005 — Resolution: dependency DAG, recipes, reachability

- **Status:** 📝 Draft
- **Scope:** The resolve stage (`bloomery/resolve/`, spec §5.2) and the public
  `resolve(project, catalog) -> Resolution` analysis API (spec §8): building the single
  dependency DAG over source columns, mapped fields, catalog canonical fields with their
  recipes, and metrics; validating recorded recipe choices; computing metric reachability
  with specific missing leaves; cycle detection; and the topological emission order with
  lexicographic tie-breaks. Also owns all cross-spec reference validation deferred from
  parse (RFC 0002 D4). Does not cover type checking of the resolved chains (RFC 0004),
  guardrail semantics (RFC 0006), or how the topo order is consumed (IR build, RFC 0003;
  emitters, RFC 0008). New module: `bloomery/resolve/`.
- **Related:** [`rfcs/_original-smelter-spec.md`](_original-smelter-spec.md) §3.2, §3.4,
  §5.2, §8; RFC 0002 (parsed specs in, `ResolutionError` in the hierarchy §5.4), RFC 0003
  (unreachable metrics are IR members, D6; ordering rules), RFC 0004 (typecheck consumes
  resolved chains), RFC 0006 (guardrails run over the resolved DAG).
- **Origin:** Original `smelter` spec v0.1, renamed `bloomery`.

---

## 1. Summary

A pure function from parsed specs plus catalog to a `Resolution`: one dependency DAG
spanning source columns, entity fields, canonical fields (via recipes), and metrics;
recorded recipe ids validated but never chosen; reachable and unreachable metrics with
the specific missing leaves; per-field provenance; and a deterministic topological
emission order. Every failure is a `ResolutionError` with a source path, batched per
stage; cycles raise `CircularDerivation` naming the full cycle path.

## 2. Motivation

Resolution is where the four spec kinds become one graph, and where the two hardest
product questions get their answers: *which metrics can this tenant actually have* and
*why not the rest*. "You can't get margin because `cogs` is missing" is a product-facing
output (spec §5.2), not a diagnostic — it must name the exact missing leaf, so the answer
has to be computed structurally, not discovered as a downstream failure. Resolution is
also the determinism choke point: emission order comes from a topological sort whose ties,
left to dict or set accidents, are the main nondeterminism hazard in the package
(spec §5.2; RFC 0003 §2). Finally, it is the stage RFC 0002 D4 points every dangling
reference at — parse guarantees shape, resolve guarantees the graph.

## 3. Current state

Greenfield. RFC 0002 delivers the frozen spec models with source paths, and explicitly
defers reference existence to this stage. The mapping model records `recipe:` ids as
authored (spec §3.4: "recorded, not inferred at compile time"). `ResolutionError` is
declared in `bloomery/errors.py` (RFC 0002 §5.4); this RFC adds its leaves.

## 4. Goals / Non-goals

**Goals**

- One DAG over all four node kinds; no per-concern mini-graphs that can disagree.
- Validate — never choose — the recorded recipe for each mapped canonical field.
- `Resolution` result: reachable metrics, unreachable metrics with reasons, per-field
  provenance, topo order. Pure, no I/O.
- All cross-spec reference checks, batched, with source paths.

**Non-goals**

- Recipe *selection* — choosing among a catalog field's ordered recipes happens upstream
  (where the LLM may participate, spec §3.4); the compiler validates and reproduces the
  recorded choice. Determinism and auditability both depend on this: the same specs must
  resolve identically forever, and a reviewer must see which recipe was used in the spec
  itself.
- Type checking the resolved chains — RFC 0004 runs immediately after, over this stage's
  output.
- Unit/grain/additivity legality of edges — the guardrails (RFC 0006) run over the same
  DAG but answer a different question.

## 5. Design

### 5.1 The graph (`bloomery/resolve/graph.py`)

```python
class NodeKind(StrEnum):
    SOURCE_COLUMN = "source_column"      # (mapping, jsonpath) — a bronze extraction
    ENTITY_FIELD = "entity_field"        # (entity, field)
    CANONICAL_FIELD = "canonical_field"  # (catalog field) — reached via a recipe or direct link
    METRIC = "metric"

@dataclass(frozen=True, slots=True)
class Node:
    kind: NodeKind
    name: str            # canonical dotted id, e.g. "order_item.unit_price", "metric.gross_revenue"

@dataclass(frozen=True, slots=True)
class Edge:
    src: Node            # dependency
    dst: Node            # dependent
    label: str           # "direct" | "recipe:<id>" | "requires" | "requires_metrics" | "canonical"
```

Edges point dependency → dependent. Source columns feed entity fields (via transform
chains or recipe `from` aliases); entity fields feed canonical fields (via `canonical:`
links); canonical fields feed metrics (via `requires`); metrics feed metrics (via
`requires_metrics`, e.g. `average_order_value` over `net_revenue` and `order_count`).
One graph — reachability, cycles, topo order, and guardrail traversal (RFC 0006) all read
the same structure, so they cannot disagree about what depends on what.

### 5.2 Recipe validation (`bloomery/resolve/recipes.py`)

For a mapping field in recipe form (`{recipe: <id>, from: {alias: jsonpath}}`), resolution
checks, in order, each failure a `ResolutionError` at the mapping field's source path:

1. The target entity field carries `canonical:` — a recipe without a catalog link is
   meaningless.
2. `<id>` exists among that canonical field's `recipes` in the catalog.
3. Every name in the recipe's `requires` is bound by the mapping's `from` aliases —
   exactly; unbound requires and surplus aliases are both errors (a surplus alias is a
   silent no-op otherwise, the failure mode this package exists to reject).

The recipe's `expr` is then lowered with the aliases substituted by their source-column
chains — but lowering belongs to IR build; resolution only records the binding. The
compiler never falls back to another recipe when validation fails: a stale recorded choice
(catalog evolved, recipe removed) is an error the upstream chooser must re-decide, not a
decision the compiler quietly remakes.

### 5.3 Availability and reachability (`bloomery/resolve/reach.py`)

A canonical field is **available** for an entity iff some mapped entity field links to it
via `canonical:` with either a direct mapping or a validated recipe. A metric is
**reachable** iff every leaf of its transitive `requires`/`requires_metrics` closure is an
available canonical field. Unreachable metrics are not errors — they are results:

```python
@dataclass(frozen=True, slots=True)
class UnreachableMetric:
    name: str
    missing: tuple[str, ...]     # the specific unavailable leaves, sorted
```

`missing` names leaves, not intermediate metrics: if `average_order_value` requires
`net_revenue` which requires `discount` and no mapping supplies `discount`, the reason is
`discount` — the actionable fact. This tuple is stored in the IR (RFC 0003 D6) and flows
to the product surface.

### 5.4 Cycles and ordering (`bloomery/resolve/order.py`)

Any cycle anywhere in the DAG raises `CircularDerivation` — a `ResolutionError` subclass —
whose message names the full cycle path (`metric.a → metric.b → metric.a`), rotated to
start at the lexicographically smallest node so the same cycle always prints identically.

Emission order is a topological sort with ties broken **lexicographically by node name** —
Kahn's algorithm over a sorted ready-heap, never over set iteration. This is the main
determinism hazard in the package (spec §5.2): the sort is implemented once, here, and
every consumer (IR build, emitters) takes the order from `Resolution` rather than
re-deriving it.

### 5.5 Cross-spec reference validation (`bloomery/resolve/refs.py`)

All existence checks deferred by RFC 0002 D4 live here, run before graph construction
(the graph builder may then assume references resolve):

- `mapping.target` names an entity in the EntityModel.
- Every `canonical:` on an entity field names a catalog canonical field (and its declared
  `entity:` matches).
- Relationship endpoints (`from`, `to`, `via` columns) exist.
- Metric `template:` refs name a catalog metric template; `requires` /
  `requires_metrics` names exist in the catalog / MetricSet.

Every failure is a `ResolutionError` with the referencing node's source path. Failures are
**batched per stage**: all reference errors are collected and raised as one
`ResolutionError` listing every path (the one-round-trip principle, RFC 0002 D6); recipe
validation and cycle detection then run only on a reference-clean graph, so their errors
are never cascades of a single dangling name.

### 5.6 The result type and API (`bloomery/resolve/__init__.py`)

```python
class Provenance(StrEnum):
    DIRECT = "direct"                  # mapped straight from a source column
    RECIPE = "recipe"                  # via a validated catalog recipe (id recorded)
    TENANT_NATIVE = "tenant_native"    # no canonical: link — participates in no catalog metric

@dataclass(frozen=True, slots=True)
class FieldProvenance:
    entity: str
    field: str
    provenance: Provenance
    recipe_id: str | None              # set iff provenance is RECIPE

@dataclass(frozen=True, slots=True)
class Resolution:
    reachable_metrics: tuple[str, ...]             # sorted
    unreachable_metrics: tuple[UnreachableMetric, ...]  # sorted by name
    provenance: tuple[FieldProvenance, ...]        # sorted by (entity, field)
    topo_order: tuple[Node, ...]                   # the emission order

def resolve(project: Project, catalog: Catalog | None = None) -> Resolution: ...
```

`resolve` is public API (spec §8) — the control plane calls it for analysis without
emission ("what would this tenant get?"). `catalog=None` is legal (spec: M2 runs without a
catalog): every `canonical:` link then fails reference validation *unless* no field uses
one, so a catalog-free project is direct-and-tenant-native only. `Resolution` follows the
IR ordering rules (RFC 0003 §5.3) — all tuples, explicit sorts — because it is embedded in
IR construction and its content reaches fingerprinted output.

## 6. Tests

- Unit: each reference-check failure (wrong target, dangling canonical, bad relationship
  endpoint, unknown template) asserting error type, batching, and source paths; recipe
  validation branches (missing link, unknown id, unbound require, surplus alias); cycle
  detection incl. metric-on-metric and recipe-induced cycles, asserting the rotated path;
  reachability with multi-level `requires_metrics`, asserting leaf-level `missing`.
- Property (Hypothesis): topo order is a valid linearization and invariant under input
  document order and dict permutation; `resolve` is idempotent (`resolve(p, c)` twice →
  equal `Resolution`s); on random DAGs with one edge reversed to force a cycle,
  `CircularDerivation` always names it.
- Fixtures: `ecom_basic` reports reachable/unreachable correctly (M3's done-condition);
  `multi_source` exercises two mappings feeding one entity.

## 7. Docs

Explanation page `pages/explanation/resolution.md`: the DAG, why the compiler never
chooses recipes (determinism + auditability), and how to read an unreachable-metric
report. Reference entry for `resolve` / `Resolution` in the public API page.

## 8. Out of scope

- **Recipe *choice* tooling** — a helper that ranks satisfiable recipes for the upstream
  chooser is control-plane territory; adding it here would blur the "compiler validates,
  never decides" line. Escape hatch: it could ship as a separate analysis function that
  provably does not feed compilation.
- **Identity resolution / cross-source xref** (original open question #2) — `multi_source`
  resolves as independent mappings to one entity; merging identities is a later, likely
  emitter-level concern, kept out of M1–M5 per the original spec's own lean.
- **Partial resolution / warnings mode** — resolution either produces a trusted graph or
  raises; unreachable metrics are the only "soft" output, and they are data, not warnings.

## 9. Risks

- *Leaf-level `missing` can mislead when an intermediate metric is itself unreachable for
  a non-leaf reason* (e.g. a cycle elsewhere) — mitigated by ordering: cycles raise before
  reachability runs, so `missing` is only ever computed on an acyclic, reference-clean
  graph.
- *Node-name collisions across kinds* (an entity field and a metric sharing a name) —
  prevented structurally: node ids are kind-prefixed dotted names, and the id scheme is
  pinned in tests because it reaches `CircularDerivation` messages and topo output.
- *`catalog=None` semantics read as "catalog optional in production"* — docs word it as a
  bring-up mode; reachable metrics are empty without a catalog by construction.

## 10. Unresolved questions

- None blocking. Implementation is free to settle the internal graph representation
  (adjacency maps vs edge lists) and whether `refs.py` checks run as one pass or several,
  as long as batching semantics and error paths match §5.5.

## 11. Decisions

| # | Decision |
| --- | --- |
| 1 | Resolution builds a single dependency DAG over source columns (JSONPath refs), mapped entity fields, catalog canonical fields + recipes, and metrics including `requires_metrics` metric-on-metric edges. One graph feeds reachability, cycles, topo order, and the guardrails (RFC 0006) — no parallel structures that can disagree. |
| 2 | The compiler never chooses a recipe. The mapping's recorded `recipe:` id is validated — id exists on the catalog field, every `requires` name bound by the mapping's `from` aliases (exactly) — else `ResolutionError`. Choice happens upstream; the compiler reproduces it (determinism + auditability, spec §3.4). Consequence: catalog evolution can invalidate recorded choices, and that is a loud error, not a silent re-choice. |
| 3 | A canonical field is available iff some mapped field links to it via `canonical:` with a direct mapping or validated recipe. A metric is reachable iff every leaf of its `requires`/`requires_metrics` closure is available; unreachable metrics report the specific missing leaves and are stored in the IR (RFC 0003 D6) as product-facing output. |
| 4 | Any cycle in the DAG raises `CircularDerivation` (a `ResolutionError` subclass) naming the full cycle path, rotated to the lexicographically smallest node for stable messages. |
| 5 | Emission order is a topological sort with ties broken lexicographically by node name — implemented once in resolve; all consumers take the order from `Resolution`. This is the package's main determinism hazard, contained here. |
| 6 | `Resolution` = reachable metrics, unreachable metrics + reasons, per-field provenance (`direct` \| `recipe:<id>` \| `tenant-native`), topo order — all tuples, explicitly sorted. `resolve(project, catalog)` is a pure function, no I/O, and public API. |
| 7 | All cross-spec reference validation lives here, not parse (RFC 0002 D4): mapping targets, `canonical:` links, relationship endpoints, metric template refs. All failures are `ResolutionError`s with source paths, batched per stage; later checks run only on a reference-clean graph. |

## 12. Phasing

M2 ships the graph, reference validation, cycle detection, and topo order for
catalog-free projects (direct mappings only). M3 adds catalog links, recipe validation,
availability, and reachability — `ecom_basic` reporting reachable/unreachable metrics
correctly is M3's done-condition. The guardrails (RFC 0006, M4) then traverse the same
graph without extending this module's surface.
