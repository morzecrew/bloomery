# Resolve identities across systems

Two systems describe the same customers and share no key. The CRM issues `C-1001`, billing
issues `AC-77`, and only a fuzzy match can tell they are one person. bloomery resolves this
with a **Tier 3 step**, wired in a `steps:` document. There is no `xref` spec kind and there
will not be one.

## Why a step

A declarative matcher would need blocking keys, similarity functions, thresholds and
transitive closure, none of which bloomery could typecheck, guardrail or diff. A step
carries a declared, runtime-enforced output contract, so it is the *safer* shape:

| You need | Supplied by |
|---|---|
| fuzzy matching | a `python_model` step with a typed manifest |
| two outputs from one computation | multiple declared outputs, one generated wrapper each |
| marts over the resolved entity | step outputs are synthesized as entities |
| metrics over resolved data | `canonical:` links on the wiring |
| siblings agreeing within one run | the declared cross-output `references:` audit |
| reproducible backfills | `determinism: pure` plus `runtime_lock` |

The test before adding any spec kind: *can bloomery typecheck it, guardrail it, and diff it
meaningfully?* If not, it is a step.

## The two sources stay separate entities

A merge (two mappings on one target) is the wrong tool and is refused anyway: merging needs
one shared key space. Keep each source its own entity, normalize in its mapping so the
cleaning is visible SQL, and let the step read both.

```yaml spec=entity_model
spec_version: 1
entities:
  customer_crm:
    grain: one row per customer in the CRM
    key: [source_system, source_id]
    fields:
      source_system: {type: string, required: true}
      source_id: {type: string, required: true}
      email: {type: string}
      name: {type: string}
  customer_billing:
    grain: one row per billing account
    key: [source_system, source_id]
    fields:
      source_system: {type: string, required: true}
      source_id: {type: string, required: true}
      email: {type: string}
      name: {type: string}
```

```yaml spec=mapping
mapping_version: 1
source: crm__contacts
target: customer_crm
key:
  source_system: {from: "$.system", transform: [to_string]}
  source_id: {from: "$.id", transform: [to_string]}
fields:
  email: {from: "$.email", transform: [to_string, lower, trim]}
  name: {from: "$.full_name", transform: [trim]}
```

## The wiring

This is the whole of identity resolution as an authored spec. No field could carry a
matching rule or threshold formula: the manifest declares those, and the platform owns them.

```yaml spec=steps
steps_version: 1
steps:
  - use: resolve_customers@4
    inputs: {crm: silver.customer_crm, billing: silver.customer_billing}
    outputs:
      customer: silver.customer
      customer_xref: silver.customer_xref
    parameters: {threshold: 0.9}
    canonical:
      customer: {canonical_id: customer_ref}
    quality:
      - {name: confidence_is_high, rule: expression, expr: "confidence >= 0.8", on_fail: fail}
    applies_to: {confidence_is_high: customer}
```

- **`parameters`** are bounded by the manifest. A stricter tenant changes `threshold`; it
  never forks the step.
- **`canonical:`** says which canonical field a produced column is. Without it every metric
  over the output is unreachable. It is never inferred from a matching column name.
- **`quality:`** with `on_fail: fail` lowers to a blocking audit, so a low-confidence match
  stops the run.
- **`applies_to`** names the output each rule judges; a step has several.

## The manifest

The manifest is platform code, beside the step body, never in a spec or in bloomery. It
reaches the compiler inside a `StepRegistry` the caller assembles. Its output contract is
what the generated wrapper asserts on every run.

```yaml fragment
ref: resolve_customers
version: 4
kind: python_model
entrypoint: platform_steps.resolve_customers:resolve
determinism: pure
runtime_lock: sha256:a91f
outputs:
  customer:
    grain: customer
    key: [canonical_id]
    produces:
      canonical_id: {type: string, required: true}
      confidence: {type: "decimal(4,3)"}
  customer_xref:
    grain: customer_source_row
    key: [source_system, source_id]
    produces:
      source_system: {type: string, required: true}
      source_id: {type: string, required: true}
      canonical_id: {type: string}
      method: {type: string}
    references: {canonical_id: customer}
```

## Compiling it

The CLI cannot wire steps. Compile from Python with the registry:

```python
from bloomery import Target, compile_project, load_catalog, load_project

project = load_project(documents)  # filename -> YAML text, steps.yaml included
artifacts = compile_project(
    project, target=Target.SQLMESH, dialect="duckdb", catalog=load_catalog(catalog_text), steps=registry
)
```

`registry` is the `StepRegistry` your platform builds from its manifests. A `use:` naming a
version the registry does not hold is `UnknownStep`, naming the versions it does.

What comes out: the two mapped sources as ordinary silver models with
`<entity>_key_unique` audits, one generated Python wrapper per output
(`models/silver/customer.py`, `models/silver/customer_xref.py`), the quality audit, and a
`references` audit proving every `canonical_id` in the crosswalk exists in `customer`. Each
output is its own model, so the step runs once per output; that audit is what catches a step
misdeclared as `pure`.

## Reading the result

`customer_xref` is a **total** map from source rows. A row the matcher could not resolve
appears with a NULL `canonical_id` and `method = 'none'`. So the crosswalk's id must **not**
be declared `required`: the wrapper checks required columns null-free on every run and would
abort on the first unmatched row.

Downstream, a metric or mart over `customer` is ordinary; nothing knows a step was involved.

```yaml spec=metrics
metrics_version: 1
metrics:
  customer_count:
    template: customer_count
```

## Limits

- bloomery never runs the step: it emits a wrapper that imports your entrypoint at run time.
- **dbt refuses this project.** Tier 3 steps are SQLMesh-only; Cube serves marts over the
  resolved entity like any other.
- Upgrading the matcher's libraries changes `runtime_lock`, which `plan()` classifies as
  `RESTATING` and backfills the outputs.

## Published pages

- [Resolve identities across systems](https://morzecrew.github.io/bloomery/latest/how-to/resolve-identities/)
- [Steps: referenced implementations](https://morzecrew.github.io/bloomery/latest/concepts/step-registry/)
