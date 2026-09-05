"""A small hand-built project for the grain tests (RFC 0037 §6).

Hand-built rather than compiled from a fixture on purpose: every case §6 asks
for is a *shape* of the relationship graph — a transitive chain, a fan-out
edge, a historical target, two routes onto one entity — and the shortest way
to state a shape is to write it. Building it out of YAML would put a spec
parser between the assertion and the thing asserted.
"""

from __future__ import annotations

from bloomery.ir import (
    Cardinality,
    ColumnIR,
    EntityIR,
    Materialization,
    ProjectIR,
    RelationshipIR,
    SCDKind,
)
from bloomery.semantic import ColumnRef, GrainRef, RollupContext
from bloomery.typing import IntType, StringType, TimestampType

# ----------------------- #

#: Anything named ``*_at`` is a timestamp, so an ``as_of`` anchor on it
#: qualifies. A suffix rule rather than a list, so a test needing a *second*
#: temporal column — two anchors reading one relation at different instants —
#: gets one by naming it, instead of silently getting an int.
def _temporal(name: str) -> bool:
    return name.endswith("_at")


def column(name: str) -> ColumnIR:
    return ColumnIR(
        name=name,
        type=TimestampType() if _temporal(name) else StringType() if name.endswith("_id") else IntType(),
        canonical=None,
        unit=None,
        tax_basis=None,
        renamed_from=None,
        required=False,
    )


# ....................... #


def entity(
    name: str, key: tuple[str, ...], columns: tuple[str, ...], *, scd: SCDKind = SCDKind.TYPE1
) -> EntityIR:
    return EntityIR(
        name=name,
        grain=name,
        key=key,
        scd=scd,
        materialization=Materialization.FULL,
        partition_by=(),
        columns=tuple(column(c) for c in columns),
        sources=(),
    )


# ....................... #


def relationship(
    name: str,
    from_entity: str,
    to_entity: str,
    cardinality: Cardinality,
    via: tuple[tuple[str, str], ...],
) -> RelationshipIR:
    return RelationshipIR(
        name=name,
        from_entity=from_entity,
        to_entity=to_entity,
        via=via,
        cardinality=cardinality,
    )


# ....................... #


def project(
    entities: tuple[EntityIR, ...], relationships: tuple[RelationshipIR, ...] = ()
) -> ProjectIR:
    """Sorted by name, as :class:`~bloomery.ir.ProjectIR` promises — the grain
    model reads that promise rather than re-sorting."""

    return ProjectIR(
        entities=tuple(sorted(entities, key=lambda e: e.name)),
        relationships=tuple(sorted(relationships, key=lambda r: r.name)),
    )


# ....................... #


def grain(entity_name: str, *columns: str) -> GrainRef:
    return GrainRef(tuple(ColumnRef(entity_name, c) for c in columns))


# ....................... #
# The entities the cases below draw from.


ORDER_ITEM = entity("order_item", ("order_id", "line_id"), ("order_id", "line_id", "quantity"))
ORDER = entity(
    "order",
    ("order_id",),
    (
        "order_id",
        "customer_id",
        "billing_address_id",
        "shipping_address_id",
        "ordered_at",
        "shipped_at",
        "region",
        "shipping",
    ),
)
CUSTOMER = entity("customer", ("customer_id",), ("customer_id", "country"))
ADDRESS = entity("address", ("address_id",), ("address_id", "city"))
CUSTOMER_TIER = entity(
    "customer_tier", ("customer_id",), ("customer_id", "tier"), scd=SCDKind.TYPE2
)

#: Joined on a column that is *neither* side's key, in the multiplying
#: direction: the two entities are related and neither determines the other,
#: which is the only shape that is genuinely "cardinality-expanding" rather
#: than a refinement (a ``one_to_many`` whose ``via`` lands on the left key
#: makes the right side determine the left, and that is a refinement).
PROMO = entity("promo", ("promo_id",), ("promo_id", "region"))
ORDER_PROMO = relationship(
    "order_promo", "order", "promo", Cardinality.ONE_TO_MANY, (("region", "region"),)
)

#: A ``one_to_one``, which is read in **both** directions — the only shape
#: where one relationship can block twice, for different reasons, in one call.
#: With an anchor named for `order`, neither direction qualifies and the two
#: refusals differ: `visit` has no such column, and `visit` is not historical
#: so an anchor onto it names a version that does not exist.
SESSION = entity("session", ("session_id",), ("session_id", "channel"), scd=SCDKind.TYPE2)
VISIT = entity("visit", ("visit_id",), ("visit_id", "session_id"))
VISIT_SESSION = relationship(
    "visit_session", "visit", "session", Cardinality.ONE_TO_ONE, (("session_id", "session_id"),)
)

ITEM_ORDER = relationship(
    "item_order", "order_item", "order", Cardinality.MANY_TO_ONE, (("order_id", "order_id"),)
)
ORDER_CUSTOMER = relationship(
    "order_customer", "order", "customer", Cardinality.MANY_TO_ONE, (("customer_id", "customer_id"),)
)
ORDER_LINES = relationship(
    "order_lines", "order", "order_item", Cardinality.ONE_TO_MANY, (("order_id", "order_id"),)
)
ORDER_TIER = relationship(
    "order_tier", "order", "customer_tier", Cardinality.MANY_TO_ONE, (("customer_id", "customer_id"),)
)
#: The same join as ORDER_TIER onto the same entity. Two hops that are
#: identical but for the instant they are read at — the pair that collapses
#: into one route unless a derivation's signature carries its anchor.
ORDER_TIER_SHIPPED = relationship(
    "order_tier_shipped",
    "order",
    "customer_tier",
    Cardinality.MANY_TO_ONE,
    (("customer_id", "customer_id"),),
)
ORDER_BILLING = relationship(
    "order_billing", "order", "address", Cardinality.MANY_TO_ONE, (("billing_address_id", "address_id"),)
)
ORDER_SHIPPING = relationship(
    "order_shipping", "order", "address", Cardinality.MANY_TO_ONE, (("shipping_address_id", "address_id"),)
)


# ....................... #
# The whole corpus, for the determinism guard: every entity and every
# relationship shape at once, so one walk covers the fan-out edge, the
# historical target and the two routes onto `address`.

CORPUS = project(
    (ORDER_ITEM, ORDER, CUSTOMER, ADDRESS, CUSTOMER_TIER, PROMO, SESSION, VISIT),
    (
        ITEM_ORDER,
        ORDER_CUSTOMER,
        ORDER_LINES,
        ORDER_TIER,
        ORDER_BILLING,
        ORDER_SHIPPING,
        ORDER_PROMO,
        VISIT_SESSION,
    ),
)

#: Anchors that qualify one historical hop and fail to qualify the other in two
#: different ways — the case where one relationship contributes two blocked
#: edges, whose ordering is the thing most easily left to a hash seed.
ANCHORED = RollupContext((("order_tier", "ordered_at"), ("visit_session", "ordered_at")))

#: ``(source, target)`` pairs covering a proof, a proof onto a composite grain,
#: a refinement, an ambiguity and an unanchored historical hop — one of each
#: answer :func:`can_roll_up` returns, so a seed-dependent walk cannot hide in
#: an unexercised branch, and so that "every determinant" is asserted against a
#: target that has more than one.
QUESTIONS = (
    (grain("order_item", "order_id", "line_id"), grain("customer", "customer_id")),
    # A **composite** target that is provable, which the four below are not:
    # every other proven answer here has a single-determinant target, so an
    # assertion counting premises against determinants compares one to one and
    # holds however many were dropped. Found by sabotage — truncating a proof's
    # premises to the first changed nothing (logs/T-0020.md, D-113).
    (grain("order_item", "order_id", "line_id"), grain("order_item", "order_id", "line_id")),
    (grain("order", "order_id"), grain("order_item", "order_id", "line_id")),
    (grain("order", "order_id"), grain("address", "address_id")),
    (grain("order", "order_id"), grain("customer_tier", "customer_id")),
    (grain("order", "order_id"), grain("promo", "promo_id")),
)
