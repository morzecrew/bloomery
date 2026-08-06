"""The ``Catalog`` spec kind (RFC 0002 §5.5; original spec §3.2).

Domain knowledge, one per vertical: canonical fields with derivation recipes
and unit/tax-basis metadata, canonical relationships, and metric templates.
Authored by the operator, deliberately not part of :class:`Project`
(RFC 0002 D8) — it is passed separately to compile/resolve.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from bloomery.spec.common import (
    AdditivityName,
    CardinalityName,
    CurrencyCode,
    RatioSpec,
    SemiAdditivePolicy,
    SpecModel,
    TypeString,
)

__all__ = [
    "Catalog",
    "CanonicalField",
    "CanonicalRelationship",
    "MetricTemplate",
    "Recipe",
]


class Recipe(SpecModel):
    """One alternative derivation path to a canonical field, ordered by
    reliability in the catalog; the compiler validates recorded choices but
    never chooses (RFC 0005 D2)."""

    id: str
    requires: tuple[str, ...]
    expr: str | None = None


class CanonicalField(SpecModel):
    """A canonical domain field: its home entity, logical type, monetary
    metadata (drives the guardrails, RFC 0006 §5.2), and recipes."""

    entity: str
    type: TypeString
    unit: Literal["currency", "count"] | None = None
    tax_basis: Literal["net", "gross", "unknown"] | None = None
    currency: CurrencyCode | None = None
    recipes: tuple[Recipe, ...] = ()


class CanonicalRelationship(SpecModel):
    """A canonical relationship between two catalog entities."""

    from_: str = Field(alias="from")
    to: str
    via: str
    cardinality: CardinalityName


class MetricTemplate(SpecModel):
    """A catalog-level metric template a project metric may instantiate via
    ``template:`` (RFC 0002 §5.5)."""

    requires: tuple[str, ...] = ()
    requires_metrics: tuple[str, ...] = ()
    grain: str | None = None
    additivity: AdditivityName
    agg: str | None = None
    expr: str | None = None
    ratio: RatioSpec | None = None
    semi_additive: SemiAdditivePolicy | None = None


class Catalog(SpecModel):
    """The vertical-level domain catalog (original spec §3.2), loaded via
    :func:`bloomery.load_catalog`."""

    catalog_version: int = Field(ge=1)
    vertical: str
    canonical_fields: dict[str, CanonicalField] = Field(default_factory=dict)
    canonical_relationships: tuple[CanonicalRelationship, ...] = ()
    metric_templates: dict[str, MetricTemplate] = Field(default_factory=dict)
