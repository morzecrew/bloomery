"""The additivity guard (RFC 0006 §5.4, D6, D11).

Checked over ``MetricIR.additivity`` on the draft IR:

- A ``non_additive`` metric declared without a ``ratio``, a ``derived:`` block
  (RFC 0034 D1), or an equivalent additive decomposition — an expression over
  additive dependencies — is
  :class:`~bloomery.errors.NonAdditiveWithoutComponents`: with nothing
  additive to recompute from at query time, the metric could only ever be
  answered by storing it, which the next rule forbids.
- A ``non_additive`` metric may **never** materialize as a stored number. At
  M4 the only place that could arise is an entity column sharing the metric's
  name — a stored :class:`~bloomery.errors.AdditivityViolation`; emitters
  re-refuse independently (RFC 0008), defense in depth.
- A ``semi_additive`` metric aggregates only over dimensions *other than* its
  ``over:`` dimension: a missing ``semi_additive: {over, rule}`` policy makes
  the invariant unenforceable, and an expression that explicitly aggregates
  the ``over`` dimension away violates it directly — both
  :class:`~bloomery.errors.AdditivityViolation`. The query-time lowering of
  ``rule`` is RFC 0011's, not this stage's (D11).
- An ``additive`` metric must be telling the truth (RFC 0038 D1/D2). Until
  then the word was taken on trust — the two rules above inspect only metrics
  declared ``non_additive`` or ``semi_additive``, so a false ``additive``
  claim was the one declaration nothing read. Two shapes are decidable from
  the spec alone and both are :class:`~bloomery.errors.FalseAdditivityClaim`:
  an ``avg`` re-averaged, and a measure summed across the very axis its origin
  grain is taken along.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from sqlglot import exp

from bloomery.errors import (
    AdditivityViolation,
    FalseAdditivityClaim,
    GuardrailError,
    InvariantViolated,
    NonAdditiveWithoutComponents,
)
from bloomery.ir import Additivity
from bloomery.semantic import grain_of
from bloomery.typing import DateType, TimestampType

if TYPE_CHECKING:
    from bloomery.ir import EntityIR, MetricIR, ProjectIR, SqlExpr

# ----------------------- #

__all__ = [
    "check_additivity",
]


def _has_decomposition(metric: MetricIR) -> bool:
    """A decomposition the planner can recompute the metric from (RFC 0011 D5):
    an expression over declared dependencies, or the ``derived:`` block that
    generalizes exactly that shape (RFC 0034 D1).

    ``derived:`` needs no ``depends_on`` test of its own — the template merge
    unions its inputs into ``requires_metrics``, so a derived metric always has
    the edges, and its own guard refuses one whose expression references an
    alias the inputs do not declare.
    """

    return metric.derived is not None or (metric.expr is not None and metric.depends_on != ())


# ....................... #


def _aggregates_over(expr: SqlExpr, dimension: str) -> bool:
    return any(
        col.name == dimension
        for agg in expr.ast().find_all(exp.AggFunc)
        for col in agg.find_all(exp.Column)
    )


# ....................... #


def _check_non_additive(metric: MetricIR, draft: ProjectIR, path: str) -> list[GuardrailError]:
    violations: list[GuardrailError] = []

    if metric.ratio is None and not _has_decomposition(metric):
        msg = (
            f"metric {metric.name!r} is non_additive but declares neither a ratio, a "
            "derived: block, nor an additive decomposition — there is nothing additive to "
            "recompute it from at query time, so it could only ever be answered by storing "
            "it, which is forbidden (RFC 0006 §5.4). Fix: add ratio: {numerator, "
            "denominator} naming its additive components, a derived: expression over other "
            "metrics, or an expr over additive dependencies"
        )
        violations.append(NonAdditiveWithoutComponents(msg, source_path=path))

    stored = sorted(
        entity.name
        for entity in draft.entities
        for column in entity.columns
        if column.name == metric.name
    )

    if stored:
        msg = (
            f"metric {metric.name!r} is non_additive and may not be materialized as a "
            f"stored number, but entity {stored[0]!r} stores a column of that name — a "
            "stored average re-aggregates wrongly (RFC 0006 D6). Fix: store the additive "
            "components and rename either the column or the metric; the ratio is a "
            "calculated measure at query time"
        )
        violations.append(AdditivityViolation(msg, source_path=path))

    return violations


# ....................... #


def _check_semi_additive(metric: MetricIR, path: str) -> list[GuardrailError]:
    if metric.semi_additive is None:
        msg = (
            f"metric {metric.name!r} is semi_additive but declares no semi_additive: "
            "{over, rule} policy — without the over: dimension the only-aggregate-over-"
            "other-dimensions invariant is unenforceable (RFC 0006 D11). Fix: add "
            "semi_additive: {over: <date dimension>, rule: last|first|avg|min|max}"
        )
        return [AdditivityViolation(msg, source_path=path)]

    over = metric.semi_additive.over.dimension

    if metric.expr is not None and _aggregates_over(metric.expr, over):
        msg = (
            f"metric {metric.name!r} is semi_additive over {over!r} but its expr "
            f"aggregates {over!r} away — a semi_additive metric may only be aggregated "
            "over dimensions other than its over: dimension (RFC 0006 D6). Fix: remove "
            f"the aggregation of {over!r}; the over-dimension rule "
            f"({metric.semi_additive.rule}) is applied at query time"
        )
        return [AdditivityViolation(msg, source_path=path)]

    return []


# ....................... #


#: Aggregations that **provably re-aggregate**, and the only ones an
#: ``additive`` claim is accepted over. An allowlist rather than a denylist,
#: because ``agg`` is a free string — nothing validates it against a
#: vocabulary — so a denylist blesses every spelling it has not heard of,
#: including typos and engine-specific names bloomery cannot reason about.
#:
#: The line is not idempotence but whether *any* rollup operator over the
#: stored value exists: ``sum``, ``min`` and ``max`` roll up under themselves,
#: and ``count`` rolls up under ``sum`` — the total is the sum of the counts.
#: An average, a median and a distinct count leave nothing to roll up from.
_REAGGREGABLE: Final = ("sum", "min", "max", "count")

#: Aggregations that accumulate magnitude across rows, and so are the ones a
#: snapshot's repeated state actually corrupts. ``min``, ``max`` and ``count``
#: over a snapshot are honest questions — the lowest balance in the period,
#: the number of account-days — and refusing them would be telling an author
#: to declare a restriction their query does not need.
_ACCUMULATING: Final = ("sum",)

#: How to repair an additive claim, per aggregation. The default is for an
#: aggregation bloomery does not recognise, where the honest thing to say is
#: that it cannot verify the claim rather than that the claim is false.
_REMEDIES: Final = {
    "avg": (
        "declare the additive components and let the quotient be calculated at query "
        "time — additivity: non_additive with ratio: {numerator, denominator} naming them"
    ),
    "median": (
        "a median has no additive decomposition, so there is nothing to recompute it "
        "from — keep it at its own grain, or declare additivity: non_additive with a "
        "derived: block if one exists"
    ),
    "count_distinct": (
        "a distinct count cannot be summed across groups without double-counting an "
        "entity present in several — keep it at its own grain, or declare additivity: "
        "non_additive with a derived: block if one exists"
    ),
}

_UNKNOWN_REMEDY = (
    "bloomery cannot verify that this aggregation re-aggregates, and will not accept an "
    f"additive claim it cannot check — the ones it knows are {', '.join(_REAGGREGABLE)}. "
    "If this aggregation does roll up, that is a gap worth reporting; if it does not, "
    "declare additivity: non_additive with a ratio: or derived: decomposition"
)


def _check_average(metric: MetricIR, path: str) -> list[GuardrailError]:
    """An ``additive`` claim is accepted only over an aggregation whose rollup
    is known to be sound (RFC 0038 D2).

    ``AVG(AVG(x))`` weights each group equally instead of each row, so a
    re-aggregated average is wrong wherever the groups differ in size — which
    is every real dataset. D2 is the general statement: a ratio is stored as
    its operands, never as the materialized quotient, because the quotient
    cannot be rolled up and looks exactly like a number that can.

    An ``agg`` of ``None`` is not judged here: a metric with no aggregation of
    its own has no rollup to be wrong about, and its shape is
    ``check_metrics``' business.
    """

    if metric.agg is None or metric.agg in _REAGGREGABLE:
        return []

    msg = (
        f"metric {metric.name!r} declares additivity: additive with agg: {metric.agg}, "
        "which bloomery does not accept an additive claim over (RFC 0038 D2). Fix: "
        f"{_REMEDIES.get(metric.agg, _UNKNOWN_REMEDY)}"
    )

    return [FalseAdditivityClaim(msg, source_path=path)]


# ....................... #


def _check_snapshot(
    metric: MetricIR, entity: EntityIR, draft: ProjectIR, path: str
) -> list[GuardrailError]:
    """A measure is not additive along the axis its own grain is taken over
    (RFC 0038 D1).

    The origin grain is the entity's key, read through the grain model so that
    "what the grain is" keeps one definition rather than growing a second,
    weaker one here (RFC 0037). A temporal determinant in that key means each
    row is a *snapshot* — one row per account per day — and summing across the
    axis adds every day's copy of the same money. Additive across the other
    determinants, and not across this one, is exactly what ``semi_additive``
    says, which is why that is what the message asks for.

    **Only an accumulating aggregation is at risk.** A ``min``, ``max`` or
    ``count`` over a snapshot asks an honest question — the lowest balance in
    the period, the number of account-days — and none of them is corrupted by
    the same state appearing on many days. Only ``sum`` adds the repeated
    magnitude, so only ``sum`` is refused.

    **A temporal key column is not enough on its own either** (see
    logs/T-0019.md, D-107). An entity keyed ``(payment_id, paid_at)`` is one row per payment:
    ``paid_at`` is functionally dependent on ``payment_id`` and the key is
    merely redundant, so there is no axis to be non-additive over — and telling
    that author to declare ``semi_additive`` would assert a rollup axis that
    does not exist. Nothing in the key distinguishes the two shapes, so the
    check asks the question §6 actually poses: is the axis *exposed for
    rollup*? A mart carrying this measure and flattening the column as a date
    dimension is what exposes it, and is what makes the wrong number reachable
    in the first place. Where no mart does, nothing can be summed across
    anything yet and there is no false claim to catch.
    """

    if metric.agg not in _ACCUMULATING:
        return []

    determinants = {d.column for d in grain_of(entity.name, entity.key).determinants}
    temporal = tuple(
        column.name
        for column in entity.columns  # sorted by name on EntityIR
        if column.name in determinants and isinstance(column.type, DateType | TimestampType)
    )

    exposed = tuple(
        column
        for column in temporal
        for mart in draft.marts
        if metric.name in mart.measures
        and any(dimension.column == column for dimension in mart.dimensions)
    )

    if not exposed:
        return []

    over = exposed[0]
    msg = (
        f"metric {metric.name!r} declares additivity: additive, but its grain "
        f"{entity.name!r} is one row per {', '.join(entity.key)} — {over!r} is part of "
        "that key, so each row is a point-in-time snapshot and summing across "
        f"{over!r} adds the same value once per period (RFC 0038 D1). Fix: additivity: "
        f"semi_additive with semi_additive: {{over: {over}, rule: last|first|avg|min|max}}, "
        f"which stays additive across {', '.join(k for k in entity.key if k != over) or 'the other determinants'}"
    )

    return [FalseAdditivityClaim(msg, source_path=path)]


# ....................... #


def _check_additive(metric: MetricIR, draft: ProjectIR, path: str) -> list[GuardrailError]:
    """``additivity: additive`` is a claim; these are the two shapes of it that
    are false and decidable without a planner (RFC 0038 D1/D2)."""

    violations = _check_average(metric, path)

    entity = next((e for e in draft.entities if e.name == metric.grain), None)
    if entity is not None:
        violations.extend(_check_snapshot(metric, entity, draft, path))

    return violations


# ....................... #


def check_additivity(draft: ProjectIR) -> list[GuardrailError]:
    """Every additivity violation across the draft's metrics."""
    violations: list[GuardrailError] = []

    for metric in draft.metrics:
        path = f"metrics: metrics.{metric.name}"
        if metric.additivity is Additivity.NON_ADDITIVE:
            violations.extend(_check_non_additive(metric, draft, path))
        elif metric.additivity is Additivity.SEMI_ADDITIVE:
            violations.extend(_check_semi_additive(metric, path))
        elif metric.additivity is Additivity.ADDITIVE:
            violations.extend(_check_additive(metric, draft, path))
        else:  # pragma: no cover — `RESOLVABLE` is what keeps this unreachable
            # RFC 0038 D1 closed the enum at six while resolution mints three,
            # and the three it does not mint have no rule here yet. Raising
            # rather than falling through is the whole point (logs/T-0019.md,
            # D-105): a silent `else` would hand a SNAPSHOT metric the
            # additive checks, which are written for a different meaning, and
            # nothing would say so.
            msg = (
                f"metric {metric.name!r} resolved to additivity "
                f"{metric.additivity.value!r}, which no project can currently declare — "
                "bloomery.ir.RESOLVABLE names the three that can, and the guard that "
                "asserts it should have failed before this did (RFC 0038 D1)"
            )
            raise InvariantViolated(msg)

    return violations
