# Sources

The cell is filled from the run recorded in `observed.txt`, not from documentation. What is
cited here is the **feature set** the configuration uses, so a reader can check that the
configuration is idiomatic rather than a strawman.

## Primary — the installed package

Version-pinned and checkable offline, which is what makes it the primary citation:

| What | Where, in the installed distributions |
|---|---|
| the shape every block in `config/models/semantic_models.yml` is validated against | `dbt/contracts/graph/unparsed.py`, `UnparsedSemanticModel` and `UnparsedMeasure` |
| the free-form `meta` a measure's `config` accepts | `dbt/artifacts/resources/v1/semantic_model.py`, `SemanticLayerElementConfig.meta` — a `Dict[str, Any]` |
| the semantic validation dbt runs while parsing | `dbt/contracts/graph/semantic_manifest.py`, `SemanticManifest.validate` |
| the commands a dbt Core user has | `dbt/cli/main.py` — `build`, `compile`, `list`, `parse`, `run`, `show`, `test` and the rest |

```
python -c "import importlib.metadata as m; print(m.version('dbt-core'))"     # 1.12.5
python -c "import importlib.metadata as m; print(m.version('dbt-duckdb'))"   # 1.11.0
```

## Secondary — the published documentation

dbt Labs publishes this surface under `docs.getdbt.com/docs/build/` (semantic models,
measures, metrics) and `docs.getdbt.com/reference/resource-configs/meta`. **These pages were
not fetched while this bundle was produced**, and no cell rests on them.

## Why "no typed slot" rather than "not found"

`UnparsedMeasure` is a closed set of keys, and `observed.txt`'s last line is dbt refusing an
invented `currency` one:

```text
name  agg  description  label  expr  agg_params  non_additive_dimension
agg_time_dimension  create_metric  config
```

None states a unit. `config.meta` accepts any mapping, which is why the labels in
`config/models/semantic_models.yml` build; the run recorded no effect from them on the measure
that adds the two labelled columns.
