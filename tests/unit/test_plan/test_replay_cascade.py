"""A replayed parent brings its children back (S-0084).

A ``referential`` verdict reads only the parent's admitted silver rows, so a
child judged while its parent sat in quarantine was orphaned. When the parent's
own rule relaxes, the plan names the children too: a quarantining child in
``replay_scope`` after its parent (D3, D4), an ``unknown_member`` or ``flag``
child in ``backfill_scope`` (D5).
"""

from __future__ import annotations

import pytest
from support.plan_ir import entity, project, quality_rule

from bloomery import plan
from bloomery.ir import EntityIR, OnFail, QualityRuleIR
from bloomery.plan import Plan

pytestmark = pytest.mark.unit

QUARANTINE_RULE = quality_rule(name="amount_positive", on_fail=OnFail.QUARANTINE)
NARROW_RULE = quality_rule(name="amount_positive", params=(("min", "5"),))


def _referential(parent: str, on_missing: str) -> QualityRuleIR:
    return quality_rule(
        name=f"of_{parent}_referential",
        kind="referential",
        column_name=None,
        on_fail=None,
        params=(("relationship", f"of_{parent}"), ("to_entity", parent), ("on_missing", on_missing)),
    )


def _child(name: str, *parents: tuple[str, str]) -> EntityIR:
    return entity(name, quality=tuple(_referential(p, on_missing) for p, on_missing in parents))


def _plan(children: tuple[EntityIR, ...], *, new_parent_rules: tuple[QualityRuleIR, ...] = ()) -> Plan:
    old = project(entities=(entity("parent", quality=(QUARANTINE_RULE,)), *children))
    new = project(entities=(entity("parent", quality=new_parent_rules), *children))
    return plan(old, new)


def test_relaxing_a_parent_names_its_quarantining_child_after_it() -> None:
    result = _plan((_child("a_child", ("parent", "quarantine")),))
    assert result.replay_scope.entities == ("parent", "a_child")


def test_keeping_children_are_named_in_the_backfill_not_the_replay() -> None:
    result = _plan(
        (
            _child("kept", ("parent", "unknown_member")),
            _child("flagged", ("parent", "flag")),
        )
    )
    assert result.replay_scope.entities == ("parent",)
    assert result.backfill_scope.entities == ("flagged", "kept", "parent")


def test_the_cascade_follows_a_chain_and_its_keepers() -> None:
    result = _plan(
        (
            _child("grandchild", ("child", "quarantine")),
            _child("child", ("parent", "quarantine")),
            _child("kept", ("grandchild", "flag")),
        )
    )
    assert result.replay_scope.entities == ("parent", "child", "grandchild")
    assert result.backfill_scope.entities == ("kept", "parent")


def test_ties_go_by_name_and_a_child_waits_for_every_parent() -> None:
    result = _plan(
        (
            _child("b", ("parent", "quarantine")),
            _child("a", ("parent", "quarantine"), ("b", "quarantine")),
            _child("c", ("parent", "quarantine")),
        )
    )
    assert result.replay_scope.entities == ("parent", "b", "a", "c")


def test_a_cycle_is_ordered_by_name_among_itself() -> None:
    result = _plan(
        (
            _child("y", ("parent", "quarantine"), ("x", "quarantine")),
            _child("x", ("y", "quarantine")),
        )
    )
    assert result.replay_scope.entities == ("parent", "x", "y")


def test_tightening_a_rule_names_no_dependent() -> None:
    result = _plan(
        (
            _child("quarantined", ("parent", "quarantine")),
            _child("kept", ("parent", "unknown_member")),
        ),
        new_parent_rules=(NARROW_RULE,),
    )
    assert result.replay_scope.entities == ()
    assert result.backfill_scope.entities == ("parent",)


def test_an_unrelated_entity_is_not_named() -> None:
    result = _plan((_child("elsewhere", ("other", "quarantine")),))
    assert result.replay_scope.entities == ("parent",)
    assert result.backfill_scope.entities == ("parent",)


def test_a_replayed_child_still_owes_the_backfill_its_keeping_rule_needs() -> None:
    result = _plan(
        (
            _child("q", ("parent", "quarantine")),
            _child("c", ("parent", "unknown_member"), ("q", "quarantine")),
        )
    )
    assert result.replay_scope.entities == ("parent", "q", "c")
    assert "c" in result.backfill_scope.entities


def test_a_child_replayed_for_its_own_rule_still_waits_for_its_parent() -> None:
    old = project(
        entities=(
            entity("z_parent", quality=(QUARANTINE_RULE,)),
            _child("a_child", ("z_parent", "quarantine")),
        )
    )
    new = project(entities=(entity("z_parent"), _child("a_child", ("z_parent", "unknown_member"))))
    assert plan(old, new).replay_scope.entities == ("z_parent", "a_child")


def test_a_child_that_held_no_orphans_before_the_change_is_not_replayed() -> None:
    """S-0084/D-3: only a child that already quarantined on the parent can hold
    its orphans in a reject table. One that is new, or that quarantines on the
    parent only from this change on, has nothing to replay."""
    old = project(
        entities=(
            entity("parent", quality=(QUARANTINE_RULE,)),
            _child("was_kept", ("parent", "unknown_member")),
            _child("held", ("parent", "quarantine")),
        )
    )
    new = project(
        entities=(
            entity("parent"),
            _child("was_kept", ("parent", "quarantine")),
            _child("held", ("parent", "quarantine")),
            _child("brand_new", ("parent", "quarantine")),
        )
    )
    assert plan(old, new).replay_scope.entities == ("parent", "held")
