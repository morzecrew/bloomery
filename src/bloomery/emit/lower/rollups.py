"""Rollup lowering: the aggregate body a rollup mart is built from
(RFC 0058 §5.3, P2).

``SELECT <keep…>, <agg>(<expr>) AS <measure> … FROM <gold parent> GROUP BY
<keep…>`` — one shared body, because SQLMesh and dbt build the same relation
and two renderings of one aggregate would disagree the first time either
changed.

This is the first place a **measure** is aggregated at build time. Models have
aggregated before — the quality mart counts rule evaluations, a reconcile model
compares two totals — but a metric has always been aggregated at query time, by
the planner or by the engine reading the semantic layer, and a wide mart
projects columns at its base grain. A rollup moves that into the build, which
is exactly why the obligation had to exist before this emitter: from here the
safety condition is invisible, and the SQL below is correct-looking whatever it
aggregates.

What is *not* here is any decision about whether a rollup may be read. Row 14
keeps it out of ``measure_owners`` and the covering-mart search by putting it
in its own IR collection; this module renders a relation and chooses nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlglot import exp

from bloomery.errors import UnsupportedByTarget
from bloomery.ir import COMPUTED, Layer

if TYPE_CHECKING:
    from bloomery.emit.base import EmitContext
    from bloomery.ir import MetricIR, ProjectIR, RollupIR

# ----------------------- #

__all__ = [
    "ROLLUP_AGGREGATES",
    "rollup_measures",
    "rollup_select",
]

#: Metric ``agg`` → the SQL aggregate a rollup builds it with. Deliberately the
#: same five :mod:`bloomery.emit.lower.reconcile` gives a mart assertion: both
#: compute one number over a column of a gold relation, and two lists that mean
#: the same thing drift.
#:
#: ``count_distinct`` is absent rather than mapped. It is the aggregate whose
#: whole problem is that summing per-group results double-counts, R013 refuses
#: a ``distinct_count`` measure on a rollup for exactly that reason, and a
#: mapping here would be a second answer to a question already settled.
ROLLUP_AGGREGATES: dict[str, type[exp.AggFunc]] = {
    "avg": exp.Avg,
    "count": exp.Count,
    "max": exp.Max,
    "min": exp.Min,
    "sum": exp.Sum,
}


def rollup_measures(rollup: RollupIR, ir: ProjectIR) -> tuple[MetricIR, ...]:
    """The measures a rollup **stores**, in name order.

    A :data:`~bloomery.ir.COMPUTED` metric is skipped, the way both semantic
    emitters skip it: a ratio is recomputed from its operands at query time and
    is never a stored number, so a column for it here would be the materialized
    quotient RFC 0038 D2 exists to prevent. R013 has already required that the
    rollup carry those operands, so what it drops is only the arithmetic.
    """

    by_name = {metric.name: metric for metric in ir.metrics}

    return tuple(
        by_name[name]
        for name in rollup.measures
        if name in by_name and by_name[name].additivity not in COMPUTED
    )


# ....................... #


def _aggregate(metric: MetricIR) -> exp.AggFunc:
    if metric.agg is None or metric.expr is None:
        msg = (
            f"metric {metric.name!r} has no aggregation to build a rollup measure from — "
            "only agg-over-expr metrics become rollup columns (RFC 0058 §5.3)"
        )
        raise UnsupportedByTarget(msg)

    aggregate = ROLLUP_AGGREGATES.get(metric.agg)

    if aggregate is None:
        msg = (
            f"metric {metric.name!r} uses aggregation {metric.agg!r}, which a rollup has no "
            f"way to build; supported: {sorted(ROLLUP_AGGREGATES)}"
        )
        raise UnsupportedByTarget(msg)

    return aggregate(this=metric.expr.ast())


# ....................... #


def rollup_select(rollup: RollupIR, ir: ProjectIR, ctx: EmitContext) -> exp.Select:
    """The aggregate SELECT: the parent mart grouped by the kept columns.

    ``keep`` is sorted on :class:`~bloomery.ir.RollupIR`, so the projection and
    the ``GROUP BY`` are in one deterministic order and cannot disagree with
    each other.
    """

    namespace, relation = ctx.naming.relation(rollup.of, Layer.GOLD)
    kept = [exp.column(column) for column in rollup.keep]

    return (
        exp.Select()
        .select(
            *kept,
            *[
                exp.alias_(_aggregate(metric), metric.name)
                for metric in rollup_measures(rollup, ir)
            ],
        )
        .from_(exp.table_(relation, db=namespace))
        .group_by(*kept)
    )
