# Sources

The cell is filled from the run recorded in `observed.txt`, not from documentation. What is
cited here is the **feature set** the configuration uses, so a reader can check that the
configuration is idiomatic rather than a strawman.

## Primary — the installed package

Version-pinned and checkable offline, which is what makes it the primary citation:

| What | Where, in the `dbt-core` distribution |
|---|---|
| the shape every block in `config/models/semantic_models.yml` is validated against | `dbt/contracts/graph/unparsed.py`, `UnparsedSemanticModel` and `UnparsedMeasure` |
| the `ratio` metric type, which `config/` declares | `dbt/artifacts/resources/v1/metric.py`, `Metric.type` — a `MetricType` imported from `metricflow_semantic_interfaces.type_enums`, so at this version dbt Core's semantic vocabulary *is* that package's |
| the input a `ratio` metric's numerator and denominator accept, including `filter` | `dbt/contracts/graph/unparsed.py`, `UnparsedMetricInput` |
| the semantic validation dbt runs while parsing | `dbt/contracts/graph/semantic_manifest.py`, `SemanticManifest.validate` |
| the commands a dbt Core user has | `dbt/cli/main.py` — `build`, `compile`, `list`, `parse`, `run`, `show`, `test` and the rest |

```
python -c "import importlib.metadata as m; print(m.version('dbt-core'))"     # 1.12.3
python -c "import importlib.metadata as m; print(m.version('dbt-duckdb'))"   # 1.11.0
```

## Secondary — the published documentation

dbt Labs publishes this surface under `docs.getdbt.com/docs/build/` (semantic models,
measures, metrics, metric filters). **These pages were not fetched while this bundle was
produced**, and no cell rests on them: they are named so a reader knows which documented
surface is being exercised, and the primary citations above are what the claim is checked
against.

## Why `NOT-REPRESENTED` for the `declared` row

The fact a refusal would have to read is *this quotient is over the rows that moved a
parcel*, attached to the ratio itself. What this vocabulary offers instead is a `filter` on
each input, written independently and optional on both — so the inclusive ratio and the
restricted one are both well-formed, and dbt has nothing to compare them against. The value
names the absence of a slot, not an unlucky search.

## A key that looks relevant, measured rather than reasoned about

`fill_nulls_with` reads as though it answered a null denominator. In the denominator position
of a `ratio` metric, dbt Core `1.12.3` refuses it outright — `observed.txt`'s last line — so
this bundle makes no claim about what it would have changed. MetricFlow `0.212.0` accepted
the same key in the same position and returned `4.0` either way; the two are different
packages at different versions, and the difference is recorded rather than smoothed over.

## Why `CUSTOM` rather than `NATIVE-PLAN` for the answered rows

`dbt compile --select metric:cost_per_parcel_restricted` renders nothing in this
configuration, so the `3.0` and `4.0` in `observed.txt` are produced by models in
`config/models/`, written by the project author. The metrics are declared natively and dbt
accepts them; what is project-authored is the SQL that answers with them. Whether another
configuration — `dbt-metricflow`, or the hosted Semantic Layer — renders those metrics was
not run here and is not what these cells claim.
