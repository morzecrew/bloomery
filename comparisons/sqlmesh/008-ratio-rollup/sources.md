# Sources

The cell is filled from the run recorded in `observed.txt`, not from documentation. What is
cited here is the **feature set** the configuration uses, so a reader can check that the
configuration is idiomatic rather than a strawman.

## Primary — the installed package

Version-pinned and checkable offline, which is what makes it the primary citation:

| What | Where, in the `sqlmesh` distribution |
|---|---|
| the shape every `METRIC (...)` block is validated against | `sqlmesh/core/metric/definition.py`, `MetricMeta` — keys `name`, `dialect`, `expression`, `description`, `owner` |
| the derived metric `revenue_per_item_declared` uses: a bare column in an expression is resolved as a reference to another metric | `sqlmesh/core/metric/definition.py`, `MetricMeta.to_metric` |
| the re-aggregation the declared cell rests on — operands collected into one subquery and divided outside it | `sqlmesh/core/metric/rewriter.py`, `Rewriter._expand` and `Rewriter._build_sources` |
| the keys a `MODEL (...)` block accepts, which `config/models/` uses for `grain` and `references` | `sqlmesh/core/model/meta.py`, `ModelMeta` |

```
python -c "import importlib.metadata as m; print(m.version('sqlmesh'))"   # 0.236.1
python -c "import importlib.metadata as m; print(m.version('duckdb'))"    # 1.5.5
```

## Secondary — the published documentation

Tobiko publishes this surface at `sqlmesh.readthedocs.io` (models, metrics, derived metrics).
**These pages were not fetched while this bundle was produced**, and no cell rests on them:
they are named so a reader knows which documented surface is being exercised, and the primary
citations above are what the claim is checked against.

## Why `NOT-REPRESENTED` rather than "not found"

`MetricMeta` forbids extra keys and `observed.txt`'s last line is the refusal of an invented
one. The five keys carry a name, a SQL expression, the dialect that expression is in, a
description and an owner; none of them says that the column an expression averages is itself
a rate. The naive metric is therefore not a mistake this vocabulary could describe.

## Why `NATIVE-PLAN` rather than `CUSTOM` for the declared cell

The rendered SQL in `observed.txt` is SQLMesh's. `revenue_total` and `item_total` are bare
aggregates of model columns; the division is the derived metric's formula, and the subquery
that puts the two sums at the same grain was built by the rewriter, not by this project. That
is the line drawn in `002`'s `sources.md`: a bare aggregate composed by SQLMesh's derived
metrics is native; a predicate or conversion written by the author is `CUSTOM`.

## A limit of this version, found while writing the bundle

A metric whose expression is itself a compound of aggregates — `SUM(a) / SUM(b)` in one
`METRIC` block rather than two — renders SQL that DuckDB refuses, because the inner select
projects the expression without an alias and the outer one selects it by name. The working
form is the derived one used here and in `009`, which is also the documented one; the failure
is recorded in `009`'s bundle rather than asserted from memory.
