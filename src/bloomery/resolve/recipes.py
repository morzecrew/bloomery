"""Recorded-recipe validation (S-0022/recipe-validation-bloomery-resolve-recipes-py, S-0022/D-2): the compiler validates —
and NEVER chooses — the recipe id a mapping records.

For each recipe-form field mapping, in order: the target entity field must
carry a ``canonical:`` link (a recipe without a catalog link is meaningless);
the recorded id must exist among that canonical field's recipes; and every
name in the recipe's ``requires`` must be bound by the mapping's ``from``
aliases — *exactly*: unbound requires and surplus aliases are both errors (a
surplus alias would be a silent no-op, the failure mode this package exists
to reject). A stale recorded choice is a loud error the upstream chooser must
re-decide, never a decision the compiler quietly remakes.

Runs on reference-clean specs (S-0022/cross-spec-reference-validation-bloomery-resolve-refs-py); failures are batched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sqlglot import exp, parse_one
from sqlglot.expressions.core import Expression

from bloomery.errors import BloomeryError, ResolutionError, UntypedRecipeOperand
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


#: The operators S-0091/D-3 refuses an untyped operand under: ``+``, ``-``
#: (binary and unary), ``*`` and ``/``. Modulo and the bitwise forms are
#: deliberately absent, so the refusal is exactly as wide as the defect it closes.
_ARITHMETIC = (exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Neg)

#: What a name can sit inside without being a value the arithmetic around it
#: reads: a comparison, a boolean connective, a negation.
_CONDITIONS = (exp.Predicate, exp.Connector, exp.Not)


def _in_condition(column: exp.Expr, operator: exp.Expr) -> bool:
    """Whether *column* reaches *operator* only through a test: inside a
    condition, or as the selector of a simple ``CASE x WHEN …`` or the test of
    a ``WHEN`` branch (the ``this`` of an ``exp.Case`` or an ``exp.If``)."""

    node: exp.Expr = column

    while node is not operator and node.parent is not None:
        parent = node.parent

        if isinstance(parent, _CONDITIONS):
            return True

        if isinstance(parent, (exp.Case, exp.If)) and node.arg_key == "this":
            return True

        node = parent

    return node is not operator


def _arithmetic_operands(expr: str) -> set[str]:
    """The bare column names an expression applies arithmetic to.

    A name an operator *reaches* as a value, at any depth: ``a / (b + c)``
    applies ``/`` to ``a`` and ``+`` to ``b`` and ``c``, and ``-a`` negates
    ``a``. A name read only as a test — ``raw_status`` in ``amount * CASE WHEN
    raw_status = 'x' THEN f ELSE 0 END`` or in ``CASE raw_status WHEN 'x' THEN
    f END * amount`` — is not, and neither is a name outside every arithmetic
    node; both are left to S-0091/D-2 alone.
    """

    parsed = cast("Expression", parse_one(expr))

    return {
        column.name
        for operator in parsed.find_all(*_ARITHMETIC)
        for column in operator.find_all(exp.Column)
        if not column.table and not _in_condition(column, operator)
    }


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
    of the S-0022/recipe-validation-bloomery-resolve-recipes-py failures.
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

    if recipe.expr is not None:
        # S-0091/D-3: an operand the recipe neither types nor shares a name with a
        # canonical field reaches the engine untyped, and arithmetic on a text
        # extraction is a model PostgreSQL and BigQuery refuse before it reads a
        # row. Refused here, where the fix is one `types:` line, rather than at run
        # time on an engine that cannot say which operand it choked on.
        operands = _arithmetic_operands(recipe.expr)
        unbound = sorted(operands - required)

        if unbound:
            # Not an alias slot at all: the name is read off the source relation
            # as it lands, and `types:` cannot name it, since D-1 holds its keys
            # to `requires`.
            msg = (
                f"recipe {recipe.id!r} applies +, -, * or / to {unbound}, which its "
                "requires: does not name, so the operand would be read off the source "
                "untyped. Fix: add it to the recipe's requires: and the mapping's from:, "
                "with a types: entry unless the catalog declares it canonically"
            )
            raise UntypedRecipeOperand(msg, source_path=f"{path}.recipe")

        untyped = sorted(
            name
            for name in operands
            if name not in recipe.types and name not in catalog.canonical_fields
        )

        if untyped:
            entries = ", ".join(f"{name!r}: '<type>'" for name in untyped)
            msg = (
                f"recipe {recipe.id!r} applies +, -, * or / to {untyped}, which the "
                "recipe's types: does not name and the catalog does not declare "
                f"canonically, so the operand would reach the engine untyped. Fix: add "
                f"{entries} to recipe {recipe.id!r}'s types:"
            )
            raise UntypedRecipeOperand(msg, source_path=f"{path}.recipe")

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
