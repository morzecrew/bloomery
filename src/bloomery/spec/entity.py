"""The ``EntityModel`` spec kind (S-0019/spec-model-surface; original spec §3.3).

What a project's data means: entities with grain, key, SCD kind, partitioning,
optional explicit materialization (S-0019/D-7 — explicit-with-derived-default),
typed fields with optional ``canonical:`` links and ``assert:`` clauses
(S-0023/D-8), relationships with cardinality, and the entity-level data-
quality surface — ``quality:`` row rules, ``dedupe:``, ``quarantine:`` — plus
the document-level ``reconcile:`` list (S-0033/spec-schema).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field as PydanticField

from bloomery.spec.common import (
    CardinalityName,
    ClassificationName,
    Grants,
    MaterializationName,
    MemberName,
    PartitionSpecString,
    RelationName,
    SeedsRefusal,
    SpecModel,
    TypeString,
)
from bloomery.spec.quality import Coverage, Dedupe, EntityQualityRule, Quarantine, Reconcile

# ----------------------- #

__all__ = [
    "AssertClause",
    "Entity",
    "EntityModel",
    "Field",
    "Relationship",
]


class AssertClause(SpecModel):
    """Per-field range-sanity assertions (S-0023/D-8, S-0023/range-sanity): validated for
    well-typedness at the guardrail stage, lowered to target-native audits at
    emit. Shape-only here."""

    min: int | Decimal | str | None = None
    max: int | Decimal | str | None = None
    not_null: bool | None = None
    enum: tuple[str | int, ...] | None = None
    regex: str | None = None


# ....................... #


class Field(SpecModel):
    """One entity field: logical type (grammar-validated string at parse,
    S-0019/spec-model-surface), optional catalog link, explicit-rename annotation
    (S-0024/D-3), and assert clauses."""

    type: TypeString
    required: bool = False
    canonical: str | None = None
    renamed_from: str | None = None
    assert_: AssertClause | None = PydanticField(default=None, alias="assert")
    #: What class of data this column holds (S-0062/classification), from a closed
    #: vocabulary. Reaches target metadata, and marks a `pii` or `secret`
    #: column `public: false` on Cube — which hides it from Cube's own UIs and
    #: leaves it queryable by anything that names it (measured; see
    #: `tests/e2e/test_cube_meta.py`).
    #:
    #: **A declaration bloomery does not verify.** Nothing is masked, nothing is
    #: encrypted, and a column marked `public` that is not reads exactly like
    #: one that is. It is also never a place to put a secret *value*: this names
    #: a column, it never carries one.
    classification: ClassificationName | None = None


# ....................... #


class Entity(SpecModel):
    """One entity: grain, authored-order key, SCD kind, partitioning, optional
    explicit materialization, named fields (generated names reserved,
    S-0019/D-10 / S-0033/schema-additions-and-the-array-capability), and the entity-level quality surface.

    ``dedupe`` partitions by this entity's ``key``; ``quality`` holds the row
    rules (``expression``, ``referential``); ``quarantine`` governs the
    ``<entity>__reject`` table (S-0033/spec-schema, S-0033/quarantine-one-reject-table-per-entity).
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
    #: Who is responsible for this, as a free string (S-0062/owner). Reaches
    #: every target's owner slot and changes no SQL.
    #:
    #: **A declaration bloomery does not verify.** Nobody is paged, the name is
    #: not checked against a directory, and an owner who has left reads exactly
    #: like one who has not. Not validated as an email, a handle or a team name
    #: either (D8): every project spells this differently, and a format rule
    #: would refuse spellings that are correct for their reader.
    owner: str | None = None
    #: Who may read the relation this becomes (S-0062/grants). Unlike the two
    #: annotations above, this one is **applied** — by the framework, on the
    #: engine — so being wrong changes who can read data.
    grants: Grants | None = None


# ....................... #


class Relationship(SpecModel):
    """A declared relationship between two entities; ``via`` maps from-side
    columns to to-side columns."""

    name: str
    from_: str = PydanticField(alias="from")
    to: str
    #: At least one column pair, the same way ``Entity.key`` requires at least
    #: one column. A relationship *is* its join, so ``via: {}`` describes
    #: nothing — and every consumer reads it as a non-empty list. Left open, an
    #: empty mapping parsed cleanly and then crashed at emit, differently in
    #: each place that reads it: ``IndexError`` from the coverage audit's
    #: ``conjunction([])``, and ``ValueError: not enough values to unpack``
    #: from inside SQLGlot when a mart flattened it. Three unhelpful
    #: exceptions with no source path, for one shape question parse can settle
    #: (S-0019/D-4 — shape is exactly what parse is for).
    via: dict[str, str] = PydanticField(min_length=1)
    cardinality: CardinalityName
    #: The artifact this relationship was read out of, where it was not
    #: authored here (S-0075/D-7). Its **presence** is the fact: a
    #: relationship carrying it is `IMPORTED_VERIFIED` and one without it is
    #: `DECLARED`. A string rather than a boolean because the refusal that
    #: reads it has to name the artifact for a reader to act on, and a boolean
    #: would need a second key to do that.
    #:
    #: Written by an importer, not by hand. There is no way for the compiler
    #: to tell the difference, and S-0075/risks says so rather than implying a
    #: check that does not exist.
    #:
    #: Non-empty for the reason ``via`` is: presence is the fact, and an empty
    #: string is present while naming nothing — it would lower the
    #: relationship's grade and then produce a refusal citing ``''`` as the
    #: artifact, which is a worse answer than either accepting or refusing
    #: outright. Shape is what parse is for (S-0019/D-4).
    imported_from: str | None = PydanticField(default=None, min_length=1)


# ....................... #


class EntityModel(SpecModel):
    """The per-project entity model document (``spec_version``), exactly one
    per project (S-0019/spec-model-surface).

    ``reconcile:`` sits here, at the document root, exactly where S-0033
    §5.3's YAML puts it — a sibling of ``entities:``, not a member of one.
    That placement is the schema, not a convenience: a reconcile check relates
    *two* entities (``sum(order_item.line_total) by order_id`` against
    ``order.total_amount``), so it belongs to no single entity, and this is the
    one document a project is guaranteed to have exactly one of.
    """

    #: Pinned to the one version bloomery implements (S-0035/D-7). It was
    #: ``int`` with ``ge=1``, which accepted a document written for a future
    #: bloomery and silently applied v1 semantics to it — the exact misreading
    #: a version key exists to refuse. This key is also the document-kind
    #: discriminator, so it stays required: a document without one cannot be
    #: identified at all.
    spec_version: Literal[1]
    #: Declared in order to be refused (S-0062/D-7). See
    #: :func:`~bloomery.spec.common._refuse_seeds`: a seed is data in the
    #: repository, and the answer an author needs is "never", not "unknown key".
    seeds: SeedsRefusal = None
    entities: dict[RelationName, Entity]
    relationships: tuple[Relationship, ...] = ()
    reconcile: tuple[Reconcile, ...] = ()
    #: Cross-entity coverage checks (S-0033/D-90). Beside ``reconcile:`` for
    #: the same reason it is there: a check that relates two entities belongs
    #: to neither of them.
    coverage: tuple[Coverage, ...] = ()
