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

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlglot import exp

from bloomery.errors import guaranteed
from bloomery.ir import AuditIR, ColumnIR, SourceColumnIR, canon, extraction
from bloomery.transforms import neutral_type

if TYPE_CHECKING:
    from bloomery.guardrails.operands import Derivation
    from bloomery.ir import EntityIR, ProjectIR

# ----------------------- #

__all__ = [
    "Shadow",
    "path_conflict_amendments",
]


@dataclass(slots=True)
class Shadow:
    """One field's ``__direct`` shadow: the entity column, and the projection
    each source relation contributes to it.

    Mutable, and deliberately not frozen like the IR nodes it carries: it is
    filled branch by branch as the derivations are walked and then completed by
    :func:`_fill`, so ``frozen=True`` would have been true of the binding and
    false of the dict — a claim the reader has to check rather than read.

    The pair travels together for the reason :func:`resolve.build._column_pair`
    gives — a schema column with no projection is a column the SELECT cannot
    produce — and the projections are keyed by relation because a merged
    entity's branches read different paths for it (RFC 0024 D36).
    """

    column: ColumnIR
    #: Source relation → that branch's projection. Read by relation, never
    #: iterated where the order could reach output (RFC 0003).
    projections: dict[str, SourceColumnIR]


def _shadow_column(derived: ColumnIR) -> ColumnIR:
    """The direct-path shadow's schema half: same declared type and catalog
    metadata as the derived column, since it is the same canonical field.

    One per entity column, never one per source — the schema of a merged
    entity is what every mapping agrees on (RFC 0024 D26), and this half is
    derived from the entity's own column alone.
    """

    return ColumnIR(
        name=f"{derived.name}__direct",
        type=derived.type,
        canonical=derived.canonical,
        unit=derived.unit,
        tax_basis=derived.tax_basis,
        renamed_from=None,
        required=False,
    )


# ....................... #


def _shadow_projection(derived: ColumnIR, direct: str) -> SourceColumnIR:
    """One branch's projection of the shadow: a declared-type cast of *that
    mapping's* direct extraction (RFC 0005 lowering rules).

    Per source, because ``direct:`` is per mapping (RFC 0024 D36). Under D28
    this was one projection for one entity and the combination was refused
    outright; the refusal named the right failure — a shadow NULL for one
    branch's rows is indistinguishable from a genuinely NULL direct value —
    but reached it from `Derivation` carrying no source rather than from
    anything about NULLs. With the source carried, disagreement is refused in
    `resolve.build` and agreement fans out here like every other lowering.

    This is the **second** place a lowering is built — the first is
    ``resolve.build._column_pair`` — because the shadow is an amendment the
    guardrail stage adds after the builder has run.
    """

    return SourceColumnIR(
        name=f"{derived.name}__direct",
        expr=canon(exp.cast(extraction(direct), neutral_type(derived.type))),
    )


# ....................... #


def _fill(shadow: Shadow, relations: tuple[str, ...]) -> None:
    """A typed ``NULL`` projection for every branch that recorded no path.

    Only a branch that does not produce the column at all reaches this: D36's
    refusal has already stopped a mapping that produces it and stays silent.
    The spelling is ``resolve.build._filled``'s, and cast for its reason — an
    untyped null makes the union's column type depend on which branch the
    engine reads first, which is the whole thing a fixed branch order buys.
    """
    for relation in relations:
        if relation in shadow.projections:
            continue
        shadow.projections[relation] = SourceColumnIR(
            name=shadow.column.name,
            expr=canon(exp.cast(exp.null(), neutral_type(shadow.column.type))),
        )


# ....................... #


def path_conflict_amendments(
    derivations: tuple[Derivation, ...], draft: ProjectIR
) -> tuple[dict[str, list[Shadow]], dict[str, list[AuditIR]]]:
    """Per-entity shadow columns and reconcile audits for every derivation
    that also records a ``direct:`` path.

    Grouped by ``(entity, field)`` rather than taken one derivation at a time,
    because a merged entity has one derivation **per mapping** for the same
    field (RFC 0024 D36). What that grouping decides is the arity of each half:
    one schema column and one reconcile audit for the field, and one projection
    for each source that recorded a path. Appending per derivation instead
    would emit the audit once per branch and hand the entity N columns of one
    name — two writers at one path, which is what D8 refuses for relations and
    what an entity's own schema has no way to express.

    Every mapping that produces the column records a ``direct:`` or none does;
    ``resolve.build`` has refused the entity otherwise (D36). A mapping that
    does not produce the column at all is outside that refusal — §5.2 rule 3
    lets a source omit an optional field — so its branch gets a typed NULL
    projection, exactly as the builder's ``_filled`` gives it one for the
    derived column itself. The shadow is then NULL on that branch beside a
    derived value that is also NULL, and ``IS DISTINCT FROM`` reports no
    disagreement, which is the true statement about those rows.
    """
    entities: dict[str, EntityIR] = {entity.name: entity for entity in draft.entities}
    shadows: dict[str, list[Shadow]] = {}
    audits: dict[str, list[AuditIR]] = {}
    built: dict[tuple[str, str], Shadow] = {}

    for derivation in derivations:
        if derivation.direct is None:
            continue
        entity = entities[derivation.entity]
        derived = guaranteed(
            (column for column in entity.columns if column.name == derivation.field),
            expected=f"the derived column {derivation.field!r} on entity {entity.name!r}",
            by="resolution, which builds the column it derives",
        )
        key = (derivation.entity, derivation.field)
        shadow = built.get(key)

        if shadow is None:
            shadow = Shadow(column=_shadow_column(derived), projections={})
            built[key] = shadow
            shadows.setdefault(derivation.entity, []).append(shadow)
            audits.setdefault(derivation.entity, []).append(
                AuditIR(
                    kind="reconcile",
                    column=derivation.field,
                    params=(("shadow", f"{derivation.field}__direct"),),
                )
            )

        shadow.projections[derivation.source] = _shadow_projection(derived, derivation.direct)

    for entity_name, entity_shadows in shadows.items():
        relations = tuple(source.relation for source in entities[entity_name].sources)
        for shadow in entity_shadows:
            _fill(shadow, relations)

    return shadows, audits
