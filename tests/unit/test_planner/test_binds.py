"""Bound request values (S-0097/D-1, D-2, D-3, D-5, D-6; #304).

``Planner.plan(..., paramstyle=...)`` binds every request filter and
row-policy value, spells each as the driver's placeholder, and carries the
values in ``QueryPlan.params``; a metric's own ``filter:`` stays text.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from decimal import Decimal

import pytest

from bloomery import AnyOf, MetricRequest, Op, Predicate, RowPolicy, TimeGrain
from bloomery.errors import InvalidRequest
from bloomery.planner.filters import PARAMSTYLES
from bloomery.planner.result import QueryPlan
from support.planning import fixture_ir, make_planner, variant_ir

pytestmark = pytest.mark.unit

PLANNER = make_planner()

#: One filter per bindable type, plus a LIKE carrying a quote, a `%` and a
#: template delimiter, and an IN: every value a caller can hand the planner.
FILTERS = (
    Predicate("sold_at", Op.GTE, (date(2024, 3, 4),)),
    Predicate("booked_at", Op.LT, (datetime(2024, 5, 1, 9, 30),)),
    Predicate("amount", Op.GT, (Decimal("40.00"),)),
    Predicate("is_test", Op.EQ, (False,)),
    Predicate("channel", Op.LIKE, ("it's 100% {{ x }}",)),
    Predicate("units", Op.IN, (1, 3)),
)

VALUES = (
    date(2024, 3, 4),
    datetime(2024, 5, 1, 9, 30),
    Decimal("40.00"),
    False,
    "it's 100% {{ x }}",
    1,
    3,
)

#: Each style's placeholder for the n-th (1-based) one.
SPELLINGS = {
    "qmark": "?",
    "numeric": ":{n}",
    "named": ":p{n}",
    "format": "%s",
    "pyformat": "%(p{n})s",
}

_PLACEHOLDER = re.compile(r"\?|:p?[0-9]+\b|%s|%\(p[0-9]+\)s")


def _request(*filters: Predicate | AnyOf, metrics: tuple[str, ...] = ("revenue",)) -> MetricRequest:
    return MetricRequest(
        metrics=metrics, dimensions=("sold_month",), time_grain=TimeGrain.MONTH, filters=filters
    )


def _plan(
    request: MetricRequest, paramstyle: str | None, *, policy: RowPolicy | None = None
) -> QueryPlan:
    return PLANNER.plan(
        fixture_ir("period_over_period"), request, dialect="duckdb", policy=policy, paramstyle=paramstyle
    )


# ....................... #
# D-1, D-2: the styles and the params


def test_the_styles_are_pep_249_s_five() -> None:
    assert PARAMSTYLES == set(SPELLINGS)


@pytest.mark.parametrize("paramstyle", sorted(SPELLINGS))
def test_every_style_spells_its_placeholders_and_carries_the_values_in_order(paramstyle: str) -> None:
    plan = _plan(_request(*FILTERS), paramstyle)

    assert plan.params == tuple((f"p{n}", value) for n, value in enumerate(VALUES, 1))
    assert _PLACEHOLDER.findall(plan.sql) == [SPELLINGS[paramstyle].format(n=n) for n in range(1, len(VALUES) + 1)]
    assert "__bloomery_bind_" not in plan.sql


def test_a_value_reaches_the_params_and_never_the_text() -> None:
    sql = _plan(_request(*FILTERS), "qmark").sql

    for text in ("2024-03-04", "2024-05-01", "40.00", "it''s", "{{ x }}", "FALSE"):
        assert text not in sql


def test_inline_is_the_default_and_unchanged() -> None:
    plan = _plan(_request(*FILTERS), None)

    assert plan.params == ()
    assert "'2024-03-04'" in plan.sql
    assert plan.fingerprint == plan.shape == hashlib.sha256(plan.sql.encode()).hexdigest()


def test_an_unknown_style_is_refused_naming_the_five() -> None:
    with pytest.raises(InvalidRequest, match="paramstyle 'dollar'.*'format'"):
        _plan(_request(), "dollar")


# ....................... #
# D-3: what binds


def test_a_like_pattern_binds_whole_and_its_escape_stays_text() -> None:
    plan = _plan(_request(Predicate("channel", Op.LIKE, ("w\\_%",))), "named")

    assert "LIKE :p1 ESCAPE '\\'" in plan.sql
    assert plan.params == (("p1", "w\\_%"),)


def test_the_policy_binds_ahead_of_the_request_filters() -> None:
    plan = _plan(
        _request(Predicate("channel", Op.EQ, ("web",))),
        "named",
        policy=RowPolicy("status", Op.NE, "void"),
    )

    assert plan.params == (("p1", "void"), ("p2", "web"))
    assert plan.sql.index("<> :p1") < plan.sql.index("= :p2")


def test_any_of_binds_each_member() -> None:
    either = AnyOf((Predicate("status", Op.EQ, ("refunded",)), Predicate("amount", Op.GTE, ("100",))))
    plan = _plan(_request(either), "qmark")

    assert plan.params == (("p1", "refunded"), ("p2", Decimal("100")))


def test_a_metric_s_filter_stays_text() -> None:
    plan = _plan(_request(Predicate("channel", Op.EQ, ("web",)), metrics=("paid_revenue",)), "qmark")

    assert "= 'paid'" in plan.sql
    assert [value for _name, value in plan.params] == ["web"]


def test_a_composed_plan_binds_every_branch() -> None:
    request = MetricRequest(
        metrics=("line_discount", "shipping_count"),
        dimensions=("order_customer_tier",),
        filters=(Predicate("order_customer_tier", Op.EQ, ("gold",)),),
    )
    inline = PLANNER.plan(fixture_ir("cross_mart_branches"), request, dialect="duckdb")
    plan = PLANNER.plan(fixture_ir("cross_mart_branches"), request, dialect="duckdb", paramstyle="named")

    assert len(plan.marts) == 2
    assert inline.sql.count("'gold'") == len(plan.params) > 1
    assert {value for _name, value in plan.params} == {"gold"}
    assert "'gold'" not in plan.sql
    assert "__bloomery_bind_" not in plan.sql


# ....................... #
# D-5: `%` under format and pyformat


@pytest.mark.parametrize(("paramstyle", "literal"), [("pyformat", "'100%%'"), ("format", "'100%%'"), ("qmark", "'100%'")])
def test_a_percent_in_the_text_is_doubled_for_a_percent_style(paramstyle: str, literal: str) -> None:
    """A metric's filter is text, so its `%` meets the driver's parser: a
    `pyformat` driver reads `%%` as the one character (#304)."""
    ir = variant_ir(
        "period_over_period",
        metrics=(
            "      - {dimension: status, op: eq, values: [paid]}\n",
            "      - {dimension: status, op: eq, values: [\"100%\"]}\n",
        ),
    )
    request = _request(Predicate("channel", Op.EQ, ("web",)), metrics=("paid_revenue",))
    plan = PLANNER.plan(ir, request, dialect="duckdb", paramstyle=paramstyle)

    assert f"= {literal}" in plan.sql


# ....................... #
# D-6: fingerprint and shape


def test_two_values_share_a_shape_and_not_a_fingerprint() -> None:
    """A result cache keyed on the fingerprint never serves one filter's rows
    for another; a statement cache keyed on the shape reuses one."""
    first = _plan(_request(Predicate("sold_at", Op.GTE, (date(2024, 3, 4),))), "qmark")
    second = _plan(_request(Predicate("sold_at", Op.GTE, (date(2024, 4, 1),))), "qmark")
    again = _plan(_request(Predicate("sold_at", Op.GTE, (date(2024, 3, 4),))), "qmark")

    assert first.sql == second.sql
    assert first.shape == second.shape == hashlib.sha256(first.sql.encode()).hexdigest()
    assert first.fingerprint != second.fingerprint
    assert first.fingerprint == again.fingerprint
