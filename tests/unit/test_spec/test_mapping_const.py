"""A field mapping may set a constant (#375, S-0019/D-16).

Two marketplaces map onto one merged entity, and reports split rows by
marketplace, a value fixed per mapping. A field mapping had to read a path, so
the workaround read one that is always present and mapped every value to the
constant: a trick that breaks on a NULL and makes lineage name a column the
field never reads.

`{const: Wildberries}` is a literal, typed against the field's declaration,
that reads no path.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from support.compiling import FIXTURES, fixture_sources

from bloomery import Direction, build_project_ir, lineage, load_catalog, load_project, resolve
from bloomery.errors import SpecParseError, TypeCheckError
from bloomery.ir import EntityIR
from bloomery.resolve.graph import entity_field_node

pytestmark = pytest.mark.unit

FIXTURE = "multi_source"


def _sources(
    *, platform: str = "Shopify", legacy: str | None = "WooCommerce", declared: str = "string"
) -> dict[str, str]:
    """`multi_source` with a `channel` field each shop sets to its own name."""
    sources = fixture_sources(FIXTURE)

    def swap(key: str, old: str, new: str) -> None:
        assert sources[key].count(old) == 1, (key, old)
        sources[key] = sources[key].replace(old, new)

    swap("entity_model", "      gift_note: {type: string}\n", f"      gift_note: {{type: string}}\n      channel: {{type: {declared}}}\n")
    swap("mapping_platform", "fields:\n", f"fields:\n  channel: {{const: {platform}}}\n")
    if legacy is not None:
        swap("mapping_legacy", "fields:\n", f"fields:\n  channel: {{const: {legacy}}}\n")
    return sources


def _entity(sources: dict[str, str]) -> EntityIR:
    (entity,) = build_project_ir(load_project(sources)).entities
    return entity


# ....................... #
# The IR


def test_each_mapping_sets_its_own_constant_and_reads_no_path() -> None:
    entity = _entity(_sources())

    by_source = {source.relation: source for source in entity.sources}
    exprs = {
        relation: next(column.expr.sql for column in source.columns if column.name == "channel")
        for relation, source in by_source.items()
    }
    assert exprs == {
        "shopify__order_lines": "CAST('Shopify' AS TEXT)",
        "woo__order_lines": "CAST('WooCommerce' AS TEXT)",
    }
    assert not any(
        field.target_field == "channel" for source in entity.sources for field in source.fields
    )


def test_one_mapping_alone_has_the_column() -> None:
    """The issue's second point: `_source` exists only once two mappings feed
    an entity, and a constant does not depend on that."""
    sources = _sources(legacy=None)
    del sources["mapping_legacy"]
    entity = _entity(sources)

    assert "channel" in {column.name for column in entity.columns}


@pytest.mark.parametrize(
    ("declared", "value", "sql"),
    [
        ("int", "7", "CAST(7 AS BIGINT)"),
        ('"decimal(5,2)"', '"12.50"', "CAST('12.50' AS DECIMAL(5, 2))"),
        ("bool", "true", "CAST(TRUE AS BOOLEAN)"),
        ("date", "2026-01-01", "CAST('2026-01-01' AS DATE)"),
        # Without the ISO `T`, which Trino refuses to cast, and in UTC, which is
        # what a timestamp is (codeant on #377).
        ("timestamp", '"2026-01-01T10:00:00+03:00"', "CAST('2026-01-01 07:00:00' AS TIMESTAMP)"),
        ("timestamp", "2026-01-01T10:00:00", "CAST('2026-01-01 10:00:00' AS TIMESTAMP)"),
    ],
)
def test_a_constant_is_typed_against_the_field(declared: str, value: str, sql: str) -> None:
    entity = _entity(_sources(platform=value, legacy=value, declared=declared))

    (source, _) = entity.sources
    assert next(column.expr.sql for column in source.columns if column.name == "channel") == sql


@pytest.mark.parametrize(
    ("declared", "value"),
    [
        ("int", "Wildberries"),
        ("int", "true"),
        ('"decimal(3,2)"', '"123.45"'),
        ("date", "Wildberries"),
        ("bool", "1"),
        # A BIGINT holds a signed 64-bit integer (codeant on #377).
        ("int", str(2**63)),
        ("int", str(-(2**63) - 1)),
    ],
)
def test_a_constant_that_does_not_fit_the_field_is_refused(declared: str, value: str) -> None:
    with pytest.raises(TypeCheckError) as refused:
        build_project_ir(load_project(_sources(platform=value, legacy=None, declared=declared)))

    leaves = refused.value.collected or (refused.value,)
    (leaf,) = (one for one in leaves if "channel" in (one.source_path or ""))
    assert leaf.source_path == "mapping[shopify__order_lines->order_line]: fields.channel"
    assert "const" in str(leaf)


@pytest.mark.parametrize("value", ["1.5", '"{{ var }}"', "null"])
def test_a_float_a_brace_and_a_null_are_refused_at_parse(value: str) -> None:
    """A float has no exact reading (S-0020/D-5), a brace would reach dbt's
    Jinja inside the model, and a NULL constant is a column that is always
    missing."""
    with pytest.raises(SpecParseError):
        load_project(_sources(platform=value, legacy=None))


@pytest.mark.parametrize(
    "extra", ["transform: [to_string]", "quality: [{rule: not_null, on_fail: fail}]"]
)
def test_a_constant_takes_no_transform_and_no_quality(extra: str) -> None:
    sources = _sources(legacy=None)
    sources["mapping_platform"] = sources["mapping_platform"].replace(
        "  channel: {const: Shopify}\n", f"  channel: {{const: Shopify, {extra}}}\n"
    )
    with pytest.raises(SpecParseError):
        load_project(sources)


def test_the_schema_advertises_what_parsing_accepts() -> None:
    """An editor validating against the JSON schema accepts what the loader
    does: no number but an integer, no string carrying a brace or a NUL."""
    schema = json.loads(Path("tests/golden/schema/mapping.json").read_text(encoding="utf-8"))
    branches = schema["$defs"]["ConstFieldMapping"]["properties"]["const"]["anyOf"]

    assert {"type": "number"} not in branches
    (text,) = (b for b in branches if b.get("type") == "string" and "format" not in b)
    pattern = re.compile(text["pattern"])
    assert pattern.search("Wildberries")
    assert not pattern.search("{{ var }}")
    assert not pattern.search("a\x00b")


# ....................... #
# Lineage and quality


def test_lineage_names_no_source_column_for_it() -> None:
    graph = resolve(load_project(_sources())).graph
    node = entity_field_node("order_line", "channel")

    assert node in graph.nodes
    assert lineage(graph, node, Direction.UPSTREAM).edges == ()


def test_a_constant_gets_no_implicit_coercible_rule() -> None:
    """Nothing is cast from bronze, so no cast can fail. The rule's marker
    reads "NULL although every source was not", which over no source is
    vacuous."""
    sources = _sources()
    sources["entity_model"] = sources["entity_model"].replace(
        "    key: [order_id, line_no]\n",
        "    key: [order_id, line_no]\n    quarantine: {retention: 30d}\n",
        1,
    )
    for key in ("mapping_platform", "mapping_legacy"):
        sources[key] += "unmapped: ['$._ingested_at', '$._load_id', '$._source_row_id']\n"
    entity = _entity(sources)

    assert "channel" not in {rule.column for rule in entity.quality if rule.kind == "coercible"}
    assert "sku" in {rule.column for rule in entity.quality if rule.kind == "coercible"}


# ....................... #
# Review round 2 (CodeRabbit on #377)


@pytest.mark.parametrize("value", ["2026-01-01", "2026-01-01 10:00:00"])
def test_an_unquoted_date_is_not_text(value: str) -> None:
    """YAML reads it as a date, and its text does not survive the round trip:
    `2026-01-01 10:00:00` comes back with a `T`. A string field takes it
    quoted, as the text it is."""
    with pytest.raises(TypeCheckError, match="quote it"):
        build_project_ir(load_project(_sources(platform=value, legacy=None)))

    entity = _entity(_sources(platform=f'"{value}"', legacy=None))
    (source, _) = entity.sources
    assert next(c.expr.sql for c in source.columns if c.name == "channel") == (
        f"CAST('{value}' AS TEXT)"
    )


def test_a_string_constant_keeps_its_whitespace() -> None:
    """Spec strings are stripped, which is right for names and wrong for a
    value: the column must hold what was written."""
    entity = _entity(_sources(platform='" VIP "', legacy=None))
    (source, _) = entity.sources

    assert next(c.expr.sql for c in source.columns if c.name == "channel") == "CAST(' VIP ' AS TEXT)"


def test_a_constant_can_be_a_conversion_s_currency_column() -> None:
    """A feed whose every row is in one currency, named by a sibling column
    that is a constant: the conversion reads the literal."""
    sources = fixture_sources("currency_convert_per_row")
    old = '  currency_code: {from: "$.currency", transform: [to_string]}\n'
    assert sources["mapping"].count(old) == 1
    sources["mapping"] = sources["mapping"].replace(old, "  currency_code: {const: EUR}\n")
    catalog = load_catalog(
        (FIXTURES / "currency_convert_per_row" / "catalog.yaml").read_text(encoding="utf-8")
    )
    (entity,) = build_project_ir(load_project(sources), catalog).entities
    (source,) = entity.sources

    converted = next(c.expr.sql for c in source.columns if c.name == "amount_usd")
    assert "CAST('EUR' AS TEXT)" in converted
