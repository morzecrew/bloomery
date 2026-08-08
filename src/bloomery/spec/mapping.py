"""The ``Mapping`` spec kind (RFC 0002 §5.5; original spec §3.4).

How one bronze source becomes an entity: key lowering, field mappings (simple
``{from, transform}`` or recipe ``{recipe, from: {alias: path}}`` — a
discriminated union on the presence of ``recipe``), the unmapped tail, and the
per-field ``quality:`` rules (RFC 0016 §5.3). ``from`` paths are JSONPath-lite,
grammar-validated only; transform-name existence is checked at typecheck, not
parse (RFC 0002 D4).
"""

from __future__ import annotations

from collections.abc import Mapping as AbcMapping
from typing import Annotated, cast

from pydantic import Discriminator, Field, Tag, model_validator

from bloomery.spec.common import JsonPath, MemberName, SpecModel
from bloomery.spec.quality import FieldQualityRule

__all__ = [
    "FieldMapping",
    "KeyField",
    "Mapping",
    "RecipeFieldMapping",
    "SimpleFieldMapping",
    "TransformStep",
    "mapping_doc",
]


class TransformStep(SpecModel):
    """One step of a transform chain, normalized at parse (RFC 0002 §5.5) from
    either a bare name (``to_int``) or a single-key mapping
    (``{parse_ts: "ISO8601"}``) into ``(name, args)``."""

    name: str
    args: tuple[str | int, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, value: object) -> object:
        if isinstance(value, str):
            return {"name": value}
        if isinstance(value, AbcMapping):
            mapping = cast("AbcMapping[object, object]", value)
            if set(mapping.keys()) in ({"name"}, {"name", "args"}):
                return mapping  # already-normalized form (round-trips)
            if len(mapping) == 1:
                ((name, raw_args),) = mapping.items()
                args: tuple[object, ...] = (
                    tuple(cast("list[object] | tuple[object, ...]", raw_args))
                    if isinstance(raw_args, (list, tuple))
                    else (raw_args,)
                )
                return {"name": name, "args": args}
            msg = (
                "a transform step is a bare name or a single-key mapping "
                f"({{name: arg}}), got {len(mapping)} keys: {sorted(map(str, mapping.keys()))}"
            )
            raise ValueError(msg)
        msg = f"a transform step is a bare name or a single-key mapping, got {type(value).__name__}"
        raise ValueError(msg)


class KeyField(SpecModel):
    """Key-column lowering: a JSONPath-lite source path plus transform chain."""

    from_: JsonPath = Field(alias="from")
    transform: tuple[TransformStep, ...] = ()


class SimpleFieldMapping(SpecModel):
    """Direct field mapping: one source path plus a transform chain, and the
    field's ``quality:`` rules (RFC 0016 §5.3)."""

    from_: JsonPath = Field(alias="from")
    transform: tuple[TransformStep, ...] = ()
    quality: tuple[FieldQualityRule, ...] = ()


class RecipeFieldMapping(SpecModel):
    """Recipe field mapping: a recorded catalog recipe id (chosen upstream,
    reproduced here — RFC 0005 D2) plus the alias→path bindings its
    ``requires`` names.

    ``direct`` records that the source *also* carries the field directly — the
    path-conflict state (RFC 0006 §5.5, D7): the compiler then emits the
    derived column, a ``<name>__direct`` shadow, and a reconciliation audit.
    It never picks one silently, and omitting the direct path to silence the
    shadow is a recorded upstream decision, not a compiler default.
    """

    recipe: str
    from_: dict[str, JsonPath] = Field(alias="from")
    direct: JsonPath | None = None
    quality: tuple[FieldQualityRule, ...] = ()


def _field_mapping_tag(value: object) -> str:
    if isinstance(value, AbcMapping) and "recipe" in value:
        return "recipe"
    if isinstance(value, RecipeFieldMapping):
        return "recipe"
    return "simple"


FieldMapping = Annotated[
    Annotated[SimpleFieldMapping, Tag("simple")] | Annotated[RecipeFieldMapping, Tag("recipe")],
    Discriminator(_field_mapping_tag),
]
"""Discriminated union on the presence of ``recipe`` (RFC 0002 §5.5)."""


class Mapping(SpecModel):
    """One (source, target entity) mapping document (``mapping_version``)."""

    mapping_version: int = Field(ge=1)
    source: str
    target: str
    key: dict[str, KeyField]
    fields: dict[MemberName, FieldMapping] = Field(default_factory=dict)
    unmapped: tuple[JsonPath, ...] = ()
    # ``on_unmapped_enum`` is retired here (RFC 0016 §5.2, D3 — an RFC 0002
    # amendment): a one-value policy no emitter ever implemented, superseding
    # RFC 0008 D7's paper `<entity>__quarantine` convention. An unmapped enum
    # value now simply fails the ``in_enum`` rule and takes that rule's
    # disposition, through one mechanism and one reject table.


def mapping_doc(mapping: Mapping) -> str:
    """The deterministic source-path label for one mapping document — parsed
    models do not retain their document names (RFC 0002 §5.3), so both the
    resolve and guardrail stages address a mapping by this label."""
    return f"mapping[{mapping.source}->{mapping.target}]"
