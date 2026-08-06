"""Shared compile-path helpers (RFC 0009 §5.1 ``tests/support/``): fixture
loading through the public API only, whole-fixture compilation, and the
artifact SELECT extraction the execution tier uses."""

from __future__ import annotations

from pathlib import Path

from bloomery import Target, compile_project, load_catalog, load_project
from bloomery.emit import EmittedArtifact
from bloomery.spec import Catalog, Project

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


def compile_fixture(name: str, *, dialect: str = "duckdb") -> tuple[EmittedArtifact, ...]:
    project, catalog = load_fixture(name)
    return compile_project(project, target=Target.SQLMESH, dialect=dialect, catalog=catalog)


def extract_select(content: str) -> str:
    """Strip the SQLMesh ``MODEL (...)`` envelope: the SELECT follows the
    envelope's closing ``);`` (the envelope contains no other ``);``)."""
    _envelope, _sep, select = content.partition(");")
    return select.strip()
