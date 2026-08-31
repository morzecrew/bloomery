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
from typing import Annotated, Literal, Self, cast

from pydantic import Discriminator, Field, Tag, model_validator
from pydantic.json_schema import SkipJsonSchema

from bloomery.spec.common import JsonPath, MemberName, SpecModel
from bloomery.spec.quality import FieldQualityRule
from bloomery.spec.steps import ParameterValue, StepUse

# ----------------------- #

__all__ = [
    "ALIAS_BOUND",
    "FieldMapping",
    "KeyField",
    "MacroFieldMapping",
    "Mapping",
    "RecipeFieldMapping",
    "SimpleFieldMapping",
    "TransformStep",
    "mapping_doc",
]


class TransformStep(SpecModel):
    """One step of a transform chain, normalized at parse (RFC 0002 §5.5) from
    either a bare name (``to_int``) or a single-key mapping
    (``{parse_ts: "ISO8601"}``) into ``(name, args)``.

    ``step`` is the Tier 1 link (RFC 0017 D51): ``{step: extract_domain@1}``
    splices a ``sql_macro`` into the chain at that position. It is a separate
    field rather than a reserved transform *name* because a whitelist entry
    called ``step`` would otherwise shadow it silently — and the whitelist is
    open to additions by RFC amendment (RFC 0004), so "no transform is called
    that today" is not a property anything guarantees.
    """

    name: str = ""
    args: tuple[str | int, ...] = ()
    step: StepUse | None = None

    # ....................... #

    @model_validator(mode="after")
    def _is_one_kind_of_link(self) -> Self:
        if bool(self.name) == (self.step is not None):
            msg = "a chain step is either a transform name or a step: reference, never both"
            raise ValueError(msg)

        return self

    # ....................... #

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, value: object) -> object:
        if isinstance(value, str):
            return {"name": value}

        if isinstance(value, AbcMapping):
            mapping = cast("AbcMapping[object, object]", value)
            if "step" in mapping:
                return mapping  # the Tier 1 link — no name/args to normalize
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


# ....................... #


class KeyField(SpecModel):
    """Key-column lowering: a JSONPath-lite source path plus transform chain."""

    from_: JsonPath = Field(alias="from")
    transform: tuple[TransformStep, ...] = ()


# ....................... #


class SimpleFieldMapping(SpecModel):
    """Direct field mapping: one source path plus a transform chain, and the
    field's ``quality:`` rules (RFC 0016 §5.3)."""

    from_: JsonPath = Field(alias="from")
    transform: tuple[TransformStep, ...] = ()
    quality: tuple[FieldQualityRule, ...] = ()


# ....................... #


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


# ....................... #


class MacroFieldMapping(SpecModel):
    """A field computed by a Tier 1 ``sql_macro`` (RFC 0017 §5.1, D50).

    The third field shape, beside a direct ``from:`` and a catalog
    ``recipe:``. ``step`` names the macro as ``ref@version``; ``from`` binds
    each ``:name`` its body refers to, exactly as a recipe binds the aliases
    its ``requires`` names. Both read the same way on purpose — a macro is a
    recipe the platform owns and versions, rather than one the catalog
    declares.

    ``parameters`` are supplied **here**, at the call site, not in the
    ``steps:`` document. A macro writes no relation, so it has no output to
    bind there; and one wiring per ref (RFC 0017 D13) would make a macro
    usable in exactly one mapping, with one parameter set — which is the
    pressure that produces ``fuzzy_score_strict`` and is the fork §5.7 exists
    to refuse.

    There is still no field here that can hold a body. The macro's SQL comes
    from the registry the caller assembled, never from the spec (§5.3, D3).
    """

    step: StepUse
    from_: dict[str, JsonPath] = Field(alias="from", default_factory=dict[str, JsonPath])
    parameters: dict[str, ParameterValue] = Field(default_factory=dict[str, ParameterValue])
    quality: tuple[FieldQualityRule, ...] = ()


# ....................... #


def _field_mapping_tag(value: object) -> str:
    if isinstance(value, AbcMapping):
        if "recipe" in value:
            return "recipe"
        if "step" in value:
            return "macro"

    if isinstance(value, RecipeFieldMapping):
        return "recipe"

    if isinstance(value, MacroFieldMapping):
        return "macro"

    return "simple"


# ....................... #


FieldMapping = Annotated[
    Annotated[SimpleFieldMapping, Tag("simple")]
    | Annotated[RecipeFieldMapping, Tag("recipe")]
    | Annotated[MacroFieldMapping, Tag("macro")],
    Discriminator(_field_mapping_tag),
]
"""Discriminated union on the presence of ``recipe`` or ``step`` (RFC 0002
§5.5, RFC 0017 D50)."""

#: The two shapes that bind **several** source paths under aliases, rather
#: than one path directly. They differ in where the expression comes from — a
#: catalog recipe or a platform macro — and agree on everything a caller that
#: only wants the paths cares about, which is why those callers test for this
#: pair instead of naming one class and falling through on the other.
ALIAS_BOUND = (RecipeFieldMapping, MacroFieldMapping)


class Mapping(SpecModel):
    """One (source, target entity) mapping document (``mapping_version``)."""

    #: The document this mapping was parsed from — the identity two reports need
    #: in order to name an edit (RFC 0032 D1). It is unique by construction (a
    #: key of ``load_project``'s ``sources``), already orders
    #: :attr:`~bloomery.spec.project.Project.mappings`, and is already the
    #: prefix on this document's refusals (RFC 0002 §5.3).
    #:
    #: **Set by the loader, never authored** (RFC 0032 D3): a document
    #: declaring ``document:`` is refused, because a document asserting its own
    #: filename is a second source of truth that can disagree with the first.
    #:
    #: ``SkipJsonSchema`` for that same reason, and it is load-bearing rather
    #: than cosmetic. ``bloomery schema`` exports these models for editors to
    #: validate against (RFC 0020), and its audience is a spec *author* — so a
    #: required ``document`` in the exported schema would have an editor demand
    #: the one key the loader refuses. The schema describes the authored
    #: vocabulary; this field is not in it.
    document: SkipJsonSchema[str]
    #: Pinned to the one version bloomery implements (RFC 0018 D7). It was
    #: ``int`` with ``ge=1``, which accepted a document written for a future
    #: bloomery and silently applied v1 semantics to it — the exact misreading
    #: a version key exists to refuse. This key is also the document-kind
    #: discriminator, so it stays required: a document without one cannot be
    #: identified at all.
    mapping_version: Literal[1]
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


# ....................... #


def mapping_doc(mapping: Mapping) -> str:
    """The deterministic source-path label for one mapping document — parsed
    models do not retain their document names (RFC 0002 §5.3), so both the
    resolve and guardrail stages address a mapping by this label."""

    return f"mapping[{mapping.source}->{mapping.target}]"
