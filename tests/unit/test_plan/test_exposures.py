"""``Plan.affected_exposures`` (RFC 0056 §5.4, D2a).

The report change that makes an exposure worth declaring: a breaking change
already names its downstream metrics, and this puts names to the dashboards
those metrics feed — the difference between "this is breaking" and "this is
breaking, and here is who to tell".

The shape these tests are really about is D2a's: **marts as well as metrics**.
The metric-only walk is the obvious shortcut and it omits exactly the mart-only
exposure, from a report whose entire purpose is to be complete.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from bloomery.ir import Materialization, UnreachableMetric
from bloomery.plan import plan
from support.plan_ir import column, entity, exposure, mart, mart_column, metric, project

pytestmark = pytest.mark.unit


def _project(**overrides: object) -> object:
    base = project(
        entities=(entity("order_item", columns=(column("amount"),)),),
        metrics=(metric("gross_revenue", expr="amount"),),
        marts=(
            mart(
                "order_items",
                columns=(mart_column("amount"),),
                measures=("gross_revenue",),
            ),
        ),
        exposures=(
            exposure("weekly_revenue_review", metrics=("gross_revenue",)),
            exposure("finance_extract", kind="application", marts=("order_items",)),
        ),
    )
    return replace(base, **overrides)  # type: ignore[type-var]


def test_an_unchanged_project_reaches_nobody() -> None:
    """``plan(ir, ir)`` is the empty plan (RFC 0007 D2), and an empty plan that
    named a consumer would be telling someone about nothing."""

    ir = _project()
    assert plan(ir, ir).affected_exposures == ()


def test_a_changed_metric_reaches_the_exposure_that_reads_it() -> None:
    ir = _project()
    after = replace(ir, metrics=(metric("gross_revenue", expr="amount * qty"),))

    result = plan(ir, after)

    assert result.downstream_impact == ("gross_revenue",)
    assert result.affected_exposures == ("weekly_revenue_review",)


def test_a_changed_mart_reaches_the_exposure_that_reads_only_marts() -> None:
    """D2a, and the case the metric-only walk cannot see: ``finance_extract``
    names no metric at all, so nothing in ``downstream_impact`` will ever match
    it — and it is a real consumer of a mart that just changed shape."""

    ir = _project()
    after = replace(
        ir,
        marts=(
            mart(
                "order_items",
                columns=(mart_column("amount"),),
                measures=("gross_revenue",),
                materialization=Materialization.INCREMENTAL_BY_KEY,
            ),
        ),
    )

    result = plan(ir, after)

    assert result.downstream_impact == ()
    assert "finance_extract" in result.affected_exposures


def test_a_metric_that_became_unreachable_still_reaches_its_exposure() -> None:
    """The metric-side twin of the mart-only case, and the same hole.

    `_downstream_impact` walks `new.metrics`, so a metric that *left* that
    collection cannot appear in it — and a metric losing reachability is a
    BREAKING change whose whole point is that someone reading it is about to
    lose a number. The exposure guardrail asks the authored documents, where an
    unreachable metric is declared like any other, so declaring one is legal and
    the consumer is real.
    """

    ir = replace(
        _project(),
        metrics=(metric("gross_revenue", expr="amount"), metric("margin", expr="amount - cogs")),
        exposures=(exposure("margin_watch", kind="analysis", metrics=("margin",)),),
    )
    after = replace(
        ir,
        metrics=(metric("gross_revenue", expr="amount"),),
        unreachable=(UnreachableMetric(name="margin", missing=("cogs",), via=()),),
    )

    result = plan(ir, after)

    assert [(c.subject, c.change_class.value) for c in result.changes] == [
        ("metric:margin", "breaking")
    ]
    assert result.downstream_impact == ()
    assert result.affected_exposures == ("margin_watch",)


def test_a_metric_removed_outright_reaches_its_exposure_too() -> None:
    """The other way a metric leaves `new.metrics`. Both arrive here as a
    `metric:` change the walk cannot see, so both are covered by the same
    rule — and pinning only one would let a fix for it miss the other."""

    ir = replace(
        _project(),
        metrics=(metric("gross_revenue", expr="amount"), metric("margin", expr="amount")),
        exposures=(exposure("margin_watch", kind="analysis", metrics=("margin",)),),
    )
    after = replace(ir, metrics=(metric("gross_revenue", expr="amount"),))

    assert plan(ir, after).affected_exposures == ("margin_watch",)


def test_an_additive_metric_change_reaches_nobody() -> None:
    """The rule is symmetric with the mart side: a metric *added* moves no
    existing number, so it tells no dashboard anything — and without this the
    section would fire on every plan that declares a new metric."""

    ir = replace(
        _project(),
        exposures=(exposure("weekly_revenue_review", metrics=("gross_revenue",)),),
    )
    after = replace(
        ir, metrics=(metric("gross_revenue", expr="amount"), metric("order_count", agg="count"))
    )

    result = plan(ir, after)

    assert [change.change_class.value for change in result.changes] == ["additive"]
    assert result.affected_exposures == ()


def test_an_additive_mart_change_reaches_nobody() -> None:
    """The rule the metric side already applies to itself: ADDITIVE means
    nothing existing moves, so a partitioning change tells no dashboard
    anything. Without this the section would fire on every plan that touches a
    mart at all, and a report that always names everyone names no one."""

    ir = _project()
    after = replace(
        ir,
        marts=(
            mart(
                "order_items",
                columns=(mart_column("amount"),),
                measures=("gross_revenue",),
                cost_hint=7,
            ),
        ),
    )

    result = plan(ir, after)

    assert [change.change_class.value for change in result.changes] == ["additive"]
    assert result.affected_exposures == ()


def test_the_names_come_back_sorted() -> None:
    """Every plan collection is sorted (RFC 0007 D6), and this one is built by
    filtering ``ProjectIR.exposures``, which is sorted by name — so the
    assertion is that the filter preserved it rather than that a sort ran."""

    ir = _project()
    after = replace(
        ir,
        metrics=(metric("gross_revenue", expr="amount * qty"),),
        marts=(
            mart(
                "order_items",
                columns=(mart_column("amount"),),
                measures=("gross_revenue",),
                materialization=Materialization.INCREMENTAL_BY_KEY,
            ),
        ),
    )

    assert plan(ir, after).affected_exposures == ("finance_extract", "weekly_revenue_review")


def test_a_project_with_no_exposures_reports_none() -> None:
    """The field defaults to empty and stays empty, so a project that has never
    heard of the feature reads exactly as it did before."""

    ir = replace(_project(), exposures=())
    after = replace(ir, metrics=(metric("gross_revenue", expr="amount * qty"),))

    assert plan(ir, after).affected_exposures == ()


def test_an_exposure_the_change_does_not_reach_is_not_named() -> None:
    """The half that makes the report worth reading: naming everyone is the
    same as naming no one."""

    ir = replace(
        _project(),
        metrics=(metric("gross_revenue", expr="amount"), metric("order_count", agg="count")),
        exposures=(
            exposure("ops_board", metrics=("order_count",)),
            exposure("weekly_revenue_review", metrics=("gross_revenue",)),
        ),
    )
    after = replace(ir, metrics=(metric("gross_revenue", expr="amount * qty"), metric("order_count", agg="count")))

    assert plan(ir, after).affected_exposures == ("weekly_revenue_review",)
