"""Adapter unit tests (RFC 0013 R2): plan assembly, limit clamping and
warnings, the fingerprint, error translation (MetricFlow types never
escape), dialect refusal, and the Explanation ``render()`` shapes locked as
goldens-in-code."""

from __future__ import annotations

import hashlib

import pytest
import sqlglot
from metricflow_semantics.errors.error_classes import (
    InvalidQueryException,
    InvalidQuerySyntax,
    MetricFlowException,
    UnknownMetricError,
)

from bloomery import AnyOf, MetricRequest, Op, OrderSpec, Predicate, RowPolicy
from bloomery.semantic import Compute
from bloomery.errors import (
    AmbiguousDimension,
    InvalidRequest,
    PlannerError,
    UnknownMember,
    UnreachableAtGrain,
)
from bloomery.planner import TimeGrain
from bloomery.planner.metricflow_planner import translate_mf_error
from bloomery.semantic.plan import Filter, Scan
from support.planning import fixture_ir, make_planner, variant_ir

pytestmark = pytest.mark.unit

PLANNER = make_planner()


def test_plan_shape_and_fingerprint() -> None:
    plan = PLANNER.plan(
        fixture_ir("semi_additive_inventory"),
        MetricRequest(metrics=("stock_on_hand",), dimensions=("warehouse_id",)),
        dialect="duckdb",
    )
    assert plan.mart == "inventory"
    assert plan.warnings == ()
    assert plan.fingerprint == hashlib.sha256(plan.sql.encode("utf-8")).hexdigest()
    assert [c.name for c in plan.columns] == ["warehouse_id", "stock_on_hand"]
    assert "gold.mart_inventory" in plan.sql


def test_limit_is_clamped_with_a_warning() -> None:
    planner = make_planner(max_limit=10)
    plan = planner.plan(
        fixture_ir("non_additive_aov"),
        MetricRequest(metrics=("revenue",), dimensions=("store",), limit=99),
        dialect="duckdb",
    )
    assert plan.warnings == ("limit 99 exceeds the planner's max_limit 10; clamped to 10",)
    assert "LIMIT 10" in plan.sql
    assert "99" not in plan.sql


def test_default_limit_applies_when_request_has_none() -> None:
    planner = make_planner(default_limit=5)
    plan = planner.plan(
        fixture_ir("non_additive_aov"),
        MetricRequest(metrics=("revenue",)),
        dialect="duckdb",
    )
    assert "LIMIT 5" in plan.sql
    assert plan.warnings == ()


def test_default_limit_is_clamped_too() -> None:
    planner = make_planner(max_limit=3, default_limit=50)
    plan = planner.plan(
        fixture_ir("non_additive_aov"), MetricRequest(metrics=("revenue",)), dialect="duckdb"
    )
    assert "LIMIT 3" in plan.sql
    assert plan.warnings == ("limit 50 exceeds the planner's max_limit 3; clamped to 3",)


def test_time_grain_without_date_dimension_warns_and_is_ignored() -> None:
    plan = PLANNER.plan(
        fixture_ir("non_additive_aov"),
        MetricRequest(metrics=("revenue",), dimensions=("store",), time_grain=TimeGrain.MONTH),
        dialect="duckdb",
    )
    assert plan.warnings == (
        "time_grain 'month' has no date-role dimension in the request to apply to; ignored",
    )


def test_unknown_dialect_is_a_planner_error() -> None:
    with pytest.raises(PlannerError, match="unknown planner dialect"):
        PLANNER.plan(
            fixture_ir("non_additive_aov"),
            MetricRequest(metrics=("revenue",)),
            dialect="oracle",
        )


def test_order_by_desc_and_limit_reach_the_sql() -> None:
    plan = PLANNER.plan(
        fixture_ir("non_additive_aov"),
        MetricRequest(
            metrics=("revenue",),
            dimensions=("store",),
            order_by=(OrderSpec("revenue", "desc"), OrderSpec("store")),
            limit=7,
        ),
        dialect="duckdb",
    )
    assert "ORDER BY revenue DESC" in plan.sql
    assert "LIMIT 7" in plan.sql


# ....................... #
# Error translation (RFC 0013 D2) — MetricFlow types never escape


def test_invalid_query_syntax_translates_to_invalid_request() -> None:
    error = translate_mf_error(InvalidQuerySyntax("bad filter template"))
    assert isinstance(error, InvalidRequest)
    assert "bad filter template" in str(error)


def test_unknown_metric_error_translates_to_unknown_member() -> None:
    assert isinstance(translate_mf_error(UnknownMetricError("no such metric")), UnknownMember)


def test_ambiguous_resolution_translates_to_ambiguous_dimension() -> None:
    error = translate_mf_error(InvalidQueryException("the given input is ambiguous"))
    assert isinstance(error, AmbiguousDimension)


def test_unmatched_group_by_translates_to_unknown_member() -> None:
    error = translate_mf_error(
        InvalidQueryException("The given input does not match any of the available group-bys")
    )
    assert isinstance(error, UnknownMember)


def test_join_failure_translates_to_unreachable_at_grain() -> None:
    error = translate_mf_error(
        InvalidQueryException("unable to join metrics without a common semantic model")
    )
    assert isinstance(error, UnreachableAtGrain)


def test_other_invalid_query_translates_to_invalid_request() -> None:
    error = translate_mf_error(InvalidQueryException("something request-shaped went wrong"))
    assert isinstance(error, InvalidRequest)


def test_unclassified_metricflow_error_stays_a_planner_error_with_message() -> None:
    error = translate_mf_error(MetricFlowException("internal surprise"))
    assert type(error) is PlannerError
    assert "internal surprise" in str(error)


def test_metricflow_failure_is_translated_never_reraised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The delegation seam: a MetricFlow exception surfacing from explain()
    reaches the caller as bloomery taxonomy, with the original chained."""
    from bloomery.planner import metricflow_planner as adapter

    class _ExplodingEngine:
        def __init__(self, **_kwargs: object) -> None: ...

        def explain(self, _request: object) -> object:
            raise InvalidQueryException("the given input is ambiguous")

    monkeypatch.setattr(adapter, "MetricFlowEngine", _ExplodingEngine)
    with pytest.raises(AmbiguousDimension) as excinfo:
        make_planner().plan(
            fixture_ir("non_additive_aov"), MetricRequest(metrics=("revenue",)), dialect="duckdb"
        )
    assert isinstance(excinfo.value.__cause__, InvalidQueryException)


def test_refusals_happen_before_delegation() -> None:
    """Coverage refuses the request; MetricFlow never sees it — the hydrator
    is never even consulted for an unanswerable one.

    Grouped by `order_id`, which **both** marts carry and neither means the
    same thing by: it is the key of the mart based at `order` and the foreign
    key on the mart based at `order_item`. RFC 0041 P1 answers a cross-mart
    request by joining branch aggregates, so the unanswerable one is no longer
    "two grains" but "two grains with nothing proven to join on"
    (RFC 0041 D12).
    """
    planner = make_planner()
    with pytest.raises(UnreachableAtGrain):
        planner.plan(
            fixture_ir("multi_mart_refusal"),
            MetricRequest(metrics=("shipping_cost", "line_discount"), dimensions=("order_id",)),
            dialect="duckdb",
        )


# ....................... #
# Explanation renders — locked shapes (RFC 0011 D8: change deliberately)


def test_day_column_falls_back_to_the_source_column_name() -> None:
    from bloomery.planner.explain import _day_column

    mart = fixture_ir("non_additive_aov").marts[0]
    assert _day_column(mart, "order_date") == "ordered_day"
    assert _day_column(mart, "not_a_date_source") == "not_a_date_source"


def test_human_predicate_prose_covers_every_operator() -> None:
    from bloomery.planner.explain import _human_predicate

    assert _human_predicate(Predicate("store", Op.IS_NULL, (True,)), "store") == (
        "store is null"
    )
    assert _human_predicate(Predicate("store", Op.IS_NULL, (False,)), "store") == (
        "store is not null"
    )
    assert _human_predicate(Predicate("store", Op.IN, ("A", "B")), "store") == (
        "store in ('A', 'B')"
    )
    assert _human_predicate(Predicate("store", Op.NOT_IN, ("A",)), "store") == (
        "store not in ('A')"
    )
    assert _human_predicate(Predicate("store", Op.LIKE, ("%dh%",)), "store") == (
        "store like '%dh%'"
    )
    # Multi-pattern like/ilike is an OR of repeated predicates — the prose
    # says what the renderer executes (RFC 0015 §5.1), never a value list
    # that hides the disjunction.
    assert _human_predicate(Predicate("store", Op.ILIKE, ("a%", "b%")), "store") == (
        "store ilike 'a%' OR store ilike 'b%'"
    )
    assert _human_predicate(Predicate("store", Op.LIKE, ("a%", "b%", "c%")), "store") == (
        "store like 'a%' OR store like 'b%' OR store like 'c%'"
    )
    assert _human_predicate(Predicate("flag", Op.EQ, (True,)), "flag") == "flag = true"
    assert _human_predicate(Predicate("flag", Op.NE, (False,)), "flag") == "flag != false"
    assert _human_predicate(Predicate("amount", Op.GT, (5,)), "amount") == "amount > 5"
    # The remaining comparison symbols — all eleven Op members are asserted
    # here, so the _SYMBOLS lookup is locked for every one of them.
    assert _human_predicate(Predicate("amount", Op.LT, (5,)), "amount") == "amount < 5"
    assert _human_predicate(Predicate("amount", Op.LTE, (5,)), "amount") == "amount <= 5"
    assert _human_predicate(Predicate("amount", Op.GTE, (5,)), "amount") == "amount >= 5"


def test_ratio_explanation_render() -> None:
    plan = PLANNER.plan(
        fixture_ir("non_additive_aov"),
        MetricRequest(
            metrics=("average_order_value",),
            dimensions=("store",),
            filters=(
                Predicate("ordered_month", Op.GTE, ("2024-01-01",)),
                Predicate("ordered_month", Op.LTE, ("2024-03-01",)),
            ),
        ),
        dialect="duckdb",
        policy=RowPolicy("store", Op.EQ, "A"),
    )
    assert plan.explanation.render() == (
        "average_order_value\n"
        "  mart:     gold.mart_orders (grain: order)\n"
        "  measure:  average_order_value = revenue / order_count\n"
        "            [non-additive ratio — recomputed at the requested grain, not summed]\n"
        "  filters:  ordered_month >= '2024-01-01'; ordered_month <= '2024-03-01'\n"
        "  policy:   applied"
    )


def test_any_of_explanation_shows_one_entry_with_or() -> None:
    plan = PLANNER.plan(
        fixture_ir("non_additive_aov"),
        MetricRequest(
            metrics=("revenue",),
            filters=(
                AnyOf((Predicate("store", Op.EQ, ("A",)), Predicate("store", Op.EQ, ("B",)))),
            ),
        ),
        dialect="duckdb",
    )
    assert plan.explanation.filters == ("store = 'A' OR store = 'B'",)


def test_semi_additive_explanation_render() -> None:
    plan = PLANNER.plan(
        fixture_ir("semi_additive_inventory"),
        MetricRequest(metrics=("stock_on_hand",)),
        dialect="duckdb",
    )
    assert plan.explanation.render() == (
        "stock_on_hand\n"
        "  mart:     gold.mart_inventory (grain: inventory_level)\n"
        "  measure:  stock_on_hand = SUM(stock_level)\n"
        "            [semi-additive last over snapshot_day — MAX-join then SUM]\n"
        "  filters:  (none)\n"
        "  policy:   not applied"
    )


def test_a_distinct_count_is_planned_on_one_mart_and_explained_as_one() -> None:
    """A `COUNT(DISTINCT x)` over the scan is one plain aggregate, so the
    single-mart `SemanticPlan` states it (logs/T-0028.md) — and the note says
    what the class means rather than calling it additive.
    """
    ir = variant_ir(
        "cross_mart_branches",
        metrics=(
            "  shipping_count:\n    grain: order\n    additivity: additive\n    agg: count\n"
            '    expr: "order_id"\n',
            "  shipping_count:\n    grain: order\n    additivity: distinct_count\n"
            '    agg: count_distinct\n    expr: "customer_id"\n',
        ),
    )
    plan = PLANNER.plan(
        ir, MetricRequest(metrics=("shipping_count",), dimensions=("region",)), dialect="duckdb"
    )

    assert "COUNT(DISTINCT" in plan.sql
    assert plan.semantic is not None
    assert plan.semantic.nodes[2].measures == ("shipping_count",)
    assert plan.explanation.render() == (
        "shipping_count\n"
        "  mart:     gold.mart_orders (grain: order)\n"
        "  measure:  shipping_count = COUNT(DISTINCT customer_id)\n"
        "            [distinct count — COUNT(DISTINCT) over the rows at the requested grain, "
        "never rolled up]\n"
        "  filters:  (none)\n"
        "  policy:   not applied"
    )


def test_additive_explanation_render() -> None:
    plan = PLANNER.plan(
        fixture_ir("non_additive_aov"),
        MetricRequest(metrics=("order_count", "revenue")),
        dialect="duckdb",
    )
    assert plan.explanation.render() == (
        "order_count, revenue\n"
        "  mart:     gold.mart_orders (grain: order)\n"
        "  measure:  order_count = COUNT(order_id)\n"
        "            [additive — COUNT]\n"
        "  measure:  revenue = SUM(amount)\n"
        "            [additive — SUM]\n"
        "  filters:  (none)\n"
        "  policy:   not applied"
    )


# ....................... #
# Planner dialect smoke (M10): MetricFlow's shipped trino/postgres renderers
# wired through sql_client_for_dialect — render-only, nothing executed.


@pytest.mark.parametrize("dialect", ["postgres", "trino"])
def test_plan_renders_legal_sql_for_the_second_dialects(dialect: str) -> None:
    plan = PLANNER.plan(
        fixture_ir("non_additive_aov"),
        MetricRequest(metrics=("revenue",), dimensions=("store",)),
        dialect=dialect,
    )
    assert "gold.mart_orders" in plan.sql
    parsed = sqlglot.parse_one(plan.sql, dialect=dialect)
    assert parsed is not None


# ....................... #
# Cross-mart requests — RFC 0041 P1


def _composed(
    dimensions: tuple[str, ...] = ("tier",),
    *,
    limit: int | None = None,
    **kwargs: object,
):
    planner = make_planner(**kwargs)  # type: ignore[arg-type]
    return planner.plan(
        fixture_ir("cross_mart_branches"),
        MetricRequest(
            metrics=("shipping_count", "line_discount", "customer_count"),
            dimensions=dimensions,
            limit=limit,
        ),
        dialect="duckdb",
    )


def test_a_cross_mart_request_names_every_mart_it_read() -> None:
    """D15: `mart` is a single name and a composed plan has several, so
    `marts` carries them all and `mart` keeps its meaning as the first —
    something that really served part of the answer, rather than a name
    invented for the join."""
    plan = _composed()

    assert plan.marts == ("customers", "order_items", "orders")
    assert plan.mart == "customers"


def test_the_result_columns_are_the_caller_s_order_and_the_caller_s_names() -> None:
    """Branches are sorted by mart name so the SQL is deterministic; a
    result's column order is part of the answer and is the request's. The key
    is answered under the name the caller asked for, not under any branch's
    spelling of it (logs/T-0026.md, D-165)."""
    plan = _composed()

    assert [column.name for column in plan.columns] == [
        "tier",
        "shipping_count",
        "line_discount",
        "customer_count",
    ]
    assert [column.sql_alias for column in plan.columns][0] == "tier"


def test_the_explanation_names_every_branch() -> None:
    """RFC 0011 D8 asks that every number ships with how it was computed, and
    for a composed answer that is three relations rather than one."""
    rendered = _composed().explanation.render()

    assert rendered.count("branch:") == 3
    assert "gold.mart_orders (grain: order)" in rendered
    assert "  mart:" not in rendered


def test_a_limit_lands_on_the_composed_statement_and_not_in_a_branch() -> None:
    """RFC 0041 §13a's P2 half of the limit (logs/T-0027.md, D-182).

    P1 dropped the planner's default and said so, because a limit pushed into
    a branch truncates it **before** the join and answers from a prefix. The
    composed statement is where it means what the caller asked for, so it goes
    there — and nowhere else, which is what the branch count asserts: exactly
    one `LIMIT` in the whole statement, after the joins.
    """
    plan = _composed(default_limit=100)

    assert plan.sql.upper().count("LIMIT") == 1
    assert plan.sql.rstrip().endswith("LIMIT 100")
    assert not any("default limit" in warning for warning in plan.warnings)


def test_a_clamped_limit_still_warns_on_the_composed_path() -> None:
    """RFC 0011 D4's clamp is the planner's, not MetricFlow's, so moving the
    limit onto bloomery's own statement must not leave the clamp behind — the
    composed path reuses `_effective_limit` rather than keeping a second copy
    of the rule (D-182)."""
    plan = _composed(max_limit=25, limit=1_000)

    assert plan.sql.rstrip().endswith("LIMIT 25")
    assert any("clamped to 25" in warning for warning in plan.warnings)


def test_the_composed_sql_is_fingerprinted_over_the_whole_statement() -> None:
    """The fingerprint is the caller's result-cache key, so it has to change
    when the join around the branches changes and not only when a branch
    does."""
    import hashlib

    plan = _composed()

    assert plan.fingerprint == hashlib.sha256(plan.sql.encode("utf-8")).hexdigest()
    # The branches are CTEs of one statement, not two statements a caller
    # would have to run in order.
    assert plan.sql.startswith("WITH branch_0 AS (")
    assert plan.sql.count("LEFT JOIN branch_") == len(plan.marts)


def test_the_key_keeps_the_requested_name_when_no_branch_spells_it_that_way() -> None:
    """The case the three-measure test above cannot see, and a sabotage sweep
    found: with `customers` among the branches the first branch calls the
    dimension `tier` already, so taking the first branch's spelling and taking
    the requested name are the same string, and a planner doing the first
    passes a test written for the second.

    Two branches, and neither spells it `tier`: `order_items` reaches it as
    `order_customer_tier` two hops away and `orders` as `customer_tier` one
    hop away. The caller asked for `tier` (logs/T-0026.md, D-165).
    """
    plan = make_planner().plan(
        fixture_ir("cross_mart_branches"),
        MetricRequest(metrics=("shipping_count", "line_discount"), dimensions=("tier",)),
        dialect="duckdb",
    )

    assert plan.marts == ("order_items", "orders")
    assert [column.name for column in plan.columns][0] == "tier"
    assert "AS tier" in plan.sql


def test_a_date_role_is_answered_under_its_effective_name() -> None:
    """D-169, the exception to D-165, exercised where it decides something.

    A request for `ordered_day` under a monthly `time_grain` is answered by a
    single-mart plan under `ordered_month`, and answering a composed one under
    the string the caller typed would print a monthly number beneath a daily
    name. Every branch agrees on the effective name, because two marts
    reaching one date column under different roles have different provenance
    and D12 refuses them before a name has to be chosen.

    Built from resolutions rather than from a fixture: the marts that would
    share a date role by provenance are two marts on one base entity, and the
    rule under test is a naming rule the resolutions already carry.
    """
    from bloomery.planner.coverage import Coverage, composed_keys
    from bloomery.planner.names import ResolvedDimension
    from bloomery.planner.request import TimeGrain

    ir = fixture_ir("cross_mart_branches")
    marts = {mart.name: mart for mart in ir.marts}
    resolved = ResolvedDimension(name="ordered_month", role="ordered", grain=TimeGrain.MONTH)
    branches = tuple(
        Coverage(
            mart=marts[name],
            dimensions=(resolved,),
            filter_dimensions=(),
            policy_dimension=None,
            metrics=(),
        )
        for name in ("order_items", "orders")
    )

    keys = composed_keys(
        MetricRequest(metrics=("shipping_count",), dimensions=("ordered_day",)), branches
    )

    assert keys == ("ordered_month",)


def test_a_metric_named_like_a_rebucketed_dimension_is_refused() -> None:
    """The collision guard reads the name the *result* carries, not the one
    the request typed. A metric called `ordered_month` and a request for
    `ordered_day` under a monthly grain never share a string until the key is
    resolved, and then they name one column twice.
    """
    from bloomery.planner.coverage import Coverage, composed_keys
    from bloomery.planner.names import ResolvedDimension
    from bloomery.planner.request import TimeGrain

    ir = fixture_ir("cross_mart_branches")
    marts = {mart.name: mart for mart in ir.marts}
    resolved = ResolvedDimension(name="ordered_month", role="ordered", grain=TimeGrain.MONTH)
    branches = tuple(
        Coverage(
            mart=marts[name],
            dimensions=(resolved,),
            filter_dimensions=(),
            policy_dimension=None,
            metrics=(),
        )
        for name in ("order_items", "orders")
    )
    request = MetricRequest(metrics=("ordered_month",), dimensions=("ordered_day",))

    keys = composed_keys(request, branches)

    # Nothing collides between what was typed; everything collides between
    # what comes back, which is what the precheck now compares.
    assert not set(request.metrics) & set(request.dimensions)
    assert set(request.metrics) & set(keys) == {"ordered_month"}


def test_a_time_grain_with_nothing_to_apply_to_warns_on_a_composed_plan_too() -> None:
    """The warning a single-mart plan already carries, on the path that
    rebuilds its own warnings: a `time_grain` is a re-bucketing instruction,
    and a request with no date-role dimension gives it nothing to re-bucket."""
    from bloomery.planner import TimeGrain

    plan = make_planner().plan(
        fixture_ir("cross_mart_branches"),
        MetricRequest(
            metrics=("shipping_count", "line_discount"),
            dimensions=("tier",),
            time_grain=TimeGrain.MONTH,
        ),
        dialect="duckdb",
    )

    assert any("has no date-role dimension" in warning for warning in plan.warnings)



# ....................... #
# RFC 0041 P2: computation above the join.


def _computed(metric: str):
    return make_planner().plan(
        fixture_ir("cross_mart_branches"),
        MetricRequest(metrics=(metric,), dimensions=("tier",)),
        dialect="duckdb",
    )


@pytest.mark.parametrize(
    ("metric", "operator"),
    [("discount_per_order", "/ NULLIF("), ("discount_less_orders", " - ")],
)
def test_a_metric_whose_components_split_is_computed_above_the_join(
    metric: str, operator: str
) -> None:
    """RFC 0041 D3 and D1 together: the operands are aggregated in their own
    branches and combined afterwards, because `SUM(a)/SUM(b)` and a row-level
    `a/b` summed afterwards are different numbers.

    Both shapes P2 admits — a ratio with the spelling §13a fixes, and the
    RFC 0034 ``derived:`` expression the same phase reaches (logs/T-0027.md,
    D-179). The branches were asked for the **components**; the requested name
    exists only in the composed projection.
    """
    plan = _computed(metric)
    # The composed SELECT is the last one at column zero: every branch body
    # sits inside a CTE above it, and the key domain's SELECTs are indented.
    branch_sql, _, composed = plan.sql.rpartition("\nSELECT\n")

    assert plan.marts == ("order_items", "orders")
    assert operator in composed
    assert metric not in branch_sql, "a branch was asked for the computed metric itself"
    assert [column.name for column in plan.columns] == ["tier", metric]


def test_a_computed_metric_is_described_though_no_branch_produced_it() -> None:
    """It belongs to no mart, so no branch's column envelope or explanation
    carries it — and a caller binding the result still needs both."""
    plan = _computed("discount_per_order")
    column = plan.columns[-1]
    rendered = plan.explanation.render()

    assert (column.name, column.sql_alias, column.role) == (
        "discount_per_order",
        "discount_per_order",
        "measure",
    )
    assert "discount_per_order = line_discount / shipping_count" in rendered
    assert "line_discount = SUM" not in rendered, "the components are not what was asked for"


def test_a_computed_metric_is_stated_above_the_join() -> None:
    """RFC 0041 D3 says where the arithmetic happens, and §4's node vocabulary
    had nowhere to say it — so the plan was withheld rather than claim the join
    produced a column it does not (logs/T-0027.md, D-178).

    `Compute` is that node (RFC 0066 §5.2), and it sits above the join for the
    same reason it sits above an aggregate: the operands are reduced first and
    the expression is evaluated over the result.

    Paired with the stored-measure request so the assertion cannot pass because
    composed plans are never stated at all.
    """
    plan = _computed("discount_per_order").semantic

    assert plan is not None
    assert plan.shape == ("join_aggregates", "compute", "project")

    (compute,) = [node for node in plan.nodes if isinstance(node, Compute)]
    assert [name for name, _expr in compute.outputs] == ["discount_per_order"]
    assert (proof := compute.proof) is not None
    assert proof.rule == "R014"

    assert (
        make_planner()
        .plan(
            fixture_ir("cross_mart_branches"),
            MetricRequest(metrics=("shipping_count", "line_discount"), dimensions=("tier",)),
            dialect="duckdb",
        )
        .semantic
        is not None
    )


def test_a_filter_reaches_each_branch_in_that_branchs_own_spelling() -> None:
    """RFC 0041 D12 applied to a restriction: `region` is `region` on the mart
    based at `order` and `order_region` on the one that flattened its way
    there, and both are the same column. Placing the requested spelling on both
    would refuse one branch; placing a same-named column on both would be the
    name match D5 refuses."""
    plan = make_planner().plan(
        fixture_ir("cross_mart_branches"),
        MetricRequest(
            metrics=("shipping_count", "line_discount"),
            dimensions=("tier",),
            filters=(Predicate(dimension="region", op=Op.EQ, values=("EU",)),),
        ),
        dialect="duckdb",
    )

    assert "WHERE order__region = 'EU'" in plan.sql
    assert "WHERE order_item__order_region = 'EU'" in plan.sql
    assert plan.explanation.render().count("region = 'EU'") == 1, (
        "one filter reached every branch; the explanation reports the request's account"
    )


def test_each_branch_plan_names_the_column_that_branch_restricts() -> None:
    """A `SemanticPlan` is lowered, not shown, so its predicates have to name
    the columns the branch actually filters.

    The merged explanation speaks the *requested* spelling, which is right for
    a reader and wrong here: a branch whose `Filter` said `region` while its
    scan restricts `order_region` lowers into a predicate on a column that
    relation does not have. The `Aggregate` beside it already named the
    branch-local column, so the plan contradicted itself — which is the
    evidence, and which the self-audit missed (logs/T-0027.md, finding 7).
    """
    plan = make_planner().plan(
        fixture_ir("cross_mart_branches"),
        MetricRequest(
            metrics=("shipping_count", "line_discount"),
            dimensions=("tier",),
            filters=(Predicate(dimension="region", op=Op.EQ, values=("EU",)),),
        ),
        dialect="duckdb",
        policy=RowPolicy("region", Op.NE, "UK"),
    )
    assert plan.semantic is not None
    join = plan.semantic.nodes[0]
    by_relation = {
        next(node.relation for node in branch.plan.nodes if isinstance(node, Scan)): next(
            node.predicates for node in branch.plan.nodes if isinstance(node, Filter)
        )
        for branch in join.branches  # type: ignore[attr-defined]
    }

    assert by_relation == {
        "order_items": ("order_region != 'UK'", "order_region = 'EU'"),
        "orders": ("region != 'UK'", "region = 'EU'"),
    }
    # And each name is the column its own branch actually restricts — the two
    # branches render the same clause against differently-spelled columns,
    # which is the whole reason the plan may not speak one spelling for both.
    assert "order_item__order_region = 'EU'" in plan.sql
    assert "order__region = 'EU'" in plan.sql
