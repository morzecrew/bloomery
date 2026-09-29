# Sources

The cell is filled from the run recorded in `observed.txt`, not from documentation. What is
cited here is the **feature set** the configuration uses, so a reader can check that the
configuration is idiomatic rather than a strawman.

## Primary — the installed package

Version-pinned and checkable offline, which is what makes it the primary citation:

| What | Where, in the `sqlmesh` distribution |
|---|---|
| the shape every `METRIC (...)` block is validated against, and the refusal of the `unit` probe | `sqlmesh/core/metric/definition.py`, `MetricMeta` — keys `name`, `dialect`, `expression`, `description`, `owner` |
| the keys a `MODEL (...)` block accepts, which `config/models/` uses for `grain` | `sqlmesh/core/model/meta.py`, `ModelMeta` |
| the refusal an invented `MODEL` key gets, which is what makes the absence checkable | `sqlmesh/core/model/common.py`, the `Invalid field name present in the MODEL block` error |
| what turns `SELECT METRIC(x) FROM __semantic.__table` into SQL | `sqlmesh/core/metric/rewriter.py`, `Rewriter.rewrite` |

```
python -c "import importlib.metadata as m; print(m.version('sqlmesh'))"   # 0.236.2
python -c "import importlib.metadata as m; print(m.version('duckdb'))"    # 1.5.5
```

## Secondary — the published documentation

Tobiko publishes this surface at `sqlmesh.readthedocs.io` (models, metrics).
**These pages were not fetched while this bundle was produced**, and no cell rests on them.
They are named so a reader knows which documented surface is being exercised; the primary
citations above are what the claim is checked against.

## Why `NOT-REPRESENTED` for the mixed and mislabelled readings

Both key sets were probed rather than read, and `observed.txt` records both refusals. A
column's type is the only thing a model states about it, and `DECIMAL(12, 4)` is the same for
euros and for dollars. So the mixed sum is a legal sum of legal columns. The mislabelled
conversion is a legal join that happens to name the wrong pair.

## Why `CUSTOM` for the converted reading

`172.5000` rests on `silver.payments_usd`, whose join to the rate relation and whose
`amount_eur * rate` are SQL this project's author wrote. That is the line drawn in `002`'s
`sources.md`: a bare aggregate composed by SQLMesh's derived metrics is native, and a
conversion written by the author is not.
