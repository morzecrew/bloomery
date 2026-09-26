"""The retrieval document (S-0011/D-1, S-0011/D-2, S-0011/D-5, S-0011/D-12):
its own spec kind behind its own `retrieval_version` key, what a document may
say, and what the grammar refuses before any guardrail reads a relation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bloomery import load_project
from bloomery.errors import SpecParseError
from bloomery.spec import RetrievalSpec

pytestmark = pytest.mark.unit

DOCUMENT = """
retrieval_version: 1
semantic_spaces:
  chunk_space:
    dimensions: 1536
    scalar: float32
    distance: cosine
    document_encoder: {family: openai, model: text-embedding-3-small, input_kind: document}
    query_encoder: {family: openai, model: text-embedding-3-small, input_kind: query}
profiles:
  support_search:
    relation: {entity: chunk}
    grain: [chunk_id]
    vector: {field: embedding, space: chunk_space}
    filterable: [product]
    return: [chunk_id, body]
"""

ENTITY_MODEL = """
spec_version: 1
entities:
  chunk:
    grain: one row per chunk
    key: [chunk_id]
    fields:
      chunk_id: {type: string, required: true}
"""


def _spec(**overrides: object) -> RetrievalSpec:
    """The worked document, with profile keys overridden."""

    profile: dict[str, object] = {
        "relation": {"entity": "chunk"},
        "grain": ["chunk_id"],
        "vector": {"field": "embedding", "space": "chunk_space"},
        "return": ["chunk_id"],
        **overrides,
    }
    return RetrievalSpec.model_validate(
        {
            "retrieval_version": 1,
            "semantic_spaces": {
                "chunk_space": {
                    "dimensions": 1536,
                    "scalar": "float32",
                    "distance": "cosine",
                    "document_encoder": {
                        "family": "openai",
                        "model": "m",
                        "input_kind": "document",
                    },
                    "query_encoder": {"family": "openai", "model": "m", "input_kind": "query"},
                }
            },
            "profiles": {"support_search": profile},
        }
    )


# ....................... #
# The kind (D1)


def test_the_document_is_recognised_by_its_version_key() -> None:
    project = load_project({"entity_model": ENTITY_MODEL, "retrieval": DOCUMENT})
    assert project.retrieval is not None
    assert set(project.retrieval.semantic_spaces) == {"chunk_space"}
    assert set(project.retrieval.profiles) == {"support_search"}


def test_a_project_with_no_retrieval_document_has_none() -> None:
    """The whole design is invisible to a project that does not retrieve, which
    is the point of a separate kind rather than optional entity-model keys."""

    assert load_project({"entity_model": ENTITY_MODEL}).retrieval is None


def test_a_second_retrieval_document_is_refused() -> None:
    with pytest.raises(SpecParseError, match="RetrievalSpec"):
        load_project({"entity_model": ENTITY_MODEL, "a": DOCUMENT, "b": DOCUMENT})


def test_the_version_key_is_pinned_to_the_one_bloomery_implements() -> None:
    with pytest.raises(SpecParseError):
        load_project(
            {
                "entity_model": ENTITY_MODEL,
                "retrieval": DOCUMENT.replace("retrieval_version: 1", "retrieval_version: 2"),
            }
        )


def test_an_unknown_key_is_refused() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _spec(top_k=10)


# ....................... #
# The space (D2, D3, D12)


def test_the_worked_document_parses_with_distance_on_the_space() -> None:
    """D12, decided: `distance` is a property of the space, not of the profile.

    Every field claiming one space is then scored the same way, and the
    relaxation — moving it onto the profile later — is additive, which the
    reverse is not.
    """

    space = _spec().semantic_spaces["chunk_space"]
    assert space.distance == "cosine"
    assert space.dimensions == 1536
    assert space.scalar == "float32"


def test_an_encoder_is_three_opaque_strings() -> None:
    """No identity is resolved against a provider (S-0011/D-2) — the value is
    carried and compared, never looked up."""

    space = _spec().semantic_spaces["chunk_space"]
    assert (space.document_encoder.family, space.document_encoder.model) == ("openai", "m")
    assert space.query_encoder.input_kind == "query"


def _space(**overrides: object) -> None:
    base: dict[str, object] = {
        "dimensions": 1536,
        "scalar": "float32",
        "distance": "cosine",
        "document_encoder": {"family": "openai", "model": "m", "input_kind": "document"},
        "query_encoder": {"family": "openai", "model": "m", "input_kind": "query"},
        **overrides,
    }
    RetrievalSpec.model_validate(
        {"retrieval_version": 1, "semantic_spaces": {"s": base}, "profiles": {}}
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"scalar": "float64"},  # the scalar vocabulary is closed (D3)
        {"distance": "manhattan"},  # so is the distance vocabulary
        {"dimensions": 0},
        {"dimensions": 100000},  # past the five digits the type grammar admits
    ],
)
def test_a_space_outside_the_closed_vocabularies_is_refused(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _space(**overrides)


def test_an_encoder_under_the_wrong_side_is_refused() -> None:
    """A space whose `query_encoder` says `input_kind: document` reads as
    symmetric while saying it is not."""

    with pytest.raises(ValidationError, match="must declare 'input_kind: query'"):
        _space(query_encoder={"family": "openai", "model": "m", "input_kind": "document"})


# ....................... #
# The profile


def test_a_profile_names_exactly_one_relation() -> None:
    with pytest.raises(ValidationError, match="name exactly one of 'mart' or 'entity'"):
        _spec(relation={"entity": "chunk", "mart": "chunks"})

    with pytest.raises(ValidationError, match="name exactly one of 'mart' or 'entity'"):
        _spec(relation={})


def test_a_mart_is_the_other_relation_kind() -> None:
    profile = _spec(relation={"mart": "chunks"}).profiles["support_search"]
    assert profile.relation.mart == "chunks"
    assert profile.relation.entity is None


def test_the_return_key_is_spelled_return_in_the_document() -> None:
    assert _spec().profiles["support_search"].return_ == ("chunk_id",)


@pytest.mark.parametrize("overrides", [{"return": []}, {"grain": []}])
def test_an_empty_grain_or_projection_is_refused(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _spec(**overrides)


def test_filterable_defaults_to_nothing() -> None:
    """Searchable is not filterable (S-0011/D-9): a field is filterable because
    it was declared so, never because it happened to be returned."""

    assert _spec().profiles["support_search"].filterable == ()


# ....................... #
# Hybrid retrieval (D5, D9)


def test_a_hybrid_profile_parses_with_both_sides() -> None:
    profile = _spec(lexical={"fields": ["body"]}, fusion={"method": "rrf"}).profiles[
        "support_search"
    ]
    assert profile.lexical is not None
    assert profile.lexical.fields == ("body",)
    assert profile.fusion is not None
    assert profile.fusion.method == "rrf"


@pytest.mark.parametrize(
    "overrides",
    [{"lexical": {"fields": ["body"]}}, {"fusion": {"method": "rrf"}}],
)
def test_one_side_of_a_hybrid_without_the_other_is_refused(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="Fix: declare both"):
        _spec(**overrides)


def test_any_fusion_but_rrf_is_refused_by_the_grammar() -> None:
    """D5: RRF combines *ranks*, so it needs no shared scale between a lexical
    score and a cosine similarity. A weighted method would, and there is no
    defensible default for the normalization."""

    with pytest.raises(ValidationError, match="Input should be 'rrf'"):
        _spec(lexical={"fields": ["body"]}, fusion={"method": "weighted"})


def test_a_lexical_side_needs_a_field() -> None:
    with pytest.raises(ValidationError):
        _spec(lexical={"fields": []}, fusion={"method": "rrf"})


# ....................... #
# The cross-reference the guardrails cannot make


def test_a_profile_naming_an_undeclared_space_is_refused_here() -> None:
    """Everything the space would have been compared against is absent with it,
    so the guardrails would report nothing at all for the profile."""

    with pytest.raises(ValidationError, match="which this document does not declare"):
        _spec(vector={"field": "embedding", "space": "other_space"})


def test_a_declared_producer_is_carried_for_the_guardrail_to_compare() -> None:
    profile = _spec(
        vector={
            "field": "embedding",
            "space": "chunk_space",
            "producer": {"family": "cohere", "model": "embed-v3", "input_kind": "document"},
        }
    ).profiles["support_search"]
    assert profile.vector.producer is not None
    assert profile.vector.producer.family == "cohere"


def test_a_producer_is_optional() -> None:
    assert _spec().profiles["support_search"].vector.producer is None
