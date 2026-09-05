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

from typing import TYPE_CHECKING, Final

from bloomery.ir import Cardinality, SCDKind
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
from bloomery.semantic.proof import (
    BASIS_PROVENANCE,
    BASIS_RULES,
    RULES,
    Obligation,
    Proof,
    Provenance,
    Refutation,
    SemanticFact,
    SemanticJudgement,
)

if TYPE_CHECKING:
    from bloomery.ir import EntityIR, ProjectIR, RelationshipIR

# ----------------------- #

__all__ = [
    "can_roll_up",
    "closure",
    "dependencies",
    "prove_rollup",
]

#: How many derivations a closure member keeps. Two is enough to *establish*
#: that a path is ambiguous, which is all §9 asks the vocabulary to
#: distinguish; enumerating every route is a proof-tree question and belongs
#: to RFC 0039.
#:
# ponytail: capped alternatives, lift when a consumer needs to enumerate routes
_MAX_DERIVATIONS = 2


def _entity_grain(entity: EntityIR) -> GrainRef | None:
    """The grain of an entity, or ``None`` where its declared key does not
    identify one of its rows.

    Two cases, and they fail for the same reason — nothing here identifies a
    row, so a dependency hung off it would be a claim about a row that does
    not exist:

    * **No declared key.** A grain of no determinants reads as "determined by
      the empty set", i.e. by a constant.
    * **`scd: type2`.** The relation holds one row per version per key, so the
      business key selects a *set* of versions. This is the same fact
      :class:`~bloomery.errors.HistoricalFanout` refuses on a mart's base
      entity, read here about the entity rather than about a join onto it
      (RFC 0037 §5.3, D4). A historical row is reached by an anchored hop, in
      :func:`dependencies`, and by nothing else.
    """
    if not entity.key or entity.scd is SCDKind.TYPE2:
        return None

    return grain_of(entity.name, entity.key)


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

            # `via` is always (from-side column, to-side column); the hop is
            # stated determinant-side first, whichever way it is read.
            join = tuple(
                sorted(
                    (
                        ColumnRef(reading.name, b if inverse else a),
                        ColumnRef(target.name, a if inverse else b),
                    )
                    for a, b in rel.via
                )
            )

            anchor = context.anchor(rel.name)
            state = qualify_as_of(reading=reading, target=target, as_of=anchor)
            if state is AsOfState.CURRENT:
                as_of = None
            elif state is AsOfState.QUALIFIED:
                as_of, basis = anchor, DependencyBasis.AS_OF
            else:
                blocked.append(BlockedEdge(rel.name, _blocked_by(state), state=state))
                if not admit_unqualified:
                    continue
                as_of = anchor

            # A qualified as-of hop determines the *whole* of the target row,
            # not only the joined key: the anchor picks one version, which is
            # what an as-of join is for. The target's own key cannot do that
            # for it — a `type2` relation holds one row per version per key —
            # so this is the only way its columns enter a closure at all.
            dependents = (
                tuple(ColumnRef(target.name, column.name) for column in target.columns)
                if state is AsOfState.QUALIFIED
                else tuple(ColumnRef(target.name, a if inverse else b) for a, b in rel.via)
            )

            found.extend(
                FunctionalDependency(grain, dependent, basis, via=rel.name, as_of=as_of, join=join)
                for dependent in dependents
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


#: The refusals a failed as-of pairing produces — the set `_diagnose` narrows
#: to when asking whether the anchor is what stopped this route.
_AS_OF_REASONS: Final = frozenset(
    {RefusalReason.UNQUALIFIED_HISTORICAL, RefusalReason.ANCHOR_WITHOUT_HISTORY}
)


def _blockers(
    source: GrainRef, target: GrainRef, project: ProjectIR, candidates: tuple[BlockedEdge, ...]
) -> tuple[BlockedEdge, ...]:
    """The blocked edges that are actually holding this question together.

    An edge qualifies when removing it disconnects the source's entities from
    the target's — i.e. it is the only way across. Being *in* the component is
    not enough: undirected walks make every edge in a connected component
    reachable on some walk to the target, so a component filter reports a
    fan-out edge in an unrelated corner as the blocker and sends the author to
    correct a ``cardinality:`` that has nothing to do with the question.

    Falls back to the whole candidate set when no single edge is critical —
    two parallel fan-out edges are each dispensable and jointly the reason, and
    reporting neither would be worse than reporting both.
    """
    wanted = {ref.entity for ref in target.determinants}
    critical = tuple(
        edge
        for edge in candidates
        if not wanted & _component(source, project, without=edge.relationship)
    )

    return critical or candidates


# ....................... #


def _blocked_by(state: AsOfState) -> RefusalReason:
    """Which refusal a failed as-of pairing is.

    ``ANCHOR_ON_CURRENT`` is kept apart from the other three: there the target
    keeps no versions at all, so reporting an *unqualified historical* path
    would name history that is not in the model and send the author looking
    for a `scd:` declaration that is correct as it stands. The other three are
    a historical hop that did not come back qualified, whichever way the
    anchor failed — which is what "unqualified" says.
    """

    return (
        RefusalReason.ANCHOR_WITHOUT_HISTORY
        if state is AsOfState.ANCHOR_ON_CURRENT
        else RefusalReason.UNQUALIFIED_HISTORICAL
    )


# ....................... #


def _blocked_sort_key(edge: BlockedEdge) -> tuple[str, ...]:
    """Every field of the node, because the collection it orders was
    deduplicated through a ``set``: a key that leaves one out lets two edges
    tie, and a tie under ``set`` iteration is hash-seed order (RFC 0003)."""

    return (edge.relationship, edge.reason, edge.state or "")


# ....................... #


def _dependency_sort_key(dep: FunctionalDependency) -> tuple[str, ...]:
    """Total over the dependency, for the reason above — and the closure walks
    this order, so a tie here would reach a derivation and then an artifact."""

    return (
        dep.determinant.label,
        dep.dependent.entity,
        dep.dependent.column,
        dep.basis,
        dep.via or "",
        dep.as_of or "",
        repr(dep.join),
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

    # Source only. A rollup *to* a historical grain is a real question that an
    # anchored hop answers; a rollup *from* one is not, because the declared
    # key names a set of versions and there is no single row for a value to
    # have originated at.
    historical = tuple(
        ref for ref in source.determinants if entities[ref.entity].scd is SCDKind.TYPE2
    )
    if historical:
        return RollupRefusal(source, target, RefusalReason.HISTORICAL_GRAIN, unreached=historical)

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


def _component(source: GrainRef, project: ProjectIR, *, without: str = "") -> set[str]:
    """Every entity joined to the source's, **ignoring direction and
    cardinality**.

    Undirected reachability, used for one thing only: telling "there is a
    relationship, and it does not preserve the grain" apart from "there is no
    relationship". D5 forbids implementing :func:`can_roll_up` as reachability
    because an edge existing says nothing about which way values may travel —
    it does not forbid asking whether an edge exists once the answer is
    already no.

    The component rather than a yes/no, because a refusal has to name the edge
    that stopped *this* question: the blocked set is project-wide, and a
    fan-out edge in an unrelated part of the graph reported as the blocker is
    a diagnostic that sends the author to the wrong relationship.
    """
    frontier = sorted({ref.entity for ref in source.determinants})
    seen = set(frontier)

    while frontier:
        current = frontier.pop()
        for rel in project.relationships:
            if rel.name == without:
                continue
            for near, far in ((rel.from_entity, rel.to_entity), (rel.to_entity, rel.from_entity)):
                if near == current and far not in seen:
                    seen.add(far)
                    frontier.append(far)

    return seen


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

    reverse = {member.ref for member in closure(target, admitted)}
    if all(ref in reverse for ref in source.determinants):
        return RollupRefusal(source, target, RefusalReason.REFINEMENT, unreached=unreached)

    relaxed = {
        member.ref: member
        for member in closure(source, dependencies(project, context, admit_unqualified=True))
    }
    if all(ref in relaxed for ref in target.determinants):
        # The relationships the relaxed closure actually walked — so the
        # refusal names the hops on *this* route rather than every as-of edge
        # in the project.
        route = {
            name
            for ref in target.determinants
            for derivation in relaxed[ref].derivations
            for name in derivation.relationships
        }
        on_route = tuple(
            edge
            for edge in admitted.blocked
            if edge.relationship in route and edge.reason in _AS_OF_REASONS
        )
        # Reaching here with nothing on the route would mean the relaxed
        # closure completed a path that used no relaxed edge — which the
        # strict closure would then have completed too, so it cannot. The
        # guard is what stops that contradiction becoming a refusal naming no
        # edge at all; the connectivity question below is the fallthrough.
        if on_route:
            return RollupRefusal(
                source,
                target,
                RefusalReason.UNQUALIFIED_HISTORICAL
                if any(e.reason is RefusalReason.UNQUALIFIED_HISTORICAL for e in on_route)
                else RefusalReason.ANCHOR_WITHOUT_HISTORY,
                unreached=unreached,
                blocked=on_route,
            )

    if {ref.entity for ref in target.determinants} & _component(source, project):
        return RollupRefusal(
            source,
            target,
            RefusalReason.CARDINALITY_EXPANDING,
            unreached=unreached,
            blocked=_blockers(
                source,
                target,
                project,
                tuple(
                    edge
                    for edge in admitted.blocked
                    if edge.reason is RefusalReason.CARDINALITY_EXPANDING
                ),
            ),
        )

    return RollupRefusal(source, target, RefusalReason.NO_FUNCTIONAL_PATH, unreached=unreached)


# ----------------------- #
# The same answer, as a proof (RFC 0039 §8)


#: What to do about each refusal, where the compiler knows. A reason with no
#: entry gets an empty remediation rather than a guessed one: an author acts on
#: what this says, so a wrong repair costs more than a missing one.
_REMEDIES: Final[dict[RefusalReason, str]] = {
    RefusalReason.UNKNOWN_GRAIN: (
        "name an entity this project maps, and columns that are part of its key"
    ),
    RefusalReason.NO_FUNCTIONAL_PATH: (
        "declare a relationship connecting the two entities, in the direction values travel"
    ),
    RefusalReason.CARDINALITY_EXPANDING: (
        "the route crosses a one_to_many in the direction that multiplies rows — aggregate "
        "to the coarser grain first, or ask for the measure at the grain it originates on"
    ),
    RefusalReason.UNQUALIFIED_HISTORICAL: (
        "supply an as_of: anchor naming a column of the reading entity that orders against "
        "the version interval"
    ),
    RefusalReason.ANCHOR_WITHOUT_HISTORY: (
        "drop the as_of: anchor — the relation keeps no versions, so there is nothing to "
        "read it as of"
    ),
    RefusalReason.HISTORICAL_GRAIN: (
        "values do not originate at a set of versions — take the source grain from the "
        "entity that owns the measure, not from the scd: type2 relation"
    ),
    RefusalReason.AMBIGUOUS_PATH: (
        "two routes reach the target by different joins, so the same column name has two "
        "meanings — name the relationship the request means"
    ),
    RefusalReason.REFINEMENT: (
        "the target grain is finer than the source, so the value would be duplicated rather "
        "than aggregated — request it at the source grain or coarser"
    ),
}


def _dependency_proof(step: FunctionalDependency) -> Proof:
    """One hop, as the rule that admitted it and the fact it rests on."""

    basis = step.basis.value
    source = (
        f"relationship:{step.via}" if step.via is not None else f"entity:{step.determinant.label}"
    )

    return Proof(
        rule=BASIS_RULES[basis],
        conclusion=SemanticJudgement(
            "Determines",
            (("by", basis), ("from", step.determinant.label), ("to", str(step.dependent))),
        ),
        facts=(
            SemanticFact(
                source=source,
                provenance=BASIS_PROVENANCE[basis],
                statement=RULES[BASIS_RULES[basis]].summary,
            ),
        ),
    )


# ....................... #


def _determined_proof(determined: Determined) -> Proof:
    """One determinant of the target, and the chain that reached it.

    The *first* derivation, not all of them: a member reached by two different
    joins is :attr:`Determined.ambiguous` and ``can_roll_up`` has already
    refused it, so anything arriving here has one reading. Derivations are
    canonically ordered upstream, so "first" is deterministic (RFC 0003).

    Three shapes, and the middle one is why this is not a loop over steps:

    * **No steps** — the member is a determinant of the origin grain, an axiom.
      It is emitted rather than dropped, because a proof that silently omits
      its own starting points reads as though it proved more than it did.
    * **One step** — the hop *is* the reaching. Wrapping it would repeat the
      hop's own rule one line higher and claim a composition that composed
      nothing.
    * **Several** — R005, whose premises are the hops.
    """

    derivation = determined.derivations[0]

    if not derivation.steps:
        return Proof(
            rule="R007",
            conclusion=SemanticJudgement("Reaches", (("column", str(determined.ref)),)),
            facts=(
                SemanticFact(
                    source=f"grain:{determined.ref.entity}",
                    provenance=Provenance.DECLARED,
                    statement=RULES["R007"].summary,
                ),
            ),
        )

    if len(derivation.steps) == 1:
        return _dependency_proof(derivation.steps[0])

    return Proof(
        rule="R005",
        conclusion=SemanticJudgement("Reaches", (("column", str(determined.ref)),)),
        premises=tuple(_dependency_proof(step) for step in derivation.steps),
    )


# ....................... #


def prove_rollup(
    source: GrainRef,
    target: GrainRef,
    project: ProjectIR,
    context: RollupContext = NO_CONTEXT,
) -> Proof | Refutation:
    """:func:`can_roll_up`'s answer, expressed in RFC 0039's vocabulary.

    Expressed rather than replaced (D3, `LOCKED`): ``can_roll_up`` stays the
    decision and this is a second reading of it, so the two cannot disagree
    about whether a rollup is safe — there is only one place that decides.
    Deleting the narrower answer in favour of this one is a later change, and
    only once something has compared them.

    A determinant of the source grain is an axiom — determined by nothing, and
    needing no argument — and is emitted as one rather than dropped, because a
    proof that silently omits its own starting points reads as though it proved
    more than it did.
    """

    answer = can_roll_up(source, target, project, context)
    judgement = SemanticJudgement("SafeRollup", (("from", source.label), ("to", target.label)))

    if isinstance(answer, RollupRefusal):
        # §6 pairs each requirement with what was found instead, and a blocked
        # edge is exactly that: the route exists and something about it is
        # wrong. Where none is recorded the refusal is about the whole question
        # — a refinement, an unknown grain — and there is no "instead" to name,
        # so the obligation carries the requirement alone rather than an empty
        # line pretending to be an answer.
        obligations = (
            tuple(
                Obligation(
                    required=f"reach {target.label} from {source.label}",
                    found=f"{edge.relationship} is {edge.reason.value}"
                    + (f" ({edge.state})" if edge.state else ""),
                )
                for edge in answer.blocked
            )
            or tuple(
                Obligation(required=f"reach {column} from {source.label}")
                for column in answer.unreached
            )
            or (Obligation(required=f"roll up {source.label} to {target.label}"),)
        )

        return Refutation(
            reason=answer.reason.value,
            judgement=judgement,
            obligations=obligations,
            remediation=_REMEDIES.get(answer.reason, ""),
            rejected=tuple(
                SemanticFact(
                    source=f"relationship:{edge.relationship}",
                    provenance=Provenance.UNKNOWN,
                    statement=f"blocked: {edge.reason.value}",
                )
                for edge in answer.blocked
            ),
        )

    return Proof(
        rule="R006",
        conclusion=judgement,
        premises=tuple(_determined_proof(member) for member in answer.determinants),
    )
