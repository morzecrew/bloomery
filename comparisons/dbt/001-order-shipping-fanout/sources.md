# Sources

The cell is filled from the run recorded in `observed.txt`, not from documentation. What is
cited here is the **feature set** the configuration uses, so a reader can check that the
configuration is idiomatic rather than a strawman.

## Primary — the installed package

Version-pinned and checkable offline, which is what makes it the primary citation:

| What | Where, in the installed distributions |
|---|---|
| the shape every block in `config/models/semantic_models.yml` is validated against | `dbt/contracts/graph/unparsed.py`, `UnparsedSemanticModel`, `UnparsedEntity` and `UnparsedMeasure` |
| the `primary` and `foreign` entity types both semantic models declare | `metricflow_semantic_interfaces/type_enums/entity_type.py`, `EntityType` |
| the semantic validation dbt runs while parsing | `dbt/contracts/graph/semantic_manifest.py`, `SemanticManifest.validate` |
| the commands a dbt Core user has | `dbt/cli/main.py` — `build`, `compile`, `list`, `parse`, `run`, `show`, `test` and the rest |

```
python -c "import importlib.metadata as m; print(m.version('dbt-core'))"     # 1.12.3
python -c "import importlib.metadata as m; print(m.version('dbt-duckdb'))"   # 1.11.0
```

## Secondary — the published documentation

dbt Labs publishes this surface under `docs.getdbt.com/docs/build/` (semantic models,
entities, measures, metrics). **These pages were not fetched while this bundle was
produced**, and no cell rests on them.

## Why the wide semantic model is the idiomatic `representation` arm

A measure in this vocabulary belongs to the semantic model it is declared on, and that
model's grain is its primary entity. `UnparsedMeasure`'s keys are `name`, `agg`,
`description`, `label`, `expr`, `agg_params`, `non_additive_dimension`, `agg_time_dimension`,
`create_metric` and `config`: none names a grain for the value other than the model's own.
Declaring `shipping` on a line-grain model is therefore the only way this vocabulary states
"a line-grain mart listing shipping", and `observed.txt` records that `dbt build` accepted it.

## Why the correct number is project-authored

`dbt compile --select metric:<name>` renders nothing for either metric in this
configuration, so `9.0000` and `27.0000` in `observed.txt` come from models in
`config/models/`, written by the project author.
