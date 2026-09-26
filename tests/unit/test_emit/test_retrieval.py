"""The retrieval manifest emitter (S-0011/the-manifest, S-0011/D-6): one JSON
artifact per project, every profile carrying its semantic space inlined
(S-0011/D-7), the corpus relation resolved through the naming policy, and nothing
in it that a float or an embedding could reach (S-0011/D-2, S-0011/D-3).

The corpus is inline rather than a fixture because it is the *shape* under test
and nothing else reads it: a project whose only vector arrives from a step's
declared output, which is the one route a vector column can take — a vector is
produced by no transform, so no mapping chain could populate one.

`examples/retrieval/` is the same project as a runnable example, and
`tests/unit/test_examples.py` compiles it; the two are deliberately separate,
because an example is documentation people edit and these assertions are about
the emitter.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from bloomery import Target, compile_project, load_project
from bloomery.emit import ArtifactKind, get_emitter
from bloomery.emit.retrieval import MANIFEST_PATH, MANIFEST_VERSION
from bloomery.naming import PrefixNaming
from bloomery.steps import StepManifest, StepRegistry

pytestmark = pytest.mark.unit

SOURCES: dict[str, str] = {
    "entity_model": """
spec_version: 1
entities:
  document:
    grain: one row per document
    key: [document_id]
    fields:
      document_id: {type: string, required: true}
      title: {type: string}
""",
    "mapping": """
mapping_version: 1
source: cms__documents
target: document
key:
  document_id: {from: "$.id", transform: [to_string]}
fields:
  title: {from: "$.title", transform: [to_string, trim]}
""",
    "steps": """
steps_version: 1
steps:
  - use: chunk_and_embed@1
    inputs: {documents: silver.document}
    outputs: {chunk: silver.chunk}
""",
    "marts": """
marts_version: 1
marts:
  chunks:
    grain: chunk
    base: chunk
""",
    "retrieval": """
retrieval_version: 1
semantic_spaces:
  chunk_text:
    dimensions: 1536
    scalar: float32
    distance: cosine
    document_encoder: {family: openai, model: text-embedding-3-small, input_kind: document}
    query_encoder: {family: openai, model: text-embedding-3-small, input_kind: query}
profiles:
  chunk_hybrid:
    relation: {entity: chunk}
    grain: [chunk_id]
    vector:
      field: embedding
      space: chunk_text
      producer: {family: openai, model: text-embedding-3-small, input_kind: document}
    lexical: {fields: [body]}
    fusion: {method: rrf}
    filterable: [document_id]
    return: [chunk_id, body]
  chunk_dense:
    relation: {mart: chunks}
    grain: [chunk_id]
    vector: {field: embedding, space: chunk_text}
    filterable: [document_id]
    return: [chunk_id]
""",
}

#: The step's contract as data, the way a caller assembles a registry: the
#: `embedding` column is declared here and nowhere else.
MANIFEST = StepManifest.model_validate(
    {
        "ref": "chunk_and_embed",
        "version": 1,
        "kind": "python_model",
        "determinism": "pure",
        "lineage": "coarse",
        "entrypoint": "platform_steps.retrieval:chunk_and_embed",
        "runtime_lock": "sha256:f00d",
        "inputs": {"documents": {"grain": "one row per document", "requires": ["document_id"]}},
        "outputs": {
            "chunk": {
                "grain": "one row per chunk",
                "key": ["chunk_id"],
                "produces": {
                    "chunk_id": {"type": "string", "required": True},
                    "document_id": {"type": "string", "required": True},
                    "body": {"type": "string", "required": True},
                    "embedding": {"type": "vector(float32, 1536)", "required": True},
                },
            }
        },
    }
)
REGISTRY = StepRegistry({("chunk_and_embed", 1): MANIFEST})

#: The same project with the retrieval document left out — one target, two
#: projects, and the difference is the whole of what the emitter branches on.
WITHOUT_RETRIEVAL = {name: text for name, text in SOURCES.items() if name != "retrieval"}


def compile_retrieval(
    sources: dict[str, str] | None = None, **kwargs: Any
) -> tuple[Any, ...]:
    """The corpus compiled for the retrieval target."""
    return compile_project(
        load_project(sources if sources is not None else SOURCES),
        target=Target.RETRIEVAL,
        dialect="duckdb",
        steps=REGISTRY,
        **kwargs,
    )


def manifest_payload(**kwargs: Any) -> dict[str, Any]:
    """The emitted manifest, parsed."""
    (artifact,) = compile_retrieval(**kwargs)
    return json.loads(artifact.content)


# ....................... #


def test_one_artifact_at_the_manifest_path() -> None:
    (artifact,) = compile_retrieval()

    assert artifact.path == MANIFEST_PATH == "retrieval_manifest.json"
    assert artifact.kind is ArtifactKind.MODEL


def test_the_manifest_is_valid_json_with_no_fingerprint_header() -> None:
    """The semantic manifest's rule (S-0059/D-5), for the same reason: a
    ``-- fingerprint:`` comment would make the document invalid rather than
    annotated, and the artifact carries the content checksum anyway."""
    (artifact,) = compile_retrieval()

    assert not artifact.content.startswith("--")
    assert json.loads(artifact.content)
    assert artifact.content.endswith("}\n")
    assert not artifact.content.endswith("}\n\n")


def test_every_declared_profile_is_carried_under_its_version() -> None:
    payload = manifest_payload()

    assert payload["retrieval_manifest_version"] == MANIFEST_VERSION
    assert sorted(payload["profiles"]) == ["chunk_dense", "chunk_hybrid"]


def test_each_profile_carries_its_space_inlined(
) -> None:
    """S-0011/D-7. The consumer is a runtime with no access to the spec tree, so
    a profile naming ``chunk_text`` and nothing else would send its reader
    looking for a file bloomery does not emit. Both profiles claim the one
    space, and both carry the whole of it."""
    profiles = manifest_payload()["profiles"]

    for name, profile in profiles.items():
        space = profile["vector"]["space"]
        assert space == {
            "name": "chunk_text",
            "dimensions": 1536,
            "scalar": "float32",
            "distance": "cosine",
            "document_encoder": {
                "family": "openai",
                "model": "text-embedding-3-small",
                "input_kind": "document",
            },
            "query_encoder": {
                "family": "openai",
                "model": "text-embedding-3-small",
                "input_kind": "query",
            },
        }, f"profile {name} carries a partial space"


def test_the_corpus_relation_is_resolved_through_the_naming_policy() -> None:
    """A runtime interpolates ``namespace``/``table``; the logical name stays
    beside them, for the human reading the manifest against the specs. An entity
    resolves in silver and a mart in gold, which is the only thing the manifest
    reads the relation's kind for."""
    profiles = manifest_payload()["profiles"]

    assert profiles["chunk_hybrid"]["relation"] == {
        "kind": "entity",
        "name": "chunk",
        "namespace": "silver",
        "table": "chunk",
    }
    assert profiles["chunk_dense"]["relation"] == {
        "kind": "mart",
        "name": "chunks",
        "namespace": "gold",
        "table": "mart_chunks",
    }


def test_a_tenant_prefix_reaches_the_corpus_relation() -> None:
    """The policy is a port, not a default the emitter may quietly bypass: a
    manifest that named ``silver.chunk`` for a tenant whose relations live in
    ``acme_silver`` points every query at a table that is not there."""
    profiles = manifest_payload(naming=PrefixNaming("acme"))["profiles"]

    assert profiles["chunk_hybrid"]["relation"]["namespace"] == "acme_silver"
    assert profiles["chunk_dense"]["relation"]["namespace"] == "acme_gold"


def test_the_hybrid_side_and_the_projection_are_carried_verbatim() -> None:
    """``lexical`` and ``fusion`` stand or fall together, and ``return`` keeps
    its authored spelling — the field is ``return_`` in Python and nowhere
    else."""
    profiles = manifest_payload()["profiles"]

    assert profiles["chunk_hybrid"]["lexical"] == {"fields": ["body"]}
    assert profiles["chunk_hybrid"]["fusion"] == {"method": "rrf"}
    assert profiles["chunk_hybrid"]["filterable"] == ["document_id"]
    assert profiles["chunk_hybrid"]["return"] == ["chunk_id", "body"]
    assert profiles["chunk_hybrid"]["vector"]["producer"]["model"] == "text-embedding-3-small"
    assert "return_" not in json.dumps(profiles)


def test_a_dense_profile_carries_no_lexical_or_fusion_key() -> None:
    """Absence, not ``null``: "this profile has no lexical side" is spelled by
    the key not being there, so a consumer testing for the key gets the right
    answer without a second reading."""
    dense = manifest_payload()["profiles"]["chunk_dense"]

    assert "lexical" not in dense
    assert "fusion" not in dense
    assert "producer" not in dense["vector"]


def test_a_project_with_no_retrieval_document_emits_nothing() -> None:
    """The MetricFlow emitter's rule for a project with no marts: an empty
    manifest is a file claiming a retrieval contract that is not there."""
    assert compile_retrieval(WITHOUT_RETRIEVAL) == ()


def test_the_manifest_holds_no_float_and_no_embedding() -> None:
    """S-0011/D-3 and S-0011/D-2 at the artifact.

    A space declares a shape and an identity; fusion is rank-based, so there is
    no weight to tune. Nothing here computed, read or validated a vector — the
    only numbers a manifest can carry are a dimension count and a version, and a
    float appearing in one would mean something upstream started reading
    embeddings.
    """
    payload = manifest_payload()

    def walk(value: object) -> None:
        assert not isinstance(value, float), f"a float reached the manifest: {value!r}"
        if isinstance(value, dict):
            for key, item in value.items():
                assert not isinstance(key, float)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    assert "e-" not in json.dumps(payload), "scientific notation is a float in a string"


def test_the_bytes_are_sorted_keys_json() -> None:
    """What makes the artifact independent of the order pydantic handed the
    document over in — the property the cross-process guard measures over two
    hash seeds (S-0020), asserted here on the bytes themselves."""
    (artifact,) = compile_retrieval()

    assert artifact.content == json.dumps(json.loads(artifact.content), indent=2, sort_keys=True) + "\n"


def test_the_target_is_registered_under_its_name() -> None:
    assert get_emitter("retrieval").name == "retrieval"
    assert Target.RETRIEVAL.value == "retrieval"


def test_no_core_target_names_a_vector_store() -> None:
    """S-0011/D-10, ``LOCKED``, as a check rather than a habit.

    A vendor-oriented vector emitter stays out of tree behind
    ``register_emitter`` until it has an artifact contract someone has run, and
    the enum is where that decision would be quietly reversed: one member named
    after a store, and bloomery ships an integration it cannot test. The target
    added here names an *artifact*, and this pins the set so that the next
    addition is a deliberate edit to this list.
    """
    assert {target.value for target in Target} == {
        "cube",
        "dbt",
        "metricflow",
        "retrieval",
        "sqlmesh",
    }
