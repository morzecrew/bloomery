"""The dependency set, its closure, and the rollup question
(RFC 0037 §5.2, §5.4, §5.8).

Three functions, each a pure operation over :class:`~bloomery.ir.ProjectIR`:

``dependencies``
    every functional dependency the project *justifies*, and every edge it
    refused with the reason. Nothing is inferred — D3 (`LOCKED`) closes the
    list of admissible bases, and the refused half is what lets a later
    refusal name the hop that stopped it.
``closure``
    what a grain determines, each member carrying the derivations that reach
    it rather than a boolean (D6).
``can_roll_up``
    whether values originating at one grain may be aggregated to another.
    Directional, and not graph reachability (D5) — the two grains are asked in
    a fixed order and the answer changes when they swap, which is the whole
    of D2: a coarser measure is never moved to a finer grain because a join
    exists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bloomery.ir import Cardinality
from bloomery.semantic.historical import AsOfState, qualify_as_of
from bloomery.semantic.nodes import (
    NO_CONTEXT,
    BlockedEdge,
    ColumnRef,
    DependencyBasis,
    DependencySet,
    Derivation,
    Determined,
    FunctionalDependency,
    GrainRef,
    RefusalReason,
    RollupContext,
    RollupProof,
    RollupRefusal,
    grain_of,
)

if TYPE_CHECKING:
    from bloomery.ir import EntityIR, ProjectIR, RelationshipIR

# ----------------------- #

__all__ = [
    "can_roll_up",
    "closure",
    "dependencies",
]

#: How many derivations a closure member keeps. Two is enough to *establish*
#: that a path is ambiguous, which is all §9 asks the vocabulary to
#: distinguish; enumerating every route is a proof-tree question and belongs
#: to RFC 0039.
#:
# ponytail: capped alternatives, lift when a consumer needs to enumerate routes
_MAX_DERIVATIONS = 2


def _entity_grain(entity: EntityIR) -> GrainRef | None:
    """An entity with no declared key determines nothing and is determined by
    nothing — it contributes no dependencies rather than a grain of no
    determinants, which would read as "determined by the empty set", i.e. by a
    constant."""

    return grain_of(entity.name, entity.key) if entity.key else None


# ....................... #


def _admitted_directions(
    rel: RelationshipIR,
) -> tuple[tuple[bool, DependencyBasis], ...]:
    """Which readings of a declared relationship carry a dependency, as
    ``(inverse, basis)`` pairs.

    ``many_to_one`` in its declared direction; ``one_to_one`` both ways, being
    symmetric; ``one_to_many`` **only inversely**, where it is a
    ``many_to_one`` — the many side determines the one side. D3 excludes
    ``one_to_many`` in the *preserving* direction, which is the declared one,
    and §6 test 3 asks for exactly that asymmetry.
    """
    match rel.cardinality:
        case Cardinality.MANY_TO_ONE:
            return ((False, DependencyBasis.MANY_TO_ONE),)
        case Cardinality.ONE_TO_ONE:
            return ((False, DependencyBasis.ONE_TO_ONE), (True, DependencyBasis.ONE_TO_ONE))
        case Cardinality.ONE_TO_MANY:
            return ((True, DependencyBasis.MANY_TO_ONE),)


# ....................... #


def dependencies(
    project: ProjectIR,
    context: RollupContext = NO_CONTEXT,
    *,
    admit_unqualified: bool = False,
) -> DependencySet:
    """Every dependency ``project`` justifies under ``context``.

    ``admit_unqualified`` is **diagnosis only**: :func:`can_roll_up` sets it to
    ask "would this have worked but for the missing anchor", so a refusal can
    distinguish that from no path at all (§9). It does not belong in a proof —
    a dependency admitted under it is not one the project justifies.
    """
    entities = {entity.name: entity for entity in project.entities}
    found: list[FunctionalDependency] = []
    blocked: list[BlockedEdge] = []

    for entity in project.entities:
        grain = _entity_grain(entity)
        if grain is None:
            continue
        found.extend(
            FunctionalDependency(
                grain, ColumnRef(entity.name, column.name), DependencyBasis.ENTITY_KEY
            )
            for column in entity.columns
        )

    for rel in project.relationships:
        from_entity = entities.get(rel.from_entity)
        to_entity = entities.get(rel.to_entity)
        if from_entity is None or to_entity is None:
            blocked.append(BlockedEdge(rel.name, RefusalReason.UNKNOWN_GRAIN))
            continue

        if rel.cardinality is Cardinality.ONE_TO_MANY:
            # The declared direction of a one_to_many is the fan-out. Recorded
            # rather than merely skipped: a refusal that cannot name the edge
            # sends the author looking for a missing relationship that is
            # right there.
            blocked.append(BlockedEdge(rel.name, RefusalReason.CARDINALITY_EXPANDING))

        for inverse, basis in _admitted_directions(rel):
            reading, target = (to_entity, from_entity) if inverse else (from_entity, to_entity)
            grain = _entity_grain(reading)
            if grain is None:
                continue

            anchor = context.anchor(rel.name)
            state = qualify_as_of(reading=reading, target=target, as_of=anchor)
            if state is AsOfState.CURRENT:
                as_of = None
            elif state is AsOfState.QUALIFIED:
                as_of = anchor
            else:
                blocked.append(
                    BlockedEdge(rel.name, RefusalReason.UNQUALIFIED_HISTORICAL, state=state)
                )
                if not admit_unqualified:
                    continue
                as_of = anchor

            found.extend(
                FunctionalDependency(
                    grain,
                    # `via` is always (from-side column, to-side column); the
                    # dependent is the column on whichever side is the target.
                    ColumnRef(target.name, from_column if inverse else to_column),
                    basis,
                    via=rel.name,
                    as_of=as_of,
                    through=ColumnRef(reading.name, to_column if inverse else from_column),
                )
                for from_column, to_column in rel.via
            )

    return DependencySet(
        dependencies=tuple(sorted(found, key=_dependency_sort_key)),
        # Sorted on the node's *whole* value, `state` included. Without it two
        # edges of one relationship that block for different reasons — a
        # one_to_one is read both ways, and the anchor that qualifies one
        # direction names no column on the other — tie on the key and come out
        # in `set` iteration order, which is hash-seed order (RFC 0003).
        blocked=tuple(sorted(set(blocked), key=_blocked_sort_key)),
    )


# ....................... #


def _blocked_sort_key(edge: BlockedEdge) -> tuple[str, ...]:
    return (edge.relationship, edge.reason, edge.state or "")


# ....................... #


def _dependency_sort_key(dep: FunctionalDependency) -> tuple[str, ...]:
    return (
        dep.determinant.label,
        dep.dependent.entity,
        dep.dependent.column,
        dep.basis,
        dep.via or "",
        dep.as_of or "",
        str(dep.through or ""),
    )


# ....................... #


def _merge(existing: tuple[Derivation, ...], candidate: Derivation) -> tuple[Derivation, ...]:
    """Add ``candidate`` unless an equivalent route is already held.

    Equivalent means *the same joined columns in the same order* — the
    derivation's signature, not its relationship names. Collapsing on the
    signature is what stops one relationship declared in both directions
    reading as two meanings, and what stops a composite determinant reporting
    ambiguity it does not have.
    """
    if any(held.signature == candidate.signature for held in existing):
        return existing

    merged = sorted([*existing, candidate], key=lambda d: d.signature)

    return tuple(merged[:_MAX_DERIVATIONS])


# ....................... #


def _compose(parts: tuple[Derivation, ...], dep: FunctionalDependency) -> Derivation:
    """One derivation for ``dep`` firing on determinants reached by ``parts``.

    The proof is a DAG; ``steps`` is a topological linearization of it, in
    fire order and deduplicated. RFC 0039 is where a tree-shaped proof lives —
    what this owes RFC 0037 D6 is *a* derivation per member, never a boolean.
    """
    steps: list[FunctionalDependency] = []
    for part in parts:
        steps.extend(step for step in part.steps if step not in steps)
    if dep not in steps:
        steps.append(dep)

    return Derivation(tuple(steps))


# ....................... #


def closure(grain: GrainRef, deps: DependencySet) -> tuple[Determined, ...]:
    """What ``grain`` determines, sorted by reference, each with its
    derivations (RFC 0037 §5.8).

    The origin's own determinants are members with an empty derivation: they
    are the grain, and a grain is not argued for. Everything else carries the
    dependencies composed to reach it.
    """
    reached: dict[ColumnRef, tuple[Derivation, ...]] = {
        ref: (Derivation(),) for ref in grain.determinants
    }

    changed = True
    while changed:
        changed = False
        for dep in deps.dependencies:
            parts = tuple(reached.get(ref) for ref in dep.determinant.determinants)
            if any(part is None for part in parts):
                continue

            # One candidate from each determinant's first route, plus a second
            # taken from the first determinant that has one. Bounded by
            # `_MAX_DERIVATIONS` at the member, so this terminates.
            primary = tuple(part[0] for part in parts if part is not None)
            candidates = [_compose(primary, dep)]
            for index, part in enumerate(parts):
                if part is not None and len(part) > 1:
                    alternative = (*primary[:index], part[1], *primary[index + 1 :])
                    candidates.append(_compose(alternative, dep))
                    break

            held = reached.get(dep.dependent, ())
            updated = held
            for candidate in candidates:
                updated = _merge(updated, candidate)
            if updated != held:
                reached[dep.dependent] = updated
                changed = True

    return tuple(Determined(ref, reached[ref]) for ref in sorted(reached))


# ....................... #


def _unknown(grain: GrainRef, entities: dict[str, EntityIR]) -> tuple[ColumnRef, ...]:
    """Determinants that name no entity of this project, or a column that is
    not part of that entity's key.

    A grain of *no* determinants is not this function's case — nothing
    identifies its rows, which :func:`can_roll_up` refuses before asking.
    """

    return tuple(
        ref
        for ref in grain.determinants
        if ref.entity not in entities or ref.column not in entities[ref.entity].key
    )


# ....................... #


def can_roll_up(
    source: GrainRef,
    target: GrainRef,
    project: ProjectIR,
    context: RollupContext = NO_CONTEXT,
) -> RollupProof | RollupRefusal:
    """Whether values originating at ``source`` may be aggregated to
    ``target`` (RFC 0037 §5.4).

    Directional by construction: the question is whether ``source`` *
    determines* every determinant of ``target``, so swapping the arguments
    asks a different question and usually gets a different answer. It is not
    reachability over the relationship graph — an edge between two entities
    says nothing about which way values may travel along it (D5).

    Refuses rather than approximating, and the reason distinguishes the
    repairs (§9): a refinement is not a missing relationship, and an
    unanchored historical hop is not a missing one either.
    """
    entities = {entity.name: entity for entity in project.entities}

    if not source.determinants or not target.determinants:
        return RollupRefusal(source, target, RefusalReason.UNKNOWN_GRAIN)

    unknown = _unknown(source, entities) + _unknown(target, entities)
    if unknown:
        return RollupRefusal(
            source, target, RefusalReason.UNKNOWN_GRAIN, unreached=tuple(sorted(set(unknown)))
        )

    admitted = dependencies(project, context)
    determined = {member.ref: member for member in closure(source, admitted)}

    unreached = tuple(ref for ref in target.determinants if ref not in determined)
    if not unreached:
        members = tuple(determined[ref] for ref in target.determinants)
        if any(member.ambiguous for member in members):
            return RollupRefusal(source, target, RefusalReason.AMBIGUOUS_PATH)

        return RollupProof(source, target, members)

    return _diagnose(source, target, project, context, admitted, unreached)


# ....................... #


def _connected(source: GrainRef, target: GrainRef, project: ProjectIR) -> bool:
    """Whether the two grains' entities are joined at all, **ignoring
    direction and cardinality**.

    Undirected reachability, used for one thing only: telling "there is a
    relationship, and it does not preserve the grain" apart from "there is no
    relationship". D5 forbids implementing :func:`can_roll_up` as reachability
    because an edge existing says nothing about which way values may travel —
    it does not forbid asking whether an edge exists once the answer is
    already no.
    """
    frontier = sorted({ref.entity for ref in source.determinants})
    seen = set(frontier)
    wanted = {ref.entity for ref in target.determinants}

    while frontier:
        current = frontier.pop()
        if current in wanted:
            return True
        for rel in project.relationships:
            for near, far in ((rel.from_entity, rel.to_entity), (rel.to_entity, rel.from_entity)):
                if near == current and far not in seen:
                    seen.add(far)
                    frontier.append(far)

    # Everything added to `seen` is also pushed onto `frontier` and so is
    # checked above before this line can be reached.
    return False


# ....................... #


def _diagnose(
    source: GrainRef,
    target: GrainRef,
    project: ProjectIR,
    context: RollupContext,
    admitted: DependencySet,
    unreached: tuple[ColumnRef, ...],
) -> RollupRefusal:
    """Why the closure fell short (§9).

    Asked in this order, and the order is the answer as much as the questions
    are. **Refinement first:** it is also a path through a fan-out edge, and
    reporting the fan-out would send the author to correct a ``cardinality:``
    that is already right — the same distinction
    :class:`~bloomery.errors.HistoricalFanout` keeps from
    :class:`~bloomery.errors.FanoutRisk`. **Then the unanchored hop,** whose
    repair is neither a relationship nor a remodelling. **Then connectivity,**
    which is the weakest claim of the three and so the last resort.
    """

    def edges(reason: RefusalReason) -> tuple[BlockedEdge, ...]:
        return tuple(edge for edge in admitted.blocked if edge.reason is reason)

    reverse = {member.ref for member in closure(target, admitted)}
    if all(ref in reverse for ref in source.determinants):
        return RollupRefusal(source, target, RefusalReason.REFINEMENT, unreached=unreached)

    relaxed = closure(source, dependencies(project, context, admit_unqualified=True))
    if all(ref in {member.ref for member in relaxed} for ref in target.determinants):
        return RollupRefusal(
            source,
            target,
            RefusalReason.UNQUALIFIED_HISTORICAL,
            unreached=unreached,
            blocked=edges(RefusalReason.UNQUALIFIED_HISTORICAL),
        )

    if _connected(source, target, project):
        return RollupRefusal(
            source,
            target,
            RefusalReason.CARDINALITY_EXPANDING,
            unreached=unreached,
            blocked=edges(RefusalReason.CARDINALITY_EXPANDING),
        )

    return RollupRefusal(source, target, RefusalReason.NO_FUNCTIONAL_PATH, unreached=unreached)
