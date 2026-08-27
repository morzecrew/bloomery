"""Shared compile-path helpers (RFC 0009 §5.1 ``tests/support/``): fixture
loading through the public API only, whole-fixture compilation, and the
artifact SELECT extraction the execution tier uses."""

from __future__ import annotations

import re
from pathlib import Path

from bloomery import Target, compile_project, load_catalog, load_project
from bloomery.emit import EmittedArtifact
from bloomery.spec import Catalog, Project
from support.steps import registry_for

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

#: ``{{ ref('x') }}`` and ``{{ source('ns', 'x') }}`` as the dbt emitter writes
#: them (RFC 0008 D20) — anchored on the exact rendering rather than on loose
#: brace matching, so a change in how they are emitted fails here rather than
#: silently stopping to match.
_DBT_REF = re.compile(r"\{\{ ref\('(?P<relation>[^']+)'\) \}\}")
_DBT_SOURCE = re.compile(r"\{\{ source\('(?P<namespace>[^']+)', '(?P<relation>[^']+)'\) \}\}")


#: Fixture directories that hold no spec project. `dirty` is the CSV seed-data
#: corpus the quality tiers read; it has no `*.yaml` and `read_spec_directory`
#: refuses it. Named rather than discovered, so a *spec* fixture that stops
#: loading fails its caller by name instead of quietly leaving the sweep.
NON_SPEC_FIXTURES = frozenset({"dirty"})


def spec_fixture_names() -> tuple[str, ...]:
    """Every fixture directory holding a spec project, sorted.

    Callers that sweep the corpus iterate this and load **without** catching:
    a broad `except: continue` turns a resolver regression into a smaller sweep
    that still passes, because a floor like "at least 20 fixtures" cannot tell
    twenty-two from twenty. Anything here that fails to load is a failure of
    whoever is sweeping, which is the point.
    """
    return tuple(
        sorted(
            entry.name
            for entry in FIXTURES.iterdir()
            if entry.is_dir() and entry.name not in NON_SPEC_FIXTURES
        )
    )


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


def resolve_dbt_references(sql: str) -> str:
    """dbt references back to the relations they resolve to (RFC 0008 D20).

    A dbt model body is a *template*, not SQL: since D20 its inputs are
    ``{{ ref(...) }}`` and ``{{ source(...) }}`` so that dbt can order the DAG
    and place the relations. Two tiers need the SQL underneath — the
    port-abstraction proof (D5) compares it against what SQLMesh renders, and
    the parse property checks it is well-formed — and both would otherwise have
    to stop looking at dbt, which is the coverage loss rather than the
    substitution.

    ``ref()`` names a *model*, not a relation, so it resolves without a
    namespace; the namespace it will materialize into is the ``+schema``
    config's business and is asserted where that config is. ``source()``
    carries its namespace and keeps it.
    """
    sql = _DBT_SOURCE.sub(lambda m: f"{m['namespace']}.{m['relation']}", sql)
    return _DBT_REF.sub(lambda m: m["relation"], sql)
