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

from bloomery.ir import AuditIR, ColumnIR, canon, extraction, generic_type

if TYPE_CHECKING:
    from bloomery.guardrails.operands import Derivation
    from bloomery.ir import EntityIR, ProjectIR

__all__ = [
    "path_conflict_amendments",
]


def _shadow(derived: ColumnIR, direct: str) -> ColumnIR:
    """The direct-path shadow: same declared type and catalog metadata as the
    derived column (it is the same canonical field), lowered as a declared-
    type cast of the direct extraction (RFC 0005 lowering rules)."""
    return ColumnIR(
        name=f"{derived.name}__direct",
        type=derived.type,
        canonical=derived.canonical,
        unit=derived.unit,
        tax_basis=derived.tax_basis,
        expr=canon(exp.cast(extraction(direct), generic_type(derived.type))),
        recipe_id=None,
        renamed_from=None,
        required=False,
    )


def path_conflict_amendments(
    derivations: tuple[Derivation, ...], draft: ProjectIR
) -> tuple[dict[str, list[ColumnIR]], dict[str, list[AuditIR]]]:
    """Per-entity shadow columns and reconcile audits for every derivation
    that also records a ``direct:`` path."""
    entities: dict[str, EntityIR] = {entity.name: entity for entity in draft.entities}
    shadows: dict[str, list[ColumnIR]] = {}
    audits: dict[str, list[AuditIR]] = {}
    for derivation in derivations:
        if derivation.direct is None:
            continue
        entity = entities[derivation.entity]
        derived = next(column for column in entity.columns if column.name == derivation.field)
        shadows.setdefault(derivation.entity, []).append(_shadow(derived, derivation.direct))
        audits.setdefault(derivation.entity, []).append(
            AuditIR(
                kind="reconcile",
                column=derivation.field,
                params=(("shadow", f"{derivation.field}__direct"),),
            )
        )
    return shadows, audits
