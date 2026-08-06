"""The MartSet spec kind (RFC 0010 §5.1): flatten-step union, prefixes, roles."""

from __future__ import annotations

import pytest
import yaml

from bloomery.errors import SpecParseError
from bloomery.spec import DateRoleStep, MartSet, ViaStep
from bloomery.spec.common import validate_document

pytestmark = pytest.mark.unit


def parse(text: str, document: str = "marts") -> MartSet:
    return validate_document(MartSet, yaml.safe_load(text), document=document)


HAPPY = """
marts_version: 1
marts:
  order_items:
    grain: order_item
    base: order_item
    flatten:
      - {via: item_of_order, prefix: order_}
      - {via: order_of_customer, prefix: customer_}
      - {date: order_date, role: ordered}
      - {date: ship_date, role: shipped}
    measures: [gross_revenue, discount, net_revenue, quantity]
    partition_by: [days(ordered_day)]
    cost_hint: 3
"""


def test_happy_parse() -> None:
    mart_set = parse(HAPPY)
    mart = mart_set.marts["order_items"]
    assert mart.grain == "order_item"
    assert mart.base == "order_item"
    # authored order is meaningful (chains flatten transitively, RFC 0010 D3)
    step_0, step_1, step_2, step_3 = mart.flatten
    assert isinstance(step_0, ViaStep) and step_0.prefix == "order_"
    assert isinstance(step_1, ViaStep) and step_1.via == "order_of_customer"
    assert isinstance(step_2, DateRoleStep) and step_2.role == "ordered"
    assert isinstance(step_3, DateRoleStep) and step_3.date == "ship_date"
    assert mart.measures == ("gross_revenue", "discount", "net_revenue", "quantity")
    assert mart.cost_hint == 3


def test_cost_hint_defaults_to_one() -> None:
    mart_set = parse("marts_version: 1\nmarts:\n  m: {grain: g, base: g}\n")
    assert mart_set.marts["m"].cost_hint == 1
    assert mart_set.marts["m"].flatten == ()


def test_via_step_requires_prefix() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            "marts_version: 1\nmarts:\n  m:\n    grain: g\n    base: g\n"
            "    flatten: [{via: item_of_order}]\n"
        )
    assert excinfo.value.source_path == "marts: marts.m.flatten[0].via.prefix"


def test_date_step_requires_role() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            "marts_version: 1\nmarts:\n  m:\n    grain: g\n    base: g\n"
            "    flatten: [{date: order_date}]\n"
        )
    assert excinfo.value.source_path == "marts: marts.m.flatten[0].date.role"


def test_bad_flatten_step_mixed_keys() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            "marts_version: 1\nmarts:\n  m:\n    grain: g\n    base: g\n"
            "    flatten: [{via: r, prefix: p_, date: d, role: x}]\n"
        )
    # two extra keys → batched into one aggregate listing both paths
    assert "flatten[0].via.date" in str(excinfo.value)
    assert "flatten[0].via.role" in str(excinfo.value)


def test_reserved_metric_time_role() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            "marts_version: 1\nmarts:\n  m:\n    grain: g\n    base: g\n"
            "    flatten: [{date: order_date, role: metric_time}]\n"
        )
    assert excinfo.value.source_path == "marts: marts.m.flatten[0].date.role"
    assert "reserved" in str(excinfo.value)


def test_bad_cost_hint() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse("marts_version: 1\nmarts:\n  m: {grain: g, base: g, cost_hint: 0}\n")
    assert excinfo.value.source_path == "marts: marts.m.cost_hint"


def test_flatten_union_revalidates_model_instances() -> None:
    # the tag function must also discriminate already-constructed step models
    original = parse(HAPPY).marts["order_items"]
    from bloomery.spec import Mart

    revalidated = Mart.model_validate(
        {
            "grain": original.grain,
            "base": original.base,
            "flatten": list(original.flatten),
        }
    )
    assert revalidated.flatten == original.flatten


def test_bad_partition_grammar() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            "marts_version: 1\nmarts:\n  m:\n    grain: g\n    base: g\n"
            "    partition_by: [minutes(ordered_day)]\n"
        )
    assert excinfo.value.source_path == "marts: marts.m.partition_by[0]"
