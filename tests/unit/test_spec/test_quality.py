"""The data-quality spec surface (RFC 0016 §5.3): the closed field- and
row-rule catalogues, the ``dedupe:``/``quarantine:``/``reconcile:`` blocks,
the portable regex subset, and the closed retention grammar."""

from __future__ import annotations

from decimal import Decimal

import pytest
import yaml

from bloomery.errors import SpecParseError
from bloomery.spec import (
    CoercibleRule,
    EntityModel,
    ExpressionRule,
    InSetRule,
    LengthRule,
    Mapping,
    PatternRule,
    RangeRule,
    ReferentialRule,
    SimpleFieldMapping,
)
from bloomery.spec.common import validate_document
from bloomery.spec.quality import PORTABLE_REGEX_REJECTED

pytestmark = pytest.mark.unit


def mapping_with(quality: str, document: str = "mappings/orders") -> Mapping:
    text = (
        "mapping_version: 1\nsource: s\ntarget: t\nkey: {}\n"
        'fields:\n  f:\n    from: "$.f"\n    quality:\n' + quality
    )
    return validate_document(Mapping, yaml.safe_load(text), document=document)


def entity_model(body: str, document: str = "entity_model") -> EntityModel:
    text = (
        "spec_version: 1\nentities:\n  e:\n    grain: g\n    key: [k]\n"
        "    fields: {k: {type: string}}\n" + body
    )
    return validate_document(EntityModel, yaml.safe_load(text), document=document)


def rules(mapping: Mapping) -> tuple[object, ...]:
    field = mapping.fields["f"]
    assert isinstance(field, SimpleFieldMapping)
    return field.quality


# ....................... #
# Field-level rules — the closed catalogue (D5)


ALL_FIELD_RULES = """
      - {rule: coercible, on_fail: quarantine}
      - {rule: not_null, on_fail: fail}
      - {rule: range, min: 0, on_fail: quarantine}
      - {rule: range, max: 1000000, on_fail: flag}
      - {rule: length, min: 1, max: 64, on_fail: flag}
      - {rule: pattern, regex: "^[A-Z]{2}-[0-9]+$", on_fail: quarantine}
      - {rule: in_enum, on_fail: quarantine}
      - {rule: in_set, values: [open, closed, 3], on_fail: flag}
      - {rule: unique, on_fail: fail}
"""


def test_every_field_rule_parses() -> None:
    parsed = rules(mapping_with(ALL_FIELD_RULES))
    assert len(parsed) == 9
    assert isinstance(parsed[0], CoercibleRule)
    price_min = parsed[2]
    assert isinstance(price_min, RangeRule)
    assert (price_min.min, price_min.max, price_min.on_fail) == (0, None, "quarantine")
    length = parsed[4]
    assert isinstance(length, LengthRule)
    assert (length.min, length.max) == (1, 64)
    assert isinstance(parsed[5], PatternRule)
    in_set = parsed[7]
    assert isinstance(in_set, InSetRule)
    assert in_set.values == ("open", "closed", 3)


def test_recipe_field_mapping_carries_quality_too() -> None:
    mapping = validate_document(
        Mapping,
        yaml.safe_load(
            "mapping_version: 1\nsource: s\ntarget: t\nkey: {}\n"
            'fields:\n  f:\n    recipe: from_total\n    from: {a: "$.a"}\n'
            "    quality: [{rule: coercible, on_fail: fail}]\n"
        ),
        document="mappings/orders",
    )
    assert len(mapping.fields["f"].quality) == 1


def test_quality_defaults_to_empty() -> None:
    assert rules(mapping_with("      []\n")) == ()


def test_range_bounds_never_become_floats() -> None:
    # RFC 0003 D5: no floats in the IR or an emission path — an authored
    # 1000.5 must land as a Decimal, exactly as assert: bounds do.
    rule = rules(mapping_with("      - {rule: range, max: 1000.5, on_fail: flag}\n"))[0]
    assert isinstance(rule, RangeRule)
    assert rule.max == Decimal("1000.5")
    assert not isinstance(rule.max, float)


def test_unknown_rule_names_the_closed_catalogue() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        mapping_with("      - {rule: bogus, on_fail: flag}\n")
    assert excinfo.value.source_path == "mappings/orders: fields.f.simple.quality[0]"
    # the refusal enumerates the catalogue — new rules are RFC amendments (D5)
    assert "'coercible', 'not_null', 'range', 'length', 'pattern'" in str(excinfo.value)


def test_on_fail_is_required_never_defaulted() -> None:
    # RFC 0016 D2: explicit per rule, never a global default.
    with pytest.raises(SpecParseError) as excinfo:
        mapping_with("      - {rule: unique}\n")
    assert excinfo.value.source_path == "mappings/orders: fields.f.simple.quality[0].unique.on_fail"
    assert "Field required" in str(excinfo.value)


def test_repair_is_not_a_v1_disposition() -> None:
    # RFC 0016 D17: repair is deferred out of v1 on a repair-recipe contract.
    with pytest.raises(SpecParseError) as excinfo:
        mapping_with("      - {rule: unique, on_fail: repair}\n")
    assert "Input should be 'flag', 'quarantine' or 'fail'" in str(excinfo.value)


def test_drop_is_not_a_disposition() -> None:
    # RFC 0016 D2: deliberately no drop — quarantine is drop plus recoverability.
    with pytest.raises(SpecParseError):
        mapping_with("      - {rule: unique, on_fail: drop}\n")


def test_unknown_rule_key_rejected() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        mapping_with("      - {rule: coercible, on_fail: fail, sample: 0.1}\n")
    assert (
        excinfo.value.source_path == "mappings/orders: fields.f.simple.quality[0].coercible.sample"
    )


def test_range_needs_at_least_one_bound() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        mapping_with("      - {rule: range, on_fail: quarantine}\n")
    assert excinfo.value.source_path == "mappings/orders: fields.f.simple.quality[0].range"
    assert "at least one of min / max" in str(excinfo.value)


def test_length_needs_at_least_one_bound() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        mapping_with("      - {rule: length, on_fail: flag}\n")
    assert "at least one of min / max" in str(excinfo.value)


def test_length_bounds_are_non_negative() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        mapping_with("      - {rule: length, min: -1, on_fail: flag}\n")
    assert excinfo.value.source_path == "mappings/orders: fields.f.simple.quality[0].length.min"


def test_in_set_needs_at_least_one_value() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        mapping_with("      - {rule: in_set, values: [], on_fail: flag}\n")
    assert excinfo.value.source_path == "mappings/orders: fields.f.simple.quality[0].in_set.values"


def test_in_enum_takes_no_admissible_set() -> None:
    # the set *is* the enum_map chain's mapping; restating it would let the
    # two drift, so `values:` is an unknown key here
    with pytest.raises(SpecParseError):
        mapping_with("      - {rule: in_enum, values: [a], on_fail: flag}\n")


# ....................... #
# The portable regex subset (D5)


@pytest.mark.parametrize(
    "regex",
    [
        "^[A-Z]{2}$",  # character class, anchors, quantifier
        r"\d+(-\d+)*",  # capturing groups and escapes
        "(?:abc|def)$",  # non-capturing groups stay portable
        r"a\[b",  # an escaped bracket is not a class opener
        "[(?=]",  # a class containing lookahead-shaped characters
        r"\(?=x",  # an escaped paren is a literal, not lookahead
    ],
)
def test_portable_patterns_accepted(regex: str) -> None:
    rule = rules(mapping_with(f"      - {{rule: pattern, regex: '{regex}', on_fail: flag}}\n"))[0]
    assert isinstance(rule, PatternRule)
    assert rule.regex == regex


@pytest.mark.parametrize(
    ("regex", "label"),
    [
        ("(?=abc)x", "lookahead"),
        ("(?!abc)x", "negative lookahead"),
        ("(?<=a)b", "lookbehind"),
        ("(?<!a)b", "negative lookbehind"),
        ("(?P<year>[0-9]{4})", "named group"),
        (r"(?P<a>x)(?P=a)", "named group"),
        ("(?<year>[0-9]{4})", "named group"),
        ("x[a]y(?=z)", "lookahead"),  # found after a character class
    ],
)
def test_non_portable_regex_rejected(regex: str, label: str) -> None:
    with pytest.raises(SpecParseError) as excinfo:
        mapping_with(f"      - {{rule: pattern, regex: '{regex}', on_fail: flag}}\n")
    assert excinfo.value.source_path == "mappings/orders: fields.f.simple.quality[0].pattern.regex"
    message = str(excinfo.value)
    assert label in message
    assert "portable regex subset" in message


def test_every_rejected_construct_is_reachable() -> None:
    # the table is the contract: each prefix must be refusable, and the
    # longer lookbehind prefixes must win over the bare named-group one
    for prefix, label in PORTABLE_REGEX_REJECTED:
        with pytest.raises(SpecParseError) as excinfo:
            mapping_with(f"      - {{rule: pattern, regex: '{prefix}a)', on_fail: flag}}\n")
        assert label in str(excinfo.value)


def test_malformed_regex_rejected() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        mapping_with("      - {rule: pattern, regex: '[unclosed', on_fail: flag}\n")
    assert "invalid regular expression" in str(excinfo.value)


# ....................... #
# Entity-level rules (D6)


ENTITY_QUALITY = """    quality:
      - {rule: expression, name: discount_not_exceeding_gross,
         expr: "discount <= unit_price * quantity", on_fail: flag}
      - {rule: referential, via: item_of_order, on_missing: unknown_member}
"""


def test_entity_row_rules_parse() -> None:
    entity = entity_model(ENTITY_QUALITY).entities["e"]
    expression, referential = entity.quality
    assert isinstance(expression, ExpressionRule)
    assert expression.name == "discount_not_exceeding_gross"
    assert expression.expr == "discount <= unit_price * quantity"
    assert isinstance(referential, ReferentialRule)
    assert (referential.via, referential.on_missing) == ("item_of_order", "unknown_member")


def test_entity_quality_defaults_to_empty() -> None:
    entity = entity_model("").entities["e"]
    assert (entity.quality, entity.dedupe, entity.quarantine) == ((), None, None)


def test_referential_has_no_fail_disposition() -> None:
    # RFC 0016 D6: orphans are an expected, recoverable data condition; a
    # pipeline-stopping orphan gate is a reconcile check instead.
    with pytest.raises(SpecParseError) as excinfo:
        entity_model("    quality: [{rule: referential, via: r, on_missing: fail}]\n")
    assert (
        excinfo.value.source_path
        == "entity_model: entities.e.quality[0].referential.on_missing"
    )
    assert "Input should be 'unknown_member', 'quarantine' or 'flag'" in str(excinfo.value)


def test_referential_carries_no_on_fail() -> None:
    with pytest.raises(SpecParseError):
        entity_model(
            "    quality: [{rule: referential, via: r, on_missing: flag, on_fail: flag}]\n"
        )


def test_expression_rule_name_is_identifier_constrained() -> None:
    # RFC 0016 D23: rule names reach _quality_flags in both lowerings, so no
    # form ever needs escaping.
    with pytest.raises(SpecParseError) as excinfo:
        entity_model('    quality: [{rule: expression, name: "Bad Name", expr: a, on_fail: flag}]\n')
    assert excinfo.value.source_path == "entity_model: entities.e.quality[0].expression.name"


def test_row_rules_are_a_closed_catalogue() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        entity_model("    quality: [{rule: unique, on_fail: flag}]\n")
    # `unique` is a *field* rule — it has no row-rule form
    assert "does not match any of the expected tags: 'expression', 'referential'" in str(
        excinfo.value
    )


# ....................... #
# dedupe / quarantine


def test_dedupe_parses() -> None:
    entity = entity_model(
        "    dedupe: {keep: latest_by, field: _ingested_at, tie_break: [_load_id]}\n"
    ).entities["e"]
    assert entity.dedupe is not None
    assert (entity.dedupe.keep, entity.dedupe.field) == ("latest_by", "_ingested_at")
    assert entity.dedupe.tie_break == ("_load_id",)


def test_missing_tie_break_parses_and_is_left_to_the_guardrail_stage() -> None:
    # RFC 0016 §5.3 names DedupeTieBreakMissing a *compile* error: a statement
    # about the model, batched with the rest — not a document-shape failure.
    entity = entity_model("    dedupe: {keep: latest_by, field: _ingested_at}\n").entities["e"]
    assert entity.dedupe is not None
    assert entity.dedupe.tie_break == ()


def test_dedupe_keep_is_a_closed_vocabulary() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        entity_model("    dedupe: {keep: first_by, field: _ingested_at}\n")
    assert excinfo.value.source_path == "entity_model: entities.e.dedupe.keep"


def test_dedupe_requires_a_field() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        entity_model("    dedupe: {keep: latest_by}\n")
    assert excinfo.value.source_path == "entity_model: entities.e.dedupe.field"


def test_quarantine_parses() -> None:
    entity = entity_model(
        '    quarantine: {retention: 90d, redact: ["$.customer.email"]}\n'
    ).entities["e"]
    assert entity.quarantine is not None
    assert entity.quarantine.retention == "90d"
    assert entity.quarantine.redact == ("$.customer.email",)


@pytest.mark.parametrize("retention", ["1h", "12h", "90d", "6w", "99999d"])
def test_retention_grammar_accepts(retention: str) -> None:
    entity = entity_model(f"    quarantine: {{retention: {retention}}}\n").entities["e"]
    assert entity.quarantine is not None
    assert entity.quarantine.retention == retention


@pytest.mark.parametrize(
    "retention",
    [
        "3m",  # ambiguous: minutes or months
        "6M",  # months are not a fixed duration
        "1y",  # nor years
        "0d",  # a zero window is a deletion policy, not a retention one
        "90",  # no unit
        "d",  # no magnitude
        "07d",  # leading zero
        "90 d",  # no whitespace form
        "1d12h",  # single-term grammar only
        "100000d",  # beyond the five-digit cap
    ],
)
def test_retention_grammar_rejects(retention: str) -> None:
    with pytest.raises(SpecParseError) as excinfo:
        entity_model(f'    quarantine: {{retention: "{retention}"}}\n')
    assert excinfo.value.source_path == "entity_model: entities.e.quarantine.retention"


def test_quarantine_requires_retention() -> None:
    # RFC 0016 §5.6: a reject table holds raw payloads, therefore PII —
    # retention is required, never defaulted.
    with pytest.raises(SpecParseError) as excinfo:
        entity_model('    quarantine: {redact: ["$.a"]}\n')
    assert excinfo.value.source_path == "entity_model: entities.e.quarantine.retention"


def test_redact_paths_are_jsonpaths() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        entity_model("    quarantine: {retention: 90d, redact: [customer.email]}\n")
    assert excinfo.value.source_path == "entity_model: entities.e.quarantine.redact[0]"


# ....................... #
# reconcile (document root)


RECONCILE = """reconcile:
  - {name: order_total_matches_lines, left: "sum(order_item.line_total) by order_id",
     right: "order.total_amount", tolerance: "0.01", on_fail: flag}
"""


def test_reconcile_parses_at_the_document_root() -> None:
    model = entity_model(RECONCILE)
    (block,) = model.reconcile
    assert block.name == "order_total_matches_lines"
    assert block.left == "sum(order_item.line_total) by order_id"
    assert block.tolerance == Decimal("0.01")
    assert not isinstance(block.tolerance, float)
    assert block.on_fail == "flag"


def test_reconcile_defaults_to_empty() -> None:
    assert entity_model("").reconcile == ()


def test_unquoted_tolerance_is_refused_as_a_float() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        entity_model(RECONCILE.replace('tolerance: "0.01"', "tolerance: 0.01"))
    assert excinfo.value.source_path == "entity_model: reconcile[0]"
    assert "quoted decimal string" in str(excinfo.value)


def test_integer_tolerance_is_accepted() -> None:
    # an int is exact; only the float form is ambiguous
    model = entity_model(RECONCILE.replace('tolerance: "0.01"', "tolerance: 0"))
    assert model.reconcile[0].tolerance == Decimal(0)


def test_negative_tolerance_rejected() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        entity_model(RECONCILE.replace('tolerance: "0.01"', 'tolerance: "-0.01"'))
    assert excinfo.value.source_path == "entity_model: reconcile[0].tolerance"


def test_reconcile_name_is_identifier_constrained() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        entity_model(RECONCILE.replace("name: order_total_matches_lines", 'name: "Order Total"'))
    assert excinfo.value.source_path == "entity_model: reconcile[0].name"


def test_non_mapping_reconcile_entry_rejected() -> None:
    # the float guard runs before shape validation, so it must pass a
    # non-mapping through untouched rather than mask the real complaint
    with pytest.raises(SpecParseError) as excinfo:
        entity_model("reconcile: [just_a_string]\n")
    assert excinfo.value.source_path == "entity_model: reconcile[0]"
    assert "valid dictionary" in str(excinfo.value)


def test_unknown_reconcile_key_rejected() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        entity_model(RECONCILE.replace("on_fail: flag", "on_fail: flag, sample: 1"))
    assert excinfo.value.source_path == "entity_model: reconcile[0].sample"
