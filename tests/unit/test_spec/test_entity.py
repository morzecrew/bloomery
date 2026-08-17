"""The EntityModel spec kind (RFC 0002 §5.5; original spec §3.3)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from bloomery.errors import SpecParseError
from bloomery.spec import EntityModel
from bloomery.spec.common import (  # noqa: PLC2701 — the reason is part of the contract
    _RESERVED_MEMBER_REASONS,
    RESERVED_MEMBER_NAMES,
    validate_document,
)

pytestmark = pytest.mark.unit


def parse(text: str, document: str = "entity_model") -> EntityModel:
    import yaml

    return validate_document(EntityModel, yaml.safe_load(text), document=document)


HAPPY = """
spec_version: 1
entities:
  order_item:
    grain: one row per line on an order
    key: [order_id, line_no]
    scd: type2
    partition_by: [days(order_date), region]
    materialization: incremental_by_partition
    fields:
      order_id: {type: string, required: true}
      line_no: {type: int, required: true}
      unit_price: {type: "decimal(12,4)", canonical: unit_price}
      qty: {type: int, renamed_from: quantity}
      weight_kg:
        type: decimal(10,3)
        assert: {min: 0, max: 1000.5, not_null: true}
      status:
        type: string
        assert: {enum: [open, closed], regex: "^(open|closed)$"}
      extensions: {type: variant}
relationships:
  - name: item_of_order
    from: order_item
    to: order
    via: {order_id: order_id}
    cardinality: many_to_one
"""


def test_happy_parse() -> None:
    model = parse(HAPPY)
    entity = model.entities["order_item"]
    assert entity.key == ("order_id", "line_no")  # authored order preserved
    assert entity.scd == "type2"
    assert entity.partition_by == ("days(order_date)", "region")
    assert entity.materialization == "incremental_by_partition"
    assert entity.fields["unit_price"].canonical == "unit_price"
    assert entity.fields["qty"].renamed_from == "quantity"
    weight_assert = entity.fields["weight_kg"].assert_
    assert weight_assert is not None
    assert weight_assert.min == 0
    assert weight_assert.max == Decimal("1000.5")  # floats never survive parse
    assert not isinstance(weight_assert.max, float)
    assert weight_assert.not_null is True
    status_assert = entity.fields["status"].assert_
    assert status_assert is not None
    assert status_assert.enum == ("open", "closed")
    rel = model.relationships[0]
    assert rel.from_ == "order_item"
    assert rel.via == {"order_id": "order_id"}


def test_scd_defaults_to_type1_and_materialization_to_none() -> None:
    model = parse("spec_version: 1\nentities:\n  e:\n    grain: g\n    key: [k]\n    fields:\n      k: {type: string}\n")
    assert model.entities["e"].scd == "type1"
    assert model.entities["e"].materialization is None  # derived later (RFC 0002 D7)


def test_bad_scd_enum() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            "spec_version: 1\nentities:\n  e:\n    grain: g\n    key: [k]\n"
            "    scd: type3\n    fields:\n      k: {type: string}\n"
        )
    assert excinfo.value.source_path == "entity_model: entities.e.scd"


def test_bad_partition_grammar() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            "spec_version: 1\nentities:\n  e:\n    grain: g\n    key: [k]\n"
            "    partition_by: [weeks(order_date)]\n    fields:\n      k: {type: string}\n"
        )
    assert excinfo.value.source_path == "entity_model: entities.e.partition_by[0]"


def test_bad_type_grammar() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            "spec_version: 1\nentities:\n  e:\n    grain: g\n    key: [k]\n"
            "    fields:\n      k: {type: float}\n"
        )
    assert excinfo.value.source_path == "entity_model: entities.e.fields.k.type"


def test_missing_required_grain() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse("spec_version: 1\nentities:\n  e:\n    key: [k]\n    fields:\n      k: {type: string}\n")
    assert excinfo.value.source_path == "entity_model: entities.e.grain"


def test_empty_key_rejected() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse("spec_version: 1\nentities:\n  e:\n    grain: g\n    key: []\n    fields:\n      k: {type: string}\n")
    assert excinfo.value.source_path == "entity_model: entities.e.key"


def test_unknown_field_key_rejected() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            "spec_version: 1\nentities:\n  e:\n    grain: g\n    key: [k]\n"
            "    fields:\n      k: {type: string, requird: true}\n"
        )
    assert excinfo.value.source_path == "entity_model: entities.e.fields.k.requird"


def test_reserved_metric_time_field_name() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            "spec_version: 1\nentities:\n  e:\n    grain: g\n    key: [k]\n"
            "    fields:\n      metric_time: {type: timestamp}\n"
        )
    assert excinfo.value.source_path == "entity_model: entities.e.fields.metric_time"
    assert "reserved" in str(excinfo.value)


@pytest.mark.parametrize("name", RESERVED_MEMBER_NAMES)
def test_every_generated_column_name_is_reserved(name: str) -> None:
    # RFC 0016 §5.5/§5.6 (D9, D21): the quality columns and the ingestion
    # metadata are *generated*, so an authored field claiming one would
    # collide silently — the whole reason `metric_time` was reserved first.
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            "spec_version: 1\nentities:\n  e:\n    grain: g\n    key: [k]\n"
            f"    fields:\n      {name}: {{type: string}}\n"
        )
    assert excinfo.value.source_path == f"entity_model: entities.e.fields.{name}"
    assert "reserved name" in str(excinfo.value)
    # The reason is contractual, not decorative — the stability reference makes
    # a newly reserved name the one change that may refuse a `spec_version: 1`
    # document without minting a version, and it is admissible *because* the
    # refusal says which layer owns the name and what to do. A message reading
    # only "reserved" would leave an author who has just been broken by an
    # upgrade with nothing to act on, which is the version bump's job undone.
    assert _RESERVED_MEMBER_REASONS[name] in str(excinfo.value)


#: The only reserved names an *entity* or *mart* can be called: the other seven
#: begin with ``_`` and `RELATION_NAME_PATTERN` refuses them before the reserved
#: check runs, so a test over all nine would assert nothing about seven of them.
RESERVED_RELATION_NAMES = ("has_quality_flags", "metric_time")


@pytest.mark.parametrize("name", RESERVED_RELATION_NAMES)
def test_a_reserved_relation_name_says_to_rename_the_relation(name: str) -> None:
    """`MemberName` and `RelationName` share the reserved list and not the
    repair instruction. One validator served both and told everyone to rename a
    "field/dimension/role", so an *entity* called `metric_time` was pointed at a
    field it does not have — and the stability reference admits a newly reserved
    name as the one within-version refusal precisely because the message is
    actionable, so naming the wrong surface undoes the argument.
    """
    with pytest.raises(SpecParseError) as excinfo:
        parse(f"spec_version: 1\nentities:\n  {name}:\n    grain: g\n    key: [k]\n    fields:\n      k: {{type: string}}\n")
    message = str(excinfo.value)
    assert _RESERVED_MEMBER_REASONS[name] in message
    assert "entity/mart" in message
    assert "field" not in message.split("pick a different")[1]


def test_the_reserved_set_is_exactly_the_generated_names() -> None:
    assert RESERVED_MEMBER_NAMES == (
        "_ingested_at",
        "_load_id",
        "_quality_flags",
        "_quality_ok",
        "_quality_repairs",
        # Reserved unconditionally, not only on a merged entity (RFC 0024 D18):
        # a name that is legal until a second mapping arrives is a trap laid
        # for the change that adds one.
        "_source",
        "_source_row_id",
        "has_quality_flags",
        "metric_time",
    )


def test_reserved_message_names_the_owning_rfc() -> None:
    # a bare "reserved" tells an author nothing about which layer owns it
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            "spec_version: 1\nentities:\n  e:\n    grain: g\n    key: [k]\n"
            "    fields:\n      _source_row_id: {type: string}\n"
        )
    assert "RFC 0016 D21" in str(excinfo.value)


def test_bad_cardinality() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            "spec_version: 1\nentities:\n  e:\n    grain: g\n    key: [k]\n"
            "    fields:\n      k: {type: string}\n"
            "relationships:\n"
            "  - {name: r, from: e, to: e, via: {k: k}, cardinality: many_to_many}\n"
        )
    assert excinfo.value.source_path == "entity_model: relationships[0].cardinality"


def test_a_relationship_needs_at_least_one_via_pair() -> None:
    """A relationship *is* its join, so ``via: {}`` describes nothing.

    Left open, an empty mapping parsed cleanly and crashed at emit — three
    different exceptions in three places, none of them naming the document.
    Shape is what parse is for (RFC 0002 D4), and ``Entity.key`` has required
    at least one entry on the same argument since it was written.
    """
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            "spec_version: 1\nentities:\n  e:\n    grain: g\n    key: [k]\n"
            "    fields:\n      k: {type: string}\n"
            "relationships:\n"
            "  - {name: r, from: e, to: e, via: {}, cardinality: many_to_one}\n"
        )
    assert excinfo.value.source_path == "entity_model: relationships[0].via"
    assert "at least 1" in str(excinfo.value)


def test_one_via_pair_is_enough() -> None:
    """The nearest non-trigger: a single-column join is the common case and
    must not be caught by the bound."""
    model = parse(
        "spec_version: 1\nentities:\n  e:\n    grain: g\n    key: [k]\n"
        "    fields:\n      k: {type: string}\n"
        "relationships:\n"
        "  - {name: r, from: e, to: e, via: {k: k}, cardinality: many_to_one}\n"
    )
    assert model.relationships[0].via == {"k": "k"}
