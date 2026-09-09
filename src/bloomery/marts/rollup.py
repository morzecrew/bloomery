"""Rollup lowering: ``lower_rollups(mart_set, draft) -> RollupLowering``
(RFC 0058 §5.2, P2).

A rollup is a mart at a coarser grain than one this project already builds.
This module resolves each declared one against the parent it names and, for
every measure it would carry, asks the obligation R013 states — and refuses
where the obligation does not discharge (D5, `LOCKED`).

Total, like :mod:`bloomery.marts.flatten`: it never raises. A rollup with any
violation contributes no :class:`~bloomery.ir.RollupIR` and its leaves batch
into the guardrail stage's single aggregate, so an author fixes a marts
document in one round-trip.

**Nothing here decides whether a rollup is *used*.** Row 14 (`LOCKED`) says a
rollup is never a measure owner and never a covering mart, and it holds because
:class:`~bloomery.ir.RollupIR` lands in ``ProjectIR.rollups`` rather than in
``ProjectIR.marts`` — the collection ``measure_owners`` and the planner's
covering-mart search both walk. There is no filter to keep in step here;
choosing to read a rollup instead of the detail is RFC 0040's job (§4).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from bloomery.errors import UnprovableRollup
from bloomery.ir import Materialization, RollupIR, partition_specs
from bloomery.semantic import Refutation, prove_mart_rollup

if TYPE_CHECKING:
    from bloomery.errors import GuardrailError
    from bloomery.ir import MartIR, MetricIR, ProjectIR
    from bloomery.spec.marts import MartSet, RollupMart

# ----------------------- #

__all__ = [
    "RollupLowering",
    "lower_rollups",
]


@dataclass(frozen=True, slots=True)
class RollupLowering:
    """The rollup resolver's product: cleanly lowered rollups (sorted by name)
    and every violation found, as guardrail leaves for the stage aggregate."""

    rollups: tuple[RollupIR, ...]
    violations: tuple[GuardrailError, ...]


# ....................... #


def _not_on_the_parent(
    name: str, rollup: RollupMart, parent: MartIR, path: str
) -> UnprovableRollup | None:
    """A measure the parent does not carry.

    Asked here rather than left to R013, because the obligation is asked with
    the rollup's own measure list and would therefore find every one of them
    "carried". A rollup aggregates the rows of one relation, and a measure that
    relation does not store is not one of them.
    """

    absent = tuple(sorted(set(rollup.measures) - set(parent.measures)))

    if not absent:
        return None

    msg = (
        f"rollup {name!r} carries {', '.join(absent)}, which mart {parent.name!r} does not. "
        "A rollup aggregates the rows of the mart it names, so it can only carry measures "
        f"that mart stores (RFC 0058 §5.2). Fix: name the measure among {parent.name!r}'s "
        "measures, or drop it from the rollup"
    )

    return UnprovableRollup(msg, source_path=f"{path}.measures")


# ....................... #


def _refused(name: str, answer: Refutation, path: str) -> UnprovableRollup:
    """R013's refutation, as the guardrail leaf an author reads.

    The rendered proof form is not used: a refutation renders over several
    lines and every other leaf in this stage is one sentence, so the aggregate
    would read as two formats. What is kept is everything the four lines carry — the
    obligation, the reason code and the fix — in the shape
    ``resolve.build`` already uses for R009's refusal.
    """

    obligation = answer.obligations[0]
    fix = f" Fix: {answer.remediation}" if answer.remediation else ""

    msg = (
        f"rollup {name!r} is not provable: {obligation.found} (required: "
        f"{obligation.required}). A rollup is read instead of the detail table, so an "
        "unprovable one answers quickly and plausibly rather than failing (RFC 0058 D5, "
        f"R013, {answer.reason}).{fix}"
    )

    return UnprovableRollup(msg, source_path=path)


# ....................... #


def _dropped_declaration(
    name: str, measure: str, metric: MetricIR, path: str
) -> UnprovableRollup | None:
    """A measure whose declaration a rollup's aggregate would silently drop.

    R013 asks the aggregation-class question and gets it right; two other
    declarations reach the same measure and neither is a class. A ``filter:``
    restricts the rows a metric aggregates, and a rollup's ``SUM(expr)`` over
    the parent aggregates all of them — the unrestricted number, under the
    restricted metric's name. A ``cumulative:`` window accumulates across rows
    at query time and is not an aggregate a ``GROUP BY`` can stand in for.

    Refused here rather than folded into R013 because both are questions about
    what an emitted aggregate can *carry*, and R013 is about whether the
    arithmetic is sound. Supporting the first means a third rendering of the
    metric-filter grammar — after Cube's and MetricFlow's — and
    ``metric_filter_sql`` says in its own docstring that two copies of an
    escaping rule is the defect this project keeps finding in itself
    (logs/T-0034.md).
    """

    dropped = (
        "a filter:, which restricts the rows it aggregates"
        if metric.filter
        else "a cumulative: window, which accumulates across rows at query time"
        if metric.cumulative is not None
        else ""
    )

    if not dropped:
        return None

    msg = (
        f"rollup {name!r} carries {measure!r}, which declares {dropped}. A rollup builds its "
        "measure with one aggregate over the parent's rows, so the declaration would be "
        "dropped and the column would hold a number that is not the metric it is named after "
        f"(RFC 0058 D5). Fix: leave {measure!r} off the rollup and request it at the grain it "
        "is declared for"
    )

    return UnprovableRollup(msg, source_path=f"{path}.measures")


# ....................... #


def lower_rollups(mart_set: MartSet | None, draft: ProjectIR) -> RollupLowering:
    """Resolve every declared rollup against the parent it names (RFC 0058 P2).

    Total — never raises. A project with no marts document, or one whose marts
    are all wide, lowers to the empty tuple.

    A rollup whose parent is absent from ``draft.marts`` is **skipped in
    silence**, and that is not a hole: the spec layer already refuses a
    ``rollup_of`` naming a mart this document does not declare, so the only way
    to arrive here is a parent that failed to lower. Its own violation is in
    the same aggregate and is the actionable one; a second leaf saying the
    rollup could not be checked would send an author to the rollup.
    """

    if mart_set is None:
        return RollupLowering(rollups=(), violations=())

    parents = {mart.name: mart for mart in draft.marts}
    rollups: list[RollupIR] = []
    violations: list[GuardrailError] = []

    for name in sorted(mart_set.rollups):
        rollup = mart_set.rollups[name]
        parent = parents.get(rollup.of)

        if parent is None:
            continue

        # `rollups.<name>`, not `marts.<name>`: a source path addresses the
        # authored document (RFC 0002 §5.3), and a rollup is authored under its
        # own key. Sending an author to `marts.monthly` when they wrote
        # `rollups: monthly` is the same defect that ruled out putting a rollup
        # in `marts:` as a discriminated union — a path naming a key nobody
        # wrote (logs/T-0034.md).
        path = f"marts: rollups.{name}"
        missing = _not_on_the_parent(name, rollup, parent, path)

        if missing is not None:
            violations.append(missing)
            continue

        # The parent restricted to the measures this rollup takes. A rollup may
        # carry a subset — that is the point of declaring `measures:` at all,
        # since a mart with one `distinct_count` would otherwise have no
        # provable rollup — and R013 is asked about what the rollup carries
        # (§5.2), not about what the parent does.
        carried = replace(parent, measures=tuple(sorted(rollup.measures)))
        answer = prove_mart_rollup(carried, rollup.keep, draft)

        if isinstance(answer, Refutation):
            violations.append(_refused(name, answer, path))
            continue

        by_name = {metric.name: metric for metric in draft.metrics}
        dropped = tuple(
            leaf
            for measure in sorted(rollup.measures)
            if (leaf := _dropped_declaration(name, measure, by_name[measure], path)) is not None
        )

        if dropped:
            violations.extend(dropped)
            continue

        rollups.append(
            RollupIR(
                name=name,
                of=rollup.of,
                keep=tuple(sorted(set(rollup.keep))),
                measures=tuple(sorted(rollup.measures)),
                partition_by=partition_specs(rollup.partition_by),
                materialization=(
                    Materialization.FULL
                    if rollup.materialization is None
                    else Materialization(rollup.materialization)
                ),
            )
        )

    return RollupLowering(rollups=tuple(rollups), violations=tuple(violations))
