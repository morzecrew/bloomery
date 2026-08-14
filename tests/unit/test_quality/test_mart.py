"""The quality mart's IR node (RFC 0016 §5.8): the parts decided *before*
any emitter sees it.

Emission shape lives in ``tests/unit/test_emit/test_quality_mart.py``; what
this module pins is the node itself — it is an ordinary
:class:`~bloomery.ir.MartIR`, it attaches only where there is something to
report, and the one constant it necessarily duplicates across a layer boundary
still agrees with its source.
"""

from __future__ import annotations

import pytest

from bloomery.ir import Additivity, Materialization, ProjectIR
from bloomery.marts import DATE_BUCKETS
from bloomery.quality import (
    QUALITY_MART,
    QUALITY_MEASURE_COLUMNS,
    QUALITY_METRICS,
    QUALITY_RUN_ROLE,
    RunContext,
    attach_quality_mart,
    counted_entities,
    is_quality_mart,
    quality_mart_ir,
)
from bloomery.quality.mart import _DATE_BUCKETS  # noqa: PLC2701 — the pinned duplicate

pytestmark = pytest.mark.unit


def test_the_duplicated_bucket_vocabulary_matches_its_source() -> None:
    """``bloomery.marts`` sits *below* ``bloomery.quality`` in the import
    contract, so the mart module cannot import ``DATE_BUCKETS`` and spells it
    again. A duplicated constant is only safe while something pins it."""
    assert _DATE_BUCKETS == DATE_BUCKETS


def test_the_mart_is_an_ordinary_mart_node() -> None:
    mart = quality_mart_ir()
    assert is_quality_mart(mart)
    assert mart.materialization is Materialization.FULL
    assert mart.joins == ()
    # Every column is a requestable dimension, as for any mart (RFC 0010 §10).
    assert {d.column for d in mart.dimensions} == {c.name for c in mart.columns}
    # The date role expands like an authored one, so RFC 0010 D9 is satisfied
    # by the same mechanism rather than by an exemption.
    assert {f"{QUALITY_RUN_ROLE}_{bucket}" for bucket in DATE_BUCKETS} <= {
        c.name for c in mart.columns
    }


def test_measures_are_the_four_counts_and_never_a_stored_rate() -> None:
    mart = quality_mart_ir()
    assert mart.measures == tuple(sorted(metric for _c, metric in QUALITY_MEASURE_COLUMNS))
    assert "quality_quarantine_rate" not in mart.measures


def test_the_rate_metric_is_non_additive_with_a_ratio() -> None:
    ir = attach_quality_mart(_ir_with_quality())
    rate = next(m for m in ir.metrics if m.name == "quality_quarantine_rate")
    assert rate.additivity is Additivity.NON_ADDITIVE
    assert rate.expr is None  # never a measure — RATIO metric territory
    assert rate.ratio is not None


def _ir_with_quality() -> ProjectIR:
    from support.plan_ir import entity, project, quality_rule

    return project(entities=(entity(quality=(quality_rule(),)),))


def test_a_project_with_nothing_to_report_gains_nothing() -> None:
    empty = ProjectIR()
    assert attach_quality_mart(empty) is empty


def test_a_reconcile_only_project_still_gains_the_mart() -> None:
    """Reconcile checks contribute rows too — their names share the rule-name
    grammar precisely so they can land in the ``rule`` dimension."""
    from decimal import Decimal

    from support.plan_ir import project

    from bloomery.ir import OnFail, ReconcileIR

    ir = project(
        reconcile=(
            ReconcileIR(
                name="totals_match",
                left="sum(order_item.amount) by order_id",
                right="order.total",
                tolerance=Decimal("0.01"),
                on_fail=OnFail.FLAG,
            ),
        )
    )
    attached = attach_quality_mart(ir)
    assert QUALITY_MART in {mart.name for mart in attached.marts}
    assert set(QUALITY_METRICS) <= {metric.name for metric in attached.metrics}


def test_a_step_only_quality_rule_gains_no_mart() -> None:
    """The mart counts rows off `_quality_flags` and the reject table, and a
    step-produced relation has neither: its wrapper writes exactly the
    manifest's declared columns.

    Its one permitted rule kind — `expression` with `on_fail: fail` — lowers to
    a blocking audit that stops the run rather than marking a row, so there is
    nothing evaluated-but-surviving to report. Counting it anyway emitted
    `_quality_flags AS _flags` against a relation with no such column: a gold
    model that compiled clean and failed on its first run.

    `carries_quality` and the emitter's branch loop read one predicate for this
    reason — if the first said yes and the second found nothing, the mart would
    be emitted with no branches to union at all.
    """
    from support.plan_ir import entity, project, quality_rule

    ir = project(entities=(entity(quality=(quality_rule(),), produced_by="resolve@1"),))
    assert counted_entities(ir) == ()
    assert attach_quality_mart(ir) is ir


def test_a_step_output_beside_a_mapped_entity_is_the_only_one_counted() -> None:
    """The mart still exists for the mapped entity — the step output is
    excluded from the count, not allowed to suppress everything else."""
    from support.plan_ir import entity, project, quality_rule

    ir = project(
        entities=(
            entity(name="mapped", quality=(quality_rule(),)),
            entity(name="produced", quality=(quality_rule(),), produced_by="resolve@1"),
        )
    )
    assert [each.name for each in counted_entities(ir)] == ["mapped"]
    assert QUALITY_MART in {mart.name for mart in attach_quality_mart(ir).marts}


def test_attaching_twice_over_distinct_irs_is_a_pure_function() -> None:
    assert attach_quality_mart(_ir_with_quality()) == attach_quality_mart(_ir_with_quality())


def test_the_run_context_defaults_to_declared_but_null() -> None:
    """bloomery never reads a clock, so the default is "the caller fills it" —
    a target opts *in* to a macro it can prove the engine expands."""
    assert RunContext() == RunContext(run_id=None, run_date=None)
