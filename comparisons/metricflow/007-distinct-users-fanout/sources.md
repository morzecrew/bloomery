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

## Why the summed per-day counts are not refused

A measure's YAML schema is **closed** — `additionalProperties: False` — so its key set is
exhaustive rather than a list of the keys somebody happened to look for:

```
name  agg  agg_time_dimension  expr  agg_params  create_metric
create_metric_display_name  non_additive_dimension  description  label  config
```

`metricflow_semantic_interfaces/parsing/schemas.py`, `measure_schema`. One key states a non-additive axis
(`non_additive_dimension`), which this bundle does not declare, because the case's column
is not a snapshot; none states that a column is already a distinct count, or claims that a
measure is additive. The claim the corpus's `naive` spec makes has no key to be made in,
and the fact that would refuse the summed view has no key either.
