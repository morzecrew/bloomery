"""Name bridging (RFC 0013 §5.5, D7): the bidirectional mapping between
bloomery's mart vocabulary and MetricFlow's dunder names, keyed on the
semantic model's **primary entity** — which is the mart's grain entity in
both key shapes the emitter produces (single-column key: a PRIMARY entity
named ``mart.grain``; composite key: ``primary_entity = mart.grain`` set
name-only on the model). A model named ``orders`` with grain ``order``
yields ``order__carrier``, never ``orders__carrier``.

The bloomery-facing dimension vocabulary is exactly the mart's flattened
columns (RFC 0010): categorical dimensions are column names
(``warehouse_id``), date-role dimensions are the ``<role>_<bucket>`` bucket
columns (``ordered_month``). Because the emitter declares only the *day*
bucket as a TIME dimension and MetricFlow derives coarser grains from it
(RFC 0013 R1), the bridge maps ``<role>_<grain>`` onto
``{entity}__{role}_day__{grain}``. ``metric_time`` is reserved and never
emitted from user input.

Callers never see dunder names: :func:`columns_from` translates the typed
``query_spec`` back into :class:`~bloomery.planner.result.ColumnDescriptor`
rows in bloomery names, and the round-trip property test (every emitted
dimension → :func:`group_by_name` → :func:`bloomery_dimension_name` →
original name + grain) keeps emitter and bridge agreeing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from metricflow_semantics.specs.dimension_spec import DimensionSpec
from metricflow_semantics.specs.time_dimension_spec import TimeDimensionSpec

from bloomery.errors import PlannerError
from bloomery.ir import Additivity
from bloomery.planner.request import TimeGrain
from bloomery.planner.result import ColumnDescriptor
from bloomery.typing import DecimalType, IntType

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from metricflow_semantics.specs.query_spec import MetricFlowQuerySpec

    from bloomery.ir import MartIR, MetricIR
    from bloomery.planner.request import OrderSpec
    from bloomery.typing import LogicalType

# ----------------------- #

__all__ = [
    "ResolvedDimension",
    "bloomery_dimension_name",
    "columns_from",
    "entity_key",
    "group_by_name",
    "to_mf_group_by",
    "to_mf_metrics",
    "to_mf_order",
]

_DAY_SUFFIX = "_day"

#: A metric expression that is a bare column reference — used to type the
#: measure column from the mart column it reads (RFC 0011 D2 envelope).
_BARE_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class ResolvedDimension:
    """One requested dimension after coverage resolution (RFC 0013 R3):
    ``name`` is the effective bloomery name — a mart column — with ``role``
    and ``grain`` set for date-role dimensions, ``None`` for categorical."""

    name: str
    role: str | None = None
    grain: TimeGrain | None = None


# ....................... #


def entity_key(mart: MartIR) -> str:
    """The dunder key for a mart's semantic model: its grain entity name —
    the primary entity in both key shapes the emitter produces."""

    return mart.grain


# ....................... #


def to_mf_metrics(metrics: Sequence[str]) -> tuple[str, ...]:
    """Metric names cross the bridge unchanged — metric names are the shared
    vocabulary (RFC 0013 §5.2: the manifest metric *is* the bloomery metric).
    Centralized so the seam stays visible and swappable."""

    return tuple(metrics)


# ....................... #


def group_by_name(dimension: ResolvedDimension, *, entity: str) -> str:
    """One dimension's MetricFlow group-by name (RFC 0013 D7):
    ``{entity}__{column}`` for categorical, ``{entity}__{role}_day__{grain}``
    for date roles — the day bucket is the declared TIME dimension and
    MetricFlow derives the requested grain from it."""

    if dimension.role is not None and dimension.grain is not None:
        return f"{entity}__{dimension.role}{_DAY_SUFFIX}__{dimension.grain.value}"

    return f"{entity}__{dimension.name}"


# ....................... #


def to_mf_group_by(dimensions: Sequence[ResolvedDimension], *, entity: str) -> tuple[str, ...]:
    """Every requested dimension as a MetricFlow group-by name, in request
    order (output column order follows it — the planner passes
    ``output_column_order_mode=INPUT_ORDER``)."""

    return tuple(group_by_name(dimension, entity=entity) for dimension in dimensions)


# ....................... #


def to_mf_order(
    order_by: Sequence[OrderSpec],
    *,
    entity: str,
    metrics: Sequence[str],
    dimensions: Mapping[str, ResolvedDimension],
) -> tuple[str, ...]:
    """Order terms as MetricFlow ``order_by_names`` — a leading ``-`` marks
    descending. ``dimensions`` maps each *requested* dimension string to its
    resolution; request validation already guaranteed every field is a
    requested metric or dimension (RFC 0011 D4)."""
    names: list[str] = []

    for spec in order_by:
        if spec.field in dimensions:
            name = group_by_name(dimensions[spec.field], entity=entity)
        elif spec.field in metrics:
            name = spec.field
        else:  # pragma: no cover — MetricRequest validation refuses this
            msg = f"order_by field {spec.field!r} is not a requested metric or dimension"
            raise PlannerError(msg)
        names.append(f"-{name}" if spec.direction == "desc" else name)

    return tuple(names)


# ....................... #


def bloomery_dimension_name(element_name: str, grain: TimeGrain | None) -> str:
    """The reverse bridge for one dimension element: a TIME element
    ``{role}_day`` at ``grain`` maps back to the ``{role}_{grain}`` bucket
    column; a categorical element is already the column name."""

    if grain is None:
        return element_name

    role = element_name.removesuffix(_DAY_SUFFIX)
    return f"{role}_{grain.value}"


# ....................... #


def _column_type(mart: MartIR, column: str) -> LogicalType:
    for mart_column in mart.columns:
        if mart_column.name == column:
            return mart_column.type

    msg = f"MetricFlow returned dimension {column!r}, which mart {mart.name!r} does not flatten"
    raise PlannerError(msg)


# ....................... #


def _measure_type(metric: MetricIR, mart: MartIR) -> LogicalType:
    """The declared type of a measure column — honest where knowable: counts
    are ints, a bare-column SUM/MIN/MAX keeps the column's type, everything
    else (ratios, expressions) is a wide decimal."""

    if metric.additivity is Additivity.NON_ADDITIVE:
        return DecimalType(38, 9)

    if metric.agg in ("count", "count_distinct"):
        return IntType()

    if metric.expr is not None and _BARE_COLUMN.match(metric.expr.sql):
        for mart_column in mart.columns:
            if mart_column.name == metric.expr.sql:
                return mart_column.type

    return DecimalType(38, 9)


# ....................... #


def columns_from(
    query_spec: MetricFlowQuerySpec,
    *,
    mart: MartIR,
    metrics_by_name: Mapping[str, MetricIR],
) -> tuple[ColumnDescriptor, ...]:
    """The plan's typed column envelope, in bloomery names and output order.

    Reads the typed ``query_spec.input_spec_order`` (never the SQL text):
    group-by items first, metrics after — exactly the output column order the
    planner requests from MetricFlow. Time dimensions come back role-
    qualified at their effective grain (``ordered_month``), never as dunders.
    """
    columns: list[ColumnDescriptor] = []

    for spec in query_spec.input_spec_order.group_by_item_specs:
        if isinstance(spec, TimeDimensionSpec):
            granularity = spec.time_granularity
            if granularity is None:  # pragma: no cover — the bridge always sets one
                msg = f"time dimension {spec.element_name!r} came back without a grain"
                raise PlannerError(msg)
            grain = TimeGrain(granularity.base_granularity.value)
            name = bloomery_dimension_name(spec.element_name, grain)
        elif isinstance(spec, DimensionSpec):
            name = bloomery_dimension_name(spec.element_name, None)
        else:
            msg = (
                f"MetricFlow returned a group-by of type {type(spec).__name__!r} the "
                "planner never requests — entity and metric group-bys are not part of "
                "the bridge (RFC 0013 D7)"
            )
            raise PlannerError(msg)
        columns.append(
            ColumnDescriptor(
                name=name,
                sql_alias=spec.dunder_name,
                type=_column_type(mart, name),
                role="dimension",
            )
        )

    for metric_spec in query_spec.input_spec_order.metric_specs:
        metric = metrics_by_name.get(metric_spec.element_name)
        if metric is None:  # pragma: no cover — coverage validated the names
            msg = f"MetricFlow returned unknown metric {metric_spec.element_name!r}"
            raise PlannerError(msg)
        columns.append(
            ColumnDescriptor(
                name=metric.name,
                sql_alias=metric.name,
                type=_measure_type(metric, mart),
                role="measure",
                label=metric.description,
            )
        )

    return tuple(columns)
