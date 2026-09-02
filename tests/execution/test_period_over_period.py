"""Metrics over time, executed (RFC 0034, RFC 0009 §5.2 tier 4).

The compile-time checks prove a DERIVED metric with an offset is *emitted*;
this proves it subtracts the right two numbers, which is the claim the feature
exists for and a different one. Everything below is hand-computable from the
seed, and every expected value is written as arithmetic rather than as a
constant, so a reader can check the test rather than trust it.

The specimen: eight sales across 2023 and 2024.

``revenue`` by month
    2023-03 → 100, 2024-03 → 257 (100 + 7 + 50 + 100), 2023-04 → 40,
    2024-04 → 40, 2024-05 → 60.

``revenue_yoy`` — the question the ceiling made unaskable
    2024-03 → **157**, because 257 − 100. 2024-04 → **0**, a real zero rather
    than a null. 2024-05 → **NULL**, because there is no 2023-05: no prior
    period is not the same as no growth, and a metric that answered ``60`` or
    ``+100%`` there would be inventing a comparison.

``paid_revenue`` — the filter
    2024-03 → **207**, the 50 that was refunded excluded, against the 257 its
    unfiltered sibling reports off the same rows.

``revenue_mtd`` — accumulation from the start of the month
    03-01 → 100, 03-04 → 107, 03-05 → 157, 03-11 → 257. Every day between
    carries the running total forward, which is what distinguishes it from
    ``revenue`` reported per day.

``revenue_trailing_7d`` — accumulation over a moving window
    03-11 → **150** (03-05's 50 + 03-11's 100). The 7 on 03-04 is *exactly*
    seven days earlier and is **excluded**: MetricFlow's trailing window is
    half-open at the far end, and the seed is built to pin that boundary rather
    than to avoid it. 03-10 → 57 (03-04 + 03-05) shows the same edge from the
    inside.

``revenue_vs_month_start`` — the offset's other form
    Each day against the first day of its own month: 03-04 → 7 − 100 = −93.

All money is ``Decimal`` — floats never appear (RFC 0003 D5).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import duckdb
import pytest
from support.compiling import compile_fixture, fixture_sources, load_fixture
from support.execution import materialize, warehouse
from support.planning import fixture_ir, make_planner, normalize_month

from bloomery import MetricRequest, ProjectIR, TimeGrain, build_project_ir, load_project

pytestmark = pytest.mark.execution

FIXTURE = "period_over_period"

PLANNER = make_planner()

#: ``(id, amount, units, is_test, status, channel, sold_at)`` as bronze holds
#: them — text, like every payload. The dates are chosen so that every
#: assertion below is arithmetic on two or three of these rows; ``units`` and
#: ``is_test`` carry no metric and exist so the fixture has an integer and a
#: boolean column to type a filter against.
SALES = [
    ("s01", "100.00", "1", "false", "paid", "web", "2023-03-15"),
    ("s02", "100.00", "1", "false", "paid", "web", "2024-03-01"),
    # Exactly seven days before s05: the trailing-window boundary, seeded on
    # purpose rather than stepped around.
    ("s03", "7.00", "1", "false", "paid", "store", "2024-03-04"),
    # The row `paid_revenue` must not count.
    ("s04", "50.00", "2", "false", "refunded", "web", "2024-03-05"),
    ("s05", "100.00", "1", "false", "paid", "store", "2024-03-11"),
    ("s06", "40.00", "1", "false", "paid", "store", "2023-04-10"),
    ("s07", "40.00", "1", "false", "paid", "store", "2024-04-10"),
    # No 2023-05 counterpart: the year-over-year comparison has nothing to
    # subtract, and must say so.
    ("s08", "60.00", "3", "false", "paid", "web", "2024-05-02"),
]


#: The fixture's mart line, rewritten by `variant_ir` when a case needs a metric
#: the fixture does not carry.
_MEASURES = "measures: [large_recent_revenue, paid_revenue, revenue, revenue_mtd, revenue_trailing_7d]"


def variant_ir(extra: str, *, served: str) -> ProjectIR:
    """The fixture's IR plus one more measure-carrying metric.

    The mart table is **not** rebuilt, and does not need to be: a mart's SELECT
    projects its flattened columns and knows nothing about which metrics are
    served from it, so a metric added here plans against the table the module
    fixture already materialized.
    """

    sources = dict(fixture_sources(FIXTURE))
    sources["metrics"] = sources["metrics"] + extra
    assert _MEASURES in sources["marts"]
    sources["marts"] = sources["marts"].replace(_MEASURES, _MEASURES[:-1] + f", {served}]")
    _project, catalog = load_fixture(FIXTURE)
    return build_project_ir(load_project(sources), catalog)


@pytest.fixture(scope="module")
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = warehouse()
    connection.execute(
        "CREATE TABLE bronze.shop__sales (id VARCHAR, amount VARCHAR, units VARCHAR, "
        "is_test VARCHAR, status VARCHAR, channel VARCHAR, sold_at VARCHAR)"
    )
    connection.executemany("INSERT INTO bronze.shop__sales VALUES (?, ?, ?, ?, ?, ?, ?)", SALES)
    materialize(connection, compile_fixture(FIXTURE, dialect="duckdb"))
    yield connection
    connection.close()


def by_month(
    conn: duckdb.DuckDBPyConnection, *metrics: str
) -> dict[date, tuple[Decimal | None, ...]]:
    """Every requested metric by month, keyed by the month's first day.

    Rows where every metric is NULL are dropped: a request that reaches the
    time spine (any offset or cumulative window does) returns one row per spine
    period, and a month nothing happened in carries no claim.
    """

    plan = PLANNER.plan(
        fixture_ir(FIXTURE),
        MetricRequest(metrics=metrics, dimensions=("sold_month",), time_grain=TimeGrain.MONTH),
        dialect="duckdb",
    )
    rows = conn.execute(plan.sql).fetchall()
    return {
        normalize_month(row[0]): tuple(row[1:])
        for row in rows
        if any(value is not None for value in row[1:])
    }


def by_day(conn: duckdb.DuckDBPyConnection, *metrics: str) -> dict[date, tuple[Decimal | None, ...]]:
    """The same, at day grain."""

    plan = PLANNER.plan(
        fixture_ir(FIXTURE),
        MetricRequest(metrics=metrics, dimensions=("sold_day",), time_grain=TimeGrain.DAY),
        dialect="duckdb",
    )
    return {normalize_month(row[0]): tuple(row[1:]) for row in conn.execute(plan.sql).fetchall()}


# ....................... #
# Period over period (RFC 0034 D1, D2)


def test_year_over_year_subtracts_the_same_month_one_year_earlier(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """The feature, in one assertion: March 2024 is compared with March 2023,
    not with February 2024 and not with the whole of 2023."""
    rows = by_month(conn, "revenue", "revenue_yoy")

    assert rows[date(2024, 3, 1)][0] == Decimal("257.0000")
    assert rows[date(2023, 3, 1)][0] == Decimal("100.0000")
    assert rows[date(2024, 3, 1)][1] == Decimal("257.0000") - Decimal("100.0000")


def test_an_unchanged_year_reports_zero_rather_than_nothing(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """April is 40 in both years. Zero growth is a *number*; a metric that went
    NULL here would be indistinguishable from one with no prior period."""
    rows = by_month(conn, "revenue", "revenue_yoy")

    assert rows[date(2024, 4, 1)] == (Decimal("40.0000"), Decimal("0.0000"))


def test_a_month_with_no_prior_period_refuses_to_invent_one(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """2024-05 has no 2023-05 behind it. The comparison is NULL — not 60, and
    not "+100%": both would report growth against a period that never
    happened."""
    rows = by_month(conn, "revenue", "revenue_yoy")

    assert rows[date(2024, 5, 1)] == (Decimal("60.0000"), None)


def test_the_offset_reads_the_start_of_the_containing_period(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """``offset: {to_grain: month}`` is not a fixed distance back: every day in
    March is compared with 2024-03-01, whatever its own date."""
    rows = by_day(conn, "revenue", "revenue_vs_month_start")
    month_start = Decimal("100.0000")

    assert rows[date(2024, 3, 1)][1] == month_start - month_start
    assert rows[date(2024, 3, 4)][1] == Decimal("7.0000") - month_start
    assert rows[date(2024, 3, 5)][1] == Decimal("50.0000") - month_start


# ....................... #
# Cumulative windows (RFC 0034 D5)


def test_month_to_date_accumulates_and_does_not_reset_per_day(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """The defect this refuses is the reason ``cumulative:`` was refused for so
    long: compiled as a plain simple metric it would report each day's own
    revenue, which is right on the first day of the month and wrong every day
    after."""
    rows = by_day(conn, "revenue", "revenue_mtd")
    running = Decimal("0")

    for day, own in ((1, "100.00"), (4, "7.00"), (5, "50.00"), (11, "100.00")):
        running += Decimal(own)
        assert rows[date(2024, 3, day)][1] == running, f"2024-03-{day:02d}"

    # The days between carry the total forward rather than dropping to NULL.
    assert rows[date(2024, 3, 6)] == (None, Decimal("157.0000"))


def test_month_to_date_starts_over_in_the_next_month(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """April accumulates April, never March's 257 — the accumulation is bounded
    by the declared ``grain_to_date``."""
    rows = by_day(conn, "revenue", "revenue_mtd")

    assert rows[date(2024, 4, 10)][1] == Decimal("40.0000")


def test_the_trailing_window_is_half_open_at_the_far_end(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """``window: "7 days"`` at 2024-03-11 covers 03-05 through 03-11 and stops:
    03-04 is exactly seven days earlier and falls outside.

    Pinned rather than avoided. The boundary is MetricFlow's convention, not
    bloomery's, and an off-by-one here changes every trailing number silently —
    so the seed puts a row exactly on it.
    """
    rows = by_day(conn, "revenue", "revenue_trailing_7d")

    assert rows[date(2024, 3, 11)][1] == Decimal("50.0000") + Decimal("100.0000")
    # Seen from the inside: at 03-10 the same 03-04 row is six days back, and in.
    assert rows[date(2024, 3, 10)][1] == Decimal("7.0000") + Decimal("50.0000")


def test_a_month_grain_request_reports_the_accumulation_at_the_period_s_end(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """What `period_agg` decides, executed rather than described.

    A cumulative metric is a *series*, so asking for it at a grain coarser than
    it accumulates to has to collapse each period to one value. bloomery
    defaults that to `last`, so March 2024 by month reports the **257** the
    month finished on.

    This is the project's one deliberate divergence from MetricFlow, whose
    default is `first` — which reported 100 here, the running total on 03-01. A
    metric named `revenue_mtd` answering 100 for a month that totalled 257 is
    not month-to-date by any reading, and the reason bloomery may choose is
    that the choice is the author's: dbt exposes `period_agg` and pinning it
    removed that, rather than inheriting a convention.
    """
    rows = by_month(conn, "revenue", "revenue_mtd")

    assert rows[date(2024, 3, 1)] == (Decimal("257.0000"), Decimal("257.0000"))
    # Where a month holds one day, first and last coincide and the distinction
    # is invisible — which is why the March row above is the one that pins it.
    assert rows[date(2024, 5, 1)] == (Decimal("60.0000"), Decimal("60.0000"))


def test_an_author_who_wants_the_period_s_first_point_can_ask_for_it(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """The default is not the whole answer: `period_agg: first` is expressible,
    and it is the value MetricFlow would have imposed."""
    ir = variant_ir(
        "  revenue_mtd_first:\n"
        "    grain: sale\n"
        "    additivity: additive\n"
        "    agg: sum\n"
        '    expr: "amount"\n'
        "    cumulative: {grain_to_date: month, period_agg: first}\n",
        served="revenue_mtd_first",
    )
    plan = PLANNER.plan(
        ir,
        MetricRequest(
            metrics=("revenue", "revenue_mtd", "revenue_mtd_first"),
            dimensions=("sold_month",),
            time_grain=TimeGrain.MONTH,
        ),
        dialect="duckdb",
    )
    rows = {
        normalize_month(row[0]): tuple(row[1:])
        for row in conn.execute(plan.sql).fetchall()
        if any(value is not None for value in row[1:])
    }

    assert rows[date(2024, 3, 1)] == (
        Decimal("257.0000"),
        Decimal("257.0000"),
        Decimal("100.0000"),
    )


# ....................... #
# Metric filters (RFC 0034 D8)


def test_a_filtered_metric_counts_a_subset_of_the_rows_its_sibling_counts(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """``paid_revenue`` and ``revenue`` are the same aggregation over the same
    mart; the filter is the whole of the difference, and it is in the metric
    rather than in every caller's request."""
    rows = by_month(conn, "revenue", "paid_revenue")

    assert rows[date(2024, 3, 1)] == (
        Decimal("257.0000"),
        Decimal("257.0000") - Decimal("50.0000"),
    )
    # A month whose rows are all paid: the filter removes nothing, rather than
    # removing everything or being silently dropped.
    assert rows[date(2024, 4, 1)] == (Decimal("40.0000"), Decimal("40.0000"))


def test_two_filter_clauses_are_anded(conn: duckdb.DuckDBPyConnection) -> None:
    """That a where-filter intersection is an AND is MetricFlow's model; this
    runs it.

    March 2024 holds 257 in total, 207 of it paid, and exactly 100 of it both
    paid *and* on the web channel — the refunded 50 is web, and the paid 7 and
    100 are in store. An OR would report 257; either clause alone reports 207
    or 150.
    """
    ir = variant_ir(
        "  paid_web_revenue:\n"
        "    grain: sale\n"
        "    additivity: additive\n"
        "    agg: sum\n"
        '    expr: "amount"\n'
        "    filter:\n"
        "      - {dimension: status, op: eq, values: [paid]}\n"
        "      - {dimension: channel, op: eq, values: [web]}\n",
        served="paid_web_revenue",
    )
    plan = PLANNER.plan(
        ir,
        MetricRequest(
            metrics=("revenue", "paid_revenue", "paid_web_revenue"),
            dimensions=("sold_month",),
            time_grain=TimeGrain.MONTH,
        ),
        dialect="duckdb",
    )
    rows = {
        normalize_month(row[0]): tuple(row[1:])
        for row in conn.execute(plan.sql).fetchall()
        if any(value is not None for value in row[1:])
    }

    assert rows[date(2024, 3, 1)] == (
        Decimal("257.0000"),
        Decimal("207.0000"),
        Decimal("100.0000"),
    )
    # April is all in store, so the second clause removes everything the first
    # one kept — an AND that can reach empty, not a filter that quietly widens.
    assert rows[date(2024, 4, 1)][2] is None


def test_a_filter_reaches_sql_in_the_column_s_own_type(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """A decimal bound and a date bound, both written through the string
    carrier, both ANDed.

    The carrier is how an exact decimal is written in YAML (RFC 0015 D5), and
    rendering it as a *string* literal left the comparison to the engine's
    coercion rules — which Trino does not have: it refuses
    `decimal <= varchar` and `date <= varchar` outright. DuckDB coerces, so
    this assertion holds either way; the engine tier is where the difference
    shows, and this is the arithmetic it checks against.
    """
    rows = by_month(conn, "revenue", "large_recent_revenue")

    # 100 + 50 + 100 — the 7.00 on 03-04 is under the amount bound.
    assert rows[date(2024, 3, 1)] == (Decimal("257.0000"), Decimal("250.0000"))
    # 2023 is excluded by the date bound even though its 100.00 clears the other.
    assert rows[date(2023, 3, 1)] == (Decimal("100.0000"), None)


def test_the_filter_is_reported_in_the_explanation(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """A restricted metric that explains itself as its unrestricted sibling is
    a number the reader has no way to question (RFC 0011 §5.6)."""
    plan = PLANNER.plan(
        fixture_ir(FIXTURE),
        MetricRequest(metrics=("paid_revenue",), dimensions=("sold_month",)),
        dialect="duckdb",
    )
    (measure,) = plan.explanation.measures

    assert "restricted to status eq ['paid']" in measure.note
