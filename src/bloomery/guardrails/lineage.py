"""The lineage-namespace guard (S-0059/the-node-id-collision-refused-at-its-cause, S-0059/D-6–S-0059/D-8): entity names that would
mint node ids in another kind's namespace.

Every id on :class:`~bloomery.resolve.graph.Graph` but an entity field's is
kind-prefixed — ``metric.gross_revenue``, ``canonical.unit_price``,
``step.resolve_customers``, ``source.<relation>.<path>``,
``mart.order_items``, ``exposure.weekly_revenue_review``. An entity field is
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
    from bloomery.ir import EntityIR, ProjectIR

# ----------------------- #

__all__ = [
    "check_lineage_names",
]

#: The id each prefix mints, and whether an entity field can *equal* one.
#:
#: All but one can. ``source`` cannot, and saying otherwise in the message
#: would be a refusal that describes a collision the author can check and find
#: is not there: a bronze extraction's id carries a third segment
#: (``source.<relation>.<path>``) and a field name is a single identifier, so no
#: entity field ever reaches it. It is reserved anyway, because the rule an
#: author has to remember is "an entity is never named after a node-id prefix"
#: — a rule that held for all but one would be learned as a list of exceptions.
#:
#: Every member of :data:`~bloomery.ir.NODE_ID_PREFIXES` has an entry, and
#: ``test_every_prefix_is_described`` pins that: a prefix added without one
#: would raise :class:`KeyError` inside a guardrail, on a spec whose only
#: offence is an entity name.
_MINTS = {
    "canonical": ("a catalog canonical field is spelled 'canonical.<name>'", True),
    "exposure": ("a declared consumer is spelled 'exposure.<name>'", True),
    "mart": ("a gold relation is spelled 'mart.<name>'", True),
    "metric": ("a metric is spelled 'metric.<name>'", True),
    "source": ("a bronze extraction is spelled 'source.<relation>.<path>'", False),
    "step": ("a referenced implementation is spelled 'step.<ref>'", True),
}


def _source_path(entity: EntityIR) -> str:
    """The document that actually named this entity.

    An authored entity is `entity_model: entities.<name>`. A **step-synthesized**
    one has no such entry — its name is the last segment of the relation its
    wiring binds (S-0034/emission-and-the-dag) — so pointing there sends the author to a
    document with nothing of that name in it, for a refusal whose entire value
    is naming the fix. ``produced_by`` is ``ref@version``, which is exactly how
    ``resolve.steps`` spells a wiring's own path.
    """

    if entity.produced_by is None:
        return f"entity_model: entities.{entity.name}"

    return f"steps: steps.{entity.produced_by}.outputs"


# ....................... #


def _alias_collisions(draft: ProjectIR) -> list[GuardrailError]:
    """Refuse a local entity named after an upstream alias (S-0002/D-6).

    An imported node's id carries a project component built from the alias —
    ``metric.platform.gross_revenue`` — so the alias is a segment of the id
    namespace exactly as a kind prefix is, and an entity named ``platform`` is
    a second owner of that segment.

    No field of such an entity ever *equals* an imported id: the imported one
    carries three segments and ``<entity>.<field>`` carries two. The message
    says so, on the ``source`` precedent above — a refusal describing a
    collision the author can check and find absent is worse than no message —
    and the alias is reserved anyway, for the reason ``source`` is.

    Over the aliases this compile actually **bound**, because an alias the
    caller did not supply has no imported node behind it and is refused as an
    ``UnknownUpstream`` anyway; a namespace refusal beside that one would name
    a fix that is not the fix.
    """

    errors: list[GuardrailError] = []
    aliases = {upstream.alias for upstream in draft.upstream}

    for entity in draft.entities:
        if entity.name not in aliases:
            continue
        field = entity.columns[0].name if entity.columns else "<field>"
        msg = (
            f"entity {entity.name!r} collides with the lineage node-id namespace of the "
            f"upstream imported under that alias: an imported node is spelled "
            f"'<kind>.{entity.name}.<name>' and an entity field is spelled "
            f"'<entity>.<field>', so this entity's field {field!r} never equals an imported "
            f"id — the alias is a segment of that namespace all the same (S-0002/D-6). Fix: "
            f"rename the entity, or import that upstream under another alias"
        )
        errors.append(ReservedEntityName(msg, source_path=_source_path(entity)))

    return errors


# ....................... #


def check_lineage_names(draft: ProjectIR) -> list[GuardrailError]:
    """Refuse an entity named after one of the node-id prefixes.

    Over ``draft.entities`` rather than over the authored entity model: a step
    output is an entity too, named after the last segment of the relation its
    wiring binds (S-0034/emission-and-the-dag), so a wiring writing ``silver.metric`` reaches
    the graph by a path the spec layer never sees. One quantifier over the set
    the graph is actually built from is what makes the check total (D8).

    Unconditional, not conditional on a real collision (D7). Refusing only
    when a metric of the matching name also exists would make a spec's
    validity depend on a metric someone adds later, in another file — an
    author would meet the reservation at the worst possible moment.

    **An upstream alias is reserved on the same terms** (S-0002 (§5.4),
    S-0002/D-6), for the whole document's aliases rather than per field, which
    is ``source``'s reasoning one input over: the rule worth remembering is
    "an entity is never named after an upstream", and one that held only where
    a field name happened to match would be learned as a coincidence.
    """
    errors: list[GuardrailError] = _alias_collisions(draft)

    for entity in draft.entities:
        if entity.name not in NODE_ID_PREFIXES:
            continue
        spelling, collides = _MINTS[entity.name]
        field = entity.columns[0].name if entity.columns else "<field>"
        detail = (
            f"so this entity's field {field!r} and a {entity.name} of that name are one id"
            if collides
            else f"so every field of this entity mints an id in the {entity.name} namespace"
        )
        msg = (
            f"entity {entity.name!r} collides with the lineage node-id namespace: an entity "
            f"field is spelled '<entity>.<field>', and {spelling} — {detail} "
            f"(S-0048/every-label-is-handled-and-the-vocabulary-is-closed-here). Fix: rename the entity — "
            f"{', '.join(repr(name) for name in NODE_ID_PREFIXES)} are reserved as node-id "
            f"prefixes"
        )
        errors.append(ReservedEntityName(msg, source_path=_source_path(entity)))

    return errors
