# Sources

The cell is filled from the run recorded in `observed.txt`, not from documentation. What is
cited here is the **feature set** the configuration uses, so a reader can check that the
configuration is idiomatic rather than a strawman.

## Primary — the installed package

Version-pinned and checkable offline, which is what makes it the primary citation:

| What | Where, in the `metricflow` distribution |
|---|---|
| the YAML schema every config in `config/` is validated against | `metricflow_semantic_interfaces/parsing/schemas.py` |
| `count_distinct` as a measure's `agg`, which `config/` declares | `metricflow_semantic_interfaces/type_enums/aggregation_type.py` |
| `time_granularity` on a time dimension, `month` on the rollup | `metricflow_semantic_interfaces/parsing/schemas.py`, `dimension_type_params_schema` |
| a request naming several metrics and a group-by, as `run.py` builds it | `metricflow/engine/metricflow_engine.py`, `MetricFlowQueryRequest` |
| the manifest validator, run in full | `metricflow_semantic_interfaces/validations/semantic_manifest_validator.py` |

```
python -c "import importlib.metadata as m; print(m.version('metricflow'))"   # 0.213.0
```

## Secondary — the published documentation

MetricFlow's user-facing documentation is published by dbt Labs under
`docs.getdbt.com/docs/build/` (semantic models, measures, metric_time, validation).
**These pages were not fetched while this bundle was produced**, and no cell rests on them:
they are named so a reader knows which documented surface is being exercised, and the
primary citations above are what the claim is checked against.

## Why the rollup's `buyers` is not refused

A measure's YAML schema is **closed** — `additionalProperties: False` — so its key set is
exhaustive rather than a list of the keys somebody happened to look for:

```
name  agg  agg_time_dimension  expr  agg_params  create_metric
create_metric_display_name  non_additive_dimension  description  label  config
```

`metricflow_semantic_interfaces/parsing/schemas.py`, `measure_schema`. None states that a column is already an aggregate,
or which identity a stored count is over. A semantic model's schema is closed over

```
name  node_relation  defaults  primary_entity  entities  measures  dimensions
description  label  config
```

(`semantic_model_schema`, same file) — no key relates one model to another it was built
from. The fact a refusal of `buyers_rolled` would have to read has no place in the manifest.
