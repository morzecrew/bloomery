# Sources

The cell is filled from the run recorded in `observed.txt`, not from documentation. What is
cited here is the **feature set** the configuration uses, so a reader can check that the
configuration is idiomatic rather than a strawman.

## Primary — the installed package

Version-pinned and checkable offline, which is what makes it the primary citation:

| What | Where, in the `sqlmesh` distribution |
|---|---|
| the shape every `METRIC (...)` block is validated against | `sqlmesh/core/metric/definition.py`, `MetricMeta` — keys `name`, `dialect`, `expression`, `description`, `owner` |
| the model a metric's aggregate is over, read from the column it names | `sqlmesh/core/metric/definition.py`, `Metric.aggs` and `_get_measure_and_dim_tables` |
| one subquery per measure model, aggregated and then joined on the grouping keys | `sqlmesh/core/metric/rewriter.py`, `Rewriter._build_sources` and `Rewriter._expand` |
| the join type used between those subqueries, `FULL` by default | `sqlmesh/core/metric/rewriter.py`, `Rewriter.__init__` |
| the keys a `MODEL (...)` block accepts, which `config/models/` uses for `grain` and `references` | `sqlmesh/core/model/meta.py`, `ModelMeta` |

```
python -c "import importlib.metadata as m; print(m.version('sqlmesh'))"   # 0.236.2
python -c "import importlib.metadata as m; print(m.version('duckdb'))"    # 1.5.5
```

## Secondary — the published documentation

Tobiko publishes this surface at `sqlmesh.readthedocs.io` (metrics, the semantic layer's
`__semantic.__table`). **These pages were not fetched while this bundle was produced**, and
no cell rests on them. They are named so a reader knows which documented surface is being
exercised; the primary citations above are what the claim is checked against.

## Why `NATIVE-PLAN`

The rendered SQL in `observed.txt` is SQLMesh's. The metrics are bare aggregates of model
columns, and the aggregate-then-join shape was built by the rewriter, not by this project.
That is the line drawn in `002`'s `sources.md`.
