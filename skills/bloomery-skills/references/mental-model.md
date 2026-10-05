# Mental model

What a bloomery project is, how its documents meet, what a compile does, and what
bloomery does and does not promise. Read this first: every other reference assumes it.

## What bloomery is

A pure compiler. Spec documents go in as YAML text; artifacts, plans and reports come
out as data. bloomery executes no SQL, reads no warehouse, schedules nothing and holds
no LLM. Running what it emits is the target's job (SQLMesh, dbt, Cube, MetricFlow).

Its failure mode is designed around one sentence: **the system may not know an answer,
but it may not return a wrong one without warning.** A spec that would produce a
plausible but wrong number (a measure summed across a fan-out, net mixed with gross, a
ratio re-averaged) is a compile error with a source path, never a warning.

## The document kinds

Every document is strict YAML: unknown keys and duplicate keys are refused. Each one
identifies itself by its version key, pinned to `1`.

| Kind | Version key | How many | Says |
|---|---|---|---|
| Catalog | `catalog_version` | one per vertical, outside the project | canonical fields, units, tax bases, recipes, relationships, metric templates, the date dimension |
| EntityModel | `spec_version` | exactly one | entities: grain, key, typed fields, relationships |
| Mapping | `mapping_version` | one per (source, entity) | how a bronze source becomes an entity |
| MetricSet | `metrics_version` | at most one | measures with grain and additivity |
| MartSet | `marts_version` | at most one | wide gold tables and rollups |
| StepSet | `steps_version` | at most one | wiring for platform-owned code |
| ExposureSet | `exposures_version` | at most one | who reads the project |
| ExportSet / ImportSet | `exports_version` / `imports_version` | at most one each | composition across projects |

The smallest complete project is an entity model and one mapping:

```yaml spec=entity_model
spec_version: 1
entities:
  order:
    grain: one row per order
    key: [order_id]
    fields:
      order_id: {type: string, required: true}
      amount: {type: "decimal(12,2)"}
```

```yaml spec=mapping
mapping_version: 1
source: shop__orders
target: order
key:
  order_id: {from: "$.id", transform: [to_string]}
fields:
  amount: {from: "$.amount", transform: [{to_decimal: [12, 2]}]}
```

## How the kinds meet

Resolution builds one dependency graph:

- source paths feed entity fields, through transform chains and recorded recipes;
- entity fields feed catalog canonical fields, through `canonical:` links;
- canonical fields feed metrics, through `requires:`;
- metrics feed metrics, through `requires_metrics:`, `ratio:` and `derived:`;
- marts read entities and serve metrics as measures.

A field without a `canonical:` link is tenant-native: legal and queryable, but it feeds no
catalog-derived metric and carries no unit or tax basis. A metric whose leaves are not all
available is **unreachable**, and bloomery names the missing leaf ("`margin` missing:
`cogs`"); an unreachable metric is an answer, not an error.

## The compile pipeline

Six pure stages. Each either produces trusted output for the next or refuses with a typed
`BloomeryError` carrying a source path into the spec.

1. **Parse**: YAML to strict models. Shape and grammar only. `SpecParseError`, batched
   per document.
2. **Resolve**: references and the graph. Dangling names, invalid recorded recipes, cycles.
   `ResolutionError`, `CircularDerivation`.
3. **Typecheck**: every transform chain against the closed whitelist. `TypeCheckError`,
   `UnknownTransformError`.
4. **Guardrails**: arithmetic that typechecks and is still wrong: units, tax basis,
   currency mixing, grain fan-out, additivity. One `GuardrailError` carrying every violation.
5. **Plan**: `plan(old_ir, new_ir)`, a structural diff classifying every change.
6. **Lower and emit**: the IR becomes target artifacts. A feature a target cannot express is
   `UnsupportedByTarget`, never a silent degradation.

Stages 2 to 4 meet at one frozen value, `ProjectIR`. Emitters and the planner read the IR,
never the specs, so the model that builds a table and the planner that queries it cannot
disagree about what it means. `evaluate()` reports which stage analysis reached and what
the earlier stages produced; `compile_project()` is all or nothing.

## Determinism

`compile(x) == compile(x)` byte for byte, across processes, machines and hash seeds. That
is why:

- the compiler **never chooses**: a mapping records which catalog recipe it uses, and the
  compiler validates the choice rather than making one;
- defaults are derived and visible, never inferred from intent;
- every artifact whose format admits a comment carries a `blm1:` fingerprint header, a hash
  of the compiled IR; the MetricFlow and retrieval JSON manifests carry none, since a
  comment would make them invalid JSON.

The fingerprint answers "did the compiled meaning change?". It is not stable across
bloomery versions and is not a migration key: specs are durable, fingerprints and
artifacts are cache.

```python
from bloomery import build_project_ir, load_catalog, load_project, project_fingerprint

catalog = load_catalog(catalog_text)
project = load_project({"entity_model.yaml": entity_text, "mapping_orders.yaml": mapping_text})
print(project_fingerprint(build_project_ir(project, catalog=catalog)))
```

## What bloomery proves

> bloomery does not prove truth. It proves preservation of declared semantics.

If you declare `shipping` an order-grain measure in dollars, every artifact and every plan
that would make it mean something else is refused. If it is really per parcel, or the
column holds euros, nothing catches it: that is a wrong declaration.

Two questions stay separate:

- **Representation safety** (an artifact): a mart may not store a measure in a shape where
  ordinary aggregation changes its meaning. Guardrails enforce it.
- **Query answerability** (a plan): a request may still be answered when the planner can
  aggregate each measure at its own grain before joining.

Unknown is not safe: a refusal can mean "unsafe" or "no rule covers this yet". Facts carry
grades: `LOCKED` (an author wrote it), `ASSUMED` (the compiler obtained it soundly).
`requires_evidence: locked` on a mart or exposure asks for authored premises only.

## What a target is

A target is a rendering of the IR, chosen at compile time: `sqlmesh`, `dbt`, `cube`,
`metricflow`. The same specs compile to any of them. Target and SQL dialect vary
independently (`duckdb`, `postgres`, `trino`). A target accepting the syntax is not
evidence of correctness: semantic acceptance happened before lowering.

## Published pages

- [Introduction](https://morzecrew.github.io/bloomery/latest/get-started/introduction/)
- [The compile pipeline](https://morzecrew.github.io/bloomery/latest/concepts/compile-pipeline/)
- [Determinism](https://morzecrew.github.io/bloomery/latest/concepts/determinism/)
- [Specs and the catalog](https://morzecrew.github.io/bloomery/latest/concepts/specs-and-catalog/)
- [What bloomery proves](https://morzecrew.github.io/bloomery/latest/concepts/what-bloomery-proves/)
