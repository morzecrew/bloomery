# Sources

The cell is filled from the run recorded in `observed.txt`, not from documentation. What is
cited here is the **feature set** the configuration uses, so a reader can check that the
configuration is idiomatic rather than a strawman.

## Primary — the installed package

Version-pinned and checkable offline, which is what makes it the primary citation:

| What | Where, in the `metricflow` distribution |
|---|---|
| the YAML schema every config in `config/` is validated against | `metricflow_semantic_interfaces/parsing/schemas.py` |
| the `ratio` metric type, which `config/` declares | `metricflow_semantic_interfaces/implementations/metric.py` |
| `filter` and `fill_nulls_with` on a metric's input measure, which `config/` declares | `metricflow_semantic_interfaces/parsing/schemas.py`, `metric_input_measure_schema` |
| what `fill_nulls_with` fills | `metricflow_semantic_interfaces/protocols/metric.py`, `fill_nulls_with` |
| the manifest validator, run in full | `metricflow_semantic_interfaces/validations/semantic_manifest_validator.py` |

```
python -c "import importlib.metadata as m; print(m.version('metricflow'))"   # 0.212.0
```

## Secondary — the published documentation

MetricFlow's user-facing documentation is published by dbt Labs under
`docs.getdbt.com/docs/build/` (semantic models, measures, metrics overview, metric filters,
validation). **These pages were not fetched while this bundle was produced**, and no cell
rests on them: they are named so a reader knows which documented surface is being exercised,
and the primary citations above are what the claim is checked against.

## Why `NOT-REPRESENTED` for the `declared` row

A metric input measure's YAML schema is **closed** — `additionalProperties: False` — so its
key set is exhaustive rather than a list of the keys somebody happened to look for:

```
name  filter  alias  join_to_timespine  fill_nulls_with
```

`metricflow_semantic_interfaces/parsing/schemas.py`, `metric_input_measure_schema`. One key
restricts the rows (`filter`), and the bundle uses it to reach `3.00`; none states that a
ratio's operands must be about the same rows, or that a row with a zero denominator is
outside the question. The restriction is therefore something an author may apply and nothing
an author is asked for — which is the fact a refusal of the unrestricted ratio would have to
read.

`fill_nulls_with` is the key whose name reads as if it answered this case. Its protocol
docstring is *"What null values should be filled with if set"*, and it sits beside
`join_to_timespine` — *"If the measure should be joined to the timespine"* —
(`metricflow_semantic_interfaces/protocols/metric.py`). It fills periods a time-spine join
opens, not rows a ratio should not be about. `config/` declares it on
`cost_per_parcel_filled` and `observed.txt` records the result: `4.0`, unchanged.
