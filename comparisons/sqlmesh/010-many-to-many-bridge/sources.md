# Sources

The cell is filled from the run recorded in `observed.txt`, not from documentation. What is
cited here is the **feature set** the configuration uses, so a reader can check that the
configuration is idiomatic rather than a strawman.

## Primary — the installed package

Version-pinned and checkable offline, which is what makes it the primary citation:

| What | Where, in the `sqlmesh` distribution |
|---|---|
| the keys a `MODEL (...)` block accepts, which `config/models/` uses for `grain` and `references` | `sqlmesh/core/model/meta.py`, `ModelMeta` |
| a model's grain counted as a unique reference beside its declared ones | `sqlmesh/core/model/meta.py`, `ModelMeta.all_references` |
| the path search the grouped request takes, including its rule against many-to-many steps | `sqlmesh/core/reference.py`, `ReferenceGraph.find_path` |
| the `ON` clause built from consecutive references on that path | `sqlmesh/core/metric/rewriter.py`, `Rewriter._add_joins` |
| the shape every `METRIC (...)` block is validated against | `sqlmesh/core/metric/definition.py`, `MetricMeta` — keys `name`, `dialect`, `expression`, `description`, `owner` |

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

## Why `NOT-REPRESENTED` for the bridged reading

`silver.promoted_orders` is a join this project's author wrote, and it has one row per bridge
row. The metric over it is a bare `SUM`, and no key records where the `revenue` column
originates. So the two revenue metrics are indistinguishable to the load, the plan and the
audit.

## Why the grouped request is recorded rather than scored

`observed.txt` records the join SQLMesh rendered: `order_id = promo_id`. `find_path`
extends a path with any reference of the next model, and `_add_joins` pairs consecutive
references on it. So the reference that leads to `silver.promos` is also the one compared
with `silver.orders`' key. The request neither refuses nor fans out. It is a property of how
this version walks this bridge, and it is recorded so the cell does not have to guess at it.
