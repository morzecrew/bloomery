# Sources

The cell is filled from the run recorded in `observed.txt`, not from documentation. What is
cited here is the **feature set** the configuration uses, so a reader can check that the
configuration is idiomatic rather than a strawman.

## Primary — the installed package

Version-pinned and checkable offline, which is what makes it the primary citation:

| What | Where, in the `metricflow` distribution |
|---|---|
| the YAML schema every config in `config/` is validated against | `metricflow_semantic_interfaces/parsing/schemas.py` |
| entity types, `primary` and `foreign` | `metricflow_semantic_interfaces/type_enums/entity_type.py` |
| which entity joins are valid | `metricflow_semantics/model/semantics/semantic_model_join_evaluator.py` |
| a request naming several metrics and a group-by, as `run.py` builds it | `metricflow/engine/metricflow_engine.py`, `MetricFlowQueryRequest` |
| the manifest validator, run in full | `metricflow_semantic_interfaces/validations/semantic_manifest_validator.py` |

```
python -c "import importlib.metadata as m; print(m.version('metricflow'))"   # 0.213.0
```

## Secondary — the published documentation

MetricFlow's user-facing documentation is published by dbt Labs under
`docs.getdbt.com/docs/build/` (semantic models, entities, measures, joins).
**These pages were not fetched while this bundle was produced**, and no cell rests on them:
they are named so a reader knows which documented surface is being exercised, and the
primary citations above are what the claim is checked against.
