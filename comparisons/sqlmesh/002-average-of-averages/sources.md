# Sources

The cell is filled from the run recorded in `observed.txt`, not from documentation. What is
cited here is the **feature set** the configuration uses, so a reader can check that the
configuration is idiomatic rather than a strawman.

## Primary — the installed package

Version-pinned and checkable offline, which is what makes it the primary citation:

| What | Where, in the `sqlmesh` distribution |
|---|---|
| the shape every `METRIC (...)` block is validated against | `sqlmesh/core/metric/definition.py`, `MetricMeta` — a frozen model whose keys are `name`, `dialect`, `expression`, `description`, `owner` |
| the derived metric `average_item_price_decomposed` uses, and the rule that its operands are other metrics | `sqlmesh/core/metric/definition.py`, `MetricMeta.to_metric` — a bare column in an expression is resolved as a metric reference |
| what turns `SELECT METRIC(x) FROM __semantic.__table` into SQL, including the aggregates and joins | `sqlmesh/core/metric/rewriter.py`, `Rewriter.rewrite` |
| the keys a `MODEL (...)` block accepts, including `grain` and `references` | `sqlmesh/core/model/meta.py`, `ModelMeta` |
| the commands a SQLMesh user has | `sqlmesh/cli/main.py` — `info`, `plan`, `run`, `audit`, `rewrite`, `fetchdf`, `render`, `lint` and the rest |

```
python -c "import importlib.metadata as m; print(m.version('sqlmesh'))"   # 0.236.1
python -c "import importlib.metadata as m; print(m.version('duckdb'))"    # 1.5.5
```

## Secondary — the published documentation

Tobiko publishes this surface at `sqlmesh.readthedocs.io` (models, metrics, the semantic
layer's `__semantic.__table`). **These pages were not fetched while this bundle was
produced**, and no cell rests on them: they are named so a reader knows which documented
surface is being exercised, and the primary citations above are what the claim is checked
against.

## Why `NOT-REPRESENTED` rather than "not found"

`MetricMeta` is a Pydantic model that forbids extra keys, and `observed.txt`'s last line is
SQLMesh refusing an invented sixth one:

```text
name  dialect  expression  description  owner
```

`expression` carries SQL and `dialect` says which SQL; none of the five states a property of
the measure — that a column is **already an aggregate**, that it may not be summed across an
axis, that a rate has a denominator. That is what the value names: not that the search was
unlucky, but that the vocabulary has no slot.

## Why `NATIVE-PLAN` rather than `CUSTOM` for the decomposed cell

`sqlmesh rewrite` renders the decomposed metric itself: the `COUNT` and `SUM` are built into
a subquery over `silver.order_items` and divided in the outer select, with no SQL from this
project beyond the two column aggregates the metrics name.

The line this bundle draws — and the one the other SQLMesh bundles draw with it — is between
**a bare aggregate of a model column, composed by SQLMesh's derived metrics**, which is
SQLMesh's documented way to declare a measure and is counted native, and **a predicate or
conversion written inside an expression or a model**, which is SQL this project's author
wrote and which SQLMesh carries through without knowing what it means. The second is `CUSTOM`
wherever a cell rests on it.
