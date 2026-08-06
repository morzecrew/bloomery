"""Recorded-recipe validation (RFC 0005 §5.2, D2): the compiler validates,
never chooses — every failure branch, with exact alias-set enforcement."""

from __future__ import annotations

import pytest

from bloomery import load_catalog, load_project
from bloomery.errors import ResolutionError
from bloomery.resolve import resolve

pytestmark = pytest.mark.unit

ENTITY_MODEL = """\
spec_version: 1
entities:
  order_item:
    grain: one row per line
    key: [order_id]
    fields:
      order_id: {type: string, required: true}
      unit_price: {type: "decimal(12,4)", canonical: unit_price}
      note: {type: string}
"""

RECIPE_MAPPING = """\
mapping_version: 1
source: src__lines
target: order_item
key:
  order_id: {from: "$.id", transform: [to_string]}
fields:
  unit_price:
    recipe: from_total
    from: {line_total: "$.total", quantity: "$.qty"}
"""

CATALOG = """\
catalog_version: 1
vertical: test
canonical_fields:
  unit_price:
    entity: order_item
    type: decimal(12,4)
    recipes:
      - {id: direct, requires: [unit_price]}
      - {id: from_total, requires: [line_total, quantity], expr: "line_total / quantity"}
      - {id: broken_pair, requires: [alpha, beta]}
"""

DOC = "mapping[src__lines->order_item]"


def test_valid_recorded_recipe_resolves() -> None:
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": RECIPE_MAPPING})
    resolve(project, load_catalog(CATALOG))


def test_recipe_on_field_without_canonical_link() -> None:
    mapping = RECIPE_MAPPING.replace("  unit_price:", "  note:")
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": mapping})
    with pytest.raises(ResolutionError, match="carries no canonical: link") as excinfo:
        resolve(project, load_catalog(CATALOG))
    assert excinfo.value.source_path == f"{DOC}: fields.note.recipe"


def test_unknown_recipe_id_names_known_ids_and_never_rechooses() -> None:
    mapping = RECIPE_MAPPING.replace("recipe: from_total", "recipe: from_totals")
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": mapping})
    with pytest.raises(ResolutionError) as excinfo:
        resolve(project, load_catalog(CATALOG))
    message = str(excinfo.value)
    assert "'from_totals' does not exist" in message
    assert "['broken_pair', 'direct', 'from_total']" in message
    assert "never re-chooses" in message
    assert excinfo.value.source_path == f"{DOC}: fields.unit_price.recipe"


def test_unbound_requires_is_an_error() -> None:
    mapping = RECIPE_MAPPING.replace(', quantity: "$.qty"', "")
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": mapping})
    with pytest.raises(ResolutionError, match=r"requires \['quantity'\]") as excinfo:
        resolve(project, load_catalog(CATALOG))
    assert excinfo.value.source_path == f"{DOC}: fields.unit_price.from"


def test_surplus_alias_is_an_error_not_a_silent_noop() -> None:
    mapping = RECIPE_MAPPING.replace('"$.qty"}', '"$.qty", extra: "$.x"}')
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": mapping})
    with pytest.raises(ResolutionError, match=r"aliases \['extra'\].*silent no-op") as excinfo:
        resolve(project, load_catalog(CATALOG))
    assert excinfo.value.source_path == f"{DOC}: fields.unit_price.from"


def test_wrong_alias_set_reports_both_directions() -> None:
    mapping = RECIPE_MAPPING.replace("line_total:", "grand_total:")
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": mapping})
    with pytest.raises(ResolutionError, match=r"requires \['line_total'\]"):
        resolve(project, load_catalog(mapping and CATALOG))


def test_exprless_recipe_with_multiple_requires_is_invalid() -> None:
    mapping = RECIPE_MAPPING.replace("recipe: from_total", "recipe: broken_pair").replace(
        'from: {line_total: "$.total", quantity: "$.qty"}',
        'from: {alpha: "$.a", beta: "$.b"}',
    )
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": mapping})
    with pytest.raises(ResolutionError, match="has no expr and requires 2 names"):
        resolve(project, load_catalog(CATALOG))


def test_exprless_single_require_recipe_is_identity() -> None:
    mapping = RECIPE_MAPPING.replace("recipe: from_total", "recipe: direct").replace(
        'from: {line_total: "$.total", quantity: "$.qty"}',
        'from: {unit_price: "$.price"}',
    )
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": mapping})
    resolve(project, load_catalog(CATALOG))


def test_recipe_failures_are_batched() -> None:
    model = ENTITY_MODEL.replace(
        "      note: {type: string}",
        '      note: {type: string}\n      discount: {type: "decimal(12,4)", canonical: unit_price}',
    )
    mapping = RECIPE_MAPPING.replace("recipe: from_total", "recipe: from_totals") + (
        "  discount:\n    recipe: nope\n    from: {x: \"$.x\"}\n"
    )
    project = load_project({"entity_model": model, "mapping": mapping})
    with pytest.raises(ResolutionError) as excinfo:
        resolve(project, load_catalog(CATALOG))
    assert len(excinfo.value.collected) == 2
