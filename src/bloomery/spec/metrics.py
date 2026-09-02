"""The ``MetricSet`` spec kind (RFC 0002 §5.5; original spec §3.2 templates).

Project-authored metrics mirroring the catalog's ``metric_templates``: a
metric either references a template by ``template:`` or is fully inline
(``expr``/``agg``/``grain``). Additivity is typed — ``semi_additive`` carries
a :class:`~bloomery.spec.common.SemiAdditivePolicy`, ``non_additive`` a
:class:`~bloomery.spec.common.RatioSpec` or a :class:`DerivedSpec`; their
*presence* is shape-validated here, their necessity is enforced at the
guardrail stage (``NonAdditiveWithoutComponents``, RFC 0006).

The time-shaped forms (RFC 0034) also live here, and this module owns their
grammar because both readers of it are metric-shaped: ``derived:`` computes a
metric from other metrics, each input optionally read at an ``offset:``;
``cumulative:`` accumulates a metric's own measure over a window. ``filter:``
restricts the rows a metric aggregates, as a typed predicate list and never
as a SQL string (RFC 0034 D8).

Parse validates shape and grammar only (RFC 0002 D4). What needs the marts —
that a filter's dimension is flattened somewhere and fits the column's type,
that a derived expression references only declared aliases — is checked at
the guardrail stage, batched with every other model error.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, StringConstraints, model_validator

from bloomery.spec.common import (
    AdditivityName,
    DimensionName,
    MemberName,
    RatioSpec,
    SemiAdditivePolicy,
    SpecModel,
)

# ----------------------- #

__all__ = [
    "TIME_WINDOW_PATTERN",
    "CumulativeSpec",
    "DerivedSpec",
    "FilterOpName",
    "FilterValue",
    "Metric",
    "MetricFilter",
    "MetricInputSpec",
    "MetricOffset",
    "MetricSet",
    "TimeGrainName",
    "TimeWindowString",
    "parse_time_window",
]

# ....................... #
# Time vocabulary (RFC 0034 D2)

#: The grains an offset window, an offset target and a cumulative window may
#: name — the mart's own date buckets (RFC 0010 D4), one definition shared by
#: all three. ``hour`` is deliberately absent even though MetricFlow accepts
#: it: the emitted time spine is day-grain (RFC 0008 D13), so an hourly window
#: would resolve against a spine that cannot express it.
TimeGrainName = Literal["day", "week", "month", "quarter", "year"]

#: ``"<count> <grain>"`` — ``"1 year"``, ``"7 days"``, ``"3 months"``. A
#: plural ``s`` is accepted and normalized away by :func:`parse_time_window`;
#: a zero count is refused, because a window of nothing is a metric equal to
#: its own input written the long way.
TIME_WINDOW_PATTERN = r"^[1-9][0-9]* (?:day|week|month|quarter|year)s?$"

TimeWindowString = Annotated[str, StringConstraints(pattern=TIME_WINDOW_PATTERN)]


# ....................... #
# Filter vocabulary (RFC 0034 D8, D10, D12)

#: The operators a metric *definition* may pin. Deliberately **not**
#: :class:`bloomery.planner.request.Op`, which is what a *request* may ask:
#: that set carries ``like``/``ilike``, whose ``\`` escape language, ``ESCAPE``
#: clause and case-folding portability argument (RFC 0015 decision 13) buy
#: nothing in a definition, where the author knows the values. Two vocabularies
#: by decision (D12), not by accident — a future reader seeing both should not
#: reach for the merge.
FilterOpName = Literal["eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "is_null"]

#: The operators taking exactly one value; everything else takes one or more.
_SINGLE_VALUE_OPS = frozenset({"eq", "ne", "gt", "gte", "lt", "lte", "is_null"})

#: Both semantic targets template with braces — Jinja on MetricFlow,
#: ``{member}`` on Cube — so a value carrying one would need per-target
#: neutralization, and two escaping rules that can disagree is the defect this
#: project keeps finding in itself (RFC 0034 D13).
_TEMPLATE_CHARS = re.compile(r"[{}]")


def _filter_value(value: object) -> object:
    """One authored filter value, before coercion (RFC 0034 D13).

    Runs *before* pydantic's union coercion so it sees what the document
    actually said: a YAML ``1.5`` arrives here as a ``float`` and is refused
    by type, where after coercion it would already have become a ``Decimal``
    and the refusal would have nothing left to see.
    """

    if isinstance(value, float):
        msg = (
            f"filter value {value!r} is a float, and no float ever reaches an emission "
            'path (RFC 0003 D5). Fix: write it as a quoted string — "1.5" — which parses '
            "as an exact Decimal"
        )
        raise ValueError(msg)

    if isinstance(value, Decimal) and not value.is_finite():
        msg = (
            f"filter value {value!r} is non-finite: `amount < nan` is never TRUE on some "
            "engines and always TRUE on others (RFC 0015 D5). Fix: write a real value"
        )
        raise ValueError(msg)

    if isinstance(value, str):
        if "\x00" in value:
            raise ValueError("filter value contains a NUL byte — refused")
        if _TEMPLATE_CHARS.search(value):
            msg = (
                f"filter value {value!r} contains a template brace. Both semantic targets "
                "template with braces — Jinja on MetricFlow, {member} on Cube — and a value "
                "carrying one has no neutralization both agree on (RFC 0034 D13)"
            )
            raise ValueError(msg)

    return value


#: A metric-filter literal. ``bool`` precedes ``int`` so ``true`` stays a
#: boolean; ``float`` is absent by construction and refused by name above.
FilterValue = Annotated[
    bool | int | Decimal | date | datetime | str, BeforeValidator(_filter_value)
]


class MetricFilter(SpecModel):
    """One row-level restriction on a metric (RFC 0034 D8).

    ``dimension`` names a column flattened on the mart carrying the metric;
    that it is flattened, and that ``values`` fit its declared type, is a
    guardrail (D9) — this layer checks only what is decidable from the
    document: the operator/arity coherence, and that the name is a bare
    identifier. The second is not cosmetic — see
    :data:`~bloomery.spec.common.DimensionName`, which the reference is typed
    with: this is the one place a member name reaches a template unquoted.
    """

    dimension: DimensionName
    op: FilterOpName
    values: tuple[FilterValue, ...] = ()

    # ....................... #

    @model_validator(mode="after")
    def _arity(self) -> MetricFilter:
        if self.op == "is_null":
            if len(self.values) != 1 or not isinstance(self.values[0], bool):
                msg = (
                    f"filter on {self.dimension!r} (is_null) takes exactly one bool — "
                    "true renders IS NULL, false renders IS NOT NULL"
                )
                raise ValueError(msg)
        elif self.op in _SINGLE_VALUE_OPS:
            if len(self.values) != 1:
                msg = (
                    f"filter on {self.dimension!r} ({self.op}) takes exactly 1 value, "
                    f"got {len(self.values)}"
                )
                raise ValueError(msg)
        elif not self.values:
            msg = f"filter on {self.dimension!r} ({self.op}) needs at least one value"
            raise ValueError(msg)

        return self


# ....................... #


class MetricOffset(SpecModel):
    """How far back a derived metric's input reads (RFC 0034 D2): exactly one
    of a fixed ``window`` or the start of the containing period.

    ``{window: "1 year"}`` against a monthly grouping is the same month one
    year earlier; ``{to_grain: month}`` against a daily grouping is the first
    day of each row's own month.
    """

    window: TimeWindowString | None = None
    to_grain: TimeGrainName | None = None

    # ....................... #

    @model_validator(mode="after")
    def _exactly_one(self) -> MetricOffset:
        if (self.window is None) == (self.to_grain is None):
            msg = "offset requires exactly one of 'window' or 'to_grain'"
            raise ValueError(msg)

        return self


# ....................... #


class MetricInputSpec(SpecModel):
    """One input of a derived metric — the metric read, and optionally the
    offset it is read at. Its *alias* is the key it sits under in
    :attr:`DerivedSpec.inputs`, because the alias is what the expression
    references (RFC 0034 D1)."""

    metric: str
    offset: MetricOffset | None = None


# ....................... #


class DerivedSpec(SpecModel):
    """A metric computed by an expression over other metrics (RFC 0034 D1).

    ``inputs`` is a mapping keyed by alias rather than a list: the alias is
    the input's identity because ``expr`` references it, and a mapping makes a
    duplicate alias unrepresentable instead of something to validate. That the
    expression references only declared aliases is a guardrail — it needs the
    parsed expression, which lives a layer up.
    """

    expr: str
    inputs: dict[MemberName, MetricInputSpec] = Field(min_length=1)

    # ....................... #

    @property
    def input_metrics(self) -> tuple[str, ...]:
        """The distinct metrics this one depends on, sorted.

        The single definition of that set: the reference checker validates
        these names against the metric set, and the template merge unions them
        into ``requires_metrics`` so the resolution DAG carries the edges
        (RFC 0034 D3). Two spellings of "what a derived metric depends on" is
        how the two come to disagree.
        """

        return tuple(sorted({spec.metric for spec in self.inputs.values()}))


# ....................... #


class CumulativeSpec(SpecModel):
    """A metric's accumulation over time (RFC 0002 D10, lowered by RFC 0034
    D5): exactly one of a trailing ``window`` or a ``grain_to_date``.

    ``{window: "7 days"}`` is a trailing seven-day total; ``{grain_to_date:
    month}`` is month-to-date. The metric keeps its own measure and its own
    ``additivity`` — that describes the measure, while this describes how the
    measure accumulates (D6).
    """

    window: TimeWindowString | None = None
    grain_to_date: TimeGrainName | None = None

    # ....................... #

    @model_validator(mode="after")
    def _exactly_one(self) -> CumulativeSpec:
        if (self.window is None) == (self.grain_to_date is None):
            msg = "cumulative requires exactly one of 'window' or 'grain_to_date'"
            raise ValueError(msg)

        return self


# ....................... #


def parse_time_window(window: str) -> tuple[int, str]:
    """``"3 months"`` → ``(3, "month")``. The one place the plural is dropped.

    Total on :data:`TimeWindowString`, which is the only type that reaches it:
    the pattern has already established the shape, so this splits rather than
    validates.
    """

    count, _, grain = window.partition(" ")
    return int(count), grain.rstrip("s")


# ....................... #


class Metric(SpecModel):
    """One authored metric: a template instantiation or an inline definition.

    Shape-only at parse (RFC 0002 D4): whether ``template`` exists, leaves are
    reachable, or the additivity policy is complete is checked downstream
    (resolution RFC 0005; guardrails RFC 0006).
    """

    template: str | None = None
    description: str | None = None
    requires: tuple[str, ...] = ()
    requires_metrics: tuple[str, ...] = ()
    grain: str | None = None
    additivity: AdditivityName | None = None
    agg: str | None = None
    expr: str | None = None
    ratio: RatioSpec | None = None
    semi_additive: SemiAdditivePolicy | None = None
    cumulative: CumulativeSpec | None = None
    derived: DerivedSpec | None = None
    filter: tuple[MetricFilter, ...] = ()


# ....................... #


class MetricSet(SpecModel):
    """The per-project metric document (``metrics_version``), at most one per
    project (RFC 0002 §5.5)."""

    #: Pinned to the one version bloomery implements (RFC 0018 D7). It was
    #: ``int`` with ``ge=1``, which accepted a document written for a future
    #: bloomery and silently applied v1 semantics to it — the exact misreading
    #: a version key exists to refuse. This key is also the document-kind
    #: discriminator, so it stays required: a document without one cannot be
    #: identified at all.
    metrics_version: Literal[1]
    metrics: dict[MemberName, Metric]
