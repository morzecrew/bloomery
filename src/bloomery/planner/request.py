"""The planner's request types (RFC 0011 §5.2, D2 — verbatim from D1):
:class:`TimeGrain`, :class:`FilterExpr`, :class:`OrderSpec`, and
:class:`MetricRequest` — frozen slotted dataclasses forming the static shape
an upstream Query Agent fills with dynamic content. It never writes SQL; a
malformed request fails *validation* here with a typed
:class:`~bloomery.errors.InvalidRequest` and is never delegated to the
backend (RFC 0011 D9 — planner errors are not batched; first failure wins).

Structural rules enforced at construction:

- at least one metric; duplicate metrics/dimensions are refused (a duplicate
  is always an authoring bug, never a meaningful request);
- ``order_by`` fields must be requested metrics or dimensions — arbitrary
  expressions are an injection surface (RFC 0011 D4);
- ``limit`` must be ≥ 1 (the *ceiling* is the planner's ``max_limit``);
- filter operator/value arity coherence (``between`` takes exactly two
  values, ``is_null`` none, ``in``/``not_in`` at least one, the rest one);
- filter values are :data:`JsonScalar` only — floats are banned package-wide
  (RFC 0003 D5): send :class:`decimal.Decimal` or a string.

Type-vs-dimension checking (a string against a numeric column) is *not*
structural — it needs the covering mart's column types and happens in
:mod:`bloomery.planner.filters` (``FilterTypeMismatch``, RFC 0013 D8).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from bloomery.errors import InvalidRequest

__all__ = [
    "FilterExpr",
    "FilterOp",
    "JsonScalar",
    "MetricRequest",
    "OrderSpec",
    "TimeGrain",
]

#: A structured filter value: never a float (RFC 0003 D5 — ``Decimal`` or
#: int), never ``None`` (absence is the ``is_null`` operator, not a value).
type JsonScalar = str | int | bool | Decimal

type FilterOp = Literal[
    "eq",
    "ne",
    "in",
    "not_in",
    "gt",
    "gte",
    "lt",
    "lte",
    "between",
    "contains",
    "is_null",
]

type OrderDirection = Literal["asc", "desc"]


class TimeGrain(StrEnum):
    """Requestable time grains (RFC 0011 D2). ``HOUR`` is accepted here for
    contract stability but marts expand date roles to day..year buckets only
    (RFC 0010 D4) — an hour request is refused at coverage."""

    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


#: Exact value count per operator; ``None`` means "one or more".
_ARITY: dict[str, int | None] = {
    "eq": 1,
    "ne": 1,
    "gt": 1,
    "gte": 1,
    "lt": 1,
    "lte": 1,
    "contains": 1,
    "between": 2,
    "is_null": 0,
    "in": None,
    "not_in": None,
}


def _check_scalar(value: object, *, where: str) -> None:
    if isinstance(value, float):
        msg = (
            f"{where} carries a float value {value!r} — floats are banned "
            "(RFC 0003 D5); send a Decimal or a string instead"
        )
        raise InvalidRequest(msg)
    if not isinstance(value, (str, int, bool, Decimal)):
        msg = f"{where} carries a non-scalar value of type {type(value).__name__!r}"
        raise InvalidRequest(msg)


@dataclass(frozen=True, slots=True)
class FilterExpr:
    """One structured filter over a requested dimension (RFC 0011 D2).

    ``dimension`` may be role-qualified (``ordered_month``) or bare; it is
    resolved against the covering mart at coverage time (RFC 0013 R3).
    """

    dimension: str
    op: FilterOp
    values: tuple[JsonScalar, ...] = ()

    def __post_init__(self) -> None:
        if not self.dimension:
            raise InvalidRequest("a filter needs a dimension name")
        if self.op not in _ARITY:
            msg = f"unknown filter operator {self.op!r}; known: {sorted(_ARITY)}"
            raise InvalidRequest(msg)
        expected = _ARITY[self.op]
        where = f"filter on {self.dimension!r} ({self.op})"
        if expected is None:
            if not self.values:
                raise InvalidRequest(f"{where} needs at least one value")
        elif len(self.values) != expected:
            msg = f"{where} takes exactly {expected} value(s), got {len(self.values)}"
            raise InvalidRequest(msg)
        for value in self.values:
            _check_scalar(value, where=where)


@dataclass(frozen=True, slots=True)
class OrderSpec:
    """One ordering term: a *requested* metric or dimension, never arbitrary
    SQL (RFC 0011 D4 — that would be an injection surface)."""

    field: str
    direction: OrderDirection = "asc"

    def __post_init__(self) -> None:
        if self.direction not in ("asc", "desc"):
            msg = f"order direction must be 'asc' or 'desc', got {self.direction!r}"
            raise InvalidRequest(msg)


@dataclass(frozen=True, slots=True)
class MetricRequest:
    """A complete metric request (RFC 0011 D2): what the Query Agent emits.

    ``time_grain`` applies to every date-role dimension in the request
    (RFC 0011 D6 consumer side): requesting ``ordered_day`` with
    ``time_grain=MONTH`` groups by the ``ordered_month`` bucket.
    """

    metrics: tuple[str, ...]
    dimensions: tuple[str, ...] = ()
    filters: tuple[FilterExpr, ...] = ()
    time_grain: TimeGrain | None = None
    order_by: tuple[OrderSpec, ...] = ()
    limit: int | None = None

    def __post_init__(self) -> None:
        if not self.metrics:
            raise InvalidRequest("a request needs at least one metric")
        for kind, names in (("metric", self.metrics), ("dimension", self.dimensions)):
            duplicates = sorted({n for n in names if names.count(n) > 1})
            if duplicates:
                raise InvalidRequest(f"duplicate {kind}(s) in request: {duplicates}")
        if self.limit is not None and self.limit < 1:
            raise InvalidRequest(f"limit must be >= 1, got {self.limit}")
        allowed = set(self.metrics) | set(self.dimensions)
        for spec in self.order_by:
            if spec.field not in allowed:
                msg = (
                    f"order_by field {spec.field!r} is not a requested metric or "
                    "dimension — arbitrary order expressions are refused (RFC 0011 D4)"
                )
                raise InvalidRequest(msg)
