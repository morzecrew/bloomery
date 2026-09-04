# RFC 0056 — Exposures and downstream consumers

- **Status:** 📝 Draft — schedulable; the smallest of the platform-metadata split.
- **Scope:** An `exposures:` document naming what consumes a mart or a metric — a
  dashboard, a report, a reverse-ETL sync — so that the lineage graph does not stop at
  gold. One new spec kind, one new node kind in the lineage graph, one dbt artifact, and
  a refusal for the targets with nowhere to put it. No SELECT changes.
- **Related:** [`src/bloomery/guardrails/lineage.py`](../src/bloomery/guardrails/lineage.py),
  [`src/bloomery/ir/nodes.py`](../src/bloomery/ir/nodes.py) (`NODE_ID_PREFIXES`),
  [`src/bloomery/cli/__init__.py`](../src/bloomery/cli/__init__.py) (`bloomery lineage`),
  [`src/bloomery/emit/dbt/__init__.py`](../src/bloomery/emit/dbt/__init__.py),
  RFC 0031 (lineage; retired at `bcae31d`), RFC 0030 (the unresolved-work report;
  retired at `bcae31d`).
- **Origin:** The ceiling review's third item. Split out because an exposure is the only
  member of that list that adds a **node** rather than an annotation — everything else
  decorates something bloomery already knows about.

---

## 1. Summary

`bloomery lineage --node metric:gross_revenue --direction downstream` answers with the
marts that can serve it and stops. That is the truthful answer today and it is the wrong
shape of answer: the reason anyone asks is to find out what breaks, and what breaks is
downstream of gold.

An exposure is a leaf the spec declares: a name, a kind, an owner, and the metrics and
marts it depends on. It becomes a node in the lineage graph and a dbt `exposures:` block,
and it does two jobs — it answers the downstream question, and it makes `plan()`'s
breaking-change report say *who* a break reaches.

## 2. Motivation

**The graph has no sink.** `NODE_ID_PREFIXES` is `("canonical", "metric", "source",
"step")` — sources are roots, and metrics and marts are where the graph ends. Every
consumer of a bloomery project is outside it.

**`plan()` already computes the thing an exposure would make useful.** A breaking change
reports its downstream metrics; with exposures it reports the dashboards those metrics
feed, which is the difference between "this is breaking" and "this is breaking, and here
is who to tell". That is a report change, not a new analysis.

**dbt has the artifact and bloomery emits the file it belongs in.** dbt exposures are
first-class — `dbt ls --select +exposure:*` — and this compiler already writes the
project's YAML. The cost is an emitter branch, not a mechanism.

**Metrics are declared here and consumed elsewhere, which is the whole problem.** A
metric with no exposure may be unused or may be the one the CFO reads every morning, and
`bloomery resolve`'s reachability report cannot tell those apart. It answers "can this be
computed", never "does anyone compute it".

## 3. Current state

Verified against the tree.

- **Spec kinds** are `entity_model`, `mapping`, `metric`, `steps`, plus the catalog. No
  document names a consumer.
- **Lineage node ids** carry a kind prefix from `NODE_ID_PREFIXES`; a fifth prefix is
  additive, and the reservation check `check_lineage_names` already refuses an entity
  field or metric whose name would collide with one.
- **dbt** emits `dbt_project.yml`, `models/sources.yml`, `models/schema.yml` and
  `macros/`; no exposures file.
- **Cube** has no exposure concept. Its consumers *are* the API's callers.
- **SQLMesh** has no exposure concept either. `tags` on a model is the nearest thing and
  it is a label, not an edge.
- **MetricFlow** has `saved_queries`, which is a stored request rather than a declared
  consumer. Near, and not the same thing; §10 asks whether it should be one.

## 4. Goals / Non-goals

**Goals**

- An `exposures:` document: name, kind, owner, `depends_on` naming metrics and marts.
- Exposure nodes in the lineage graph, reachable from `bloomery lineage --direction
  downstream`.
- dbt `models/exposures.yml`.
- `plan()`'s breaking report naming the exposures a change reaches.
- A guardrail refusing an exposure that depends on a metric or mart the project does not
  declare — an exposure pointing at nothing is worse than no exposure, because it reports
  clean.

**Non-goals**

- **Reading anything from a BI tool.** An exposure is declared, never discovered.
  Discovery needs credentials and a network, which RFC 0003 forbids.
- **A URL that is fetched.** An exposure may carry a `url:`; it is text.
- **Refusing an unexposed metric.** Plenty of metrics exist for ad-hoc use, and a
  "metric with no exposure" warning would be noise on day one and ignored by day three.
- **Cube and SQLMesh exposure artifacts.** Neither framework has the concept (§5.3).

## 5. Design

### 5.1 The document

```yaml
exposures_version: 1
exposures:
  weekly_revenue_review:
    kind: dashboard          # dashboard | notebook | analysis | ml | application
    owner: analytics@example.com
    url: https://bi.example.com/dash/17
    depends_on:
      metrics: [gross_revenue, order_count]
      marts: [order_items]
```

`kind` is dbt's vocabulary, adopted rather than invented: it is the only one with a
consumer, and a bloomery-specific set would have to be mapped to it anyway. The five
values are dbt's exact enum, measured by handing it each one — `report` is **not** among
them and `analysis` is, which an earlier draft of this section had backwards:

```
report     -> is not one of ['dashboard', 'notebook', 'analysis', 'ml', 'application']
analysis   -> parses
```

**The lowering is not a transcription**, and §11 D3's "verbatim" governs the vocabulary
rather than the document shape. dbt spells the key `type`, takes `owner` as an object
rather than a scalar, and takes a **flat** `depends_on` list of `ref()`/`metric()` calls
rather than the grouped form above:

```yaml
version: 2
exposures:
  - name: weekly_revenue_review
    type: dashboard
    owner: {email: analytics@example.com}
    url: https://bi.example.com/dash/17
    depends_on:
      - metric('gross_revenue')
      - metric('order_count')
      - ref('mart_order_items')
```

The bloomery document groups by kind because a spec reader needs to know which is which;
the emitted one flattens because dbt's schema does. Both are stated here so the phase that
writes the emitter is not deciding it.

### 5.2 The graph

A fifth node-id prefix, `exposure`. `check_lineage_names` reserves the prefixes, so the
reservation is one entry in `_MINTS` — **and the message is not covered as-is**: it
hardcodes "reserved as the four node-id prefixes" (`lineage.py`), which would read *four*
while listing five. The count comes off the tuple in the same change.

Its scope is narrower than it looks, which this section had wrong: the check iterates
`draft.entities` and tests `entity.name`. It refuses an *entity* named after a prefix, and
neither a metric nor an entity field. Whether the reservation should widen with the fifth
prefix is a decision the phase makes rather than an omission it inherits.

Downstream from a metric now reaches exposures; upstream from an exposure reaches
metrics, marts, entities and sources, which is the query that makes the feature worth
having — "what does this dashboard actually read" is answerable from the spec for the
first time.

### 5.3 Targets

dbt gets `models/exposures.yml`. Cube and SQLMesh get **nothing, silently** — and this is
the one place this RFC departs from the compiler's usual "refuse rather than degrade"
reflex, so the reason is stated in a decision row rather than in passing: an exposure is
not a thing those frameworks build or fail to build. Refusing a Cube compile because the
project declares a dashboard would make an annotation into a target restriction, which is
the opposite of what it is for. §11 D4.

### 5.4 `plan()`

`PlanReport` gains `affected_exposures`, computed from the full downstream graph —
**metrics and marts both**.

Deriving it from the existing downstream-metric walk alone is the obvious shortcut and is
wrong: `_downstream_impact()` returns metrics from `new.metrics` and follows
`MetricIR.depends_on`, and `_diff_marts()` adds no mart node to that walk. An exposure
that depends only on a mart — which §5.1's grammar permits — would be silently absent from
a report whose whole purpose is to be complete. A mart-only exposure is the test case.

## 6. Tests

- **Unit:** the graph, both directions; the dangling-dependency refusal.
- **Golden:** `models/exposures.yml` for a fixture that declares one, and — this is the
  assertion that matters — the *unchanged* goldens for every fixture that does not.
- **Refusal census:** the dangling-dependency message.
- **e2e:** `dbt parse` over a project with exposures, and `dbt ls --select +exposure:*`
  resolving the dependency, because a well-formed YAML naming a model that does not exist
  parses fine and fails there.
- **CLI:** `bloomery lineage --node metric:… --direction downstream --format json`
  carrying the exposure, since the JSON is the surface a script reads.

## 7. Docs

- A how-to: declaring an exposure and asking what a change breaks.
- `pages/docs/reference/api.md`: `PlanReport.affected_exposures`.
- The lineage page: the fifth node kind, and that Cube and SQLMesh emit nothing.

## 8. Out of scope

- Ownership as a general annotation — RFC 0055. An exposure's `owner` is its own field
  and does not wait for that RFC; the two agree on the spelling and nothing else.
- Freshness, grants, rollup marts, multi-project references.
- MetricFlow `saved_queries` (§10).

## 9. Risks

- **An exposure is a claim about the world and rots silently.** A dashboard deleted in
  the BI tool leaves a declaration nothing refutes, and the report keeps naming it. There
  is no fix inside a compiler that reads no network; the mitigation is that the docs say
  it plainly and the `url:` is text.
- **`depends_on` is hand-maintained.** A dashboard that starts reading a second metric
  and does not update the spec produces a report that is confidently incomplete — worse
  than no report, since a reader trusts it.
- **Scope pressure toward discovery.** "Just read the Looker API" is a small, reasonable-
  looking patch that puts a network call in a compiler that has none. The non-goal is a
  test, not a sentence.

## 10. Unresolved questions

- Whether an exposure should also emit a MetricFlow `saved_query`. The shapes are close —
  both name metrics and dimensions — but a saved query is a *request* and an exposure is a
  *consumer*, and conflating them would make the manifest claim someone runs a query
  nobody wrote.
- Whether `depends_on.marts` is needed at all, or whether an exposure should depend only
  on metrics and reach marts transitively. Marts are the physical surface and a dashboard
  can read one directly, which argues for keeping it; one dependency kind is simpler.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | Exposures are **declared**, never discovered. Discovery needs a network and credentials; RFC 0003 forbids both, and a compiler that reads a BI tool is a different program. |
| 2 | `LOCKED` | An exposure naming an undeclared metric or mart is refused. An exposure pointing at nothing reports clean, which is the failure mode the feature exists to remove. |
| 2a | `LOCKED` | `affected_exposures` walks marts as well as metrics. The metric-only walk is the shortcut that omits exactly the mart-only exposure, and an impact report that is confidently incomplete is worse than none. |
| 3 | `ASSUMED` | `kind` uses dbt's **vocabulary** verbatim — `dashboard`, `notebook`, `analysis`, `ml`, `application`, measured against dbt's own schema. It does not follow that the *document* is dbt's: the emitted form spells `type`, takes an owner object and a flat `depends_on`, and §5.1 states both shapes so the emitter phase is not deciding it. |
| 4 | `LOCKED` | Cube and SQLMesh emit nothing for an exposure, and this is **not** a refusal. Neither framework has the concept, so there is nothing to degrade; refusing a Cube compile because the project declares a dashboard would turn an annotation into a target restriction. |
| 5 | `ASSUMED` | A metric with no exposure is not reported. Most metrics are legitimately ad-hoc, and a warning nobody can act on is one everybody learns to skip. |
| 6 | `ASSUMED` | `url:` is text. It is never fetched, never validated beyond being a string, and its correctness is the author's. |

## 12. Phasing

Three commits:

1. **The spec kind and the IR node**, with the dangling-dependency refusal. No emitter
   changes — the graph is the product.
2. **The dbt artifact**, with its golden and the `dbt parse`/`dbt ls` e2e leg.
3. **`plan()`'s report**, which is one hop on a walk that already exists.
