"""Emission of the RFC 0034 metric forms: what each target does with a derived
metric, a cumulative window and a metric filter.

The manifest golden pins the bytes; this pins the *decisions* — which
MetricFlow type each form lowers to, what the offsets carry, that Cube refuses
two of the three by name, and that the one predicate both targets render comes
from one function (D15).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from bloomery import Target, build_project_ir, compile_project, load_project
from bloomery.emit.lower import metric_filter_sql
from bloomery.emit.metricflow import emit_manifest
from bloomery.errors import GrainViolation, GuardrailError, UnsupportedByTarget
from bloomery.ir import MetricFilterIR, project_fingerprint
from bloomery.naming import DefaultNaming
from bloomery.typing import (
    BoolType,
    DateType,
    DecimalType,
    IntType,
    LogicalType,
    StringType,
    TimestampType,
)
from support.compiling import fixture_sources, load_fixture

pytestmark = pytest.mark.unit

FIXTURE = "period_over_period"


def manifest_metrics() -> dict[str, object]:
    project, catalog = load_fixture(FIXTURE)
    manifest = emit_manifest(build_project_ir(project, catalog), naming=DefaultNaming())
    return {metric.name: metric for metric in manifest.metrics}


#: The fixture's mart line, and the one that serves only the two metrics Cube
#: can express. Named because three variants below rewrite it.
_ALL_MEASURES = "measures: [booked_since_march, large_recent_revenue, paid_revenue, revenue, revenue_mtd, revenue_trailing_7d]"
_SIMPLE_MEASURES = "measures: [paid_revenue, revenue]"


def variant(extra_metrics: str = "") -> tuple[object, object]:
    """The fixture with its cumulative and derived metrics cut, plus whatever
    ``extra_metrics`` adds back.

    Cube refuses a project carrying *any* derived or cumulative metric (D11),
    so the emittable half has to be a separate project rather than a separate
    mart — this builds it by truncating one document instead of duplicating
    five, and every case below that needs a *different* offending metric adds
    exactly that one.
    """

    sources = dict(fixture_sources(FIXTURE))
    head, marker, _rest = sources["metrics"].partition("  # Month-to-date")
    assert marker, "the metrics document no longer has the cumulative section"
    sources["metrics"] = head + extra_metrics
    assert _ALL_MEASURES in sources["marts"]
    sources["marts"] = sources["marts"].replace(_ALL_MEASURES, _SIMPLE_MEASURES)
    _project, catalog = load_fixture(FIXTURE)
    return load_project(sources), catalog


def with_metric(extra: str, *, served: str) -> dict[str, object]:
    """The whole fixture plus one more measure-carrying metric, as emitted
    manifest metrics by name.

    The complement of :func:`variant`, which *removes* metrics to reach the
    subset Cube can express. Cases that cross a new construct with an existing
    one — a cumulative metric that is also filtered, a semi-additive one that is
    — need the fixture intact and one metric added.
    """

    sources = dict(fixture_sources(FIXTURE))
    sources["metrics"] = sources["metrics"] + extra
    assert _ALL_MEASURES in sources["marts"]
    sources["marts"] = sources["marts"].replace(_ALL_MEASURES, _ALL_MEASURES[:-1] + f", {served}]")
    _project, catalog = load_fixture(FIXTURE)
    manifest = emit_manifest(
        build_project_ir(load_project(sources), catalog), naming=DefaultNaming()
    )
    return {metric.name: metric for metric in manifest.metrics}


# ....................... #
# MetricFlow: the four shapes (RFC 0034 D1, D2, D5, D8)


def test_a_derived_metric_lowers_to_derived_with_its_expression() -> None:
    metric = manifest_metrics()["revenue_yoy"]

    assert metric.type.value == "derived"
    assert metric.type_params.expr == "current - prior"
    assert [i.name for i in metric.type_params.metrics] == ["revenue", "revenue"]
    assert [i.alias for i in metric.type_params.metrics] == ["current", "prior"]


def test_an_offset_window_carries_its_count_and_grain() -> None:
    """`"1 year"` is parsed once, in the spec layer, and reaches MetricFlow as
    a count and a singular grain — never as the authored string."""
    (_current, prior) = manifest_metrics()["revenue_yoy"].type_params.metrics

    assert prior.offset_window.count == 1
    assert prior.offset_window.granularity == "year"
    assert prior.offset_to_grain is None


def test_an_offset_to_grain_carries_the_period_instead_of_a_distance() -> None:
    (_current, month_start) = manifest_metrics()["revenue_vs_month_start"].type_params.metrics

    assert month_start.offset_to_grain == "month"
    assert month_start.offset_window is None


@pytest.mark.parametrize(
    ("name", "window", "grain_to_date"),
    [
        ("revenue_mtd", None, "month"),
        ("revenue_trailing_7d", (7, "day"), None),
    ],
)
def test_a_cumulative_metric_lowers_to_cumulative_type_params(
    name: str, window: tuple[int, str] | None, grain_to_date: str | None
) -> None:
    """The window lands in `cumulative_type_params` and never in the legacy
    `type_params.window`/`grain_to_date` pair: two accounts of one window in a
    manifest is one for MSI's transformer to reconcile."""
    params = manifest_metrics()[name].type_params

    assert params.window is None
    assert params.grain_to_date is None
    assert params.cumulative_type_params.grain_to_date == grain_to_date
    if window is None:
        assert params.cumulative_type_params.window is None
    else:
        assert (
            params.cumulative_type_params.window.count,
            params.cumulative_type_params.window.granularity,
        ) == window


def test_a_metric_filter_lowers_to_a_where_filter_over_the_entity_key() -> None:
    """The dimension is spelled the way MetricFlow names a group-by item —
    `{entity}__{column}` — because that is the only name its resolver accepts
    inside a where-filter."""
    metric = manifest_metrics()["paid_revenue"]
    (where,) = metric.filter.where_filters

    assert where.where_sql_template == "{{ Dimension('sale__status') }} = 'paid'"


def test_an_unfiltered_metric_carries_no_filter_at_all() -> None:
    """Not an empty intersection: an empty `where_filters` list is a filter
    that matches everything, and it would serialize into every manifest."""
    assert manifest_metrics()["revenue"].filter is None


def test_a_cumulative_metric_can_also_be_filtered() -> None:
    """The two constructs are independent — the window says how the measure
    accumulates, the filter says which rows it accumulates — and the lowering
    has to carry both. Untested crossings are where a branch that "obviously"
    composes turns out not to."""
    metric = with_metric(
        "  paid_revenue_mtd:\n"
        "    grain: sale\n"
        "    additivity: additive\n"
        "    agg: sum\n"
        '    expr: "amount"\n'
        "    cumulative: {grain_to_date: month}\n"
        "    filter: [{dimension: status, op: eq, values: [paid]}]\n",
        served="paid_revenue_mtd",
    )["paid_revenue_mtd"]

    assert metric.type.value == "cumulative"
    assert metric.type_params.cumulative_type_params.grain_to_date == "month"
    assert metric.filter.where_filters[0].where_sql_template == (
        "{{ Dimension('sale__status') }} = 'paid'"
    )


def test_a_semi_additive_metric_can_also_be_filtered() -> None:
    """The same crossing on the third measure shape: the filter rides on the
    metric, the `non_additive_dimension` on the measure, and neither displaces
    the other."""
    metrics = with_metric(
        "  paid_balance:\n"
        "    grain: sale\n"
        "    additivity: semi_additive\n"
        "    agg: sum\n"
        '    expr: "amount"\n'
        "    semi_additive: {over: sold_at, rule: last}\n"
        "    filter: [{dimension: status, op: eq, values: [paid]}]\n",
        served="paid_balance",
    )

    assert metrics["paid_balance"].filter.where_filters[0].where_sql_template == (
        "{{ Dimension('sale__status') }} = 'paid'"
    )


def test_naming_a_derived_metric_in_measures_is_refused_not_inert() -> None:
    """RFC 0034 D4's second half is **wrong**, and this is where it shows.

    D4 (ASSUMED) says naming a derived metric in a mart's `measures:` "stays
    legal and inert, as it is for a ratio". It is neither: a derived metric
    declares no grain — it has no measure to have one — and the grain guardrail
    requires a measure's grain to equal the mart's exactly (RFC 0010 D2). So the
    mart refuses it.

    The ratio precedent D4 reasoned from was never exercised: no fixture in the
    corpus lists a grainless ratio in `measures:` either, so the claim was
    inherited from a shape nobody had tried. The refusal is the right behaviour
    — a mart cannot serve a metric it has no grain agreement with — and the
    message's first remedy is the correct one.
    """
    sources = dict(fixture_sources(FIXTURE))
    assert _ALL_MEASURES in sources["marts"]
    sources["marts"] = sources["marts"].replace(
        _ALL_MEASURES, _ALL_MEASURES[:-1] + ", revenue_yoy]"
    )
    _project, catalog = load_fixture(FIXTURE)

    with pytest.raises(GuardrailError) as excinfo:
        build_project_ir(load_project(sources), catalog)
    (leaf,) = excinfo.value.collected

    assert isinstance(leaf, GrainViolation)
    assert "remove it from this mart's measures" in str(leaf)


def test_two_spellings_of_one_window_compile_to_one_ir() -> None:
    """The consequence of dropping the plural, at the level where it shows.

    `"7 days"` and `"7 day"` are the same window, and RFC 0003 §5.4 says the
    fingerprint is a function of what the spec *means*. The manifest cannot
    show this — MetricFlow's transformer normalizes the grain itself — so
    without this assertion the normalization has no test at all.
    """
    sources = dict(fixture_sources(FIXTURE))
    assert 'cumulative: {window: "7 days"}' in sources["metrics"]
    singular = dict(sources)
    singular["metrics"] = sources["metrics"].replace(
        'cumulative: {window: "7 days"}', 'cumulative: {window: "7 day"}'
    )
    _project, catalog = load_fixture(FIXTURE)

    plural_ir = build_project_ir(load_project(sources), catalog)
    singular_ir = build_project_ir(load_project(singular), catalog)

    assert project_fingerprint(plural_ir) == project_fingerprint(singular_ir)


# ....................... #
# Cube: refused per construct (RFC 0034 D11)


def test_cube_refuses_a_cumulative_metric_by_name() -> None:
    """`revenue_mtd` sorts first among the fixture's offending metrics, so the
    full project refuses on the cumulative construct."""
    project, catalog = load_fixture(FIXTURE)
    with pytest.raises(UnsupportedByTarget) as excinfo:
        compile_project(project, catalog=catalog, target=Target.CUBE, dialect="duckdb")

    assert "'revenue_mtd'" in str(excinfo.value)
    assert "trailing rolling_window" in str(excinfo.value)


def test_cube_refuses_a_derived_metric_even_when_no_mart_names_it() -> None:
    """A derived metric need not appear in any mart's `measures:` (D4), so a
    per-mart check would let it pass unmentioned and Cube would emit a
    complete-looking model quietly missing the metric."""
    project, catalog = variant(
        "  revenue_yoy:\n"
        "    additivity: non_additive\n"
        "    derived:\n"
        '      expr: "current - prior"\n'
        "      inputs:\n"
        "        current: {metric: revenue}\n"
        "        prior: {metric: revenue, offset: {window: 1 year}}\n"
    )

    with pytest.raises(UnsupportedByTarget) as excinfo:
        compile_project(project, catalog=catalog, target=Target.CUBE, dialect="duckdb")

    assert "'revenue_yoy'" in str(excinfo.value)
    assert "compareDateRange" in str(excinfo.value)


def test_cube_emits_a_measure_filter_for_a_filtered_metric() -> None:
    """The one RFC 0034 construct Cube does express, and it renders through the
    same function the MetricFlow where-filter does — only the column spelling
    differs."""
    project, catalog = variant()
    artifact = next(
        a
        for a in compile_project(project, catalog=catalog, target=Target.CUBE, dialect="duckdb")
        if a.path == "model/cubes/sales.yml"
    )

    assert "filters:" in artifact.content
    assert "sql: '{CUBE}.status = ''paid'''" in artifact.content


# ....................... #
# The shared predicate (RFC 0034 D15)


@pytest.mark.parametrize(
    ("clause", "declared", "expected"),
    [
        (MetricFilterIR("status", "eq", ("paid",)), StringType(), "REF = 'paid'"),
        (MetricFilterIR("status", "ne", ("paid",)), StringType(), "REF <> 'paid'"),
        (
            MetricFilterIR("status", "in", ("paid", "shipped")),
            StringType(),
            "REF IN ('paid', 'shipped')",
        ),
        (MetricFilterIR("status", "not_in", ("void",)), StringType(), "REF NOT IN ('void')"),
        (MetricFilterIR("n", "gt", (1,)), IntType(), "REF > 1"),
        (MetricFilterIR("n", "gte", (1,)), IntType(), "REF >= 1"),
        (MetricFilterIR("n", "lt", (1,)), IntType(), "REF < 1"),
        (MetricFilterIR("n", "lte", (1,)), IntType(), "REF <= 1"),
        (MetricFilterIR("flag", "eq", (True,)), BoolType(), "REF = TRUE"),
        (MetricFilterIR("flag", "eq", (False,)), BoolType(), "REF = FALSE"),
        (MetricFilterIR("x", "is_null", (True,)), StringType(), "REF IS NULL"),
        (MetricFilterIR("x", "is_null", (False,)), StringType(), "REF IS NOT NULL"),
        # The one escaping rule, defined once because both targets read it.
        (MetricFilterIR("name", "eq", ("O'Brien",)), StringType(), "REF = 'O''Brien'"),
        # Typed, not quoted-and-hoped: Trino refuses `decimal <= varchar` and
        # `date <= varchar` outright, and the other two dialects only rescued
        # them by implicit cast.
        (MetricFilterIR("amt", "gte", ("50.00",)), DecimalType(12, 4), "REF >= 50.00"),
        (MetricFilterIR("amt", "gte", (Decimal("50.00"),)), DecimalType(12, 4), "REF >= 50.00"),
        (
            MetricFilterIR("d", "gte", ("2024-01-01",)),
            DateType(),
            "REF >= CAST('2024-01-01' AS DATE)",
        ),
        # The ISO `T` does not survive: Trino refuses
        # `CAST('2024-01-01T00:00:00' AS TIMESTAMP)` with INVALID_CAST_ARGUMENT,
        # while the space-separated form casts on all three dialects.
        (
            MetricFilterIR("t", "lt", ("2024-01-01T00:00:00",)),
            TimestampType(),
            "REF < CAST('2024-01-01 00:00:00' AS TIMESTAMP)",
        ),
        (
            MetricFilterIR("t", "lt", ("2024-01-01",)),
            TimestampType(),
            "REF < CAST('2024-01-01' AS TIMESTAMP)",
        ),
    ],
)
def test_every_operator_renders_once_for_both_targets(
    clause: MetricFilterIR, declared: LogicalType, expected: str
) -> None:
    assert metric_filter_sql(clause, ref="REF", declared=declared) == expected
