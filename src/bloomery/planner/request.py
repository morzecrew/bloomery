"""The planner's request types (S-0028/request-and-response-types S-0028/D-2, amended by S-0032):
:class:`TimeGrain`, the CNF filter vocabulary (:class:`Op`,
:class:`Predicate`, :class:`AnyOf`, ``Clause``), :class:`OrderSpec`, and
:class:`MetricRequest` — frozen slotted dataclasses forming the static shape
an upstream Query Agent fills with dynamic content. It never writes SQL; a
malformed request fails *validation* here with a typed
:class:`~bloomery.errors.InvalidRequest` (or, for the S-0032 vocabulary
refusals, an :class:`~bloomery.errors.UnsupportedFilter` leaf) and is never
delegated to the backend (S-0028/D-9 — planner errors are not batched;
first failure wins).

Filters are CNF (S-0032/D-3): ``MetricRequest.filters`` is an implicit
AND across clauses, each clause a single :class:`Predicate` or one
:class:`AnyOf` disjunction group — exactly one level of disjunction, deeper
nesting unrepresentable by construction.

Structural rules enforced at construction:

- at least one metric; duplicate metrics/dimensions are refused (a duplicate
  is always an authoring bug, never a meaningful request);
- ``order_by`` fields must be requested metrics or dimensions — arbitrary
  expressions are an injection surface (S-0028/D-4);
- ``limit`` must be ≥ 1 (the *ceiling* is the planner's ``max_limit``);
- filter operator/value arity coherence (S-0032/types-replaces-rfc-0011-d2-s-filterexpr-orderspec: comparisons take
  exactly one value, ``is_null`` exactly one **bool**, ``in``/``not_in``
  and ``like``/``ilike`` one or more);
- ``float`` values are accepted at this boundary and normalized to
  ``Decimal(str(value))`` immediately (S-0032/D-5 amending S-0020/D-5 —
  no float ever reaches literal rendering or emission); non-finite numerics
  are :class:`~bloomery.errors.InvalidLiteral`;
- ``like``/``ilike`` operands are SQL ``LIKE`` *patterns* in the ``\\``
  escape language (S-0032 decision 13): an unpaired trailing ``\\`` or a
  NUL byte is :class:`~bloomery.errors.InvalidLiteral`.

Type-vs-dimension checking (a string against a numeric column) is *not*
structural — it needs the covering mart's column types and happens in
:mod:`bloomery.planner.filters` (``FilterTypeMismatch``, S-0030/D-8).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, cast
from uuid import UUID

from bloomery.errors import InvalidLiteral, InvalidRequest

# ----------------------- #

__all__ = [
    "AnyOf",
    "Clause",
    "MetricRequest",
    "Op",
    "OrderSpec",
    "Predicate",
    "Scalar",
    "TimeGrain",
    "clause_predicates",
]

#: A structured filter value (S-0032/types-replaces-rfc-0011-d2-s-filterexpr-orderspec). ``float`` is accepted at this
#: boundary only — construction normalizes it to ``Decimal(str(value))``
#: (S-0032/D-5), so no float survives into a built :class:`Predicate`.
#: Never ``None``: absence is the ``is_null`` operator, not a value.
type Scalar = int | float | Decimal | bool | str | date | datetime | UUID

type OrderDirection = Literal["asc", "desc"]


class Op(StrEnum):
    """The closed filter-operator vocabulary (S-0032/types-replaces-rfc-0011-d2-s-filterexpr-orderspec) — semantics
    match the upstream Mongo-flavoured grammar (``$eq``/``$neq``/…), naming
    stays plain."""

    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    NOT_IN = "not_in"
    IS_NULL = "is_null"
    LIKE = "like"
    ILIKE = "ilike"


# ....................... #


class TimeGrain(StrEnum):
    """Requestable time grains (S-0028/D-2). ``HOUR`` is accepted here for
    contract stability but marts expand date roles to day..year buckets only
    (S-0027/D-4) — an hour request is refused at coverage."""

    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


# ....................... #


#: The six exactly-one-value comparison operators (S-0032/D-5 calls them
#: the ordering operators — the ops non-finite operands fail open on).
COMPARISON_OPS = frozenset({Op.EQ, Op.NE, Op.GT, Op.GTE, Op.LT, Op.LTE})

#: The pattern-matching operators (S-0032/D-2/decision 13).
PATTERN_OPS = frozenset({Op.LIKE, Op.ILIKE})

_NON_FINITE_MSG = (
    "is non-finite — NaN/Infinity comparisons fail open (Postgres sorts "
    "'NaN'::numeric above every number), refused (S-0032/D-5)"
)


def _normalize_scalar(value: object, *, where: str) -> Scalar:
    """One value at the request boundary (S-0032/D-5): floats normalize to
    ``Decimal(str(value))`` so no float survives construction; non-finite
    numerics (float or ``Decimal``) are :class:`InvalidLiteral`."""

    if isinstance(value, float):
        candidate = Decimal(str(value))
        if not candidate.is_finite():
            raise InvalidLiteral(f"{where} value {value!r} {_NON_FINITE_MSG}")
        return candidate

    if isinstance(value, Decimal):
        if not value.is_finite():
            raise InvalidLiteral(f"{where} value {value!r} {_NON_FINITE_MSG}")
        return value

    if not isinstance(value, (str, int, bool, date, datetime, UUID)):
        msg = f"{where} carries a non-scalar value of type {type(value).__name__!r}"
        raise InvalidRequest(msg)

    return value


# ....................... #


def _check_pattern(pattern: object, *, where: str) -> str:
    """One ``like``/``ilike`` operand (S-0032 decision 13): a SQL ``LIKE``
    pattern in the ``\\`` escape language. An unpaired trailing ``\\`` is
    invalid SQL on several dialects and a NUL byte can truncate — both are
    :class:`InvalidLiteral`, refusal beating engine-dependent behavior."""

    if not isinstance(pattern, str):
        msg = f"{where} takes string LIKE patterns, got {type(pattern).__name__!r}"
        raise InvalidRequest(msg)

    if "\x00" in pattern:
        raise InvalidLiteral(f"{where} pattern contains a NUL byte — refused")

    index = 0

    while index < len(pattern):
        if pattern[index] == "\\":
            if index + 1 >= len(pattern):
                msg = (
                    f"{where} pattern {pattern!r} ends in an unpaired escape "
                    "character — write \\\\ (two characters) for a literal "
                    "backslash (S-0032)"
                )
                raise InvalidLiteral(msg)
            index += 2
        else:
            index += 1

    return pattern


# ....................... #


@dataclass(frozen=True, slots=True)
class Predicate:
    """One single-dimension filter (S-0032/types-replaces-rfc-0011-d2-s-filterexpr-orderspec; renames S-0028/D-2's
    ``FilterExpr``).

    ``dimension`` may be role-qualified (``ordered_month``) or bare; it is
    resolved against the covering mart at coverage time (S-0030 R3).
    Never field-to-field — a dimension-to-dimension comparison is refused
    upstream (``UnsupportedFieldCompare``, adapter-owned).
    """

    dimension: str
    op: Op
    values: tuple[Scalar, ...] = ()

    # ....................... #

    def __post_init__(self) -> None:
        # The annotation is a promise untyped callers may break — validate
        # at runtime (the same discipline OrderSpec applies to `field`).
        dimension = cast("object", self.dimension)

        if not isinstance(dimension, str) or not dimension:
            msg = f"a filter needs a non-empty string dimension name, got {dimension!r}"
            raise InvalidRequest(msg)

        try:
            op = Op(self.op)
        except ValueError:
            known = sorted(member.value for member in Op)
            msg = f"unknown filter operator {self.op!r}; known: {known}"
            raise InvalidRequest(msg) from None

        object.__setattr__(self, "op", op)
        where = f"filter on {self.dimension!r} ({op.value})"

        if op in COMPARISON_OPS:
            if len(self.values) != 1:
                msg = f"{where} takes exactly 1 value(s), got {len(self.values)}"
                raise InvalidRequest(msg)
        elif op is Op.IS_NULL:
            if len(self.values) != 1 or not isinstance(self.values[0], bool):
                msg = (
                    f"{where} takes exactly one bool — True renders IS NULL, "
                    "False renders IS NOT NULL (S-0032/types-replaces-rfc-0011-d2-s-filterexpr-orderspec)"
                )
                raise InvalidRequest(msg)
        elif not self.values:
            raise InvalidRequest(f"{where} needs at least one value")

        if op in PATTERN_OPS:
            patterns = tuple(_check_pattern(value, where=where) for value in self.values)
            object.__setattr__(self, "values", patterns)
        else:
            normalized = tuple(_normalize_scalar(value, where=where) for value in self.values)
            object.__setattr__(self, "values", normalized)


# ....................... #


def _check_member(member: object) -> None:
    """Defensive runtime check — untyped callers exist (S-0032/D-3)."""

    if not isinstance(member, Predicate):
        msg = (
            "an any_of group holds Predicate members only — nesting is "
            f"unrepresentable (S-0032/D-3), got {type(member).__name__!r}"
        )
        raise InvalidRequest(msg)


# ....................... #


def _check_clause(clause: object) -> None:
    """Defensive runtime check — untyped callers exist (S-0032/D-3)."""

    if not isinstance(clause, (Predicate, AnyOf)):
        msg = (
            "filters hold Predicate or AnyOf clauses only (S-0032 "
            f"D-Q3), got {type(clause).__name__!r}"
        )
        raise InvalidRequest(msg)


# ....................... #


@dataclass(frozen=True, slots=True)
class AnyOf:
    """One disjunction group — exactly one level (S-0032/D-3): OR across
    its predicates, AND with every other clause. Members may span different
    dimensions (CNF distribution routinely produces mixed-dimension groups);
    deeper nesting is unrepresentable by construction."""

    predicates: tuple[Predicate, ...]

    # ....................... #

    def __post_init__(self) -> None:
        # The container itself is validated first: a list passes an
        # emptiness check but stays mutable after construction, which a
        # frozen value object may not be (S-0032/D-3).
        predicates = cast("object", self.predicates)

        if not isinstance(predicates, tuple):
            msg = (
                "an any_of group needs tuple predicate members — a mutable "
                f"container is not a frozen value object, got {type(predicates).__name__!r}"
            )
            raise InvalidRequest(msg)

        if not self.predicates:
            raise InvalidRequest("an any_of group needs at least one predicate")

        for member in self.predicates:
            _check_member(member)


# ....................... #


#: One filter clause (S-0032/D-3): a predicate, or one disjunction group.
type Clause = Predicate | AnyOf


def clause_predicates(clause: Clause) -> tuple[Predicate, ...]:
    """The predicates of one clause — a 1-tuple for a bare predicate, the
    member tuple for an :class:`AnyOf` group."""

    return clause.predicates if isinstance(clause, AnyOf) else (clause,)


# ....................... #


@dataclass(frozen=True, slots=True)
class OrderSpec:
    """One ordering term: a *requested* metric or dimension, never arbitrary
    SQL (S-0028/D-4 — that would be an injection surface). Carries no
    ``nulls`` placement (S-0032/D-7 — accepting-and-dropping is worse
    than refusing; non-default placements refuse in ``parse_sort_json``)."""

    field: str
    direction: OrderDirection = "asc"

    # ....................... #

    def __post_init__(self) -> None:
        # The annotation is a promise untyped callers may break — validate
        # at runtime (the same discipline Predicate applies to `dimension`).
        field = cast("object", self.field)

        if not isinstance(field, str) or not field:
            msg = f"an order term needs a non-empty string field, got {field!r}"
            raise InvalidRequest(msg)

        if self.direction not in ("asc", "desc"):
            msg = f"order direction must be 'asc' or 'desc', got {self.direction!r}"
            raise InvalidRequest(msg)


# ....................... #


@dataclass(frozen=True, slots=True)
class MetricRequest:
    """A complete metric request (S-0028/D-2): what the Query Agent emits.

    ``filters`` is CNF (S-0032/D-3): implicit AND across clauses.
    ``time_grain`` applies to every date-role dimension in the request
    (S-0028/D-6 consumer side): requesting ``ordered_day`` with
    ``time_grain=MONTH`` groups by the ``ordered_month`` bucket.
    """

    metrics: tuple[str, ...]
    dimensions: tuple[str, ...] = ()
    filters: tuple[Clause, ...] = ()
    time_grain: TimeGrain | None = None
    order_by: tuple[OrderSpec, ...] = ()
    limit: int | None = None

    # ....................... #

    def __post_init__(self) -> None:
        if not self.metrics:
            raise InvalidRequest("a request needs at least one metric")

        for kind, names in (("metric", self.metrics), ("dimension", self.dimensions)):
            duplicates = sorted({n for n in names if names.count(n) > 1})
            if duplicates:
                raise InvalidRequest(f"duplicate {kind}(s) in request: {duplicates}")

        for clause in self.filters:
            _check_clause(clause)

        if self.limit is not None and self.limit < 1:
            raise InvalidRequest(f"limit must be >= 1, got {self.limit}")

        allowed = set(self.metrics) | set(self.dimensions)

        for spec in self.order_by:
            if spec.field not in allowed:
                msg = (
                    f"order_by field {spec.field!r} is not a requested metric or "
                    "dimension — arbitrary order expressions are refused (S-0028/D-4)"
                )
                raise InvalidRequest(msg)
