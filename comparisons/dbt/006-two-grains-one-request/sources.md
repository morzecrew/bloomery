# Sources

The cell is filled from the run recorded in `observed.txt`, not from documentation. What is
cited here is the **feature set** the configuration uses, so a reader can check that the
configuration is idiomatic rather than a strawman.

## Primary — the installed package

Version-pinned and checkable offline, which is what makes it the primary citation:

| What | Where, in the installed distributions |
|---|---|
| the shape every block in `config/models/semantic_models.yml` is validated against | `dbt/contracts/graph/unparsed.py`, `UnparsedSemanticModel`, `UnparsedEntity` and `UnparsedMeasure` |
| the `primary` and `foreign` entity types that relate the two semantic models | `metricflow_semantic_interfaces/type_enums/entity_type.py`, `EntityType` |
| the semantic validation dbt runs while parsing | `dbt/contracts/graph/semantic_manifest.py`, `SemanticManifest.validate` |
| the commands a dbt Core user has | `dbt/cli/main.py` — `build`, `compile`, `list`, `parse`, `run`, `show`, `test` and the rest |

```
python -c "import importlib.metadata as m; print(m.version('dbt-core'))"     # 1.12.5
python -c "import importlib.metadata as m; print(m.version('dbt-duckdb'))"   # 1.11.0
```

## Secondary — the published documentation

dbt Labs publishes this surface under `docs.getdbt.com/docs/build/` (semantic models,
entities, measures, metrics). **These pages were not fetched while this bundle was
produced**, and no cell rests on them.

## Why the composition is project-authored

The facts a planner would need — which grain each measure belongs to, and the entity that
relates the two grains — are all declared in `config/models/semantic_models.yml` and accepted.
What would read them into a plan is the engine that renders metrics, and in this
configuration `dbt compile --select metric:<name>` renders nothing. So the `16.0000` in
`observed.txt` comes from `config/models/two_grains_composed.sql`, written by the project
author.
