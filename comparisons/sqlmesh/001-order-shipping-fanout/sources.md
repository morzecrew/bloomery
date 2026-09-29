# Sources

The cell is filled from the run recorded in `observed.txt`, not from documentation. What is
cited here is the **feature set** the configuration uses, so a reader can check that the
configuration is idiomatic rather than a strawman.

## Primary — the installed package

Version-pinned and checkable offline, which is what makes it the primary citation:

| What | Where, in the `sqlmesh` distribution |
|---|---|
| the shape every `METRIC (...)` block is validated against | `sqlmesh/core/metric/definition.py`, `MetricMeta` — keys `name`, `dialect`, `expression`, `description`, `owner` |
| the keys a `MODEL (...)` block accepts, which `config/models/` uses for `grain` and `references` | `sqlmesh/core/model/meta.py`, `ModelMeta` |
| a model's grain counted as a unique reference beside its declared ones | `sqlmesh/core/model/meta.py`, `ModelMeta.all_references` |
| the join path the grouped request takes, built from those references | `sqlmesh/core/reference.py`, `ReferenceGraph.find_path` and `models_for_column` |
| the `ON` clause built from consecutive references on that path, and the grouping | `sqlmesh/core/metric/rewriter.py`, `Rewriter._add_joins` |
| what turns `SELECT METRIC(x) FROM __semantic.__table` into SQL | `sqlmesh/core/metric/rewriter.py`, `Rewriter.rewrite` |

```
python -c "import importlib.metadata as m; print(m.version('sqlmesh'))"   # 0.236.2
python -c "import importlib.metadata as m; print(m.version('duckdb'))"    # 1.5.5
```

## Secondary — the published documentation

Tobiko publishes this surface at `sqlmesh.readthedocs.io` (models, metrics, the semantic
layer's `__semantic.__table`). **These pages were not fetched while this bundle was
produced**, and no cell rests on them. They are named so a reader knows which documented
surface is being exercised; the primary citations above are what the claim is checked
against.

## Why `NATIVE-PLAN` for the rollup reading

`observed.txt` records the rewriter placing `SUM(silver__orders.shipping)` in a subquery over
`silver.orders` alone. The metric names a bare aggregate of a model column, which is the line
drawn in `002`'s `sources.md` for native.

## Why `NOT-REPRESENTED` for the representation reading

`grain` states which columns identify a row. It does not state where each of the other
columns originates. `silver.order_lines` is truthful about its grain, and its `shipping`
column is a copy per line. No key was found that would let the metric over it be told apart
from the one over `silver.orders`, and the two load, plan and audit identically.

## Why the refinement reading is not a prevention

The grouped request fails in DuckDB's binder on SQL the rewriter rendered. `Rewriter._add_joins`
pairs consecutive references on the path. Here the second is `silver.order_items`'s composite
grain, so the comparison is between one column and a tuple. The same rendering appears in
`003`'s bundle for a type-2 history keyed on `(customer_id, valid_from)`. It is a property of
how this version renders a join to a composite grain, and nothing about it depends on
shipping.
