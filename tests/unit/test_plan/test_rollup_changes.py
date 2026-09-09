"""Rollup changes in a plan (RFC 0058 §5.2).

A rollup is its own IR collection, so `plan()` had to be taught to walk it;
until it was, changing one reported no impact at all — the quietest possible
answer to "what does this change break".

Every redefinition is breaking, and that is a decision rather than an
omission. A rollup is three facts — the parent, the grouping, the measures —
and each one changes the rows the table holds. There is no metadata half to
sort into `ADDITIVE`, the way a mart's `cost_hint` is, so grading one would be
inventing a distinction the node does not have.
"""

from __future__ import annotations

import dataclasses

import pytest
from support.plan_ir import project

from bloomery import plan
from bloomery.ir import RollupIR
from bloomery.plan import Change, ChangeClass

pytestmark = pytest.mark.unit

MONTHLY = RollupIR(
    name="orders_monthly",
    of="orders",
    keep=("ordered_month",),
    measures=("revenue",),
)


def _changes(old: tuple[RollupIR, ...], new: tuple[RollupIR, ...]) -> tuple[Change, ...]:
    return plan(project(rollups=old), project(rollups=new)).changes


def test_a_new_rollup_is_additive() -> None:
    (change,) = _changes((), (MONTHLY,))

    assert change.subject == "rollup:orders_monthly"
    assert change.change_class is ChangeClass.ADDITIVE


def test_a_dropped_rollup_is_breaking() -> None:
    """Breaking because a relation went away, not because a measure did: a
    rollup only pre-aggregates measures its parent still stores, and nothing
    that reads a measure reads it."""

    (change,) = _changes((MONTHLY,), ())

    assert change.change_class is ChangeClass.BREAKING
    assert change.detail == "rollup dropped"


def test_a_dropped_rollup_does_not_drop_a_measure() -> None:
    """The mart's own `_diff_marts` records dropped measures; this must not,
    or removing a pre-aggregate would report the measure as gone."""

    result = plan(project(rollups=(MONTHLY,)), project(rollups=()))

    assert result.replay_scope.entities == ()
    assert all("revenue" not in (change.detail or "") for change in result.changes)


@pytest.mark.parametrize(
    ("field", "value"),
    [("of", "order_lines"), ("keep", ("ordered_year",)), ("measures", ("revenue", "lines"))],
)
def test_any_redefinition_is_breaking(field: str, value: object) -> None:
    """Each of the three facts changes the rows the table holds."""

    (change,) = _changes((MONTHLY,), (dataclasses.replace(MONTHLY, **{field: value}),))

    assert change.change_class is ChangeClass.BREAKING
    assert change.detail == "rollup redefined — the rows it holds changed"


def test_an_unchanged_rollup_is_no_change_at_all() -> None:
    assert _changes((MONTHLY,), (MONTHLY,)) == ()
