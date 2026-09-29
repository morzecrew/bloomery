# Sources

The cell is filled from the run recorded in `observed.txt`, not from documentation. What is
cited here is the **feature set** the configuration uses, so a reader can check that the
configuration is idiomatic rather than a strawman.

## Primary — the installed package

Version-pinned and checkable offline, which is what makes it the primary citation:

| What | Where, in the `metricflow` distribution |
|---|---|
| the YAML schema every config in `config/` is validated against | `metricflow_semantic_interfaces/parsing/schemas.py` |
| `expr` on a measure, which `config/` declares | `metricflow_semantic_interfaces/parsing/schemas.py`, `measure_schema` |
| the manifest validator, run in full | `metricflow_semantic_interfaces/validations/semantic_manifest_validator.py` |

```
python -c "import importlib.metadata as m; print(m.version('metricflow'))"   # 0.213.0
```

## Secondary — the published documentation

MetricFlow's user-facing documentation is published by dbt Labs under
`docs.getdbt.com/docs/build/` (semantic models, measures, validation).
**These pages were not fetched while this bundle was produced**, and no cell rests on them:
they are named so a reader knows which documented surface is being exercised, and the
primary citations above are what the claim is checked against.

## Why the unconverted sum is not refused

A measure's YAML schema is **closed** — `additionalProperties: False` — so its key set is
exhaustive rather than a list of the keys somebody happened to look for:

```
name  agg  agg_time_dimension  expr  agg_params  create_metric
create_metric_display_name  non_additive_dimension  description  label  config
```

`metricflow_semantic_interfaces/parsing/schemas.py`, `measure_schema`. None names a currency or a unit, and a
dimension's and a semantic model's schemas are closed too. The search is stated rather than
implied, so it can be repeated:

```
rg -il currency .venv/lib/python3.13/site-packages/metricflow_semantic_interfaces
```

returns nothing at `0.213.0`. The vocabulary the manifest is parsed into has no slot for a
denomination, which is what makes the mixed sum unrefusable and the conversion
project-authored SQL rather than a declaration.
