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
| the refusal an invented `MODEL` key gets, which is what makes the absence checkable | `sqlmesh/core/model/common.py`, the `Invalid field name present in the MODEL block` error |
| what turns `SELECT METRIC(x) FROM __semantic.__table` into SQL | `sqlmesh/core/metric/rewriter.py`, `Rewriter.rewrite` |
| the audits a model can declare without writing SQL, searched for one that states an additivity rule | `sqlmesh/core/audit/builtin.py` — `not_null`, `unique_values`, `accepted_values`, `accepted_range`, `not_constant`, `unique_combination_of_columns`, `mutually_exclusive_ranges` and the rest |

```
python -c "import importlib.metadata as m; print(m.version('sqlmesh'))"   # 0.236.1
python -c "import importlib.metadata as m; print(m.version('duckdb'))"    # 1.5.5
```

## Secondary — the published documentation

Tobiko publishes this surface at `sqlmesh.readthedocs.io` (models, metrics, audits).
**These pages were not fetched while this bundle was produced**, and no cell rests on them:
they are named so a reader knows which documented surface is being exercised, and the primary
citations above are what the claim is checked against.

## Why `NOT-REPRESENTED` for the naive cell

Two closed key sets were probed rather than read, and `observed.txt` records both refusals —
this bundle's on the `MODEL` block, `002`'s on the `METRIC` block. Neither vocabulary has a
key that says a measure is non-additive across an axis, so the naive metric is not a mistake
SQLMesh could have caught: it is a legal aggregate of a legal column.

The built-in audits were searched for the same reason. They constrain **rows** — a value is
not null, is in a range, is unique across columns — and a snapshot whose balances repeat
daily violates none of them. An audit that fired here would be rejecting valid data rather
than an invalid claim.

## Why `CUSTOM` rather than `NATIVE-PLAN` for the declared cell

The `170.0000` comes from a model this project's author wrote, whose `WHERE` clause selects
the last day before anything is summed. SQLMesh plans and materialises that model, and the
metric over it is native; what is project-authored is the reduction that makes the metric
correct. The line this bundle draws is the one `002`'s `sources.md` states: a bare aggregate
composed by SQLMesh's derived metrics is native, a predicate written by the author is not.
