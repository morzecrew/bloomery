"""Shared pieces of the three-way equivalence tier (RFC 0009 §5.8).

Two engines answer the same request in two shapes: MetricFlow's SQL returns
driver rows, Cube returns JSON with qualified member names and stringified
numbers. Comparing them needs one normal form, and it lives here rather than in
the test module so the *comparison* stays reviewable separately from the
assertions built on it — a normalizer that quietly collapsed distinct keys
would make every assertion pass, which is why the test module keeps a control
for exactly that.

The seeds live here too. They are chosen to make the comparison capable of
failing: several rows per group so a sum is not the identity, more than one
group so a grouping error is visible, and — for the ratio fixture — groups
whose *sizes differ*, because a ratio computed the wrong way (averaging stored
per-row ratios instead of dividing summed components) agrees with the right one
on equal-sized groups and only on those.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from bloomery import MetricRequest

__all__ = [
    "SEEDS",
    "Seed",
    "as_frame",
    "cube_query",
    "normalize_key",
]


@dataclass(frozen=True, slots=True)
class Seed:
    """The mart a fixture's requests read, and the rows in it."""

    mart: str
    rows: tuple[tuple[Any, ...], ...]


#: ``ecom_basic.order_items`` columns, in ``MartIR`` order: line_no,
#: order_customer_id, order_date, order_id, order_order_id, ordered_day,
#: ordered_month, ordered_quarter, ordered_week, ordered_year, quantity,
#: unit_price.
_ECOM = (
    (1, "c1", "2024-01-02", "o1", "o1", "2024-01-02", "2024-01-01", "2024-01-01",
     "2024-01-01", "2024-01-01", 2, Decimal("10.0000")),
    (2, "c1", "2024-01-03", "o1", "o1", "2024-01-03", "2024-01-01", "2024-01-01",
     "2024-01-01", "2024-01-01", 3, Decimal("5.0000")),
    (1, "c2", "2024-02-05", "o2", "o2", "2024-02-05", "2024-02-01", "2024-01-01",
     "2024-02-05", "2024-01-01", 1, Decimal("20.0000")),
    (2, "c2", "2024-02-06", "o2", "o2", "2024-02-06", "2024-02-01", "2024-01-01",
     "2024-02-05", "2024-01-01", 4, Decimal("2.5000")),
)  # fmt: skip

#: ``non_additive_aov.orders`` columns: amount, order_date, order_id,
#: ordered_day, ordered_month, ordered_quarter, ordered_week, ordered_year,
#: store.
#:
#: **Deliberately unequal group sizes.** ``north`` has three orders and
#: ``south`` has one; January has two and February two but with different
#: totals. A ratio averaged from per-row values agrees with a ratio of sums
#: whenever the groups are the same size, so equal-sized groups would let the
#: wrong arithmetic pass.
_AOV = (
    (Decimal("100.0000"), "2024-01-02", "o1", "2024-01-02", "2024-01-01",
     "2024-01-01", "2024-01-01", "2024-01-01", "north"),
    (Decimal("50.0000"), "2024-01-09", "o2", "2024-01-09", "2024-01-01",
     "2024-01-01", "2024-01-08", "2024-01-01", "north"),
    (Decimal("30.0000"), "2024-02-03", "o3", "2024-02-03", "2024-02-01",
     "2024-01-01", "2024-02-05", "2024-01-01", "north"),
    (Decimal("90.0000"), "2024-02-07", "o4", "2024-02-07", "2024-02-01",
     "2024-01-01", "2024-02-05", "2024-01-01", "south"),
)  # fmt: skip

SEEDS: dict[str, Seed] = {
    "ecom_basic": Seed(mart="order_items", rows=_ECOM),
    "non_additive_aov": Seed(mart="orders", rows=_AOV),
}


def normalize_key(value: Any) -> str:
    """One spelling for a dimension value, whichever engine produced it.

    A date arrives from psycopg as ``datetime.date`` and from Cube as
    ``'2024-01-01T00:00:00.000'``; both mean the same group. Everything else is
    compared as its string form. The mapping is deliberately *narrow* — it
    normalizes a rendering difference and nothing else, so two genuinely
    different groups stay different (the test module asserts precisely that).
    """
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value)
    if "T" in text:
        head, _, _tail = text.partition("T")
        return head
    return text


def _as_number(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:  # pragma: no cover — a non-numeric measure is a bug
        msg = f"measure value {value!r} is not a number"
        raise AssertionError(msg) from None


def as_frame(
    rows: Sequence[Sequence[Any]], dimension_count: int
) -> dict[tuple[str, ...], Decimal | None]:
    """Driver rows as ``{(dimension values…): measure}``.

    Positional: the first ``dimension_count`` columns are the grouping key and
    the last is the measure. That is the binding the planner's result actually
    supports — its ``columns`` descriptors carry the *requested* dimension
    names while MetricFlow aliases them its own way (RFC 0009 D24).
    """
    return {
        tuple(normalize_key(cell) for cell in row[:dimension_count]): _as_number(row[-1])
        for row in rows
    }


class _CubeQuery:
    """Translate a corpus entry into a Cube query and back into a frame."""

    @staticmethod
    def request(entry: dict[str, Any]) -> MetricRequest:
        return MetricRequest(
            metrics=tuple(entry["metrics"]), dimensions=tuple(entry["dimensions"])
        )

    @staticmethod
    def frame(stack: Any, entry: dict[str, Any]) -> dict[tuple[str, ...], Decimal | None]:
        cube = SEEDS[entry["fixture"]].mart
        # The *last* metric is the one compared, mirroring ``as_frame``'s
        # "measure is the final column" — a multi-metric request is checked one
        # measure at a time rather than by hoping two engines order columns
        # alike.
        measure = entry["metrics"][-1]
        rows = stack.load(
            {
                "measures": [f"{cube}.{measure}"],
                "dimensions": [f"{cube}.{name}" for name in entry["dimensions"]],
            }
        )
        return {
            tuple(normalize_key(row[f"{cube}.{name}"]) for name in entry["dimensions"]): (
                _as_number(row[f"{cube}.{measure}"])
            )
            for row in rows
        }


cube_query = _CubeQuery()
