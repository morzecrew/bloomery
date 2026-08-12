"""Shared spec-layer plumbing (RFC 0002 §5.1–§5.3, §5.6).

Hosts the strict :class:`SpecModel` base, the source-path conversion from
Pydantic ``loc`` tuples to dotted/bracketed authored-document addresses, the
shared grammars (type strings, partition specs, JSONPath-lite) and shared
sub-models (:class:`RatioSpec`, :class:`SemiAdditivePolicy`), and the strict
YAML loader that rejects duplicate keys (RFC 0002 D5).

Only :mod:`bloomery.errors` may be imported from here — the spec layer knows
nothing internal but errors (import-linter contract).
"""

from __future__ import annotations

from collections.abc import Hashable
from decimal import Decimal
from typing import Annotated, Any, Literal, cast

import yaml
from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints
from pydantic import ValidationError as PydanticValidationError

from bloomery.errors import BloomeryError, SpecParseError

__all__ = [
    "JSONPATH_PATTERN",
    "PARTITION_SPEC_PATTERN",
    "RESERVED_MEMBER_NAMES",
    "TYPE_STRING_PATTERN",
    "AdditivityName",
    "CardinalityName",
    "CurrencyCode",
    "JsonPath",
    "MaterializationName",
    "MemberName",
    "RELATION_NAME_PATTERN",
    "RelationName",
    "ParameterValue",
    "PartitionSpecString",
    "RatioSpec",
    "SemiAdditivePolicy",
    "SpecModel",
    "StepUse",
    "TypeString",
    "USE_PATTERN",
    "flatten_collected",
    "load_yaml_mapping",
    "source_path_from_loc",
    "validate_document",
]

# ....................... #
# Grammars (RFC 0002 §5.5) — shape-only; semantics live downstream.

#: The closed logical-type grammar (RFC 0004 §5.1). The spec layer validates the
#: grammar only; ``bloomery.typing.parse_type`` consumes the same pattern.
TYPE_STRING_PATTERN = (
    r"^(?:string|int|bool|date|timestamp|variant|decimal\((\d{1,3}), ?(\d{1,3})\))$"
)

#: Iceberg-style partition entries: a bare column or ``fn(column)`` with
#: ``fn ∈ {days, months, years, hours}`` (RFC 0002 §5.5).
PARTITION_SPEC_PATTERN = (
    r"^(?:(days|months|years|hours)\(([A-Za-z_][A-Za-z0-9_]*)\)|[A-Za-z_][A-Za-z0-9_]*)$"
)

#: JSONPath-lite: ``$.a.b`` dotted paths only (RFC 0002 §5.5).
JSONPATH_PATTERN = r"^\$(?:\.[A-Za-z_][A-Za-z0-9_]*)+$"

#: Names the compiler generates, so an authored field/dimension/role may never
#: claim one — the generated column would collide silently. ``metric_time`` is
#: MetricFlow's canonical query-time dimension (RFC 0002 D10, RFC 0013 R4); the
#: rest are the data-quality columns and the bronze ingestion-metadata contract
#: (RFC 0016 §5.5, §5.6, D9/D21/D23). Each carries the reason its message
#: quotes: a bare "reserved" tells an author nothing about which layer owns it.
_RESERVED_MEMBER_REASONS: dict[str, str] = {
    "metric_time": "RFC 0013 R4: the canonical query-time dimension",
    "_quality_flags": "RFC 0016 D9: the generated silver quality-flag column",
    "_quality_ok": "RFC 0016 D9: generated from _quality_flags",
    "_quality_repairs": "RFC 0016 D87: the generated repair marker",
    "_load_id": "RFC 0016 D21: bronze ingestion metadata",
    "_ingested_at": "RFC 0016 D21: bronze ingestion metadata",
    "_source_row_id": "RFC 0016 D21: the stable source-row identity",
    "has_quality_flags": "RFC 0016 D9: the generated mart dimension",
}

#: The reserved names, sorted — the message vocabulary lives in
#: :data:`_RESERVED_MEMBER_REASONS`.
RESERVED_MEMBER_NAMES = tuple(sorted(_RESERVED_MEMBER_REASONS))


def _reject_reserved(name: str) -> str:
    reason = _RESERVED_MEMBER_REASONS.get(name)
    if reason is not None:
        msg = f"{name!r} is a reserved name ({reason}); pick a different field/dimension/role name"
        raise ValueError(msg)
    return name


TypeString = Annotated[str, StringConstraints(pattern=TYPE_STRING_PATTERN)]
PartitionSpecString = Annotated[str, StringConstraints(pattern=PARTITION_SPEC_PATTERN)]
JsonPath = Annotated[str, StringConstraints(pattern=JSONPATH_PATTERN)]
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
MemberName = Annotated[str, AfterValidator(_reject_reserved)]

#: A name that becomes a **relation** — an entity or a mart (RFC 0002 D14).
#:
#: Stricter than :data:`MemberName` because it travels further. A field name
#: reaches SQL through SQLGlot, which quotes and escapes it; a relation name
#: also reaches the SQLMesh ``MODEL (...)`` envelope, which is Jinja over
#: pre-rendered strings and quotes nothing — so an entity named
#: ``t"; DROP TABLE x --`` put those characters into the model definition
#: verbatim. The pattern is the fix rather than escaping at the envelope: a
#: relation name has no business carrying anything but identifier characters,
#: and ``StepRef`` is pinned the same way for the same reason.
RELATION_NAME_PATTERN = r"^[a-z][a-z0-9_]*$"
RelationName = Annotated[
    str, StringConstraints(pattern=RELATION_NAME_PATTERN), AfterValidator(_reject_reserved)
]

AdditivityName = Literal["additive", "semi_additive", "non_additive"]
CardinalityName = Literal["many_to_one", "one_to_one", "one_to_many"]
MaterializationName = Literal["full", "incremental_by_key", "incremental_by_partition"]

# ....................... #
# Base model (RFC 0002 §5.2)


class SpecModel(BaseModel):
    """Base of every spec model: strict (unknown keys are hard errors), frozen
    (a parsed spec is immutable), whitespace-stripped strings."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class RatioSpec(SpecModel):
    """Additive decomposition of a non-additive metric (RFC 0002 D9, RFC 0011 D5)."""

    numerator: str
    denominator: str


class SemiAdditivePolicy(SpecModel):
    """Typed semi-additive policy (RFC 0002 §5.5): the dimension the metric is
    not additive over, and the rule applied along it."""

    over: str
    rule: Literal["last", "first", "avg", "min", "max"]


# ....................... #
# Source paths (RFC 0002 §5.3)


def source_path_from_loc(document: str, loc: tuple[int | str, ...]) -> str:
    """Convert a Pydantic ``loc`` tuple into a document-prefixed source path.

    Dict keys join with ``.``, list indices render as ``[n]``, and the document
    name prefixes the path: ``mappings/shopify: fields.unit_price.from``.
    Pydantic's ``[key]`` marker (a failing dict *key*) is dropped — the path
    already ends at the key itself.
    """
    parts: list[str] = []
    for item in loc:
        if isinstance(item, int):
            parts.append(f"[{item}]")
        elif item == "[key]":
            continue
        else:
            parts.append(f".{item}" if parts else str(item))
    if not parts:
        return document
    return f"{document}: {''.join(parts)}"


def validate_document[ModelT: SpecModel](
    model_cls: type[ModelT], data: object, *, document: str
) -> ModelT:
    """Validate one parsed YAML document against a spec model.

    Pydantic's ``ValidationError`` never escapes (RFC 0002 D3): every failure
    is converted to a :class:`SpecParseError` with a document-prefixed source
    path, and multiple failures in one document are batched into a single
    aggregate error listing every path (RFC 0002 D6).
    """
    try:
        return model_cls.model_validate(data)
    except PydanticValidationError as exc:
        collected = tuple(
            SpecParseError(
                str(err["msg"]),
                source_path=source_path_from_loc(document, tuple(err["loc"])),
            )
            for err in exc.errors()
        )
        if len(collected) == 1:
            raise collected[0] from None
        raise SpecParseError.from_collected(collected) from None


# ....................... #
# YAML parsing (RFC 0002 §5.6)


class _StrictSafeLoader(yaml.SafeLoader):
    """``yaml.SafeLoader`` that rejects duplicate mapping keys.

    PyYAML's default silently keeps the last value — exactly the silent
    failure the spec layer exists to prevent (RFC 0002 D5).
    """

    def _construct_key(self, node: yaml.Node) -> object:
        """``construct_object`` pinned to ``object`` — types-PyYAML leaves it untyped."""
        return cast(
            "object",
            self.construct_object(node, deep=True),  # pyright: ignore[reportUnknownMemberType]
        )

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Hashable, Any]:
        seen: set[object] = set()
        for key_node, _value_node in node.value:
            key = self._construct_key(key_node)
            if isinstance(key, (dict, list)):  # unhashable — SafeLoader rejects later
                continue
            if key in seen:
                raise yaml.MarkedYAMLError(
                    problem=f"duplicate key {key!r}",
                    problem_mark=key_node.start_mark,
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def load_yaml_mapping(text: str, *, document: str) -> dict[str, object]:
    """Parse one YAML document into a mapping, strictly.

    Duplicate keys, YAML syntax errors, unsafe tags, and non-mapping roots are
    all :class:`SpecParseError` with the document name as source path.
    """
    try:
        # SafeLoader subclass: only plain YAML types construct (RFC 0002 §5.6).
        data = yaml.load(text, Loader=_StrictSafeLoader)  # nosec B506
    except yaml.YAMLError as exc:
        raise SpecParseError(f"invalid YAML: {exc}", source_path=document) from exc
    if not isinstance(data, dict):
        raise SpecParseError(
            f"a spec document must be a YAML mapping, got {type(data).__name__}",
            source_path=document,
        )
    mapping = cast("dict[object, object]", data)
    bad_keys = [key for key in mapping if not isinstance(key, str)]
    if bad_keys:
        raise SpecParseError(
            f"spec document keys must be strings, got {bad_keys[0]!r}",
            source_path=document,
        )
    return {str(key): value for key, value in mapping.items()}


def flatten_collected(errors: list[BloomeryError]) -> tuple[BloomeryError, ...]:
    """Flatten already-aggregated errors into one flat collected tuple."""
    flat: list[BloomeryError] = []
    for err in errors:
        if err.collected:
            flat.extend(err.collected)
        else:
            flat.append(err)
    return tuple(flat)


# ....................... #
# Naming and binding a step (RFC 0017 §5.2)
#
# Defined here rather than in ``spec.steps`` — which re-exports both, so every
# shipped import path is unchanged — because two documents name a step and
# ``spec.steps`` imports one of them: ``quality.Repair.via`` references a
# ``sql_macro`` (RFC 0016 D87) while ``spec.steps`` reads ``quality``'s
# ``ExpressionRule`` for a step output's rules. Whichever way that pair is
# written it is a cycle, so the two primitives move below both.

#: ``ref@version`` — the only way a spec names a step.
USE_PATTERN = r"^[a-z][a-z0-9_]*@[1-9][0-9]*$"

StepUse = Annotated[str, StringConstraints(pattern=USE_PATTERN)]

#: A parameter value a call site may set. ``float`` is deliberately absent
#: (RFC 0003 D5) — a decimal arrives as ``Decimal``, and a YAML float would
#: reach emission as a binary approximation of what the author wrote.
ParameterValue = str | int | bool | Decimal
