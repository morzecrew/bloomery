# Sources

The cell is filled from the run recorded in `observed.txt`, not from documentation. What is
cited here is the **feature set** the configuration uses, so a reader can check that the
configuration is idiomatic rather than a strawman.

## Primary — the installed package

Version-pinned and checkable offline, which is what makes it the primary citation:

| What | Where, in the `metricflow` distribution |
|---|---|
| the YAML schema every config in `config/` is validated against | `metricflow_semantic_interfaces/parsing/schemas.py` |
| the `ratio` metric type | `metricflow_semantic_interfaces/implementations/metric.py` |
| `non_additive_dimension` on a measure | `metricflow_semantic_interfaces/protocols/measure.py` |
| the manifest validator, run in full | `metricflow_semantic_interfaces/validations/semantic_manifest_validator.py` |

```
python -c "import importlib.metadata as m; print(m.version('metricflow'))"   # 0.212.0
```

## Secondary — the published documentation

MetricFlow's user-facing documentation is published by dbt Labs under
`docs.getdbt.com/docs/build/` (semantic models, measures, metrics overview, validation).
**These pages were not fetched while this bundle was produced**, and no cell rests on them:
they are named so a reader knows which documented surface is being exercised, and the
primary citations above are what the claim is checked against.

## Why `NOT-REPRESENTED` rather than "not found"

A measure's YAML schema is **closed** — `additionalProperties: False` — so its key set is
exhaustive rather than a list of the keys somebody happened to look for:

```
name  agg  agg_time_dimension  expr  agg_params  create_metric
create_metric_display_name  non_additive_dimension  description  label  config
```

`metricflow_semantic_interfaces/parsing/schemas.py`, `measure_schema`. One key states a
non-additive axis (`non_additive_dimension`); none states that a column is **already an
aggregate**, which is the fact a refusal of the naive model would have to read. That is what
the value names: not that the search was unlucky, but that the vocabulary has no slot.
