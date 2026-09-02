"""The ``Catalog`` spec kind (RFC 0002 §5.5; original spec §3.2).

Domain knowledge, one per vertical: canonical fields with derivation recipes
and unit/tax-basis metadata, canonical relationships, and metric templates.
Authored by the operator, deliberately not part of :class:`Project`
(RFC 0002 D8) — it is passed separately to compile/resolve.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from bloomery.spec.common import (
    AdditivityName,
    CardinalityName,
    CurrencyCode,
    MemberName,
    RatioSpec,
    RelationName,
    SemiAdditivePolicy,
    SpecModel,
    TypeString,
)

# ----------------------- #

__all__ = [
    "Catalog",
    "CanonicalField",
    "CanonicalRelationship",
    "DateDimension",
    "FxRates",
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


# ....................... #


class CanonicalField(SpecModel):
    """A canonical domain field: its home entity, logical type, monetary
    metadata (drives the guardrails, RFC 0006 §5.2), and recipes. The optional
    ``description`` is carried through the IR into semantic-layer emissions
    (RFC 0013 R1) — it grounds the Query Agent."""

    entity: str
    type: TypeString
    description: str | None = None
    unit: Literal["currency", "count"] | None = None
    tax_basis: Literal["net", "gross", "unknown"] | None = None
    currency: CurrencyCode | None = None
    recipes: tuple[Recipe, ...] = ()


# ....................... #


class CanonicalRelationship(SpecModel):
    """A canonical relationship between two catalog entities."""

    from_: str = Field(alias="from")
    to: str
    via: str
    cardinality: CardinalityName


# ....................... #


class DateDimension(SpecModel):
    """The vertical-owned date dimension (RFC 0008 D13, RFC 0013 R1 rule 4):
    one catalog definition drives both the emitted gold ``dim_date`` model and
    the MetricFlow time-spine declaration (M6). Bounds are calendar years —
    the emitted table depends on the spec only, never on a clock."""

    name: str = "dim_date"
    grain: Literal["day"] = "day"
    start_year: int = Field(ge=1, le=9999)
    end_year: int = Field(ge=1, le=9999)

    # ....................... #

    @model_validator(mode="after")
    def _ordered_bounds(self) -> DateDimension:
        if self.end_year < self.start_year:
            msg = "end_year must be >= start_year"
            raise ValueError(msg)

        return self


# ....................... #


class FxRates(SpecModel):
    """The dated exchange-rate relation the ``convert`` transform reads
    (RFC 0023 §5.4).

    Reference data, which is why it is a catalog concern rather than an
    entity: nobody maps it, it has no grain bloomery owns, and it is shared by
    every project the vertical serves. What is declared here is the *shape* of
    a table the operator supplies — bloomery reads it and never builds it.

    ``relation`` is a bare name resolved through the naming policy at the
    silver layer, not a namespaced one. A hard-coded ``silver.fx_rate`` would
    pass :class:`~bloomery.naming.PrefixNaming` unchanged and read a relation
    outside the namespace everything else in the project was scoped into — the
    one thing a naming policy exists to prevent (RFC 0008 §5.1).

    **Both interval ends are required, and that is the whole design** (D11).
    One end is not an interval: a fact row would match every rate at or before
    its anchor, and the conversion would multiply rather than convert — the
    same fan-out :class:`~bloomery.errors.HistoricalFanout` refuses on the
    other side of this RFC. Deriving the upper bound with ``LEAD(valid_from)``
    was rejected for making every conversion a window function over the whole
    rate table, and for extending the newest rate to infinity, so that a stale
    feed converts at last week's rate instead of failing.
    """

    relation: RelationName
    from_: MemberName = Field(alias="from")
    to: MemberName
    rate: MemberName
    valid_from: MemberName
    valid_to: MemberName

    # ....................... #

    @model_validator(mode="after")
    def _distinct_columns(self) -> FxRates:
        names = (self.from_, self.to, self.rate, self.valid_from, self.valid_to)
        if len(set(names)) != len(names):
            duplicated = sorted({name for name in names if names.count(name) > 1})
            msg = (
                f"fx_rates names the same column for more than one role: {duplicated} — "
                "each of from/to/rate/valid_from/valid_to reads a different column of the "
                "rate relation, and a shared name makes the emitted predicate compare a "
                "column against itself"
            )
            raise ValueError(msg)

        return self


# ....................... #


class MetricTemplate(SpecModel):
    """A catalog-level metric template a project metric may instantiate via
    ``template:`` (RFC 0002 §5.5). ``description`` merges like every other
    template value: the metric's own wins, the template's is the fallback."""

    description: str | None = None
    requires: tuple[str, ...] = ()
    requires_metrics: tuple[str, ...] = ()
    grain: str | None = None
    additivity: AdditivityName
    agg: str | None = None
    expr: str | None = None
    ratio: RatioSpec | None = None
    semi_additive: SemiAdditivePolicy | None = None


# ....................... #


class Catalog(SpecModel):
    """The vertical-level domain catalog (original spec §3.2), loaded via
    :func:`bloomery.load_catalog`."""

    #: Pinned to the one version bloomery implements (RFC 0018 D7). It was
    #: ``int`` with ``ge=1``, which accepted a document written for a future
    #: bloomery and silently applied v1 semantics to it — the exact misreading
    #: a version key exists to refuse. This key is also the document-kind
    #: discriminator, so it stays required: a document without one cannot be
    #: identified at all.
    catalog_version: Literal[1]
    vertical: str
    canonical_fields: dict[str, CanonicalField] = Field(default_factory=dict)
    canonical_relationships: tuple[CanonicalRelationship, ...] = ()
    metric_templates: dict[str, MetricTemplate] = Field(default_factory=dict)
    date_dimension: DateDimension | None = None
    #: Absent for every vertical that never converts. Its absence is what the
    #: ``convert`` refusal names (RFC 0023 §5.4): the transform stays legal,
    #: typechecks, and is refused at emit until a rate relation is declared.
    fx_rates: FxRates | None = None
