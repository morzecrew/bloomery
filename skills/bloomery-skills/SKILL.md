---
name: bloomery-skills
description: Write a bloomery project — spec YAML (catalog, entities, mappings, metrics, marts, steps, exposures, composition), compiling to dbt, SQLMesh, MetricFlow or Cube, planning a spec change, quality rules, and the Python API. Use when creating, editing, compiling or debugging bloomery specs, or when a bloomery compile refuses.
---

# bloomery

## Mental model

A bloomery project is a directory of YAML spec documents (mappings, entity models, metrics, marts, steps, exposures, exports and imports), each identified by its version key, read against a catalog that declares the vertical's domain graph. `bloomery compile` resolves those documents into one deterministic intermediate representation, proves what it can about it, and refuses with a located error when a guardrail fails rather than emitting something wrong. A target (dbt, SQLMesh, MetricFlow, Cube) is only a rendering of that representation, so the same specs compile to any of them byte-for-byte reproducibly. bloomery reads files and executes nothing: running the emitted project is the target's job, and planning a change compares two compiled representations.

## Read the whole row

Most tasks need three to five references; read the whole row. Find your task in the routing table below and read every reference that row names, in order, before writing a spec. One reference alone leaves out a rule another one states, and the spec it produces is confidently incomplete. If no row fits, pick the closest rows and read the union, then use the index for anything they left out.

## Routing

| I want to… | Read, in order |
|---|---|
| Start a project | `mental-model` → `project-and-cli` → `catalog` → `entities` → `mappings-and-transforms` |
| Bring in a new source | `entities` → `mappings-and-transforms` → `quality-rules` → `merge-sources` |
| Build a mart and its metrics | `marts` → `metrics` → `guardrails-and-evidence` → `emit-semantic-layers` |
| Ship to dbt | `emit-dbt` → `dialects` → `plan-a-change` |
| Ship to SQLMesh | `emit-sqlmesh` → `dialects` → `plan-a-change` |
| Change a spec already in production | `plan-a-change` → `history-and-reproduction` → `emit-dbt` |
| Make a refused compile go green | `errors-and-refusals` → `guardrails-and-evidence` → `mappings-and-transforms` |
| Answer a metric request at run time | `plan-a-metric-request` → `metrics` → `python-api` |
| Compose two projects | `composition` → `guardrails-and-evidence` → `emit-dbt` |

## Index

### Foundations

- [mental-model](references/mental-model.md) — what a project is, how its documents meet, what a compile does
- [project-and-cli](references/project-and-cli.md) — install, spec layout, the ten commands, exit codes, scripting

### Specs

- [catalog](references/catalog.md) — canonical fields, recipes, metric templates, the date dimension
- [entities](references/entities.md) — grain, key, typed fields, relationships, history
- [mappings-and-transforms](references/mappings-and-transforms.md) — map a bronze source onto an entity with transform chains and recipes
- [merge-sources](references/merge-sources.md) — several mappings on one entity over a shared key space
- [resolve-identities](references/resolve-identities.md) — match records across systems with no shared key, as a Tier 3 step
- [metrics](references/metrics.md) — additivity, ratios, derived, cumulative, semi-additive, filters
- [marts](references/marts.md) — wide marts, flatten steps, date roles, history, rollups, required evidence
- [steps-and-macros](references/steps-and-macros.md) — the tier ladder, manifests, wiring, SQL parameters, macros, `runtime_lock`
- [exposures-and-annotations](references/exposures-and-annotations.md) — consumers, `owner:`, `classification:`, `grants:`
- [composition](references/composition.md) — exports, imports, compiling against an upstream IR, evidence across the boundary

### Correctness

- [guardrails-and-evidence](references/guardrails-and-evidence.md) — what a guardrail refused, what was proved, closing an open decision, `requires_evidence`
- [quality-rules](references/quality-rules.md) — field and row rules, dispositions, dedupe, reject tables and replay, reconcile, the quality mart

### Targets

- [emit-dbt](references/emit-dbt.md) — compile to dbt and run it: tests, `dbt build`, replay, schema changes
- [emit-sqlmesh](references/emit-sqlmesh.md) — compile to SQLMesh and run it: model kinds, SCD2, audits, the fingerprint
- [emit-semantic-layers](references/emit-semantic-layers.md) — the MetricFlow manifest and Cube over the marts
- [dialects](references/dialects.md) — pick a warehouse dialect; types, capabilities and where ports differ

### Change

- [plan-a-change](references/plan-a-change.md) — change classes, renames, expand/contract, backfill and replay scope, the target's refresh
- [history-and-reproduction](references/history-and-reproduction.md) — rebuild a past artifact set, trace a definition across versions
- [lineage](references/lineage.md) — walk a node upstream or downstream, node ids, `id:`

### Consumption

- [plan-a-metric-request](references/plan-a-metric-request.md) — structured requests to SQL, filters, row policies, refusals
- [python-api](references/python-api.md) — load, compile and analyse from Python; transforms and emitters
- [import-a-semantic-layer](references/import-a-semantic-layer.md) — relationships out of a MetricFlow manifest with `bloomery import`

### Running

- [errors-and-refusals](references/errors-and-refusals.md) — exit codes, stages, `source_path`, common refusals, advisories

## Documentation versions

Links to the published documentation use `https://morzecrew.github.io/bloomery/latest/<page>/`, the newest release. If the project pins an older bloomery, replace `latest` with that minor version, for example `https://morzecrew.github.io/bloomery/0.4/<page>/`, so the page matches the installed behaviour. A URL with no version segment returns 404.
