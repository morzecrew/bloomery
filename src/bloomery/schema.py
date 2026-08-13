"""JSON Schema for the six spec kinds (RFC 0020 §5.1, D1–D3).

The spec kinds are strict frozen Pydantic models (RFC 0002), so the schema is
one ``model_json_schema()`` call away and was simply never exposed. Exposing it
is the highest-leverage item in RFC 0020 because it serves four consumers from
one artifact that cannot drift from the parser: editor completion via
``yaml.schemas``, form validation in a control plane that would otherwise
transcribe the models into TypeScript, reference documentation generated from
the same docstrings, and **constrained generation** for machine-authored
specs — the one that turns "emit valid YAML" from a prompt instruction into a
structural constraint.

Three properties the raw Pydantic call does not give, each added here:

* **Deterministic.** Keys sorted at every depth, ``required`` sorted, so a
  schema golden diff is a real change rather than dictionary weather.
* **Authored-shape faithful.** Pydantic describes the *model*, and two spec
  constructs are normalized on the way in. ``transform: [to_int]`` is the
  documented spelling and the model that survives it is ``{name, args}``, so
  the generated schema rejects every mapping in the fixture corpus. §5.1's
  enum requirement and this repair are the same edit: see
  :func:`_transform_step_schema`.
* **Addressable.** ``$schema`` and a version-carrying ``$id`` per kind, so a
  consumer can ``$ref`` one by URL and pin it.

Pure, like everything else under ``src/bloomery/``: no file is written here.
:mod:`bloomery.cli` is what puts these documents on a disk.
"""

from __future__ import annotations

# Imported at run time rather than under ``TYPE_CHECKING``: it appears in
# ``all_spec_schemas``'s return annotation, and the signature-closure test
# resolves every public annotation for real (RFC 0018 D10). Aliased because
# ``bloomery.spec.Mapping`` — a spec kind — owns the plain name here.
from collections.abc import Mapping as AbcMapping
from enum import StrEnum
from typing import TYPE_CHECKING, cast, get_args

from bloomery.spec import Catalog, EntityModel, Mapping, MartSet, MetricSet, StepSet
from bloomery.transforms import registry

if TYPE_CHECKING:
    from bloomery.spec.common import SpecModel

__all__ = [
    "JsonDict",
    "SpecKind",
    "all_spec_schemas",
    "spec_json_schema",
]

#: One JSON Schema document. ``object`` rather than a recursive JSON union
#: because a schema is produced to be *serialized*, not indexed: every consumer
#: either hands it to a validator or writes it out, and a precise recursive
#: alias would buy those two callers nothing but casts.
type JsonDict = dict[str, object]

#: The meta-schema these documents are written against. 2020-12 is what
#: ``propertyNames``/``prefixItems`` and Pydantic's own output assume.
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

#: Where the published schemas live, so ``$id`` is resolvable rather than
#: decorative (RFC 0020 §7: they are built alongside the docs).
_BASE_URI = "https://morzecrew.github.io/bloomery/schemas"


class SpecKind(StrEnum):
    """The six loadable spec kinds (RFC 0020 §5.1).

    Five are project documents :func:`~bloomery.load_project` dispatches on by
    version key; :attr:`CATALOG` is loaded separately by
    :func:`~bloomery.load_catalog` because a catalog is not part of a project
    (RFC 0002 D8). Each member's value is the kind's name in a ``$id`` and on
    the ``bloomery schema --kind`` command line.
    """

    CATALOG = "catalog"
    ENTITY_MODEL = "entity_model"
    MAPPING = "mapping"
    MARTS = "marts"
    METRICS = "metrics"
    STEPS = "steps"


#: Kind → the model that parses it, and the version key that identifies it.
#: The version key is the document-kind discriminator (RFC 0002 §5.5) and, since
#: RFC 0018 D7, a ``Literal[1]`` — which is where :func:`_document_version` reads
#: the number in each ``$id`` from, rather than a constant repeated here.
_KINDS: dict[SpecKind, tuple[type[SpecModel], str]] = {
    SpecKind.CATALOG: (Catalog, "catalog_version"),
    SpecKind.ENTITY_MODEL: (EntityModel, "spec_version"),
    SpecKind.MAPPING: (Mapping, "mapping_version"),
    SpecKind.MARTS: (MartSet, "marts_version"),
    SpecKind.METRICS: (MetricSet, "metrics_version"),
    SpecKind.STEPS: (StepSet, "steps_version"),
}


def _document_version(kind: SpecKind) -> int:
    """The single version this bloomery parses for ``kind``.

    Read off the model's pinned ``Literal[1]`` rather than written down again:
    the ``$id`` a consumer pins to and the version the parser accepts are then
    the same fact, and bumping one is bumping both.
    """
    model, version_key = _KINDS[kind]
    (version,) = get_args(model.model_fields[version_key].annotation)
    if not isinstance(version, int):  # pragma: no cover — RFC 0018 D7 pins all five
        msg = f"{kind.value} version key is not a pinned integer literal: {version!r}"
        raise TypeError(msg)
    return version


def _transform_step_schema(generated: JsonDict) -> JsonDict:
    """The three authored spellings of one transform-chain step.

    ``TransformStep`` has a ``mode="before"`` validator that normalizes a bare
    name or a single-key mapping into ``{name, args}`` (RFC 0002 §5.5), and
    Pydantic documents only what comes out of it. The generated schema
    therefore rejects ``transform: [to_string]`` — the spelling every fixture,
    every doc page and the quickstart use. A schema that refuses the
    documented form is worse than none: it teaches an editor to underline
    correct specs, and it teaches a constrained generator to write a form no
    human example shows.

    So the three spellings are stated explicitly, and the transform whitelist
    (RFC 0020 D2) rides along in each of them — as an ``enum`` on the bare
    name, as ``propertyNames`` on the single-key mapping, and as an ``enum`` on
    the normalized form's ``name``. That is what makes constrained generation
    unable to invent a transform, which is the point of the enum requirement:
    the refusal that would have caught the invention never has to fire.

    The whitelist is read from the **live** registry, so a process that called
    :func:`~bloomery.register_transform` exports a schema describing the
    transforms it actually accepts. Determinism is per registry, which is the
    only honest scope: two processes with the same registry agree byte for
    byte, and one that registered an extra transform genuinely parses a
    different language.
    """
    names = sorted(registry())
    argument: JsonDict = {"anyOf": [{"type": "string"}, {"type": "integer"}]}

    normalized = dict(generated)
    properties = dict(_as_dict(normalized.get("properties")))
    name_property = dict(_as_dict(properties.get("name")))
    # The enum replaces the ``""`` default rather than sitting beside it: the
    # empty name is the model's "this step is a `step:` link instead" sentinel,
    # and the model validator refuses a document that spells it out.
    name_property.pop("default", None)
    name_property["enum"] = names
    properties["name"] = name_property
    normalized["properties"] = properties
    description = normalized.pop("description", "")

    return {
        "description": description,
        "anyOf": [
            {"title": "Bare transform name", "type": "string", "enum": names},
            {
                "title": "Single-key mapping of transform name to argument(s)",
                "type": "object",
                "minProperties": 1,
                "maxProperties": 1,
                "propertyNames": {"enum": names},
                "additionalProperties": {
                    "anyOf": [*_as_list(argument["anyOf"]), {"type": "array", "items": argument}]
                },
            },
            normalized,
        ],
    }


def _as_dict(value: object) -> dict[str, object]:
    """A nested schema node as a mapping, or empty if the key was absent.

    Pydantic's output is ``dict[str, Any]``; this is the one place that shape
    is narrowed, so the callers below stay free of casts.
    """
    return cast("dict[str, object]", value) if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return cast("list[object]", value) if isinstance(value, list) else []


def _canonical(value: object) -> object:
    """The same document with every mapping's keys sorted, recursively.

    JSON objects are unordered, so this changes nothing a validator sees and
    everything a reviewer does: the schema goldens diff on content instead of
    on whatever order Pydantic happened to walk the models in. ``required`` is
    sorted for the same reason — it is a set written as a list.
    """
    if isinstance(value, dict):
        entries = cast("dict[str, object]", value)
        canonical: dict[str, object] = {key: _canonical(entries[key]) for key in sorted(entries)}
        required = canonical.get("required")
        if isinstance(required, list):
            items = cast("list[object]", required)
            canonical["required"] = sorted(str(item) for item in items)
        return canonical
    if isinstance(value, list):
        return [_canonical(item) for item in cast("list[object]", value)]
    return value


def spec_json_schema(kind: SpecKind) -> JsonDict:
    """The JSON Schema for one spec kind (RFC 0020 D1).

    Generated from the Pydantic model, so it cannot drift from the parser by
    more than the two validators JSON Schema cannot express — measured rather
    than assumed, by ``tests/property/test_schema_agreement.py``.
    """
    model = _KINDS[kind][0]
    schema: JsonDict = dict(model.model_json_schema())
    # Copied, not mutated in place: whether Pydantic hands back a fresh
    # document or a cached one is its business, not something the export
    # should depend on.
    defs = dict(_as_dict(schema.get("$defs")))
    if "TransformStep" in defs:
        defs["TransformStep"] = _transform_step_schema(_as_dict(defs["TransformStep"]))
        schema["$defs"] = defs
    schema["$schema"] = JSON_SCHEMA_DIALECT
    schema["$id"] = f"{_BASE_URI}/v{_document_version(kind)}/{kind.value}.json"
    return _as_dict(_canonical(schema))


def all_spec_schemas() -> AbcMapping[SpecKind, JsonDict]:
    """Every kind's schema, in :class:`SpecKind` order.

    Six standalone documents rather than one bundle with cross-references
    (RFC 0020 §10 question 1, answered): the bundle's stated advantage was a
    single editor mapping, and an editor maps a *file glob* to a schema, which
    a bundle cannot discriminate within. Standalone documents with resolvable
    ``$id``s serve both that and ``$ref``-by-URL, and joining them later is
    mechanical if a consumer ever wants one.
    """
    return {kind: spec_json_schema(kind) for kind in SpecKind}
