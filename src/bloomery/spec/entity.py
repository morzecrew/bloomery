"""The ``EntityModel`` spec kind (RFC 0002 §5.5; original spec §3.3).

What a project's data means: entities with grain, key, SCD kind, partitioning,
optional explicit materialization (RFC 0002 D7 — explicit-with-derived-default),
typed fields with optional ``canonical:`` links and ``assert:`` clauses
(RFC 0006 D8), relationships with cardinality, and the entity-level data-
quality surface — ``quality:`` row rules, ``dedupe:``, ``quarantine:`` — plus
the document-level ``reconcile:`` list (RFC 0016 §5.3).
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
from bloomery.spec.quality import Coverage, Dedupe, EntityQualityRule, Quarantine, Reconcile

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
    explicit materialization, named fields (generated names reserved,
    RFC 0002 D10 / RFC 0016 §5.5), and the entity-level quality surface.

    ``dedupe`` partitions by this entity's ``key``; ``quality`` holds the row
    rules (``expression``, ``referential``); ``quarantine`` governs the
    ``<entity>__reject`` table (RFC 0016 §5.3, §5.6).
    """

    grain: str
    key: tuple[str, ...] = PydanticField(min_length=1)
    scd: Literal["type1", "type2"] = "type1"
    partition_by: tuple[PartitionSpecString, ...] = ()
    materialization: MaterializationName | None = None
    fields: dict[MemberName, Field]
    quality: tuple[EntityQualityRule, ...] = ()
    dedupe: Dedupe | None = None
    quarantine: Quarantine | None = None


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
    per project (RFC 0002 §5.5).

    ``reconcile:`` sits here, at the document root, exactly where RFC 0016
    §5.3's YAML puts it — a sibling of ``entities:``, not a member of one.
    That placement is the schema, not a convenience: a reconcile check relates
    *two* entities (``sum(order_item.line_total) by order_id`` against
    ``order.total_amount``), so it belongs to no single entity, and this is the
    one document a project is guaranteed to have exactly one of.
    """

    spec_version: int = PydanticField(ge=1)
    entities: dict[str, Entity]
    relationships: tuple[Relationship, ...] = ()
    reconcile: tuple[Reconcile, ...] = ()
    #: Cross-entity coverage checks (RFC 0016 D90). Beside ``reconcile:`` for
    #: the same reason it is there: a check that relates two entities belongs
    #: to neither of them.
    coverage: tuple[Coverage, ...] = ()
