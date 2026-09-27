"""The authored retrieval document (S-0011/a-separate-spec-kind, S-0011/D-1).

Its own spec kind, loaded by its own ``retrieval_version`` key, rather than
optional keys on the entity model: ``spec_version: 1`` is a promise that a
document which loads keeps loading, and every optional key added there is a key
every future reader of every entity model has to know about. A separate kind is
invisible to a project that does not use it and versions on its own clock.

Two declarations live here. A **semantic space** is a named, reusable claim
about a vector's shape — its dimensions, its scalar type, its distance, and the
opaque identities of the encoders that produce it. A **retrieval profile** names
a corpus relation, its grain, its vector side, its optional lexical side, its
filters and its projection.

An encoder identity is an opaque string compared for equality (S-0011/D-2).
bloomery does not know what ``text-embedding-3-small`` is, cannot verify it
exists, and must never look it up: a compile that consulted a provider would
read the network. What the identity buys is one comparison — two things claiming
the same space must name the same producer.

The refusals that need the project's relations are guardrails
(:mod:`bloomery.guardrails.retrieval`). What this module refuses is what a
document can say at all.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from bloomery.spec.common import (
    IDENTIFIER_PATTERN,
    DimensionName,
    RelationName,
    SpecModel,
)

# ----------------------- #

__all__ = [
    "CorpusRelation",
    "DistanceName",
    "Encoder",
    "Fusion",
    "LexicalSide",
    "RetrievalProfile",
    "RetrievalSpec",
    "ScalarName",
    "SemanticSpace",
    "SpaceName",
    "VectorSide",
]

#: A space's name and a profile's name. Held to the bare-identifier shape for
#: the reason :data:`~bloomery.spec.common.DimensionName` is: both are
#: interpolated by a retrieval runtime that quotes nothing, not rendered through
#: SQLGlot.
SpaceName = Annotated[str, StringConstraints(pattern=IDENTIFIER_PATTERN)]

#: The vector scalar vocabulary, closed and mirroring the
#: ``vector(<scalar>, <dimensions>)`` half of
#: :data:`~bloomery.spec.common.TYPE_STRING_PATTERN` (S-0011/D-3). A *name*,
#: never a float value.
ScalarName = Literal["float32", "float16"]

#: How closeness is measured in a space (S-0011/D-12: the property belongs to
#: the space, not the profile — every field claiming one space is scored the
#: same way). Closed, because a value nobody uses costs nothing and a value
#: someone relies on cannot be taken back.
DistanceName = Literal["cosine", "dot", "l2"]


class Encoder(SpecModel):
    """The opaque identity of one encoder (S-0011/D-2).

    Three strings, compared for equality and resolved against nothing.
    ``input_kind`` is the half a dimension check cannot see: on an asymmetric
    model, a query encoded as a document agrees about dimensions and is still
    the wrong vector.
    """

    family: str = Field(min_length=1)
    model: str = Field(min_length=1)
    input_kind: Literal["document", "query"]


# ....................... #


class SemanticSpace(SpecModel):
    """One named space a vector can live in (S-0011/a-separate-spec-kind)."""

    #: Bounded to the five digits the type-string grammar admits, so a space and
    #: a field type can always be compared rather than one being unspellable.
    dimensions: int = Field(ge=1, le=99999)
    scalar: ScalarName
    distance: DistanceName
    document_encoder: Encoder
    query_encoder: Encoder

    # ....................... #

    @model_validator(mode="after")
    def _encoders_are_on_their_own_sides(self) -> Self:
        """Each encoder declares the side it is declared under.

        A space whose ``query_encoder`` says ``input_kind: document`` reads as
        if it were symmetric while saying it is not, and every downstream
        comparison of the two identities would then be comparing the wrong
        pair.
        """

        for key, encoder, expected in (
            ("document_encoder", self.document_encoder, "document"),
            ("query_encoder", self.query_encoder, "query"),
        ):
            if encoder.input_kind != expected:
                msg = (
                    f"{key} declares 'input_kind: {encoder.input_kind}'. "
                    f"Fix: an encoder under '{key}' must declare "
                    f"'input_kind: {expected}'"
                )
                raise ValueError(msg)

        return self


# ....................... #


class CorpusRelation(SpecModel):
    """The relation a profile retrieves from — one of a mart or an entity.

    Two keys rather than one string, because the two namespaces are separate:
    a bare name would make ``support_search`` ambiguous the moment a project
    has both.
    """

    mart: RelationName | None = None
    entity: RelationName | None = None

    # ....................... #

    @model_validator(mode="after")
    def _exactly_one_relation(self) -> Self:
        named = [key for key, value in (("mart", self.mart), ("entity", self.entity)) if value]

        if len(named) != 1:
            msg = (
                f"a profile's relation names {len(named)} relations "
                f"({', '.join(named) or 'none'}). Fix: name exactly one of 'mart' or 'entity'"
            )
            raise ValueError(msg)

        return self


# ....................... #


class VectorSide(SpecModel):
    """The vector half of a profile: which field, in which space."""

    field: DimensionName
    space: SpaceName
    #: What produced the values in this field, when the author knows it. Its
    #: presence buys the one refusal dimensions cannot give: agreeing about
    #: shape is not agreeing about space (S-0011/D-2). Declared here rather
    #: than on the entity field, because retrieval ships as its own kind and
    #: adds no keys to the entity model (S-0011/D-1).
    producer: Encoder | None = None


# ....................... #


class LexicalSide(SpecModel):
    """The lexical half of a profile: the text fields a keyword query reads."""

    fields: tuple[DimensionName, ...] = Field(min_length=1)


# ....................... #


class Fusion(SpecModel):
    """How the two sides combine (S-0011/D-5).

    Reciprocal rank fusion only, refused by the grammar rather than later: RRF
    combines *ranks*, so it needs no shared scale between a lexical score and a
    cosine similarity. A weighted method would need one, and there is no
    defensible default for it.
    """

    method: Literal["rrf"]


# ....................... #


class RetrievalProfile(SpecModel):
    """One declared retrieval surface (S-0011/the-guardrails)."""

    relation: CorpusRelation
    #: One vector per retrievable item, checked against the corpus relation's
    #: key by the guardrail stage (S-0011/D-8).
    grain: tuple[DimensionName, ...] = Field(min_length=1)
    vector: VectorSide
    lexical: LexicalSide | None = None
    fusion: Fusion | None = None
    filterable: tuple[DimensionName, ...] = ()
    #: Spelled ``return:`` in the document — a Python keyword, so aliased.
    return_: tuple[DimensionName, ...] = Field(alias="return", min_length=1)

    # ....................... #

    @model_validator(mode="after")
    def _fusion_needs_both_sides(self) -> Self:
        """Fusion and a lexical side stand or fall together (S-0011/D-9).

        Hybrid retrieval needing both sides is made unrepresentable here rather
        than refused as a guardrail: a fusion block with nothing to fuse is
        meaningless, and a lexical side with no fusion method leaves the runtime
        to invent how the two rankings combine.
        """

        if (self.lexical is None) != (self.fusion is None):
            present, absent = (
                ("lexical", "fusion") if self.fusion is None else ("fusion", "lexical")
            )
            msg = (
                f"a profile declares '{present}' without '{absent}'. Fix: declare both — "
                "fusion combines a lexical ranking with a vector one, so neither says "
                "anything alone — or neither, for vector-only retrieval"
            )
            raise ValueError(msg)

        return self


# ....................... #


class RetrievalSpec(SpecModel):
    """The per-project retrieval document (``retrieval_version``), at most one
    per project (S-0011/D-1)."""

    #: Pinned to the one version bloomery implements, like every other document
    #: kind's (S-0035/D-7), and required because this key is also the
    #: document-kind discriminator.
    retrieval_version: Literal[1]
    semantic_spaces: dict[SpaceName, SemanticSpace]
    profiles: dict[SpaceName, RetrievalProfile]

    # ....................... #

    @model_validator(mode="after")
    def _profiles_name_declared_spaces(self) -> Self:
        """Every profile's space is declared in this document.

        A name resolving to nothing is caught here rather than downstream
        because everything the space would have been compared against — the
        dimensions, the scalar, the producer — is absent with it, so the
        guardrails would report nothing at all for the profile.
        """

        for name, profile in self.profiles.items():
            if profile.vector.space not in self.semantic_spaces:
                declared = ", ".join(sorted(self.semantic_spaces)) or "none"
                msg = (
                    f"profile {name!r} retrieves in space {profile.vector.space!r}, "
                    f"which this document does not declare (declared: {declared}). "
                    "Fix: declare the space under 'semantic_spaces', or name one that exists"
                )
                raise ValueError(msg)

        return self
