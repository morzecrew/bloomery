# Sources

The cell is filled from the run recorded in `observed.txt`, not from documentation. What is
cited here is the **feature set** the configuration uses, so a reader can check that the
configuration is idiomatic rather than a strawman.

## Primary — the installed package

Version-pinned and checkable offline, which is what makes it the primary citation:

| What | Where, in the `dbt-core` distribution |
|---|---|
| the shape every block in `config/models/semantic_models.yml` is validated against | `dbt/contracts/graph/unparsed.py`, `UnparsedSemanticModel` and `UnparsedMeasure` |
| `non_additive_dimension` on a measure, which `config/` declares | `dbt/contracts/graph/unparsed.py`, `UnparsedNonAdditiveDimension` — `name`, `window_choice`, `window_groupings` |
| the semantic validation dbt runs while parsing | `dbt/contracts/graph/semantic_manifest.py`, `SemanticManifest.validate` |
| the commands a dbt Core user has | `dbt/cli/main.py` — `build`, `compile`, `list`, `parse`, `run`, `show`, `test` and the rest |

```
python -c "import importlib.metadata as m; print(m.version('dbt-core'))"     # 1.12.3
python -c "import importlib.metadata as m; print(m.version('dbt-duckdb'))"   # 1.11.0
```

## Secondary — the published documentation

dbt Labs publishes this surface under `docs.getdbt.com/docs/build/` (semantic models,
measures, metrics, the MetricFlow time spine). **These pages were not fetched while this
bundle was produced**, and no cell rests on them: they are named so a reader knows which
documented surface is being exercised, and the primary citations above are what the claim is
checked against.

## Why `NOT-REPRESENTED` for the naive row when the key exists

This case is not a missing key. `config/models/semantic_models.yml` declares both measures
over the same column in the same semantic model, and the only difference between them is one
optional block. dbt accepts both, so the naive measure states nothing that could be false —
which is the condition the value names: the required fact has no representation *that the
model is obliged to carry*, and a system that is never told cannot refuse.

## Why `CUSTOM` rather than `NATIVE-PLAN` for the declared row

`dbt compile --select metric:total_balance_semi_additive` renders nothing in this
configuration, so the `170.0000` in `observed.txt` is produced by a model in
`config/models/`, written by the project author. The semi-additive declaration is native and
dbt accepts it; what is project-authored is the SQL that answers with it. Whether another
configuration — `dbt-metricflow`, or the hosted Semantic Layer — renders that metric was not
run here and is not what this cell claims.
