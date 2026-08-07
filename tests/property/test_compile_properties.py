"""Property tier (RFC 0009 §5.5): compile-twice byte identity, emitted SQL
parsing under the target dialect, and SELECT-columns ⇔ declared-fields — the
invariants that must hold for every input."""

from __future__ import annotations

import pytest
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
    "semi_additive_inventory",
]


@settings(max_examples=10, deadline=None)
@given(name=st.sampled_from(FIXTURE_NAMES))
def test_compile_twice_yields_identical_bytes(name: str) -> None:
    first = compile_fixture(name)
    second = compile_fixture(name)
    assert first == second  # paths, contents, and checksums — full byte identity


@settings(max_examples=10, deadline=None)
@given(name=st.sampled_from(FIXTURE_NAMES))
def test_emitted_select_parses_under_the_duckdb_dialect(name: str) -> None:
    for artifact in compile_fixture(name):
        # Audit bodies select from SQLMesh's @this_model macro — substitute a
        # plain relation so the SELECT itself must still parse (RFC 0008 D4).
        select = extract_select(artifact.content).replace("@this_model", "silver.model")
        parsed = parse_one(select, dialect="duckdb")
        assert isinstance(parsed, exp.Select)


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
