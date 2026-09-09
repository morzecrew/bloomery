"""Rollup changes in a plan (RFC 0058 §5.2).

A rollup is its own IR collection, so `plan()` had to be taught to walk it;
until it was, changing one reported no impact at all — the quietest possible
answer to "what does this change break".

Every redefinition of what the table *holds* is breaking, and that is a
decision rather than an omission: the parent, the grouping and the measures
each change its rows, and there is no cost-hint-shaped half of those to grade
down.

`partition_by` is the exception, and it is not a rollup-shaped judgement — it
is the one `_mart_pair` already makes about the same field on the node beside
this one. Physical layout is not rows. Grading it breaking here would have one
module answer one question two ways depending on which collection the node
came from.
"""

from __future__ import annotations

import dataclasses

import pytest
from support.plan_ir import project

from bloomery import plan
from bloomery.ir import PartitionSpec, RollupIR
from bloomery.ir import Materialization
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


def test_a_partitioning_change_is_metadata_and_not_rows() -> None:
    """The same verdict `_mart_pair` gives the same field, word for word.

    Repartitioning moves where the rows land and not which rows they are, so
    grading it breaking would say the pre-aggregate now holds something else.
    Asserted against the mart's own wording rather than a fresh sentence,
    because the point of the fix is that one module answers this once.
    """

    partitioned = dataclasses.replace(
        MONTHLY, partition_by=(PartitionSpec(transform="months", column="ordered_month"),)
    )
    (change,) = _changes((MONTHLY,), (partitioned,))

    assert change.change_class is ChangeClass.ADDITIVE
    assert change.detail == "partition_by changed (metadata only)"


def test_a_materialization_change_is_breaking() -> None:
    """A mart's is breaking too: it decides how much of the table is rebuilt,
    which is not the same question as where it lands."""

    (change,) = _changes(
        (MONTHLY,), (dataclasses.replace(MONTHLY, materialization=Materialization.INCREMENTAL_BY_KEY),)
    )

    assert change.change_class is ChangeClass.BREAKING
    assert change.detail == "rollup redefined — the rows it holds changed"


def test_a_repartitioned_redefinition_reports_both() -> None:
    """Rows and layout are separate verdicts, so a change to both is two
    changes rather than the stricter one swallowing the other."""

    both = dataclasses.replace(
        MONTHLY,
        keep=("ordered_year",),
        partition_by=(PartitionSpec(transform="years", column="ordered_year"),),
    )

    assert sorted(change.change_class for change in _changes((MONTHLY,), (both,))) == sorted(
        (ChangeClass.ADDITIVE, ChangeClass.BREAKING)
    )


def test_an_unchanged_rollup_is_no_change_at_all() -> None:
    assert _changes((MONTHLY,), (MONTHLY,)) == ()
