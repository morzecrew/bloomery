# Sources

The cell is filled from the run recorded in `observed.txt`, not from documentation. What is
cited here is the **feature set** the configuration uses, so a reader can check that the
configuration is idiomatic rather than a strawman.

## Primary — the installed package

Version-pinned and checkable offline, which is what makes it the primary citation:

| What | Where, in the installed distributions |
|---|---|
| the shape every block in `config/models/semantic_models.yml` is validated against | `dbt/contracts/graph/unparsed.py`, `UnparsedSemanticModel` (including its `primary_entity` key), `UnparsedEntity` and `UnparsedMeasure` |
| `validity_params` on a time dimension | `dbt/contracts/graph/unparsed.py`, `UnparsedDimensionTypeParams.validity_params`, typed as `DimensionValidityParams` in `dbt/artifacts/resources/v1/semantic_model.py` |
| the `natural` entity type the tier model declares | `metricflow_semantic_interfaces/type_enums/entity_type.py`, `EntityType.NATURAL` |
| the rules that refused the first configuration and accept the committed one | `metricflow_semantic_interfaces/validations/primary_entity.py`, `PrimaryEntityRule`; `metricflow_semantic_interfaces/validations/entities.py`, `NaturalEntityConfigurationRule` |
| the semantic validation dbt runs while parsing | `dbt/contracts/graph/semantic_manifest.py`, `SemanticManifest.validate` |
| the commands a dbt Core user has | `dbt/cli/main.py` — `build`, `compile`, `list`, `parse`, `run`, `show`, `test` and the rest |

```
python -c "import importlib.metadata as m; print(m.version('dbt-core'))"     # 1.12.3
python -c "import importlib.metadata as m; print(m.version('dbt-duckdb'))"   # 1.11.0
```

## Secondary — the published documentation

dbt Labs publishes this surface under `docs.getdbt.com/docs/build/` (semantic models,
entities, dimensions and their SCD type II support, metrics). **These pages were not fetched
while this bundle was produced**, and no cell rests on them.

## Why the fact is represented and the join is still project-authored

The window is stated where the vocabulary puts it, on the tier semantic model. What reads that
window is the engine that renders a metric into a join, and in this configuration none does:
`dbt compile --select metric:revenue` renders nothing. So the `300.0000` in `observed.txt`
comes from `config/models/revenue_anchored.sql`, written by the project author, and the
`600.0000` from `revenue_unanchored.sql` beside it, which dbt built without comment.
