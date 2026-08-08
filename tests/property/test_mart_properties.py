"""Mart-flattening properties (RFC 0010 §6): permuted spec dict order yields
an identical ``MartIR`` (byte-identical compile), and every mart column
traces to exactly one source entity column."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bloomery import Target, build_project_ir, compile_project, load_project
from bloomery.ir import FLAGS_COLUMN, OK_COLUMN
from bloomery.marts import HAS_QUALITY_FLAGS, lower_marts
from bloomery.quality import QUALITY_MART
from support.compiling import compile_fixture, load_fixture
from support.mart_permutations import MART_BLOCKS as _MART_BLOCKS
from support.mart_permutations import sources_with_marts as _sources_with_marts

pytestmark = pytest.mark.property


@settings(max_examples=10, deadline=None)
@given(order=st.permutations(sorted(_MART_BLOCKS)))
def test_flattening_is_invariant_under_mart_document_order(order: list[str]) -> None:
    baseline = compile_project(
        load_project(_sources_with_marts(sorted(_MART_BLOCKS))),
        target=Target.SQLMESH,
        dialect="duckdb",
    )
    permuted = compile_project(
        load_project(_sources_with_marts(order)), target=Target.SQLMESH, dialect="duckdb"
    )
    assert permuted == baseline  # paths, contents, checksums — byte identity


@settings(max_examples=10, deadline=None)
@given(order=st.permutations(sorted(_MART_BLOCKS)))
def test_lowering_yields_identical_mart_ir_under_permutation(order: list[str]) -> None:
    project, _catalog = load_fixture("role_playing_dates")
    draft = build_project_ir(project)
    baseline = lower_marts(load_project(_sources_with_marts(sorted(_MART_BLOCKS))).marts, draft)
    permuted = lower_marts(load_project(_sources_with_marts(order)).marts, draft)
    assert permuted == baseline
    assert [mart.name for mart in permuted.marts] == ["by_ordered", "by_shipped"]


@settings(max_examples=10, deadline=None)
@given(name=st.sampled_from(["ecom_basic", "role_playing_dates", "semi_additive_inventory"]))
def test_every_mart_column_traces_to_exactly_one_source_entity_column(name: str) -> None:
    """Amended by RFC 0016 §5.5: ``has_quality_flags`` traces to the base
    entity's *generated* ``_quality_ok``, which is a column of the emitted
    silver model but not of ``EntityIR.columns`` (the IR carries authored
    columns; the two quality columns are lowered at emit). The trace is still
    exactly one column of exactly one entity — it is simply a generated one."""
    project, catalog = load_fixture(name)
    ir = build_project_ir(project, catalog)
    assert ir.marts != ()
    entities = {entity.name: entity for entity in ir.entities}
    for mart in ir.marts:
        if mart.name == QUALITY_MART:
            continue  # bloomery-owned: built from rule evaluations, not an entity
        for column in mart.columns:
            source = entities[column.source_entity]
            if column.source_column in (FLAGS_COLUMN, OK_COLUMN):
                assert column.name == HAS_QUALITY_FLAGS
                assert source.quality != ()
                continue
            matches = [c for c in source.columns if c.name == column.source_column]
            assert len(matches) == 1, column


def test_mart_fixture_compiles_deterministically() -> None:
    assert compile_fixture("role_playing_dates") == compile_fixture("role_playing_dates")
