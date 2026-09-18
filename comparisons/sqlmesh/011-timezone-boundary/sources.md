# Sources

The cell is filled from the run recorded in `observed.txt`, not from documentation. What is
cited here is the **feature set** the configuration uses, so a reader can check that the
configuration is idiomatic rather than a strawman.

## Primary — the installed package

Version-pinned and checkable offline, which is what makes it the primary citation:

| What | Where, in the `sqlmesh` distribution |
|---|---|
| the keys a `MODEL (...)` block accepts, which `config/models/` uses for `grain` and `references` | `sqlmesh/core/model/meta.py`, `ModelMeta` |
| the refusal an invented `MODEL` key gets, which is what makes the absence checkable | `sqlmesh/core/model/common.py`, the `Invalid field name present in the MODEL block` error |
| the only zone-bearing key in the model vocabulary, and what it is about | `sqlmesh/core/model/meta.py`, `ModelMeta.cron_tz` — the zone a model's cron schedule is read in |
| the time column an incremental kind carries, which has a `column` and a `format` and no zone | `sqlmesh/core/model/kind.py`, `TimeColumn` and `IncrementalByTimeRangeKind` |
| the shape every `METRIC (...)` block is validated against | `sqlmesh/core/metric/definition.py`, `MetricMeta` — keys `name`, `dialect`, `expression`, `description`, `owner` |
| what turns `SELECT METRIC(x) FROM __semantic.__table` into SQL | `sqlmesh/core/metric/rewriter.py`, `Rewriter.rewrite` |

```
python -c "import importlib.metadata as m; print(m.version('sqlmesh'))"   # 0.236.1
python -c "import importlib.metadata as m; print(m.version('duckdb'))"    # 1.5.5
```

## Secondary — the published documentation

Tobiko publishes this surface at `sqlmesh.readthedocs.io` (models, model kinds, metrics).
**These pages were not fetched while this bundle was produced**, and no cell rests on them:
they are named so a reader knows which documented surface is being exercised, and the primary
citations above are what the claim is checked against.

## Why `NOT-REPRESENTED` rather than "not found"

Two things were searched rather than assumed. The `MODEL` key set is closed, and
`observed.txt`'s last line is SQLMesh refusing `time_zone` on it. And the two keys that look
as though they might carry a zone were read: `cron_tz` is about when a model runs, and
`TimeColumn` pairs a column with a format string. A key that looks relevant is not a cell
until it has been read or run.

So the zone the source system writes its wall clocks in is documentation — true of the store,
absent from the project — and the zoneless metric is a legal comparison between well-typed
values that happens to be five hours from the question.

## Why `CUSTOM` rather than `NATIVE-PLAN` for the anchored cell

The `140.00` rests on `placed_at AT TIME ZONE 'America/New_York'`, a dialect-specific string
in a model this project's author wrote. SQLMesh parses it with sqlglot, renders it for DuckDB
and materialises the result — but nothing in the project says that `placed_at_utc` denotes an
instant and `placed_at` does not, and nothing would notice if the conversion named the wrong
zone. That is the line drawn in `002`'s `sources.md`: a bare aggregate composed by SQLMesh's
derived metrics is native; a conversion written by the author is `CUSTOM`.
