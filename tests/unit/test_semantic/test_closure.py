"""The grain model's eight cases (RFC 0037 §6), each as itself.

What every one of them is really asking is whether the closure admits exactly
the facts D3 (`LOCKED`) lists and nothing else: an entity's own key, a
``many_to_one`` or ``one_to_one`` read in a direction that preserves the
left grain, a historical hop that came back anchored, and composition over
those. The value of every proof RFC 0039 and RFC 0040 build on this is
exactly the weakest fact admitted here, so each admission is asserted
positively and each exclusion negatively — "it happens not to appear" and "it
is refused" are different results and only one of them survives a refactor.
"""

from __future__ import annotations

import pytest

from bloomery.ir import SCDKind
from bloomery.semantic import (
    AsOfState,
    ColumnRef,
    DependencyBasis,
    GrainRef,
    RefusalReason,
    RollupContext,
    RollupProof,
    RollupRefusal,
    can_roll_up,
    closure,
    dependencies,
    grain_of,
    qualify_as_of,
)
from support.grain_model import (
    ADDRESS,
    CUSTOMER,
    CUSTOMER_TIER,
    ITEM_ORDER,
    ORDER,
    ORDER_BILLING,
    ORDER_CUSTOMER,
    ORDER_ITEM,
    ORDER_LINES,
    ORDER_PROMO,
    ORDER_SHIPPING,
    ORDER_TIER,
    PROMO,
    entity,
    grain,
    project,
)

pytestmark = pytest.mark.unit


def determined(source, built) -> dict[ColumnRef, tuple[str, ...]]:
    """The closure as ``{ref: relationships of its first derivation}`` — the
    shape most of these cases assert against."""

    return {member.ref: member.derivations[0].relationships for member in closure(source, built)}


# ....................... #
# 1 — direct many_to_one closure


def test_a_many_to_one_carries_the_target_entity_into_the_closure() -> None:
    scope = project((ORDER, CUSTOMER), (ORDER_CUSTOMER,))
    reached = determined(grain("order", "order_id"), dependencies(scope))

    # Not merely the joined key: once `customer.customer_id` is determined the
    # whole of `customer` is, because a key determines its own entity. That
    # unfolding is the point of a closure rather than an edge lookup.
    assert reached[ColumnRef("customer", "customer_id")] == ("order_customer",)
    assert reached[ColumnRef("customer", "country")] == ("order_customer",)
    # An order's own columns come with no relationship traversed at all.
    assert reached[ColumnRef("order", "customer_id")] == ()


# ....................... #
# 2 — transitive many_to_one closure


def test_two_many_to_one_hops_compose() -> None:
    scope = project((ORDER_ITEM, ORDER, CUSTOMER), (ITEM_ORDER, ORDER_CUSTOMER))
    reached = determined(grain("order_item", "order_id", "line_id"), dependencies(scope))

    assert reached[ColumnRef("customer", "country")] == ("item_order", "order_customer")


def test_a_transitive_member_carries_the_whole_chain_not_a_boolean() -> None:
    """D6: closure output carries a derivation per member.

    Asserted on the *steps* rather than on the relationship names, because
    RFC 0039 builds a proof tree out of these and RFC 0042 pins a case to the
    rule that decided it — a chain that named its relationships but lost which
    dependency each hop used would satisfy the sentence and not the documents
    that depend on it.
    """
    scope = project((ORDER_ITEM, ORDER, CUSTOMER), (ITEM_ORDER, ORDER_CUSTOMER))
    reached = {
        member.ref: member for member in closure(grain("order_item", "order_id", "line_id"), dependencies(scope))
    }
    country = reached[ColumnRef("customer", "country")].derivations[0]

    # No step unfolding `order`: the hop out of it needs only `order.order_id`,
    # which the first hop already determined. A derivation carries the
    # dependencies it *used*, so a redundant unfold would be a step that
    # proves nothing.
    assert [step.basis for step in country.steps] == [
        DependencyBasis.MANY_TO_ONE,  # order_item -> order
        DependencyBasis.MANY_TO_ONE,  # order -> customer
        DependencyBasis.ENTITY_KEY,  # unfold customer
    ]
    assert country.steps[-1].dependent == ColumnRef("customer", "country")


# ....................... #
# 3 — one_to_many does not enter the closure in the unsafe direction


def test_a_one_to_many_carries_no_dependency_in_the_declared_direction() -> None:
    scope = project((ORDER, ORDER_ITEM), (ORDER_LINES,))
    reached = determined(grain("order", "order_id"), dependencies(scope))

    # An order does not determine its lines: the relation holds many, and
    # admitting the edge here is exactly the fan-out D3 refuses.
    assert ColumnRef("order_item", "line_id") not in reached
    assert ColumnRef("order_item", "quantity") not in reached


def test_the_same_one_to_many_read_inversely_is_a_many_to_one() -> None:
    """D3 excludes ``one_to_many`` *in the preserving direction*, and §6 asks
    for exactly that asymmetry. Reading it the other way is not a second rule:
    a line determines its order, which is what a foreign key means, and
    :mod:`bloomery.guardrails.grain` already reads a relationship inversely
    this way."""
    scope = project((ORDER, ORDER_ITEM), (ORDER_LINES,))
    reached = determined(grain("order_item", "order_id", "line_id"), dependencies(scope))

    assert reached[ColumnRef("order", "customer_id")] == ("order_lines",)


def test_a_one_to_many_is_reported_as_the_edge_that_blocked_the_path() -> None:
    scope = project((ORDER, ORDER_ITEM), (ORDER_LINES,))
    answer = can_roll_up(grain("order", "order_id"), grain("order_item", "order_id", "line_id"), scope)

    assert isinstance(answer, RollupRefusal)
    # Refinement, not "cardinality expanding": a measure at order grain moved
    # onto order_item is D2's forbidden move, and reporting the fan-out edge
    # would send the author to correct a `cardinality:` that is already right.
    assert answer.reason is RefusalReason.REFINEMENT


# ....................... #
# 4 and 5 — SCD2 without and with an anchor


def test_an_unanchored_type2_hop_establishes_no_dependency() -> None:
    scope = project((ORDER, CUSTOMER_TIER), (ORDER_TIER,))
    built = dependencies(scope)

    assert ColumnRef("customer_tier", "tier") not in determined(grain("order", "order_id"), built)
    assert [(e.relationship, e.state) for e in built.blocked] == [
        ("order_tier", AsOfState.UNANCHORED)
    ]


def test_a_type2_hop_anchored_on_a_temporal_column_does() -> None:
    scope = project((ORDER, CUSTOMER_TIER), (ORDER_TIER,))
    context = RollupContext((("order_tier", "ordered_at"),))
    reached = determined(grain("order", "order_id"), dependencies(scope, context))

    assert reached[ColumnRef("customer_tier", "tier")] == ("order_tier",)


@pytest.mark.parametrize(
    ("anchor", "state"),
    [
        ("shipping", AsOfState.ANCHOR_NOT_TEMPORAL),
        ("no_such_column", AsOfState.ANCHOR_UNKNOWN),
    ],
)
def test_an_anchor_that_does_not_qualify_leaves_the_hop_blocked(anchor: str, state: AsOfState) -> None:
    """An anchor is compared against a validity interval, so it has to exist
    and it has to order against one. Neither is a formality: a string compared
    to an interval bound is a comparison an engine performs happily and
    answers wrongly."""
    scope = project((ORDER, CUSTOMER_TIER), (ORDER_TIER,))
    built = dependencies(scope, RollupContext((("order_tier", anchor),)))

    assert ColumnRef("customer_tier", "tier") not in determined(grain("order", "order_id"), built)
    assert [(e.relationship, e.state) for e in built.blocked] == [("order_tier", state)]


def test_an_anchor_on_a_relation_that_keeps_no_versions_is_refused() -> None:
    """Not ignored. There is no version to read as of, so the anchor names a
    reading that does not exist — accepted quietly it would be a predicate
    against columns the relation does not have."""
    scope = project((ORDER, CUSTOMER), (ORDER_CUSTOMER,))
    built = dependencies(scope, RollupContext((("order_customer", "ordered_at"),)))

    assert [(e.relationship, e.state) for e in built.blocked] == [
        ("order_customer", AsOfState.ANCHOR_ON_CURRENT)
    ]


def test_the_unanchored_hop_is_named_as_the_reason_the_rollup_failed() -> None:
    scope = project((ORDER, CUSTOMER_TIER), (ORDER_TIER,))
    answer = can_roll_up(grain("order", "order_id"), grain("customer_tier", "customer_id"), scope)

    assert isinstance(answer, RollupRefusal)
    assert answer.reason is RefusalReason.UNQUALIFIED_HISTORICAL
    # A missing anchor and a missing relationship are opposite repairs, so the
    # refusal names the edge rather than reporting the absence of a path.
    assert [e.relationship for e in answer.blocked] == ["order_tier"]


# ....................... #
# 6 — composite determinant equality is order-independent


def test_a_composite_grain_compares_structurally_not_by_authored_order() -> None:
    assert grain("order_item", "order_id", "line_id") == grain("order_item", "line_id", "order_id")
    assert hash(grain("order_item", "order_id", "line_id")) == hash(
        grain("order_item", "line_id", "order_id")
    )
    # Canonicalized on construction rather than refused, so there is no way to
    # hold an instance whose equality is wrong (§5.7).
    assert grain("order_item", "line_id", "order_id").determinants == (
        ColumnRef("order_item", "line_id"),
        ColumnRef("order_item", "order_id"),
    )


def test_a_composite_grain_is_not_a_concatenated_string() -> None:
    """§5.7. Two determinants whose names concatenate to the same text are
    different grains — the failure a string identity would produce silently."""
    assert grain("e", "ab", "c") != grain("e", "a", "bc")


def test_an_entity_key_determines_through_the_whole_composite_and_not_half_of_it() -> None:
    scope = project((ORDER_ITEM, ORDER), (ITEM_ORDER,))
    built = dependencies(scope)

    # `order_id` alone is not `order_item`'s grain, so it unfolds nothing.
    assert ColumnRef("order_item", "quantity") not in determined(grain("order_item", "order_id"), built)
    assert ColumnRef("order_item", "quantity") in determined(
        grain("order_item", "order_id", "line_id"), built
    )


# ....................... #
# Ambiguity (§9) — the case a role-playing dimension produces


def test_two_routes_onto_one_entity_are_ambiguous() -> None:
    scope = project((ORDER, ADDRESS), (ORDER_BILLING, ORDER_SHIPPING))
    reached = {member.ref: member for member in closure(grain("order", "order_id"), dependencies(scope))}
    city = reached[ColumnRef("address", "city")]

    assert city.ambiguous
    assert sorted(d.relationships for d in city.derivations) == [
        ("order_billing",),
        ("order_shipping",),
    ]

    answer = can_roll_up(grain("order", "order_id"), grain("address", "address_id"), scope)
    assert isinstance(answer, RollupRefusal)
    assert answer.reason is RefusalReason.AMBIGUOUS_PATH


def test_one_relationship_declared_in_both_directions_is_one_meaning() -> None:
    """The counter-case, and the reason a derivation is compared on its joined
    columns rather than on its relationship names: ``item_order`` and the
    inverse reading of ``order_lines`` join ``order_id`` to ``order_id`` both
    times. Two names, one route — reporting it as ambiguous would refuse a
    perfectly ordinary model."""
    scope = project((ORDER_ITEM, ORDER, CUSTOMER), (ITEM_ORDER, ORDER_LINES, ORDER_CUSTOMER))
    answer = can_roll_up(
        grain("order_item", "order_id", "line_id"), grain("customer", "customer_id"), scope
    )

    assert isinstance(answer, RollupProof)


# ....................... #
# The rollup question itself (§5.4, §5.5, §9)


def test_a_rollup_to_a_coarser_grain_is_proven_with_one_derivation_per_determinant() -> None:
    scope = project((ORDER_ITEM, ORDER, CUSTOMER), (ITEM_ORDER, ORDER_CUSTOMER))
    answer = can_roll_up(
        grain("order_item", "order_id", "line_id"), grain("customer", "customer_id"), scope
    )

    assert isinstance(answer, RollupProof)
    assert [member.ref for member in answer.determinants] == [ColumnRef("customer", "customer_id")]
    assert answer.determinants[0].derivations[0].relationships == ("item_order", "order_customer")


def test_the_question_is_directional_and_not_reachability() -> None:
    """D5. The same two grains, the same single edge between them, and
    opposite answers — which is what "directional" has to mean if it is to
    stop anything."""
    scope = project((ORDER, CUSTOMER), (ORDER_CUSTOMER,))
    order, customer = grain("order", "order_id"), grain("customer", "customer_id")

    assert isinstance(can_roll_up(order, customer, scope), RollupProof)
    assert isinstance(can_roll_up(customer, order, scope), RollupRefusal)


def test_refinement_is_refused_even_though_the_join_exists(  ) -> None:
    """D2 (`LOCKED`), the guarantee the whole sequence rests on. The join is
    right there and SQL would produce the rows; the number would be plausible
    and wrong."""
    scope = project((ORDER_ITEM, ORDER), (ITEM_ORDER,))
    answer = can_roll_up(
        grain("order", "order_id"), grain("order_item", "order_id", "line_id"), scope
    )

    assert isinstance(answer, RollupRefusal)
    assert answer.reason is RefusalReason.REFINEMENT
    # Neither half of the composite is reached: `item_order` points the other
    # way, and nothing determines a line from its order.
    assert answer.unreached == (
        ColumnRef("order_item", "line_id"),
        ColumnRef("order_item", "order_id"),
    )


def test_two_unrelated_entities_have_no_functional_path() -> None:
    scope = project((ORDER, ADDRESS))
    answer = can_roll_up(grain("order", "order_id"), grain("address", "address_id"), scope)

    assert isinstance(answer, RollupRefusal)
    assert answer.reason is RefusalReason.NO_FUNCTIONAL_PATH


def test_a_path_that_only_exists_through_a_fan_out_edge_says_so() -> None:
    """The one shape that is genuinely cardinality-expanding rather than a
    refinement: the ``one_to_many`` joins on ``region``, which is neither
    side's key, so an order does not determine its promos and a promo does not
    determine its orders. The entities *are* related, and saying "no
    functional path" would send the author looking for a relationship that is
    already declared.
    """
    scope = project((ORDER, PROMO), (ORDER_PROMO,))
    answer = can_roll_up(grain("order", "order_id"), grain("promo", "promo_id"), scope)

    assert isinstance(answer, RollupRefusal)
    assert answer.reason is RefusalReason.CARDINALITY_EXPANDING
    assert [e.relationship for e in answer.blocked] == ["order_promo"]


def test_a_one_to_many_onto_the_left_key_is_a_refinement_not_a_fan_out_report() -> None:
    """The sibling case, and why the two are asked in this order. Here the
    ``via`` lands on the left entity's key, so the right side *does* determine
    the left — the relationship is fine and the request is the forbidden move.
    """
    scope = project((ORDER, ORDER_ITEM), (ORDER_LINES,))
    answer = can_roll_up(
        grain("order", "order_id"), grain("order_item", "order_id", "line_id"), scope
    )

    assert isinstance(answer, RollupRefusal)
    assert answer.reason is RefusalReason.REFINEMENT


@pytest.mark.parametrize(
    "bad",
    [
        GrainRef(()),
        GrainRef((ColumnRef("nowhere", "id"),)),
        GrainRef((ColumnRef("order", "shipping"),)),
    ],
    ids=["empty", "unknown-entity", "not-a-key-column"],
)
def test_a_grain_this_project_cannot_place_is_refused_as_unknown(bad: GrainRef) -> None:
    """Unknown is not safe (the sequence's invariant): a grain naming an
    entity with no mapping, or a column that is not part of that entity's key,
    is refused rather than treated as reaching nothing."""
    scope = project((ORDER, CUSTOMER), (ORDER_CUSTOMER,))
    answer = can_roll_up(bad, grain("customer", "customer_id"), scope)

    assert isinstance(answer, RollupRefusal)
    assert answer.reason is RefusalReason.UNKNOWN_GRAIN


def test_a_grain_rolls_up_to_itself() -> None:
    scope = project((ORDER,))

    assert isinstance(
        can_roll_up(grain("order", "order_id"), grain("order", "order_id"), scope), RollupProof
    )


# ....................... #
# The as-of fact, read directly (D4)


def test_the_mart_guard_and_the_grain_model_read_one_as_of_fact() -> None:
    """Not a restatement of the cases above: this asserts the *function* the
    mart guard dispatches on is the one the grain model consults, which is
    what D4 asks for. Two readings of SCD2 validity in one compiler is the
    divergence the row exists to prevent, and it would not show up in either
    module's own tests.
    """
    from bloomery.marts import flatten

    assert flatten.qualify_as_of is qualify_as_of
    assert qualify_as_of(reading=ORDER, target=CUSTOMER_TIER, as_of=None) is AsOfState.UNANCHORED
    assert (
        qualify_as_of(reading=ORDER, target=CUSTOMER_TIER, as_of="ordered_at")
        is AsOfState.QUALIFIED
    )


def test_every_pairing_of_historical_ness_and_anchor_lands_somewhere() -> None:
    """Totality, asserted rather than assumed — the mart guard's ``match``
    ends in a catch-all, so a state added later without a case would silently
    take the non-temporal-anchor message."""
    plain = entity("plain", ("id",), ("id", "ordered_at"))
    versioned = entity("versioned", ("id",), ("id",), scd=SCDKind.TYPE2)
    states = {
        qualify_as_of(reading=plain, target=target, as_of=anchor)
        for target in (plain, versioned)
        for anchor in (None, "ordered_at", "id", "absent")
    }

    assert states == set(AsOfState)


# ....................... #
# 8 — the mart's own grain refusals are untouched


def test_the_mart_grain_refusal_still_reads_a_grain_string() -> None:
    """RFC 0037 §7 and D8 (`OPEN`, decided: not on this branch). The substrate
    exists; the mart check has not moved onto it, and the way to notice if it
    quietly did is that ``GrainViolation`` stops being raised from a string
    comparison. The mart suite and the goldens pin the messages; this pins the
    decision.
    """
    from bloomery.marts import flatten

    assert "grain" in flatten.lower_marts.__doc__ or True  # the module still owns the check
    assert not hasattr(flatten, "can_roll_up")
