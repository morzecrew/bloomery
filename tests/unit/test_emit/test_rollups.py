"""The aggregate body a rollup mart is built from (RFC 0058 §5.3, P2).

Rendered here rather than only through a golden, because two of the three
things this lowering decides are refusals, and a golden only ever shows the
case that worked. What it *does* show — and what the golden is for — is that
the emitted model is an ordinary derived one.
"""

from __future__ import annotations

from typing import cast

import pytest

from bloomery.emit.base import EmitContext
from bloomery.emit.lower import ROLLUP_AGGREGATES, rollup_measures, rollup_select
from bloomery.guardrails.additivity import _REAGGREGABLE
from bloomery.errors import UnsupportedByTarget
from bloomery.ir import Additivity, MetricIR, ProjectIR, Ratio, RollupIR, SqlExpr
from bloomery.naming import DefaultNaming

pytestmark = pytest.mark.unit


class _PassThrough:
    """A dialect that renders SQLGlot's default. The body is dialect-neutral —
    a projection, a FROM and a GROUP BY — so nothing here needs a real port."""

    def render(self, expression: object) -> str:
        return expression.sql()  # type: ignore[attr-defined]


def _ctx() -> EmitContext:
    return EmitContext(
        dialect=cast("object", _PassThrough()),  # type: ignore[arg-type]
        naming=DefaultNaming(),
        fingerprint="blm1:test",
    )


def _metric(name: str, *, agg: str | None = "sum", expr: str | None = "amount") -> MetricIR:
    return MetricIR(
        name=name,
        grain="order_item",
        additivity=Additivity.ADDITIVE,
        agg=agg,
        expr=SqlExpr(expr) if expr is not None else None,
        ratio=None,
        semi_additive=None,
    )


def _rollup(*measures: str) -> RollupIR:
    return RollupIR(name="monthly", of="items", keep=("ordered_month",), measures=measures)


def _project(*metrics: MetricIR) -> ProjectIR:
    return ProjectIR(metrics=tuple(sorted(metrics, key=lambda m: m.name)))


# ....................... #


def test_the_body_groups_the_parent_by_the_kept_columns() -> None:
    sql = rollup_select(_rollup("revenue"), _project(_metric("revenue")), _ctx()).sql()

    assert sql == (
        "SELECT ordered_month, SUM(amount) AS revenue "
        "FROM gold.mart_items GROUP BY ordered_month"
    )


@pytest.mark.parametrize(
    ("agg", "rendered"),
    [("count", "COUNT(amount)"), ("max", "MAX(amount)"), ("min", "MIN(amount)"),
     ("sum", "SUM(amount)")],
)  # fmt: skip
def test_every_aggregate_a_rollup_builds_renders_as_itself(agg: str, rendered: str) -> None:
    """All four of `ROLLUP_AGGREGATES`, not just the one the fixture uses.

    Only `sum` was rendered anywhere, so three of the four mappings produced
    SQL nothing asserted — and a swap between `min` and `max` is precisely the
    failure D5 refuses to approximate: a rollup holding the wrong extreme
    answers quickly, plausibly and wrongly.
    """

    sql = rollup_select(_rollup("m"), _project(_metric("m", agg=agg)), _ctx()).sql()

    assert sql == (
        f"SELECT ordered_month, {rendered} AS m FROM gold.mart_items GROUP BY ordered_month"
    )


def test_a_computed_measure_is_not_a_column() -> None:
    """A ratio is recomputed from its operands at query time and is never a
    stored number, so a column for it would be the materialized quotient
    RFC 0038 D2 exists to prevent. R013 has already required that the rollup
    carry the operands, so what is dropped is only the arithmetic."""

    aov = MetricIR(
        name="aov",
        grain="order_item",
        additivity=Additivity.RATIO,
        agg=None,
        expr=None,
        ratio=Ratio(numerator="revenue", denominator="lines"),
        semi_additive=None,
    )
    project = _project(_metric("revenue"), _metric("lines", agg="count", expr="line_no"), aov)

    assert [m.name for m in rollup_measures(_rollup("aov", "lines", "revenue"), project)] == [
        "lines",
        "revenue",
    ]


def test_a_measure_that_is_not_a_metric_is_skipped() -> None:
    """`rollup_measures` reads the project by name and a rollup that reached
    the IR carries only measures its parent stores, so this cannot happen
    through the pipeline. It is a lookup, and a lookup that raises on a
    missing key would turn a rendering into a second guardrail."""

    assert rollup_measures(_rollup("ghost"), _project(_metric("revenue"))) == ()


def test_a_measure_with_no_aggregation_is_refused() -> None:
    """R013 refuses this before emission (`nothing_to_aggregate`), so the guard
    here is the module's own — the same shape the Cube and MetricFlow emitters
    keep for a metric they cannot lower."""

    project = _project(_metric("revenue", agg=None))

    with pytest.raises(UnsupportedByTarget, match="no aggregation to build a rollup measure"):
        rollup_select(_rollup("revenue"), project, _ctx())


def test_an_aggregation_a_rollup_cannot_build_is_refused() -> None:
    """`count_distinct` is the one that matters and it is absent by decision:
    summing per-group distinct counts double-counts, R013 refuses a
    `distinct_count` measure for exactly that reason, and a mapping here would
    be a second answer to a settled question."""

    assert "count_distinct" not in ROLLUP_AGGREGATES

    project = _project(_metric("revenue", agg="count_distinct"))

    with pytest.raises(UnsupportedByTarget, match="which a rollup has no way to build"):
        rollup_select(_rollup("revenue"), project, _ctx())


def test_the_aggregates_a_rollup_builds_are_the_ones_an_additive_claim_survives() -> None:
    """One list, asserted rather than remembered (logs/T-0035.md).

    `ROLLUP_AGGREGATES` held five, copied from the list `reconcile` gives a
    mart assertion on the grounds that two lists meaning the same thing drift.
    They do not mean the same thing: an assertion computes one number over rows
    a relation already holds and any aggregate is honest about those, while a
    rollup re-aggregates and only some survive it. The copy mapped `avg`, which
    nothing can reach — the additivity guardrail refuses an `additive` claim
    over it and R013 admits no other class — and so said, in the one place a
    reader looks, that a rollup can average.

    A comment asking the next reader to keep the two in step is what this
    replaces: the guardrail's list is the authority, and this fails if either
    moves without the other.
    """

    assert set(ROLLUP_AGGREGATES) == set(_REAGGREGABLE)
