# Sources

The cell is filled from the run recorded in `observed.txt`, not from documentation. What is
cited here is the **feature set** the configuration uses, so a reader can check that the
configuration is idiomatic rather than a strawman.

## Primary — the installed package

Version-pinned and checkable offline, which is what makes it the primary citation:

| What | Where, in the `sqlmesh` distribution |
|---|---|
| the shape every `METRIC (...)` block is validated against | `sqlmesh/core/metric/definition.py`, `MetricMeta` — keys `name`, `dialect`, `expression`, `description`, `owner` |
| the model a metric reads, taken from the column its aggregate names | `sqlmesh/core/metric/definition.py`, `_get_measure_and_dim_tables` |
| the keys a `MODEL (...)` block accepts, which `config/models/` uses for `grain` and `references` | `sqlmesh/core/model/meta.py`, `ModelMeta` |
| the refusal an invented `MODEL` key gets, which is what makes the absence checkable | `sqlmesh/core/model/common.py`, the `Invalid field name present in the MODEL block` error |
| what turns a multi-metric `SELECT METRIC(x), METRIC(y) FROM __semantic.__table` into SQL | `sqlmesh/core/metric/rewriter.py`, `Rewriter.rewrite` |

```
python -c "import importlib.metadata as m; print(m.version('sqlmesh'))"   # 0.236.2
python -c "import importlib.metadata as m; print(m.version('duckdb'))"    # 1.5.5
```

## Secondary — the published documentation

Tobiko publishes this surface at `sqlmesh.readthedocs.io` (models, metrics). **These pages
were not fetched while this bundle was produced**, and no cell rests on them. They are named
so a reader knows which documented surface is being exercised; the primary citations above
are what the claim is checked against.

## Why `NOT-REPRESENTED` for the rolled reading

The rollup is a model this project's author wrote, and its two columns differ in meaning and
not in anything `MODEL` records. The probe in `observed.txt` shows an invented additivity key
is refused. So `SUM(daily_buyers)` is a legal aggregate that SQLMesh has no fact to object to.

## Why `NATIVE-PLAN` for the detail reading

`observed.txt` shows the rewriter placing `COUNT(DISTINCT silver__orders.customer_id)` and
`SUM(silver__orders.amount)` in one subquery over the orders. Both are bare aggregates of
model columns, which is the line drawn in `002`'s `sources.md`.
