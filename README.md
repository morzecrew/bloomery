<div align="center">

<img src="https://raw.githubusercontent.com/morzecrew/bloomery/main/pages/docs/assets/logo.png" alt="" width="96" height="96">

# bloomery

**Entity-first spec compiler — declarative specs in, SQLMesh, dbt and Cube artifacts out,
byte-for-byte the same every time.**

[![PyPI](https://img.shields.io/pypi/v/bloomery?logo=pypi&logoColor=white)](https://pypi.org/project/bloomery/)
[![Python](https://img.shields.io/pypi/pyversions/bloomery?logo=python&logoColor=white)](https://pypi.org/project/bloomery/)
[![Coverage](https://codecov.io/gh/morzecrew/bloomery/branch/main/graph/badge.svg)](https://codecov.io/gh/morzecrew/bloomery)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/morzecrew/bloomery/badge)](https://scorecard.dev/viewer/?uri=github.com/morzecrew/bloomery)
[![Licence](https://img.shields.io/pypi/l/bloomery)](LICENSE)

</div>

**bloomery** is a pure function library. You hand it declarative specs — a catalog,
entities, mappings, metrics, marts, and optionally steps — and it returns SQLMesh, dbt and
Cube artifacts, a MetricFlow manifest, and SQL for a metric request. It executes nothing
and reads no warehouse.

Those specs carry what SQL cannot: **grains, units, tax bases and additivity classes**.
That is the whole trick — the compiler refuses what a hand-written model would happily
run, because it knows what the columns *mean* and not just what type they are.

## The number that looks right

Shipping is charged once per order. Someone flattens it into a mart at line grain, and
`SUM(shipping)` overstates by the number of lines on each order. The SQL is valid, the
join is correct, the tests pass, the dashboard renders — and finance finds it two quarters
later. That class of bug survives syntax checks, type checks and code review, because
nothing in the stack knows that *shipping is an order-grain measure*. bloomery does:

```text
GuardrailError:
  1 error(s):
  - marts: marts.order_items.measures.shipping: measure 'shipping' has grain 'order'
    (one row per order), not the mart's grain 'order_item' (one row per line on an
    order) — measure grain must strictly equal mart grain (RFC 0010 D2). Flattened
    into the mart it is duplicated once per 'order_item' row and any SUM over it
    overstates. Fix: remove it from this mart's measures, or serve it from a mart at
    grain 'order'
```

Not a warning. A compile error, with the spec path that caused it and the two ways out.
The system may fail to answer a question; it may not answer it wrongly without saying so.

## Quick start

```bash
uv add bloomery      # or: pip install bloomery
```

Python 3.12–3.14. No orchestrator, no cloud SDK, no database driver.

```python
from bloomery import (
    LruManifestHydrator, MetricFlowPlanner, MetricRequest, Target,
    build_project_ir, compile_project, load_catalog, load_project,
)
from bloomery.naming import DefaultNaming

# The loaders take YAML *strings*, never paths: reading files is the caller's job.
catalog = load_catalog(catalog_yaml)
project = load_project({"entity_model.yaml": entities, "mapping_orders.yaml": mapping,
                        "metrics.yaml": metrics, "marts.yaml": marts})

# Compile: specs in, a tuple of file-shaped artifacts out. Writing them is yours too.
for artifact in compile_project(project, target=Target.SQLMESH, dialect="duckdb",
                                catalog=catalog):
    print(artifact.path)          # artifact.content is the model, audit or manifest

# The same specs serve queries. A request becomes SQL over a wide, pre-joined mart,
# planned by an embedded render-only MetricFlow and executed by nothing.
naming = DefaultNaming()
planner = MetricFlowPlanner(LruManifestHydrator(naming), naming=naming)
plan = planner.plan(build_project_ir(project, catalog=catalog),
                    MetricRequest(metrics=("revenue",), dimensions=("ordered_month",)),
                    dialect="duckdb")
print(plan.sql, plan.explanation.render())
```

That is [`examples/quickstart/run.py`](examples/quickstart/) condensed — the full file,
comments and filter parsing included, is run by the test suite on every commit
([`tests/unit/test_examples.py`](tests/unit/test_examples.py)), so it cannot quietly rot.

The CLI is a thin argument shell over exactly these functions, and the only part of the
package that touches a filesystem:

```bash
bloomery compile specs/ --target sqlmesh --dialect duckdb --out out/
bloomery resolve specs/          # what is computable, what is missing, what was refused
bloomery lineage specs/ --node metric.gross_revenue
```

A refusal exits `1` and a bad invocation exits `2`, so a pipeline can tell "your spec is
wrong" from "your command is wrong". Nothing is executed: `bloomery run` does not exist.

## What bloomery does not do

- **It does not execute SQL.** It emits artifacts and plans; SQLMesh, dbt or Cube run them.
- **It does no orchestration.** Scheduling, backfills and deployment belong downstream.
- **It does not read your warehouse.** Catalogs and profiles are inputs, computed elsewhere.
- **It contains no LLM.** Proposals may be drafted with LLM assistance upstream, but they
  arrive as validated specs, and everything emitted — the human-readable query
  explanations included — is generated deterministically.
- **It has no clock and no randomness.** Same specs in, byte-identical artifacts out,
  across machines, processes and `PYTHONHASHSEED` — enforced by test, not by intent.

## Examples

Every project under [`examples/`](examples/) runs, and a test covers each — the two pure
ones end to end, the two container-backed ones at their compile step — so none can rot
unnoticed. The seed data is deliberately not clean: padded emails, five spellings of one
segment vocabulary, prices in integer cents, an unparseable timestamp.

| Example | Shows | Infrastructure |
|---|---|---|
| [`quickstart/`](examples/quickstart/) | The five core spec kinds; compile, then plan a metric request | none |
| [`refusals/`](examples/refusals/) | Five specs that look right and cannot be right, with the real messages | none |
| [`targets/`](examples/targets/) | SQLMesh, dbt, Cube and the planner all actually running | one container |
| [`lakehouse/`](examples/lakehouse/) | Iceberg via Lakekeeper: union merge, quality rules, quarantine, a blocking audit | four containers |

```bash
uv run python examples/quickstart/run.py     # no setup at all
cd examples/targets && just demo             # the interesting one
```

`targets/` is worth the container. It compiles **one** spec set to SQLMesh and to dbt,
builds both, and compares the two marts row for row — because "two frameworks, one spec,
one answer" is a claim, and this turns it into a measurement.

## Documentation

Full documentation: [morzecrew.github.io/bloomery](https://morzecrew.github.io/bloomery/).

## Stability

bloomery is 0.x, so a minor release may break the Python API — never *quietly*: every
breaking change lands in [CHANGELOG.md](CHANGELOG.md) naming what moved and what to write
instead. Pin the minor (`bloomery>=0.2,<0.3`).

Spec YAML is the stronger promise and does not wait for 1.0: a document that loads keeps
loading, and a breaking grammar change mints a new `<kind>_version`. Emitted artifacts are
explicitly **not** stable across versions —
[details](https://morzecrew.github.io/bloomery/reference/stability/).

## Contributing

Contributions, issues and feature requests are welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md), including the RFC process for larger changes.

## Security

Please report security vulnerabilities privately as described in
[SECURITY.md](SECURITY.md).

## Licence

MIT — see [LICENSE](LICENSE).
