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
from typing import Annotated

from pydantic import Discriminator, Field, Tag

from bloomery.spec.common import (
    MaterializationName,
    MemberName,
    PartitionSpecString,
    SpecModel,
)

__all__ = [
    "DateRoleStep",
    "FlattenStep",
    "Mart",
    "MartSet",
    "ViaStep",
]


class ViaStep(SpecModel):
    """Flatten one declared relationship into the mart, prefixing every
    flattened column with ``prefix`` (RFC 0010 D3 — prefixes mandatory)."""

    via: str
    prefix: str


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


class Mart(SpecModel):
    """One wide mart: base entity, authored-order flatten steps (order is
    meaningful — chains flatten transitively, RFC 0010 §5.1), measures,
    partitioning, and the tie-breaking ``cost_hint`` (RFC 0010 D8)."""

    grain: str
    base: str
    flatten: tuple[FlattenStep, ...] = ()
    measures: tuple[str, ...] = ()
    partition_by: tuple[PartitionSpecString, ...] = ()
    materialization: MaterializationName | None = None
    cost_hint: int = Field(default=1, ge=1)


class MartSet(SpecModel):
    """The per-project marts document (``marts_version``), at most one per
    project, optional — a project without marts compiles silver only
    (RFC 0010 D7)."""

    marts_version: int = Field(ge=1)
    marts: dict[MemberName, Mart]
