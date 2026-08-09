"""Shared compile-path helpers (RFC 0009 §5.1 ``tests/support/``): fixture
loading through the public API only, whole-fixture compilation, and the
artifact SELECT extraction the execution tier uses."""

from __future__ import annotations

from pathlib import Path

from bloomery import Target, compile_project, load_catalog, load_project
from bloomery.emit import EmittedArtifact
from bloomery.spec import Catalog, Project
from support.steps import registry_for

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def fixture_sources(name: str) -> dict[str, str]:
    """The fixture's project documents (the catalog is loaded separately)."""
    return {
        path.stem: path.read_text()
        for path in sorted((FIXTURES / name).glob("*.yaml"))
        if path.stem != "catalog"
    }


def load_fixture(name: str) -> tuple[Project, Catalog | None]:
    project = load_project(fixture_sources(name))
    catalog_path = FIXTURES / name / "catalog.yaml"
    catalog = load_catalog(catalog_path.read_text()) if catalog_path.exists() else None
    return project, catalog


def compile_fixture(
    name: str, *, target: Target | str = Target.SQLMESH, dialect: str = "duckdb"
) -> tuple[EmittedArtifact, ...]:
    project, catalog = load_fixture(name)
    return compile_project(
        project,
        target=target,
        dialect=dialect,
        catalog=catalog,
        # Empty for every fixture that wires no step, which is all of them but
        # one — so the registry is a lookup rather than a parameter each
        # caller has to remember (RFC 0017 §5.3).
        steps=registry_for(name),
    )


#: What the execution tier substitutes for SQLMesh's run-context macros — the
#: engine's job at run time, stood in for here. Pinned rather than "today":
#: bloomery reads no clock (RFC 0003), and neither may its tests.
EXECUTION_DATE = "2024-01-03"


def expand_engine_macros(sql: str) -> str:
    """Expand the SQLMesh macros bloomery emits, the way the engine would.

    Only the quality mart carries one (``@execution_ds`` for ``run_date`` —
    RFC 0016 §5.8), and the execution tier runs emitted SQL straight against
    DuckDB with no SQLMesh in the loop, so the substitution happens here. It
    is deliberately a *literal*: substituting a clock call would make the
    materialized rows depend on when the suite ran.
    """
    return sql.replace("@execution_ds", f"'{EXECUTION_DATE}'")


def extract_select(content: str) -> str:
    """Strip the SQLMesh ``MODEL (...)`` envelope: the SELECT follows the
    envelope's closing ``);`` (the envelope contains no other ``);``)."""
    _envelope, _sep, select = content.partition(");")
    return expand_engine_macros(select.strip())
