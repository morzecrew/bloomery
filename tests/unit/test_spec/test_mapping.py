"""The Mapping spec kind (RFC 0002 §5.5; original spec §3.4): the simple/recipe
field-mapping union and TransformStep normalization."""

from __future__ import annotations

import pytest
import yaml

from bloomery.errors import SpecParseError
from bloomery.spec import Mapping, RecipeFieldMapping, SimpleFieldMapping, TransformStep
from bloomery.spec.common import RESERVED_MEMBER_NAMES, validate_document

pytestmark = pytest.mark.unit


def parse(text: str, document: str = "mappings/orders") -> Mapping:
    return validate_document(Mapping, yaml.safe_load(text), document=document)


HAPPY = """
mapping_version: 1
source: shopify__order_lines
target: order_item
key:
  order_id: {from: "$.order_id", transform: [to_string]}
  line_no: {from: "$.index", transform: [to_int]}
fields:
  unit_price:
    recipe: from_total
    from: {line_total: "$.total", quantity: "$.qty"}
  quantity: {from: "$.qty", transform: [to_int]}
  order_date:
    from: "$.created_at"
    transform: [{parse_ts: ISO8601}, {to_utc: Europe/Paris}]
unmapped: ["$.note", "$.gift_wrap"]
"""


def test_happy_parse() -> None:
    mapping = parse(HAPPY)
    assert mapping.source == "shopify__order_lines"
    assert mapping.key["order_id"].from_ == "$.order_id"
    assert mapping.key["order_id"].transform == (TransformStep(name="to_string"),)

    unit_price = mapping.fields["unit_price"]
    assert isinstance(unit_price, RecipeFieldMapping)
    assert unit_price.recipe == "from_total"
    assert unit_price.from_ == {"line_total": "$.total", "quantity": "$.qty"}

    order_date = mapping.fields["order_date"]
    assert isinstance(order_date, SimpleFieldMapping)
    assert order_date.transform == (
        TransformStep(name="parse_ts", args=("ISO8601",)),
        TransformStep(name="to_utc", args=("Europe/Paris",)),
    )
    assert mapping.unmapped == ("$.note", "$.gift_wrap")


def test_transform_step_list_args() -> None:
    mapping = parse(
        'mapping_version: 1\nsource: s\ntarget: t\n'
        'key:\n  k: {from: "$.k", transform: [{split_part: ["-", 1]}]}\nfields: {}\n'
    )
    assert mapping.key["k"].transform == (TransformStep(name="split_part", args=("-", 1)),)


def test_field_mapping_union_revalidates_model_instances() -> None:
    # the tag function must also discriminate already-constructed models
    original = parse(HAPPY)
    revalidated = Mapping.model_validate(
        {
            "mapping_version": original.mapping_version,
            "source": original.source,
            "target": original.target,
            "key": dict(original.key),
            "fields": dict(original.fields),
        }
    )
    assert revalidated.fields == original.fields


def test_bad_transform_step_shape_two_keys() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            'mapping_version: 1\nsource: s\ntarget: t\n'
            'key:\n  k: {from: "$.k", transform: [{a: 1, b: 2}]}\nfields: {}\n'
        )
    assert excinfo.value.source_path == "mappings/orders: key.k.transform[0]"
    assert "single-key mapping" in str(excinfo.value)


def test_bad_transform_step_shape_not_a_name() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            'mapping_version: 1\nsource: s\ntarget: t\n'
            'key:\n  k: {from: "$.k", transform: [17]}\nfields: {}\n'
        )
    assert excinfo.value.source_path == "mappings/orders: key.k.transform[0]"


def test_bad_jsonpath_grammar() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            "mapping_version: 1\nsource: s\ntarget: t\n"
            "key:\n  k: {from: order_id}\nfields: {}\n"
        )
    assert excinfo.value.source_path == "mappings/orders: key.k.from"


def test_recipe_mapping_records_an_optional_direct_path() -> None:
    # The path-conflict state (RFC 0006 D7): recipe + direct source column.
    mapping = parse(
        "mapping_version: 1\nsource: s\ntarget: t\nkey: {}\n"
        'fields:\n  f: {recipe: from_total, from: {a: "$.a"}, direct: "$.f"}\n'
    )
    field = mapping.fields["f"]
    assert isinstance(field, RecipeFieldMapping)
    assert field.direct == "$.f"


def test_recipe_mapping_direct_defaults_to_none() -> None:
    field = parse(HAPPY).fields["unit_price"]
    assert isinstance(field, RecipeFieldMapping)
    assert field.direct is None


def test_recipe_mapping_direct_must_be_a_jsonpath() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            "mapping_version: 1\nsource: s\ntarget: t\nkey: {}\n"
            'fields:\n  f: {recipe: from_total, from: {a: "$.a"}, direct: not_a_path}\n'
        )
    assert "fields.f.recipe.direct" in str(excinfo.value.source_path)


def test_recipe_mapping_requires_alias_paths() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            "mapping_version: 1\nsource: s\ntarget: t\nkey: {}\n"
            'fields:\n  f: {recipe: from_total, from: {alias: not_a_path}}\n'
        )
    assert "fields.f.recipe.from.alias" in str(excinfo.value.source_path)


def test_retired_on_unmapped_enum_is_an_unknown_key() -> None:
    # RFC 0016 §5.2 / D3 (an RFC 0002 amendment): the policy is retired, not
    # renamed — an unmapped enum value now fails the `in_enum` quality rule.
    # A spec still carrying it must be told, not silently accepted.
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            "mapping_version: 1\nsource: s\ntarget: t\nkey: {}\nfields: {}\n"
            "on_unmapped_enum: quarantine\n"
        )
    assert excinfo.value.source_path == "mappings/orders: on_unmapped_enum"
    assert "Extra inputs are not permitted" in str(excinfo.value)


def test_unknown_top_level_key() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse("mapping_version: 1\nsource: s\ntarget: t\nkey: {}\nfields: {}\nunmaped: []\n")
    assert excinfo.value.source_path == "mappings/orders: unmaped"


def test_reserved_metric_time_target_field() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            "mapping_version: 1\nsource: s\ntarget: t\nkey: {}\n"
            'fields:\n  metric_time: {from: "$.ts"}\n'
        )
    assert excinfo.value.source_path == "mappings/orders: fields.metric_time"


@pytest.mark.parametrize("name", RESERVED_MEMBER_NAMES)
def test_reserved_target_field_names(name: str) -> None:
    # a mapping cannot land a source path on a generated column either
    # (RFC 0016 §5.5, §5.6)
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            "mapping_version: 1\nsource: s\ntarget: t\nkey: {}\n"
            f'fields:\n  {name}: {{from: "$.x"}}\n'
        )
    assert excinfo.value.source_path == f"mappings/orders: fields.{name}"
