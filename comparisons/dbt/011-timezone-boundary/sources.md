# Sources

The cell is filled from the run recorded in `observed.txt`, not from documentation. What is
cited here is the **feature set** the configuration uses, so a reader can check that the
configuration is idiomatic rather than a strawman.

## Primary — the installed package

Version-pinned and checkable offline, which is what makes it the primary citation:

| What | Where, in the `dbt-core` distribution |
|---|---|
| the shape every block in `config/models/semantic_models.yml` is validated against | `dbt/contracts/graph/unparsed.py`, `UnparsedSemanticModel` and `UnparsedMeasure` |
| what a time dimension may declare, which is where a zone would go | `dbt/contracts/graph/unparsed.py`, `UnparsedDimensionTypeParams` — `time_granularity`, `validity_params` |
| the `filter` a metric's input measure accepts, which `config/` declares | `dbt/contracts/graph/unparsed.py`, `UnparsedMetricInputMeasure` |
| the semantic validation dbt runs while parsing | `dbt/contracts/graph/semantic_manifest.py`, `SemanticManifest.validate` |
| the commands a dbt Core user has | `dbt/cli/main.py` — `build`, `compile`, `list`, `parse`, `run`, `show`, `test` and the rest |

```
python -c "import importlib.metadata as m; print(m.version('dbt-core'))"     # 1.12.3
python -c "import importlib.metadata as m; print(m.version('dbt-duckdb'))"   # 1.11.0
```

## Secondary — the published documentation

dbt Labs publishes this surface under `docs.getdbt.com/docs/build/` (semantic models,
dimensions, metrics, metric filters). **These pages were not fetched while this bundle was
produced**, and no cell rests on them: they are named so a reader knows which documented
surface is being exercised, and the primary citations above are what the claim is checked
against.

## Why `NOT-REPRESENTED` rather than "not found"

A time dimension's `type_params` is a closed shape, and `observed.txt`'s last line is dbt
refusing the key this case would need:

```text
time_granularity  validity_params
```

Neither states which zone a stored wall clock was written in. The only place the fact can go
is the dimension's `expr`, as SQL — where it is a string dbt forwards to the warehouse rather
than a declaration dbt reads, which is why the anchored row is `CUSTOM` rather than native.

## Why `CUSTOM` also for the reason the other bundles give

`dbt compile --select metric:february_revenue_anchored` renders nothing in this
configuration, so the `140.00` in `observed.txt` is produced by a model in `config/models/`,
written by the project author. Whether another configuration — `dbt-metricflow`, or the
hosted Semantic Layer — renders that metric was not run here and is not what this cell
claims.
