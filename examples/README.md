# Examples

Runnable, self-contained example projects. Each directory holds real spec YAML
plus a `run.py` that drives the public API end to end. The test fixture corpus
(`tests/fixtures/`) doubles as a larger example set — every fixture there is a
loadable project.

## quickstart/

The smallest complete project — the five core spec kinds over one `order` entity (the
sixth, `steps_version`, is optional and this project wires none):

| File | Spec kind | What it declares |
|---|---|---|
| `catalog.yaml` | Catalog | The canonical `amount` field, a `revenue` metric template, the `dim_date` date dimension |
| `entity_model.yaml` | EntityModel | The `order` entity: key, typed fields, a `not_null` assert |
| `mapping_orders.yaml` | Mapping | How the `shop__orders` bronze source becomes `order` |
| `metrics.yaml` | MetricSet | `revenue` (from the template) and an inline `order_count` |
| `marts.yaml` | MartSet | One wide `orders` mart with an `ordered` date role |

`run.py` loads the specs, compiles them to SQLMesh artifacts for DuckDB, writes
the artifacts to `examples/quickstart/out/`, then plans one `MetricRequest`
(`revenue` by `ordered_month`) and prints the rendered SQL and the
deterministic explanation.

Run it from the repository root:

```bash
uv run python examples/quickstart/run.py
```

The [Quickstart](https://morzecrew.github.io/bloomery/get-started/quickstart/)
page walks through the same project step by step.

## lakehouse/

The compiler against a real lakehouse: seven spec documents compiled to SQLMesh
artifacts, built into Apache Iceberg tables through a [Lakekeeper](https://lakekeeper.io)
REST catalog over MinIO, queried by Trino. Four containers, one command.

It shows the two things a fixture cannot: a **union merge** — two shops, one
`order_line` entity, a `_source` column, and the *blocking* collision audit that
stops the build if their key sets ever overlap — and the **quality system**,
where a bad row is flagged and kept rather than silently averaged in.

```bash
docker compose -f examples/lakehouse/compose.yaml up -d --wait
docker exec -i bloomery-lakehouse-trino-1 trino -f /dev/stdin < examples/lakehouse/seed.sql
uv run python examples/lakehouse/run.py
```

See [`lakehouse/README.md`](lakehouse/README.md), which also shows how to break
the collision audit on purpose and watch the plan refuse to publish.

## refusals/

Six specs that look right and cannot be right, and what bloomery says about
each. No containers and no setup — every case is decided at compile time.

Four of the six would run fine in a hand-written dbt or SQL project and return
rows that are silently wrong: a dimension that keeps history flattened into a
mart, an order-grain cost duplicated per line, a `one_to_many` flatten, EUR
added to USD. The other two are unsupported rather than wrong, and say which
target does support them.

```bash
cd examples/refusals
just show
```

See [`refusals/README.md`](refusals/README.md).
