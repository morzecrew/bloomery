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


# ....................... #
# The adversarial caps: refuse with the limit named, never exhaust a resource


def _nested(levels: int) -> str:
    return "a:" + "".join("\n" + " " * i + "k:" for i in range(1, levels)) + " 1"


def test_a_too_deep_document_is_refused_not_a_recursion_error() -> None:
    """Measured before the cap: ~1000 nesting levels escaped `yaml.load` as a
    raw RecursionError — the spec path takes files from other teams, and the
    filter parser already promises its half of this guarantee."""
    with pytest.raises(SpecParseError) as excinfo:
        load_yaml_mapping(_nested(1_000), document="d")
    assert excinfo.value.source_path == "d"
    assert "levels deep" in str(excinfo.value)


def test_a_deep_but_sane_document_still_loads() -> None:
    assert load_yaml_mapping(_nested(100), document="d")


def test_an_alias_bomb_is_refused_by_expansion_not_by_document_size() -> None:
    """The billion-laughs shape: a ~400-byte document whose aliases expand to
    10^8+ values for whoever walks the result. PyYAML itself loads it cheaply
    (aliases are shared nodes), so the cap is on the *expanded* count."""
    width = 10
    bomb = "\n".join(
        ["l0: &l0 [" + ", ".join(['"x"'] * width) + "]"]
        + [
            f"l{i}: &l{i} [" + ", ".join([f"*l{i - 1}"] * width) + "]"
            for i in range(1, 9)
        ]
    )
    with pytest.raises(SpecParseError) as excinfo:
        load_yaml_mapping(bomb, document="d")
    assert "aliases expand this document" in str(excinfo.value)


def test_ordinary_anchors_and_aliases_still_load() -> None:
    """The cap must not take the legitimate use down with the bomb: sharing a
    defaults block is what anchors are for."""
    loaded = load_yaml_mapping(
        "defaults: &d {a: 1, b: 2}\nuse1: *d\nuse2: *d\n", document="d"
    )
    assert loaded["use1"] == {"a": 1, "b": 2}
    assert loaded["use2"] == {"a": 1, "b": 2}


def test_an_oversized_document_is_refused_with_its_size_named() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        load_yaml_mapping("k: v\n" + "#" * 5_000_001, document="big")
    assert excinfo.value.source_path == "big"
    assert "5,000,000 limit" in str(excinfo.value)
    assert "split it" in str(excinfo.value)
