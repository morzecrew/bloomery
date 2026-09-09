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

from bloomery.errors import DuplicateNodeId, ReservedEntityName
from bloomery.ir import NODE_ID_PREFIXES
from bloomery.spec.project import key, node_keys

if TYPE_CHECKING:
    from bloomery.errors import GuardrailError
    from bloomery.ir import EntityIR, ProjectIR
    from bloomery.spec.catalog import Catalog
    from bloomery.spec.project import Project

# ----------------------- #

__all__ = [
    "check_lineage_names",
    "check_node_ids",
]

#: The id each prefix mints, and whether an entity field can *equal* one.
#:
#: Three can. ``source`` cannot, and saying otherwise in the message would be a
#: refusal that describes a collision the author can check and find is not
#: there: a bronze extraction's id carries a third segment
#: (``source.<relation>.<path>``) and a field name is a single identifier, so no
#: entity field ever reaches it. It is reserved anyway, because the rule an
#: author has to remember is "an entity is never named after a node-id prefix"
#: — a rule that held for three of four would be learned as four exceptions.
_MINTS = {
    "canonical": ("a catalog canonical field is spelled 'canonical.<name>'", True),
    "metric": ("a metric is spelled 'metric.<name>'", True),
    "source": ("a bronze extraction is spelled 'source.<relation>.<path>'", False),
    "step": ("a referenced implementation is spelled 'step.<ref>'", True),
}


def _source_path(entity: EntityIR) -> str:
    """The document that actually named this entity.

    An authored entity is `entity_model: entities.<name>`. A **step-synthesized**
    one has no such entry — its name is the last segment of the relation its
    wiring binds (RFC 0017 §5.8) — so pointing there sends the author to a
    document with nothing of that name in it, for a refusal whose entire value
    is naming the fix. ``produced_by`` is ``ref@version``, which is exactly how
    ``resolve.steps`` spells a wiring's own path.
    """

    if entity.produced_by is None:
        return f"entity_model: entities.{entity.name}"

    return f"steps: steps.{entity.produced_by}.outputs"


# ....................... #


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
            f"(RFC 0031 §5.3). Fix: rename the entity — "
            f"{', '.join(repr(name) for name in NODE_ID_PREFIXES)} are reserved as the four "
            f"node-id prefixes"
        )
        errors.append(ReservedEntityName(msg, source_path=_source_path(entity)))

    return errors


# ....................... #


def check_node_ids(project: Project, catalog: Catalog | None) -> list[GuardrailError]:
    """Refuse two nodes of one kind that mint the same lineage id (RFC 0062 §9).

    **The check is over the resulting keys, not over the ids.** What has a
    uniqueness requirement is the string a node id is built from, and reasoning
    about the inputs instead gets it wrong in both directions: comparing ids to
    each other misses a metric adopting ``id: x`` beside a metric *named* ``x``
    that adopted nothing — the collision partial adoption makes likely, and the
    one §9 does not name — while comparing ids to names refuses a project where
    a metric named ``p`` carries ``id: q`` beside one named ``q`` carrying
    ``id: r``, whose keys are ``q`` and ``r`` and do not collide at all
    (logs/T-0032.md, attempt 2).

    Per kind, because ``metric.`` and ``canonical.`` are separate namespaces: a
    metric and a canonical field sharing a key mint two different node ids and
    collide with nothing.

    Reported once per duplicated key rather than once per node, naming every
    name that reaches it — an author fixes the collision, and the collision is
    the set.
    """

    ids = node_keys(project, catalog)
    metrics = {} if project.metric_set is None else project.metric_set.metrics
    canonical = {} if catalog is None else catalog.canonical_fields
    steps = () if project.steps is None else project.steps.steps

    populations = {
        "metric": (tuple(metrics), "metrics"),
        "canonical": (tuple(canonical), "catalog"),
        "step": (tuple(wiring.ref for wiring in steps), "steps"),
    }
    errors: list[GuardrailError] = []

    for kind, (names, document) in populations.items():
        claimed: dict[str, list[str]] = {}

        for name in names:
            claimed.setdefault(key(name, ids[kind]), []).append(name)

        for node_key, sharing in sorted(claimed.items()):
            if len(sharing) < 2:
                continue

            spelled = ", ".join(repr(name) for name in sharing)
            msg = (
                f"{kind} nodes {spelled} all mint the lineage id "
                f"'{kind}.{node_key}' (RFC 0062 §9). A stable id is one identity, and two "
                f"nodes claiming it leave the graph holding one vertex where the spec "
                f"declares two — every consumer citing that id then gets whichever the "
                f"compiler kept. Fix: give each an 'id:' of its own, and never copy one "
                f"between specs"
            )
            errors.append(DuplicateNodeId(msg, source_path=document))

    return errors
