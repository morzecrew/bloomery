# Sources

The cell is filled from the run recorded in `observed.txt`, not from documentation. What is
cited here is the **feature set** the configuration uses, so a reader can check that the
configuration is idiomatic rather than a strawman.

## Primary — the installed package

Version-pinned and checkable offline, which is what makes it the primary citation:

| What | Where, in the `metricflow` distribution |
|---|---|
| the YAML schema every config in `config/` is validated against | `metricflow_semantic_interfaces/parsing/schemas.py` |
| `validity_params` on a time dimension, which `config/` declares | `metricflow_semantic_interfaces/parsing/schemas.py`, `validity_params_schema` |
| `is_start` and `is_end` | `metricflow_semantic_interfaces/protocols/dimension.py` |
| entity types, `primary`, `foreign` and `natural` | `metricflow_semantic_interfaces/type_enums/entity_type.py` |
| which entity joins are valid, and the `natural`-without-validity refusal | `metricflow_semantics/model/semantics/semantic_model_join_evaluator.py` |
| the manifest validator, run in full | `metricflow_semantic_interfaces/validations/semantic_manifest_validator.py` |

```
python -c "import importlib.metadata as m; print(m.version('metricflow'))"   # 0.213.0
```

## Secondary — the published documentation

MetricFlow's user-facing documentation is published by dbt Labs under
`docs.getdbt.com/docs/build/` (semantic models, entities, slowly changing dimensions).
**These pages were not fetched while this bundle was produced**, and no cell rests on them:
they are named so a reader knows which documented surface is being exercised, and the
primary citations above are what the claim is checked against.

## Why the `primary` declaration is accepted

An entity's YAML schema is **closed** over

```
name  type  role  expr  entity  label  config
```

`metricflow_semantic_interfaces/parsing/schemas.py`, `entity_schema`. The uniqueness a
`primary` entity asserts is carried by `type` alone, and the validator reads the manifest,
not the rows, so nothing compares that assertion against the relation it is made about.
