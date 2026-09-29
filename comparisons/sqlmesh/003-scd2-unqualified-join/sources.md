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
| the join path a grouped request takes, found from those references | `sqlmesh/core/reference.py`, `ReferenceGraph.find_path` and `models_for_column` |
| the `ON` clause the rewriter builds: an equality between two reference expressions, and nothing else | `sqlmesh/core/metric/rewriter.py`, `Rewriter._add_joins` |
| the shape every `METRIC (...)` block is validated against | `sqlmesh/core/metric/definition.py`, `MetricMeta` — keys `name`, `dialect`, `expression`, `description`, `owner` |
| the type-2 kinds that were read and not run | `sqlmesh/core/model/kind.py`, `SCDType2ByTimeKind` and `SCDType2ByColumnKind` |

```
python -c "import importlib.metadata as m; print(m.version('sqlmesh'))"   # 0.236.2
python -c "import importlib.metadata as m; print(m.version('duckdb'))"    # 1.5.5
```

## Secondary — the published documentation

Tobiko publishes this surface at `sqlmesh.readthedocs.io` (models, model kinds, metrics).
**These pages were not fetched while this bundle was produced**, and no cell rests on them.
They are named so a reader knows which documented surface is being exercised; the primary
citations above are what the claim is checked against.

## Why `NOT-REPRESENTED` for the unanchored reading

The rewriter joins along references, and `Rewriter._add_joins` builds each join as one
equality. There is nowhere on the path for an interval predicate, and nothing in `MODEL`
says that a model's rows are versions. `observed.txt` shows both declarations this project
could make without one. The business key joins every version and returns `600.0000` across
the groups. The composite grain renders a comparison with a tuple that DuckDB refuses. The
second is a rendering failure, not a check on history, and the cell does not count it as a
prevention.

## Why `CUSTOM` for the anchored reading

`silver.orders_as_of` is SQL this project's author wrote, and its `>= valid_from AND <
valid_to` predicate is what picks the version. The metric over it is a bare aggregate. What
makes the breakdown right is the predicate, and SQLMesh carries it through as an expression.
That is the line drawn in `002`'s `sources.md`.
