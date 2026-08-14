# bloomery

**Entity-first spec compiler: declarative entity/mapping/metric specs, compiled deterministically into SQLMesh, dbt, and Cube artifacts.**

## What it is

bloomery is a pure function library. You hand it five kinds of declarative specs —
catalog, entities, mappings, metrics, marts — and it compiles them into ready-to-run
artifacts for SQLMesh, dbt, and Cube: models, audits, and semantic-layer definitions.
The same specs also serve metric queries at request time: a structured `MetricRequest`
becomes SQL over a wide mart, planned by an embedded, render-only MetricFlow.

- **Deterministic** — same specs in, byte-identical artifacts out, across machines,
  processes, and hash seeds. No clocks, no randomness, no environment reads.
- **Fail-closed guardrails** — grain fan-out, additivity violations, and contract breaks
  are compile errors with named reasons, not silent wrong numbers downstream.
- **Reviewable** — emitted artifacts are stable-sorted, pretty-printed text, so a diff of
  the output is a faithful diff of the semantic change.

## What it is not

- It does **not execute SQL** — it emits artifacts and plans for engines and frameworks
  that do.
- It does **no orchestration** — scheduling, backfills, and deployment belong to SQLMesh,
  dbt, or whatever runs the artifacts.
- It contains **no LLM** — specs are authored by people (or by tools upstream of this
  library); compilation is deterministic all the way down.

## Quick start

Pre-0.1, not yet on PyPI — install from the repository:

```bash
uv add git+https://github.com/morzecrew/bloomery
```

Compile specs into SQLMesh artifacts (the library never touches the filesystem —
writing is your loop):

```python
from bloomery import Target, compile_project, load_catalog, load_project

catalog = load_catalog(catalog_yaml)
project = load_project(
    {
        "entity_model.yaml": entities_yaml,
        "mapping_orders.yaml": mapping_yaml,
        "metrics.yaml": metrics_yaml,
        "marts.yaml": marts_yaml,
    }
)

artifacts = compile_project(project, target=Target.SQLMESH, dialect="duckdb", catalog=catalog)
for artifact in artifacts:
    print(artifact.path)  # write artifact.content wherever your repo keeps models
```

Or from a shell — the CLI is a thin argument shell over exactly these functions, and the
only part of the package that touches a filesystem:

```bash
bloomery compile specs/ --target sqlmesh --dialect duckdb --out out/
bloomery resolve specs/          # what is computable, what is missing, what was refused
bloomery schema --out schemas/   # JSON Schema per spec kind, for editors and validators
```

A refusal exits `1` and a bad invocation exits `2`, so a pipeline can tell "your spec is
wrong" from "your command is wrong". Nothing is executed: `bloomery run` does not exist.

Assess a spec before it compiles — refusals come back as a **value**, alongside whatever
analysis completed before them, so a draft mid-edit still reports what it would give you:

```python
from bloomery import Stage, evaluate

evidence = evaluate(project, catalog=catalog)
evidence.stage_reached   # read this first: at any stage but COMPLETE the rest is a prefix
evidence.reachable       # ('gross_revenue', 'order_count', …)
evidence.unreachable     # margin, blocked on 'cogs' — the specific leaf, not a summary
evidence.refusals        # each with its own source path into the spec that caused it
```

Plan a metric request over the mart those specs declared — SQL out, nothing executed:

```python
from bloomery import LruManifestHydrator, MetricFlowPlanner, MetricRequest, build_project_ir
from bloomery.naming import DefaultNaming

naming = DefaultNaming()
planner = MetricFlowPlanner(LruManifestHydrator(naming), naming=naming)
plan = planner.plan(
    build_project_ir(project, catalog=catalog),
    MetricRequest(metrics=("revenue",), dimensions=("ordered_month",)),
    dialect="duckdb",
)
print(plan.sql)
print(plan.explanation.render())
```

Filters are typed CNF clauses (`Predicate` / `AnyOf` — implicit AND, one level of OR), and
`bloomery.planner.parse_filter_json` is a public front door for the Mongo-flavoured JSON
grammar (`$and`/`$or`/`$not`, field maps): it normalizes (De Morgan → complement inversion
→ capped CNF) before refusing, and refuses only from the closed, drift-guarded list
exported as `bloomery.planner.KNOWN_UNSUPPORTED`:

```python
from bloomery.planner import parse_filter_json

filters = parse_filter_json(
    {
        "customer_id": {"$neq": "internal"},
        "$or": [{"ordered_month": {"$gte": "2024-01-01"}}, {"ordered_month": "2023-12-01"}],
    }
)  # → (Predicate(…), AnyOf(…)) — pass straight to MetricRequest(filters=…)
```

The runnable version of both snippets lives in
[`examples/quickstart/`](examples/quickstart/):

```bash
uv run python examples/quickstart/run.py
```

## Status

Pre-0.1. All core milestones (M1–M10) are implemented behind the quality gate: spec
layer, deterministic IR, transforms and typecheck, resolution, guardrails, wide marts
with role-playing dates, the SQLMesh/Cube/dbt emitters over DuckDB/Trino/Postgres, the
MetricFlow-backed planner with manifest hydration, spec-diff planning, and the CNF query
vocabulary with its JSON filter front door — 1200+ tests across the default tiers. The
end-to-end and cross-target equivalence tiers are still landing. **The API is not
stable yet** — anything may change before 0.1. What each surface will promise from 0.1
onward is written down now, in
[Stability](https://morzecrew.github.io/bloomery/reference/stability/): SemVer over the
Python API, per-kind versioning over spec YAML, and emitted artifacts explicitly **not**
stable — byte-reproducible for fixed inputs, which is determinism rather than a
cross-version promise.

Designs that have not yet landed live as RFCs in [`rfcs/`](rfcs/INDEX.md); code that
contradicts a live RFC is the bug, not the RFC. An RFC is retired once it ships — the
code, the tests and the documentation are the account of what bloomery already does.

## Documentation

Full documentation is available at
[https://morzecrew.github.io/bloomery/](https://morzecrew.github.io/bloomery/):

- [Quickstart](https://morzecrew.github.io/bloomery/get-started/quickstart/) — specs to
  compiled artifacts to a planned query.
- [Concepts](https://morzecrew.github.io/bloomery/concepts/specs-and-catalog/) — the
  domain model, the compile pipeline, determinism, guardrails, wide marts.
- How-to guides — emit
  [SQLMesh](https://morzecrew.github.io/bloomery/how-to/emit-sqlmesh/),
  [Cube](https://morzecrew.github.io/bloomery/how-to/emit-cube/), or
  [dbt](https://morzecrew.github.io/bloomery/how-to/emit-dbt/);
  [plan a metric request](https://morzecrew.github.io/bloomery/how-to/plan-a-metric-request/);
  [evolve a spec safely](https://morzecrew.github.io/bloomery/how-to/evolve-a-spec/).
- Reference —
  [spec schemas](https://morzecrew.github.io/bloomery/reference/spec-schemas/),
  [transforms](https://morzecrew.github.io/bloomery/reference/transforms/),
  [errors](https://morzecrew.github.io/bloomery/reference/errors/),
  [API](https://morzecrew.github.io/bloomery/reference/api/),
  [stability](https://morzecrew.github.io/bloomery/reference/stability/).

## Contributing

Contributions, issues, and feature requests are welcome.
See [CONTRIBUTING.md](CONTRIBUTING.md) for details — including the RFC process for larger
changes.

## Licence

bloomery is licensed under the MIT License — see [LICENSE](LICENSE) for details.
