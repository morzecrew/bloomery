"""MetricFlow emitter properties (RFC 0013 §6): the transformed manifest's
sorted-keys JSON is byte-stable under permuted spec document order (the
manifest is hashed and cached — RFC 0014; ordering drift would silently
defeat the cache), and every emitted dimension round-trips through
``DimensionRef.qualified`` (the pre-``names.py`` half of the RFC 0013 D7
bridge property; M7 owns the full round-trip)."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bloomery import build_project_ir, load_project
from bloomery.emit.metricflow import emit_manifest, manifest_json
from bloomery.naming import DefaultNaming
from support.compiling import load_fixture
from support.mart_permutations import MART_BLOCKS, sources_with_marts

pytestmark = pytest.mark.property


def _manifest_bytes(order: list[str]) -> str:
    _project, catalog = load_fixture("role_playing_dates")
    ir = build_project_ir(load_project(sources_with_marts(order)), catalog)
    return manifest_json(emit_manifest(ir, naming=DefaultNaming()))


@settings(max_examples=10, deadline=None)
@given(order=st.permutations(sorted(MART_BLOCKS)))
def test_manifest_json_is_invariant_under_mart_document_order(order: list[str]) -> None:
    assert _manifest_bytes(order) == _manifest_bytes(sorted(MART_BLOCKS))


@settings(max_examples=10, deadline=None)
@given(
    name=st.sampled_from(["ecom_basic", "role_playing_dates", "semi_additive_inventory"])
)
def test_emitted_dimensions_round_trip_through_dimension_ref(name: str) -> None:
    """Every dimension the emitter produces is a mart dimension whose
    ``DimensionRef.qualified`` equals the emitted name — the emitter and the
    (M7) name bridge must agree on flattened names (RFC 0013 D7)."""
    project, catalog = load_fixture(name)
    ir = build_project_ir(project, catalog)
    manifest = emit_manifest(ir, naming=DefaultNaming())
    for model in manifest.semantic_models:
        mart = next(m for m in ir.marts if m.name == model.name)
        refs = {dimension.column: dimension.ref for dimension in mart.dimensions}
        for dimension in model.dimensions:
            assert refs[dimension.name].qualified == dimension.name


def test_manifest_emission_is_deterministic_across_runs() -> None:
    project, catalog = load_fixture("semi_additive_inventory")
    ir = build_project_ir(project, catalog)
    assert manifest_json(emit_manifest(ir, naming=DefaultNaming())) == manifest_json(
        emit_manifest(ir, naming=DefaultNaming())
    )
