"""The metric-shape guard (RFC 0034 D5, D7, D9) — the refusals the four
time- and filter-shaped metric forms need.

Everything here is decidable from the draft IR, and every failure is a *model*
error rather than a target's inability: a metric that declares two mutually
exclusive shapes, an expression naming an input that does not exist, a filter
on a dimension no mart flattens. Each one would otherwise reach a semantic
emitter as an invalid manifest or — worse — compile clean and answer with a
number nobody asked for.

This replaces the blanket ``cumulative:`` refusal that stood while nothing
lowered it (RFC 0002 D10). The refusal was right for as long as it held; what
survives it is narrower and named per case, because "reserved surface" is no
longer why any of these fail.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from sqlglot import exp

from bloomery.errors import (
    GuardrailError,
    InvalidMetricShape,
    MetricFilterInvalid,
    guaranteed,
)
from bloomery.ir import Additivity
from bloomery.typing import (
    BoolType,
    DateType,
    DecimalType,
    IntType,
    StringType,
    TimestampType,
)

if TYPE_CHECKING:
    from bloomery.ir import MartIR, MetricFilterIR, MetricIR, ProjectIR
    from bloomery.typing import LogicalType

# ----------------------- #

__all__ = [
    "check_metrics",
]

#: ISO date/timestamp carriers, the spelling every temporal filter value takes
#: by the time it reaches the IR (``resolve.build._metric_filters``). Reusing
#: the quality layer's grammar would mean importing a sibling module for one
#: regex; the two are checked against the same corpus by the type-conformance
#: tier.
_ISO_DATE_LENGTH = 10


def _fits(value: str | int | bool | Decimal, declared: LogicalType) -> bool:
    """Whether one filter value can be compared against a column of this type
    without a cast (RFC 0013 D8's rule, applied at compile time).

    ``str`` is the carrier for decimals YAML would round and for temporals the
    IR has no tag for, so it is accepted against a numeric or temporal column
    only when it parses as one — never as an implicit cast of arbitrary text.
    """

    if isinstance(declared, BoolType):
        return isinstance(value, bool)

    # ``bool`` is an ``int`` subclass, and a boolean against a numeric column
    # is an authoring mistake rather than a narrowing.
    if isinstance(value, bool):
        return False

    if isinstance(declared, IntType):
        return isinstance(value, int)

    if isinstance(declared, DecimalType):
        if isinstance(value, (int, Decimal)):
            return True
        try:
            return Decimal(value).is_finite()
        except InvalidOperation:
            return False

    if isinstance(declared, StringType):
        return isinstance(value, str)

    if isinstance(declared, (DateType, TimestampType)):
        if not isinstance(value, str):
            return False
        head = value[:_ISO_DATE_LENGTH]
        return len(head) == _ISO_DATE_LENGTH and head.count("-") == 2

    return False  # pragma: no cover — the logical-type set is closed


# ....................... #


def _check_filter(
    metric: MetricIR, clause: MetricFilterIR, mart: MartIR, path: str
) -> list[GuardrailError]:
    """One filter clause against one mart carrying the metric (RFC 0034 D9)."""

    categorical = {
        dimension.column: dimension for dimension in mart.dimensions if dimension.ref.role is None
    }

    if clause.dimension not in categorical:
        roles = sorted(
            dimension.column for dimension in mart.dimensions if dimension.ref.role is not None
        )
        if clause.dimension in roles:
            msg = (
                f"metric {metric.name!r} filters on date-role dimension "
                f"{clause.dimension!r}. A metric restricted to a fixed period is a "
                "constant, not a metric — express the time relation as cumulative: "
                "{window|grain_to_date} or as a derived metric with an offset: "
                "(RFC 0034)"
            )
            return [MetricFilterInvalid(msg, source_path=path)]

        known = sorted(categorical)
        msg = (
            f"metric {metric.name!r} filters on {clause.dimension!r}, which mart "
            f"{mart.name!r} does not flatten as a categorical dimension; known: {known}. "
            "Fix: flatten the column onto the mart, or filter on one it already carries"
        )
        return [MetricFilterInvalid(msg, source_path=path)]

    if clause.op == "is_null":
        return []

    declared = guaranteed(
        (column.type for column in mart.columns if column.name == clause.dimension),
        expected=f"a column backing dimension {clause.dimension!r} of mart {mart.name!r}",
        by="the mart flattener, which builds every dimension from a column it flattened",
    )
    unfit = [value for value in clause.values if not _fits(value, declared)]

    if unfit:
        msg = (
            f"metric {metric.name!r} filters {clause.dimension!r} "
            f"({type(declared).__name__}) against {unfit!r}, which does not fit the "
            "column's declared type — filter values are never cast (RFC 0013 D8). "
            "Fix: write the value in the column's own type"
        )
        return [MetricFilterInvalid(msg, source_path=path)]

    return []


# ....................... #


def _check_shape(metric: MetricIR, path: str) -> list[GuardrailError]:
    """The metric's own declaration, read against itself (RFC 0034 D5–D7)."""

    violations: list[GuardrailError] = []

    if metric.cumulative is not None and metric.derived is not None:
        msg = (
            f"metric {metric.name!r} declares both derived: and cumulative:. A derived "
            "metric has no measure of its own and a cumulative window accumulates one, "
            "so the two name mutually exclusive shapes (RFC 0034 D7). Fix: accumulate a "
            "simple metric, then derive from *it*"
        )
        violations.append(InvalidMetricShape(msg, source_path=path))

    if metric.derived is not None and metric.additivity is not Additivity.NON_ADDITIVE:
        msg = (
            f"metric {metric.name!r} is derived: but declares additivity "
            f"{metric.additivity.value!r}. A derived metric has no measure to aggregate — "
            "it is recomputed from its inputs at query time, which is what non_additive "
            "means (RFC 0011 D5). Fix: additivity: non_additive"
        )
        violations.append(InvalidMetricShape(msg, source_path=path))

    if metric.cumulative is not None and metric.additivity is Additivity.NON_ADDITIVE:
        msg = (
            f"metric {metric.name!r} is cumulative: but non_additive, so it has no measure "
            "to accumulate. The additivity describes the measure and the window describes "
            "how it accumulates (RFC 0034 D6). Fix: declare the aggregation this "
            "accumulates — agg:/expr: with an additive or semi_additive additivity"
        )
        violations.append(InvalidMetricShape(msg, source_path=path))

    if metric.derived is not None and metric.filter:
        msg = (
            f"metric {metric.name!r} is derived: and carries filter:. A derived metric's "
            "rows are its inputs' rows, so a filter here restricts measures one level "
            "down rather than the metric it is written on — a post-aggregate filter, "
            "which bloomery does not express (RFC 0034 §9). Fix: filter the input "
            "metrics and derive from the filtered ones"
        )
        violations.append(InvalidMetricShape(msg, source_path=path))

    violations.extend(_check_aliases(metric, path))

    return violations


# ....................... #


def _check_aliases(metric: MetricIR, path: str) -> list[GuardrailError]:
    """A derived expression references exactly its declared aliases.

    Both directions are refused. An **unknown** alias is a manifest MetricFlow
    would reject or, worse, resolve against something else. An **unused** one
    is an input computed and discarded: the offset join runs, the column is
    never read, and the author meant something they did not write.
    """

    if metric.derived is None:
        return []

    declared = {input_.alias for input_ in metric.derived.inputs}
    referenced = {column.name for column in metric.derived.expr.ast().find_all(exp.Column)}
    violations: list[GuardrailError] = []

    if unknown := sorted(referenced - declared):
        msg = (
            f"derived metric {metric.name!r} references {unknown} in its expr, which its "
            f"inputs: do not declare; declared: {sorted(declared)}. Fix: add the input, or "
            "correct the alias"
        )
        violations.append(InvalidMetricShape(msg, source_path=path))

    if unused := sorted(declared - referenced):
        msg = (
            f"derived metric {metric.name!r} declares inputs {unused} its expr never "
            "references — each one is a metric read and discarded. Fix: remove the input, "
            "or reference it"
        )
        violations.append(InvalidMetricShape(msg, source_path=path))

    return violations


# ....................... #


def check_metrics(draft: ProjectIR) -> list[GuardrailError]:
    """Every metric-shape and metric-filter violation across the draft.

    Filters are checked against **every** mart listing the metric among its
    measures, rather than against the one that will own it: ownership is the
    cheapest-mart rule of RFC 0010 D8, which lives in the lowering package a
    layer above this one, and checking every candidate is a superset of what
    correctness needs (RFC 0034 D9). A metric no mart lists carries no
    checkable filter and none is claimed.
    """

    violations: list[GuardrailError] = []

    for metric in draft.metrics:
        path = f"metrics: metrics.{metric.name}"
        violations.extend(_check_shape(metric, path))

        for mart in draft.marts:
            if metric.name not in mart.measures:
                continue
            for clause in metric.filter:
                violations.extend(_check_filter(metric, clause, mart, path))

    return violations
