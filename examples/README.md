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
