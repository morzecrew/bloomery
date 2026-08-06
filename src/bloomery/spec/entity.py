"""The ``EntityModel`` spec kind (RFC 0002 §5.5; original spec §3.3).

What a project's data means: entities with grain, key, SCD kind, partitioning,
optional explicit materialization (RFC 0002 D7 — explicit-with-derived-default),
typed fields with optional ``canonical:`` links and ``assert:`` clauses
(RFC 0006 D8), and relationships with cardinality.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field as PydanticField

from bloomery.spec.common import (
    CardinalityName,
    MaterializationName,
    MemberName,
    PartitionSpecString,
    SpecModel,
    TypeString,
)

__all__ = [
    "AssertClause",
    "Entity",
    "EntityModel",
    "Field",
    "Relationship",
]


class AssertClause(SpecModel):
    """Per-field range-sanity assertions (RFC 0006 D8 / §5.6): validated for
    well-typedness at the guardrail stage, lowered to target-native audits at
    emit. Shape-only here."""

    min: int | Decimal | str | None = None
    max: int | Decimal | str | None = None
    not_null: bool | None = None
    enum: tuple[str | int, ...] | None = None
    regex: str | None = None


class Field(SpecModel):
    """One entity field: logical type (grammar-validated string at parse,
    RFC 0002 §5.5), optional catalog link, explicit-rename annotation
    (RFC 0007 D3), and assert clauses."""

    type: TypeString
    required: bool = False
    canonical: str | None = None
    renamed_from: str | None = None
    assert_: AssertClause | None = PydanticField(default=None, alias="assert")


class Entity(SpecModel):
    """One entity: grain, authored-order key, SCD kind, partitioning, optional
    explicit materialization, and named fields (``metric_time`` reserved,
    RFC 0002 D10)."""

    grain: str
    key: tuple[str, ...] = PydanticField(min_length=1)
    scd: Literal["type1", "type2"] = "type1"
    partition_by: tuple[PartitionSpecString, ...] = ()
    materialization: MaterializationName | None = None
    fields: dict[MemberName, Field]


class Relationship(SpecModel):
    """A declared relationship between two entities; ``via`` maps from-side
    columns to to-side columns."""

    name: str
    from_: str = PydanticField(alias="from")
    to: str
    via: dict[str, str]
    cardinality: CardinalityName


class EntityModel(SpecModel):
    """The per-project entity model document (``spec_version``), exactly one
    per project (RFC 0002 §5.5)."""

    spec_version: int = PydanticField(ge=1)
    entities: dict[str, Entity]
    relationships: tuple[Relationship, ...] = ()
