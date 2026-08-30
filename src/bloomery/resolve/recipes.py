"""Recorded-recipe validation (RFC 0005 §5.2, D2): the compiler validates —
and NEVER chooses — the recipe id a mapping records.

For each recipe-form field mapping, in order: the target entity field must
carry a ``canonical:`` link (a recipe without a catalog link is meaningless);
the recorded id must exist among that canonical field's recipes; and every
name in the recipe's ``requires`` must be bound by the mapping's ``from``
aliases — *exactly*: unbound requires and surplus aliases are both errors (a
surplus alias would be a silent no-op, the failure mode this package exists
to reject). A stale recorded choice is a loud error the upstream chooser must
re-decide, never a decision the compiler quietly remakes.

Runs on reference-clean specs (RFC 0005 §5.5); failures are batched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bloomery.errors import BloomeryError, ResolutionError
from bloomery.resolve.refs import mapping_doc
from bloomery.spec.mapping import RecipeFieldMapping

if TYPE_CHECKING:
    from bloomery.spec.catalog import Catalog, Recipe
    from bloomery.spec.mapping import Mapping
    from bloomery.spec.project import Project

# ----------------------- #

__all__ = [
    "recipe_fields",
    "resolve_recipe",
    "validate_recipes",
]


def recipe_fields(mapping: Mapping) -> tuple[tuple[str, RecipeFieldMapping], ...]:
    """The mapping's recipe-form fields, sorted by field name."""

    return tuple(
        (name, field)
        for name, field in sorted(mapping.fields.items())
        if isinstance(field, RecipeFieldMapping)
    )


# ....................... #


def resolve_recipe(
    mapping: Mapping,
    field_name: str,
    field_mapping: RecipeFieldMapping,
    project: Project,
    catalog: Catalog | None,
) -> Recipe:
    """Validate one recorded recipe choice and return the catalog recipe.

    Raises :class:`ResolutionError` at the mapping field's source path on any
    of the RFC 0005 §5.2 failures.
    """
    path = f"{mapping_doc(mapping)}: fields.{field_name}"
    entity = project.entity_model.entities[mapping.target]
    canonical = entity.fields[field_name].canonical

    if canonical is None:
        msg = (
            f"field {field_name!r} records recipe {field_mapping.recipe!r} but carries no "
            "canonical: link — a recipe without a catalog link is meaningless"
        )
        raise ResolutionError(msg, source_path=f"{path}.recipe")

    if catalog is None:  # pragma: no cover — reference validation rejects this first
        msg = f"field {field_name!r} records a recipe but no catalog was provided"
        raise ResolutionError(msg, source_path=f"{path}.recipe")

    canonical_field = catalog.canonical_fields[canonical]
    recipes_by_id = {recipe.id: recipe for recipe in canonical_field.recipes}
    recipe = recipes_by_id.get(field_mapping.recipe)

    if recipe is None:
        known = sorted(recipes_by_id)
        msg = (
            f"recorded recipe {field_mapping.recipe!r} does not exist on canonical field "
            f"{canonical!r}; known recipes: {known}. The compiler never re-chooses — "
            "the upstream chooser must re-decide"
        )
        raise ResolutionError(msg, source_path=f"{path}.recipe")

    required = set(recipe.requires)
    bound = set(field_mapping.from_)
    unbound = sorted(required - bound)

    if unbound:
        msg = (
            f"recipe {recipe.id!r} requires {unbound} but the mapping's from: aliases "
            "do not bind them"
        )
        raise ResolutionError(msg, source_path=f"{path}.from")

    surplus = sorted(bound - required)

    if surplus:
        msg = (
            f"mapping binds aliases {surplus} that recipe {recipe.id!r} does not require "
            "— a surplus alias is a silent no-op"
        )
        raise ResolutionError(msg, source_path=f"{path}.from")

    if recipe.expr is None and len(recipe.requires) != 1:
        msg = (
            f"recipe {recipe.id!r} has no expr and requires {len(recipe.requires)} names; "
            "only single-requirement recipes may omit expr (identity)"
        )
        raise ResolutionError(msg, source_path=f"{path}.recipe")

    return recipe


# ....................... #


def validate_recipes(project: Project, catalog: Catalog | None) -> None:
    """Validate every recorded recipe across all mappings, batched (D7)."""
    errors: list[BloomeryError] = []

    for mapping in project.mappings:
        for field_name, field_mapping in recipe_fields(mapping):
            try:
                resolve_recipe(mapping, field_name, field_mapping, project, catalog)
            except ResolutionError as exc:
                errors.append(exc)

    if errors:
        if len(errors) == 1:
            raise errors[0]
        raise ResolutionError.from_collected(tuple(errors))
