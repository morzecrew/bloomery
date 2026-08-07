"""Data-quality guardrails (RFC 0016 §5.9) — the checks that say the *model*
is wrong.

Every refusal here is decidable from the spec alone, which is exactly what
makes it a guardrail rather than a quality rule (D13): a guardrail says the
model is wrong, at compile time, from the spec; a quality rule says the data
is wrong, at run time, per row. All of them are :class:`GuardrailError` leaves
declared in ``errors.py`` (RFC 0002 D3) and returned — never raised — so they
batch into the stage's single aggregate and an author fixes a spec in one
round-trip (RFC 0006 D2).

The seven checks:

======================================  ==============================
``DedupeTieBreakMissing``               §5.3, D6
``DedupeDispositionConflict``           §5.4, D6
``QuarantineRetentionMissing``          §5.6, D10
``IngestionMetadataMissing``            §5.6, D21
``RedactionConflict``                   §5.6, D10
``pattern`` portability                 §5.3, D5 (bare ``GuardrailError``)
``unknown_member`` on a non-string fk   §5.4, D6 (bare ``GuardrailError``)
======================================  ==============================

The last two are bare :class:`GuardrailError` deliberately: §5.9 enumerates
exactly five *named* new leaves, and both refusals are stated in the RFC prose
without minting one ("a compile-time ``GuardrailError`` naming the
alternatives", §5.4). Inventing a sixth and seventh leaf would put names in
``errors.py`` the design authority does not have.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bloomery.errors import (
    DedupeDispositionConflict,
    DedupeTieBreakMissing,
    GuardrailError,
    IngestionMetadataMissing,
    QuarantineRetentionMissing,
    RedactionConflict,
)
from bloomery.ir import OnFail
from bloomery.quality import (
    INGESTION_METADATA,
    disposition,
    lower_quality,
    mapped_fields,
    params_of,
    payload_key,
    unsupported_dialects,
)
from bloomery.spec.mapping import RecipeFieldMapping, mapping_doc
from bloomery.spec.quality import CoercibleRule, PatternRule
from bloomery.typing import StringType, parse_type

if TYPE_CHECKING:
    from bloomery.ir import ProjectIR
    from bloomery.spec.entity import Entity, Relationship
    from bloomery.spec.mapping import Mapping
    from bloomery.spec.project import Project

__all__ = [
    "check_quality",
]


def _entity_path(entity_name: str, suffix: str) -> str:
    return f"entity_model: entities.{entity_name}.{suffix}"


def _read_paths(mapping: Mapping) -> tuple[str, ...]:
    """Every JSONPath the mapping reads — key ``from``s, field ``from``s, and
    every recipe alias binding (RFC 0016 §5.6 names the aliases explicitly).
    ``unmapped:`` is *not* read: it is the acknowledged tail."""
    paths: set[str] = {key_field.from_ for key_field in mapping.key.values()}
    for field_mapping in mapping.fields.values():
        if isinstance(field_mapping, RecipeFieldMapping):
            paths.update(field_mapping.from_.values())
        else:
            paths.add(field_mapping.from_)
    return tuple(sorted(paths))


def _declared_paths(mapping: Mapping) -> frozenset[str]:
    """Every bronze path the mapping states exists — read paths plus the
    acknowledged ``unmapped:`` tail."""
    return frozenset({*_read_paths(mapping), *mapping.unmapped})


# ....................... #
# The checks


def _check_dedupe(entity_name: str, entity: Entity) -> list[GuardrailError]:
    if entity.dedupe is None or entity.dedupe.tie_break:
        return []
    msg = (
        f"entity {entity_name!r} declares dedupe.keep: {entity.dedupe.keep} on "
        f"{entity.dedupe.field!r} without tie_break — two rows sharing a "
        f"{entity.dedupe.field} would make the winner arbitrary, and a nondeterministic "
        "model violates the core invariant (RFC 0003). Fix: add tie_break: [<column>, …]"
    )
    return [DedupeTieBreakMissing(msg, source_path=_entity_path(entity_name, "dedupe"))]


def _check_dedupe_disposition(
    entity_name: str, entity: Entity, mapping: Mapping
) -> list[GuardrailError]:
    """``coercible`` is forced to ``fail`` on any field the dedupe order reads
    (§5.4): an uncastable recency field leaves dedupe ordering undefined, so a
    weaker declared disposition on such a field is a contradiction, not a
    preference."""
    if entity.dedupe is None:
        return []
    ordering = {entity.dedupe.field: "dedupe.field"} | dict.fromkeys(
        entity.dedupe.tie_break, "dedupe.tie_break"
    )
    errors: list[GuardrailError] = []
    for column, field_mapping in mapped_fields(mapping):
        if column not in ordering or field_mapping is None:
            continue
        for rule in field_mapping.quality:
            if isinstance(rule, CoercibleRule) and rule.on_fail != "fail":
                msg = (
                    f"field {column!r} of entity {entity_name!r} declares "
                    f"{{rule: coercible, on_fail: {rule.on_fail}}}, but {ordering[column]} "
                    f"reads {column!r} — the fixed pipeline order deduplicates before the "
                    "rules run (RFC 0016 §5.4), so an uncastable value there leaves the "
                    "dedupe order undefined and coercible is forced to 'fail'. Fix: write "
                    "on_fail: fail, or order dedupe by a different column"
                )
                errors.append(
                    DedupeDispositionConflict(
                        msg, source_path=f"{mapping_doc(mapping)}: fields.{column}.quality"
                    )
                )
    return errors


def _check_retention(
    entity_name: str, entity: Entity, mapping: Mapping, relationships: tuple[Relationship, ...]
) -> list[GuardrailError]:
    if entity.quarantine is not None:
        return []
    quarantining = [
        rule
        for rule in lower_quality(entity, mapping, relationships)
        if disposition(rule) is OnFail.QUARANTINE
    ]
    if not quarantining:
        return []
    names = ", ".join(sorted(rule.name for rule in quarantining))
    msg = (
        f"entity {entity_name!r} has quarantine dispositions ({names}) but no quarantine: "
        "block — reject rows hold raw source payloads, and therefore PII, so retention is "
        "required and never defaulted (RFC 0016 §5.6). Note that the implicit coercible "
        "rule carries the quarantine default (§5.2), so an entity with any quality: surface "
        "has one even when nothing spells it. Fix: add quarantine: {retention: 90d}"
    )
    return [QuarantineRetentionMissing(msg, source_path=_entity_path(entity_name, "quarantine"))]


def _check_ingestion_metadata(
    entity_name: str, entity: Entity, mapping: Mapping
) -> list[GuardrailError]:
    """An entity using ``quarantine`` or ``dedupe`` requires all three bronze
    metadata columns (D21).

    **How a mapping "supplies" them (an RFC ambiguity resolved).** They are
    reserved member names, so no entity field and no mapping target may be
    called ``_load_id``; the one surface where a mapping states that a bronze
    column *exists* without mapping it is ``unmapped:``. So presence means:
    the path appears among the mapping's declared source paths — a ``from``,
    a recipe alias binding, or the acknowledged tail. That keeps the check
    decidable from the spec alone, which is what makes it a guardrail at all.
    """
    if entity.quarantine is None and entity.dedupe is None:
        return []
    declared = _declared_paths(mapping)
    missing = [column for column in INGESTION_METADATA if f"$.{column}" not in declared]
    if not missing:
        return []
    using = "quarantine" if entity.quarantine is not None else "dedupe"
    msg = (
        f"entity {entity_name!r} uses {using}, so its bronze source "
        f"{mapping.source!r} must supply the ingestion metadata contract "
        f"({', '.join(INGESTION_METADATA)}), but the mapping declares none of "
        f"{', '.join(missing)} (RFC 0016 §5.6, D21). Fix: map or acknowledge them, "
        f"e.g. unmapped: [{', '.join(repr(f'$.{column}') for column in missing)}]"
    )
    return [IngestionMetadataMissing(msg, source_path=f"{mapping_doc(mapping)}: unmapped")]


def _check_redaction(entity_name: str, entity: Entity, mapping: Mapping) -> list[GuardrailError]:
    if entity.quarantine is None:
        return []
    # Column granularity, matching what ``raw`` can express: ``raw`` is the
    # bronze *row*, so redaction removes a whole column. Refusing at the same
    # granularity means a ``redact: $.a.b`` alongside a mapped ``$.a.c`` is a
    # compile error rather than a silent over-removal that breaks replay.
    read = {payload_key(path) for path in _read_paths(mapping)}
    clashing = sorted(path for path in entity.quarantine.redact if payload_key(path) in read)
    if not clashing:
        return []
    msg = (
        f"quarantine.redact on entity {entity_name!r} lists {', '.join(clashing)}, whose "
        f"bronze column mapping {mapping_doc(mapping)} reads — you cannot both require a "
        "field and destroy "
        "it at write time (RFC 0016 §5.6): replay re-runs the current mapping against raw, "
        "and a redacted path is gone by then. Fix: stop mapping the path, or stop redacting it"
    )
    return [RedactionConflict(msg, source_path=_entity_path(entity_name, "quarantine.redact"))]


def _check_patterns(entity_name: str, mapping: Mapping) -> list[GuardrailError]:
    errors: list[GuardrailError] = []
    for column, field_mapping in mapped_fields(mapping):
        if field_mapping is None:
            continue
        for rule in field_mapping.quality:
            if not isinstance(rule, PatternRule):
                continue
            unsupported = unsupported_dialects(rule.regex)
            if unsupported:
                msg = (
                    f"pattern rule on field {column!r} of entity {entity_name!r} cannot be "
                    f"expressed on dialect(s) {', '.join(unsupported)}: {rule.regex!r} "
                    "(RFC 0016 §5.3). A regex that works on one dialect and silently means "
                    "something else on another is the bug this check exists to prevent. "
                    "Fix: narrow the pattern to the portable subset, or drop the rule"
                )
                errors.append(
                    GuardrailError(
                        msg, source_path=f"{mapping_doc(mapping)}: fields.{column}.quality"
                    )
                )
    return errors


def _check_unknown_member(
    entity_name: str, entity: Entity, mapping: Mapping, relationships: tuple[Relationship, ...]
) -> list[GuardrailError]:
    """``unknown_member`` requires a string-typed fk in v1 (§5.4).

    The reserved member is the *string* ``'__unknown__'`` — there is nowhere
    sound to put it in a non-string key, and a typed sentinel like ``-1``
    colliding with a legal key value is exactly the silent wrongness this
    project refuses.
    """
    by_name = {relationship.name: relationship for relationship in relationships}
    errors: list[GuardrailError] = []
    for rule in lower_quality(entity, mapping, relationships):
        params = params_of(rule)
        if rule.kind != "referential" or params["on_missing"] != "unknown_member":
            continue
        relationship = by_name[params["relationship"]]
        # Resolution (RFC 0005) has already refused a ``via`` naming a column
        # neither entity declares, so the lookup is total by the time the
        # guardrail stage runs.
        from_column = sorted(relationship.via)[0]
        field = entity.fields[from_column]
        declared = parse_type(
            field.type, source_path=_entity_path(entity_name, f"fields.{from_column}.type")
        )
        if not isinstance(declared, StringType):
            msg = (
                f"referential rule via {relationship.name!r} on entity {entity_name!r} "
                f"declares on_missing: unknown_member, but the fk {from_column!r} is "
                f"{field.type!r} — the reserved member is the string '__unknown__', and "
                "there is nowhere sound to put it in a non-string key (RFC 0016 §5.4; typed "
                "per-key sentinels are rejected because one could collide with a legal "
                "value). Fix: use on_missing: quarantine or flag, or map the key to string"
            )
            errors.append(GuardrailError(msg, source_path=_entity_path(entity_name, "quality")))
    return errors


def check_quality(draft: ProjectIR, project: Project) -> list[GuardrailError]:
    """Every data-quality guardrail over the whole project, in one pass.

    ``draft`` is accepted for symmetry with the stage's other checks and to
    keep the seam honest — these refusals are all decidable from the spec, so
    nothing here reads the lowered IR.
    """
    del draft
    relationships = project.entity_model.relationships
    by_target = {mapping.target: mapping for mapping in project.mappings}
    errors: list[GuardrailError] = []
    for entity_name in sorted(project.entity_model.entities):
        entity = project.entity_model.entities[entity_name]
        mapping = by_target.get(entity_name)
        if mapping is None:
            continue  # an unmapped entity emits nothing; nothing to refuse
        errors.extend(_check_dedupe(entity_name, entity))
        errors.extend(_check_dedupe_disposition(entity_name, entity, mapping))
        errors.extend(_check_ingestion_metadata(entity_name, entity, mapping))
        errors.extend(_check_redaction(entity_name, entity, mapping))
        errors.extend(_check_patterns(entity_name, mapping))
        # Both of these read the *lowered* rules rather than the opt-in flag:
        # ``lower_quality`` is empty for an entity that never joined the
        # quality system, so they are silently satisfied there.
        errors.extend(_check_retention(entity_name, entity, mapping, relationships))
        errors.extend(_check_unknown_member(entity_name, entity, mapping, relationships))
    return errors
