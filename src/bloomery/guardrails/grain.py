"""The grain guard — the fan-out refusal (S-0023/grain-the-fan-out-guard, S-0023/D-5).

All operands of a derivation must share the derivation's grain, or the
expression must contain an explicit aggregation over the foreign-grain
operand. An operand reached through a ``many_to_one`` relationship sits at a
coarser grain; joined down without aggregation it is duplicated once per
fine-grained row and every downstream ``SUM`` overstates it. There is no
"distribute evenly" auto-fix — allocation is a modelling decision the author
must write as an explicit expression.

The same rule runs over metric expressions whose ``requires`` span entities
with different grains. The mart-level leaves (``GrainViolation``,
``FanoutRisk`` — S-0023/D-10) run where marts are lowered, with M5
(S-0027); this module is the derivation/metric-level guard only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sqlglot import exp, parse_one
from sqlglot.expressions.core import Expression

from bloomery.errors import GrainMismatch, GuardrailError
from bloomery.guardrails.operands import operand_meta
from bloomery.ir import Cardinality

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bloomery.guardrails.operands import Derivation
    from bloomery.ir import ProjectIR
    from bloomery.spec.catalog import Catalog
    from bloomery.spec.project import Project

# ----------------------- #

__all__ = [
    "check_grain",
]

#: A relationship read against its declared direction inverts its cardinality.
_INVERSE: dict[Cardinality, Cardinality] = {
    Cardinality.MANY_TO_ONE: Cardinality.ONE_TO_MANY,
    Cardinality.ONE_TO_ONE: Cardinality.ONE_TO_ONE,
    Cardinality.ONE_TO_MANY: Cardinality.MANY_TO_ONE,
}


def _grains(project: Project, draft: ProjectIR) -> dict[str, str]:
    """Every entity a grain can be read off, imported ones included.

    The imported entities first and the authored model over them, so a local
    entity's grain is still read from the document that declares it. What the
    imports add is an entity a mart or a metric may now name across the
    boundary (S-0002/D-2): it sits at that entity's grain, and the fan-out
    rule applies unchanged — before this an imported grain read as "undeclared
    in this project", which is the message for a name resolving to nothing.
    """

    return {
        entity.name: entity.grain for upstream in draft.upstream for entity in upstream.entities
    } | {name: entity.grain for name, entity in project.entity_model.entities.items()}


# ....................... #


def _grain_of(grains: Mapping[str, str], entity_name: str) -> str:
    return grains.get(entity_name, "undeclared in this project")


# ....................... #


def _relationship_between(draft: ProjectIR, from_entity: str, to_entity: str) -> str:
    """How ``to_entity`` is reached from ``from_entity``, for the message."""

    for rel in draft.relationships:
        if rel.from_entity == from_entity and rel.to_entity == to_entity:
            return f"relationship {rel.name!r} ({rel.cardinality})"
        if rel.from_entity == to_entity and rel.to_entity == from_entity:
            return f"relationship {rel.name!r} ({_INVERSE[rel.cardinality]}, read inversely)"

    return "no declared relationship"


# ....................... #


def _fully_aggregated(tree: Expression, name: str) -> bool:
    """Every occurrence of ``name`` in the expression sits under an explicit
    aggregation — the sanctioned way to bring a foreign grain in (D5)."""
    occurrences = [col for col in tree.find_all(exp.Column) if col.name == name]
    return bool(occurrences) and all(
        col.find_ancestor(exp.AggFunc) is not None for col in occurrences
    )


# ....................... #


def _mismatch(
    *,
    operand: str,
    home: str,
    anchor: str,
    subject: str,
    reached: str,
    fix: str,
    grains: Mapping[str, str],
    source_path: str,
) -> GrainMismatch:
    msg = (
        f"{subject} combines {operand!r} from entity {home!r} (grain: "
        f"{_grain_of(grains, home)}) at the grain of entity {anchor!r} (grain: "
        f"{_grain_of(grains, anchor)}), reached via {reached} with no aggregation step. "
        f"Joined across grains, {operand!r} is duplicated once per {anchor!r} row and "
        f"any SUM over the result overstates it. Fix: {fix}"
    )
    return GrainMismatch(msg, source_path=source_path)


# ....................... #


def check_grain(
    derivations: tuple[Derivation, ...],
    draft: ProjectIR,
    project: Project,
    catalog: Catalog | None,
) -> list[GuardrailError]:
    """Every grain violation across derivations and metric expressions."""
    violations: list[GuardrailError] = []
    grains = _grains(project, draft)

    for derivation in derivations:
        tree = (
            cast("Expression", parse_one(derivation.expr)) if derivation.expr is not None else None
        )
        for operand in derivation.operands:
            meta = operand_meta(operand, catalog)
            if meta is None or meta.entity == derivation.entity:
                continue
            if tree is not None and _fully_aggregated(tree, operand):
                continue
            violations.append(
                _mismatch(
                    operand=operand,
                    home=meta.entity,
                    anchor=derivation.entity,
                    subject=f"derivation of {derivation.field!r}",
                    reached=_relationship_between(draft, derivation.entity, meta.entity),
                    fix=(
                        f"add an explicit aggregation/allocation over {derivation.entity!r}, "
                        f"or declare the derivation on entity {meta.entity!r}"
                    ),
                    grains=grains,
                    source_path=derivation.source_path,
                )
            )

    violations.extend(_check_metric_grain(draft, grains, catalog))

    return violations


# ....................... #


def _check_metric_grain(
    draft: ProjectIR, grains: Mapping[str, str], catalog: Catalog | None
) -> list[GuardrailError]:
    violations: list[GuardrailError] = []

    for metric in draft.metrics:
        if metric.expr is None:
            continue
        homes = {
            name: meta.entity
            for name in metric.depends_on
            if (meta := operand_meta(name, catalog)) is not None
        }
        distinct = sorted(set(homes.values()))
        if len(distinct) <= 1:
            continue
        source_path = f"metrics: metrics.{metric.name}"
        tree = metric.expr.ast()
        if metric.grain in grains:
            for name in sorted(homes):
                if homes[name] == metric.grain or _fully_aggregated(tree, name):
                    continue
                violations.append(
                    _mismatch(
                        operand=name,
                        home=homes[name],
                        anchor=metric.grain,
                        subject=f"metric {metric.name!r}",
                        reached=_relationship_between(draft, metric.grain, homes[name]),
                        fix=(
                            f"aggregate {name!r} explicitly inside expr, or split the "
                            f"metric per entity"
                        ),
                        grains=grains,
                        source_path=source_path,
                    )
                )
        else:
            spans = ", ".join(f"{e!r} ({_grain_of(grains, e)})" for e in distinct)
            msg = (
                f"metric requires span entities with different grains — {spans} — and "
                f"its grain ({metric.grain!r}) names none of them, so no shared grain "
                "exists for the expression. Fix: declare grain: as one of these entities "
                "and aggregate the others explicitly"
            )
            violations.append(GrainMismatch(msg, source_path=source_path))

    return violations
