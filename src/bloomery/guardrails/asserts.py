"""Range sanity — static validation and lowering of ``assert:`` clauses
(RFC 0006 §5.6, D8).

The guardrail stage validates only that each clause is **well-typed against
the field's logical type**: ``min``/``max`` require a numeric or temporal
field (numeric bounds for numeric fields, ISO string bounds for temporal
ones), ``regex`` a string field with a compilable pattern, ``enum`` members
castable to the field type. An ill-typed clause — or a clause on a field no
mapping lowers, so the audit could never run — is an
:class:`~bloomery.errors.AssertLoweringError`, batched with the rest: a range
assertion that can never run is a silent hole in the audit net.

Valid clauses lower into :class:`~bloomery.ir.AuditIR` entries on the entity
(kinds ``not_null``/``min``/``max``/``enum``/``regex``); rendering them as
target-native audits is the emitters' job (RFC 0008). ``enum`` members are
carried as index-keyed params (``value_0000`` …) so the authored order
survives the params' by-name sort (RFC 0003).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from bloomery.errors import AssertLoweringError, GuardrailError
from bloomery.ir import AuditIR
from bloomery.typing import (
    DateType,
    DecimalType,
    IntType,
    LogicalType,
    StringType,
    TimestampType,
    parse_type,
)

if TYPE_CHECKING:
    from decimal import Decimal

    from bloomery.ir import ProjectIR
    from bloomery.spec.entity import AssertClause, Field
    from bloomery.spec.project import Project

# ----------------------- #

__all__ = [
    "lower_asserts",
]


def _range_audit(
    kind: str,
    value: int | Decimal | str,
    declared: LogicalType,
    type_string: str,
    column: str,
    path: str,
) -> AuditIR | GuardrailError:
    if isinstance(declared, (IntType, DecimalType)):
        if isinstance(value, str):
            msg = (
                f"{kind}: {value!r} is a string but the field is {type_string!r}; a "
                f"numeric field takes a numeric bound. Fix: write {kind}: as a number"
            )
            return AssertLoweringError(msg, source_path=path)
        return AuditIR(kind=kind, column=column, params=(("value", str(value)),))

    if isinstance(declared, (DateType, TimestampType)):
        if isinstance(value, str):
            return AuditIR(kind=kind, column=column, params=(("value", value),))
        msg = (
            f"{kind}: {value!r} is a number but the field is {type_string!r}; a temporal "
            f"field takes an ISO literal. Fix: write {kind}: as a quoted date/timestamp"
        )
        return AssertLoweringError(msg, source_path=path)

    msg = (
        f"{kind}: requires a numeric or temporal field, but the field is {type_string!r} "
        f"— the bound can never run (RFC 0006 §5.6). Fix: drop the clause or retype the "
        "field"
    )
    return AssertLoweringError(msg, source_path=path)


# ....................... #


def _enum_audit(
    members: tuple[str | int, ...],
    declared: LogicalType,
    type_string: str,
    column: str,
    path: str,
) -> AuditIR | GuardrailError:
    member_type: type[str] | type[int]

    if isinstance(declared, StringType):
        member_type = str
    elif isinstance(declared, IntType):
        member_type = int
    else:
        msg = (
            f"enum: requires a string or int field, but the field is {type_string!r}. "
            "Fix: drop the clause or retype the field"
        )
        return AssertLoweringError(msg, source_path=path)

    bad = [member for member in members if not isinstance(member, member_type)]

    if bad:
        msg = (
            f"enum member {bad[0]!r} is not castable to the field type {type_string!r}. "
            f"Fix: write every member as a {member_type.__name__}"
        )
        return AssertLoweringError(msg, source_path=path)

    params = tuple((f"value_{i:04d}", str(member)) for i, member in enumerate(members))
    return AuditIR(kind="enum", column=column, params=params)


# ....................... #


def _regex_audit(
    pattern: str, declared: LogicalType, type_string: str, column: str, path: str
) -> AuditIR | GuardrailError:
    if not isinstance(declared, StringType):
        msg = (
            f"regex: requires a string field, but the field is {type_string!r}. "
            "Fix: drop the clause or map the field as a string"
        )
        return AssertLoweringError(msg, source_path=path)

    try:
        re.compile(pattern)
    except re.error as exc:
        msg = f"regex: {pattern!r} does not compile ({exc}) — the audit can never run"
        return AssertLoweringError(msg, source_path=path)

    return AuditIR(kind="regex", column=column, params=(("pattern", pattern),))


# ....................... #


def _lower_clause(
    clause: AssertClause, field: Field, field_name: str, path: str
) -> list[AuditIR | GuardrailError]:
    declared = parse_type(field.type, source_path=f"{path[: path.rfind('.')]}.type")
    lowered: list[AuditIR | GuardrailError] = []

    if clause.not_null:
        lowered.append(AuditIR(kind="not_null", column=field_name))

    if clause.min is not None:
        lowered.append(_range_audit("min", clause.min, declared, field.type, field_name, path))

    if clause.max is not None:
        lowered.append(_range_audit("max", clause.max, declared, field.type, field_name, path))

    if clause.enum is not None:
        lowered.append(_enum_audit(clause.enum, declared, field.type, field_name, path))

    if clause.regex is not None:
        lowered.append(_regex_audit(clause.regex, declared, field.type, field_name, path))

    return lowered


# ....................... #


def lower_asserts(
    project: Project, draft: ProjectIR
) -> tuple[list[GuardrailError], dict[str, list[AuditIR]]]:
    """Validate every ``assert:`` clause and lower the valid ones.

    Returns the batched errors plus the per-entity audits (only consulted by
    the stage when the whole project is violation-free).
    """
    columns = {entity.name: {column.name for column in entity.columns} for entity in draft.entities}
    errors: list[GuardrailError] = []
    audits: dict[str, list[AuditIR]] = {}

    for entity_name in sorted(project.entity_model.entities):
        entity = project.entity_model.entities[entity_name]
        for field_name in sorted(entity.fields):
            field = entity.fields[field_name]
            if field.assert_ is None:
                continue
            path = f"entity_model: entities.{entity_name}.fields.{field_name}.assert"
            if field_name not in columns.get(entity_name, set()):
                msg = (
                    f"assert: on field {field_name!r} of entity {entity_name!r}, but no "
                    "mapping lowers the field — the audit can never run, a silent hole "
                    "in the audit net (RFC 0006 §5.6). Fix: map the field or drop the "
                    "clause"
                )
                errors.append(AssertLoweringError(msg, source_path=path))
                continue
            for lowered in _lower_clause(field.assert_, field, field_name, path):
                if isinstance(lowered, AuditIR):
                    audits.setdefault(entity_name, []).append(lowered)
                else:
                    errors.append(lowered)

    return errors, audits
