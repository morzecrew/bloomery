"""Shared spec plumbing (S-0019/source-paths, S-0019/yaml-parsing): source-path conversion and the
strict duplicate-key-rejecting YAML loader."""

from __future__ import annotations

import itertools

import pytest

from bloomery.errors import SpecParseError
from bloomery.spec.common import (
    SpecModel,
    load_yaml_mapping,
    source_path_from_loc,
    validate_document,
)

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


@pytest.mark.parametrize(
    ("text", "problem", "line"),
    [
        # The scheduled fuzz run's reproducer, byte for byte (#398).
        ('"\\U' + "9" * 79 + "fenumo", "past U+10FFFF", 1),
        ('a: "\\U00110000"\n', "past U+10FFFF", 1),
        ("a: 1\nb: 2026-13-01\n", "cannot read '2026-13-01' as a YAML timestamp", 2),
        ("a: [x, {b: 2026-02-30}]\n", "cannot read '2026-02-30' as a YAML timestamp", 1),
        ('a: !!int "0x"\n', "cannot read '0x' as a YAML int", 1),
        ('a: !!int ""\n', "cannot read '' as a YAML int", 1),
        ("a: !!bool maybe\n", "cannot read 'maybe' as a YAML bool", 1),
        ("a: 1\nb: !!timestamp x\n", "cannot read 'x' as a YAML timestamp", 2),
        ("a: !!set [x]\n", "expected a mapping node", 1),
        # A key is built at once, through its children: the child's refusal
        # is the one reported, not a second one wrapped around it.
        ('? [x, !!int ""]\n: y\n', "cannot read '' as a YAML int", 1),
    ],
)
def test_a_value_yaml_cannot_build_is_refused_at_its_line(
    text: str, problem: str, line: int
) -> None:
    """PyYAML hands a ``\\U`` escape to ``chr`` and a scalar to its type's
    builder unchecked, so ``ValueError`` (``OverflowError`` past a C int on
    Python 3.12), ``IndexError``, ``KeyError`` and ``AttributeError`` crossed
    ``load_project`` as themselves (#398). The builder's own words differ
    between Python versions, so only the refusal's are asserted."""
    with pytest.raises(SpecParseError) as excinfo:
        load_yaml_mapping(text, document="d")
    assert excinfo.value.source_path == "d"
    assert problem in str(excinfo.value)
    assert f"line {line}," in str(excinfo.value)


_TAGS = ("int", "float", "bool", "null", "timestamp", "binary", "str", "set", "omap", "pairs", "seq", "map")
_VALUES = ('""', '"-"', '"_"', '"0x"', '"1:x"', "maybe", '"2026-13-01"', "[1]", "[a]", "{a: 1}", "[{a: 1}, 2]")
_PLACES = ("k: {}\n", "k:\n  - x\n  - {}\n", "? {}\n: x\n", "k: !!set {{? {}}}\n", "<<: {}\nk: 1\n")


def test_no_tagged_value_crosses_the_loader_unrefused() -> None:
    """Every safe tag over text it cannot read, as a value, a list item, a key,
    a set member and a merge: each loads or is a `SpecParseError`, whatever the
    builder raised underneath."""
    escaped = []
    for place, tag, value in itertools.product(_PLACES, _TAGS, _VALUES):
        text = place.format(f"!!{tag} {value}")
        try:
            load_yaml_mapping(text, document="d")
        except SpecParseError:
            pass
        except Exception as exc:  # the finding this test exists to catch
            escaped.append(f"{text!r}: {type(exc).__name__}")
    assert escaped == []


def test_the_last_code_point_and_a_quoted_date_still_load() -> None:
    assert load_yaml_mapping('a: "\\U0010FFFF"\nb: "2026-13-01"\n', document="d") == {
        "a": "\U0010ffff",
        "b": "2026-13-01",
    }


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


@pytest.mark.parametrize(
    "text",
    [
        "a: &x\n  b: *x\n",  # the alias inside its own anchor
        "a: &x\n  b: *x\nc: *x\n",  # and named again after the anchor closes
        "a: &x [1, *x]\n",  # the sequence spelling
    ],
)
def test_a_recursive_alias_is_refused_not_constructed(text: str) -> None:
    """Measured before the fix: `a: &x {b: *x}` loaded and made
    `d["a"]["b"] is d["a"]` true — a cyclic value that hangs or crashes
    whoever walks it (pydantic validation, `json.dumps`). A per-alias check
    cannot see it, because inside its own anchor the alias resolves to a
    node whose children are not composed yet; the accounting therefore runs
    once on the finished graph, where the cycle is visible."""
    with pytest.raises(SpecParseError) as excinfo:
        load_yaml_mapping(text, document="d")
    assert "inside its own anchor" in str(excinfo.value)


def test_heavy_but_honest_alias_reuse_still_loads() -> None:
    """The expansion budget scales with the document's own written size, so
    thousands of references to a small shared block — the legitimate use at
    its heaviest — stay loadable while a bomb's ratio is astronomical."""
    document = "anchor: &a {x: 1, y: 2}\n" + "\n".join(f"k{i}: *a" for i in range(2_000))
    assert len(load_yaml_mapping(document, document="d")) == 2_001


# ....................... #


class _Refused(SpecModel):
    count: int


def test_a_refused_document_leaves_no_validation_error_alive() -> None:
    """Raised inside the `except`, every refusal held its `ValidationError` as
    context, so refusing specs by the thousand grew memory (S-0088/D-1).
    Asserted on the refusal's own chain rather than by scanning the heap, which
    any other test or library holding a `ValidationError` would turn red."""
    with pytest.raises(SpecParseError) as excinfo:
        validate_document(_Refused, {"count": "x"}, document="d")
    assert excinfo.value.__context__ is None
    assert excinfo.value.__cause__ is None


def test_a_quality_expression_past_the_depth_cap_is_refused_at_load() -> None:
    """S-0088/D-3 reaches a quality rule's `expr`, which is not `SqlText`
    because the quality guardrail owns its other refusals: only the depth is
    judged at load, and a shallow expression still loads."""
    from bloomery import load_project  # noqa: PLC0415

    def entity_model(expr: str) -> str:
        return (
            "spec_version: 1\nentities:\n  e:\n    grain: one e\n    key: [id]\n"
            "    fields:\n      id: {type: string}\n      amount: {type: int}\n"
            f'    quality:\n      - {{rule: expression, name: positive, expr: "{expr}", on_fail: flag}}\n'
        )

    assert load_project({"entity_model": entity_model("amount > 0")})
    deep = "(" * 40 + "amount > 0" + ")" * 40
    with pytest.raises(SpecParseError, match="levels deep"):
        load_project({"entity_model": entity_model(deep)})


def test_a_quality_expression_the_parser_cannot_convert_is_passed_on() -> None:
    """`DepthCappedSql` judges only depth, so a text the parser rejects is left
    for the quality guardrail, which owns this rule's other refusals — the bare
    `ValueError` SQLGlot's JSON-arrow path parser raises included (#281). It
    reaches load as authored text, not as a refusal here."""
    from bloomery import load_project  # noqa: PLC0415

    document = (
        "spec_version: 1\nentities:\n  e:\n    grain: one e\n    key: [id]\n"
        "    fields:\n      id: {type: string}\n      amount: {type: int}\n"
        '    quality:\n      - {rule: expression, name: positive, expr: "x->1e5", on_fail: flag}\n'
    )
    assert load_project({"entity_model": document})
