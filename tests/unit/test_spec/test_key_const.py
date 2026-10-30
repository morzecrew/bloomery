"""A key part may be a constant (#380, S-0019/D-17).

Marketplace entities are keyed by the marketplace and the source's own id, so
two marketplaces feeding one merged entity never collide even where their ids
overlap. The marketplace is a value fixed per mapping, and a key part had to
read a path, so the workaround kept in the key was the one a constant field
retired: read a path that is always present and map every value to the
constant.

`{const: Ozon}` under `key:` is the field mapping's constant: typed against the
key column's declaration, lowered to a cast of the literal, reading no path. A
key every part of which is a constant gives every row of the mapping one key,
so at least one part must read a path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from support.compiling import fixture_sources

from bloomery import (
    Direction,
    Target,
    build_project_ir,
    compile_project,
    lineage,
    load_project,
    resolve,
)
from bloomery.errors import ResolutionError, SpecParseError, TypeCheckError
from bloomery.ir import EntityIR
from bloomery.resolve.graph import entity_field_node

pytestmark = pytest.mark.unit

FIXTURE = "multi_source"


def _swap(sources: dict[str, str], key: str, old: str, new: str) -> None:
    assert sources[key].count(old) == 1, (key, old)
    sources[key] = sources[key].replace(old, new)


def _sources(
    *, platform: str = "Shopify", legacy: str = "WooCommerce", declared: str = "string"
) -> dict[str, str]:
    """`multi_source` keyed by the shop too, each mapping setting its own."""
    sources = fixture_sources(FIXTURE)
    _swap(
        sources,
        "entity_model",
        "    key: [order_id, line_no]\n",
        "    key: [marketplace, order_id, line_no]\n",
    )
    _swap(
        sources,
        "entity_model",
        "      order_id: {type: string, required: true}\n",
        f"      marketplace: {{type: {declared}, required: true}}\n"
        "      order_id: {type: string, required: true}\n",
    )
    _swap(sources, "mapping_platform", "key:\n", f"key:\n  marketplace: {{const: {platform}}}\n")
    _swap(sources, "mapping_legacy", "key:\n", f"key:\n  marketplace: {{const: {legacy}}}\n")
    return sources


def _entity(sources: dict[str, str]) -> EntityIR:
    (entity,) = build_project_ir(load_project(sources)).entities
    return entity


def _key_sql(entity: EntityIR, relation: str) -> str:
    (source,) = (one for one in entity.sources if one.relation == relation)
    return next(column.expr.sql for column in source.columns if column.name == "marketplace")


# ....................... #
# The IR


def test_each_mapping_sets_its_own_key_part_and_reads_no_path() -> None:
    entity = _entity(_sources())

    assert "marketplace" in entity.key
    assert _key_sql(entity, "shopify__order_lines") == "CAST('Shopify' AS TEXT)"
    assert _key_sql(entity, "woo__order_lines") == "CAST('WooCommerce' AS TEXT)"
    assert not any(
        field.target_field == "marketplace" for source in entity.sources for field in source.fields
    )


def test_a_key_part_is_typed_against_its_field() -> None:
    entity = _entity(_sources(platform="7", legacy="8", declared="int"))

    assert _key_sql(entity, "shopify__order_lines") == "CAST(7 AS BIGINT)"


def test_a_key_part_that_does_not_fit_its_field_is_refused() -> None:
    with pytest.raises(TypeCheckError) as refused:
        build_project_ir(load_project(_sources(platform="Ozon", legacy="9", declared="int")))

    leaves = refused.value.collected or (refused.value,)
    (leaf,) = (one for one in leaves if "marketplace" in (one.source_path or ""))
    assert leaf.source_path == "mapping[shopify__order_lines->order_line]: key.marketplace"
    assert "const 'Ozon'" in str(leaf)


def _refused(sources: dict[str, str]) -> list[tuple[str | None, str]]:
    with pytest.raises(ResolutionError) as refused:
        build_project_ir(load_project(sources))

    return [(leaf.source_path, str(leaf)) for leaf in refused.value.collected or (refused.value,)]


def test_a_key_of_constants_alone_is_refused() -> None:
    """Every row of the mapping would carry one key, so dedupe or the merge
    would fold the source into a single row."""
    sources = _sources()
    _swap(
        sources,
        "mapping_platform",
        '  order_id: {from: "$.order.id", transform: [to_string]}\n'
        '  line_no: {from: "$.position", transform: [to_int]}\n',
        "  order_id: {const: S1}\n  line_no: {const: 1}\n",
    )

    ((source_path, message),) = _refused(sources)
    assert source_path == "mapping[shopify__order_lines->order_line]: key"
    assert "at least one of them must read a path" in message


def test_a_path_read_under_key_for_a_non_key_field_keys_nothing() -> None:
    """`key:` may lower a declared non-key field too. Keyed by the shop alone,
    each mapping's `order_id` is read but keys no row, and its shop is still
    the one key all of its rows carry."""
    sources = _sources()
    _swap(sources, "entity_model", "    key: [marketplace, order_id, line_no]\n", "    key: [marketplace]\n")

    assert sorted(source_path for source_path, _message in _refused(sources)) == [
        "mapping[shopify__order_lines->order_line]: key",
        "mapping[woo__order_lines->order_line]: key",
    ]


@pytest.mark.parametrize(
    ("column", "document", "old", "new"),
    [
        (
            "marketplace",
            "mapping_platform",
            "  marketplace: {const: Shopify}\n",
            '  marketplace: {from: "$.shop"}\n',
        ),
        (
            "sku",
            "mapping_legacy",
            '  sku: {from: "$.product_sku", transform: [to_string]}\n',
            "  sku: {const: GHI}\n",
        ),
    ],
    ids=["key", "field"],
)
def test_a_column_one_source_reads_and_another_sets_keeps_its_rule(
    column: str, document: str, old: str, new: str
) -> None:
    """Shopify reads the column and Woo sets it. Shopify's implicit
    `coercible` is no disagreement: Woo's constant has no rule to agree with,
    and the rule is inert on Woo's branch, which reads no sources for it."""
    sources = _sources()
    _swap(
        sources,
        "entity_model",
        "    key: [marketplace, order_id, line_no]\n",
        "    key: [marketplace, order_id, line_no]\n    quarantine: {retention: 30d}\n",
    )
    for key in ("mapping_platform", "mapping_legacy"):
        sources[key] += "unmapped: ['$._ingested_at', '$._load_id', '$._source_row_id']\n"
    _swap(sources, document, old, new)
    entity = _entity(sources)
    (woo,) = (one for one in entity.sources if one.relation == "woo__order_lines")
    (set_by_woo,) = (one for one in woo.columns if one.name == column)

    assert f"{column}_coercible" in {rule.name for rule in entity.quality}
    assert set_by_woo.sources == ()


def test_a_constant_key_part_takes_no_transform() -> None:
    sources = _sources()
    _swap(
        sources,
        "mapping_platform",
        "  marketplace: {const: Shopify}\n",
        "  marketplace: {const: Shopify, transform: [to_string]}\n",
    )

    with pytest.raises(SpecParseError):
        load_project(sources)


def test_the_schema_advertises_a_constant_key_part() -> None:
    schema = json.loads(Path("tests/golden/schema/mapping.json").read_text(encoding="utf-8"))
    part = schema["properties"]["key"]["additionalProperties"]
    refs = {branch["$ref"] for branch in part["oneOf"]}

    assert refs == {"#/$defs/KeyField", "#/$defs/ConstFieldMapping"}


@pytest.mark.parametrize("target", list(Target))
def test_every_target_compiles_it(target: Target) -> None:
    compile_project(load_project(_sources()), target=target, dialect="duckdb")


# ....................... #
# Lineage and quality


def test_lineage_names_no_source_column_for_it() -> None:
    graph = resolve(load_project(_sources())).graph
    node = entity_field_node("order_line", "marketplace")

    assert node in graph.nodes
    assert lineage(graph, node, Direction.UPSTREAM).edges == ()


def test_a_constant_key_part_gets_no_implicit_coercible_rule() -> None:
    """Nothing is cast from bronze, so no cast can fail; the key part that
    reads a path keeps its rule."""
    sources = _sources()
    _swap(
        sources,
        "entity_model",
        "    key: [marketplace, order_id, line_no]\n",
        "    key: [marketplace, order_id, line_no]\n    quarantine: {retention: 30d}\n",
    )
    for key in ("mapping_platform", "mapping_legacy"):
        sources[key] += "unmapped: ['$._ingested_at', '$._load_id', '$._source_row_id']\n"
    coercible = {rule.column for rule in _entity(sources).quality if rule.kind == "coercible"}

    assert "marketplace" not in coercible
    assert "order_id" in coercible
