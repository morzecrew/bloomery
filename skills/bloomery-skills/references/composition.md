# Composition across projects

Let one project read another's published surface: the upstream lists what it exports, the
downstream lists what it imports under a private alias, and the compile is handed the
upstream's compiled IR. What crosses is always the IR, never spec documents, and never a
path bloomery goes looking for.

## The upstream: `exports:`

```yaml spec=exports
exports_version: 1
exports:
  name: ecom_platform
  entities: [order, order_item]
  marts: [order_items]
  metrics: [gross_revenue, order_count]
```

- At least one of `entities`, `marts`, `metrics` must be non-empty.
- `name` (pattern `^[a-z][a-z0-9_]*$`) is optional, but it is the project's only identity
  across compiles. dbt needs it (it becomes `name:` in `dbt_project.yml`; without one the
  project is called `bloomery`), and import cycles are refused by it.
- A project that both imports and exports must declare `name` (`NamelessImporter`). One that
  only exports may omit it and still be imported, though not over dbt.

## The downstream: `imports:`

```yaml spec=imports
imports_version: 1
imports:
  platform:
    entities: [order, order_item]
    marts: [order_items]
    metrics: [gross_revenue, order_count]
```

`platform` is a **local alias**, the downstream's private spelling of the upstream. It keys
the compile input and nothing else: it is not the upstream's name. Each alias lists what it
reads, grouped by kind, at least one list non-empty.

Imported names are used like local ones. A local mart over an imported entity:

```yaml spec=marts
marts_version: 1
marts:
  lines:
    grain: order_item
    base: order_item
    owner: analytics@example.com
    flatten:
      - {date: order_date, role: ordered}
    measures: [gross_revenue]
```

The mart is authored and judged here; only its inputs crossed. No model is emitted for an
imported relation, because the upstream builds it.

## Compiling: two commands

```bash
bloomery compile upstream/ --emit-ir /tmp/platform.json --out /tmp/upstream
bloomery compile downstream/ --target dbt --upstream platform=/tmp/platform.json --out /tmp/downstream
```

- `--emit-ir` writes the IR beside the artifacts and is independent of `--target`; one IR
  file serves every downstream target.
- `--upstream alias=path` is repeatable, once per alias. bloomery reads exactly the file
  you name: no registry, no package index, no lookup beside the spec directory. How the IR
  got there (a checkout, a CI artifact) is yours.
- Omitting it is refused as `UnknownUpstream`, naming the alias and what was supplied.
- The IR is versioned: one written by a different bloomery release is refused on load.
  Recompile both sides with one compiler.

## What each target does

| Target | Imported relation spelled as | Obligation |
|---|---|---|
| dbt | `{{ ref('ecom_platform', 'order_item') }}` plus a `dependencies.yml` listing the project | the upstream must export a `name`, or the dbt compile is refused |
| SQLMesh | the relation name directly | both projects compiled under the same naming policy |
| Cube, MetricFlow | read the downstream's marts | same naming policy, since they read relations the policy names |

The dbt `ref()` uses the upstream's **export name**, not the alias. A project that imports
nothing gets no `dependencies.yml`. bloomery cannot check that the two naming policies
match; a mismatch surfaces in the warehouse, not the compile.

## Fingerprints

The upstream's own fingerprint is part of the downstream's `ProjectIR`, whole. So **any**
upstream change moves the downstream fingerprint, even one touching nothing the downstream
imports: a spurious cache miss costs a compile, a missed change would be wrong output.
Reformatting the upstream's specs does not move its IR, so the downstream is undisturbed.
A fingerprint is not an identity; the export `name` is.

## Evidence across the boundary

A fact imported from an upstream grades **`ASSUMED`** here, however strong it was where it
was authored. A strict consumer over one is refused, naming the alias and the upstream's
fingerprint: a mart with `requires_evidence: locked` over an imported base, a strict mart
listing an imported metric, or a strict exposure reading an imported mart or metric.

```yaml fragment
lines:
  grain: order_item
  base: order_item          # imported from 'platform'
  requires_evidence: locked # refused
```

The two repairs: set `requires_evidence: assumed` on this consumer, or put
`requires_evidence: locked` on the upstream's mart, where the fact can be judged. It cannot
be authored in the downstream, and an upstream cannot launder a fact by being imported.

## Published pages

- [Emit dbt: composing across projects](https://morzecrew.github.io/bloomery/latest/how-to/emit-dbt/)
- [Use the CLI: composing across projects](https://morzecrew.github.io/bloomery/latest/how-to/use-the-cli/)
- [Determinism: composition](https://morzecrew.github.io/bloomery/latest/concepts/determinism/)
- [What bloomery proves](https://morzecrew.github.io/bloomery/latest/concepts/what-bloomery-proves/)
