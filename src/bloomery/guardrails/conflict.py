"""Path conflict — the guardrail that does not raise (RFC 0006 §5.5, D7).

When a field records both a satisfiable derivation and a direct source
column (``direct:`` on the recipe mapping, RFC 0002 §5.5), any silent choice
is wrong: the two can disagree, and whichever the compiler picked, the
discrepancy would become invisible. So the stage amends the IR to emit
**both** — the derived column under the field's name (the recipe is the
recorded, auditable decision), a ``<name>__direct`` shadow column carrying
the direct value, and a ``reconcile`` :class:`~bloomery.ir.AuditIR` whose
target-native lowering surfaces row-level disagreement (RFC 0008). Never an
error: both paths are individually valid, so the refusal targets the
silence, not the spec.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlglot import exp

from bloomery.errors import guaranteed
from bloomery.ir import AuditIR, ColumnIR, SourceColumnIR, canon, extraction, generic_type

if TYPE_CHECKING:
    from bloomery.guardrails.operands import Derivation
    from bloomery.ir import EntityIR, ProjectIR

__all__ = [
    "path_conflict_amendments",
]


def _shadow(derived: ColumnIR, direct: str) -> tuple[ColumnIR, SourceColumnIR]:
    """The direct-path shadow: same declared type and catalog metadata as the
    derived column (it is the same canonical field), lowered as a declared-
    type cast of the direct extraction (RFC 0005 lowering rules).

    Returns both halves (RFC 0024 D26). This is the **second** place a lowering
    is built — the first is ``resolve.build._column_pair`` — because the shadow
    is an amendment the guardrail stage adds after the builder has run.

    It stays single-source, and that is a decision rather than an oversight:
    ``direct:`` is per mapping, so a merged entity could declare one on one
    source and not another, leaving this shadow NULL for the other's rows and
    a reconcile audit that silently stops checking. RFC 0024 D28 refuses the
    combination, which is what keeps this function one-to-one.
    """
    return (
        ColumnIR(
            name=f"{derived.name}__direct",
            type=derived.type,
            canonical=derived.canonical,
            unit=derived.unit,
            tax_basis=derived.tax_basis,
            renamed_from=None,
            required=False,
        ),
        SourceColumnIR(
            name=f"{derived.name}__direct",
            expr=canon(exp.cast(extraction(direct), generic_type(derived.type))),
        ),
    )


def path_conflict_amendments(
    derivations: tuple[Derivation, ...], draft: ProjectIR
) -> tuple[dict[str, list[tuple[ColumnIR, SourceColumnIR]]], dict[str, list[AuditIR]]]:
    """Per-entity shadow columns and reconcile audits for every derivation
    that also records a ``direct:`` path."""
    entities: dict[str, EntityIR] = {entity.name: entity for entity in draft.entities}
    shadows: dict[str, list[tuple[ColumnIR, SourceColumnIR]]] = {}
    audits: dict[str, list[AuditIR]] = {}
    for derivation in derivations:
        if derivation.direct is None:
            continue
        entity = entities[derivation.entity]
        derived = guaranteed(
            (column for column in entity.columns if column.name == derivation.field),
            expected=f"the derived column {derivation.field!r} on entity {entity.name!r}",
            by="resolution, which builds the column it derives",
        )
        shadows.setdefault(derivation.entity, []).append(_shadow(derived, derivation.direct))
        audits.setdefault(derivation.entity, []).append(
            AuditIR(
                kind="reconcile",
                column=derivation.field,
                params=(("shadow", f"{derivation.field}__direct"),),
            )
        )
    return shadows, audits
