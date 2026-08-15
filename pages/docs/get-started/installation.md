# Installation

How to install bloomery into a project, what it brings with it, and what it deliberately
does not need.

## Requirements

- Python **3.12, 3.13, or 3.14** (`>=3.12,<3.15`).
- Nothing else: no database, no orchestrator, no cloud credentials. bloomery is a pure
  library — it emits artifacts and plans; executing them is another tool's job.

## Install

With [uv](https://docs.astral.sh/uv/):

```bash
uv add bloomery
```

With pip:

```bash
pip install bloomery
```

**Pin the minor.** Below 1.0 a breaking API change may ship in a minor release — never
silently, always with a changelog entry naming the migration, but it may ship. So
`bloomery>=0.1,<0.2` is the constraint that holds the API still; see
[Stability](../reference/stability.md) for exactly what each surface promises.

To track unreleased work instead, install from the repository — append `@<sha>` to pin a
commit:

```bash
uv add git+https://github.com/morzecrew/bloomery
```

## For contributors

Clone the repository and let uv build the environment from the lockfile:

```bash
git clone https://github.com/morzecrew/bloomery
cd bloomery
uv sync
```

`just quality -s` runs the full quality gate and `just test` the default test tiers —
see [CONTRIBUTING.md](https://github.com/morzecrew/bloomery/blob/main/CONTRIBUTING.md)
for the workflow.

## What comes with it

The install brings the compilation toolchain as ordinary dependencies: SQLGlot (SQL as
AST), Pydantic (spec validation), PyYAML, Jinja2 (artifact envelopes), and a pinned
MetricFlow that powers the request-time planner — embedded and render-only, never
connected to a database. The emitted artifacts are consumed by SQLMesh, dbt, or Cube;
none of those need to be installed alongside bloomery, only wherever the artifacts run.

## Verify

```bash
bloomery --version
python -c "import bloomery; print(sorted(bloomery.__all__))"
```

The first prints the release you installed — quote it in a bug report. The second prints
the public API surface, `load_project` through `compile_project` to `MetricFlowPlanner`.
Continue to the [Quickstart](quickstart.md) to compile your first project.
