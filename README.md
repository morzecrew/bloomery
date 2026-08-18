<div align="center">

# bloomery

**Entity-first spec compiler — declarative specs in, SQLMesh, dbt and Cube artifacts out,
byte-for-byte the same every time.**

[![PyPI](https://img.shields.io/pypi/v/bloomery?logo=pypi&logoColor=white)](https://pypi.org/project/bloomery/)
[![Python](https://img.shields.io/pypi/pyversions/bloomery?logo=python&logoColor=white)](https://pypi.org/project/bloomery/)
[![CI](https://github.com/morzecrew/bloomery/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/morzecrew/bloomery/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/morzecrew/bloomery/branch/main/graph/badge.svg)](https://codecov.io/gh/morzecrew/bloomery)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/morzecrew/bloomery/badge)](https://scorecard.dev/viewer/?uri=github.com/morzecrew/bloomery)
[![Docs](https://img.shields.io/badge/docs-morzecrew.github.io-blue)](https://morzecrew.github.io/bloomery/)
[![Licence](https://img.shields.io/pypi/l/bloomery)](LICENSE)
[![Typed](https://img.shields.io/badge/typing-strict-blue?logo=python&logoColor=white)](https://github.com/morzecrew/bloomery/blob/main/pyrightconfig.json)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

[Documentation](https://morzecrew.github.io/bloomery/) ·
[Quickstart](https://morzecrew.github.io/bloomery/get-started/quickstart/) ·
[Examples](examples/) ·
[Concepts](https://morzecrew.github.io/bloomery/concepts/specs-and-catalog/) ·
[Changelog](CHANGELOG.md)

</div>

---

## The number that looks right

In a config-driven data platform the worst failure is not a crash. It is a number that
looks right and is wrong.

Shipping is charged once per order. Someone flattens it into a mart at line grain, and
`SUM(shipping)` quietly overstates by the number of lines on each order. The SQL is
valid, the join is correct, the tests pass, the dashboard renders — and finance finds it
two quarters later. The formula was right, the data was right, the answer was 3× wrong.

That class of bug survives syntax checks, type checks and code review, because nothing in
the stack knows that *shipping is an order-grain measure*. bloomery does, and refuses:

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

## What it is

A **pure function library**. You hand it declarative specs — a catalog, entities,
mappings, metrics, marts, and optionally steps — and it returns artifacts:

```text
                            ┌─▶  SQLMesh    models, audits
   catalog.yaml             │
   entity_model.yaml        ├─▶  dbt        models, schema tests
   mapping_*.yaml   ──────▶ ┤
   metrics.yaml             ├─▶  Cube       semantic model
   marts.yaml               │
   steps.yaml               └─▶  MetricFlow semantic manifest

   MetricRequest    ──────▶      SQL over a wide mart + a written explanation
```

Those specs carry what SQL cannot: **grains, units, tax bases, and additivity classes**.
That is the whole trick — the compiler refuses what a hand-written model would happily
run, because it knows what the columns *mean*, not just what type they are.

Three properties it holds itself to, each enforced by test rather than intent:

| | |
|---|---|
| **Deterministic** | Same specs in, byte-identical artifacts out — across machines, processes, and `PYTHONHASHSEED`. No clocks, no randomness, no environment reads, no filesystem. |
| **Fail-closed** | Grain fan-out, additivity violations, mixed units, contract breaks: compile errors with a source path and a named reason, never a silent wrong number. |
| **Reviewable** | Emitted artifacts are stable-sorted, pretty-printed text, so a diff of the output is a faithful diff of the semantic change. |

## Install

```bash
uv add bloomery      # or: pip install bloomery
```

Python 3.12–3.14. No orchestrator, no cloud SDK, no database driver.

## The shape of it

Specs go in as strings, artifacts come out as values. Writing them to disk is your loop —
the library never touches a filesystem:

```python
from bloomery import Target, compile_project, load_catalog, load_project

catalog = load_catalog(catalog_yaml)
project = load_project({"entity_model.yaml": entities_yaml, "mapping_orders.yaml": mapping_yaml,
                        "metrics.yaml": metrics_yaml, "marts.yaml": marts_yaml})

for artifact in compile_project(project, target=Target.SQLMESH, dialect="duckdb", catalog=catalog):
    print(artifact.path)          # write artifact.content wherever your repo keeps models
```

The same specs also *serve* queries. A `MetricRequest` becomes SQL over a wide,
pre-joined mart — planned by an embedded, render-only MetricFlow, and executed by nothing:

```python
plan = planner.plan(project_ir, MetricRequest(metrics=("revenue",), dimensions=("ordered_month",)),
                    dialect="duckdb")
print(plan.sql, plan.explanation.render())
```

And from a shell — the CLI is a thin argument shell over exactly these functions, and the
only part of the package that touches a filesystem:

```bash
bloomery compile specs/ --target sqlmesh --dialect duckdb --out out/
bloomery resolve specs/          # what is computable, what is missing, what was refused
bloomery schema  --out schemas/  # JSON Schema per spec kind, for editors and validators
```

A refusal exits `1` and a bad invocation exits `2`, so a pipeline can tell "your spec is
wrong" from "your command is wrong". Nothing is executed: `bloomery run` does not exist.

## See it work

Four runnable projects in [`examples/`](examples/). None of them asserts anything it does
not execute, and the seed data is deliberately not clean — padded emails, five spellings
of one segment vocabulary, prices in integer cents, an unparseable timestamp.

| Example | What it demonstrates | Infrastructure |
|---|---|---|
| [`quickstart/`](examples/quickstart/) | The five core spec kinds; compile, then plan a metric request | none |
| [`refusals/`](examples/refusals/) | Six specs that look right and cannot be right, with the real messages | none |
| [`targets/`](examples/targets/) | SQLMesh, dbt, Cube and the planner all actually running | one container |
| [`lakehouse/`](examples/lakehouse/) | Iceberg via Lakekeeper: union merge, quality rules, quarantine, a blocking audit | four containers |

```bash
uv run python examples/quickstart/run.py     # no setup at all
cd examples/targets && just demo             # the interesting one
```

`targets/` is worth the container. It compiles **one** spec set to SQLMesh and to dbt,
builds both, and compares the two marts row for row — because "two frameworks, one spec,
one answer" is a claim, and this turns it into a measurement.

## What it is not

- **It does not execute SQL.** It emits artifacts and plans; SQLMesh, dbt, or Cube run them.
- **It does no orchestration** — scheduling, backfills and deployment belong downstream.
- **It does not read your warehouse.** Catalogs and profiles are inputs, computed elsewhere.
- **It contains no LLM.** Proposals may be drafted with LLM assistance upstream, but they
  arrive as validated specs, and everything the library emits — including the
  human-readable query explanations — is generated deterministically.

## Status

**0.1.0**, the first release. Everything the library does ships behind the quality gate:
the spec layer over six document kinds, the deterministic IR, transforms and typecheck,
resolution, fail-closed guardrails, declarative data quality with quarantine and replay,
steps as referenced implementations, wide marts with role-playing dates, the
SQLMesh/dbt/Cube emitters over DuckDB/Trino/Postgres, the MetricFlow-backed planner,
spec-diff planning, spec assessment, the CLI, and the JSON Schema export. Every test tier
runs, including the Docker-backed engine matrix, the target e2e tiers, and the three-way
equivalence tier.

From this release the promises in
[Stability](https://morzecrew.github.io/bloomery/reference/stability/) bind: per-kind
versioning over spec YAML (fully), SemVer over the Python API (breaking changes are
allowed in a minor below 1.0, but never silently), and emitted artifacts explicitly
**not** stable across versions — byte-reproducible for fixed inputs, which is determinism
rather than a cross-version promise. Pin the minor if you want the API to hold still.

Designs that have not yet landed live as RFCs in [`rfcs/`](rfcs/INDEX.md); code that
contradicts a live RFC is the bug, not the RFC. An RFC is retired once it ships — the
code, the tests and the documentation are then the account of what bloomery does.

## Documentation

Full documentation: **[morzecrew.github.io/bloomery](https://morzecrew.github.io/bloomery/)**

- [Introduction](https://morzecrew.github.io/bloomery/get-started/introduction/) — the
  problem, the spec kinds, the invariants, and the boundary.
- [Quickstart](https://morzecrew.github.io/bloomery/get-started/quickstart/) — specs to
  compiled artifacts to a planned query, in one sitting.
- [Examples](https://morzecrew.github.io/bloomery/get-started/examples/) — which of the
  four runnable projects to reach for, and what each one proves.
- [Concepts](https://morzecrew.github.io/bloomery/concepts/specs-and-catalog/) — the
  domain model, the [compile pipeline](https://morzecrew.github.io/bloomery/concepts/compile-pipeline/),
  [determinism](https://morzecrew.github.io/bloomery/concepts/determinism/),
  [guardrails](https://morzecrew.github.io/bloomery/concepts/guardrails/),
  [data quality](https://morzecrew.github.io/bloomery/concepts/data-quality/),
  [wide marts](https://morzecrew.github.io/bloomery/concepts/wide-marts/).
- How-to — emit [SQLMesh](https://morzecrew.github.io/bloomery/how-to/emit-sqlmesh/),
  [dbt](https://morzecrew.github.io/bloomery/how-to/emit-dbt/) or
  [Cube](https://morzecrew.github.io/bloomery/how-to/emit-cube/);
  [add quality rules](https://morzecrew.github.io/bloomery/how-to/add-quality-rules/);
  [merge sources](https://morzecrew.github.io/bloomery/how-to/merge-sources/);
  [plan a metric request](https://morzecrew.github.io/bloomery/how-to/plan-a-metric-request/);
  [evolve a spec safely](https://morzecrew.github.io/bloomery/how-to/evolve-a-spec/).
- Reference — [spec schemas](https://morzecrew.github.io/bloomery/reference/spec-schemas/),
  [transforms](https://morzecrew.github.io/bloomery/reference/transforms/),
  [errors](https://morzecrew.github.io/bloomery/reference/errors/),
  [API](https://morzecrew.github.io/bloomery/reference/api/),
  [stability](https://morzecrew.github.io/bloomery/reference/stability/).

## Contributing

Contributions, issues and feature requests are welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md), including the RFC process for larger changes.

## Licence

MIT — see [LICENSE](LICENSE).
