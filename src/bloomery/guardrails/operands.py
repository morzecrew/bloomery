"""Operand resolution shared by the guardrail checks (RFC 0006 §5.1–§5.2).

Two views of the same question — *what does this expression combine?*:

- :func:`collect_derivations` enumerates every recorded recipe derivation
  (RFC 0005 D2) with its expression, operand names, and source path — the
  derivation-level walk surface for the arithmetic and grain guards.
- :func:`operand_meta` resolves one operand name to its catalog metadata.
  Metadata originates **only** on catalog canonical fields (RFC 0006 D3): a
  mapping-local alias that names no canonical field carries none, and absent
  values are the ``unknown`` the guards poison on.

Runs on resolution-clean specs (RFC 0005 §5.5): every recorded recipe id is
known to exist by the time this module looks it up; the ``None`` guards below
only serve direct (test) callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bloomery.errors import guaranteed
from bloomery.quality import opts_in
from bloomery.spec.mapping import RecipeFieldMapping, mapping_doc

if TYPE_CHECKING:
    from bloomery.spec.catalog import Catalog
    from bloomery.spec.project import Project

# ----------------------- #

__all__ = [
    "Derivation",
    "OperandMeta",
    "collect_derivations",
    "operand_meta",
]


@dataclass(frozen=True, slots=True)
class OperandMeta:
    """Catalog metadata of one expression operand (RFC 0006 §5.2). ``None``
    values are the ``unknown`` state — never inferred, only declared."""

    name: str
    entity: str
    unit: str | None
    tax_basis: str | None
    currency: str | None


# ....................... #


@dataclass(frozen=True, slots=True)
class Derivation:
    """One recorded recipe derivation, addressed for violation reporting:
    the target entity and field, the catalog recipe's expression and operand
    names (``requires``), and the optional ``direct:`` path whose presence is
    the path-conflict state (RFC 0006 §5.5).

    ``source`` is the bronze relation the mapping that recorded this reads.
    A derivation is a **per-mapping** fact about a shared entity node, so an
    entity built from several mappings has one of these per branch — the shape
    RFC 0024 D26 split for a column's expression and D32 for a rule's inputs.
    It reaches here so that ``direct:`` can fan out the same way (D36): the
    shadow a branch projects is the path *that branch's* own mapping named,
    and no other relation need have it.

    ``cleaned`` is :func:`~bloomery.quality.opts_in` for this entity and this
    mapping — whether the builder lowered its columns produce-or-raise or
    NULL-on-failure (RFC 0016 §5.2, D3). The shadow is the one lowering built
    *after* the builder has run, so it does not inherit that choice by being
    in the loop that makes it; carrying the answer here is what keeps the
    amendment from re-deciding it, or from getting it wrong by looking at the
    IR's shape instead.

    Neither has a default. A ``Derivation`` built without ``cleaned`` would
    claim produce-or-raise, which is the pre-fix bug spelled as a convenience
    — and the fact is never absent at the one site that builds these, so a
    default could only ever paper over a caller that had stopped supplying it.
    """

    source_path: str
    source: str
    entity: str
    field: str
    expr: str | None
    operands: tuple[str, ...]
    direct: str | None
    cleaned: bool


# ....................... #


def operand_meta(name: str, catalog: Catalog | None) -> OperandMeta | None:
    """Metadata for one operand name, or ``None`` when the name is not a
    canonical field — a mapping-local alias has no declared home entity, so
    the guards have nothing to check it against (RFC 0006 D3)."""

    if catalog is None:
        return None

    field = catalog.canonical_fields.get(name)

    if field is None:
        return None

    return OperandMeta(
        name=name,
        entity=field.entity,
        unit=field.unit,
        tax_basis=field.tax_basis,
        currency=field.currency,
    )


# ....................... #


def collect_derivations(project: Project, catalog: Catalog | None) -> tuple[Derivation, ...]:
    """Every recipe-form field mapping as a :class:`Derivation`.

    Deterministic order: mappings in their (sorted-document) project order,
    fields sorted by name within each mapping (RFC 0003 §5.5).
    """
    derivations: list[Derivation] = []

    for mapping in project.mappings:
        doc = mapping_doc(mapping)
        for field_name in sorted(mapping.fields):
            field_mapping = mapping.fields[field_name]
            if not isinstance(field_mapping, RecipeFieldMapping) or catalog is None:
                continue
            entity = project.entity_model.entities[mapping.target]
            canonical = entity.fields[field_name].canonical
            if canonical is None:
                continue
            recipes = catalog.canonical_fields[canonical].recipes
            recipe = guaranteed(
                (r for r in recipes if r.id == field_mapping.recipe),
                expected=f"recipe {field_mapping.recipe!r} on canonical field {canonical!r}",
                by="resolve_recipe, which refuses an unrecorded choice (RFC 0005 §5.2)",
            )
            derivations.append(
                Derivation(
                    source_path=f"{doc}: fields.{field_name}",
                    source=mapping.source,
                    cleaned=opts_in(entity, mapping),
                    entity=mapping.target,
                    field=field_name,
                    expr=recipe.expr,
                    operands=recipe.requires,
                    direct=field_mapping.direct,
                )
            )

    return tuple(derivations)
