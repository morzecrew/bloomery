"""The MetricSet spec kind (RFC 0002 §5.5, D9–D10)."""

from __future__ import annotations

import pytest
import yaml

from bloomery.errors import SpecParseError
from bloomery.spec import MetricSet
from bloomery.spec.common import validate_document

pytestmark = pytest.mark.unit


def parse(text: str, document: str = "metrics") -> MetricSet:
    return validate_document(MetricSet, yaml.safe_load(text), document=document)


HAPPY = """
metrics_version: 1
metrics:
  gross_revenue:
    template: gross_revenue
  net_revenue:
    requires: [unit_price, quantity, discount]
    grain: order_item
    additivity: additive
    agg: sum
    expr: "unit_price * quantity - discount"
  stock_on_hand:
    grain: inventory_level
    additivity: semi_additive
    agg: sum
    expr: "stock_level"
    semi_additive: {over: date, rule: last}
  average_order_value:
    additivity: non_additive
    ratio: {numerator: net_revenue, denominator: order_count}
  revenue_mtd:
    additivity: additive
    template: gross_revenue
    cumulative: {grain_to_date: month}
"""


def test_happy_parse() -> None:
    metric_set = parse(HAPPY)
    assert metric_set.metrics_version == 1
    assert metric_set.metrics["gross_revenue"].template == "gross_revenue"
    net = metric_set.metrics["net_revenue"]
    assert net.requires == ("unit_price", "quantity", "discount")
    assert net.additivity == "additive"
    stock = metric_set.metrics["stock_on_hand"]
    assert stock.semi_additive is not None
    assert (stock.semi_additive.over, stock.semi_additive.rule) == ("date", "last")
    aov = metric_set.metrics["average_order_value"]
    assert aov.ratio is not None
    assert (aov.ratio.numerator, aov.ratio.denominator) == ("net_revenue", "order_count")
    mtd = metric_set.metrics["revenue_mtd"]
    assert mtd.cumulative is not None
    assert mtd.cumulative.grain_to_date == "month"


def test_bad_additivity_enum() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse("metrics_version: 1\nmetrics:\n  m: {additivity: sometimes}\n")
    assert excinfo.value.source_path == "metrics: metrics.m.additivity"


def test_bad_semi_additive_rule() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            "metrics_version: 1\nmetrics:\n  m:\n    additivity: semi_additive\n"
            "    semi_additive: {over: date, rule: median}\n"
        )
    assert excinfo.value.source_path == "metrics: metrics.m.semi_additive.rule"


def test_ratio_requires_both_members() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            "metrics_version: 1\nmetrics:\n  m:\n    additivity: non_additive\n"
            "    ratio: {numerator: net_revenue}\n"
        )
    assert excinfo.value.source_path == "metrics: metrics.m.ratio.denominator"


def test_cumulative_requires_exactly_one_form() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            "metrics_version: 1\nmetrics:\n  m:\n"
            "    cumulative: {window: 7 days, grain_to_date: month}\n"
        )
    assert excinfo.value.source_path == "metrics: metrics.m.cumulative"
    assert "exactly one" in str(excinfo.value)


def test_reserved_metric_time_metric_name() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse("metrics_version: 1\nmetrics:\n  metric_time: {additivity: additive}\n")
    assert excinfo.value.source_path == "metrics: metrics.metric_time"


def test_unknown_key_rejected() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse("metrics_version: 1\nmetrics:\n  m: {additivty: additive}\n")
    assert excinfo.value.source_path == "metrics: metrics.m.additivty"
