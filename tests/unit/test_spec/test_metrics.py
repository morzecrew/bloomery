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


# ....................... #
# The RFC 0034 grammar: derived, offsets, filters


DERIVED = """
metrics_version: 1
metrics:
  revenue_yoy:
    additivity: non_additive
    derived:
      expr: "current - prior"
      inputs:
        current: {metric: revenue}
        prior: {metric: revenue, offset: {window: 1 year}}
"""


def test_derived_parses_with_aliased_inputs() -> None:
    derived = parse(DERIVED).metrics["revenue_yoy"].derived
    assert derived is not None
    assert sorted(derived.inputs) == ["current", "prior"]
    assert derived.inputs["prior"].offset is not None
    assert derived.inputs["prior"].offset.window == "1 year"


def test_input_metrics_is_the_single_definition_of_what_a_derived_metric_needs() -> None:
    """Both the reference checker and the template merge read this property
    (RFC 0034 D3); it de-duplicates, so naming one metric twice is one edge."""
    derived = parse(DERIVED).metrics["revenue_yoy"].derived
    assert derived is not None
    assert derived.input_metrics == ("revenue",)


def test_derived_needs_at_least_one_input() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse('metrics_version: 1\nmetrics:\n  m:\n    derived: {expr: "1", inputs: {}}\n')
    assert excinfo.value.source_path == "metrics: metrics.m.derived.inputs"


@pytest.mark.parametrize("window", ["1 year", "7 days", "3 months", "2 quarters", "1 week"])
def test_the_window_grammar_accepts_singular_and_plural(window: str) -> None:
    parse(f'metrics_version: 1\nmetrics:\n  m:\n    cumulative: {{window: "{window}"}}\n')


@pytest.mark.parametrize(
    "window",
    [
        "0 days",  # a window of nothing is the metric written the long way
        "1 hour",  # the emitted time spine is day-grain (RFC 0008 D13)
        "year",  # no count
        "1year",  # no separator
        "1 fortnight",
    ],
)
def test_the_window_grammar_refuses_everything_else(window: str) -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse(f'metrics_version: 1\nmetrics:\n  m:\n    cumulative: {{window: "{window}"}}\n')
    assert excinfo.value.source_path == "metrics: metrics.m.cumulative.window"


def test_offset_requires_exactly_one_form() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            'metrics_version: 1\nmetrics:\n  m:\n    derived:\n      expr: "a"\n'
            "      inputs:\n        a: {metric: r, offset: {}}\n"
        )
    assert "exactly one" in str(excinfo.value)


def test_filter_parses_typed_values() -> None:
    metric = parse(
        "metrics_version: 1\nmetrics:\n  m:\n    filter:\n"
        "      - {dimension: status, op: in, values: [paid, shipped]}\n"
        "      - {dimension: line_no, op: gte, values: [1]}\n"
    ).metrics["m"]
    assert [clause.op for clause in metric.filter] == ["in", "gte"]
    assert metric.filter[0].values == ("paid", "shipped")
    assert metric.filter[1].values == (1,)


@pytest.mark.parametrize(
    ("clause", "fragment"),
    [
        ("{dimension: s, op: eq, values: [a, b]}", "exactly 1 value"),
        ("{dimension: s, op: in, values: []}", "at least one value"),
        ("{dimension: s, op: is_null, values: [1]}", "exactly one bool"),
        # RFC 0003 D5 — no float ever reaches an emission path.
        ("{dimension: s, op: eq, values: [1.5]}", "is a float"),
        # RFC 0034 D13 — both semantic targets template with braces.
        ('{dimension: s, op: eq, values: ["a{b}c"]}', "template brace"),
    ],
)
def test_filter_grammar_refusals(clause: str, fragment: str) -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse(f"metrics_version: 1\nmetrics:\n  m:\n    filter: [{clause}]\n")
    assert fragment in str(excinfo.value)


def test_a_quoted_decimal_survives_as_an_exact_value() -> None:
    """The string carrier RFC 0015 D5 established: YAML would round `1.5` to a
    float, and the quoted form is how an exact decimal is written."""
    metric = parse(
        'metrics_version: 1\nmetrics:\n  m:\n    filter: [{dimension: s, op: gt, values: ["1.5"]}]\n'
    ).metrics["m"]
    assert metric.filter[0].values == ("1.5",)


def test_a_nul_byte_in_a_filter_value_is_refused() -> None:
    with pytest.raises(SpecParseError) as excinfo:
        parse(
            "metrics_version: 1\nmetrics:\n  m:\n"
            '    filter: [{dimension: s, op: eq, values: ["a\\0b"]}]\n'
        )
    assert "NUL byte" in str(excinfo.value)


def test_a_non_finite_decimal_is_refused() -> None:
    """Not reachable from YAML — a `nan` there is a float and is refused as
    one — but an untyped caller can construct the model directly, and
    `amount < nan` is never TRUE on some engines and always TRUE on others."""
    from decimal import Decimal

    from bloomery.spec.metrics import MetricFilter

    with pytest.raises(ValueError, match="non-finite"):
        MetricFilter(dimension="amount", op="gt", values=(Decimal("NaN"),))
