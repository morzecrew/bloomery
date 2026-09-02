"""The metric-shape guard (RFC 0034 D5–D9): the refusals the four time- and
filter-shaped metric forms need, and the one thing that used to be refused and
is now lowered.

Every case is the `period_over_period` fixture plus one metric, so what fails
is the metric under test and nothing around it — the same discipline the
`cumulative:` refusal these replace was pinned with.
"""

from __future__ import annotations

import pytest

from bloomery import build_project_ir, load_project
from bloomery.errors import (
    GuardrailError,
    InvalidMetricShape,
    MetricFilterInvalid,
    NonAdditiveWithoutComponents,
)
from bloomery.ir import ProjectIR
from support.compiling import fixture_sources, load_fixture

pytestmark = pytest.mark.unit

FIXTURE = "period_over_period"

_MEASURES = "measures: [paid_revenue, revenue, revenue_mtd, revenue_trailing_7d]"


def compile_with(metric_yaml: str, *, served: str = "") -> ProjectIR:
    """The fixture with one more metric, optionally served by its mart.

    ``served`` matters: a filter is checked against the marts that list the
    metric among their measures (RFC 0034 D9), so a filter case that leaves it
    unlisted is testing nothing.
    """

    _project, catalog = load_fixture(FIXTURE)
    sources = dict(fixture_sources(FIXTURE))
    sources["metrics"] = sources["metrics"] + metric_yaml
    if served:
        assert _MEASURES in sources["marts"]
        sources["marts"] = sources["marts"].replace(_MEASURES, _MEASURES[:-1] + f", {served}]")
    return build_project_ir(load_project(sources), catalog)


def violations(metric_yaml: str, *, served: str = "") -> tuple[GuardrailError, ...]:
    with pytest.raises(GuardrailError) as excinfo:
        compile_with(metric_yaml, served=served)
    return excinfo.value.collected


def one_violation(metric_yaml: str, *, served: str = "") -> GuardrailError:
    (leaf,) = violations(metric_yaml, served=served)
    return leaf


# ....................... #
# The ceiling actually lifted (RFC 0034 D5)


def test_a_cumulative_metric_compiles_where_it_used_to_be_refused() -> None:
    """`cumulative:` parse-validated and no stage lowered it, so the guardrail
    stage refused every metric carrying one (RFC 0002 D10). It lowers now, and
    the fixture's two forms reach the IR."""
    ir = build_project_ir(*load_fixture(FIXTURE))
    by_name = {metric.name: metric for metric in ir.metrics}

    assert by_name["revenue_mtd"].cumulative is not None
    assert by_name["revenue_mtd"].cumulative.grain_to_date == "month"
    assert by_name["revenue_trailing_7d"].cumulative is not None
    assert by_name["revenue_trailing_7d"].cumulative.window is not None


def test_a_derived_metric_satisfies_the_additivity_guard() -> None:
    """A derived metric is non-additive with no ratio, which is the shape
    `NonAdditiveWithoutComponents` exists to refuse — the `derived:` block is
    the decomposition that answers it (RFC 0006 §5.4, RFC 0034 D1)."""
    ir = build_project_ir(*load_fixture(FIXTURE))
    yoy = next(metric for metric in ir.metrics if metric.name == "revenue_yoy")

    assert yoy.ratio is None
    assert yoy.derived is not None


def test_a_non_additive_metric_with_neither_still_fails() -> None:
    """The guard is widened, not removed."""
    leaf = one_violation("  hollow:\n    additivity: non_additive\n")

    assert isinstance(leaf, NonAdditiveWithoutComponents)
    assert "'hollow'" in str(leaf)
    assert "derived: block" in str(leaf)


# ....................... #
# Incoherent declarations (RFC 0034 D6, D7)


def test_derived_and_cumulative_together_are_refused() -> None:
    """Two leaves, not one: the combination is refused *and* so is accumulating
    a metric with no measure. Both are true of this spelling, and RFC 0006 D2
    batches rather than stopping at the first."""
    leaves = violations(
        "  both:\n"
        "    additivity: non_additive\n"
        "    cumulative: {grain_to_date: month}\n"
        "    derived:\n"
        '      expr: "a"\n'
        "      inputs: {a: {metric: revenue}}\n"
    )

    assert [type(leaf) for leaf in leaves] == [InvalidMetricShape, InvalidMetricShape]
    assert any("mutually exclusive shapes" in str(leaf) for leaf in leaves)
    assert {leaf.source_path for leaf in leaves} == {"metrics: metrics.both"}


def test_a_derived_metric_declared_additive_is_refused() -> None:
    """It has no measure to aggregate; declaring one would send the emitter
    looking for an `agg:` that cannot exist."""
    leaf = one_violation(
        "  wrong:\n"
        "    additivity: additive\n"
        "    derived:\n"
        '      expr: "a"\n'
        "      inputs: {a: {metric: revenue}}\n"
    )

    assert isinstance(leaf, InvalidMetricShape)
    assert "no measure to aggregate" in str(leaf)


def test_a_non_additive_cumulative_metric_is_refused() -> None:
    """There is nothing to accumulate: the additivity describes the measure and
    the window describes how it accumulates (D6)."""
    leaf = one_violation(
        "  hollow_mtd:\n"
        "    additivity: non_additive\n"
        "    ratio: {numerator: revenue, denominator: revenue}\n"
        "    cumulative: {grain_to_date: month}\n"
    )

    assert isinstance(leaf, InvalidMetricShape)
    assert "no measure" in str(leaf)


def test_a_filter_on_a_derived_metric_is_refused() -> None:
    """A derived metric's rows are its inputs' rows, so a filter here restricts
    measures one level down — a post-aggregate filter, which RFC 0034 §9 keeps
    out of scope rather than approximating."""
    leaf = one_violation(
        "  filtered_derived:\n"
        "    additivity: non_additive\n"
        "    derived:\n"
        '      expr: "a"\n'
        "      inputs: {a: {metric: revenue}}\n"
        "    filter: [{dimension: status, op: eq, values: [paid]}]\n"
    )

    assert isinstance(leaf, InvalidMetricShape)
    assert "post-aggregate filter" in str(leaf)


# ....................... #
# The expression against its inputs (RFC 0034 D1)


def test_an_expression_naming_an_undeclared_alias_is_refused() -> None:
    leaves = violations(
        "  typo:\n"
        "    additivity: non_additive\n"
        "    derived:\n"
        '      expr: "currrent - prior"\n'
        "      inputs:\n"
        "        current: {metric: revenue}\n"
        "        prior: {metric: revenue, offset: {window: 1 year}}\n"
    )
    unknown = next(leaf for leaf in leaves if "references" in str(leaf))

    assert isinstance(unknown, InvalidMetricShape)
    assert "['currrent']" in str(unknown)
    assert "['current', 'prior']" in str(unknown)
    # The typo leaves `current` unread, and that is reported too — one mistake,
    # both of its consequences, rather than a fix-one-find-the-next round trip.
    assert any("['current']" in str(leaf) and "never" in str(leaf) for leaf in leaves)


def test_an_input_the_expression_never_reads_is_refused() -> None:
    """Not cosmetic: the unused input is a metric MetricFlow still computes —
    an offset join runs and its column is discarded."""
    leaf = one_violation(
        "  spare:\n"
        "    additivity: non_additive\n"
        "    derived:\n"
        '      expr: "current"\n'
        "      inputs:\n"
        "        current: {metric: revenue}\n"
        "        prior: {metric: revenue, offset: {window: 1 year}}\n"
    )

    assert isinstance(leaf, InvalidMetricShape)
    assert "never references" in str(leaf)
    assert "['prior']" in str(leaf)


# ....................... #
# Filters against the mart (RFC 0034 D9)


def test_a_filter_on_an_unflattened_dimension_is_refused() -> None:
    leaf = one_violation(
        "  regional:\n"
        "    grain: sale\n"
        "    additivity: additive\n"
        "    agg: sum\n"
        '    expr: "amount"\n'
        "    filter: [{dimension: region, op: eq, values: [emea]}]\n",
        served="regional",
    )

    assert isinstance(leaf, MetricFilterInvalid)
    assert "does not flatten" in str(leaf)
    assert "'channel'" in str(leaf)  # the known list names what it does carry


def test_a_filter_on_a_date_role_dimension_is_refused() -> None:
    """A metric pinned to one period is a constant. The message routes to the
    two constructs that express a time relation properly."""
    leaf = one_violation(
        "  march:\n"
        "    grain: sale\n"
        "    additivity: additive\n"
        "    agg: sum\n"
        '    expr: "amount"\n'
        '    filter: [{dimension: sold_month, op: eq, values: ["2024-03-01"]}]\n',
        served="march",
    )

    assert isinstance(leaf, MetricFilterInvalid)
    assert "constant, not a metric" in str(leaf)


def test_a_filter_value_that_does_not_fit_the_column_is_refused() -> None:
    """`status` is a string column; comparing it to a number would need a cast,
    and filter values are never cast (RFC 0013 D8)."""
    leaf = one_violation(
        "  numeric_status:\n"
        "    grain: sale\n"
        "    additivity: additive\n"
        "    agg: sum\n"
        '    expr: "amount"\n'
        "    filter: [{dimension: status, op: gt, values: [1]}]\n",
        served="numeric_status",
    )

    assert isinstance(leaf, MetricFilterInvalid)
    assert "StringType" in str(leaf)
    assert "never cast" in str(leaf)


def test_an_is_null_filter_needs_no_type_agreement() -> None:
    """Its one value is a bool that selects `IS NULL` or `IS NOT NULL`; it is
    never compared against the column, so a type check would be checking the
    wrong thing."""
    ir = compile_with(
        "  known_status:\n"
        "    grain: sale\n"
        "    additivity: additive\n"
        "    agg: sum\n"
        '    expr: "amount"\n'
        "    filter: [{dimension: status, op: is_null, values: [false]}]\n",
        served="known_status",
    )

    assert any(metric.name == "known_status" for metric in ir.metrics)


def _filtered(clause: str) -> str:
    """One measure-carrying metric whose only distinguishing feature is its
    filter — the shape every type case below shares."""

    return (
        "  probe:\n"
        "    grain: sale\n"
        "    additivity: additive\n"
        "    agg: sum\n"
        '    expr: "amount"\n'
        f"    filter: [{clause}]\n"
    )


@pytest.mark.parametrize(
    "clause",
    [
        # The RFC 0015 D5 carrier: `"50.5"` is how an exact decimal is written
        # in YAML, and it must not be read as an ill-typed string.
        '{dimension: amount, op: gte, values: ["50.5"]}',
        "{dimension: amount, op: gte, values: [50]}",
        "{dimension: units, op: gte, values: [1]}",
        "{dimension: is_test, op: eq, values: [false]}",
        "{dimension: status, op: in, values: [paid, shipped]}",
        '{dimension: sold_at, op: gte, values: ["2024-01-01"]}',
        # `is_null` compares nothing against the column, so no type has to fit.
        "{dimension: status, op: is_null, values: [false]}",
    ],
)
def test_a_value_in_the_columns_own_type_compiles(clause: str) -> None:
    ir = compile_with(_filtered(clause), served="probe")

    assert any(metric.name == "probe" for metric in ir.metrics)


@pytest.mark.parametrize(
    "clause",
    [
        # A boolean column takes booleans and nothing else.
        '{dimension: is_test, op: eq, values: ["yes"]}',
        # ...and a boolean is not a narrow integer: `true` against a numeric
        # column is an authoring mistake, not a 1.
        "{dimension: units, op: gte, values: [true]}",
        "{dimension: amount, op: gte, values: [true]}",
        # The string carrier is for values that *parse*, never an implicit cast
        # of arbitrary text.
        "{dimension: units, op: gte, values: [\"3\"]}",
        '{dimension: amount, op: gte, values: ["not a number"]}',
        "{dimension: status, op: eq, values: [1]}",
        # A temporal column takes an ISO carrier, not a number and not prose.
        "{dimension: sold_at, op: gte, values: [20240101]}",
        '{dimension: sold_at, op: gte, values: ["last tuesday"]}',
    ],
)
def test_a_value_the_column_cannot_hold_is_refused(clause: str) -> None:
    leaf = one_violation(_filtered(clause), served="probe")

    assert isinstance(leaf, MetricFilterInvalid)
    assert "never cast" in str(leaf)
