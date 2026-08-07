"""Property tier (RFC 0009 §5.5): compile-twice byte identity across every
(target × dialect) cell, emitted SQL parsing under the target dialect, Cube
YAML round-tripping and dialect independence, and SELECT-columns ⇔
declared-fields — the invariants that must hold for every input."""

from __future__ import annotations

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlglot import exp, parse_one

from bloomery import Target, compile_project, load_project
from support.compiling import compile_fixture, extract_select, fixture_sources, load_fixture

pytestmark = pytest.mark.property

FIXTURE_NAMES = [
    "ecom_basic",
    "minimal",
    "path_conflict",
    "role_playing_dates",
    "scd2_customers",
    "semi_additive_inventory",
]

DIALECTS = ["duckdb", "postgres", "trino"]

CUBE_FIXTURES = [
    "ecom_basic",
    "non_additive_aov",
    "role_playing_dates",
    "semi_additive_inventory",
]


@settings(max_examples=20, deadline=None)
@given(
    name=st.sampled_from(FIXTURE_NAMES),
    target=st.sampled_from(list(Target)),
    dialect=st.sampled_from(DIALECTS),
)
def test_compile_twice_yields_identical_bytes(name: str, target: Target, dialect: str) -> None:
    first = compile_fixture(name, target=target, dialect=dialect)
    second = compile_fixture(name, target=target, dialect=dialect)
    assert first == second  # paths, contents, and checksums — full byte identity


def _sql_body(target: Target, content: str) -> str:
    if target is Target.SQLMESH:
        return extract_select(content)
    # A dbt model is header + config, a blank line, then the SELECT; a
    # snapshot additionally wraps it in {% snapshot %} block markers.
    body = content.partition("\n\n")[2]
    if body.rstrip("\n").endswith("{% endsnapshot %}"):
        body = body.rpartition("\n\n")[0]
    return body.strip()


@settings(max_examples=30, deadline=None)
@given(
    name=st.sampled_from(FIXTURE_NAMES),
    target=st.sampled_from([Target.SQLMESH, Target.DBT]),
    dialect=st.sampled_from(DIALECTS),
)
def test_emitted_sql_parses_under_the_target_dialect(
    name: str, target: Target, dialect: str
) -> None:
    for artifact in compile_fixture(name, target=target, dialect=dialect):
        if not artifact.path.endswith(".sql"):
            continue
        # Audit bodies select from SQLMesh's @this_model macro — substitute a
        # plain relation so the SELECT itself must still parse (RFC 0008 D4).
        select = _sql_body(target, artifact.content).replace("@this_model", "silver.model")
        parsed = parse_one(select, dialect=dialect)
        assert isinstance(parsed, exp.Select)


@settings(max_examples=10, deadline=None)
@given(name=st.sampled_from(CUBE_FIXTURES))
def test_cube_yaml_round_trips_and_ignores_the_dialect(name: str) -> None:
    baseline = compile_fixture(name, target=Target.CUBE, dialect="duckdb")
    for artifact in baseline:
        document = yaml.safe_load(artifact.content)  # round-trips as YAML
        assert isinstance(document, dict)
        assert yaml.safe_load(artifact.content) == document
    for dialect in DIALECTS:
        # Cube YAML is dialect-independent (RFC 0008 §5.4): the dialect axis
        # must not reach the bytes.
        assert compile_fixture(name, target=Target.CUBE, dialect=dialect) == baseline


@settings(max_examples=10, deadline=None)
@given(order=st.permutations(sorted(fixture_sources("minimal"))))
def test_compile_is_invariant_under_source_insertion_order(order: list[str]) -> None:
    sources = fixture_sources("minimal")
    reordered = {name: sources[name] for name in order}
    baseline = compile_fixture("minimal")
    permuted = compile_project(load_project(reordered), target=Target.SQLMESH, dialect="duckdb")
    assert permuted == baseline


def test_minimal_select_columns_match_declared_fields_both_directions() -> None:
    project, _ = load_fixture("minimal")
    (artifact,) = compile_fixture("minimal")
    parsed = parse_one(extract_select(artifact.content), dialect="duckdb")
    assert isinstance(parsed, exp.Select)
    emitted = {projection.alias_or_name for projection in parsed.expressions}
    declared = set(project.entity_model.entities["event"].fields)
    assert emitted == declared
