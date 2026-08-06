"""Shared spec plumbing (RFC 0002 §5.3, §5.6): source-path conversion and the
strict duplicate-key-rejecting YAML loader."""

from __future__ import annotations

import pytest

from bloomery.errors import SpecParseError
from bloomery.spec.common import load_yaml_mapping, source_path_from_loc

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("loc", "expected"),
    [
        ((), "doc"),
        (("fields",), "doc: fields"),
        (("fields", "unit_price", "from"), "doc: fields.unit_price.from"),
        (("fields", "unit_price", "transform", 1), "doc: fields.unit_price.transform[1]"),
        (("entities", "e", "key", 0), "doc: entities.e.key[0]"),
        (("fields", "metric_time", "[key]"), "doc: fields.metric_time"),
        ((0, "x"), "doc: [0].x"),
    ],
)
def test_source_path_from_loc(loc: tuple[int | str, ...], expected: str) -> None:
    assert source_path_from_loc("doc", loc) == expected


def test_load_yaml_mapping_happy() -> None:
    assert load_yaml_mapping("a: 1\nb: [x]\n", document="d") == {"a": 1, "b": ["x"]}


def test_duplicate_key_rejected() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        load_yaml_mapping("a: 1\na: 2\n", document="mappings/orders")
    assert excinfo.value.source_path == "mappings/orders"
    assert "duplicate key 'a'" in str(excinfo.value)


def test_nested_duplicate_key_rejected() -> None:
    with pytest.raises(SpecParseError):
        load_yaml_mapping("outer:\n  a: 1\n  a: 2\n", document="d")


def test_invalid_yaml_rejected() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        load_yaml_mapping("a: [unclosed\n", document="d")
    assert excinfo.value.source_path == "d"
    assert "invalid YAML" in str(excinfo.value)


def test_non_mapping_root_rejected() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        load_yaml_mapping("- just\n- a list\n", document="d")
    assert "must be a YAML mapping" in str(excinfo.value)


def test_non_string_keys_rejected() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        load_yaml_mapping("1: x\n", document="d")
    assert "keys must be strings" in str(excinfo.value)


def test_unhashable_yaml_keys_rejected() -> None:
    # a sequence-valued key cannot be duplicate-checked; SafeLoader itself
    # rejects it as unhashable, surfaced as a SpecParseError
    with pytest.raises(SpecParseError) as excinfo:
        load_yaml_mapping("? [1, 2]\n: x\n", document="d")
    assert "invalid YAML" in str(excinfo.value)


def test_unsafe_tags_rejected() -> None:
    with pytest.raises(SpecParseError):
        load_yaml_mapping("a: !!python/object/apply:os.system [echo hi]\n", document="d")
