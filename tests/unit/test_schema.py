"""The JSON Schema export (RFC 0020 §5.1, D1–D3).

The load-bearing property is D2: **every closed set appears as an enumeration,
never a free string.** That is what constrained generation depends on — a
proposer choosing from an enum cannot invent a transform or a disposition, so
the refusal that would have caught the invention never has to fire. A schema
that types those as ``"type": "string"`` still validates every correct document
and buys nothing at all for the consumer this export exists for.

The rest is shape: six kinds matching the six loadable ones, a resolvable
``$id`` carrying the version the parser actually accepts, and canonical key
order so the goldens next door diff on content.
"""

from __future__ import annotations

import pytest

from bloomery import JsonDict, SpecKind, all_spec_schemas, spec_json_schema
from bloomery.schema import JSON_SCHEMA_DIALECT
from bloomery.transforms import registry

pytestmark = pytest.mark.unit

SCHEMAS = all_spec_schemas()

#: Kind → the version key that identifies the document, mirroring
#: ``bloomery.spec.project._KIND_KEYS`` plus the separately-loaded catalog.
#: Written out rather than imported so a rename in the private table is a
#: failure here instead of a silent agreement with itself.
VERSION_KEYS = {
    SpecKind.CATALOG: "catalog_version",
    SpecKind.ENTITY_MODEL: "spec_version",
    SpecKind.MAPPING: "mapping_version",
    SpecKind.MARTS: "marts_version",
    SpecKind.METRICS: "metrics_version",
    SpecKind.STEPS: "steps_version",
}


def _nodes(value: object) -> list[JsonDict]:
    """Every mapping in the document, at any depth."""
    if isinstance(value, dict):
        found = [value]
        for item in value.values():
            found.extend(_nodes(item))
        return found
    if isinstance(value, list):
        return [node for item in value for node in _nodes(item)]
    return []


def _closed_values(schema: JsonDict, *, name: str) -> set[str]:
    """The union of every ``enum``/``const`` reachable under a property called
    ``name``, across the whole document.

    A union rather than one node because the same closed set legitimately
    appears under several parents — ``on_fail`` sits on a dozen rule models —
    and the property is that each occurrence is *closed*, not that there is
    exactly one of them.
    """
    values: set[str] = set()
    for node in _nodes(schema):
        properties = node.get("properties")
        if not isinstance(properties, dict):
            continue
        target = properties.get(name)  # pyright: ignore[reportUnknownMemberType]
        if not isinstance(target, dict):
            continue
        for candidate in _nodes(target):
            enum = candidate.get("enum")
            if isinstance(enum, list):
                values.update(str(member) for member in enum)  # pyright: ignore[reportUnknownArgumentType]
            if "const" in candidate:
                values.add(str(candidate["const"]))
    return values


def _is_closed(schema: JsonDict, *, name: str) -> bool:
    """Whether every occurrence of property ``name`` is an enumeration.

    ``_closed_values`` being non-empty is not enough on its own: a kind could
    close the property in one model and leave it a free string in another, and
    the union would hide it.
    """
    occurrences = [
        properties[name]
        for node in _nodes(schema)
        if isinstance(properties := node.get("properties"), dict) and name in properties
    ]
    if not occurrences:
        return False
    return all(
        any("enum" in candidate or "const" in candidate for candidate in _nodes(occurrence))
        for occurrence in occurrences
    )


# ....................... #
# Shape


def test_one_schema_per_loadable_kind() -> None:
    assert set(SCHEMAS) == set(SpecKind)
    assert [kind.value for kind in SCHEMAS] == [kind.value for kind in SpecKind]


def test_every_schema_declares_its_dialect_and_a_versioned_id() -> None:
    for kind, schema in SCHEMAS.items():
        assert schema["$schema"] == JSON_SCHEMA_DIALECT
        assert schema["$id"] == (
            f"https://morzecrew.github.io/bloomery/schemas/v1/{kind.value}.json"
        )


def test_the_id_version_is_the_version_the_parser_accepts() -> None:
    """``$id`` is what a consumer pins to, so it has to be read off the model's
    own pinned literal rather than written down twice. RFC 0018 D7 pinned all
    six keys to ``Literal[1]``; a bump that moved one and not the other would
    hand out a schema for a version bloomery does not parse."""
    for kind, schema in SCHEMAS.items():
        assert _closed_values(schema, name=VERSION_KEYS[kind]) == {"1"}
        assert f"/v1/{kind.value}.json" in str(schema["$id"])


def test_the_version_key_is_required_on_every_kind() -> None:
    """It is the document-kind discriminator (RFC 0002 §5.5), so a schema that
    made it optional would accept a document ``load_project`` cannot identify."""
    for kind, schema in SCHEMAS.items():
        required = schema["required"]
        assert isinstance(required, list)
        assert VERSION_KEYS[kind] in required


def test_unknown_keys_are_refused_at_every_level() -> None:
    """``SpecModel`` is ``extra="forbid"`` (RFC 0002 §5.2). A schema that let
    unknown keys through would accept documents the parser rejects, which is
    the divergence direction that costs a proposal loop a round-trip."""
    for kind, schema in SCHEMAS.items():
        assert schema["additionalProperties"] is False, kind


# ....................... #
# D2 — every closed set is an enumeration, never a free string


@pytest.mark.parametrize(
    ("kind", "name"),
    [
        (SpecKind.ENTITY_MODEL, "scd"),
        (SpecKind.ENTITY_MODEL, "cardinality"),
        (SpecKind.ENTITY_MODEL, "materialization"),
        (SpecKind.ENTITY_MODEL, "on_fail"),
        (SpecKind.ENTITY_MODEL, "rule"),
        (SpecKind.MAPPING, "on_fail"),
        (SpecKind.MAPPING, "rule"),
        (SpecKind.METRICS, "additivity"),
        (SpecKind.MARTS, "agg"),
        (SpecKind.MARTS, "on_fail"),
        (SpecKind.CATALOG, "unit"),
        (SpecKind.CATALOG, "tax_basis"),
        (SpecKind.STEPS, "rule"),
        (SpecKind.STEPS, "on_fail"),
    ],
    ids=lambda value: value if isinstance(value, str) else value.value,
)
def test_closed_sets_are_enumerations(kind: SpecKind, name: str) -> None:
    assert _is_closed(SCHEMAS[kind], name=name), f"{kind.value}.{name} is not closed"


def test_the_transform_whitelist_is_an_enumeration_in_every_authored_spelling() -> None:
    """The one closed set Pydantic could not supply.

    ``TransformStep`` normalizes a bare name and a single-key mapping into
    ``{name, args}`` before validation, so the generated schema describes only
    the normalized form — it would both reject ``transform: [to_string]`` and
    leave the transform name a free string. All three spellings carry the
    registry.
    """
    expected = sorted(registry())
    step = SCHEMAS[SpecKind.MAPPING]["$defs"]
    assert isinstance(step, dict)
    branches = step["TransformStep"]["anyOf"]  # pyright: ignore[reportUnknownVariableType, reportIndexIssue]
    assert isinstance(branches, list)
    bare, single_key, normalized = branches
    assert bare["enum"] == expected
    assert single_key["propertyNames"]["enum"] == expected
    assert normalized["properties"]["name"]["enum"] == expected
    # The enum is *injected into* the generated property, not written over it:
    # a lookup that silently missed would leave `{"enum": [...]}` with no type,
    # which is valid JSON Schema and would pass the assertion above.
    assert normalized["properties"]["name"]["type"] == "string"
    # The empty-string default is gone with it: the model validator refuses a
    # document that spells the "this is a step: link instead" sentinel out.
    assert "default" not in normalized["properties"]["name"]


def test_the_logical_type_grammar_is_a_pattern_rather_than_an_enum() -> None:
    """RFC 0020 D2 lists ``LogicalType`` among the closed sets. It is closed as
    a *grammar*, not as a list: ``decimal(p, s)`` is parameterized, so an
    enumeration would have to spell out every precision/scale pair. The pattern
    is the faithful expression, and regex-constrained decoders consume it —
    recorded here rather than left as a silently unmet decision.
    """
    entity = SCHEMAS[SpecKind.ENTITY_MODEL]["$defs"]
    assert isinstance(entity, dict)
    field_type = entity["Field"]["properties"]["type"]  # pyright: ignore[reportUnknownVariableType, reportIndexIssue]
    assert "enum" not in field_type
    assert field_type["pattern"].startswith("^(?:string|int|bool|date|timestamp|variant|decimal")


def test_the_steps_document_carries_no_determinism_key() -> None:
    """A closed set that is not in the export because it is not in a *spec*.

    ``determinism`` (``pure``/``seeded``/``nondeterministic``) is declared on
    ``StepManifest`` — the platform-owned side a caller assembles into a
    ``StepRegistry``, which bloomery never reads from a document (RFC 0017 D3).
    The authored ``steps:`` document holds wiring only. Pinned so that moving
    the key into the spec is a decision someone makes rather than a schema that
    quietly stops describing a closed set.
    """
    for node in _nodes(SCHEMAS[SpecKind.STEPS]):
        properties = node.get("properties")
        if isinstance(properties, dict):
            assert "determinism" not in properties


def test_op_appears_in_no_spec_kind() -> None:
    """The other half of the same audit. RFC 0020 D2 also lists ``Op``, which
    no spec document carries: filters are request-time (RFC 0011/0015), not
    authored. The requirement is vacuous rather than unmet, and pinning it
    stops a future ``Op``-shaped spec field from arriving as a free string.
    """
    operators = {"eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "is_null", "like", "ilike"}
    for kind, schema in SCHEMAS.items():
        for node in _nodes(schema):
            enum = node.get("enum")
            if isinstance(enum, list):
                assert set(map(str, enum)) != operators, kind  # pyright: ignore[reportUnknownArgumentType]


# ....................... #
# D3 — canonical, and the same document every time


def test_keys_are_sorted_at_every_depth() -> None:
    for kind, schema in SCHEMAS.items():
        for node in _nodes(schema):
            assert list(node) == sorted(node), kind


def test_required_lists_are_sorted() -> None:
    for kind, schema in SCHEMAS.items():
        for node in _nodes(schema):
            required = node.get("required")
            if isinstance(required, list):
                assert required == sorted(map(str, required)), kind  # pyright: ignore[reportUnknownArgumentType]


def test_generation_is_repeatable_within_a_process() -> None:
    """The cross-process half of D3 rides the existing hash-seed harness
    (``tests/unit/test_determinism_guard.py``); this is the cheap in-process
    half, which catches a mutable default shared between calls."""
    for kind in SpecKind:
        assert spec_json_schema(kind) == spec_json_schema(kind)


def test_exporting_one_kind_does_not_mutate_another() -> None:
    """Pydantic's ``$defs`` are shared model definitions, and the transform
    injection edits one. Copying rather than mutating in place is what keeps a
    second call — or a second kind sharing the model — from seeing the edit
    twice."""
    first = spec_json_schema(SpecKind.MAPPING)
    _other = spec_json_schema(SpecKind.ENTITY_MODEL)
    assert spec_json_schema(SpecKind.MAPPING) == first
