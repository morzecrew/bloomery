# Sources

The cell is filled from the run recorded in `observed.txt`, not from documentation. What is
cited here is the **feature set** the configuration uses, so a reader can check that the
configuration is idiomatic rather than a strawman.

## Primary — the installed package

Version-pinned and checkable offline, which is what makes it the primary citation:

| What | Where, in the `sqlmesh` distribution |
|---|---|
| the shape every `METRIC (...)` block is validated against | `sqlmesh/core/metric/definition.py`, `MetricMeta` — keys `name`, `dialect`, `expression`, `description`, `owner` |
| a `DISTINCT` inside an aggregate read as part of the measure | `sqlmesh/core/metric/definition.py`, `_get_measure_and_dim_tables` |
| the keys a `MODEL (...)` block accepts, which `config/models/` uses for `grain` and `references` | `sqlmesh/core/model/meta.py`, `ModelMeta` |
| the refusal an invented `MODEL` key gets, which is what makes the absence checkable | `sqlmesh/core/model/common.py`, the `Invalid field name present in the MODEL block` error |
| the grouping the by-day request gets, applied to the measure's own model | `sqlmesh/core/metric/rewriter.py`, `Rewriter._add_joins` |

```
python -c "import importlib.metadata as m; print(m.version('sqlmesh'))"   # 0.236.2
python -c "import importlib.metadata as m; print(m.version('duckdb'))"    # 1.5.5
```

## Secondary — the published documentation

Tobiko publishes this surface at `sqlmesh.readthedocs.io` (models, metrics). **These pages
were not fetched while this bundle was produced**, and no cell rests on them. They are named
so a reader knows which documented surface is being exercised; the primary citations above
are what the claim is checked against.

## Why `NOT-REPRESENTED` for the naive reading

`silver.daily_users` is a model like any other. Its `daily_users` column is an integer, and
the only thing `MODEL` states about it is its type. The probe in `observed.txt` shows an
invented additivity key is refused, and `MetricMeta`'s five keys carry an expression rather
than a rule about how its result may be combined.

## Why `NATIVE-PLAN` for the declared reading

`observed.txt` shows the rewriter placing `COUNT(DISTINCT silver__sessions.user_id)` over the
sessions model, ungrouped and grouped by day. The metric is a bare aggregate of a model
column, which is the line drawn in `002`'s `sources.md`.
