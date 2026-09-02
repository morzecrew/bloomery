"""Emission of the RFC 0034 metric forms: what each target does with a derived
metric, a cumulative window and a metric filter.

The manifest golden pins the bytes; this pins the *decisions* — which
MetricFlow type each form lowers to, what the offsets carry, that Cube refuses
two of the three by name, and that the one predicate both targets render comes
from one function (D15).
"""

from __future__ import annotations

import pytest

from bloomery import Target, build_project_ir, compile_project, load_project
from bloomery.emit.lower import metric_filter_sql
from bloomery.emit.metricflow import emit_manifest
from bloomery.errors import UnsupportedByTarget
from bloomery.ir import MetricFilterIR
from bloomery.naming import DefaultNaming
from support.compiling import fixture_sources, load_fixture

pytestmark = pytest.mark.unit

FIXTURE = "period_over_period"


def manifest_metrics() -> dict[str, object]:
    project, catalog = load_fixture(FIXTURE)
    manifest = emit_manifest(build_project_ir(project, catalog), naming=DefaultNaming())
    return {metric.name: metric for metric in manifest.metrics}


def simple_only() -> tuple[object, object]:
    """The fixture cut down to the metrics Cube can express.

    Cube refuses a project carrying *any* derived or cumulative metric (D11),
    so the emittable half has to be a separate project rather than a separate
    mart — this is that project, built by truncating one document instead of
    duplicating five.
    """

    sources = dict(fixture_sources(FIXTURE))
    head, marker, _rest = sources["metrics"].partition("  # Month-to-date")
    assert marker, "the metrics document no longer has the cumulative section"
    sources["metrics"] = head
    sources["marts"] = sources["marts"].replace(
        "measures: [paid_revenue, revenue, revenue_mtd, revenue_trailing_7d]",
        "measures: [paid_revenue, revenue]",
    )
    _project, catalog = load_fixture(FIXTURE)
    return load_project(sources), catalog


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
    sources = dict(fixture_sources(FIXTURE))
    head, marker, _rest = sources["metrics"].partition("  # Month-to-date")
    assert marker
    sources["metrics"] = head + (
        "  revenue_yoy:\n"
        "    additivity: non_additive\n"
        "    derived:\n"
        '      expr: "current - prior"\n'
        "      inputs:\n"
        "        current: {metric: revenue}\n"
        "        prior: {metric: revenue, offset: {window: 1 year}}\n"
    )
    sources["marts"] = sources["marts"].replace(
        "measures: [paid_revenue, revenue, revenue_mtd, revenue_trailing_7d]",
        "measures: [paid_revenue, revenue]",
    )
    _project, catalog = load_fixture(FIXTURE)

    with pytest.raises(UnsupportedByTarget) as excinfo:
        compile_project(load_project(sources), catalog=catalog, target=Target.CUBE, dialect="duckdb")

    assert "'revenue_yoy'" in str(excinfo.value)
    assert "compareDateRange" in str(excinfo.value)


def test_cube_emits_a_measure_filter_for_a_filtered_metric() -> None:
    """The one RFC 0034 construct Cube does express, and it renders through the
    same function the MetricFlow where-filter does — only the column spelling
    differs."""
    project, catalog = simple_only()
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
    ("clause", "expected"),
    [
        (MetricFilterIR("status", "eq", ("paid",)), "REF = 'paid'"),
        (MetricFilterIR("status", "ne", ("paid",)), "REF <> 'paid'"),
        (MetricFilterIR("status", "in", ("paid", "shipped")), "REF IN ('paid', 'shipped')"),
        (MetricFilterIR("status", "not_in", ("void",)), "REF NOT IN ('void')"),
        (MetricFilterIR("n", "gt", (1,)), "REF > 1"),
        (MetricFilterIR("n", "gte", (1,)), "REF >= 1"),
        (MetricFilterIR("n", "lt", (1,)), "REF < 1"),
        (MetricFilterIR("n", "lte", (1,)), "REF <= 1"),
        (MetricFilterIR("flag", "eq", (True,)), "REF = TRUE"),
        (MetricFilterIR("flag", "eq", (False,)), "REF = FALSE"),
        (MetricFilterIR("x", "is_null", (True,)), "REF IS NULL"),
        (MetricFilterIR("x", "is_null", (False,)), "REF IS NOT NULL"),
        # The one escaping rule, defined once because both targets read it.
        (MetricFilterIR("name", "eq", ("O'Brien",)), "REF = 'O''Brien'"),
        (MetricFilterIR("d", "gte", ("2024-01-01",)), "REF >= '2024-01-01'"),
    ],
)
def test_every_operator_renders_once_for_both_targets(
    clause: MetricFilterIR, expected: str
) -> None:
    assert metric_filter_sql(clause, ref="REF") == expected
