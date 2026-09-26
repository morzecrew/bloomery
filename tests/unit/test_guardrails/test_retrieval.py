"""The retrieval guards (S-0011/the-guardrails): the six refusals that make a
declared retrieval surface mean something — dimension mismatch, scalar mismatch,
a vector field that is not a vector, a producer mismatch, a grain that is not the
corpus relation's key, and a referenced field the corpus has not got.

Read against a hand-built draft rather than a fixture because every refusal needs
a *type* or a *key*: a vector column reaches an entity from a step's declared
output (S-0011/D-11, decided — a vector may be declared on an entity as well as
on a mart), and building one through the step machinery would test that machinery
instead of these rules.
"""

from __future__ import annotations

import pytest

from bloomery import load_project
from bloomery.guardrails.retrieval import RetrievalViolation, check_retrieval
from bloomery.ir import (
    ColumnIR,
    EntityIR,
    Materialization,
    MartColumnIR,
    MartIR,
    ProjectIR,
    SCDKind,
)
from bloomery.typing import LogicalType, StringType, VectorType

pytestmark = pytest.mark.unit

ENTITY_MODEL = """
spec_version: 1
entities:
  chunk:
    grain: one row per chunk
    key: [chunk_id]
    fields:
      chunk_id: {type: string, required: true}
"""

EMBEDDING = VectorType(scalar="float32", dimensions=1536)


def _column(name: str, type_: LogicalType) -> ColumnIR:
    return ColumnIR(
        name=name,
        type=type_,
        canonical=None,
        unit=None,
        tax_basis=None,
        renamed_from=None,
        required=False,
    )


def _draft(
    *,
    columns: dict[str, LogicalType] | None = None,
    key: tuple[str, ...] = ("chunk_id",),
) -> ProjectIR:
    """A draft carrying one step-produced entity and one mart over it."""

    resolved = columns or {"chunk_id": StringType(), "body": StringType(), "embedding": EMBEDDING}
    entity = EntityIR(
        name="chunk",
        grain="one row per chunk",
        key=key,
        scd=SCDKind.TYPE1,
        materialization=Materialization.FULL,
        partition_by=(),
        columns=tuple(_column(name, type_) for name, type_ in sorted(resolved.items())),
        sources=(),
        produced_by="embed@1",
    )
    mart = MartIR(
        name="chunks",
        grain="chunk",
        base="chunk",
        columns=tuple(
            MartColumnIR(name=name, type=type_, source_entity="chunk", source_column=name)
            for name, type_ in sorted(resolved.items())
        ),
        measures=(),
        dimensions=(),
        joins=(),
        partition_by=(),
        materialization=Materialization.FULL,
    )
    return ProjectIR(entities=(entity,), marts=(mart,))


def _profile(**overrides: str) -> str:
    """The worked profile as YAML, one key at a time."""

    keys: dict[str, str] = {
        "relation": "{entity: chunk}",
        "grain": "[chunk_id]",
        "vector": "{field: embedding, space: chunk_space}",
        "return": "[chunk_id]",
        **overrides,
    }
    lines = "\n".join(f"    {key}: {value}" for key, value in keys.items())
    return f"""
retrieval_version: 1
semantic_spaces:
  chunk_space:
    dimensions: 1536
    scalar: float32
    distance: cosine
    document_encoder: {{family: openai, model: text-embedding-3-small, input_kind: document}}
    query_encoder: {{family: openai, model: text-embedding-3-small, input_kind: query}}
profiles:
  support_search:
{lines}
"""


def _refusals(draft: ProjectIR | None = None, **overrides: str) -> list[str]:
    project = load_project({"entity_model": ENTITY_MODEL, "retrieval": _profile(**overrides)})
    violations = check_retrieval(project, draft or _draft())
    assert all(isinstance(violation, RetrievalViolation) for violation in violations)
    assert all(violation.source_path == "retrieval: profiles.support_search" for violation in violations)
    return [str(violation) for violation in violations]


# ....................... #
# The default: a project that does not retrieve is untouched


def test_an_imported_relation_is_built_when_the_guard_reads_the_composed_view() -> None:
    """The stage hands the guard the composed view (S-0002/D-9): a profile
    over an entity an upstream builds, or a mart whose base is one, is over a
    relation that exists. Read from the local draft alone, the guard reported
    that the project "does not build" what the upstream builds."""
    from dataclasses import replace

    from bloomery.ir.nodes import UpstreamIR, with_imported

    local = _draft()
    (entity,) = local.entities
    imported = replace(
        local,
        entities=(),
        upstream=(UpstreamIR(alias="up", fingerprint="blm1:up", entities=(entity,)),),
    )
    assert _refusals(draft=with_imported(imported)) == _refusals(draft=local) == []
    assert any("does not build" in refusal for refusal in _refusals(draft=imported))


def test_a_mart_imported_without_its_base_entity_is_refused_by_name() -> None:
    """A mart-only import carries the mart's rows but not the key that
    identifies one (S-0011/D-8), so the guard cannot check the profile's
    `key`. That is a distinct refusal naming the missing import — not the
    "does not build" one, which would send the author to declare a mart the
    upstream already builds."""
    from dataclasses import replace

    from bloomery.ir.nodes import UpstreamIR, with_imported

    local = _draft()
    (mart,) = local.marts
    mart_only = replace(
        local,
        entities=(),
        marts=(),
        upstream=(UpstreamIR(alias="up", fingerprint="blm1:up", marts=(mart,)),),
    )
    refusals = _refusals(draft=with_imported(mart_only), relation="{mart: chunks}")
    assert len(refusals) == 1
    assert "neither builds nor imports" in refusals[0]
    assert "'chunk'" in refusals[0]
    assert "does not build" not in refusals[0]


def test_a_project_with_no_retrieval_document_is_never_walked() -> None:
    project = load_project({"entity_model": ENTITY_MODEL})
    assert check_retrieval(project, _draft()) == []


def test_the_worked_profile_is_accepted() -> None:
    """Every refusal below is reached from this, so its silence is what says the
    guard can pass at all."""

    assert _refusals() == []


# ....................... #
# Refusal 1: the dimensions disagree


def test_a_field_of_other_dimensions_than_its_space_is_refused() -> None:
    draft = _draft(columns={"chunk_id": StringType(), "embedding": VectorType("float32", 768)})
    (message,) = _refusals(draft)
    assert "of 768 dimensions in space 'chunk_space', which declares 1536" in message
    assert "a distance over vectors of different lengths cannot be computed" in message


# ....................... #
# Refusal 2: the scalars disagree


def test_a_field_of_another_scalar_than_its_space_is_refused() -> None:
    draft = _draft(columns={"chunk_id": StringType(), "embedding": VectorType("float16", 1536)})
    (message,) = _refusals(draft)
    assert "of scalar 'float16' in space 'chunk_space', which declares 'float32'" in message
    assert "silently different space" in message


def test_both_halves_of_the_shape_are_reported_at_once() -> None:
    """A space renamed and its dimensions bumped is one edit; reporting one
    disagreement at a time would make it two round-trips."""

    draft = _draft(columns={"chunk_id": StringType(), "embedding": VectorType("float16", 768)})
    assert len(_refusals(draft)) == 2


# ....................... #
# Refusal 3: the vector field is not a vector


def test_retrieving_on_a_field_that_is_not_a_vector_is_refused() -> None:
    draft = _draft(columns={"chunk_id": StringType(), "embedding": StringType()})
    (message,) = _refusals(draft)
    assert "declared 'string' rather than a vector" in message
    assert "Fix: declare it as 'vector(float32, 1536)'" in message


# ....................... #
# Refusal 4: the producers disagree


def test_a_producer_the_space_does_not_declare_is_refused() -> None:
    """Dimensions agreeing is not spaces agreeing (S-0011/D-2), and the check is
    a string comparison — no identity is resolved against a provider."""

    (message,) = _refusals(
        vector=(
            "{field: embedding, space: chunk_space, producer: "
            "{family: cohere, model: embed-v3, input_kind: document}}"
        )
    )
    assert "produced by cohere/embed-v3 (document)" in message
    assert "its documents produced by openai/text-embedding-3-small (document)" in message


def test_the_same_producer_as_the_space_passes() -> None:
    assert (
        _refusals(
            vector=(
                "{field: embedding, space: chunk_space, producer: "
                "{family: openai, model: text-embedding-3-small, input_kind: document}}"
            )
        )
        == []
    )


def test_a_query_side_producer_is_not_the_document_encoder() -> None:
    """The half a dimension check cannot see: a query encoded as a document
    agrees about dimensions and is still the wrong vector."""

    (message,) = _refusals(
        vector=(
            "{field: embedding, space: chunk_space, producer: "
            "{family: openai, model: text-embedding-3-small, input_kind: query}}"
        )
    )
    assert "produced by openai/text-embedding-3-small (query)" in message


# ....................... #
# Refusal 5: the grain is not the relation's key (D8)


def test_a_grain_that_is_not_the_relations_key_is_refused() -> None:
    (message,) = _refusals(grain="[document_id]", **{"return": "[chunk_id]"})
    assert "declares grain ['document_id'] over entity 'chunk', whose key is ['chunk_id']" in message
    assert "One vector per retrievable item" in message


def test_a_partial_key_is_not_the_key() -> None:
    """Strict key equality, the rule already applied to measures (S-0011/D-8)."""

    draft = _draft(key=("document_id", "chunk_id"))
    messages = _refusals(draft)
    assert any("whose key is ['document_id', 'chunk_id']" in message for message in messages)


def test_a_mart_is_judged_against_its_base_entitys_key() -> None:
    """A mart's rows are its base entity's rows: the flattener joins dimensions
    in without fanning out."""

    assert _refusals(relation="{mart: chunks}") == []
    (message,) = _refusals(_draft(key=("document_id",)), relation="{mart: chunks}", grain="[chunk_id]")
    assert "over mart 'chunks', whose key is ['document_id']" in message


# ....................... #
# Refusal 6: a referenced field the corpus has not got


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"filterable": "[product]"}, "filterable names 'product'"),
        ({"return": "[chunk_id, title]"}, "return names 'title'"),
        (
            {"lexical": "{fields: [title]}", "fusion": "{method: rrf}"},
            "lexical names 'title'",
        ),
    ],
)
def test_a_field_the_corpus_does_not_carry_is_refused(
    overrides: dict[str, str], expected: str
) -> None:
    (message,) = _refusals(**overrides)
    assert expected in message
    assert "Its columns: 'body', 'chunk_id', 'embedding'" in message


def test_the_vector_field_itself_is_checked_for_presence() -> None:
    draft = _draft(columns={"chunk_id": StringType()})
    (message,) = _refusals(draft)
    assert "names 'embedding', which entity 'chunk' does not carry" in message


def test_the_column_list_is_capped_rather_than_printing_eighty_names() -> None:
    columns: dict[str, LogicalType] = {f"c{index:02d}": StringType() for index in range(10)}
    columns["chunk_id"] = StringType()
    (message,) = _refusals(_draft(columns=columns, key=("chunk_id",)))
    assert "… (11 in total)" in message
    assert "'c08'" not in message


# ....................... #
# The relation itself


@pytest.mark.parametrize(
    ("relation", "expected"),
    [
        ("{entity: passage}", "retrieves from entity 'passage', which this project does not build"),
        ("{mart: passages}", "retrieves from mart 'passages', which this project does not build"),
    ],
)
def test_a_relation_the_project_does_not_build_is_refused(relation: str, expected: str) -> None:
    """A mart that failed its own check is absent from the draft, so the profile
    reports the relation as unresolvable — one leaf in the same batch."""

    (message,) = _refusals(relation=relation)
    assert expected in message


def test_an_unresolvable_relation_stops_the_other_checks_on_that_profile() -> None:
    """There is nothing to read them against, and six refusals about a relation
    that does not exist are six ways of saying the same thing."""

    assert len(_refusals(relation="{entity: passage}", grain="[nope]")) == 1
