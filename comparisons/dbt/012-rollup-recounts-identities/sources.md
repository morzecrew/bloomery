# Sources

The cell is filled from the run recorded in `observed.txt`, not from documentation. What is
cited here is the **feature set** the configuration uses, so a reader can check that the
configuration is idiomatic rather than a strawman.

## Primary — the installed package

Version-pinned and checkable offline, which is what makes it the primary citation:

| What | Where, in the installed distributions |
|---|---|
| the shape every block in `config/models/semantic_models.yml` is validated against | `dbt/contracts/graph/unparsed.py`, `UnparsedSemanticModel` and `UnparsedMeasure` |
| the `count_distinct` aggregation the detail measure declares | `metricflow_semantic_interfaces/type_enums/aggregation_type.py`, `AggregationType.COUNT_DISTINCT` |
| the semantic validation dbt runs while parsing | `dbt/contracts/graph/semantic_manifest.py`, `SemanticManifest.validate` |
| the commands a dbt Core user has | `dbt/cli/main.py` — `build`, `compile`, `list`, `parse`, `run`, `show`, `test` and the rest |

```
python -c "import importlib.metadata as m; print(m.version('dbt-core'))"     # 1.12.3
python -c "import importlib.metadata as m; print(m.version('dbt-duckdb'))"   # 1.11.0
```

## Secondary — the published documentation

dbt Labs publishes this surface under `docs.getdbt.com/docs/build/` (models and their
materializations, semantic models, measures, metrics). **These pages were not fetched while
this bundle was produced**, and no cell rests on them.

## Why the rollup is a model and a semantic model

A pre-aggregate in a dbt project is a model, so the rollup is authored as one and
materialized as a table, the way the case describes it being built. It is also declared as a
semantic model, because that is where this vocabulary would state what its columns are; the
only statement available for `buyers` is an aggregation, and `observed.txt` records that
`agg: sum` over it was accepted. `UnparsedSemanticModel`'s keys are `name`, `model`, `config`,
`description`, `label`, `defaults`, `entities`, `measures`, `dimensions` and
`primary_entity`: none says the model was derived by aggregating another.
