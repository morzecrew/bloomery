# Exposures and annotations

Say what reads the project (an `exposures:` document) and what surrounds its nodes:
`owner:` (who to tell), `classification:` (what a column holds) and `grants:` (who may read
a relation). None of these changes a line of SQL; only `grants:` is applied.

## Exposures: the consumers

Everything that consumes a project lives outside it. An exposure tells the compiler what
those consumers are, so lineage does not stop at gold and `plan()` can name who a breaking
change reaches. At most one document per project.

```yaml spec=exposures
exposures_version: 1
exposures:
  weekly_revenue_review:
    kind: dashboard
    owner: analytics@example.com
    url: https://bi.example.com/dash/17
    depends_on:
      metrics: [gross_revenue, order_count]
      marts: [order_items]
  finance_extract:
    kind: application
    owner: finance@example.com
    depends_on:
      marts: [orders]
```

| Key | Required | Meaning |
|---|---|---|
| `kind` | yes | `dashboard`, `notebook`, `analysis`, `ml`, `application` (dbt's vocabulary) |
| `owner` | yes | a non-empty free string |
| `depends_on` | yes | `metrics:` and/or `marts:`; the two namespaces are separate |
| `url` | no | text; never fetched, never validated |
| `requires_evidence` | no | `assumed` (default) or `locked`; a strict exposure over an imported mart or metric is refused |

**The one refusal.** A dependency naming a metric or mart the project does not declare is
refused as the spec is read (`DanglingExposure`), listing the declared names. A dangling
dependency would match no change, so the impact report would name nobody, which is worse
than no exposure, because a reader trusts it.

### Asking with it

```console
$ bloomery lineage specs/ --node exposure.weekly_revenue_review --direction upstream
$ bloomery lineage specs/ --node metric.gross_revenue --direction downstream
$ bloomery plan deployed/ proposed/ --catalog catalog.yaml
```

- Nothing is downstream of an exposure: it is the graph's only sink.
- A mart dependency draws an edge too, so the upstream walk continues through the mart's
  metrics (not its dimension columns).
- `Plan.affected_exposures` names the consumers a diff touches, reached by a changed mart
  as well as a changed metric. `bloomery plan` prints them last. Additive changes reach
  nobody.

### What gets emitted

dbt gets `models/exposures.yml` (metric dependencies written as `ref()` on the marts that
serve them, metric names kept under `meta:`). Cube and SQLMesh get nothing, and nothing is
refused. Nothing is discovered: an exposure is declared and hand-maintained, and a
dashboard deleted in the BI tool leaves a declaration nothing refutes.

## The three annotations

```yaml spec=entity_model
spec_version: 1
entities:
  customer:
    grain: one row per customer
    key: [customer_id]
    owner: growth-analytics@example.com
    grants:
      select: [analyst, reverse_etl]
    fields:
      customer_id: {type: string, required: true}
      email: {type: string, classification: pii}
      segment: {type: string, classification: internal}
```

### `owner:`, who to tell

A free string on an entity, a mart or a metric, never validated as an email or handle and
never verified; nobody is paged. It reaches each target's slot (SQLMesh `MODEL (owner …)`,
dbt `meta.owner`, Cube `meta.owner` on marts and measures, MetricFlow `config.meta.owner`).

**It does not inherit.** A mart over an owned entity has no owner until you write one, a
metric from a catalog template does not take the template's, and `metric_templates:` has
no `owner:` key. An entity's reject table does carry its owner.

### `classification:`, what a column holds

Exactly one of `public`, `internal`, `pii`, `secret`, on a field. dbt and Cube get
`meta.classification`; Cube marks `pii`/`secret` members `public: false`, which **hides a
column without protecting it** (a client naming it still gets an answer). SQLMesh gets
nothing.

A classification masks nothing, but it is checked against grants on the relations that
publish the column (a mart or rollup):

| Case | Outcome |
|---|---|
| `secret` column in a mart or rollup | refused, always, whatever is granted |
| `pii`/`secret` column in a relation granting a role the entity does not | refused (set difference, so disjoint sets are refused too) |
| equal, narrower, or `{select: []}` grants | pass |
| either side has no `grants:` block | `undeclared_audience` advisory on `evaluate()`'s result, not a refusal |

A rollup declares its own grants; it does not inherit its parent mart's.

### `grants:`, who may read it

```yaml fragment
grants:
  select: []          # no role may select
```

On an entity, a mart or a rollup. **This one is applied**: by SQLMesh at creation, by dbt
on every run. An entity's reject table is granted with it.

- **An empty list is not an absent block.** `select: []` grants no role; no block at all
  means bloomery has no opinion and the warehouse's grants stand. Even `[]` speaks only for
  the framework-managed grant set (Snowflake's `copy_grants` can carry privileges across).
- **Cube refuses a `grants:` block**: it reads relations it does not own, so the grant would
  restrict nothing.

## What is not here

- **Seeds.** `seeds:` is refused permanently ("refused, not missing"). Land the CSV with
  your loader, declare the relation as a bronze source, and map an entity onto it.
- **Row-level access** is a query-time concern, not an annotation.
- **Masking.** To keep a column from a consumer, grant a role set without them, or leave
  the column out of the mart they read. `quarantine.redact` is unrelated: it decides what
  a reject row keeps.

## Published pages

- [Declare what reads your project](https://morzecrew.github.io/bloomery/latest/how-to/declare-an-exposure/)
- [Say who owns a thing, what it holds, and who may read it](https://morzecrew.github.io/bloomery/latest/how-to/annotate-a-spec/)
