"""The ``MartSet`` spec kind (RFC 0010 §5.1; RFC 0002 D9).

The wide-mart gold layer: one mart per (grain × subject area), flattened at
build time. ``flatten`` steps are a discriminated union on ``via`` vs ``date``:
a ``via:`` step names a declared relationship and a mandatory column prefix; a
``date:`` step declares a role-playing time dimension expanded into
``<role>_<bucket>`` columns. Shape-only at parse — relationship existence,
cardinality, grain equality, and collision checks are compile-stage validation
(RFC 0010 §5.5).
"""

from __future__ import annotations

from collections.abc import Mapping as AbcMapping
from typing import Annotated, Literal, Self

from pydantic import Discriminator, Field, Tag, model_validator

from bloomery.spec.common import (
    MaterializationName,
    MemberName,
    PartitionSpecString,
    SpecModel,
)
from bloomery.spec.quality import RangeBound, RuleName

__all__ = [
    "DateRoleStep",
    "FlattenStep",
    "Mart",
    "MartAggregate",
    "MartAssert",
    "MartSet",
    "ViaStep",
]


class ViaStep(SpecModel):
    """Flatten one declared relationship into the mart, prefixing every
    flattened column with ``prefix`` (RFC 0010 D3 — prefixes mandatory,
    so an empty prefix is a parse error, not a silent no-op)."""

    via: str
    prefix: str = Field(min_length=1)


class DateRoleStep(SpecModel):
    """Declare a role-playing time dimension: ``{date: order_date, role:
    ordered}`` expands to ``ordered_day`` … ``ordered_year`` (RFC 0010 D4).
    ``metric_time`` is reserved as a role name (RFC 0002 D10)."""

    date: str
    role: MemberName


def _flatten_tag(value: object) -> str:
    if isinstance(value, AbcMapping) and "via" in value:
        return "via"
    if isinstance(value, ViaStep):
        return "via"
    return "date"


FlattenStep = Annotated[
    Annotated[ViaStep, Tag("via")] | Annotated[DateRoleStep, Tag("date")],
    Discriminator(_flatten_tag),
]
"""Discriminated union on ``via`` vs ``date`` (RFC 0010 §5.1)."""


#: The aggregates a mart assertion may take. Deliberately the **same** closed
#: vocabulary the ``reconcile`` grammar uses (RFC 0016 §5.3): both compute one
#: number over a column so a human can be told it is wrong, and two lists that
#: mean the same thing drift.
MartAggregate = Literal["avg", "count", "max", "min", "sum"]


class MartAssert(SpecModel):
    """One aggregate assertion over a mart (RFC 0016 D89) — §10's "no month has
    zero revenue", made declarable.

    **Why this is an assertion and not a quality rule.** §5.9 draws the line at
    what a verdict *does*: a quality rule disposes of a row. A mart row is
    derived — it has no ``_source_row_id``, no bronze payload, no reject table
    and no replay — so there is nothing to quarantine, nothing to repair, and
    nothing to bring back. What is left is D4's other half, "alert me", which
    is `assert:`. §10 asked whether mart-level rules were reconcile-shaped or a
    new surface; they are neither, and the disposition model is what separates
    them from both.

    ``by`` groups the aggregate; empty means one group over the whole mart.
    Bounds carry the exact-decimal/ISO string form for the same reason
    ``range`` does — a YAML float never reaches the IR (RFC 0003 D5).

    **What it cannot see, stated:** a group with no rows produces no row to
    aggregate, so an assertion over a mart cannot notice a month that is
    entirely *missing* — only one whose total is out of bounds. Closing that
    needs a join against the date spine, which is a different check with a
    different dependency (RFC 0016 D89).
    """

    name: RuleName
    measure: str
    agg: MartAggregate
    by: tuple[str, ...] = ()
    min: RangeBound | None = None
    max: RangeBound | None = None
    #: ``fail`` blocks the run; ``flag`` emits a non-blocking audit — the same
    #: two readings ``reconcile.on_fail`` carries (RFC 0016 D38). ``quarantine``
    #: and ``repair`` are absent rather than lowered to something weaker:
    #: neither has a meaning without a row to route.
    on_fail: Literal["flag", "fail"]

    @model_validator(mode="after")
    def _at_least_one_bound(self) -> Self:
        if self.min is None and self.max is None:
            msg = "a mart assertion needs at least one of min / max"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _by_is_a_set(self) -> Self:
        if len(set(self.by)) != len(self.by):
            msg = f"assertion {self.name!r} repeats a by: column — each names one grouping level"
            raise ValueError(msg)
        return self


class Mart(SpecModel):
    """One wide mart: base entity, authored-order flatten steps (order is
    meaningful — chains flatten transitively, RFC 0010 §5.1), measures,
    partitioning, aggregate assertions, and the tie-breaking ``cost_hint``
    (RFC 0010 D8)."""

    grain: str
    base: str
    flatten: tuple[FlattenStep, ...] = ()
    measures: tuple[str, ...] = ()
    partition_by: tuple[PartitionSpecString, ...] = ()
    materialization: MaterializationName | None = None
    assert_: tuple[MartAssert, ...] = Field(default=(), alias="assert")
    cost_hint: int = Field(default=1, ge=1)


class MartSet(SpecModel):
    """The per-project marts document (``marts_version``), at most one per
    project, optional — a project without marts compiles silver only
    (RFC 0010 D7)."""

    marts_version: int = Field(ge=1)
    marts: dict[MemberName, Mart]
