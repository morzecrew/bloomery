"""Plan-stage properties (RFC 0007 §6, RFC 0009): ``plan(ir, ir)`` is empty
for every buildable fixture IR, ``plan(None, ir)`` is all-ADDITIVE (or the
D3 staleness refusal when the IR still carries a ``renamed_from``
annotation), plans are deterministic values, and a no-BREAKING plan implies
the new IR still carries every column the old IR's metrics referenced."""

from __future__ import annotations

from functools import lru_cache

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from support.compiling import load_fixture

from bloomery import build_project_ir, plan
from bloomery.errors import RenameTargetMissing
from bloomery.ir import MetricIR, ProjectIR
from bloomery.plan import ChangeClass

pytestmark = pytest.mark.property

# Every fixture whose specs build to an IR (the guardrail-refusal corpus
# cannot reach the plan stage by construction).
FIXTURE_NAMES = [
    "ecom_basic",
    "evolution_v1",
    "evolution_v2",
    "evolution_v3",
    "evolution_v4",
    "evolution_v5",
    "minimal",
    "multi_mart_refusal",
    "non_additive_aov",
    "path_conflict",
    "role_playing_dates",
    "semi_additive_inventory",
]

EVOLUTION_PAIRS = [(f"evolution_v{n}", f"evolution_v{n + 1}") for n in range(1, 5)]


@lru_cache(maxsize=None)
def fixture_ir(name: str) -> ProjectIR:
    project, catalog = load_fixture(name)
    return build_project_ir(project, catalog)


def _annotated(ir: ProjectIR) -> bool:
    return any(
        column.renamed_from is not None for entity in ir.entities for column in entity.columns
    )


def _referenced_leaves(ir: ProjectIR) -> set[str]:
    """Every name the IR's reachable metrics transitively depend on,
    restricted to leaves (names that are not metrics)."""
    by_name = {metric.name: metric for metric in ir.metrics}

    def walk(metric: MetricIR, seen: set[str]) -> None:
        for name in metric.depends_on:
            if name in seen:
                continue
            seen.add(name)
            if name in by_name:
                walk(by_name[name], seen)

    seen: set[str] = set()
    for metric in ir.metrics:
        walk(metric, seen)
    return {name for name in seen if name not in by_name}


def _column_names(ir: ProjectIR) -> set[str]:
    names: set[str] = set()
    for entity in ir.entities:
        for column in entity.columns:
            names.add(column.name)
            if column.canonical is not None:
                names.add(column.canonical)
    return names


@settings(max_examples=20, deadline=None)
@given(name=st.sampled_from(FIXTURE_NAMES))
def test_plan_of_an_ir_against_itself_is_empty(name: str) -> None:
    ir = fixture_ir(name)
    result = plan(ir, ir)
    assert result.changes == ()
    assert not result.has_changes
    assert result.backfill_scope.entities == ()
    assert not result.backfill_scope.restates_history
    assert result.downstream_impact == ()


@settings(max_examples=20, deadline=None)
@given(name=st.sampled_from(FIXTURE_NAMES))
def test_initial_deploy_is_all_additive_or_the_staleness_refusal(name: str) -> None:
    ir = fixture_ir(name)
    if _annotated(ir):
        # RFC 0007 D3: a renamed_from whose old name is absent from old —
        # including old is None — is a stale annotation.
        with pytest.raises(RenameTargetMissing):
            plan(None, ir)
        return
    result = plan(None, ir)
    assert result.has_changes
    assert {change.change_class for change in result.changes} == {ChangeClass.ADDITIVE}
    assert result.breaking == ()
    assert result.backfill_scope.entities == ()
    assert not result.backfill_scope.restates_history
    assert result.downstream_impact == ()


@settings(max_examples=20, deadline=None)
@given(pair=st.sampled_from(EVOLUTION_PAIRS))
def test_plan_is_a_deterministic_value_for_any_pair(pair: tuple[str, str]) -> None:
    old, new = fixture_ir(pair[0]), fixture_ir(pair[1])
    first = plan(old, new)
    second = plan(old, new)
    assert first == second  # changes, scope, and impact — full value identity
    assert first.changes == tuple(sorted(first.changes, key=lambda c: (c.entity or "", c.subject)))


@settings(max_examples=20, deadline=None)
@given(pair=st.sampled_from(EVOLUTION_PAIRS))
def test_no_breaking_plan_preserves_every_referenced_column(pair: tuple[str, str]) -> None:
    """The RFC 0009 invariant: ``plan(a, b)`` classifying nothing BREAKING
    implies ``b``'s columns ⊇ ``a``'s metric-referenced columns."""
    old, new = fixture_ir(pair[0]), fixture_ir(pair[1])
    result = plan(old, new)
    if result.breaking:
        return
    assert _referenced_leaves(old) <= _column_names(new)
