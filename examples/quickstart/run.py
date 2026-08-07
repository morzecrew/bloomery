"""Quickstart: compile the specs in this directory to SQLMesh artifacts,
write them to ./out, then plan one metric request against the same specs.

Run from the repository root:

    uv run python examples/quickstart/run.py
"""

from pathlib import Path

from bloomery import (
    LruManifestHydrator,
    MetricFlowPlanner,
    MetricRequest,
    Target,
    build_project_ir,
    compile_project,
    load_catalog,
    load_project,
)
from bloomery.naming import DefaultNaming

HERE = Path(__file__).parent
OUT = HERE / "out"


def main() -> None:
    # The loaders are pure: they take YAML *strings*, never paths. Reading
    # files is the caller's job — the library performs no I/O.
    catalog = load_catalog((HERE / "catalog.yaml").read_text())
    project = load_project(
        {
            path.name: path.read_text()
            for path in sorted(HERE.glob("*.yaml"))
            if path.name != "catalog.yaml"
        }
    )

    # Compile: parsed specs in, a tuple of file-shaped artifacts out.
    # Writing them to disk is, again, the caller's four lines.
    artifacts = compile_project(project, target=Target.SQLMESH, dialect="duckdb", catalog=catalog)
    for artifact in artifacts:
        destination = OUT / artifact.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(artifact.content)
        print(f"wrote {destination.relative_to(HERE)}")

    # Plan one metric request over the mart the specs declared. The planner
    # renders SQL and never executes it — run plan.sql wherever you like.
    naming = DefaultNaming()
    planner = MetricFlowPlanner(LruManifestHydrator(naming), naming=naming)
    plan = planner.plan(
        build_project_ir(project, catalog=catalog),
        MetricRequest(metrics=("revenue",), dimensions=("ordered_month",)),
        dialect="duckdb",
    )
    print("\n-- plan.sql --")
    print(plan.sql)
    print("\n-- plan.explanation.render() --")
    print(plan.explanation.render())


if __name__ == "__main__":
    main()
