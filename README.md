# bloomery

**Entity-first spec compiler: declarative entity/mapping/metric specs, compiled deterministically into SQLMesh, dbt, and Cube artifacts.**

## What it is

bloomery is a pure function library. You hand it four kinds of declarative specs —
sources, entities, mappings, metrics — and it compiles them into ready-to-run artifacts
for SQLMesh, dbt, and Cube: models, audits, and semantic-layer definitions.

- **Deterministic** — same specs in, byte-identical artifacts out, across machines,
  processes, and hash seeds. No clocks, no randomness, no environment reads.
- **Fail-closed guardrails** — grain fan-out, additivity violations, and contract breaks
  are compile errors with named reasons, not silent wrong numbers downstream.
- **Reviewable** — emitted artifacts are stable-sorted, pretty-printed text, so a diff of
  the output is a faithful diff of the semantic change.

## What it is not

- It does **not execute SQL** — it emits artifacts for engines and frameworks that do.
- It does **no orchestration** — scheduling, backfills, and deployment belong to SQLMesh,
  dbt, or whatever runs the artifacts.
- It contains **no LLM** — specs are authored by people (or by tools upstream of this
  library); compilation is deterministic all the way down.

## Quick start

```bash
uv add bloomery
```

```python
from bloomery import compile_project, load_project

project = load_project(
    {
        "sources.yaml": sources_yaml,
        "entities/order.yaml": order_yaml,
        "metrics/revenue.yaml": revenue_yaml,
    }
)

artifacts = compile_project(project, target="sqlmesh", dialect="duckdb")
for artifact in artifacts:
    print(artifact.path)  # write them wherever your repo keeps models
```

## Status

Pre-0.1 and spec-driven: the design lives as RFCs in [`rfcs/`](rfcs/INDEX.md) and the
implementation lands milestone by milestone behind the quality gate. **The API is not
stable yet** — anything may change before 0.1.

## Documentation

Full documentation is available at [https://morzecrew.github.io/bloomery/](https://morzecrew.github.io/bloomery/).

## Contributing

Contributions, issues, and feature requests are welcome.
See [CONTRIBUTING.md](CONTRIBUTING.md) for details — including the RFC process for larger
changes.

## Licence

bloomery is licensed under the MIT License — see [LICENSE](LICENSE) for details.
