"""Coverage precheck unit tests (RFC 0013 R3, RFC 0011 D3): every refusal
branch — unknown members with suggestions, zero/split mart candidates with
the R3 message shape, ownership tie-breaks, dimension resolution including
role ambiguity and the time-grain interplay."""

from __future__ import annotations

from dataclasses import replace

import pytest

from bloomery import MetricRequest, RowPolicy
from bloomery.errors import (
    AmbiguousDimension,
    InvalidRequest,
    UnknownMember,
    UnreachableAtGrain,
)
from bloomery.ir import Cardinality, ProjectIR
from bloomery.naming import DefaultNaming
from bloomery.planner import TimeGrain
from bloomery.planner.coverage import _carried_elsewhere, _hops, _origin, check, resolve_request
from bloomery.planner.names import ResolvedDimension
from bloomery.planner.request import AnyOf, Op, Predicate
from bloomery.semantic import BASIS_PROVENANCE, RefusalReason
from support.planning import fixture_ir

pytestmark = pytest.mark.unit

NAMING = DefaultNaming()


def _check(ir: ProjectIR, request: MetricRequest) -> str:
    return check(ir, request, naming=NAMING)


# ....................... #
# Metric validation (step 1)


def test_unknown_metric_gets_a_suggestion() -> None:
    with pytest.raises(UnknownMember, match="did you mean 'revenue'"):
        _check(fixture_ir("non_additive_aov"), MetricRequest(metrics=("revenu",)))


def test_unknown_metric_without_close_match_lists_known() -> None:
    with pytest.raises(UnknownMember, match="known"):
        _check(fixture_ir("non_additive_aov"), MetricRequest(metrics=("zzz",)))


def test_unreachable_metric_names_its_missing_leaves() -> None:
    # ecom_basic's `margin` requires the deliberately unmapped `cogs`.
    with pytest.raises(UnknownMember, match="unreachable.*cogs"):
        _check(fixture_ir("ecom_basic"), MetricRequest(metrics=("margin",)))


# ....................... #
# Mart selection (step 2) — 0 / 1 / N and splits


def test_single_mart_is_selected() -> None:
    assert _check(fixture_ir("semi_additive_inventory"), MetricRequest(("stock_on_hand",))) == (
        "inventory"
    )


def test_ratio_resolves_through_its_components() -> None:
    assert _check(fixture_ir("non_additive_aov"), MetricRequest(("average_order_value",))) == (
        "orders"
    )


def test_metric_on_no_mart_is_unreachable() -> None:
    # ecom_basic declares order_count but no mart lists it as a measure.
    with pytest.raises(UnreachableAtGrain, match="served by no mart"):
        _check(fixture_ir("ecom_basic"), MetricRequest(metrics=("order_count",)))


def test_unservable_ratio_names_the_missing_component() -> None:
    # average_order_value = gross_revenue / order_count; order_count is martless.
    with pytest.raises(UnreachableAtGrain, match="component of the requested ratio"):
        _check(fixture_ir("ecom_basic"), MetricRequest(metrics=("average_order_value",)))


def test_split_measures_refuse_with_the_r3_message() -> None:
    with pytest.raises(UnreachableAtGrain) as excinfo:
        _check(
            fixture_ir("multi_mart_refusal"),
            MetricRequest(metrics=("shipping_cost", "line_discount")),
        )
    message = str(excinfo.value)
    assert "live on different grains" in message
    assert "grain: order " in message or "grain: order (" in message
    assert "grain: order_item" in message
    assert "gold.mart_orders" in message
    assert "gold.mart_order_items" in message
    assert "double-count" in message
    assert "Request them separately" in message
    assert "define a mart at the shared grain" in message


def test_ownership_prefers_cheapest_cost_hint_then_name() -> None:
    """The RFC 0010 D8 rule, shared verbatim with the emitter: cheapest
    ``cost_hint`` wins; ties break lexicographic by mart name."""
    ir = fixture_ir("multi_mart_refusal")
    orders = next(m for m in ir.marts if m.name == "orders")
    # A second mart also carrying shipping_cost, cheaper — it must win.
    cheaper = replace(orders, name="orders_lite", cost_hint=0)
    with_cheaper = replace(ir, marts=tuple(sorted((*ir.marts, cheaper), key=lambda m: m.name)))
    assert _check(with_cheaper, MetricRequest(("shipping_cost",))) == "orders_lite"
    # Same cost: lexicographic tie-break — "orders" < "orders_lite".
    tied = replace(cheaper, cost_hint=orders.cost_hint)
    with_tie = replace(ir, marts=tuple(sorted((*ir.marts, tied), key=lambda m: m.name)))
    assert _check(with_tie, MetricRequest(("shipping_cost",))) == "orders"


# ....................... #
# Dimension resolution (step 3)


def test_unknown_dimension_gets_a_suggestion() -> None:
    request = MetricRequest(metrics=("stock_on_hand",), dimensions=("warehouse",))
    with pytest.raises(UnknownMember, match="did you mean 'warehouse_id'"):
        _check(fixture_ir("semi_additive_inventory"), request)


def test_filter_dimension_must_be_on_the_covering_mart() -> None:
    request = MetricRequest(
        metrics=("stock_on_hand",), filters=(Predicate("nonexistent", Op.EQ, ("x",)),)
    )
    with pytest.raises(UnknownMember, match="nonexistent"):
        _check(fixture_ir("semi_additive_inventory"), request)


def test_every_any_of_member_dimension_must_resolve() -> None:
    # RFC 0015 D-Q3: an AnyOf group resolves every member's dimension.
    clause = AnyOf(
        (Predicate("warehouse_id", Op.EQ, ("A",)), Predicate("nonexistent", Op.EQ, ("x",)))
    )
    request = MetricRequest(metrics=("stock_on_hand",), filters=(clause,))
    with pytest.raises(UnknownMember, match="nonexistent"):
        _check(fixture_ir("semi_additive_inventory"), request)


def test_filter_dimensions_group_per_clause() -> None:
    clause = AnyOf(
        (Predicate("warehouse_id", Op.EQ, ("A",)), Predicate("stock_level", Op.GT, (10,)))
    )
    resolved = resolve_request(
        fixture_ir("semi_additive_inventory"),
        MetricRequest(
            metrics=("stock_on_hand",),
            filters=(Predicate("warehouse_id", Op.EQ, ("B",)), clause),
        ),
        naming=NAMING,
    )
    assert resolved.filter_dimensions == (
        (ResolvedDimension(name="warehouse_id"),),
        (ResolvedDimension(name="warehouse_id"), ResolvedDimension(name="stock_level")),
    )


def test_policy_dimension_must_be_on_the_covering_mart() -> None:
    with pytest.raises(UnknownMember, match="tenant_key"):
        resolve_request(
            fixture_ir("semi_additive_inventory"),
            MetricRequest(metrics=("stock_on_hand",)),
            naming=NAMING,
            policy=RowPolicy("tenant_key", "eq", "acme"),
        )


def test_unqualified_bucket_with_one_role_resolves() -> None:
    resolved = resolve_request(
        fixture_ir("semi_additive_inventory"),
        MetricRequest(metrics=("stock_on_hand",), dimensions=("month",)),
        naming=NAMING,
    )
    assert resolved.dimensions == (
        ResolvedDimension(name="snapshot_month", role="snapshot", grain=TimeGrain.MONTH),
    )


def test_unqualified_bucket_with_two_roles_is_ambiguous() -> None:
    request = MetricRequest(metrics=("revenue",), dimensions=("month",))
    with pytest.raises(
        AmbiguousDimension,
        match=r"'month' has roles \['ordered', 'shipped'\]. "
        r"Use 'ordered_month' or 'shipped_month'\.",
    ):
        _check(fixture_ir("role_playing_dates"), request)


def test_time_grain_rebuckets_requested_date_dimensions() -> None:
    resolved = resolve_request(
        fixture_ir("role_playing_dates"),
        MetricRequest(
            metrics=("revenue",), dimensions=("ordered_day",), time_grain=TimeGrain.QUARTER
        ),
        naming=NAMING,
    )
    assert resolved.dimensions == (
        ResolvedDimension(name="ordered_quarter", role="ordered", grain=TimeGrain.QUARTER),
    )


def test_time_grain_leaves_filter_dimensions_alone() -> None:
    resolved = resolve_request(
        fixture_ir("role_playing_dates"),
        MetricRequest(
            metrics=("revenue",),
            dimensions=("ordered_day",),
            filters=(Predicate("shipped_day", Op.EQ, ("2024-01-01",)),),
            time_grain=TimeGrain.MONTH,
        ),
        naming=NAMING,
    )
    assert resolved.filter_dimensions == (
        (ResolvedDimension(name="shipped_day", role="shipped", grain=TimeGrain.DAY),),
    )


def test_hour_grain_has_no_bucket_and_is_refused() -> None:
    request = MetricRequest(
        metrics=("revenue",), dimensions=("ordered_day",), time_grain=TimeGrain.HOUR
    )
    with pytest.raises(InvalidRequest, match="hour"):
        _check(fixture_ir("role_playing_dates"), request)


def test_categorical_dimensions_ignore_time_grain() -> None:
    resolved = resolve_request(
        fixture_ir("non_additive_aov"),
        MetricRequest(metrics=("revenue",), dimensions=("store",), time_grain=TimeGrain.MONTH),
        naming=NAMING,
    )
    assert resolved.dimensions == (ResolvedDimension(name="store"),)


# ....................... #
# Derived metrics (RFC 0034 §8)


def test_a_derived_metric_resolves_to_the_mart_carrying_its_inputs() -> None:
    """It has no measure of its own, so coverage follows the decomposition —
    exactly as it does for a ratio (RFC 0011 D5)."""
    assert check(
        fixture_ir("period_over_period"),
        MetricRequest(metrics=("revenue_yoy",), dimensions=("sold_month",)),
        naming=NAMING,
    ) == "sales"


def test_a_derived_metric_needs_its_input_measure_served() -> None:
    """The refusal names the *input*, not the derived metric — the fix is a
    mart carrying the input, and naming the wrapper would route to the wrong
    document."""
    ir = fixture_ir("period_over_period")
    stripped = replace(
        ir,
        marts=tuple(
            replace(mart, measures=tuple(m for m in mart.measures if m != "revenue"))
            for mart in ir.marts
        ),
    )
    with pytest.raises(UnreachableAtGrain) as excinfo:
        check(
            stripped,
            MetricRequest(metrics=("revenue_yoy",), dimensions=("sold_month",)),
            naming=NAMING,
        )

    assert "metric 'revenue'" in str(excinfo.value)
    assert "requested derived metric 'revenue_yoy'" in str(excinfo.value)


def test_one_input_named_twice_is_required_once() -> None:
    """`revenue_yoy` reads `revenue` at two offsets. The offsets are
    MetricFlow's to render; coverage needs the measure once, and a second
    entry would make a single-mart request look like a two-mart one."""
    ir = fixture_ir("period_over_period")
    yoy = next(metric for metric in ir.metrics if metric.name == "revenue_yoy")

    assert [input_.metric for input_ in yoy.derived.inputs] == ["revenue", "revenue"]
    assert check(
        ir,
        MetricRequest(metrics=("revenue_yoy", "revenue"), dimensions=("sold_month",)),
        naming=NAMING,
    ) == "sales"


def test_a_cumulative_metric_requires_its_own_measure() -> None:
    assert check(
        fixture_ir("period_over_period"),
        MetricRequest(metrics=("revenue_mtd",), dimensions=("sold_day",)),
        naming=NAMING,
    ) == "sales"


# ----------------------- #
# A dimension another mart carries (RFC 0040 §11a P2)


def test_a_dimension_on_another_mart_is_not_an_unknown_one() -> None:
    """`UnknownMember` says the name does not exist, and for this request that
    is false in the one way an author acts on: it sends them to declare a
    dimension the project already declares. `region` is on mart `orders`; what
    is missing is the hop onto `order_items`, not the dimension.
    """
    with pytest.raises(UnreachableAtGrain) as excinfo:
        check(
            fixture_ir("unflattened_hop"),
            MetricRequest(metrics=("line_discount",), dimensions=("region",)),
            naming=NAMING,
        )

    assert excinfo.value.refusal_reason == "not_flattened"
    assert "mart 'orders' carries it at grain 'order'" in str(excinfo.value)


def test_a_provable_hop_is_refused_by_naming_the_spec_edit() -> None:
    """The deliverable of this phase. The rollup from `order_item` to `order`
    is provable, so the gap is one line of spec, and the refusal names that
    line rather than guessing a nearest column name.

    It stays a refusal: P2 adds no capability (RFC 0040 D9), and bloomery does
    not join at plan time — the join belongs to the mart, proven once when it
    is built instead of re-decided per request.
    """
    with pytest.raises(UnreachableAtGrain) as excinfo:
        check(
            fixture_ir("unflattened_hop"),
            MetricRequest(metrics=("line_discount",), dimensions=("region",)),
            naming=NAMING,
        )

    assert "add `flatten: {via: item_of_order}` to mart 'order_items'" in str(excinfo.value)


def test_an_unprovable_hop_carries_the_rollup_refusal_that_explains_it() -> None:
    """`multi_mart_refusal` declares no relationship at all, so the same shape
    of request gets a different diagnosis — and the difference is the whole
    point of asking the prover rather than reporting "not on this mart".

    The reason code is RFC 0037's own, not a planner invention: a caller that
    wants to branch on why gets the vocabulary that already answers it.
    """
    with pytest.raises(UnreachableAtGrain) as excinfo:
        check(
            fixture_ir("multi_mart_refusal"),
            MetricRequest(metrics=("line_discount",), dimensions=("ship_cost",)),
            naming=NAMING,
        )

    assert excinfo.value.refusal_reason == RefusalReason.NO_FUNCTIONAL_PATH
    assert "cannot be rolled up" in str(excinfo.value)
    assert "declare a relationship connecting the two entities" in str(excinfo.value)


def test_the_reason_code_round_trips_through_the_semantic_vocabulary() -> None:
    """`refusal_reason` is the `RefusalReason` *value*, because `errors` is the
    bottom layer and the semantic vocabulary sits above it. The round trip is
    what makes storing a bare string honest rather than lossy."""
    with pytest.raises(UnreachableAtGrain) as excinfo:
        check(
            fixture_ir("multi_mart_refusal"),
            MetricRequest(metrics=("line_discount",), dimensions=("ship_cost",)),
            naming=NAMING,
        )

    assert RefusalReason(excinfo.value.refusal_reason) is RefusalReason.NO_FUNCTIONAL_PATH


def test_a_name_no_mart_carries_is_still_an_unknown_member() -> None:
    """The control, and the boundary this phase must not cross. A name that
    exists nowhere is genuinely unknown, keeps its class and keeps its
    did-you-mean — nothing here converts a refusal that was already correct.
    """
    with pytest.raises(UnknownMember) as excinfo:
        check(
            fixture_ir("unflattened_hop"),
            MetricRequest(metrics=("line_discount",), dimensions=("nonsense",)),
            naming=NAMING,
        )

    assert excinfo.value.did_you_mean is None


def test_a_measure_refusal_carries_no_dimension_reason() -> None:
    """`UnreachableAtGrain` covers two situations now, and `refusal_reason`
    empty is what says which. A measure-coverage refusal answers with
    `covering_marts`; reporting a dimension code there would be a value nobody
    computed."""
    with pytest.raises(UnreachableAtGrain) as excinfo:
        check(
            fixture_ir("multi_mart_refusal"),
            MetricRequest(metrics=("line_discount", "shipping_cost")),
            naming=NAMING,
        )

    assert excinfo.value.refusal_reason == ""
    assert excinfo.value.covering_marts != ()


def test_two_routes_to_the_same_entity_name_neither() -> None:
    """A remediation that names a relationship the author must write into
    their mart is only useful if it is the right one. With two routes there is
    no right one to name, and guessing sends them to write the wrong line — so
    the message says to flatten the hop and leaves the choice where it belongs.

    Asked of `_hop` directly: no fixture declares two relationships between one
    pair of entities, and one written to would be a fixture whose only reader
    is this test.
    """
    ir = fixture_ir("unflattened_hop")
    (declared,) = [
        relationship for relationship in ir.relationships if relationship.name == "item_of_order"
    ]
    doubled = replace(
        ir, relationships=(*ir.relationships, replace(declared, name="also_item_of_order"))
    )

    assert _hops(ir, "order_item", "order") == ("item_of_order",)
    assert _hops(doubled, "order_item", "order") == ()


def test_the_mart_a_refusal_names_does_not_depend_on_iteration_order() -> None:
    """Two marts may carry the same dimension, and the message names one. RFC
    0003 makes that a sorted choice rather than whichever the IR listed first —
    a refusal two runs disagree about is a refusal nobody can quote."""
    ir = fixture_ir("unflattened_hop")
    (serving,) = [mart for mart in ir.marts if mart.name == "order_items"]
    (carrying,) = [mart for mart in ir.marts if mart.name == "orders"]
    also = replace(carrying, name="aaa_orders")

    forward = replace(ir, marts=(serving, carrying, also))
    backward = replace(ir, marts=(serving, also, carrying))

    assert _carried_elsewhere(forward, serving, "region")[0].name == "aaa_orders"
    assert _carried_elsewhere(backward, serving, "region")[0].name == "aaa_orders"


def test_no_rollup_basis_carries_a_provenance_that_leaves_a_proof_open() -> None:
    """Why `_not_here` tests `answer.closed` and no fixture can reach the
    branch: every basis a rollup proof rests on is `DECLARED` or `DERIVED`, so
    `prove_rollup` cannot return an unclosed proof today.

    The guard is not decoration. RFC 0044 is about imported provenance, and the
    first basis that arrives as `IMPORTED_VERIFIED` or `INFERRED_HEURISTIC`
    makes an open proof reachable — at which point "provable, just flatten it"
    would be said about a heuristic. This fails then, which is where someone
    decides whether that still counts as safe.
    """
    assert all(provenance.closes for provenance in BASIS_PROVENANCE.values())


def test_a_grain_this_project_maps_no_entity_for_states_that_much() -> None:
    """A quality mart's grain is not an entity — it is the run itself — so
    there is no rollup to state between it and a fact mart, and the refusal
    says which of the two grains it could not place.

    Found by the audit: the branch is reachable in four fixtures and no test
    ran it. What made it easy to miss is that it needs a dimension of the
    *other* mart, and reaching for a plausible name lands on `UnknownMember`
    instead — the path only opens for a column that really is over there.
    """
    with pytest.raises(UnreachableAtGrain) as excinfo:
        check(
            fixture_ir("quality_precedence"),
            MetricRequest(metrics=("line_amount_total",), dimensions=("disposition",)),
            naming=NAMING,
        )

    assert excinfo.value.refusal_reason == RefusalReason.UNKNOWN_GRAIN
    assert "maps no entity for one of those grains" in str(excinfo.value)


def test_the_proof_target_is_the_dimension_s_own_entity() -> None:
    """A flattened column came from an entity, and that entity — not the
    carrying mart's grain — is what a rollup question about it is about.

    `order_items` carries `order_customer_id` from `order`. Ask the carrier's
    grain instead and a second mart at the requester's own grain would prove a
    reflexive rollup and report "safe, just flatten it" about a hop nobody
    proved (logs/T-0022.md, D-139).
    """
    ir = fixture_ir("ecom_basic")
    (mart,) = ir.marts

    assert _origin(mart, "order_customer_id") == "order"
    assert _origin(mart, "line_no") == mart.grain


def test_a_filter_naming_a_dimension_elsewhere_refuses_the_same_way() -> None:
    """Filters resolve through the same function as group-bys, so they inherit
    the diagnosis — and should: a filter on a column another mart carries has
    the same cause and the same one-line repair (logs/T-0022.md, D-138)."""
    with pytest.raises(UnreachableAtGrain) as excinfo:
        check(
            fixture_ir("unflattened_hop"),
            MetricRequest(
                metrics=("line_discount",),
                filters=(Predicate(dimension="region", op=Op.EQ, values=("eu",)),),
            ),
            naming=NAMING,
        )

    assert excinfo.value.refusal_reason == "not_flattened"


def test_a_row_policy_naming_a_dimension_elsewhere_refuses_the_same_way() -> None:
    """And the policy path, which resolves its dimension through the same
    function. A policy that cannot be applied must refuse rather than plan
    without it, and the class it refuses with is the one that says why."""
    with pytest.raises(UnreachableAtGrain) as excinfo:
        resolve_request(
            fixture_ir("unflattened_hop"),
            MetricRequest(metrics=("line_discount",)),
            naming=NAMING,
            policy=RowPolicy(dimension="region", op=Op.EQ, value="eu"),
        )

    assert excinfo.value.refusal_reason == "not_flattened"


def test_a_carried_dimension_is_proven_to_its_own_entity_not_its_carriers_grain() -> None:
    """`customer_tier` is carried by `orders`, a mart at `order` grain, and it
    originates at `customer`. The refusal must be about reaching `customer`.

    End to end rather than through `_origin` alone: with the carrier's grain as
    the target this proves `order_item -> order`, which holds, and the message
    would offer a `flatten` that does not bring the column (logs/T-0022.md,
    D-139).
    """
    with pytest.raises(UnreachableAtGrain) as excinfo:
        check(
            fixture_ir("unflattened_hop"),
            MetricRequest(metrics=("line_discount",), dimensions=("customer_tier",)),
            naming=NAMING,
        )

    assert "flattened from 'customer'" in str(excinfo.value)
    assert "roll up to 'customer'" in str(excinfo.value)


def test_a_one_to_many_is_never_named_as_the_flatten_to_add() -> None:
    """Provable and flattenable are different questions, and the remediation
    answers the second.

    RFC 0037 admits a `one_to_many` **only inversely**, so a rollup can hold
    across the reverse of one — while the mart flattener refuses to flatten it
    at all ("flattening it multiplies the mart's own rows once per row"). Name
    it and the author writes a line the compiler rejects (logs/T-0022.md,
    D-140).
    """
    ir = fixture_ir("unflattened_hop")
    (declared,) = [
        relationship for relationship in ir.relationships if relationship.name == "item_of_order"
    ]
    fanning = replace(
        ir,
        relationships=tuple(
            replace(relationship, cardinality=Cardinality.ONE_TO_MANY)
            if relationship.name == "item_of_order"
            else relationship
            for relationship in ir.relationships
        ),
    )

    assert declared.cardinality is Cardinality.MANY_TO_ONE
    assert _hops(ir, "order_item", "order") == ("item_of_order",)
    assert _hops(fanning, "order_item", "order") == ()


def test_a_transitive_hop_names_every_flatten_in_order() -> None:
    """Marts flatten transitively, so reaching `customer` from `order_item` is
    two `flatten:` lines and not a missing relationship.

    The fallback used to tell the author to declare a direct
    `order_item -> customer` edge they can already reach by composition —
    redundant modelling, prescribed by a message meant to save them work
    (logs/T-0022.md, D-141).
    """
    with pytest.raises(UnreachableAtGrain) as excinfo:
        check(
            fixture_ir("unflattened_hop"),
            MetricRequest(metrics=("line_discount",), dimensions=("customer_tier",)),
            naming=NAMING,
        )

    assert "`flatten: {via: item_of_order}` then `flatten: {via: order_of_customer}`" in str(
        excinfo.value
    )
    assert "declare a many_to_one" not in str(excinfo.value)


def test_the_chain_is_the_shortest_one_and_only_when_it_is_unique() -> None:
    """Shortest, so a route that composes is preferred to one that detours;
    unique, so two equally short routes name neither. Both matter for the same
    reason the single-edge case did: a remediation the author cannot trust is
    worse than one that admits it does not know."""
    ir = fixture_ir("unflattened_hop")
    (direct,) = [
        relationship for relationship in ir.relationships if relationship.name == "item_of_order"
    ]
    shortcut = replace(direct, name="item_of_customer", to_entity="customer")

    assert _hops(ir, "order_item", "customer") == ("item_of_order", "order_of_customer")
    assert _hops(replace(ir, relationships=(*ir.relationships, shortcut)), "order_item", "customer") == (
        "item_of_customer",
    )


def test_a_dimension_from_this_marts_own_grain_asks_for_no_relationship() -> None:
    """The identity rollup proves trivially and involves no relationship, so
    the chain logic had nothing to name and told the author to declare an edge
    from an entity to itself.

    Reachable whenever another mart flattens a join to the entity this mart is
    built from: the prefix gives one column two names. The remedy is the local
    spelling, not a relationship (logs/T-0022.md, D-142).
    """
    ir = fixture_ir("ecom_basic")
    (items,) = ir.marts
    (foreign,) = [c for c in items.columns if c.name == "order_customer_id"]
    slim = replace(
        items,
        name="slim_orders",
        grain="order",
        dimensions=tuple(d for d in items.dimensions if d.column != "order_customer_id"),
        # The same source column is flattened here under another name and is
        # *not* a dimension — a join key never doubles as one. Naming it would
        # answer the refusal with a request that is refused too.
        columns=(
            *(c for c in items.columns if c.name != "order_customer_id"),
            replace(foreign, name="customer_id"),
        ),
    )
    # `slim_orders` owns the measure, so it is the mart serving the request;
    # `order_items` keeps its dimensions and is the one carrying the column.
    project = replace(ir, marts=(slim, replace(items, measures=())))

    with pytest.raises(UnreachableAtGrain) as excinfo:
        check(
            project,
            MetricRequest(metrics=("gross_revenue",), dimensions=("order_customer_id",)),
            naming=NAMING,
        )

    assert excinfo.value.refusal_reason == "not_flattened"
    assert "no relationship is involved" in str(excinfo.value)
    assert "relationship from 'order' to 'order'" not in str(excinfo.value)
    assert "expose it on mart 'slim_orders'" in str(excinfo.value)


def test_the_same_column_under_another_name_is_named() -> None:
    """The half that turns a refusal into a corrected request. A flattened join
    prefixes what it brings, so one underlying column sits on two marts under
    two names, and the caller reached for the wrong one.

    Only names this mart exposes as dimensions: a mart may flatten a column
    without making it requestable — join keys never double as one — and naming
    one of those would answer a refusal with a request that is refused too.
    """
    ir = fixture_ir("ecom_basic")
    (items,) = ir.marts
    (foreign,) = [c for c in items.columns if c.name == "order_customer_id"]
    local = replace(foreign, name="customer_id")
    (foreign_dimension,) = [d for d in items.dimensions if d.column == "order_customer_id"]
    slim = replace(
        items,
        name="slim_orders",
        grain="order",
        columns=(*(c for c in items.columns if c.name != "order_customer_id"), local),
        dimensions=(
            *(d for d in items.dimensions if d.column != "order_customer_id"),
            replace(foreign_dimension, column="customer_id"),
        ),
    )
    project = replace(ir, marts=(slim, replace(items, measures=())))

    with pytest.raises(UnreachableAtGrain) as excinfo:
        check(
            project,
            MetricRequest(metrics=("gross_revenue",), dimensions=("order_customer_id",)),
            naming=NAMING,
        )

    assert "ask for 'customer_id' instead" in str(excinfo.value)


def test_the_chain_walk_holds_two_routes_at_most() -> None:
    """The question is "exactly one route or not", so a second witness answers
    it and every further one is a route nobody reads.

    Keeping them all is the textbook way to turn a breadth-first search into an
    exponential one: `seen` prevents revisiting *between* levels, not within,
    so a diamond doubles the paths held at each level. Two diamonds in series
    is four routes, and the answer — ambiguous, name none — is the same one two
    witnesses give (logs/T-0022.md, D-143).
    """
    ir = fixture_ir("unflattened_hop")
    (direct,) = [
        relationship for relationship in ir.relationships if relationship.name == "item_of_order"
    ]
    diamond = (
        *ir.relationships,
        replace(direct, name="item_of_order_alt"),
        replace(direct, name="order_of_customer_alt", from_entity="order", to_entity="customer"),
    )

    assert _hops(replace(ir, relationships=diamond), "order_item", "customer") == ()
    assert _hops(ir, "order_item", "customer") == ("item_of_order", "order_of_customer")
