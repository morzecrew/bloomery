# Sources

The cell is filled from the run recorded in `observed.txt`, not from documentation. What is
cited here is the **feature set** the configuration uses, so a reader can check that the
configuration is idiomatic rather than a strawman.

## Primary — the installed package

Version-pinned and checkable offline, which is what makes it the primary citation:

| What | Where, in the `metricflow` distribution |
|---|---|
| the YAML schema every config in `config/` is validated against | `metricflow_semantic_interfaces/parsing/schemas.py` |
| `expr` and `type_params` on a time dimension, which `config/` declares | `metricflow_semantic_interfaces/parsing/schemas.py`, `dimension_schema` |
| `filter` on a metric's input measure, which `config/` declares | `metricflow_semantic_interfaces/parsing/schemas.py`, `metric_input_measure_schema` |
| the manifest validator, run in full | `metricflow_semantic_interfaces/validations/semantic_manifest_validator.py` |

```
python -c "import importlib.metadata as m; print(m.version('metricflow'))"   # 0.212.0
```

## Secondary — the published documentation

MetricFlow's user-facing documentation is published by dbt Labs under
`docs.getdbt.com/docs/build/` (semantic models, dimensions, metric filters, validation).
**These pages were not fetched while this bundle was produced**, and no cell rests on them:
they are named so a reader knows which documented surface is being exercised, and the
primary citations above are what the claim is checked against.

## Why `NOT-REPRESENTED` and `CUSTOM` rather than "not found"

A time dimension's `type_params` is **closed** — `additionalProperties: False` — so its key
set is exhaustive rather than a list of the keys somebody happened to look for:

```
time_granularity  validity_params
```

`metricflow_semantic_interfaces/parsing/schemas.py`, `dimension_type_params_schema`. The
dimension itself is closed too, over `name  description  type  is_partition  expr
type_params  label  config`. One key carries SQL (`expr`); none names the zone a wall clock
was written in.

The search is stated rather than implied, so it can be repeated:

```
rg -in "time_?zone" .venv/lib/python3.13/site-packages/metricflow_semantic_interfaces
```

returns nothing at `0.212.0`. The vocabulary that the manifest is parsed into has no slot for
a zone, which is what makes the zoneless dimension unrefusable and the anchored one
project-authored SQL rather than a declaration.

`join_to_timespine` is the key whose name reads as if it answered this case — it sits on a
metric's input measure beside `fill_nulls_with`, and its protocol docstring is *"If the
measure should be joined to the timespine"*
(`metricflow_semantic_interfaces/protocols/metric.py`). It governs which *periods* appear in
a result, joining against the project's declared time spine; it says nothing about which
instant a stored wall clock denotes, and the boundary this case turns on is five hours wide
inside a single day. `config/` does not declare it, because there are no missing periods here
to open.
