"""The lineage-namespace guard (RFC 0051 §5.2, D6–D8): entity names that would
mint node ids in another kind's namespace.

Every id on :class:`~bloomery.resolve.graph.Graph` but an entity field's is
kind-prefixed — ``metric.gross_revenue``, ``canonical.unit_price``,
``step.resolve_customers``, ``source.<relation>.<path>``. An entity field is
``<entity>.<field>`` bare, so an entity named ``metric`` with a field
``revenue`` produces exactly the id a metric named ``revenue`` produces.

Sorting was made deterministic in ``logs/T-0005.md`` D-025 by adding the node
*kind* as a tiebreak, which is why this is not a determinism bug. What it left
is two distinct nodes rendering as one string — and ``Node.name`` is published
surface (``bloomery lineage --node metric.gross_revenue`` is a documented
invocation), so the fix is to refuse the collision rather than to re-spell the
ids the whole ecosystem stores.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bloomery.errors import ReservedEntityName
from bloomery.ir import NODE_ID_PREFIXES

if TYPE_CHECKING:
    from bloomery.errors import GuardrailError
    from bloomery.ir import ProjectIR

# ----------------------- #

__all__ = [
    "check_lineage_names",
]

#: What each prefix would be mistaken for, in the message.
_MINTS = {
    "canonical": "a catalog canonical field is spelled 'canonical.<name>'",
    "metric": "a metric is spelled 'metric.<name>'",
    "source": "a bronze extraction is spelled 'source.<relation>.<path>'",
    "step": "a referenced implementation is spelled 'step.<ref>'",
}


def check_lineage_names(draft: ProjectIR) -> list[GuardrailError]:
    """Refuse an entity named after one of the four node-id prefixes.

    Over ``draft.entities`` rather than over the authored entity model: a step
    output is an entity too, named after the last segment of the relation its
    wiring binds (RFC 0017 §5.8), so a wiring writing ``silver.metric`` reaches
    the graph by a path the spec layer never sees. One quantifier over the set
    the graph is actually built from is what makes the check total (D8).

    Unconditional, not conditional on a real collision (D7). Refusing only
    when a metric of the matching name also exists would make a spec's
    validity depend on a metric someone adds later, in another file — an
    author would meet the reservation at the worst possible moment.
    """
    errors: list[GuardrailError] = []

    for entity in draft.entities:
        if entity.name not in NODE_ID_PREFIXES:
            continue
        field = entity.columns[0].name if entity.columns else "<field>"
        msg = (
            f"entity {entity.name!r} collides with the lineage node-id namespace: an entity "
            f"field is spelled '<entity>.<field>', and {_MINTS[entity.name]} — so this "
            f"entity's field {field!r} and a {entity.name} of that name are one id "
            f"(RFC 0031 §5.3). Fix: rename the entity — "
            f"{', '.join(repr(name) for name in NODE_ID_PREFIXES)} are reserved as the four "
            f"node-id prefixes"
        )
        errors.append(ReservedEntityName(msg, source_path=f"entity_model: entities.{entity.name}"))

    return errors
