# Sources

The cell is filled from the run recorded in `observed.txt`, not from documentation. What is
cited here is the **feature set** the configuration uses, so a reader can check that the
configuration is idiomatic rather than a strawman.

## Primary — the installed package

Version-pinned and checkable offline, which is what makes it the primary citation:

| What | Where, in the installed distributions |
|---|---|
| the shape every block in `config/models/semantic_models.yml` is validated against | `dbt/contracts/graph/unparsed.py`, `UnparsedSemanticModel` and `UnparsedMeasure` |
| the `count_distinct` aggregation the sessions measure declares | `metricflow_semantic_interfaces/type_enums/aggregation_type.py`, `AggregationType.COUNT_DISTINCT` |
| the semantic validation dbt runs while parsing | `dbt/contracts/graph/semantic_manifest.py`, `SemanticManifest.validate` |
| the commands a dbt Core user has | `dbt/cli/main.py` — `build`, `compile`, `list`, `parse`, `run`, `show`, `test` and the rest |

```
python -c "import importlib.metadata as m; print(m.version('dbt-core'))"     # 1.12.3
python -c "import importlib.metadata as m; print(m.version('dbt-duckdb'))"   # 1.11.0
```

## Secondary — the published documentation

dbt Labs publishes this surface under `docs.getdbt.com/docs/build/` (semantic models,
measures and their aggregations, metrics). **These pages were not fetched while this bundle
was produced**, and no cell rests on them.

## Why the naive arm is a semantic model and not only a model

The corpus's naive spec states the wrong fact in the vocabulary; here the same fact is stated
the only way dbt's vocabulary can state it — a `sum` measure over the per-day column — so the
run shows what dbt does with the statement, not only with the SQL. `UnparsedMeasure`'s keys
are `name`, `agg`, `description`, `label`, `expr`, `agg_params`, `non_additive_dimension`,
`agg_time_dimension`, `create_metric` and `config`; none describes what a column already
holds.
