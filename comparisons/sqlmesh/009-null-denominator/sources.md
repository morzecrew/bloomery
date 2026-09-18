# Sources

The cell is filled from the run recorded in `observed.txt`, not from documentation. What is
cited here is the **feature set** the configuration uses, so a reader can check that the
configuration is idiomatic rather than a strawman.

## Primary — the installed package

Version-pinned and checkable offline, which is what makes it the primary citation:

| What | Where, in the `sqlmesh` distribution |
|---|---|
| the shape every `METRIC (...)` block is validated against | `sqlmesh/core/metric/definition.py`, `MetricMeta` — keys `name`, `dialect`, `expression`, `description`, `owner` |
| the derived metrics both ratios use, and the resolution of a bare column into a metric reference | `sqlmesh/core/metric/definition.py`, `MetricMeta.to_metric` |
| the rendering the compound metric runs into: operands are aliased into the subquery, a bare expression is not | `sqlmesh/core/metric/rewriter.py`, `Rewriter._expand` |
| the `accepted_range` audit this bundle declares, with its `min_v` and `blocking` arguments | `sqlmesh/core/audit/builtin.py`, `accepted_range` |
| the audits a model can declare without writing SQL, searched for one that states which rows a ratio is over | `sqlmesh/core/audit/builtin.py` — `not_null`, `unique_values`, `accepted_values`, `accepted_range`, `not_constant`, `not_null_proportion`, `mutually_exclusive_ranges` and the rest |

```
python -c "import importlib.metadata as m; print(m.version('sqlmesh'))"   # 0.236.1
python -c "import importlib.metadata as m; print(m.version('duckdb'))"    # 1.5.5
```

## Secondary — the published documentation

Tobiko publishes this surface at `sqlmesh.readthedocs.io` (models, metrics, audits).
**These pages were not fetched while this bundle was produced**, and no cell rests on them:
they are named so a reader knows which documented surface is being exercised, and the primary
citations above are what the claim is checked against.

## Why `NOT-REPRESENTED` rather than `RUNTIME-DETECT` for the declared cell

This is the one cell in the SQLMesh column where a native runtime check does fire, so the
reasoning is written out rather than left to the value's name.

`observed.txt` records `accepted_range` failing on `s3` during the plan and again under
`sqlmesh audit`. An audit is a predicate over the rows of one model, evaluated after it is
built. What makes the unqualified ratio wrong is not that `s3` exists — it is a real shipment
with a real charge — but that a request for cost per parcel did not say whether it is about
shipments that moved parcels. The audit cannot carry that distinction: it fires the same way
for a project that asks the restricted question, the inclusive one, both, or neither, and the
only way to satisfy it is to remove valid data.

`RUNTIME-DETECT` is for a native check that detects the bad result or the data condition
behind it. This one detects a row a correct project would keep, so the cell reports the
absence in the vocabulary instead, and the run that produced this reasoning is checked in
beside it.

## Why `NATIVE-PLAN` for the inclusive cell and `CUSTOM` for the restricted one

Both numbers come from the same rewriter. The difference is in the operands: the inclusive
ratio's are `SUM(carrier_cost)` and `SUM(parcels)`, bare aggregates of model columns, and the
restricted ratio's carry a `CASE WHEN silver.shipments.parcels > 0` this project's author
wrote. SQLMesh passes that predicate through without knowing that it is what makes the ratio
answer the question. That is the line drawn in `002`'s `sources.md`.
