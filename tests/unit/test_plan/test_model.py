"""The plan-stage value objects (RFC 0007 §5.1)."""

from __future__ import annotations

import pytest

from bloomery.plan import BackfillScope, Change, ChangeClass, Plan

pytestmark = pytest.mark.unit

EMPTY_SCOPE = BackfillScope(entities=(), restates_history=False)


def test_change_class_is_exactly_the_spec_vocabulary() -> None:
    assert [member.value for member in ChangeClass] == [
        "additive",
        "widening",
        "rename",
        "restating",
        "breaking",
    ]


def test_empty_plan_has_no_changes_and_no_breaking_subset() -> None:
    empty = Plan(changes=(), backfill_scope=EMPTY_SCOPE, downstream_impact=())
    assert not empty.has_changes
    assert empty.breaking == ()


def test_breaking_property_filters_in_plan_order() -> None:
    additive = Change(None, "metric:m", ChangeClass.ADDITIVE, "metric added")
    first = Change("a", "entity:a", ChangeClass.BREAKING, "grain changed")
    second = Change("b", "field:x", ChangeClass.BREAKING, "field dropped")
    populated = Plan(
        changes=(additive, first, second),
        backfill_scope=EMPTY_SCOPE,
        downstream_impact=(),
    )
    assert populated.has_changes
    assert populated.breaking == (first, second)


def test_plan_values_are_hashable_and_comparable() -> None:
    change = Change("e", "field:x", ChangeClass.RENAME, "renamed from 'y'", old="y", new="x")
    scope = BackfillScope(entities=("e",), restates_history=True)
    left = Plan(changes=(change,), backfill_scope=scope, downstream_impact=("m",))
    right = Plan(changes=(change,), backfill_scope=scope, downstream_impact=("m",))
    assert left == right
    assert hash(left) == hash(right)
